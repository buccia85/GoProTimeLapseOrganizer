"""Organize GoPro time-lapse photos into one folder per time-lapse.

GoPro time-lapse files are named ``GxxxYYYY.JPG`` where ``xxx`` identifies the
time-lapse group and ``YYYY`` is the incremental photo number.
Group ids wrap around (001-999), so the same id is reused by unrelated
time-lapses over time, and a single time-lapse may span several folders.

To keep things fast, only the first and last photo of each group inside a
folder are read (one segment per folder and group). Segments with the same
group id are then merged across folders when one starts right after the
previous one ends.

Each time-lapse is moved into a folder named after the capture date/time of
its first photo (``yyyyMMdd_HHmmss``), created directly under the images root.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
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


@dataclass
class Segment:
    """Photos of one group, sorted by sequence, possibly spanning several folders."""

    group: str
    start: datetime
    end: datetime
    photos: list[Path] = field(default_factory=list)

    @property
    def folders(self) -> list[str]:
        return sorted({p.parent.name for p in self.photos})


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


def scan_folder(folder: Path) -> list[Segment]:
    """Build one segment per group found in the folder, reading only its first and last photo."""
    by_group: dict[str, list[tuple[int, Path]]] = defaultdict(list)
    for file in folder.iterdir():
        match = FILE_PATTERN.match(file.name)
        if match and file.is_file():
            by_group[match["group"]].append((int(match["seq"]), file))

    segments = []
    for group, entries in by_group.items():
        entries.sort()
        photos = [path for _, path in entries]
        start = read_capture_time(photos[0])
        end = read_capture_time(photos[-1]) if len(photos) > 1 else start
        segments.append(Segment(group, start, end, photos))
    return segments


def collect_segments(root: Path) -> list[Segment]:
    """Scan all source subfolders of root."""
    segments: list[Segment] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        # Skip folders produced by a previous run
        if TARGET_DIR_PATTERN.match(folder.name):
            continue
        print(f"Scanning {folder.name}...")
        segments.extend(scan_folder(folder))
    return segments


def merge_segments(segments: list[Segment], max_gap: timedelta) -> list[Segment]:
    """Merge segments of the same group where one starts right after the other ends.

    Segments are sorted by start time and swept once: each segment is appended
    to the previous merged one when the gap is small enough. Since a merged
    segment takes the end of its last part, chains of any length (A+B+C, or
    (A+B)+(C+D)) collapse in a single pass, giving the same result as merging
    repeatedly until nothing changes.
    """
    by_group: dict[str, list[Segment]] = defaultdict(list)
    for segment in segments:
        by_group[segment.group].append(segment)

    merged: list[Segment] = []
    for group_segments in by_group.values():
        group_segments.sort(key=lambda s: (s.start, s.folders))
        current = group_segments[0]
        for segment in group_segments[1:]:
            if timedelta(0) <= segment.start - current.end <= max_gap:
                current = Segment(current.group, current.start, segment.end,
                                  current.photos + segment.photos)
            else:
                merged.append(current)
                current = segment
        merged.append(current)
    merged.sort(key=lambda s: s.start)
    return merged


def unique_target_dir(root: Path, name: str, reserved: set[str]) -> Path:
    """Return a non-existing, non-reserved folder path, adding a numeric suffix on collision."""
    target = root / name
    counter = 1
    while target.exists() or target.name in reserved:
        target = root / f"{name}_{counter}"
        counter += 1
    return target


def organize(root: Path, max_gap: timedelta, dry_run: bool) -> None:
    segments = collect_segments(root)
    if not segments:
        print(f"No time-lapse photos found in {root}")
        return

    source_dirs: set[Path] = set()
    # In dry run folders are not created, so planned names are tracked as well
    planned: set[str] = set()
    for timelapse in merge_segments(segments, max_gap):
        target = unique_target_dir(root, timelapse.start.strftime("%Y%m%d_%H%M%S"), planned)
        planned.add(target.name)

        first, last = timelapse.photos[0], timelapse.photos[-1]
        print(f"Group {timelapse.group}: {len(timelapse.photos)} photos "
              f"({first.name} .. {last.name}, {', '.join(timelapse.folders)}) -> {target.name}")
        if dry_run:
            continue
        target.mkdir()
        for photo in timelapse.photos:
            destination = target / photo.name
            if destination.exists():
                print(f"  warning: {destination} already exists, {photo} left in place")
                continue
            source_dirs.add(photo.parent)
            shutil.move(str(photo), str(destination))

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
                        help="max seconds between the last photo of a folder and the first photo "
                             f"of the next folder in the same time-lapse (default: {DEFAULT_MAX_GAP_SECONDS})")
    args = parser.parse_args()

    root: Path = args.root.resolve()
    if not root.is_dir():
        print(f"Folder not found: {root}", file=sys.stderr)
        return 1
    organize(root, timedelta(seconds=args.max_gap), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
