"""Organize GoPro time-lapse photos into one folder per time-lapse.

GoPro time-lapse files are named ``GxxxYYYY.JPG`` where ``xxx`` identifies the
time-lapse group and ``YYYY`` is the incremental photo number inside it.
Group ids wrap around (001-999), so the same id is reused by unrelated
time-lapses over time. Photos are therefore sorted chronologically and a new
time-lapse starts whenever the group id changes or the time gap between two
consecutive photos exceeds a threshold.

Each time-lapse is moved into a folder named after the capture date/time of
its first photo (``yyyyMMdd_HHmmss``), created directly under the images root.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

FILE_PATTERN = re.compile(r"^G(?P<group>\d{3})(?P<seq>\d+)\.jpe?g$", re.IGNORECASE)
TARGET_DIR_PATTERN = re.compile(r"^\d{8}_\d{6}(_\d+)?$")
EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132
EXIF_IFD = 0x8769
DEFAULT_ROOT = Path(__file__).resolve().parent / "images"
# The longest GoPro Session 5 time-lapse interval is 60 s
DEFAULT_MAX_GAP_SECONDS = 120


@dataclass(frozen=True)
class Photo:
    path: Path
    group: str
    seq: int
    taken: datetime

    @property
    def sort_key(self) -> tuple[datetime, str, int]:
        # Folder and sequence break ties between photos taken in the same second
        return self.taken, self.path.parent.name, self.seq


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


def collect_photos(root: Path) -> list[Photo]:
    """Find time-lapse photos in the source subfolders, sorted chronologically."""
    photos: list[Photo] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        # Skip folders produced by a previous run
        if TARGET_DIR_PATTERN.match(folder.name):
            continue
        print(f"Scanning {folder.name}...")
        for file in folder.iterdir():
            match = FILE_PATTERN.match(file.name)
            if file.is_file() and match:
                photos.append(Photo(file, match["group"], int(match["seq"]), read_capture_time(file)))
    photos.sort(key=lambda p: p.sort_key)
    return photos


def split_timelapses(photos: list[Photo], max_gap: timedelta) -> list[list[Photo]]:
    """Split chronologically sorted photos into individual time-lapses."""
    timelapses: list[list[Photo]] = []
    for photo in photos:
        current = timelapses[-1] if timelapses else None
        if current and current[-1].group == photo.group and photo.taken - current[-1].taken <= max_gap:
            current.append(photo)
        else:
            timelapses.append([photo])
    return timelapses


def unique_target_dir(root: Path, name: str, reserved: set[str]) -> Path:
    """Return a non-existing, non-reserved folder path, adding a numeric suffix on collision."""
    target = root / name
    counter = 1
    while target.exists() or target.name in reserved:
        target = root / f"{name}_{counter}"
        counter += 1
    return target


def organize(root: Path, max_gap: timedelta, dry_run: bool) -> None:
    photos = collect_photos(root)
    if not photos:
        print(f"No time-lapse photos found in {root}")
        return

    source_dirs: set[Path] = set()
    # In dry run folders are not created, so planned names are tracked as well
    planned: set[str] = set()
    for timelapse in split_timelapses(photos, max_gap):
        first, last = timelapse[0], timelapse[-1]
        target = unique_target_dir(root, first.taken.strftime("%Y%m%d_%H%M%S"), planned)
        planned.add(target.name)

        folders = sorted({p.path.parent.name for p in timelapse})
        print(f"Group {first.group}: {len(timelapse)} photos "
              f"({first.path.name} .. {last.path.name}, {', '.join(folders)}) -> {target.name}")
        if dry_run:
            continue
        target.mkdir()
        for photo in timelapse:
            destination = target / photo.path.name
            if destination.exists():
                print(f"  warning: {destination} already exists, {photo.path} left in place")
                continue
            source_dirs.add(photo.path.parent)
            shutil.move(str(photo.path), str(destination))

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
    parser.add_argument("--max-gap", type=int, default=DEFAULT_MAX_GAP_SECONDS, metavar="SECONDS",
                        help="max seconds between two photos of the same time-lapse "
                             f"(default: {DEFAULT_MAX_GAP_SECONDS})")
    args = parser.parse_args()

    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"Folder not found: {root}", file=sys.stderr)
        return 1
    organize(root, timedelta(seconds=args.max_gap), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
