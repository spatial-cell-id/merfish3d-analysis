"""
Convert igfl Abberior confocal MERFISH data to qi2labdatastore.

Reads Huygens-deconvolved OME-TIFF stacks and a semicolon-delimited codebook
from the igfl data layout and writes a qi2labDataStore-compatible zarr store.

Blanc 2025/06 - production CLI adapter.
"""

import json
import warnings
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import typer
from psfmodels import make_psf
from tifffile import TiffFile, imread
from tqdm import tqdm

from merfish3danalysis.qi2labDataStore import qi2labDataStore

warnings.filterwarnings("ignore", category=UserWarning)

app = typer.Typer()

_OME_NS = {"ome": "http://www.openmicroscopy.org/Schemas/OME/2016-06"}

# Map codebook dye shorthand → OME channel Name field on this microscope system
CODEBOOK_TO_OME_NAME: dict[str, str] = {
    "Atto700": "ATTO 700 Custom",
    "Atto647N": "STAR RED",  # Abberior STAR RED = Atto647N on this system
    "Atto565": "ATTO 565",
    "DAPI": "DAPI",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_ome_pixels(tf: TiffFile) -> dict:
    """Parse pixel metadata from an OME-TIFF file.

    Parameters
    ----------
    tf : TiffFile
        Open TiffFile object for an OME-TIFF. Must have valid OME metadata.

    Returns
    -------
    dict
        Keys: ``yx_pixel_um``, ``z_step_um``, ``size_z``, ``size_c``,
        ``channels`` (list of dicts with ``name``, ``ex_um``, ``em_um``),
        ``stage_pos_zyx_um`` (float32 ndarray), ``na`` (float or None),
        ``tile_overlap`` (float or None).
    """
    root = ET.fromstring(tf.ome_metadata)
    pixels = root.find("ome:Image/ome:Pixels", _OME_NS)

    yx_pixel_um = float(pixels.get("PhysicalSizeX")) * 1e6  # m → µm
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
    stage_x_um = float(
        np.mean([float(p.get("PositionX")) * 1e6 for p in planes]))
    stage_y_um = float(
        np.mean([float(p.get("PositionY")) * 1e6 for p in planes]))
    stage_z_um = float(planes[0].get("PositionZ")) * 1e6

    # Parse NA from the Folder[2] Description JSON (Abberior-specific)
    na = None
    folders = root.findall("ome:Folder", _OME_NS)
    if len(folders) >= 3:
        desc_el = folders[2].find("ome:Description", _OME_NS)
        if desc_el is not None and desc_el.text:
            try:
                desc = json.loads(desc_el.text)
                na_str = desc["objective_lens"]["name"].split(
                    "NA")[-1].split("(")[0]
                na = float(na_str)
            except (KeyError, ValueError, json.JSONDecodeError):
                pass

    tile_overlap = None
    if len(folders) >= 3:
        desc_el = folders[2].find("ome:Description", _OME_NS)
        if desc_el is not None and desc_el.text:
            try:
                desc = json.loads(desc_el.text)
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


def _find_raw_tile(
    raw_dir: Path, root_name: str, round_idx: int, tile_idx: int
) -> Path:
    """Return the path to a raw OME-TIFF tile.

    Parameters
    ----------
    raw_dir : Path
        Root raw-data directory (``<dataset>/Raw data``).
    root_name : str
        Dataset stem (``root_path.stem``).
    round_idx : int
        Zero-based round index.
    tile_idx : int
        Zero-based tile index.

    Returns
    -------
    Path
        Path to the matching ``*.ome.tiff`` file.

    Raises
    ------
    FileNotFoundError
        If no matching tile is found.
    """
    folder = raw_dir / f"{root_name} raw_data round_{round_idx + 1:03d}"
    candidates = list(folder.glob(f"*tile_{tile_idx + 1:03d}.ome.tiff"))
    if not candidates:
        raise FileNotFoundError(
            f"No raw tile found in {folder} for tile {tile_idx + 1:03d}"
        )
    return candidates[0]


def _find_deconv_tile(
    deconv_dir: Path, root_name: str, round_idx: int, tile_idx: int
) -> Path:
    """Return the path to a Huygens-deconvolved OME-TIFF tile.

    Parameters
    ----------
    deconv_dir : Path
        Root deconvolved-data directory (``<dataset>/Deconv data``).
    root_name : str
        Dataset stem (``root_path.stem``).
    round_idx : int
        Zero-based round index.
    tile_idx : int
        Zero-based tile index.

    Returns
    -------
    Path
        Path to the matching ``*.ome.tiff`` file.

    Raises
    ------
    FileNotFoundError
        If no matching tile is found.
    """
    folder = deconv_dir / f"{root_name} deconv_data round_{round_idx + 1:03d}"
    candidates = list(folder.glob(f"*tile_{tile_idx + 1:03d}.ome.tiff"))
    if not candidates:
        raise FileNotFoundError(
            f"No deconv tile found in {folder} for tile {tile_idx + 1:03d}"
        )
    return candidates[0]


def _parse_codebook(
    codebook_path: Path,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.DataFrame]:
    """Parse an igfl semicolon-delimited codebook CSV.

    Parameters
    ----------
    codebook_path : Path
        Path to the codebook CSV file. Row 0 = bit numbers, row 1 = round
        numbers, row 2 = dye/channel names, row 3 = (ignored header), rows
        4+ = gene entries.

    Returns
    -------
    bit_row : pd.Series
        Bit number for each imaging channel column.
    round_row : pd.Series
        Round number for each imaging channel column.
    chan_row : pd.Series
        Dye name for each imaging channel column.
    codebook_df : pd.DataFrame
        Gene-by-bit DataFrame with columns ``[gene_id, bit01, bit02, ...]``.
    """
    raw = pd.read_csv(codebook_path, header=None, index_col=0, sep=";")
    bit_row = raw.iloc[0].astype(int)
    round_row = raw.iloc[1].astype(int)
    chan_row = raw.iloc[2]
    gene_rows = raw.iloc[4:]

    codebook_df = gene_rows.reset_index()
    codebook_df.columns = ["gene_id"] + [f"bit{int(b):02d}" for b in bit_row]

    return bit_row, round_row, chan_row, codebook_df


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@app.command()
def convert_data(
    root_path: Path = typer.Argument(..., help="Root directory of the igfl dataset"),  # noqa: B008
    codebook_path: Path | None = typer.Option(  # noqa: B008
        None, help="Path to codebook.csv. Defaults to <root_path>/codebook.csv"
    ),
    output_path: Path | None = typer.Option(  # noqa: B008
        None,
        help="Output path for the qi2labdatastore. Defaults to <root_path>/qi2labdatastore",
    ),
    na: float | None = typer.Option(
        None, help="Objective NA. Auto-parsed from OME metadata if not provided."
    ),
    ri: float = typer.Option(
        1.4, help="Refractive index of immersion medium (silicon oil)"
    ),
    ri_sample: float = typer.Option(1.33, help="Refractive index of sample"),
    z_size_crop: int | None = typer.Option(
        None,
        help="Crop Z dimension to this many slices (reduces memory; use ~20 for testing)",
    ),
    z_start: int = typer.Option(
        0, help="First Z plane index for the crop window (used with --z_size_crop)"
    ),
    deconv_scale: float = typer.Option(
        200.0,
        help=(
            "Constant multiplier applied to deconv float values before the uint16 "
            "cast. Huygens deconv output is float32 with a small range (most pixels "
            "< 1.0); a direct uint16 cast truncates the fractional part and destroys "
            "the signal. The same factor is applied to every tile/round/channel so "
            "relative intensities are preserved across tiles (no per-tile "
            "renormalization, which would cause fusion artifacts)."
        ),
    ),
) -> None:
    """Convert igfl Abberior confocal MERFISH data to qi2labdatastore.

    Parameters
    ----------
    root_path : Path
        Root directory of the igfl dataset. Must contain ``Raw data/`` and
        ``Deconv data/`` subdirectories.
    codebook_path : Path or None
        Path to the semicolon-delimited codebook CSV. Defaults to
        ``<root_path>/codebook.csv``.
    output_path : Path or None
        Destination for the qi2labDataStore zarr. Defaults to
        ``<root_path>/qi2labdatastore``.
    na : float or None
        Objective numerical aperture. Auto-parsed from OME metadata when
        ``None``; falls back to 1.3 if metadata is absent.
    ri : float
        Refractive index of the immersion medium (silicon oil default: 1.4).
    ri_sample : float
        Refractive index of the sample (default: 1.33).
    z_size_crop : int or None
        Crop the Z stack to this many planes. Useful for memory-limited test
        runs (e.g. ``20``). ``None`` keeps all planes.
    z_start : int
        First Z-plane index of the crop window (used together with
        ``z_size_crop``).
    deconv_scale : float
        Constant multiplier applied to the deconv float image before the uint16
        cast. Huygens deconv output is float32 with most values below 1.0;
        casting directly to uint16 truncates the fractional part and destroys
        the signal. The same factor is applied to every tile/round/channel so
        relative intensities are preserved across tiles (no per-tile
        renormalization).

    Returns
    -------
    None
        Writes the datastore to disk and exits.
    """
    if not root_path.exists():
        raise FileNotFoundError(f"{root_path} not found.")

    root_name = root_path.stem
    raw_dir = root_path / "Raw data"
    deconv_dir = root_path / "Deconv data"
    if not raw_dir.exists():
        raise FileNotFoundError(f"'Raw data' folder not found in {root_path}")
    if not deconv_dir.exists():
        raise FileNotFoundError(
            f"'Deconv data' folder not found in {root_path}")

    if codebook_path is None:
        codebook_path = root_path / "codebook.csv"
    if not codebook_path.exists():
        raise FileNotFoundError(f"Codebook not found: {codebook_path}")

    # -----------------------------------------------------------------------
    # Parse codebook
    # -----------------------------------------------------------------------
    bit_row, round_row, chan_row, codebook_df = _parse_codebook(codebook_path)

    rounds_to_bits: dict[int, list[int]] = defaultdict(list)
    for bit, rnd in zip(bit_row, round_row, strict=False):
        rounds_to_bits[int(rnd)].append(int(bit))

    num_rounds = max(rounds_to_bits.keys())

    # unique dyes, codebook order preserved
    readout_dyes = list(dict.fromkeys(chan_row))
    dye_order = ["DAPI", *readout_dyes]

    # Build experiment_order as DataFrame with columns = dye_order.
    # Datastore expects: col 0 (DAPI) = round number, remaining cols = bit number
    # imaged by that dye in that round (matched by round+dye lookup in codebook).
    bit_to_round_dye = {
        int(bit): (int(rnd), str(dye))
        for bit, rnd, dye in zip(bit_row, round_row, chan_row, strict=False)
    }
    exp_rows = []
    for rnd in range(1, num_rounds + 1):
        row = [rnd]
        for dye in readout_dyes:
            match = [
                b for b, (r, d) in bit_to_round_dye.items() if r == rnd and d == dye
            ]
            row.append(match[0] if match else 0)
        exp_rows.append(row)
    experiment_order = np.array(exp_rows, dtype=int)

    # -----------------------------------------------------------------------
    # Extract metadata from sample raw tile (round 0, tile 0)
    # -----------------------------------------------------------------------
    sample_raw_path = _find_raw_tile(
        raw_dir, root_name, round_idx=0, tile_idx=0)
    sample_tf = TiffFile(str(sample_raw_path))
    if not sample_tf.is_ome:
        raise ValueError(f"{sample_raw_path} is not an OME-TIFF.")
    meta = _parse_ome_pixels(sample_tf)
    sample_tf.close()

    yx_pixel_um: float = meta["yx_pixel_um"]
    z_step_um: float = meta["z_step_um"]
    channels_from_ome: list[dict] = meta["channels"]
    tile_overlap_frac: float = (
        meta["tile_overlap"] if meta["tile_overlap"] is not None else 0.08
    )

    if na is None:
        if meta["na"] is not None:
            na = meta["na"]
        else:
            typer.echo(
                "Warning: could not parse NA from OME metadata; defaulting to 1.3"
            )
            na = 1.3

    # -----------------------------------------------------------------------
    # Count rounds and tiles from folder structure
    # -----------------------------------------------------------------------
    raw_round_folders = sorted(raw_dir.glob(f"{root_name} raw_data round_*"))
    num_rounds_found = len(raw_round_folders)
    if num_rounds_found != num_rounds:
        typer.echo(
            f"Warning: codebook has {num_rounds} rounds but found {num_rounds_found} raw folders."
        )
        num_rounds = num_rounds_found

    # Count tiles from round 0 folder
    first_raw_round = raw_round_folders[0]
    num_tiles = len(list(first_raw_round.glob("*.ome.tiff")))

    # -----------------------------------------------------------------------
    # Map dye names to OME channel indices
    # -----------------------------------------------------------------------
    ome_name_to_idx = {ch["name"]: i for i, ch in enumerate(channels_from_ome)}
    dye_to_chan_idx: dict[str, int] = {}
    for dye in dye_order:
        ome_name = CODEBOOK_TO_OME_NAME.get(dye)
        if ome_name is None or ome_name not in ome_name_to_idx:
            raise ValueError(
                f"Dye '{dye}' (OME name '{ome_name}') not found in OME channel list: "
                f"{list(ome_name_to_idx.keys())}. Update CODEBOOK_TO_OME_NAME."
            )
        dye_to_chan_idx[dye] = ome_name_to_idx[ome_name]

    # -----------------------------------------------------------------------
    # Generate PSFs (required for downstream DataRegistration)
    # -----------------------------------------------------------------------
    channel_psfs = []
    for dye in dye_order:
        ch_meta = channels_from_ome[dye_to_chan_idx[dye]]
        psf = make_psf(
            z=51,
            nx=51,
            dxy=yx_pixel_um,
            dz=z_step_um,
            NA=na,
            wvl=ch_meta["em_um"],
            ns=ri_sample,
            ni=ri,
            ni0=ri,
            model="vectorial",
        ).astype(np.float32)
        psf /= psf.sum()
        channel_psfs.append(psf)
    channel_psfs_arr = np.asarray(channel_psfs, dtype=np.float32)

    # -----------------------------------------------------------------------
    # Initialize datastore
    # -----------------------------------------------------------------------
    datastore_path = (
        output_path if output_path is not None else root_path / "qi2labdatastore"
    )
    datastore = qi2labDataStore(datastore_path)

    voxel_size_zyx_um = [z_step_um, yx_pixel_um, yx_pixel_um]
    datastore.channels_in_data = dye_order
    datastore.num_rounds = num_rounds
    datastore.num_tiles = num_tiles
    datastore.codebook = codebook_df
    datastore.experiment_order = experiment_order
    datastore.tile_overlap = tile_overlap_frac
    datastore.microscope_type = "3D" if z_step_um < 0.5 else "2D"
    datastore.camera_model = "igfl-abberior"
    datastore.camera = "igfl-abberior"
    datastore.e_per_ADU = 1
    datastore.offset = 0
    datastore.binning = 1
    datastore.na = na
    datastore.ri = ri
    datastore.channel_psfs = channel_psfs_arr
    datastore.voxel_size_zyx_um = voxel_size_zyx_um

    datastore_state = datastore.datastore_state
    datastore_state.update({"Calibrations": True})
    datastore.datastore_state = datastore_state

    # -----------------------------------------------------------------------
    # Write conversion metadata JSON for QC
    # -----------------------------------------------------------------------
    conversion_meta: dict = {
        "root_path": str(root_path),
        "root_name": root_name,
        "num_rounds": num_rounds,
        "num_tiles": num_tiles,
        "num_bits": int(bit_row.max()),
        "voxel_size_zyx_um": voxel_size_zyx_um,
        "na": na,
        "ri": ri,
        "ri_sample": ri_sample,
        "z_size_crop": z_size_crop,
        "z_start": z_start,
        "deconv_scale": deconv_scale,
        "channels": [
            {
                "dye_order_idx": i,
                "dye_name": dye,
                "ome_name": CODEBOOK_TO_OME_NAME[dye],
                "ome_channel_idx": dye_to_chan_idx[dye],
                "ex_wvl_um": channels_from_ome[dye_to_chan_idx[dye]]["ex_um"],
                "em_wvl_um": channels_from_ome[dye_to_chan_idx[dye]]["em_um"],
            }
            for i, dye in enumerate(dye_order)
        ],
        "experiment_order": experiment_order.tolist(),
        "codebook_bits_per_round": {
            str(r): bits for r, bits in sorted(rounds_to_bits.items())
        },
    }
    meta_path = datastore_path.parent / "conversion_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(conversion_meta, f, indent=2)

    typer.echo(f"Conversion metadata written to {meta_path}")

    # -----------------------------------------------------------------------
    # Main loop: populate datastore tile by tile, round by round
    # -----------------------------------------------------------------------
    saturation_warned = False
    for round_idx in tqdm(range(num_rounds), desc="rounds"):
        for tile_idx in tqdm(range(num_tiles), desc="tile", leave=False):
            if round_idx == 0:
                datastore.initialize_tile(tile_idx)

            # Load deconv OME-TIFF (CZYX, float32 from Huygens)
            deconv_path = _find_deconv_tile(
                deconv_dir, root_name, round_idx, tile_idx)
            decon_image: np.ndarray = imread(str(deconv_path))
            if z_size_crop is not None:
                decon_image = decon_image[:,
                                          z_start: z_start + z_size_crop, ...]

            # Huygens deconv output is float32 with most values below 1.0.
            # Scale by a constant factor (same for every tile/round/channel) so
            # the uint16 cast preserves sub-integer precision instead of
            # truncating the signal away. Warn once if scaling saturates.
            decon_image = decon_image.astype(np.float32) * deconv_scale
            if not saturation_warned and decon_image.max() > 2**16 - 1:
                typer.echo(
                    f"Warning: scaled deconv max {decon_image.max():.1f} exceeds "
                    f"{2**16 - 1}; bright pixels are clipped. Lower --deconv-scale "
                    "to avoid saturation."
                )
                saturation_warned = True
            decon_image = decon_image.clip(0, 2**16 - 1).astype(np.uint16)

            # Stage position from raw OME-TIFF Plane elements
            raw_path = _find_raw_tile(raw_dir, root_name, round_idx, tile_idx)
            raw_tf = TiffFile(str(raw_path))
            tile_meta = _parse_ome_pixels(raw_tf)
            raw_tf.close()
            stage_pos_zyx_um = tile_meta["stage_pos_zyx_um"]

            affine_zyx_px = np.eye(4, dtype=np.float32)
            datastore.save_local_stage_position_zyx_um(
                stage_pos_zyx_um, affine_zyx_px, tile=tile_idx, round=round_idx
            )

            # Save DAPI fiducial
            dapi_ch_idx = dye_to_chan_idx["DAPI"]
            datastore.save_local_corrected_image(
                decon_image[dapi_ch_idx],
                tile=tile_idx,
                psf_idx=0,
                gain_correction=False,
                hotpixel_correction=False,
                shading_correction=False,
                round=round_idx,
            )
            datastore.save_local_wavelengths_um(
                (
                    channels_from_ome[dapi_ch_idx]["ex_um"],
                    channels_from_ome[dapi_ch_idx]["em_um"],
                ),
                tile=tile_idx,
                round=round_idx,
            )

            # Save readout bits for this round (1-indexed round number)
            bits_this_round = sorted(rounds_to_bits[round_idx + 1])
            for bit_num in tqdm(bits_this_round, desc="bits", leave=False):
                # Find which codebook column corresponds to this bit
                bit_col_idx = list(bit_row).index(bit_num)
                dye_name = chan_row.iloc[bit_col_idx]
                ch_idx = dye_to_chan_idx[dye_name]
                psf_idx = dye_order.index(dye_name)

                datastore.save_local_corrected_image(
                    decon_image[ch_idx],
                    tile=tile_idx,
                    psf_idx=psf_idx,
                    gain_correction=False,
                    hotpixel_correction=False,
                    shading_correction=False,
                    bit=bit_num - 1,  # 0-indexed
                )
                datastore.save_local_wavelengths_um(
                    (
                        channels_from_ome[ch_idx]["ex_um"],
                        channels_from_ome[ch_idx]["em_um"],
                    ),
                    tile=tile_idx,
                    bit=bit_num - 1,
                )

    datastore_state = datastore.datastore_state
    datastore_state.update({"Corrected": True})
    datastore.datastore_state = datastore_state

    typer.echo(f"Done. Datastore written to {datastore_path}")


def main() -> None:
    """Entry point for the igfl datastore conversion CLI.

    Returns
    -------
    None
        Delegates to the Typer app.
    """
    app()


if __name__ == "__main__":
    main()
