"""
QC script: compare the fiducial channel of a moving round against the reference
round (the first round, round001) for one tile/FOV in napari, before and after
registration.

Tile and round are selected with the datastore's own ids (tile0000, round002,
...); an integer index into the datastore's ordered id list is also accepted.

Three additively-blended layers are shown so misregistration appears as color
fringing:
  - reference round001 (registered) ........ gray
  - moving round (original, un-registered) . magenta
  - moving round (registered) .............. green

Toggle the magenta vs. green layer over the gray reference to flip between the
pre- and post-registration state. A good registration: the green layer overlaps
the reference (neutral/white) while the magenta layer is visibly offset.

Usage
-----
python examples/igfl/qc_round_registration.py <root_path> --tile tile0000 --round round002
"""

from pathlib import Path

import napari
import numpy as np
import typer

from merfish3danalysis.qi2labDataStore import qi2labDataStore

app = typer.Typer(add_completion=False)


def _resolve_id(value: str, ids: list[str], kind: str) -> str:
    """Resolve a tile/round selector to a datastore id.

    Accepts either a native datastore id (e.g. "tile0000", "round002") or an
    integer index into the datastore's ordered id list (e.g. "0", "1").
    """

    if value in ids:
        return value
    try:
        idx = int(value)
    except ValueError:
        raise ValueError(
            f"Invalid {kind} '{value}'. Use a datastore id ({ids[0]} ... {ids[-1]}) "
            f"or an index in [0, {len(ids) - 1}]."
        ) from None
    if not 0 <= idx < len(ids):
        raise ValueError(
            f"{kind} index {idx} out of range; valid indices are [0, {len(ids) - 1}]."
        )
    return ids[idx]


@app.command()
def qc_round_registration(
    root_path: Path = typer.Argument(..., help="Root directory of the igfl dataset"),  # noqa: B008
    tile: str = typer.Option(
        "tile0000", help="Tile id (e.g. tile0000) or index to inspect"
    ),
    round: str = typer.Option(
        "round002",
        help="Moving round id (e.g. round002) or index; compared to reference round001",
    ),
) -> None:
    """Overlay reference, original, and registered fiducial volumes in napari."""

    datastore_path = root_path / "qi2labdatastore"
    if not datastore_path.exists():
        raise FileNotFoundError(f"Datastore not found: {datastore_path}")

    datastore = qi2labDataStore(datastore_path)

    tile_ids = datastore.tile_ids
    round_ids = datastore.round_ids
    if not tile_ids or not round_ids:
        raise ValueError("Datastore is missing tile_ids / round_ids metadata.")
    tile_ids = list(tile_ids)
    round_ids = list(round_ids)

    tile_id = _resolve_id(tile, tile_ids, "tile")
    round_id = _resolve_id(round, round_ids, "round")
    ref_round_id = round_ids[0]  # reference round (round001)
    if round_id == ref_round_id:
        raise ValueError(
            f"--round must differ from the reference round {ref_round_id}, "
            f"got {round_id}."
        )

    # --- load the three fiducial volumes ---
    ref_registered = datastore.load_local_registered_image(
        tile=tile_id, round=ref_round_id, return_future=False
    )
    if ref_registered is None:
        raise FileNotFoundError(
            f"Registered reference fiducial missing for {tile_id}, {ref_round_id}. "
            "Run qi2lab-preprocess with save_all_fiducial enabled."
        )

    moving_original = datastore.load_local_corrected_image(
        tile=tile_id, round=round_id, return_future=False
    )
    if moving_original is None:
        raise FileNotFoundError(
            f"Corrected (original) fiducial missing for {tile_id}, {round_id}."
        )

    moving_registered = datastore.load_local_registered_image(
        tile=tile_id, round=round_id, return_future=False
    )
    if moving_registered is None:
        raise FileNotFoundError(
            f"Registered fiducial missing for {tile_id}, {round_id}. "
            "Run qi2lab-preprocess with save_all_fiducial enabled."
        )

    ref_vol = np.squeeze(np.asarray(ref_registered))
    orig_vol = np.squeeze(np.asarray(moving_original))
    reg_vol = np.squeeze(np.asarray(moving_registered))

    scale_zyx_um = datastore.voxel_size_zyx_um

    typer.echo(f"reference  {tile_id}  {ref_round_id}  registered : {ref_vol.shape}")
    typer.echo(f"moving     {tile_id}  {round_id}  original    : {orig_vol.shape}")
    typer.echo(f"moving     {tile_id}  {round_id}  registered  : {reg_vol.shape}")
    typer.echo(f"voxel_size_zyx_um = {scale_zyx_um}")

    # --- visualise ---
    viewer = napari.Viewer()
    viewer.add_image(
        ref_vol,
        name=f"{ref_round_id} (ref, registered)",
        scale=scale_zyx_um,
        colormap="gray",
        blending="additive",
    )
    viewer.add_image(
        orig_vol,
        name=f"{round_id} original",
        scale=scale_zyx_um,
        colormap="magenta",
        blending="additive",
    )
    viewer.add_image(
        reg_vol,
        name=f"{round_id} registered",
        scale=scale_zyx_um,
        colormap="green",
        blending="additive",
    )
    napari.run()


if __name__ == "__main__":
    app()
