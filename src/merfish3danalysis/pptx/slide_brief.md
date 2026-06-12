# Slide Brief — merfish3d-analysis

> For the slide builder. Audience: research engineers **and** biologists with no
> software background. Every slide is written biology-first: lead with the
> plain-language idea, then give the engineer-level detail. Each slide carries a
> visual description (no images supplied — describe what to draw). Every technical
> term has a plain-language equivalent on the slide or in the speaker notes.

---

## Slide 1 — Title

- **Title:** merfish3d-analysis — Turning raw 3D microscope images into a map of which genes are active in which cells
- **Visual:** Full-bleed title slide. Left half: a faint grayscale 3D image stack of fluorescent dots. Right half: the same field re-drawn as crisp colored dots, each labeled with a gene name and sitting inside a traced cell outline. A bold right-pointing arrow spans the two halves. Bottom strip: the qi2lab name and the "GPU-accelerated" tag.
- **Engineer content:** `merfish3d-analysis` — GPU-accelerated post-processing pipeline for 2D/3D iterative barcoded FISH (MERFISH). Python 3.12+, Linux + Nvidia CUDA 12.8 only.
- **Biologist content:** A software tool that takes the enormous image files coming off a microscope and automatically figures out, for thousands of genes at once, exactly where each RNA molecule sits in 3D tissue — and which cell it belongs to.
- **Speaker notes:** "FISH" = fluorescence in-situ hybridization: a way of lighting up specific RNA molecules in a tissue sample so they appear as bright dots under a microscope. "MERFISH" adds a barcode trick (next slides) so you can read thousands of genes instead of a handful. "GPU-accelerated" just means it runs on a graphics card to be fast enough for terabyte-scale data.

---

## Slide 2 — The biological problem

- **Title:** Why this is hard: thousands of genes, millions of dots, in 3D
- **Visual:** A funnel diagram. Wide mouth labeled "Raw data: 6 dimensions — rounds × tiles × color channels × z × y × x" feeding down through a narrow neck labeled "processing" into a small clean output labeled "decoded transcripts + cell outlines." Small annotation: "gigabytes to petabytes."
- **Engineer content:** Input is inherently 6D `[rounds, tile, channel, z, y, x]`. Each dimension needs heavy processing to go from raw acquisition to QC'd 3D transcript localizations and 3D cell boundaries. Datasets range from GB to PB.
- **Biologist content:** A single experiment images the same piece of tissue over and over (many "rounds"), in several colors, across many overlapping fields of view, and at many depths. That is a mountain of pictures. Buried in it is the answer — where every RNA molecule is — but you cannot find it by eye.
- **Biologist content (the goal):** We want a list: "this gene, at this 3D location, inside this cell," for the whole sample.
- **Speaker notes:** A "tile" is one field of view; large samples are imaged as a grid of overlapping tiles, later stitched together. "z" is depth — this is what makes it 3D rather than a flat image. qi2lab builds custom high-resolution and light-sheet microscopes, which produce even denser data than standard setups.

---

## Slide 3 — How MERFISH works: barcodes for genes

- **Title:** The core trick — every gene gets a binary barcode
- **Visual:** A small table. Rows = genes (`Barcode_1`, `Barcode_2`, …). Columns = 16 numbered "bits." Cells filled with 0 or 1, with the 1s highlighted. Beside it, a strip of microscope rounds (Round 1, 2, 3 …) each showing two colored channels (Yellow, Red), with arrows mapping each round+color to a bit number.
- **Engineer content:** `codebook.csv` = `gene_id` + 16 binary bit columns; each gene is a unique on/off pattern (e.g. `Barcode_1 = 0000111000000010`). `bit_order.csv` maps each imaging round and color channel (Yellow, Red) to a bit index. Default 16-bit MERFISH codebook.
- **Biologist content:** Instead of one dye per gene (which limits you to a few genes), MERFISH gives each gene a unique on/off pattern spread across many imaging rounds — like a barcode. A gene "lights up" in some rounds and stays dark in others. Read the pattern of lit/unlit across rounds and you know which gene it is.
- **Speaker notes:** A "bit" is one yes/no measurement — did this spot light up in this round+color, yes or no. With 16 bits you can encode far more genes than 16, and the extra bits give error-checking. Some barcodes are deliberately left unassigned ("blank" barcodes) — they should never appear, so counting how often they do tells us our error rate (see QC slide).

---

## Slide 4 — High-level architecture

- **Title:** Three core components, one shared data store
- **Visual:** A hub-and-spoke diagram. Center cylinder labeled `qi2labDataStore` (the hub). Three boxes around it with double-headed arrows to the hub: `DataRegistration` (top-left), `PixelDecoder` (top-right), and `Segmentation / Stitching` (bottom). Outer ring of small icons: GPU chip, Zarr file, codebook table.
- **Engineer content:** Three core classes. `qi2labDataStore` (`src/merfish3danalysis/qi2labDataStore.py`) is the central I/O hub — every component reads/writes through it. `DataRegistration` (`DataRegistration.py`) aligns and deconvolves. `PixelDecoder` (`PixelDecoder.py`) decodes barcodes into transcripts. State is tracked in JSON sidecars so the pipeline is resumable.
- **Biologist content:** Think of one big organized filing cabinet (the data store) that holds the images and all the experiment information. Three specialist tools take turns working on what is in the cabinet: one that lines the pictures up, one that reads the barcodes, and one that draws the cell outlines.
- **Speaker notes:** The key design idea: components never pass huge images directly to each other; they all go through the data store. That keeps memory under control and lets you stop and resume at any stage. "Class" = a self-contained software component bundling data + the operations on it.

---

## Slide 5 — End-to-end data flow

- **Title:** From raw images to a gene-by-cell table
- **Visual:** A left-to-right pipeline of labeled boxes joined by arrows: `Raw TIFF/NDTiff` → `create_datastore` → `qi2labDataStore (Zarr)` → `preprocess: register + deconvolve` → `global register + segment` → `pixeldecode` → `transcripts (CSV/Parquet)` → `Proseg/Baysor` → `cell × gene counts`. A dashed branch at the end points to `F1 score vs ground truth (simulation)`. Each box tinted by which core class owns it.
- **Engineer content:** `Raw TIFF/NDTiff → [create_datastore] → qi2labDataStore → [DataRegistration preprocess] → [multiview-stitcher global register + Cellpose segment] → [PixelDecoder decode + filter + assign] → decoded_features (CSV/Parquet) → [Proseg/Baysor] → cell × gene matrix`. Simulation runs add an F1 comparison against `GT_spots.csv`.
- **Biologist content:** Step by step: load the raw pictures into the filing cabinet → sharpen and align them so every round lines up → stitch the tiles into one big map and outline the cells → read the barcodes to identify each RNA dot → finally, count how many of each gene sit inside each cell. On simulated data we can also score how accurate we were.
- **Speaker notes:** "Zarr" is a chunked, compressed file format good for huge image arrays. "Parquet/CSV" are table formats for the final transcript lists. Proseg/Baysor are external tools that refine which transcripts belong to which cell. The simulation F1 path is for validation, not real experiments.

---

## Slide 6 — Component: qi2labDataStore

- **Title:** qi2labDataStore — the organized filing cabinet
- **Visual:** A cabinet illustration with labeled drawers: "Metadata", "Calibrations", "Codebook", "PSFs", "Per-tile images", "Pipeline state (JSON)". A small lock icon labeled "tracks what's done" on the state drawer. Arrows from all three core tools pointing into the cabinet.
- **Engineer content:** `qi2labDataStore` (`src/merfish3danalysis/qi2labDataStore.py`, ~4360 lines). Wraps **Zarr v2** storage via the **Tensorstore** library for performance. Exposes typed properties/accessors: `codebook`, `channel_psfs`, `voxel_size_zyx_um`, `experiment_order`, `num_rounds`, `num_bits`, `tile_ids`, normalization vectors, etc. `datastore_state` (a JSON sidecar) records which stages have completed (`LocalRegistered`, etc.).
- **Biologist content:** This is the single place all the experiment's data and settings live: the images themselves, the microscope settings, the gene barcode table, and a running checklist of which processing steps are already finished. Every other tool talks to this cabinet rather than to each other.
- **Speaker notes:** "PSF" (point spread function) = the predictable blur the microscope adds to every point of light; storing it lets us undo that blur later (deconvolution). "Voxel size" = the real-world size (in microns) of one 3D pixel. Keeping a checklist on disk means a crashed run can pick up where it left off instead of starting over.

---

## Slide 7 — Component: DataRegistration

- **Title:** DataRegistration — making every round line up
- **Visual:** Two columns. Left ("Before"): three semi-transparent copies of the same dot field, slightly offset/rotated, looking blurry where they overlap. Right ("After"): the three copies snapped into perfect alignment, dots crisp. Below: a small flow `fiducials → rigid → affine → deformable → warp readouts`.
- **Engineer content:** `DataRegistration` (`DataRegistration.py`). Uses fiducial (bead) rounds to estimate transforms, then applies them: rigid → affine → deformable (optical flow). GPU pixel warping via **warpfield**; optional **RLGC deconvolution**; optional **U-FISH** CNN spot prediction to sharpen registration. Multi-GPU: one spawned process per GPU with `CUDA_VISIBLE_DEVICES` isolation (`_generate_registrations`, `_apply_registration_to_bits`). Driven by `qi2lab-preprocess`.
- **Biologist content:** Because the tissue is imaged dozens of times, the sample inevitably shifts a little between rounds. This tool detects that drift using fixed reference markers (beads) imaged every round, then nudges, rotates, and gently warps each round until they all overlap perfectly. If the rounds are not aligned, the barcodes are unreadable.
- **Speaker notes:** "Fiducials" = reference beads that look the same every round, used as anchor points. "Rigid → affine → deformable" = increasingly flexible corrections: first just slide/rotate, then stretch uniformly, then allow local bending. "Optical flow" estimates how each region moved between two images. The deconvolution and spot-detection pieces get their own slides next.

---

## Slide 8 — Deep dive: Deconvolution (RLGC)

- **Title:** Deconvolution — un-blurring the microscope
- **Visual:** Side-by-side pair of a single fluorescent dot: left "raw" (a fuzzy blob), right "deconvolved" (a tight bright point). Below, a tiny loop diagram: `estimate → compare to blur model (PSF) → correct → repeat`, with a "consensus gate" badge on the correction arrow.
- **Engineer content:** `utils/rlgc.py` (~950 lines). Richardson-Lucy **Gradient Consensus** deconvolution (Manton-style core, Biggs-Andrews acceleration). Iterative multiplicative update gated by a consensus map, implemented as a custom **CuPy `ElementwiseKernel`** (`filter_update_ba`). FFT-friendly sizing + cached FFT buffers; **Ryomen** `Slicer` tiles volumes larger than GPU memory. Invoked by `DataRegistration` for fiducial and/or readout channels.
- **Biologist content:** Every microscope smears each point of light into a small blurry blob in a known, predictable way. Deconvolution uses that known blur pattern to mathematically reverse it, turning fuzzy blobs back into sharp points — which makes the dots easier to locate and the barcodes easier to read.
- **Speaker notes:** It is an iterative guess-and-check: start from the blurry image, predict what the blur would produce, compare, nudge the estimate, repeat. The "gradient consensus" part only keeps corrections that two independent estimates agree on, which suppresses amplified noise. "Ryomen" lets us process volumes bigger than the GPU's memory by working on overlapping chunks.

---

## Slide 9 — Deep dive: U-FISH spot prediction

- **Title:** U-FISH — a neural net that finds the real dots
- **Visual:** A raw noisy image patch on the left feeding into a small box labeled "U-FISH CNN" producing, on the right, a clean "spot probability" heatmap with bright peaks exactly on the true dots. A dropdown chip lists model options: default, merfish, seqfish, smfish, deepspot, exseq.
- **Engineer content:** Optional CNN-based feature detector (**U-FISH**) used to improve registration. Model selectable via `ufish_model` (`UFISH_MODEL_ALIASES` in `DataRegistration.py`): `default`, `merfish`, `seqfish`, `simfish/smfish`, `deepspot`, `exseq`, or a local `.onnx`/`.pth` path. Resolved lazily by `_resolve_ufish_weights_path` so U-FISH need not be imported unless used.
- **Biologist content:** A trained machine-learning model that looks at a noisy image and predicts where the genuine fluorescent dots are, separating real signal from background speckle. Cleaner dot detection means more reliable alignment between rounds. Different pre-trained versions are available for different experiment types.
- **Speaker notes:** "CNN" = convolutional neural network, the kind of model used for image recognition. Here it acts as a smart spot-finder. It is optional — you can run the pipeline without it — but it tends to make registration more robust on hard data. The aliases let a biologist pick a model by experiment name rather than a file path.

---

## Slide 10 — Global registration & fusion

- **Title:** Stitching the tiles into one big map
- **Visual:** A 3×3 grid of overlapping image tiles on the left, each slightly misplaced; an arrow to the right shows them merged into one seamless mosaic with a single coordinate ruler (global X/Y) along the edges. Small "max-projected, downsampled" tag on the merged image.
- **Engineer content:** Global registration via **multiview-stitcher** aligns per-tile local coordinates into one global system (rigid + affine). Produces an XY-downsampled, Z-max-projected, fused fiducial image used downstream. multiview-stitcher runs in a **separate `merfish3d-stitcher` conda env** (numpy>2.0 conflict workaround), invoked automatically. CLI: `qi2lab-globalregister`; fusion helpers in `cli/qi2lab_microscopes/fuseall.py`.
- **Biologist content:** Large samples are photographed as a grid of overlapping snapshots. This step works out exactly how the snapshots fit together and merges them into one continuous map with a single coordinate system — so a transcript's position is meaningful across the whole sample, not just within one snapshot.
- **Speaker notes:** "Global coordinates" = one shared ruler for the entire sample, versus each tile having its own local ruler. "Max projection" flattens the z-stack to its brightest values to make a 2D overview for stitching and for cell outlining. The separate conda environment is a temporary dependency workaround the README documents — it is created and called automatically.

---

## Slide 11 — Cell segmentation

- **Title:** Drawing the cell boundaries
- **Visual:** The fused overview image with colored outlines traced around each cell (a typical Cellpose-style segmentation mask). A few parameter dials drawn on the side: "diameter", "flow threshold", "cell probability". Arrow showing outlines being saved back into the data store as ROIs.
- **Engineer content:** Cell segmentation with **Cellpose** (Cellpose-SAM) on the fused fiducial image. CLI: `qi2lab-segment` (`cli/qi2lab_microscopes/segment_fiducial.py`) — runs Cellpose with user-tuned params (`diameter`, `flow_threshold`, `cellprob_threshold`), saves ROIs, then warps them into global coordinates and back into the datastore. Parameters are optimized by the user in the Cellpose GUI first.
- **Biologist content:** Before we can say "this RNA is inside that cell," we need the cell outlines. This step runs a popular cell-detection tool to trace the boundary of every cell in the sample, then stores those outlines alongside the images. You tune a few intuitive settings (roughly how big the cells are, how confident to be) in a graphical tool first.
- **Speaker notes:** "ROI" = region of interest, here a traced cell outline. "Cellpose" is a widely used deep-learning cell segmenter. Segmentation runs on the flattened overview image; the outlines are then mapped onto the full 3D coordinate system so the decoder can assign transcripts to cells.

---

## Slide 12 — Component: PixelDecoder

- **Title:** PixelDecoder — reading the barcodes
- **Visual:** A single pixel location shown as a vertical bar chart of 16 bit-intensities; an arrow to a "nearest match" comparison against the codebook table; output = a gene label stamped on that pixel. Around it, faint z-planes indicating the decode runs plane-by-plane in 3D.
- **Engineer content:** `PixelDecoder` (`PixelDecoder.py`, ~3580 lines). L2-normalizes each codeword (`_normalize_codebook`) and each pixel's 16-bit trace, then for every voxel finds the nearest codeword by Euclidean distance (`_decode_pixels`, plane-by-plane in z). Estimates **global** and **iterative** normalization/background vectors to remove subjective user scaling. GPU-first (CuPy/cuVS). CLI: `qi2lab-decode`.
- **Biologist content:** This is the tool that actually identifies genes. For each point in the image it reads the on/off pattern across all 16 bits and asks "which gene's barcode does this most closely match?" It also auto-balances the brightness of each round so the user does not have to guess thresholds by hand — a common source of bias.
- **Speaker notes:** "L2-normalize" = rescale each pattern to unit length so we compare shapes, not absolute brightness. "Iterative normalization" = the software repeatedly re-estimates the right per-bit scaling from the data itself, which the docs highlight as a key advantage over manual tuning. The exact accept/reject rule is the next slide.

---

## Slide 13 — Deep dive: the two-threshold caller

- **Title:** How a pixel earns a gene label — two gates
- **Visual:** A 2D scatter region with two axes: x = "distance to nearest barcode", y = "signal magnitude". A green "accepted" box sits where distance is small AND magnitude is between a low and high line; everything outside is shaded "rejected (-1)". Annotate the thresholds.
- **Engineer content:** In `_decode_pixels`: a pixel is assigned its nearest codeword only if `distance ≤ _pixel_assignment_threshold` (a value derived from codebook geometry / the median number of on-bits in `_load_codebook`), AND its magnitude is within `magnitude_threshold = (low, high)`; otherwise it is set to `-1` (no call). Distances computed against the L2-normalized decoding matrix. Connected accepted voxels are then grouped into transcript features (`_extract_barcodes`).
- **Biologist content:** A point only gets called as a gene if it passes two checks: (1) its pattern is close enough to a real barcode, and (2) it is bright enough to be a true signal but not so blindingly bright it is an artifact. Points that fail either check are discarded. Neighboring accepted points that belong to the same molecule are merged into one transcript.
- **Speaker notes:** The distance threshold is computed from the codebook itself (how many bits are "on" per barcode and the geometry of single-bit errors), not hand-picked — so it adapts to the codebook. The low/high magnitude band rejects both faint noise and saturated junk. "-1" is the code for "unassigned." Grouping turns per-pixel calls into one dot = one RNA molecule.

---

## Slide 14 — Filtering & quality control

- **Title:** Keeping only trustworthy calls
- **Visual:** A funnel: top "all raw barcode calls", passing through three labeled filters — "blank-barcode fraction", "logistic-regression FDR", "tile-overlap de-duplication" — into a clean bottom labeled "filtered transcripts". A small gauge showing "false-discovery rate ≤ 5%."
- **Engineer content:** `PixelDecoder` filters: `_filter_all_barcodes_blank_fraction` and `_filter_all_barcodes_blank_bit_enrichment` use unused ("blank") codewords to estimate misidentification; `_calculate_lr_fdr` / `_filter_all_barcodes_LR` apply a logistic-regression false-discovery-rate cut (default target `0.05`). `_remove_duplicates_in_tile_overlap` and `_remove_duplicates_within_tile` (union-find) drop double-counted molecules in overlapping tile regions.
- **Biologist content:** Not every call is real. Because some barcodes are intentionally left unused, any time one of those "blank" barcodes shows up we know it is a mistake — and that lets us estimate and trim the overall error rate. We also remove duplicate counts where neighboring tiles overlap, so one molecule is never counted twice.
- **Speaker notes:** "False discovery rate (FDR)" = the expected fraction of calls that are wrong; the default keeps it at or below 5%. "Logistic regression" here is a simple model that scores each call's likelihood of being genuine. De-duplication matters because tiles are imaged with overlap to allow stitching — molecules in that seam appear in two tiles.

---

## Slide 15 — Transcripts → cells (Proseg/Baysor)

- **Title:** Counting genes per cell
- **Visual:** Left: filtered transcripts as colored dots scattered over traced cell outlines, some dots clearly inside, some ambiguous near borders. Right: a resulting table — rows = cells, columns = genes, values = counts. A box labeled "Proseg / Baysor" sits between them refining the ambiguous border assignments.
- **Engineer content:** `PixelDecoder._assign_cells` assigns each transcript to a Cellpose ROI (point-in-polygon). Output `decoded_features.csv.gz` carries `gene_id`, `global_x/y/z`, `tile_idx`, `cell_id`. External **Proseg** (or Baysor) refines assignments and produces counts: run via documented CLI (2D or 3D, `--voxel-layers ≈ sample thickness in µm`), emitting SpatialData zarr, `.mtx.gz` counts, and cell-polygon GeoJSON.
- **Biologist content:** Now that we know where each RNA is and where the cells are, we tally how many copies of each gene fall inside each cell — the gene-by-cell table that downstream biology (cell typing, spatial analysis) is built on. A specialized tool cleans up the tricky cases near cell borders before producing the final counts.
- **Speaker notes:** "Point-in-polygon" = simply testing whether a dot falls inside a traced outline. Border transcripts are genuinely ambiguous, which is why Proseg/Baysor (probabilistic cell-assignment tools) are used to settle them. The final outputs are standard spatial-omics formats other software can read.

---

## Slide 16 — GPU tech stack & platform

- **Title:** What makes it fast — and what it requires
- **Visual:** A layered stack diagram, bottom to top: "Nvidia GPU + CUDA 12.8" → "RAPIDS: cupy, cucim, cuvs, cudnn + custom CUDA kernels" → "Ryomen out-of-core tiling" → "Tensorstore + Zarr v2 storage" → "merfish3d-analysis classes". A side callout: "Linux + Nvidia only" and "multi-GPU = 1 process per GPU."
- **Engineer content:** GPU-first throughout: **CuPy**, **cuCIM**, **cuVS**, **cuDNN**, custom CUDA kernels; non-GPU paths are **Numba**-accelerated. **Ryomen** handles larger-than-GPU-memory blocks. Storage is **Zarr v2** read/written via **Tensorstore**. Multi-GPU parallelism = spawned processes (`mp.set_start_method("spawn")`) with `CUDA_VISIBLE_DEVICES` isolation. **Linux + Nvidia CUDA 12.8 only** (RAPIDS constraint).
- **Biologist content:** The pipeline runs on graphics cards (GPUs) because the data is far too large for ordinary processors to handle in reasonable time. It works with chunks of data at a time so it never needs to fit the whole image in memory, and it can split work across several GPUs. Practical requirement: a Linux machine with an Nvidia GPU.
- **Speaker notes:** "RAPIDS" is Nvidia's suite of GPU data-science libraries — the reason for the Linux/Nvidia restriction. "Out-of-core" means data lives on disk and is streamed in pieces. "Spawn one process per GPU" gives each GPU a clean, isolated context. None of this changes the science; it is purely about doing it at scale.

---

## Slide 17 — Two CLI pipeline families

- **Title:** Real experiments vs. simulated validation
- **Visual:** Two parallel vertical tracks. Left track "qi2lab_microscopes (real data)": datastore → preprocess → globalregister → segment → decode. Right track "statphysbio_simulation (validation)": convert → datastore → preprocess → decode → F1score. A bridge arrow labeled "same core engine" connects the middle of both tracks.
- **Engineer content:** Two command families under `src/merfish3danalysis/cli/`. Real data: `qi2lab-datastore`, `qi2lab-preprocess`, `qi2lab-globalregister`, `qi2lab-segment`, `qi2lab-decode`. Simulation: `sim-convert`, `sim-datastore`, `sim-preprocess`, `sim-decode`, `sim-f1score`. Both drive the same `qi2labDataStore` / `DataRegistration` / `PixelDecoder` core; entry points declared in `pyproject.toml` `[project.scripts]`. Built with **typer**.
- **Biologist content:** There are two sets of commands. One set processes real microscope experiments end to end. The other set runs the same engine on simulated data where the right answer is already known, so we can measure how accurate the pipeline is. They share the same underlying code, so the validation genuinely reflects the real pipeline.
- **Speaker notes:** "CLI" = command-line interface — commands you type in a terminal. The simulation family exists for testing/benchmarking; it converts synthetic data into a fake acquisition, runs it through, and scores the result. Sharing one core engine is what makes the simulation a meaningful test.

---

## Slide 18 — How to run it

- **Title:** Running the pipeline
- **Visual:** A numbered vertical checklist with terminal-style command chips:
  `1. conda create -n merfish3d python=3.12`
  `2. pip install -e .`
  `3. setup-merfish3d`
  `4. qi2lab-datastore → qi2lab-preprocess → qi2lab-globalregister → qi2lab-segment → qi2lab-decode`
  `5. python -m pytest tests/test_simulation_example_pipeline.py -q`
  Each chip annotated with a one-line plain meaning.
- **Engineer content:** Install: `pip install -e .` then `setup-merfish3d` (sets up CUDA libs + the second `merfish3d-stitcher` conda env automatically). Run real data via the `qi2lab-*` commands in order. Validate with the simulation integration test (`tests/test_simulation_example_pipeline.py`); exhaustive sweep with `--run-simulation-exhaustive`. Lint/format with `ruff check --fix` / `ruff format`. No-install trial via the Colab notebook.
- **Biologist content:** Set up a Python environment, install the package, and run one setup command that prepares the GPU libraries for you. Then run the steps in order (load → align → stitch → outline cells → decode). A built-in test runs the whole thing on simulated data to confirm everything works. There is also a cloud notebook to try it without installing anything.
- **Speaker notes:** `setup-merfish3d` is doing the heavy lifting of CUDA setup and creating the helper stitcher environment — biologists do not need to understand the details, just run it. The Colab link in the README lets non-installers experiment on simulated data in the browser. Cellpose parameters are tuned in its GUI before `qi2lab-segment`.

---

## Slide 19 — Glossary

- **Title:** Glossary — paired technical & plain-language terms
- **Visual:** A two-column table. Left column "Term", right column "Plain meaning." Color-code rows: blue = software/engineering, green = biology/imaging. Keep to ~14 rows so it is readable.
- **Engineer content / Biologist content (paired rows):**
  - **MERFISH** — imaging method that gives each gene a multi-round on/off barcode so thousands can be read at once.
  - **FISH** — lighting up specific RNA molecules so they appear as bright dots.
  - **Codebook** — the table mapping each gene to its barcode pattern (`codebook.csv`).
  - **Bit** — one yes/no measurement: did this spot light up in this round+color.
  - **Round** — one repeat of the imaging cycle; multiple rounds build the barcode.
  - **Fiducial** — reference bead imaged every round, used as an alignment anchor.
  - **Registration** — nudging/rotating/warping rounds so they line up exactly.
  - **Deconvolution** — mathematically un-blurring the microscope's known blur.
  - **PSF** — the microscope's characteristic blur pattern (point spread function).
  - **Segmentation** — tracing the outline of each cell.
  - **Transcript** — one detected RNA molecule (a gene identity + a 3D location).
  - **Blank barcode** — an unused code; if it appears, it flags an error → error rate.
  - **FDR** — false-discovery rate: expected fraction of calls that are wrong (kept ≤5%).
  - **GPU / CUDA / RAPIDS** — graphics-card computing that makes terabyte-scale processing feasible.
  - **Zarr / Tensorstore** — chunked compressed storage for huge image arrays.
  - **Voxel** — a single 3D pixel (has a real-world size in microns).
- **Speaker notes:** Use this slide as a reference/parking-lot during Q&A. If the deck runs long, this can become a printed handout instead of a presented slide. The blue/green color coding lets each audience scan to the terms relevant to them.

---

## Slide 20 — End-to-end pipeline summary

- **Title:** End-to-end pipeline summary
- **Visual:** Full-slide horizontal flow diagram of the pipeline. Six processing steps (create datastore → preprocess → global register → segment → pixel decode → 3-D re-segment) drawn as rounded boxes linked by right-pointing arrows. Input/output data artefacts labelled in small italic text above and below each arrow. A component-ownership strip below the main flow shows which class is responsible for each step (qi2labDataStore spans all; DataRegistration covers preprocess + global register; PixelDecoder covers pixel decode; Segmentation covers segment + 3-D re-segment).
- **Speaker notes:** Walk the audience through each stage left-to-right. Emphasise that qi2labDataStore is the single shared I/O hub — every step reads and writes through it. The ownership strip at the bottom maps each stage to the corresponding Python class in the repo.

---

### Builder notes (not a slide)
- Biology-first framing per the request: on every slide the plain-language idea comes first in delivery even though the field order lists Engineer content before Biologist content (per the required template).
- Every slide has a Visual and every jargon term is glossed on-slide or in notes — satisfies the "serve both audiences, no text-only slides" constraint.
- File paths and class/method names are accurate to the repo as of this brief: `qi2labDataStore.py`, `DataRegistration.py`, `PixelDecoder.py`, `utils/rlgc.py`, CLI entry points in `pyproject.toml`, and the `codebook.csv`/`bit_order.csv`/`GT_spots.csv` formats.
