"""
Run 3D cellpose on the fused fiducial volume, save ROIs, and warp ROIs to
global coordinate system.

Unlike the qi2lab version (which segments a 2D max-projection), this CLI runs
cellpose on the full 3D volume, so cell layers are not collapsed along z — the
relevant case for thick confocal samples.

Why not distributed (cellpose's ``distributed_eval``)?
------------------------------------------------------
An earlier version of this CLI tiled the volume with
``cellpose.contrib.distributed_segmentation.distributed_eval``. That path is
**incompatible with this project's zarr stack**: the datastore writes/reads
OME-Zarr v0.5 (zarr **v3**, via yaozarrs/tensorstore), but cellpose 4.1.1's
``distributed_segmentation`` calls ``zarr.open(path, 'w', shape=..., ...)`` —
the zarr **v2** API where ``mode`` is positional. Under zarr 3.x ``mode`` is
keyword-only, so ``distributed_eval`` raises ``TypeError`` (and so would its
``numpy_array_to_zarr`` helper). The fused fiducial volume is small enough to
segment in memory on one GPU, so distributed tiling is overkill here. If a
future dataset is too large to fit in memory, revisit the distributed path once
cellpose's ``distributed_segmentation`` supports zarr 3.x.

QC outputs (max-projection TIFF + z-depth PNG) are produced by global_register.

Blanc 2025/06 - created for igfl Abberior confocal data.
"""

from pathlib import Path

import numpy as np
import typer
from cellpose import models
from roifile import ImagejRoi, roiwrite
from skimage.measure import find_contours
from tqdm import tqdm

from merfish3danalysis.qi2labDataStore import qi2labDataStore

app = typer.Typer()
app.pretty_exceptions_enable = False


def _build_pixel_rois(masks: np.ndarray) -> list[ImagejRoi]:
    """Extract per-slice ImageJ ROIs from a 3D mask array.

    For every Z-slice, contours are traced for each cell label using
    skimage.measure.find_contours (returns (row, col) = (y, x) order).
    Each ROI is named cell_{cell_id:07d}_z{z:04d}.
    """
    pixel_rois: list[ImagejRoi] = []
    for z in range(masks.shape[0]):
        slice_mask = masks[z]
        for cell_id in np.unique(slice_mask):
            if cell_id == 0:
                continue
            contours = find_contours(slice_mask == cell_id, level=0.5)
            if not contours:
                continue
            # use the longest contour (outermost boundary)
            yx = contours[int(np.argmax([len(c) for c in contours]))].astype(np.float32)
            # ImagejRoi expects (x, y) — flip from (row=y, col=x)
            roi = ImagejRoi.frompoints(yx[:, ::-1])
            roi.name = f"cell_{cell_id:07d}_z{z:04d}"
            pixel_rois.append(roi)
    return pixel_rois


@app.command()
def run_cellpose(
    root_path: Path,
    normalization: tuple[float, float] = typer.Option([1.0, 99.0]),
    diameter: int = typer.Option(30),
    flow_threshold: float = typer.Option(0.4),
    cellprob_threshold: float = typer.Option(0.0),
    zstride_level: int = typer.Option(0),
) -> None:
    """Run 3D cellpose on the fused fiducial volume and save ROIs.

    Parameters
    ----------
    root_path : Path
        Path to the experiment root directory.
    normalization : tuple[float, float]
        Percentile normalization bounds [low, high].
    diameter : int
        Expected cell diameter in pixels.
    flow_threshold : float
        Cellpose flow error threshold.
    cellprob_threshold : float
        Cell probability threshold.
    zstride_level : int
        Use a skip-z datastore (0 = standard datastore).
    """

    # --- initialize datastore ---
    if zstride_level == 0:
        datastore_path = root_path / Path("qi2labdatastore")
    else:
        datastore_path = root_path / Path(f"qi2labdatastore_zstride0{zstride_level}")
    datastore = qi2labDataStore(datastore_path)
    print(f"Using datastore at {datastore_path}")

    # --- load fused fiducial volume and global transforms ---
    result = datastore.load_global_fidicual_image(return_future=False)
    if result is None:
        raise FileNotFoundError("Global fiducial image not found in datastore.")
    fused_image, affine_zyx_um, origin_zyx_um, spacing_zyx_um = result

    # the datastore stores the fused image as (t, c, z, y, x) with singleton
    # leading axes; drop them down to a 3D (z, y, x) volume for cellpose.
    volume = np.squeeze(np.asarray(fused_image))
    if volume.ndim != 3:
        raise ValueError(
            f"Expected a 3D fiducial volume after squeezing, got shape {volume.shape}"
        )

    # --- run 3D cellpose in memory ---
    anisotropy = float(spacing_zyx_um[0]) / float(spacing_zyx_um[1])
    model = models.CellposeModel(gpu=True)
    print("Running cellpose 3D segmentation...")
    masks, _, _ = model.eval(
        volume,
        z_axis=0,
        channel_axis=None,
        diameter=diameter,
        flow_threshold=flow_threshold,
        cellprob_threshold=cellprob_threshold,
        do_3D=True,
        anisotropy=anisotropy,
        niter=200,
        normalize={"normalize": True, "percentile": list(normalization)},
    )
    print("Cellpose 3D segmentation done.")
    masks = np.asarray(masks)
    print(f"Cellpose complete. Found {int(masks.max())} cells.")

    # --- save 3D masks to datastore zarr ---
    cellpose_path = datastore_path / "segmentation" / "cellpose"
    cellpose_path.mkdir(parents=True, exist_ok=True)
    datastore.save_global_cellpose_segmentation_image(masks, downsampling=[1, 1, 1])
    print("Saved 3D masks to datastore.")

    # --- save pixel-spaced ROIs ---
    imagej_roi_path_dir = cellpose_path / "imagej_rois"
    imagej_roi_path_dir.mkdir(exist_ok=True)

    pixel_rois = _build_pixel_rois(masks)
    roiwrite(imagej_roi_path_dir / "pixel_spacing_rois.zip", pixel_rois, mode="w")
    print(f"Saved {len(pixel_rois)} pixel-spaced ROI slices.")

    # --- warp ROIs to global coordinates ---
    global_spacing_rois: list[ImagejRoi] = []
    for pixel_roi in tqdm(pixel_rois, desc="warping ROIs"):
        # name encodes z: cell_XXXXXXX_zZZZZ
        z = int(pixel_roi.name.split("_z")[-1])
        pixel_coordinates = pixel_roi.coordinates().astype(np.float32)
        # ROIs are (x, y); build padded (z, y, x) rows for warp_point
        z_col = np.full((pixel_coordinates.shape[0], 1), float(z))
        padded = np.hstack((z_col, pixel_coordinates[:, ::-1]))
        global_padded = np.zeros_like(padded, dtype=np.float32)
        for pt_idx, pts in enumerate(padded):
            global_padded[pt_idx, :] = warp_point(
                pts.copy().astype(np.float32),
                spacing_zyx_um,
                origin_zyx_um,
                affine_zyx_um,
            )
        # drop z column, flip (y, x) back to (x, y)
        global_xy = global_padded[:, 1:][:, ::-1]
        roi = ImagejRoi.frompoints(np.round(global_xy, 2).astype(np.float32))
        roi.name = pixel_roi.name
        global_spacing_rois.append(roi)

    roiwrite(imagej_roi_path_dir / "global_coords_rois.zip", global_spacing_rois, mode="w")
    print(f"Saved {len(global_spacing_rois)} global-coordinate ROIs.")


def warp_point(
    pixel_space_point: np.ndarray,
    spacing: np.ndarray,
    origin: np.ndarray,
    affine: np.ndarray,
) -> np.ndarray:
    """Warp a point from pixel space to global space using known transforms.

    Parameters
    ----------
    pixel_space_point : np.ndarray
        Point in image coordinate system, zyx order.
    spacing : np.ndarray
        Pixel size in microns, zyx order.
    origin : np.ndarray
        World coordinate origin (µm), zyx order.
    affine : np.ndarray
        4x4 affine matrix (µm), zyx order.

    Returns
    -------
    np.ndarray
        Point in world coordinate system (µm), zyx order.
    """
    physical_space_point = pixel_space_point * spacing + origin
    registered_space_point = (
        np.array(affine) @ np.array([*list(physical_space_point), 1])
    )[:-1]
    return registered_space_point


def main() -> None:
    """
    Main.

    Returns
    -------
    None
        Function result.
    """
    app()


if __name__ == "__main__":
    main()
