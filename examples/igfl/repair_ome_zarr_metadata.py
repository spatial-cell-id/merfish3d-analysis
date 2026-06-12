#!/usr/bin/env python3
"""Repair non-spec-compliant qi2labDataStore OME-Zarr group metadata.

Older datastore writes injected a top-level ``extra_attributes`` key into each
group ``zarr.json``. That key violates the zarr v3 spec, so compliant readers
(napari, napari-ome-zarr, zarr-python v3) fail with::

    GroupMetadata.__init__() got an unexpected keyword argument 'extra_attributes'

This script moves any top-level ``extra_attributes`` into ``attributes`` (where
the same data already lives) and removes the offending top-level key. It is
lossless and idempotent.

Usage
-----
    python scripts/repair_ome_zarr_metadata.py /path/to/qi2labdatastore
    python scripts/repair_ome_zarr_metadata.py /path/to/store --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def repair_zarr_json(zarr_json_path: Path, *, dry_run: bool) -> bool:
    """Repair a single ``zarr.json``; return True if it needed a change."""
    try:
        data = json.loads(zarr_json_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  SKIP (unreadable): {zarr_json_path} -> {exc}")
        return False

    if not isinstance(data, dict) or "extra_attributes" not in data:
        return False

    extra = data.pop("extra_attributes")
    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    if isinstance(extra, dict):
        # Preserve anything not already present under attributes.
        for key, value in extra.items():
            attributes.setdefault(key, value)
    data["attributes"] = attributes

    if dry_run:
        print(f"  WOULD FIX: {zarr_json_path}")
        return True

    zarr_json_path.write_text(json.dumps(data, indent=2))
    print(f"  FIXED: {zarr_json_path}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path, help="Path to a qi2labdatastore root")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    root: Path = args.store
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")

    fixed = 0
    scanned = 0
    for zarr_json_path in root.rglob("zarr.json"):
        scanned += 1
        if repair_zarr_json(zarr_json_path, dry_run=args.dry_run):
            fixed += 1

    verb = "would be repaired" if args.dry_run else "repaired"
    print(f"\nScanned {scanned} zarr.json file(s); {fixed} {verb}.")


if __name__ == "__main__":
    main()
