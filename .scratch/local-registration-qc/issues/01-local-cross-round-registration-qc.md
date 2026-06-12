# Add QC outputs to the local cross-round registration step

Status: needs-triage

## Problem

The **local** cross-round registration step (`DataRegistration`, driven by
`qi2lab-preprocess`) emits no QC metric or QC images. There is currently no way to
inspect, after a preprocess run, whether each round registered well against the
reference fiducial round — a misregistration is only discovered downstream when
decoding fails or yields poor results.

This is in contrast to the **global** registration step
(`qi2lab-globalregister` / `global_register.py`), which already writes QC outputs:
a fiducial max-projection TIFF and a z-depth PNG (turbo colormap, one pixel per
max-intensity Z) at the fused root path (see commit `d47a713`).

## Desired outcome

The local cross-round registration step should emit QC artifacts so a misregistered
round is visible without running the full pipeline:

- A per-round QC metric capturing registration quality against the reference round.
- QC image(s) — e.g. before/after overlays or max-projection comparisons of the
  fiducial channel — so misregistration is visually obvious.

## Notes / context

- Related code: [DataRegistration.py](../../../src/merfish3danalysis/DataRegistration.py),
  [preprocess.py](../../../src/merfish3danalysis/cli/qi2lab_microscopes/preprocess.py)
- Reference implementation to mirror for output style/placement:
  [global_register.py](../../../src/merfish3danalysis/cli/qi2lab_microscopes/global_register.py)
  (commit `d47a713`).
- The dataset `/home/hblanc01/Data/20250718_DH_Merfish_3x2bit` has a known round-2
  DAPI fiducial labelling bug that breaks cross-round registration — a useful failing
  case for validating that the QC surfaces bad registration.
