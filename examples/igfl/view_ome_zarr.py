#!/usr/bin/env python3
"""Open qi2labDataStore OME-Zarr images in napari from inside WSL.

Drag-and-drop from Windows (``\\\\wsl.localhost\\...``) routes the read through
fsspec, which misreads the UNC path as remote and fails with an SSL/ASN1 error.
Running napari inside WSL on the local POSIX path avoids that entirely. This
launcher also bypasses any OME reader plugin: it opens the zarr arrays directly
and applies the voxel scale from the OME metadata, so it works regardless of
napari-ome-zarr being installed.

Usage
-----
    # one or more .ome.zarr stores
    python scripts/view_ome_zarr.py /path/to/corrected_data.ome.zarr

    # a whole tile folder (loads every *.ome.zarr it contains, recursively)
    python scripts/view_ome_zarr.py /path/to/qi2labdatastore/readouts/tile0003
"""

from __future__ import annotations

import argparse
from pathlib import Path

import napari
import zarr


def _scale_from_ome(attributes: dict) -> list[float] | None:
    """Pull the per-axis scale from OME multiscales metadata, if present."""
    ome = attributes.get("ome") if isinstance(attributes, dict) else None
    if not isinstance(ome, dict):
        return None
    try:
        dataset = ome["multiscales"][0]["datasets"][0]
        for xform in dataset["coordinateTransformations"]:
            if xform.get("type") == "scale":
                return [float(s) for s in xform["scale"]]
    except (KeyError, IndexError, TypeError):
        return None
    return None


def _collect_stores(target: Path) -> list[Path]:
    """Return the .ome.zarr stores under ``target`` (or target itself)."""
    if target.name.endswith(".ome.zarr"):
        return [target]
    stores = sorted(
        p for p in target.rglob("*.ome.zarr") if (p / "zarr.json").exists()
    )
    return stores


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        type=Path,
        nargs="+",
        help="One or more .ome.zarr stores, or folders containing them.",
    )
    args = parser.parse_args()

    viewer = napari.Viewer()
    loaded = 0
    for target in args.paths:
        if not target.exists():
            print(f"SKIP (missing): {target}")
            continue
        for store in _collect_stores(target):
            try:
                group = zarr.open_group(str(store), mode="r")
                array = group["0"]
            except Exception as exc:
                print(f"SKIP (unreadable {store}): {exc}")
                continue
            scale = _scale_from_ome(dict(group.attrs))
            # name layers as <tile>/<image> for readable QC
            name = f"{store.parent.name}/{store.name.replace('.ome.zarr', '')}"
            viewer.add_image(array, name=name, scale=scale, blending="additive")
            loaded += 1
            print(f"loaded: {name}  shape={array.shape}  scale={scale}")

    if loaded == 0:
        print("No OME-Zarr stores loaded.")
        return
    napari.run()


if __name__ == "__main__":
    main()
