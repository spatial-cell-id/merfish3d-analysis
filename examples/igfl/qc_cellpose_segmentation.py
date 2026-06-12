"""
QC script: open the fused fiducial volume and 3-D cellpose mask in napari
for visual inspection after running igfl-segment-fiducial.

Usage
-----
python examples/igfl/qc_cellpose_segmentation.py <root_path>
"""

from pathlib import Path

import napari
import numpy as np
import typer

from merfish3danalysis.qi2labDataStore import qi2labDataStore

app = typer.Typer(add_completion=False)


@app.command()
def qc_cellpose_segmentation(
    root_path: Path = typer.Argument(..., help="Root directory of the igfl dataset"),
) -> None:
    """Open fiducial volume and cellpose mask in napari for visual QC."""

    datastore_path = root_path / "qi2labdatastore"
    if not datastore_path.exists():
        raise FileNotFoundError(f"Datastore not found: {datastore_path}")

    datastore = qi2labDataStore(datastore_path)

    # --- load fiducial volume ---
    result = datastore.load_global_fidicual_image(return_future=False)
    if result is None:
        raise FileNotFoundError("Global fiducial image not found in datastore.")
    fused_image, _affine_zyx_um, _origin_zyx_um, spacing_zyx_um = result
    volume = np.squeeze(np.asarray(fused_image))
    if volume.ndim != 3:
        raise ValueError(f"Expected 3-D fiducial volume, got shape {volume.shape}")

    # --- load cellpose masks ---
    masks_raw = datastore.load_global_cellpose_segmentation_image(return_future=False)
    if masks_raw is None:
        raise FileNotFoundError("Cellpose segmentation not found in datastore.")
    masks = np.asarray(masks_raw)

    typer.echo(f"Fiducial volume : {volume.shape}  spacing_zyx_um={spacing_zyx_um}")
    typer.echo(f"Cellpose masks  : {masks.shape}  cells={int(masks.max())}")

    # --- visualise ---
    viewer = napari.Viewer()
    viewer.add_image(
        volume,
        name="fiducial",
        scale=spacing_zyx_um,
        colormap="gray",
        blending="additive",
    )
    viewer.add_labels(
        masks,
        name="cellpose_masks",
        scale=spacing_zyx_um,
        opacity=0.4,
    )
    napari.run()


if __name__ == "__main__":
    app()
