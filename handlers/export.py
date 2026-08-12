from functools import partial
from multiprocessing import Manager
from multiprocessing.managers import DictProxy
from multiprocessing.pool import Pool
from pathlib import Path
from threading import Semaphore

from lxml import etree  # type: ignore[attr-defined]
from tqdm import tqdm

from handlers import sql as sql_handlers
from handlers.transcode import EXPORT_SEMAPHORE_COUNT, change_track_location
from models import (
    RATING_MAP,
    BeatGridInfo,
    CollectionType,
    CueColour,
    CuePoint,
    ExportedTrack,
    KeyType,
    TrackContext,
    mixxx_colour_to_rekordbox,
)
from offset_handlers import Mp3Decoder, flush_offset_errors
from rekordbox_gen import (
    TRACK_COLLECTION,
    encode_xml_element,
    format_track_id,
    generate_xml,
    set_location_prefix,
)


def mixxx_cuepos_to_ms(cuepos: int, samplerate: int, channels: int) -> float:
    # Keep sub-millisecond precision so cues land exactly where Mixxx has them
    return (cuepos * 1000.0) / (samplerate * channels)


def get_track_info(
    track_id: str,
    out_dir: str | None,
    out_format: str | None,
    key_type: KeyType,
    export_semaphore: Semaphore,
) -> tuple[TrackContext, BeatGridInfo | None] | None:
    track_info = sql_handlers.get_track_info(track_id)
    if track_info:
        (
            samplerate,
            channels,
            duration,
            title,
            artist,
            album,
            genre,
            bpm,
            beats,
            beats_version,
            key_id,
            rating,
            colour,
            track_location,
        ) = track_info
    else:
        return None

    if not Path.exists(track_location):
        print(f"File not found at {track_location}")
        return None

    # out_format without out_dir is rejected in export_to_rekordbox_xml
    if out_dir:
        track_location = change_track_location(
            track_location, out_dir, out_format, export_semaphore
        )
    if track_location.endswith(".ogg"):
        temp_path = Path.home().absolute() / "temp"
        temp_path.mkdir(exist_ok=True)
        print(f"{track_location} cannot be read by Rekordbox, converting to .mp3")
        track_location = change_track_location(
            track_location,
            str(temp_path),
            "mp3",
            export_semaphore,
        )
        print(f"New track created at: {track_location}")

    return TrackContext(
        id=track_id,
        samplerate=int(samplerate),
        channels=int(channels),
        duration=int(duration),
        title=title or "",
        artist=artist or "",
        album=album or "",
        genre=genre or "",
        bpm=float(bpm) or 0.0,
        location=track_location,
        key=key_type.get_key(key_id),
        rating=RATING_MAP[rating],
        colour=mixxx_colour_to_rekordbox(colour),
    ), (BeatGridInfo(beats, beats_version, samplerate) if beats else None)


# Mixxx stores intro/outro as a single range, Rekordbox has no equivalent,
# so their ends are exported as named memory cues
RANGE_CUE_NAMES = {6: "Intro", 7: "Outro"}


def get_cue_points(
    track_id: str,
    samplerate: int,
    channels: int,
) -> list[CuePoint]:
    cue_points = []
    for (
        cue_index,
        cue_position,
        cue_type,
        length,
        color,
        label,
    ) in sql_handlers.get_cue_points(track_id):
        position_ms = mixxx_cuepos_to_ms(int(cue_position), samplerate, channels)
        end_ms = mixxx_cuepos_to_ms(
            int(cue_position) + int(length), samplerate, channels
        )
        colour = CueColour(hex(color or 0))

        if cue_type in RANGE_CUE_NAMES:
            name = RANGE_CUE_NAMES[cue_type]
            if int(cue_position) >= 0:
                cue_points.append(
                    CuePoint(
                        cue_type,
                        cue_index,
                        position_ms,
                        position_ms,
                        colour,
                        f"{name} start",
                    )
                )
            if int(length) > 0:
                cue_points.append(
                    CuePoint(cue_type, cue_index, end_ms, end_ms, colour, f"{name} end")
                )
            continue

        cue_points.append(
            CuePoint(cue_type, cue_index, position_ms, end_ms, colour, label or "")
        )
    return cue_points


def get_exported_track(
    track_id: str,
    out_dir: str | None,
    out_format: str | None,
    key_type: KeyType,
    mp3_decoder: Mp3Decoder | None,
    export_semaphore: Semaphore,
    track_collection: DictProxy,
) -> ExportedTrack | None:
    if track_id in track_collection:
        return track_collection[track_id]

    track_info = get_track_info(
        track_id, out_dir, out_format, key_type, export_semaphore
    )
    if not track_info:
        print(f"No info found for Track {track_id}")
        return None

    track_context, beat_grid = track_info
    return ExportedTrack(
        id=format_track_id(track_id),
        track_context=track_context,
        beat_grid=beat_grid,
        cue_points=get_cue_points(
            track_id, track_context.samplerate, track_context.channels
        ),
        mp3_decoder=mp3_decoder,
    )


def init_track_worker(db_location: str) -> None:
    sql_handlers.set_db_location(db_location)


def get_data_for_tracks(
    track_ids: list[str],
    out_dir: str | None,
    out_format: str | None,
    key_type: KeyType,
    mp3_decoder: Mp3Decoder | None,
    db_location: str | None,
) -> list[ExportedTrack]:
    manager = Manager()
    export_semaphore = manager.Semaphore(EXPORT_SEMAPHORE_COUNT)
    track_collection = manager.dict()
    track_collection.update(TRACK_COLLECTION)
    with Pool(
        # os.cpu_count() // (2 if out_format else 1),
        initializer=init_track_worker,
        initargs=(db_location,),
    ) as pool:
        return list(
            tqdm(
                (
                    track
                    for track in pool.imap(
                        partial(
                            get_exported_track,
                            out_dir=out_dir,
                            out_format=out_format,
                            key_type=key_type,
                            mp3_decoder=mp3_decoder,
                            export_semaphore=export_semaphore,
                            track_collection=track_collection,
                        ),
                        track_ids,
                        chunksize=1 if out_format else 2,
                    )
                    if track
                ),
                unit="track",
                total=len(track_ids),
            )
        )


def append_collection_to_element(
    collection_id: str,
    collection_name: str,
    xml_element: etree.Element,
    export_all: bool,
    collection_type: CollectionType,
    out_dir: str | None,
    out_format: str | None,
    key_type: KeyType,
    mp3_decoder: Mp3Decoder | None,
    db_location: str | None,
) -> etree.Element:
    if (
        not export_all
        and input(f"Export {collection_name}? [y/n]").lower().strip() != "y"
    ):
        return xml_element

    print(f"{collection_name}:")
    track_ids = sql_handlers.get_collection_tracks(collection_type, collection_id)

    return generate_xml(
        get_data_for_tracks(
            track_ids, out_dir, out_format, key_type, mp3_decoder, db_location
        ),
        collection_name,
        xml_element,
    )


def export_to_rekordbox_xml(
    out_format: str | None,
    out_dir: str | None,
    export_all: bool,
    mixxx_db_location: str | None,
    key_type: KeyType,
    collection_type: CollectionType,
    mp3_decoder: Mp3Decoder | None = None,
    location_prefix: tuple[str, str] | None = None,
) -> None:
    db_location = sql_handlers.get_mixxx_db_location(mixxx_db_location)
    if out_format and not out_dir:
        raise Exception("Output directory must be specified if changing file formats.")
    sql_handlers.set_db_location(db_location)
    if location_prefix:
        set_location_prefix(*location_prefix)

    collections = sql_handlers.get_collections(collection_type)

    print(f"Preparing to export {len(collections)} {collection_type}s...\n")
    xml_element = None
    for collection in collections:
        collection_id = collection[0]
        collection_name = collection[1]
        xml_element = append_collection_to_element(
            collection_id,
            collection_name,
            xml_element,
            export_all,
            collection_type,
            out_dir,
            out_format,
            key_type,
            mp3_decoder,
            db_location,
        )
        flush_offset_errors()
        print("")
    if xml_element is None:
        print(f"No {collection_type} were exported, rekordbox.xml was not written")
        return
    with open("rekordbox.xml", "wb") as fd:
        fd.write(encode_xml_element(xml_element))
        fd.close()
    print("done")
