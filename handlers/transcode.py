import os
import shutil
from pathlib import Path
from threading import Semaphore

from pydub import AudioSegment
from tinytag import TinyTag

# Prevent spawning too many processes
EXPORT_SEMAPHORE_COUNT = (os.cpu_count() or 2) // 2

BITRATE_MAP = {
    "mp3": "320k",
    "aac": "256k",
}


def get_bitrate_from_format(out_format: str) -> str | None:
    return BITRATE_MAP.get(out_format.lower())


def transcode_track(
    track_path: Path, out_path: Path, out_format: str, export_semaphore: Semaphore
) -> str:
    in_format = track_path.suffix[1:]
    new_file = out_path.joinpath(f"{track_path.stem}.{out_format}")

    if new_file.exists():
        return str(new_file)

    if in_format == out_format:
        return str(track_path.copy(new_file))

    if in_format == "aif":
        in_format = "aiff"

    with export_semaphore:
        segment = AudioSegment.from_file(track_path, format=in_format)
        tags = TinyTag.get(track_path)

        segment.export(
            new_file,
            format=out_format,
            bitrate=get_bitrate_from_format(out_format),
            tags=tags.as_dict(),
        )
    return str(new_file)


def change_track_location(
    track_location: str,
    out_dir: str,
    out_format: str | None,
    export_semaphore: Semaphore,
) -> str:
    track_path = Path(track_location)
    out_dir_path = Path(out_dir)
    if out_format:
        return transcode_track(track_path, out_dir_path, out_format, export_semaphore)
    else:
        out_file_path = out_dir_path.joinpath(track_path.name)
        shutil.copy2(track_path, out_file_path)
        return str(out_file_path)
