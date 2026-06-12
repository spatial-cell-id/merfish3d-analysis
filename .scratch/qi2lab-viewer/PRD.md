# qi2lab-viewer: multi-round fiducials, 3D fused, stitch-QC, window split

Status: ready-for-human

> Source: distilled from a planning + grilling session (2026-06-12). Domain terms are in
> the repo-root [CONTEXT.md](../../CONTEXT.md). Run `/to-issues` against this PRD to break
> it into per-phase tickets under `.scratch/qi2lab-viewer/issues/`.

## Context

`qi2lab-viewer` ([src/merfish3danalysis/viewer.py](../../src/merfish3danalysis/viewer.py),
entry point `merfish3danalysis.cli.qi2lab_microscopes.viewer:main`) is the **view-only**
ndv/PyQt GUI for inspecting a `qi2labDataStore`. It loads existing pipeline outputs and
never writes. Four limitations the user wants fixed, plus the single-window UI being
physically cramped.

Today's limits:
1. **Fiducial inspection locked to round 1** — both `load_image_channels`
   ([viewer.py:441-462](../../src/merfish3danalysis/viewer.py#L441-L462)) and the duplicate
   `_load_image_channels_with_progress`
   ([viewer.py:1799-1841](../../src/merfish3danalysis/viewer.py#L1799-L1841)) hardcode
   `round_ids[0]`. The datastore loaders already accept any round.
2. **Fused global view forced to 2D max-projection**
   ([viewer.py:1159](../../src/merfish3danalysis/viewer.py#L1159)).
3. **No stitching / global-register QC** (no per-tile coloring).
4. **Single cramped window** — controls + image in one `QHBoxLayout`.

Facts settled during planning (durable versions in CONTEXT.md):
- `load_local_corrected_image` / `load_local_registered_image` accept **any** round
  ([qi2labDataStore.py:3199](../../src/merfish3danalysis/qi2labDataStore.py#L3199),
  [3745](../../src/merfish3danalysis/qi2labDataStore.py#L3745)).
- **Round1 registered == corrected** (round1 is the reference; no warp —
  [DataRegistration.py:258](../../src/merfish3danalysis/DataRegistration.py#L258)). Other
  rounds have a registered image **only if** registration ran with
  `save_all_fiducial_registered`
  ([DataRegistration.py:424](../../src/merfish3danalysis/DataRegistration.py#L424));
  otherwise the loader returns `None`.
- Per-tile global transform = phase-correlation **translation** (default
  `multiview_stitcher.phase_correlation_registration`) ∘ stored **stage affine**
  `affine_zyx_px`. Stage affine is **identity for IGFL** (`np.eye(4)`,
  [igfl/create_datastore.py:543](../../src/merfish3danalysis/cli/igfl_microscopes/create_datastore.py#L543))
  but a **camera↔stage flip/scale for qi2lab**
  ([qi2lab/create_datastore.py:314-322](../../src/merfish3danalysis/cli/qi2lab_microscopes/create_datastore.py#L314-L322)).
  ⇒ final transform is a **pure translation only when the stage affine is identity**.
- Pure helpers are covered by
  [tests/test_qi2lab_viewer.py](../../tests/test_qi2lab_viewer.py) against
  `FakeDatastore`/`SyntheticDatastore`. **That contract stays green.**

Outcome: pick any round and toggle corrected/registered, scroll the fused volume in 3D,
run a magenta/green checkerboard stitch-QC overlay, all in a layout where the image has
its own resizable window.

## Sequencing — refactor first, then features

Each phase ends with `ruff check --fix && ruff format` and
`pytest tests/test_qi2lab_viewer.py -q` green.

---

## Phase 0 — De-duplicate channel loading (prerequisite)

Collapse the two near-identical loaders into one. Add a keyword-only
`progress_cb: Callable[[int, str], None] | None = None` to the pure `load_image_channels`
(and thread it through `_append_channel`); make the Qt
`_load_image_channels_with_progress` a thin wrapper passing `self._advance_progress`.
Existing positional test calls keep working. One code path to extend in Phase 2.

Files: viewer.py. Verify: existing tests green.

---

## Phase 1 — Window split (display gets its own resizable window)

Justification is **physical cramping**, not LUT tuning. Do **not** add any
LUT-grouping/collapsing UI.

- Introduce a no-Qt `ViewerController` owning `datastore`, `datastore_path`,
  `gene_to_bits`, `channel_labels`, exposing `build_local_stack(...)` /
  `build_global_stack(...)` that just compose existing pure functions.
- Split `DatastoreViewerWindow` into:
  - `ControlWindow(QMainWindow)` — all current controls + status/progress.
  - `DisplayWindow(QMainWindow)` — owns the ndv `ArrayViewer` and `_reset_array_viewer`;
    exposes `show_stack(xarray, labels)`.
  - Control holds a ref to Display; Display button → controller builds stack →
    `display_window.show_stack(...)`. Both created in `run_viewer`, tiled; closing either
    quits.
- **LUT cleanup (consolidation only):** move the private-`_lut_controllers` access and the
  triple `singleShot(50/250ms)` retry into one `DisplayWindow._apply_lut_names`, called
  once after `show_stack` (keep a single short retry for ndv lazy view-build).

Files: viewer.py (restructure nested classes; module-top pure functions untouched).
Verify: launch `qi2lab-viewer <datastore>`; two windows; local tile renders with named,
gray-fiducial LUTs.

---

## Phase 2 — Multi-round fiducial selection (corrected + registered)

- Replace the fixed "Fiducial round 1" group with a **round multi-select list** (checkable
  item per `datastore.round_ids`) + the existing `corrected` / `registered/decon`
  checkboxes.
- **Default selection:** round1 with `registered` checked (preserves today's behavior);
  multi-round is opt-in.
- Unified loader iterates selected rounds × selected fiducial sources, one channel per
  `(round, source)`, label `f"{tile}:{round_id}:fiducial {source}"`. `_append_channel`
  already no-ops on `None`, so registered rounds with no image are skipped.
- **Round1 redundancy:** when round1 is selected, suppress the redundant second channel —
  registered round1 == corrected round1; emit a single round1 fiducial channel rather than
  two identical ones.
- Update `selected_image_channel_count`
  ([viewer.py:503](../../src/merfish3danalysis/viewer.py#L503)) to take `rounds: list[str]`
  instead of `has_fiducial_round: bool`.
- Status line notes any registered rounds skipped for lack of an image.

Tests: extend test_qi2lab_viewer.py — ≥2-round `SyntheticDatastore`; multi-round corrected
→ N channels; non-round1 registered with no image skipped; round1 corrected+registered →
one channel; updated `selected_image_channel_count` signature.

---

## Phase 3 — Full 3D fused volume

- `load_global_image_channels`
  ([viewer.py:1133](../../src/merfish3danalysis/viewer.py#L1133)) gets
  `project_z: bool = True`; when `False`, keep full `fused_zyx` instead of the
  max-projection at [viewer.py:1159](../../src/merfish3danalysis/viewer.py#L1159).
- Overlays already broadcast across z via `_match_global_overlay_shape`
  ([viewer.py:1103](../../src/merfish3danalysis/viewer.py#L1103)), so global
  segmentation/decoded/cell overlays still align in 3D.
- Add **"fused: full 3D volume"** checkbox (default unchecked = current 2D max-proj).
  `display_global_selection` passes `project_z = not checkbox.isChecked()`. Existing
  `current_index={"z_um": .../2}` gives the z-slider.

Tests: `load_global_image_channels(..., project_z=False)` keeps source z-depth; overlays
match shape.

---

## Phase 4 — Stitch-QC: 2-color checkerboard overlay

Goal: eyeball global-register/stitch quality. **Translation-only paste** (no affine
resample). Magenta + green by grid parity; good overlap blends to neutral, misalignment
shows a colored fringe at the seam.

- **Availability guard:** for each tile, read `load_local_stage_position_zyx_um(tile,
  round1)` → `affine_zyx_px`; if **any** tile's 2×2 (y,x) linear block is non-identity
  (qi2lab case), **disable the stitch-QC checkbox** with a message
  ("stitch QC needs translation-only placement; this datastore has a camera↔stage
  affine"). Enabled only when all stage affines are identity (IGFL case).
- **Grid parity (pure, testable):** no `(row,col)` is stored — derive it. Collect tile
  stage `y`/`x`; bin each axis onto grid lines (rank distinct rounded positions) → per-tile
  `(row, col)`; `color = (row + col) % 2`. Assumes an axis-aligned regular mosaic.
- **Builder `build_stitch_qc_stack(datastore, downsample=...)` (pure):**
  1. Canvas grid from `load_global_fidicual_image` (origin/spacing/shape) — same reference
     as other global overlays.
  2. For each tile: load round1 fiducial (`load_local_registered_image(round=round1)`,
     fall back to corrected — same data for round1), downsample, paste at the translation
     offset from `load_global_coord_xforms_um(tile)` origin/spacing.
  3. Accumulate into a single **RGB composite** `(3, z|1, y, x)`: parity-0 tiles add to the
     magenta channels (R+B), parity-1 tiles to green (G). One ndv channel total — no
     per-tile LUT explosion, scales to any tile count.
- Add **"stitch QC (checkerboard)"** checkbox in the global section; when checked,
  `display_global_selection` builds the QC stack instead of the fused loader. Default
  downsample (≈4–8×) + tile-count note in status.

Tests: ≥2-tile `SyntheticDatastore` with known `load_global_coord_xforms_um` and stage
positions — assert parity derivation, that a tile lands at the expected canvas offset, that
overlapping well-aligned tiles produce neutral RGB, and that a non-identity stage affine
disables the mode.

---

## Verification (end to end)

1. `ruff check --fix && ruff format`
2. `python -m pytest tests/test_qi2lab_viewer.py -q` — all green (old + new).
3. `python -c "from merfish3danalysis.cli.qi2lab_microscopes.viewer import main"` (verify
   import per project practice).
4. Manual on a real **IGFL** datastore (≥2 rounds, ≥2 tiles, fused image):
   - `qi2lab-viewer /path` → control + display windows.
   - Select 2 rounds × corrected → 2 channels named; non-round1 registered → status notes
     skip if absent.
   - Global "full 3D volume" → z-slider scrolls fused stack.
   - Global "stitch QC" → magenta/green checkerboard; overlaps neutral; seams readable.
   - (Sanity) open a qi2lab datastore → stitch-QC checkbox disabled with message.

## Risks / notes

- ndv private-API coupling (`_lut_controllers`) is pre-existing; Phase 1 consolidates, does
  not remove it (no ndv public API for it).
- Grid-parity derivation assumes a regular axis-aligned mosaic; irregular layouts could
  mis-bin (acceptable for standard acquisitions; lives in the pure layer for easy fix).
- Stitch-QC translation paste is exact only for identity stage affines — enforced by the
  availability guard, so no silently-wrong picture.
- No `Co-Authored-By` trailer on commits (project rule).
