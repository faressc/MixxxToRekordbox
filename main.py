import argparse

from handlers.export import export_to_rekordbox_xml
from models import (
    CollectionType,
    KeyType,
)
from offset_handlers import ACCEPTED_MP3_DECODERS, Mp3Decoder

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument(
    "--out-dir", type=str, help="Outputs tracks to a new directory."
)
arg_parser.add_argument(
    "--format",
    type=str,
    help="Change the file format of the tracks, requires --out-dir to be set.",
)
arg_parser.add_argument(
    "-a",
    "--export-all",
    action="store_true",
    help="Export all playlists without prompting. May take a while and fill up your drive if --out-dir is set.",
)
arg_parser.add_argument(
    "--mixxx-db-location", type=str, help="Specify Mixxx's DB location if non-standard."
)
arg_parser.add_argument(
    "--key-type",
    type=KeyType,
    help=f"Specify a key type to export: {[kt.value for kt in KeyType]}, defaults to {KeyType.LANCELOT}",
)
arg_parser.add_argument(
    "--mp3-decoder",
    choices=ACCEPTED_MP3_DECODERS,
    help="The decoder Mixxx uses for MP3s, needed to align beat grids and cues. Defaults to CoreAudio on macOS and MAD elsewhere.",
)
arg_parser.add_argument(
    "-c",
    "--use-crates",
    action="store_true",
    help="Source the tracks from crates instead of playlists, XML output will still be playlists.",
)
arg_parser.add_argument(
    "--replace-prefix",
    type=str,
    metavar="SRC=DST",
    help="Rewrite track locations starting with SRC to start with DST in the XML, "
    "e.g. '/run/media/user/music-lib=/Volumes/music-lib' when the export is used on another OS.",
)


def main() -> None:
    args = arg_parser.parse_args()
    out_format: str | None = args.format
    out_dir: str | None = args.out_dir
    export_all: bool = args.export_all
    mixxx_db_location: str | None = args.mixxx_db_location
    key_type: KeyType = args.key_type or KeyType.LANCELOT
    mp3_decoder: Mp3Decoder | None = args.mp3_decoder
    use_crates: bool = args.use_crates
    collection_type: CollectionType = "crates" if use_crates else "playlists"

    location_prefix: tuple[str, str] | None = None
    if args.replace_prefix:
        src, sep, dst = args.replace_prefix.partition("=")
        if not sep or not src:
            arg_parser.error("--replace-prefix must be of the form SRC=DST")
        location_prefix = (src, dst)

    export_to_rekordbox_xml(
        out_format,
        out_dir,
        export_all,
        mixxx_db_location,
        key_type,
        collection_type,
        mp3_decoder,
        location_prefix=location_prefix,
    )


if __name__ == "__main__":
    main()
