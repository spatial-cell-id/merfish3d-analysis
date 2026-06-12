# Context: qi2lab-viewer

The view-only ndv/PyQt GUI for inspecting a `qi2labDataStore`. Read-only: it loads and
displays existing pipeline outputs, it never writes to the datastore.

## Glossary

**Control window** — the Qt window holding all selection controls (open datastore, tile
picker, round/source selection, bit & gene lists, overlay toggles, Display button,
status/progress). Distinct from the Display window.

**Display window** — the Qt window holding the ndv `ArrayViewer` and its per-channel LUT
controls. Receives a built channel stack from the Control window and renders it. Splitting
the two exists to give the image its own resizable window (relieve physical cramping), not
to change how LUTs are tuned.

**Channel stack** — a `(c, z, y, x)` array plus per-channel labels (`ChannelStack`), the
unit handed to ndv. A global channel stack (`GlobalChannelStack`) additionally carries
micron origin/spacing for placement on the fused global canvas.

**Local view** — display of one selected tile's own pixel data (fiducial rounds, readout
bits, per-tile overlays).

**Global / fused view** — display on the fused global canvas: the single fused fiducial
volume, or globally-placed overlays (decoded spots, cell outlines) in micron coordinates.

**Corrected fiducial** — a round's fiducial image after gain/offset correction, before
cross-round registration. Exists for every round. Used to inspect raw cross-round drift.

**Registered fiducial** — a round's fiducial warped into round1's common frame (round1's
is itself the reference). Written per-round only when registration ran with
`save_all_fiducial_registered`; otherwise only round1 exists. A per-round registered
fiducial is the alignment-QC view: all rounds should overlap once warped. When absent for
a round, the loader returns `None` and the viewer skips that channel.

For **round1 specifically, registered and corrected fiducial are the same data** — round1
is the reference, so no warp is applied (registered round1 is corrected round1, optionally
fiducial-deconvolved but spatially identical). Offering both for round1 is redundant.

**Global tile transform** — per-tile placement on the fused canvas, saved by
`save_global_coord_xforms_um` as `(affine_zyx_um, origin_zyx_um, spacing_zyx_um)`. It is
the phase-correlation translation (default `multiview_stitcher`
`phase_correlation_registration`) composed with the tile's stored stage affine
(`affine_zyx_px`). The stage affine is identity for IGFL datastores (`np.eye(4)`) but a
camera↔stage flip/scale for qi2lab datastores. So the final transform is a **pure
translation only when the stage affine is identity**.

**Stitch-QC view** — global view that pastes each tile's downsampled round1 fiducial onto
the fused canvas by translation offset, one colour per tile, to eyeball overlap
agreement (global-register quality). Translation-only paste is exact only when every
tile's stage-affine linear block is identity; the mode is disabled (with a message) when
any tile has a non-identity linear block, since a paste would misplace it.
