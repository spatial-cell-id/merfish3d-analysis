# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

GPU-accelerated post-processing for 2D/3D iterative barcoded FISH (MERFISH) data. Linux + Nvidia GPU (CUDA 12.8) only due to RAPIDS.AI dependencies. The package processes raw microscope acquisitions into decoded transcripts (gene identities + spatial coordinates).

## Commands

```bash
# Install (editable)
pip install -e .

# Run post-install CUDA library setup
setup-merfish3d

# Lint and format
ruff check --fix
ruff format

# Run tests (integration test against embedded simulation data)
python -m pytest tests/test_simulation_example_pipeline.py -q

# Run exhaustive regression suite
python -m pytest tests/test_simulation_example_pipeline.py -q --run-simulation-exhaustive

# Build docs
mkdocs build --clean
mkdocs serve
```

## Architecture

### Data Flow

```
Raw TIFF/NDTiff → [create_datastore] → qi2labDataStore (zarr)
                                              ↓
                                    [preprocess] → DataRegistration
                                              ↓
                                    [pixeldecode] → PixelDecoder
                                              ↓
                                    Transcripts (CSV/Parquet)
```

### Core Classes

**`qi2labDataStore`** ([src/merfish3danalysis/qi2labDataStore.py](src/merfish3danalysis/qi2labDataStore.py)) — Central hub for all data I/O. All other components read/write through this object. Wraps zarr storage with accessors for metadata, calibrations, codebook, PSFs, and per-tile images. Tracks pipeline state via JSON sidecars.

**`PixelDecoder`** ([src/merfish3danalysis/PixelDecoder.py](src/merfish3danalysis/PixelDecoder.py)) — GPU-accelerated transcript decoding. Normalizes the MERFISH codebook (L2 per codeword), applies a two-threshold MERFISH caller plane-by-plane, and extracts transcript features. Supports multi-GPU via one process per GPU (`decode_tiles_worker`).

**`DataRegistration`** ([src/merfish3danalysis/DataRegistration.py](src/merfish3danalysis/DataRegistration.py)) — Cross-round registration and optional deconvolution. Uses fiducial rounds to establish transforms, GPU-accelerated pixel warping (`warpfield`), and Richardson-Lucy Gradient Consensus deconvolution (`utils/rlgc.py`). Optional U-FISH CNN-based feature detection improves registration.

### CLI Entry Points

Two families of pipelines under `src/merfish3danalysis/cli/`:

- **`qi2lab_microscopes/`** — Real microscope data: `qi2lab-datastore`, `qi2lab-preprocess`, `qi2lab-decode`, `qi2lab-globalregister`, `qi2lab-segment`
- **`statphysbio_simulation/`** — Simulation validation: `sim-convert`, `sim-datastore`, `sim-preprocess`, `sim-decode`, `sim-f1score`

### Key Design Patterns

- **Lazy imports**: `__init__.py` uses `__getattr__` to defer heavy GPU library imports until needed.
- **Multi-GPU parallelism**: Workers are spawned processes (not threads) using `mp.set_start_method("spawn")` for clean CUDA context isolation.
- **GPU stack**: cupy, cucim, cuvs, cudnn — all operations are GPU-first with no CPU fallback.
- **Second conda environment**: `multiview-stitcher` is installed into a separate `merfish3d-stitcher` environment (numpy compatibility workaround); `setup-merfish3d` handles this automatically.

### Code Style

- Ruff: line length 88, target Python 3.12+, NumPy docstring convention.
- Type annotations required (ANN rules enabled; `Any` allowed via ANN401 ignore).
- Tests exempt from docstring, security, and annotation checks.
- Use `X | None` for optional types — not `Optional[X]` (Python 3.12+ target).
- Path/input validation: explicit `raise FileNotFoundError` / `raise ValueError` — never bare `assert` (fails silently under `-O`).
- CLI functions: suppress B008 with `# noqa: B008` inline on `typer.Argument`/`typer.Option` lines that trigger it — not a global config ignore.
- CLI modules: no import-time side effects (`mp.set_start_method`, env vars, etc.) — perform setup inside the command function.
- Extract helper functions from large CLI commands; keep entry points readable with `# ---` section headers.

## Agent skills

### Issue tracker

Issues and PRDs live as markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, default strings, written as a `Status:` line on each issue file. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
