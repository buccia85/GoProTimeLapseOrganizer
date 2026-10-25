# GoPro TimeLapse Organizer

A small Python script that sorts GoPro time-lapse photos into one folder per time-lapse.

GoPro cameras store time-lapse photos in DCIM folders such as `100GOPRO`, `101GOPRO`, …
with file names like `G0032336.JPG`. When you have thousands of photos from many sessions,
it is hard to tell where one time-lapse ends and the next begins. This script groups them
and moves each time-lapse into its own folder, named after the date and time of its first photo:

```
images/
├── 142GOPRO/                 images/
│   ├── G0012317.JPG          ├── 20250406_110156/   (group 001, 13 photos)
│   ├── ...           ──►     ├── 20250406_110424/   (group 002, 6 photos)
│   └── G0033312.JPG          ├── 20250406_110436/   (group 003, 1976 photos from 2 folders)
├── 143GOPRO/                 └── 20261024_174351/   (group 002, 999 photos)
└── 266GOPRO/
```

Developed and tested with photos from a **GoPro HERO5 Session**. Other GoPro models that use
the same `Gxxxyyyy.JPG` naming scheme should work as well.

## How it works

GoPro time-lapse file names have the form `G` + `xxx` + `yyyy`:

- `xxx` is the time-lapse **group** id (3 digits);
- `yyyy` is an incremental photo number.

Two details make a naive "group by `xxx`" approach unreliable:

1. **Group ids wrap around** (001 → 999 → 001), so the same id is reused by unrelated
   time-lapses shot months apart.
2. **A single time-lapse can span several folders**, because the camera starts a new DCIM
   folder every 999 files.

The script handles both in two passes:

1. **Per-folder scan** – inside each folder, photos are grouped by group id using only their
   file names. Photos of the same group in the same folder are assumed to belong to the same
   time-lapse, and their numbers must be consecutive (see [Safety checks](#safety-checks)).
   Only the EXIF capture time of the first and last photo of each group is read, which keeps
   the scan fast even with hundreds of thousands of files.
2. **Cross-folder merge** – segments with the same group id are sorted by start time and merged
   when one starts within `--max-gap` seconds of the end of the previous one. Merged segments
   can merge again, so a time-lapse spanning any number of folders ends up in a single folder.

Each resulting time-lapse is then **moved** (not copied) into `<root>/yyyyMMdd_HHmmss/`,
using the 24-hour clock. Source folders left empty are removed.

### Safety checks

- If photos of the same group in the same folder are not consecutive
  (e.g. `G0030010.JPG` followed by `G0031234.JPG`), the script stops with an error
  **before moving any file**. All problems found in all folders are listed at once.
- Folders that already match the `yyyyMMdd_HHmmss` pattern are skipped, so running the script
  again on the same root is safe.
- Existing destination folders are never overwritten: a numeric suffix (`_1`, `_2`, …) is added.
- `--dry-run` shows exactly what would happen without touching any file.

## Requirements

- Python 3 (tested with 3.11)
- [Pillow](https://python-pillow.org/), used to read EXIF capture times

## Setup

```bash
git clone https://github.com/<your-user>/GoProTimeLapseOrganizer.git
cd GoProTimeLapseOrganizer
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

## Usage

Copy the GoPro DCIM folders (`100GOPRO`, `101GOPRO`, …) into an `images` folder next to the
script, or pass any other folder as argument.

Always start with a dry run:

```bash
python organize.py --dry-run
```

Then run it for real:

```bash
python organize.py
```

Using a different root folder and gap:

```bash
python organize.py "D:\GoPro" --dry-run --max-gap 5
```

### Options

| Option | Description |
| --- | --- |
| `root` | Folder containing the GoPro DCIM subfolders. Defaults to `images` next to the script. |
| `-n`, `--dry-run` | Show what would be done without moving any file. |
| `--max-gap SECONDS` | Maximum time between the last photo of a folder and the first photo of the next folder for them to be merged into the same time-lapse. Default: `120`. Set it slightly above the longest interval you shoot with (e.g. `5` for 1-second time-lapses). |

### Example output

```
Scanning 142GOPRO...
Scanning 143GOPRO...
Scanning 266GOPRO...
Group 001: 13 photos (G0012317.JPG .. G0012329.JPG, 142GOPRO) -> 20250406_110156
Group 002: 6 photos (G0022330.JPG .. G0022335.JPG, 142GOPRO) -> 20250406_110424
Group 003: 1976 photos (G0032336.JPG .. G0034311.JPG, 142GOPRO, 143GOPRO) -> 20250406_110436
Group 002: 999 photos (G0021000.JPG .. G0021998.JPG, 266GOPRO) -> 20261024_174351

Summary
  Files parsed: 2994
  Folders to create (distinct time-lapses): 4
  Duration, all (4 time-lapses): min 0:00:03, max 0:32:55, avg 0:12:39
  Duration, 60+ photos (2 time-lapses): min 0:16:38, max 0:32:55, avg 0:24:46
  Photo dates: 2025-04-06 11:01:56 .. 2026-10-24 18:00:29
Dry run: no files were moved.
```

The exit code is `0` on success, `1` if the root folder does not exist and `2` if
non-consecutive photos were found.

## Notes

- Folder names use the **camera clock** stored in EXIF (`DateTimeOriginal`). If the camera
  clock was wrong (e.g. not adjusted for daylight saving time), the folder names will be too.
  When a photo has no EXIF date, the file modification time is used instead.
- Photos are moved, not copied. Keep a backup until you have checked the result.

## License

Released under the [MIT License](LICENSE): you are free to use, modify and redistribute it
for any purpose, including commercial use, as long as the copyright notice is kept.
