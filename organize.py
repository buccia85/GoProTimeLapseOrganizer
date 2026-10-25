"""Organize GoPro time-lapse photos into one folder per time-lapse.

GoPro time-lapse files are named ``GxxxYYYY.JPG`` where ``xxx`` identifies the
time-lapse group and ``YYYY`` is the incremental photo number inside it.
Each group is moved into a folder named after the capture date/time of its
first photo (``yyyyMMdd_HHmmss``), created directly under the images root.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

FILE_PATTERN = re.compile(r"^G(?P<group>\d{3})(?P<seq>\d+)\.jpe?g$", re.IGNORECASE)
TARGET_DIR_PATTERN = re.compile(r"^\d{8}_\d{6}(_\d+)?$")
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132
EXIF_IFD = 0x8769
DEFAULT_ROOT = Path(__file__).resolve().parent / "images"


@dataclass(frozen=True)
class Photo:
    path: Path
    group: str
    seq: int


def read_capture_time(path: Path) -> datetime:
    """Return the EXIF capture time, falling back to the file modification time."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            value = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL) or exif.get(EXIF_DATETIME)
        if value:
            return datetime.strptime(str(value).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except (OSError, ValueError):
        pass
    print(f"  warning: no EXIF date in {path.name}, using file modification time")
    return datetime.fromtimestamp(path.stat().st_mtime)


def collect_photos(root: Path) -> dict[str, list[Photo]]:
    """Find time-lapse photos in the source subfolders, grouped by time-lapse id."""
    groups: dict[str, list[Photo]] = defaultdict(list)
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        # Skip folders produced by a previous run
        if TARGET_DIR_PATTERN.match(folder.name):
            continue
        for file in folder.iterdir():
            match = FILE_PATTERN.match(file.name)
            if file.is_file() and match:
                groups[match["group"]].append(Photo(file, match["group"], int(match["seq"])))
    for photos in groups.values():
        photos.sort(key=lambda p: p.seq)
    return groups


def unique_target_dir(root: Path, name: str) -> Path:
    """Return a non-existing folder path, adding a numeric suffix on collision."""
    target = root / name
    counter = 1
    while target.exists():
        target = root / f"{name}_{counter}"
        counter += 1
    return target


def organize(root: Path, dry_run: bool) -> None:
    groups = collect_photos(root)
    if not groups:
        print(f"No time-lapse photos found in {root}")
        return

    source_dirs: set[Path] = set()
    for group_id in sorted(groups):
        photos = groups[group_id]
        start = read_capture_time(photos[0].path)
        target = unique_target_dir(root, start.strftime("%Y%m%d_%H%M%S"))
        print(f"Group {group_id}: {len(photos)} photos -> {target.name}")
        if dry_run:
            continue
        target.mkdir()
        for photo in photos:
            source_dirs.add(photo.path.parent)
            shutil.move(str(photo.path), str(target / photo.path.name))

    # Remove source folders left empty after the move
    for folder in source_dirs:
        if not any(folder.iterdir()):
            folder.rmdir()
            print(f"Removed empty folder {folder.name}")

    if dry_run:
        print("Dry run: no files were moved.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", type=Path, default=DEFAULT_ROOT,
                        help=f"images root folder (default: {DEFAULT_ROOT})")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="show what would be done without moving files")
    args = parser.parse_args()

    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"Folder not found: {root}", file=sys.stderr)
        return 1
    organize(root, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
