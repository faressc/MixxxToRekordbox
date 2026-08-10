from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Literal

from offset_handlers import Mp3Decoder, get_offset_sec
from proto.beats_pb2 import BeatGrid, BeatMap  # type: ignore[attr-defined]

CollectionType = Literal["playlists", "crates"]


SERATO_COLOURS = [
    "0xc02626",  # Red
    "0xf8821a",  # Orange
    "0xfac313",  # Yellow
    "0x1fad26",  # Green
    "0x00FFFF",  # Cyan
    "0x173ba2",  # Blue
    "0x6823b6",  # Indigo
    "0xce359e",  # Light Magenta
]

# 0 star = "0", 1 star = "51", 2 stars = "102", 3 stars = "153", 4 stars = "204", 5 stars = "255"
RATING_MAP = {0: 0, 1: 51, 2: 102, 3: 153, 4: 204, 5: 255}

# The only track colours Rekordbox recognises when importing XML.
# Lemon is listed before Orange so that Mixxx's default yellow,
# which is equidistant to both, resolves to Lemon.
REKORDBOX_TRACK_COLOURS = [
    "0xFF007F",  # Rose
    "0xFF0000",  # Red
    "0xFFFF00",  # Lemon
    "0xFFA500",  # Orange
    "0x00FF00",  # Green
    "0x25FDE9",  # Turquoise
    "0x0000FF",  # Blue
    "0x660099",  # Violet
]


def mixxx_colour_to_rekordbox(colour: int | None) -> str:
    if colour is None:
        return ""
    r, g, b = (colour >> 16) & 0xFF, (colour >> 8) & 0xFF, colour & 0xFF

    def distance(rekordbox_colour: str) -> int:
        rb = int(rekordbox_colour, 0)
        rb_r, rb_g, rb_b = (rb >> 16) & 0xFF, (rb >> 8) & 0xFF, rb & 0xFF
        return (r - rb_r) ** 2 + (g - rb_g) ** 2 + (b - rb_b) ** 2

    return min(REKORDBOX_TRACK_COLOURS, key=distance)


LancelotKey = Literal[
    "1A",
    "1B",
    "2A",
    "2B",
    "3A",
    "3B",
    "4A",
    "4B",
    "5A",
    "5B",
    "6A",
    "6B",
    "7A",
    "7B",
    "8A",
    "8B",
    "9A",
    "9B",
    "10A",
    "10B",
    "11A",
    "11B",
    "12A",
    "12B",
]
MusicalKey = Literal[
    "A",
    "Am",
    "Ab",
    "Abm",
    "C",
    "Cm",
    "D",
    "Dm",
    "Db",
    "Dbm",
    "E",
    "Em",
    "Eb",
    "Ebm",
    "F",
    "Fm",
    "F#",
    "F#m",
    "G",
    "Gm",
    "Bb",
    "Bbm",
    "B",
    "Bm",
]

LANCELOT_MAP: dict[int, LancelotKey | Literal[""]] = {
    21: "1A",
    12: "1B",
    16: "2A",
    7: "2B",
    23: "3A",
    2: "3B",
    18: "4A",
    9: "4B",
    13: "5A",
    4: "5B",
    20: "6A",
    11: "6B",
    15: "7A",
    6: "7B",
    22: "8A",
    1: "8B",
    17: "9A",
    8: "9B",
    24: "10A",
    3: "10B",
    19: "11A",
    10: "11B",
    14: "12A",
    5: "12B",
    0: "",
}

MUSICAL_MAP: dict[int, MusicalKey | Literal[""]] = {
    21: "Abm",
    12: "B",
    16: "Ebm",
    7: "F#",
    23: "Bbm",
    2: "Db",
    18: "Fm",
    9: "Ab",
    13: "Cm",
    4: "Eb",
    20: "Gm",
    11: "Bb",
    15: "Dm",
    6: "F",
    22: "Am",
    1: "C",
    17: "Em",
    8: "G",
    24: "Bm",
    3: "D",
    19: "F#m",
    10: "A",
    14: "Dbm",
    5: "E",
    0: "",
}


class KeyType(StrEnum):
    LANCELOT = auto()
    MUSICAL = auto()

    def get_key(self, key_id: int) -> str:
        match self:
            case KeyType.LANCELOT:
                return LANCELOT_MAP[key_id]
            case KeyType.MUSICAL:
                return MUSICAL_MAP[key_id]


BeatsVersion = Literal["BeatGrid-2.0", "BeatMap-1.0"]


@dataclass
class BeatGridInfo:
    start_pos: int
    beats_version: BeatsVersion
    samplerate: float
    bpm: float | None = None
    offset_sec: float = 0.0

    def __init__(
        self,
        beat_bytes: bytes,
        beats_version: BeatsVersion,
        samplerate: float,
    ):
        self.beats_version = beats_version
        self.samplerate = samplerate
        match beats_version:
            case "BeatGrid-2.0":
                beatgrid = BeatGrid()
                beatgrid.ParseFromString(beat_bytes)
                self.start_pos = beatgrid.first_beat.frame_position
                self.bpm = beatgrid.bpm.bpm
            case "BeatMap-1.0":
                # Just use the first available beat for now, we can get BPM from the track context
                beatmap = BeatMap()
                beatmap.ParseFromString(beat_bytes)
                first_beat = next(
                    beat
                    for beat in sorted(beatmap.beat, key=lambda b: -b.source)
                    if beat.enabled and beat.frame_position > 1
                )
                self.start_pos = first_beat.frame_position

    @property
    def start_sec(self) -> float:
        start_sec = self.start_pos / self.samplerate

        if not self.bpm:
            return start_sec + self.offset_sec
        interval_sec = 60 / self.bpm
        beats_per_bar = 4

        return (start_sec % (beats_per_bar * interval_sec)) + self.offset_sec


@dataclass
class TrackContext:
    id: str
    title: str
    artist: str
    album: str
    genre: str
    duration: int
    location: str
    samplerate: int
    channels: int
    bpm: float
    key: str  # a LancelotKey, a MusicalKey or "" when unset
    rating: int
    colour: str


@dataclass
class CueColour:
    hex_rgb: str  # 0xRRGGBB

    @property
    def r_int(self) -> int:
        return int(self.hex_rgb[:4], 0)

    @property
    def g_int(self) -> int:
        return int(self.hex_rgb[:2] + self.hex_rgb[4:6], 0)

    @property
    def b_int(self) -> int:
        return int(self.hex_rgb[:2] + self.hex_rgb[6:8], 0)


@dataclass
class CuePoint(dict):
    cue_type: int
    cue_index: int
    cue_position: float
    cue_end: float
    cue_color: CueColour
    cue_text: str

    def __init__(
        self,
        cue_type: int,
        cue_index: int,
        cue_position: float,
        cue_end: float,
        cue_color: CueColour,
        cue_text: str = "",
    ):
        self.cue_index = cue_index
        self.cue_position = cue_position
        self.cue_end = cue_end
        self.cue_color = cue_color
        self.cue_text = cue_text

        if cue_type == 4:  # Mixxx loops match Rekordbox loops
            self.cue_type = 4
        elif cue_type == 2:
            # Mixxx's main cue is Rekordbox's Load cue, used for autocue
            self.cue_type = 3
        else:
            # Hot cues (1) and intro/outro markers (6/7) map to regular
            # Rekordbox cues; a cue_index of -1 (Mixxx's hotcue column)
            # makes them memory cues
            self.cue_type = 0


@dataclass
class ExportedTrack:
    id: str
    track_context: TrackContext
    beat_grid: BeatGridInfo | None = None
    cue_points: list[CuePoint] = field(default_factory=list)
    offset_sec: float = 0.0

    def __init__(
        self,
        id: str,
        track_context: TrackContext,
        beat_grid: BeatGridInfo | None,
        cue_points: list[CuePoint],
        mp3_decoder: Mp3Decoder | None = None,
    ):
        self.id = id
        self.track_context = track_context
        self.offset_sec = get_offset_sec(self.track_context.location, mp3_decoder)
        if beat_grid:
            self._add_beat_grid(beat_grid)
        self.cue_points = []
        for cue_point in cue_points:
            self._add_new_cue_point(cue_point)

    def _add_beat_grid(self, beat_grid: BeatGridInfo):
        beat_grid.offset_sec = self.offset_sec
        beat_grid.bpm = beat_grid.bpm or self.track_context.bpm
        self.beat_grid = beat_grid

    def _add_new_cue_point(self, cue_point: CuePoint):
        if len(cue_point.cue_color.hex_rgb) != 8:
            cue_point.cue_color.hex_rgb = SERATO_COLOURS[
                len(self.cue_points) % len(SERATO_COLOURS)
            ]
        # Cue positions are in milliseconds, the decoder offset in seconds
        cue_point.cue_position += self.offset_sec * 1000
        cue_point.cue_position = max(0, cue_point.cue_position)
        if cue_point.cue_type == 4:  # Loop Hot Cue
            cue_point.cue_end += self.offset_sec * 1000
            cue_point.cue_end = max(0, cue_point.cue_end)

        self.cue_points.append(cue_point)
