# merfish3d-analysis — Technical Summary

> This document describes the `merfish3d-analysis` package:
> its scientific purpose, architecture, data
> formats, processing pipeline, and external dependencies. Prioritizes technical
> accuracy over brevity.

---

## 1. What the Project Does and Its Scientific Purpose

`merfish3d-analysis` is a **GPU-accelerated post-processing package for 2D and
3D iterative barcoded FISH data**, primarily **MERFISH** (Multiplexed
Error-Robust Fluorescence In Situ Hybridization). It is developed by the QI2lab
(Quantitative Imaging and Inference Lab, Douglas Shepherd, Arizona State
University).

### The scientific problem

MERFISH is a spatial transcriptomics method that measures the identity and
spatial location of RNA molecules inside intact tissue. Each gene is assigned a
binary **codeword** (e.g. a 16-bit error-correcting code). Across multiple
imaging **rounds**, fluorescent readout probes are hybridized, imaged, and
stripped, so each RNA species "blinks" on/off in a pattern matching its
codeword. By decoding which pixels followed which on/off pattern across rounds,
the software recovers **gene identity + 3D spatial coordinates** for individual
transcripts.

The package takes **raw microscope acquisitions** (TIFF/NDTiff image stacks plus
metadata) and produces **decoded transcripts** (gene IDs with global spatial
coordinates) and optionally **cell segmentations** with per-cell expression
matrices. It is the computational back end that turns terabytes of raw
fluorescence imagery into an analysis-ready spatial gene-expression dataset.

### Associated publication

Preprint: *"GPU-accelerated, self-optimizing processing for 3D multiplexed
iterative RNA-FISH experiments"* (bioRxiv 2025.10.10.681751v1).

### Platform constraints

- **Linux only, NVIDIA GPU only.** Hard requirement, driven by the RAPIDS.AI
  (cuCIM, cuVS) and CuPy dependency stack.
- Targets **CUDA 12.8**.
- **Python ≥ 3.12** (classifiers list 3.12 and 3.13).
- GPU-first design: the core image processing, deconvolution, registration, and
  decoding all run on the GPU with **no CPU fallback**.
- Package version is `0.10.0` and the README explicitly warns it is *under active
  development; expect breaking changes*. License: BSD.

---

## 2. Top-Level Repository Layout

```
merfish3d-analysis/
├── pyproject.toml              # hatchling build, deps, ruff config, CLI entry points
├── README.md                  # install + proseg segmentation instructions
├── CLAUDE.md                  # repo guidance (commands, architecture)
├── mkdocs.yml                 # docs site config
├── src/merfish3danalysis/
│   ├── __init__.py            # lazy submodule import machinery
│   ├── qi2labDataStore.py     # ~4730 lines — central data I/O hub
│   ├── PixelDecoder.py        # ~3890 lines — GPU transcript decoding
│   ├── DataRegistration.py    # ~1270 lines — cross-round registration + decon
│   ├── viewer.py              # ~2070 lines — ndv/PyQt datastore viewer (qi2lab-viewer entry point is a thin wrapper under cli/qi2lab_microscopes/viewer.py)
│   ├── setup_merfish3d.py     # post-install CUDA/env bootstrap (CLI: setup-merfish3d)
│   ├── setup_colab.py         # Google Colab bootstrap
│   ├── utils/
│   │   ├── rlgc.py            # Richardson-Lucy Gradient Consensus deconvolution
│   │   ├── registration.py   # warpfield / SimpleITK registration helpers
│   │   ├── imageprocessing.py# hot-pixel, shading, downsampling, ImageJ bridge
│   │   ├── dataio.py         # metadata, zarr, sparse-mtx, TSV I/O
│   │   └── darkfield.py      # PSF generation, dehazing, dark-channel sectioning
│   └── cli/
│       ├── qi2lab_microscopes/   # real-data pipeline (qi2lab-* commands)
│       ├── igfl_microscopes/     # IGFL Abberior-confocal ingest + 3D segment (igfl-datastore, igfl-segment)
│       └── statphysbio_simulation/ # simulation validation (sim-* commands)
├── examples/                  # zhuang_lab, human_olfactory_bulb, Colab notebook
├── docs/                      # mkdocs source (workflow, datastore, reference)
└── tests/                     # simulation integration test + embedded sim data
```

---

## 3. Core Components and Modules

The architecture centers on **one data-access object** plus **three processing
classes**, supported by a `utils` layer and two CLI families.

### 3.1 `qi2labDataStore` (`qi2labDataStore.py`)

**The central hub for all data I/O.** Every other component reads and writes
through this object — it is the single source of truth for the experiment. It
wraps a Zarr-based on-disk store and exposes:

- **Metadata as Python properties** (getters/setters that persist to disk):
  `microscope_type` (`"2D"`/`"3D"`), `camera_model`, `num_rounds`, `num_bits`,
  `num_tiles`, `channels_in_data`, `tile_overlap`, `binning`, `e_per_ADU`
  (camera gain), `na` (numerical aperture), `ri` (immersion refractive index),
  `voxel_size_zyx_um`, `experiment_order`, `codebook`.
- **Calibration data**: `noise_map` (hot-pixel/darkfield), `channel_shading_maps`
  (flat-field), `channel_psfs` (point spread functions, one per channel).
- **Normalization vectors** used by decoding: `global_normalization_vector`,
  `global_background_vector`, `iterative_normalization_vector`,
  `iterative_background_vector`.
- **ID accessors**: `tile_ids`, `round_ids`, `bit_ids`.
- **Pipeline state tracking** via `datastore_state` — a JSON dict with boolean
  flags such as `Calibrations`, `Corrected`, `LocalRegistered`,
  `GlobalRegistered`, `Fused`, etc. Each pipeline stage flips its flag when
  complete; this is how the pipeline knows what has already been done.
- **Per-tile image read/write helpers**: e.g. `initialize_tile`,
  `save_local_corrected_image`, `save_local_stage_position_zyx_um`,
  `save_local_wavelengths_um`, `load_global_fidicual_image`,
  `save_global_cellpose_segmentation_image`.

**Indexing convention (critical):** tiles/rounds/bits are **0-indexed in the
Python API** but stored on disk as **1-based, zero-padded strings**
(`round001`, `bit001`, `tile0000`).

**Required metadata to build a store:** effective xy pixel size + z step,
objective NA, immersion RI, per-tile global stage zyx position, camera
orientation relative to stage, stage motion direction relative to camera view,
which bits are collected each round, acquisition order (`(channel,z)` vs
`(z,channel)`), and per-channel excitation/emission wavelengths. **Each tile is
assumed to have a fiducial channel** — the software will not work without one.

**N-channel readout (v0.10):** the readout-bit selection logic was generalized
from hard-coded 2-vs-3-channel branching to **arbitrary N readout channels**
(channel 0 is the fiducial, channels `1..N` are readouts). This lets the store
support new microscope systems with different channel counts, such as IGFL.

### 3.2 `DataRegistration` (`DataRegistration.py`)

**Cross-round registration and optional deconvolution**, performed per tile in
**local coordinates** (aligning every round back to round 1 of the same tile).

Key behavior:
- Uses the **fiducial channel** (e.g. fluorescent beads or DAPI) present in each
  round to compute the geometric transform that aligns round *N* to round 1.
- Two-stage registration: **rigid** (via SimpleITK) followed by optional
  **deformable / optical-flow** warping. Pixel warping is GPU-accelerated via
  the **`warpfield`** library (QI2lab fork).
- Optional **Richardson-Lucy Gradient Consensus (RLGC) deconvolution** of
  fiducial and/or readout images before registration (`utils/rlgc.py`). The
  decon API was simplified (v0.10): a single `chunked_rlgc()` entry point handles
  both 2D and 3D without separate code paths.
- Optional **U-FISH** (CNN-based spot/feature detection) applied to readout bits
  to improve registration and provide candidate spot localizations. The U-FISH
  model is selectable (`ufish_model`: aliases `simfish`/`smfish` (**default**),
  `merfish`, `seqfish`, `deepspot`, `exseq` — all backed by the bundled v1.0.1
  fine-tuned `.onnx` weights — or a local `.onnx`/`.pth` / HuggingFace weights
  path). Only those six aliases are bundled; any other model (e.g. the
  `dnafish`/`rca`/`deepblink`/`suntag` entries in the README sweep table) must be
  supplied as a local `.onnx`/`.pth`/HF path and is not shipped with the package.
- Multi-GPU support: spawns one worker process per GPU
  (`_apply_fiducial_on_gpu`, `_apply_bits_on_gpu`).
- Entry points: `register_all_tiles()`, `register_one_tile(tile_id)`,
  `apply_registration_to_one_tile(tile_id)`. Tracks completion via
  `_is_tile_complete` so reruns can skip finished tiles.

### 3.3 `PixelDecoder` (`PixelDecoder.py`)

**GPU-accelerated MERFISH transcript decoding** — the scientific heart of the
package. Workflow inside the class:

1. **Codebook handling** (`_load_codebook`, `_normalize_codebook`): loads the
   codebook, drops 1-bit codewords, and **L2-normalizes each codeword**.
   Derives the geometric **two-threshold caller** parameters
   (`_pixel_assignment_threshold`, `_transcript_distance_threshold`) from the
   median number of "on" bits per codeword.
2. **Normalization vectors** — estimates per-bit background and scaling either:
   - **Global** (`_global_normalization_vectors`): percentile-based estimates
     (low/high percentile cuts, hot-pixel rejection) sampled across random
     tiles; or
   - **Iterative** (`_iterative_normalization_vectors`): refined by repeated
     decoding (`optimize_normalization_by_decoding`, default 20 random tiles ×
     5 iterations). This is the "self-optimizing" aspect from the paper title.
3. **Per-plane decoding** (`_decode_pixels`): loads bit images, applies a
   low-pass filter, scales/clips/normalizes pixel traces, computes cosine-style
   distances to normalized codewords, applies the **two-threshold MERFISH
   caller plane-by-plane**, and gates pixels by the `magnitude_threshold` range
   (pixels outside `[min, max]` are rejected here, during decoding).
4. **Feature extraction** (`_extract_barcodes`): groups contiguous same-barcode
   pixels into transcript features; enforces a `minimum_pixels` / `maximum_pixels`
   range (defaults `3` / `500`).
5. **False-positive filtering** (`optimize_filtering`): three selectable
   methods — `blank_fraction` (default, targets a gross misidentification rate
   using the fraction of decoded "blank"/control codewords); `blank_bit_enrichment`
   (binned blank-barcode thresholding — 4D histograms of bit penalties over
   intensity / voxel-count / vector-distance / bit-penalty bins, per
   PNAS 10.1073/pnas.1912459116 — for codebooks with few blanks that are enriched
   in certain bits); and `lr` (logistic-regression FDR control).
6. **Overlap cleanup**: removes duplicate transcripts in tile-overlap regions
   (`_remove_duplicates_in_tile_overlap`) and within a tile
   (`_remove_duplicates_within_tile`, union-find based).
7. **Cell assignment** (`_assign_cells`): assigns transcripts to segmentation
   ROIs, and preps data for re-segmentation.

Public orchestration methods: `decode_one_tile`, `decode_all_tiles`,
`optimize_normalization_by_decoding`, `optimize_filtering`. Multi-GPU via
`decode_tiles_worker` (one spawned process per GPU).

**Decoding defaults** (sampling-aware, set in the decode CLI):
- `minimum_pixels_per_RNA`: 7 (2D) / 28 (3D), with the test matrix using 28 for
  0.315 µm axial spacing and 7 for 1.0/1.5 µm.
- 3D magnitude threshold: `(0.9, 10.0)`.
- 2D magnitude threshold keyed by axial sampling relative to the 0.315 µm
  Nyquist reference: ~3× → 0.7, ~5× → 0.2.

### 3.4 `viewer.py` (new in v0.10)

A **view-only GUI** for inspecting a `qi2labDataStore`, built on the **`ndv`**
N-dimensional array viewer + **PyQt** (via `qtpy`); launched with the
`qi2lab-viewer` CLI. The main `Qi2labViewer` class (entry point `run_viewer()`)
uses **`xarray`** to attach micron-coordinate axes (`z_um`, `y_um`, `x_um`) and
can display per-tile images (corrected / registered / feature-predictor),
decoded-spot overlays, Cellpose cell outlines, and the **global fused fiducial
image after decoding**. `napari` remains installed (and is still used to
determine camera/stage orientation), but the viewer itself is ndv-based.

**Current implementation limits:** fiducial inspection is locked to **round 1**
(`round_ids[0]`), and the global fused view renders a **2D max projection** of
the fused volume, not the full 3D stack. Multi-round fiducial browsing, a
full-3D fused view, and stitch-QC overlays are planned
(`.scratch/qi2lab-viewer/PRD.md`) but not yet implemented.

### 3.5 `utils/` modules

- **`rlgc.py`** — Richardson-Lucy Gradient Consensus deconvolution (Manton/York
  method, Biggs-Andrews acceleration). CuPy + custom `ElementwiseKernel` CUDA
  kernels, FFT-based convolution with padding/caching. Public API simplified in
  v0.10 to `rlgc()` (core), `chunked_rlgc()` (lateral tiling, `crop_yx=2048`
  default; axial chunking dropped — `crop_z` must stay `None`), and
  `clear_rlgc_caches()`. Uses `ryomen` for slicing large volumes into GPU-sized
  blocks.
- **`registration.py`** — `compute_warpfield` (deformable field via warpfield),
  `compute_rigid_transform` and `apply_transform` (SimpleITK). GPU-accelerated
  anisotropic-downsampled registration.
- **`imageprocessing.py`** — camera correction (`replace_hot_pixels`),
  flat-field (`estimate_shading`), anisotropic downsampling (Numba JIT),
  and an **ImageJ/Fiji bridge** (`initialize_imagej`,
  `subtract_background_imagej`) via pyimagej for rolling-ball background
  subtraction.
- **`dataio.py`** — metadata/config readers (`read_metadatafile`,
  `read_config_file`), zarr reading (`return_data_zarr`), sparse matrix output
  (`write_sparse_mtx` for cell × gene count matrices), and TSV writers.
- **`darkfield.py`** — theoretical PSF generation (`psf_generator`, Bessel-based),
  high/low-pass Gaussian filters, and dehazing / dark-channel optical sectioning
  (`dehaze_fast2`, `dark_sectioning`, `guided_filter`).

---

## 4. Data Inputs, Outputs, and File Formats

### 4.1 Inputs

- **Raw images**: TIFF / NDTiff stacks, shape conceptually `[n_channels, nz, ny,
  nx]` per tile/round. Read via `tifffile` / `ndstorage`.
- **Codebook** (`codebook.csv`/`.tsv`): maps gene → binary codeword. First
  column is `gene_id` (entries starting with `blank` are negative-control
  codewords); remaining columns are `bit01..bitNN` with 0/1 values.
- **Experiment order** (`exp_order.csv`/`.tsv`): maps imaging round → which
  readout bits were collected that round. First column is the 1-based round
  number; remaining columns are readout bit indices in acquisition order.
- **Microscope/experiment metadata**: voxel size, NA, RI, stage positions,
  camera orientation, channel wavelengths, gain (`e_per_ADU`), binning.
- **Calibration inputs**: noise/darkfield map, shading maps, per-channel PSFs
  (experimental or theoretical).

### 4.2 The `qi2labDataStore` on-disk format

The store is a directory tree (layout **Version 0.6**) using **OME-NGFF v0.5**
(OME-Zarr) images for arrays and **Parquet** for tables:

```
qi2labdatastore/
├── datastore_state.json              # pipeline-stage boolean flags
├── calibrations/
│   ├── attributes.json               # codebook, exp_order, channels, voxel size, psf_manifest
│   ├── noise_map/                    # OME-NGFF v0.5 image
│   ├── shading_maps/                 # OME-NGFF v0.5 image
│   └── psf_data/psf_000.ome.zarr/ …  # one image per channel
├── fiducial/tile0000/round001/
│   ├── corrected_data.ome.zarr/
│   ├── registered_decon_data.ome.zarr/
│   └── opticalflow_xform_px.ome.zarr/  # dense 4D displacement field
├── readouts/tile0000/bit001/
│   ├── corrected_data.ome.zarr/
│   ├── registered_decon_data.ome.zarr/
│   └── registered_feature_predictor_data.ome.zarr/   # U-FISH output
├── feature_predictor_localizations/tile0000/bit001.parquet
├── fused/fused.zarr/
│   ├── fused_fiducial_iso_zyx.ome.zarr/
│   └── fused_all_channels_zyx.ome.zarr/   # optional
├── segmentation/cellpose/
│   ├── cellpose.zarr/masks_fiducial_iso_zyx.ome.zarr/
│   └── imagej_rois/global_coords_rois.zip
├── decoded/
│   ├── tile0000_decoded_features.parquet
│   └── all_tiles_filtered_decoded_features.parquet
└── mtx_output/                       # cell × gene sparse count matrices
```

**Format conventions:**
- Image arrays are read/written through **yaozarrs** using the **TensorStore**
  interface (the docs/datastore note this; the codebase also uses `zarr` and
  `numcodecs` directly in places).
- Per-image metadata (correction flags, wavelengths, `bit_linker`,
  `round_linker`, `psf_idx`, transforms) is written under the spec-compliant
  `zarr.json -> attributes` key (zarr v3 rejects unknown top-level keys, which
  broke napari and other standard readers; the read path stays
  backward-compatible with legacy `extra_attributes` stores). OME metadata
  stores only voxel `scale` and tile `translation`.
- Non-image folders carry an `attributes.json`.

### 4.3 Outputs

- **Decoded transcripts**: Parquet (and CSV.gz for proseg), one per tile plus a
  filtered `all_tiles_filtered_decoded_features` table. Columns include
  `gene_id`, global coordinates (`global_x`, `global_y`, `global_z`),
  `tile_idx`, and `cell_id`.
- **Fused images**: OME-Zarr fused fiducial volume (+ optional all-channel
  fused volume) in a global isotropic coordinate system.
- **Segmentation**: Cellpose masks (OME-Zarr) and ImageJ ROI zips; optional
  proseg `spatialdata` zarr, GeoJSON cell polygons, and `.mtx.gz` count
  matrices.
- **Cell × gene count matrices**: sparse Matrix Market (`.mtx`) via
  `write_sparse_mtx`.

---

## 5. Core Processing Pipeline / Workflow

The end-to-end flow (per `docs/workflow.md` and the CLI entry points):

```
Raw TIFF/NDTiff
   │  [create_datastore]  — camera correction, geometric local→global transform,
   │                        ingest fiducial + MERFISH data, stage positions
   ▼
qi2labDataStore (Zarr)
   │  [preprocess / DataRegistration]  — per tile, local coordinates:
   │     • fiducial: decon → rigid → deformable registration
   │     • readout:  decon → U-FISH feature prediction → tile warping
   ▼
Locally registered tiles
   │  [global_register]  — multiview-stitcher fuses fiducial round into one
   │                        global coordinate system; optimizes tile positions
   ▼
Fused global fiducial image
   │  [segment_fiducial]  — Cellpose (SAM) 2D segmentation on max-projected
   │                        fused fiducial; ROIs warped to global coords
   ▼
2D cell segmentations
   │  [pixeldecode / PixelDecoder]  — global/iterative normalization →
   │     pixel decoding (two-threshold caller) → blank-fraction/LR filtering →
   │     overlap cleanup → cell assignment
   ▼
Decoded, cell-assigned transcripts (Parquet)
   │  [3D segmentation]  — proseg re-segments cells from decoded RNA
   ▼
Updated RNA→cell assignments + count matrices
```

### Stage-by-stage notes

1. **Create datastore** (`qi2lab-datastore`): ingests raw data, applies camera
   gain/offset/hot-pixel correction, records the local→global geometric
   transform, separates fiducial vs MERFISH (readout) data, and stores global
   tile positions. Sets `Calibrations` and `Corrected` state flags. A
   `qi2lab-datastore-skipz` variant produces z-subsampled stores.
2. **Preprocess / local register** (`qi2lab-preprocess`): runs
   `DataRegistration.register_all_tiles()`. Deconvolves (optional), registers
   each round's fiducial back to round 1, applies the resulting warp to readout
   bits, and runs U-FISH feature prediction. Sets `LocalRegistered`.
3. **Global register + fuse** (`qi2lab-globalregister`): uses
   **multiview-stitcher** to register and fuse the first fiducial round across
   tiles into a global, XY-downsampled / Z-max-projected isotropic image. Writes
   a max-projection OME-TIFF for interactive Cellpose parameter tuning. Sets
   `GlobalRegistered` + `Fused`.
4. **Segment fiducial** (`qi2lab-segment`): runs **Cellpose (SAM)** on the fused
   fiducial max projection to get 2D cell masks; converts to ImageJ ROIs and
   warps them into global coordinates. *Cellpose parameters must be tuned
   manually in the GUI first.*
5. **Pixel decode** (`qi2lab-decode`): runs `PixelDecoder`. Optionally optimizes
   normalization by iterative decoding (default), decodes all tiles, filters
   false positives, cleans overlaps, and assigns transcripts to the 2D cells.
6. **3D re-segmentation** (external, via README instructions): **proseg** (2D or
   3D) consumes the decoded `decoded_features.csv.gz` — with explicit column
   mappings (`gene_id`, `global_x/y/z`, `tile_idx`, `cell_id`) — to refine cell
   boundaries from transcript density and emit final count matrices (`.mtx.gz`),
   GeoJSON cell polygons, transcript-metadata CSV, and a `spatialdata` zarr.

### IGFL Abberior-confocal pipeline (`igfl-*` commands)

A second real-data CLI family ingests IGFL Abberior confocal data, which differs
from the qi2lab path in two ways:

- **`igfl-datastore`** (`cli/igfl_microscopes/create_datastore.py`): ingests
  **Huygens-deconvolved OME-TIFF** stacks — the data is already deconvolved, so
  RLGC deconvolution is left OFF in the downstream preprocess step — and parses a
  **semicolon-delimited** codebook. It exposes `ri_sample` (sample refractive
  index, default 1.33) and `deconv_scale` (rescales the float deconvolution
  output into `uint16` without clipping signal).
- **`igfl-segment`** (`cli/igfl_microscopes/segment_fiducial.py`): runs **full 3D
  Cellpose** (`do_3D=True`) on the volume and saves masks at isotropic
  `downsampling=[1, 1, 1]`. This contrasts with the qi2lab `qi2lab-segment` path,
  which segments a **2D max projection** at `downsampling=[1, 3.5, 3.5]`.

Other stages (preprocess / local registration, global register, decode) reuse the
shared `DataRegistration` and `PixelDecoder` machinery.

### Simulation validation pipeline (`sim-*` commands)

A parallel CLI family validates the whole pipeline against ground truth:
`sim-convert` (simulation → fake acquisition) → `sim-datastore` →
`sim-preprocess` → `sim-decode` → `sim-f1score`. The F1 scorer
(`calculate_F1.py`) does greedy nearest-neighbor matching within a radius
between decoded and ground-truth spots, enforcing same-gene and one-to-one
constraints, to compute precision/recall/F1.

---

## 6. Notable Dependencies and External Tools

### 6.1 GPU / scientific stack (installed by `setup-merfish3d`)

The package itself declares only `typer` as a runtime dependency in
`pyproject.toml`; the heavy GPU stack is installed by the **`setup-merfish3d`**
post-install command, which uses conda/mamba/micromamba plus pip:

- **RAPIDS.AI / CUDA (conda, `-c rapidsai -c conda-forge -c nvidia`):**
  `cucim`, `cuvs`, `cupy`, `cudnn`, CUDA 12.8 runtime, OpenJDK.
- **pip packages:** `tqdm`, `ryomen` (volume slicing), `onnx` /
  `onnxruntime-gpu`, `napari[pyqt6]`, `ndv[vispy,pyqt]` + `qtpy` (the new viewer),
  `xarray` (coordinate-aware arrays for the viewer), `cellpose[gui]`,
  **`ufish`** (QI2lab fork — CNN spot detection),
  **`warpfield`** (QI2lab fork — GPU deformable warping),
  **`basicpy`** (QI2lab fork — flat-field/BaSiC shading), `tifffile` (pinned to
  2025.9.20 to avoid NumPy 2), `numcodecs`, `cmap`, `psfmodels`, `SimpleITK`,
  `ndstorage` (NDTiff), `roifile`, `imbalanced-learn`, `scikit-learn`,
  `yaozarrs[write-tensorstore,io]>=0.3`, `matplotlib`.
- **PyTorch** (`torch`/`torchvision`, CUDA 12.8 wheels) for Cellpose/U-FISH.
- **JAX** (Linux JAX libs) — used by BaSiCPy.

### 6.2 The two-environment workaround (operationally important)

`setup-merfish3d` **creates a second conda environment named
`merfish3d-stitcher`**. The reason: `multiview-stitcher`'s sub-dependency
`xarray-dataclass` requires `numpy>2.0`, which is incompatible with the rest of
the scientific stack (pinned below NumPy 2). The second environment holds the
minimal packages to read the datastore (`ngff-zarr[tensorstore]>=0.16.0`,
`yaozarrs`, `pandas`, `roifile`, `shapely`, `fastparquet`, `joblib`) plus
`multiview-stitcher`. The main code
**automatically invokes this second environment via subprocess** for the global
registration / fusion step. This is a temporary workaround to be removed once
the dependency conflict is resolved.

### 6.3 External tools (installed separately by the user)

- **proseg** — probabilistic cell segmentation from transcripts (2D/3D);
  invoked via shell with explicit column mappings (see README). Outputs
  spatialdata zarr, count matrices, and cell polygons. **This is the only
  transcript-based re-segmentation backend** — Baysor support was removed in
  v0.10 (including its `baysor_path`/`baysor_options`/`julia_threads` datastore
  properties).
- **Cellpose (SAM)** — 2D nuclear/fiducial segmentation; parameters tuned in its
  GUI.
- **napari** — interactive visualization (also used to determine
  camera/stage orientation when metadata is missing).
- **ImageJ / Fiji** — rolling-ball background subtraction via pyimagej bridge.

### 6.4 Algorithm/library provenance

- **RLGC deconvolution**: Manton & York gradient-consensus method
  (Zenodo 10278919) with Biggs-Andrews acceleration (1997).
- **Registration**: SimpleITK (rigid) + warpfield (GPU deformable), cuCIM/cuVS.
- **Decoding**: custom two-threshold MERFISH caller with L2-normalized codewords
  and cosine-distance assignment (CuPy).

---

## 7. Code Conventions and Tooling

- **Build**: `hatchling`; version string lives in
  `src/merfish3danalysis/__init__.py`.
- **Lazy imports**: the package `__init__.py` uses `__getattr__` to defer the
  heavy GPU library imports until a submodule is actually accessed — importing
  `merfish3danalysis` is cheap and won't fail if GPU deps are missing.
- **Multi-GPU**: worker functions are **spawned processes** (not threads),
  using `mp.set_start_method("spawn")` for clean CUDA context isolation
  (one process per GPU).
- **Lint/format**: Ruff, line length 88, target Python 3.12, NumPy docstring
  convention. Type annotations are required (ANN rules; `Any` permitted via
  ANN401). Relative imports are banned. Tests are exempt from docstring,
  security, and annotation checks.
- **Testing**: the primary coverage is the simulation integration matrix
  `tests/test_simulation_example_pipeline.py`, which runs the full
  convert→datastore→preprocess→decode→F1 flow on embedded simulation data
  (CSV ground truth under `tests/data/simulation_dataset/`). A standard matrix
  (`-q`) and an exhaustive regression matrix
  (`--run-simulation-exhaustive`) are available. The simulation data root path
  is hard-coded in the test file and may need editing. A second test file,
  `tests/test_qi2lab_viewer.py`, covers the ndv-based viewer.
- **Docs**: MkDocs (Material theme, mkdocstrings); `mkdocs serve` for local
  preview.

---

## 8. Quick Reference — CLI Entry Points

| Command | Module | Purpose |
| --- | --- | --- |
| `setup-merfish3d` | `setup_merfish3d` | Install CUDA libs + second env (post-install) |
| `setup-colab` | `setup_colab` | Colab bootstrap |
| `qi2lab-datastore` | `cli/qi2lab_microscopes/create_datastore` | Raw → datastore |
| `qi2lab-datastore-skipz` | `…/create_datastore_skip_z` | Raw → z-subsampled datastore |
| `qi2lab-preprocess` | `…/preprocess` | Local registration + decon + U-FISH |
| `qi2lab-globalregister` | `…/global_register` | Global stitch/fuse (multiview-stitcher) |
| `qi2lab-segment` | `…/segment_fiducial` | Cellpose 2D segmentation |
| `qi2lab-decode` | `…/pixeldecode` | Pixel decode + filter + cell assign |
| `qi2lab-viewer` | `cli/qi2lab_microscopes/viewer` | Launch ndv/PyQt datastore viewer (thin wrapper over `viewer.py`) |
| `igfl-datastore` | `cli/igfl_microscopes/create_datastore` | IGFL Abberior-confocal → datastore (Huygens-deconvolved input) |
| `igfl-segment` | `cli/igfl_microscopes/segment_fiducial` | IGFL 3D Cellpose segmentation |
| `sim-convert` | `cli/statphysbio_simulation/convert_simulation_to_experiment` | Sim → fake acquisition |
| `sim-datastore` | `…/convert_to_datastore` | Sim acquisition → datastore |
| `sim-preprocess` | `…/register_and_deconvolve` | Sim registration/decon |
| `sim-decode` | `…/pixeldecode` | Sim pixel decode |
| `sim-f1score` | `…/calculate_F1` | F1 vs ground truth |
| `sim-buildfigure` | `…/calculate_F1` | Build F1 summary figure |

---

*Summary generated from repository inspection of `merfish3d-analysis` at
version 0.10.0 (datastore layout v0.6, OME-NGFF v0.5).*
