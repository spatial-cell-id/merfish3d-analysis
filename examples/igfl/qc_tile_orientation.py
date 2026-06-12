"""
QC script: fuse raw tiles at their OME stage positions (no registration) to
diagnose tile orientation and XY coordinate convention before running the
full pipeline.

Outputs a single OME-TIFF mosaic built by averaging tile max-projections at
their raw stage XY positions.  Iterate with --swap-xy / --flip-x / --flip-y
until the 2-D layout looks correct, then apply the matching flags to
global_register.py.

Usage
-----
python examples/igfl/qc_tile_orientation.py <root_path>  [options]

See --help for all options.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import numpy as np
import typer
from tifffile import TiffFile, TiffWriter, imread
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Import helpers from the installed package
# ---------------------------------------------------------------------------
try:
    from merfish3danalysis.cli.igfl_microscopes.create_datastore import (
        _find_raw_tile,
        _parse_ome_pixels,
    )
except ImportError:
    # Fallback: inline copies so the script still works without a package install.
    # Keep these in sync with create_datastore.py.
    import json

    _OME_NS = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}

    def _parse_ome_pixels(tf: TiffFile) -> dict:
        root = ET.fromstring(tf.ome_metadata)
        pixels = root.find("ome:Image/ome:Pixels", _OME_NS)

        yx_pixel_um = float(pixels.get("PhysicalSizeX")) * 1e6
        z_step_um = float(pixels.get("PhysicalSizeZ")) * 1e6
        size_z = int(pixels.get("SizeZ"))
        size_c = int(pixels.get("SizeC"))

        channels = []
        for ch in pixels.findall("ome:Channel", _OME_NS):
            channels.append(
                {
                    "name": ch.get("Name"),
                    "ex_um": float(ch.get("ExcitationWavelength")) * 1e6,
                    "em_um": float(ch.get("EmissionWavelength")) * 1e6,
                }
            )

        planes = pixels.findall("ome:Plane", _OME_NS)
        stage_x_um = float(np.mean([float(p.get("PositionX")) * 1e6 for p in planes]))
        stage_y_um = float(np.mean([float(p.get("PositionY")) * 1e6 for p in planes]))
        stage_z_um = float(planes[0].get("PositionZ")) * 1e6

        na = None
        tile_overlap = None
        folders = root.findall("ome:Folder", _OME_NS)
        if len(folders) >= 3:
            desc_el = folders[2].find("ome:Description", _OME_NS)
            if desc_el is not None and desc_el.text:
                try:
                    desc = json.loads(desc_el.text)
                    na_str = desc["objective_lens"]["name"].split("NA")[-1].split("(")[0]
                    na = float(na_str)
                    tile_overlap = float(desc["region"]["tiles_overlap"]) / 100.0
                except (KeyError, ValueError, json.JSONDecodeError):
                    pass

        return {
            "yx_pixel_um": yx_pixel_um,
            "z_step_um": z_step_um,
            "size_z": size_z,
            "size_c": size_c,
            "channels": channels,
            "stage_pos_zyx_um": np.array(
                [stage_z_um, stage_y_um, stage_x_um], dtype=np.float32
            ),
            "na": na,
            "tile_overlap": tile_overlap,
        }

    def _find_raw_tile(raw_dir: Path, root_name: str, round_idx: int, tile_idx: int) -> Path:
        folder = raw_dir / f"{root_name} raw_data round_{round_idx + 1:03d}"
        candidates = list(folder.glob(f"*tile_{tile_idx + 1:03d}.ome.tiff"))
        if not candidates:
            raise FileNotFoundError(
                f"No raw tile found in {folder} for tile {tile_idx + 1:03d}"
            )
        return candidates[0]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

app = typer.Typer(add_completion=False)


@app.command()
def qc_tile_orientation(
    root_path: Path = typer.Argument(..., help="Root directory of the igfl dataset"),
    round_idx: int = typer.Option(0, help="Round to visualise (0-indexed)"),
    fiducial_channel: str = typer.Option(
        "DAPI", help="OME channel Name for the fiducial channel"
    ),
    z_planes: Optional[list[int]] = typer.Option(
        None,
        help=(
            "Z-plane indices to include in the max-projection. "
            "Provide multiple values: --z-planes 10 --z-planes 11. "
            "Default: all planes."
        ),
    ),
    swap_xy: bool = typer.Option(False, help="Swap X and Y stage coordinates"),
    flip_x: bool = typer.Option(False, help="Negate X stage coordinate"),
    flip_y: bool = typer.Option(False, help="Negate Y stage coordinate"),
    output: Optional[Path] = typer.Option(
        None, help="Output OME-TIFF path (default: <root_path>/qc_tile_mosaic.ome.tiff)"
    ),
    downsample: int = typer.Option(4, help="XY downsample factor (1 = no downsample)"),
) -> None:
    """Fuse raw tiles at raw stage positions for QC of tile orientation."""

    assert root_path.exists(), f"{root_path} not found."
    root_name = root_path.stem
    raw_dir = root_path / "Raw data"
    assert raw_dir.exists(), f"'Raw data' folder not found in {root_path}"

    if output is None:
        output = root_path / "qc_tile_mosaic.ome.tiff"

    # Count tiles from the first round folder
    first_round_folder = raw_dir / f"{root_name} raw_data round_{round_idx + 1:03d}"
    assert first_round_folder.exists(), f"Round folder not found: {first_round_folder}"
    num_tiles = len(list(first_round_folder.glob("*.ome.tiff")))
    typer.echo(f"Found {num_tiles} tiles in {first_round_folder.name}")

    # ------------------------------------------------------------------
    # Pass 1: read metadata from all tiles to determine canvas extent
    # ------------------------------------------------------------------
    tile_metas = []
    for tile_idx in range(num_tiles):
        raw_path = _find_raw_tile(raw_dir, root_name, round_idx, tile_idx)
        tf = TiffFile(str(raw_path))
        assert tf.is_ome, f"{raw_path} is not an OME-TIFF."
        meta = _parse_ome_pixels(tf)
        tf.close()
        tile_metas.append(meta)

    yx_pixel_um: float = tile_metas[0]["yx_pixel_um"]
    effective_px_um = yx_pixel_um * downsample

    # Find fiducial channel index (same for all tiles)
    channels = tile_metas[0]["channels"]
    fid_ch_matches = [i for i, ch in enumerate(channels) if ch["name"] == fiducial_channel]
    if not fid_ch_matches:
        available = [ch["name"] for ch in channels]
        typer.echo(
            f"ERROR: channel '{fiducial_channel}' not found. Available: {available}",
            err=True,
        )
        raise SystemExit(1)
    fid_ch_idx = fid_ch_matches[0]
    typer.echo(f"Using channel index {fid_ch_idx} ('{fiducial_channel}')")

    # Collect and transform stage XY positions
    def _transform(pos_zyx):
        x = float(pos_zyx[2])
        y = float(pos_zyx[1])
        if swap_xy:
            x, y = y, x
        if flip_x:
            x = -x
        if flip_y:
            y = -y
        return x, y

    stage_xy = [_transform(m["stage_pos_zyx_um"]) for m in tile_metas]

    # Print position table
    typer.echo(
        f"\n{'Tile':>4}  {'raw_x_um':>12}  {'raw_y_um':>12}  "
        f"{'tfm_x_um':>12}  {'tfm_y_um':>12}"
    )
    for i, (meta, (tx, ty)) in enumerate(zip(tile_metas, stage_xy)):
        rx = float(meta["stage_pos_zyx_um"][2])
        ry = float(meta["stage_pos_zyx_um"][1])
        typer.echo(f"{i:>4}  {rx:>12.2f}  {ry:>12.2f}  {tx:>12.2f}  {ty:>12.2f}")
    typer.echo("")

    # Canvas size
    tile_h_px = (tile_metas[0]["size_z"],)  # unused — just for reference
    sample_raw = _find_raw_tile(raw_dir, root_name, round_idx, 0)
    sample_data: np.ndarray = imread(str(sample_raw))
    tile_h_px = sample_data.shape[-2] // downsample
    tile_w_px = sample_data.shape[-1] // downsample
    del sample_data

    xs = [xy[0] for xy in stage_xy]
    ys = [xy[1] for xy in stage_xy]
    x_min, y_min = min(xs), min(ys)
    x_max, y_max = max(xs), max(ys)

    canvas_w = int(np.ceil((x_max - x_min) / effective_px_um)) + tile_w_px
    canvas_h = int(np.ceil((y_max - y_min) / effective_px_um)) + tile_h_px

    typer.echo(f"Canvas size: {canvas_h} × {canvas_w} px  (pixel size {effective_px_um:.4f} µm)")

    canvas_sum = np.zeros((canvas_h, canvas_w), dtype=np.float64)
    canvas_cnt = np.zeros((canvas_h, canvas_w), dtype=np.uint8)

    # ------------------------------------------------------------------
    # Pass 2: load, project, and paste each tile
    # ------------------------------------------------------------------
    for tile_idx in tqdm(range(num_tiles), desc="tiles"):
        raw_path = _find_raw_tile(raw_dir, root_name, round_idx, tile_idx)
        data: np.ndarray = imread(str(raw_path))

        # data is CZYX from tifffile
        fid = data[fid_ch_idx].astype(np.float32)  # ZYX

        # Z subset
        if z_planes is not None and len(z_planes) > 0:
            fid = fid[list(z_planes)]

        proj = np.max(fid, axis=0)  # YX

        # Downsample
        if downsample > 1:
            proj = proj[::downsample, ::downsample]

        # Tile canvas offset in pixels
        tx, ty = stage_xy[tile_idx]
        x_off = int(round((tx - x_min) / effective_px_um))
        y_off = int(round((ty - y_min) / effective_px_um))

        # Clamp to canvas bounds
        h = min(proj.shape[0], canvas_h - y_off)
        w = min(proj.shape[1], canvas_w - x_off)
        if h <= 0 or w <= 0:
            typer.echo(f"Warning: tile {tile_idx} falls outside canvas, skipping.")
            continue

        canvas_sum[y_off : y_off + h, x_off : x_off + w] += proj[:h, :w]
        canvas_cnt[y_off : y_off + h, x_off : x_off + w] += 1

        del data

    # Average-blend overlapping regions
    with np.errstate(invalid="ignore", divide="ignore"):
        mosaic = np.where(canvas_cnt > 0, canvas_sum / canvas_cnt, 0.0)
    mosaic = mosaic.clip(0, 2**16 - 1).astype(np.uint16)

    # ------------------------------------------------------------------
    # Write OME-TIFF
    # ------------------------------------------------------------------
    output.parent.mkdir(parents=True, exist_ok=True)
    with TiffWriter(str(output), bigtiff=True) as tif:
        metadata = {
            "axes": "YX",
            "SignificantBits": 16,
            "PhysicalSizeX": effective_px_um,
            "PhysicalSizeXUnit": "µm",
            "PhysicalSizeY": effective_px_um,
            "PhysicalSizeYUnit": "µm",
        }
        options = {
            "compression": "zlib",
            "compressionargs": {"level": 8},
            "predictor": True,
            "photometric": "minisblack",
            "resolutionunit": "CENTIMETER",
        }
        tif.write(
            mosaic,
            resolution=(1e4 / effective_px_um, 1e4 / effective_px_um),
            **options,
            metadata=metadata,
        )

    typer.echo(f"Mosaic written to {output}")
    typer.echo(
        f"Flags used: swap_xy={swap_xy}  flip_x={flip_x}  flip_y={flip_y}  "
        f"round={round_idx}  downsample={downsample}"
    )


if __name__ == "__main__":
    app()
