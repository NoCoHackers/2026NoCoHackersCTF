"""Deterministic PTS Trace segment files for the Midnight Mountain Ave Mile.

Poudre Tracking Systems' "Trace" recorders are watch-style devices worn
by the runners: they record continuously and emit ordinary GPX, carved
into quarter-mile segments by the logger. Everything the certification
tree protects is built here, byte for byte, from the organizers'
official course file (course.gpx - the real Mountain Ave Mile route),
so the PTS root is stable across builds and CI. server.py derives every
hash at boot from these bytes; nothing is trusted from storage.

Course: one mile east along Mountain Avenue, downhill from the City Park
end into Old Town. Gun fires at midnight local (06:00Z -- MDT is still
in force on Halloween).

The incident: mid-race the PTS logger stopped working. It had already
pushed the certified root to the results feed and flushed the first
three quarter segments to the archive. The finish segment -- the one
that would have named the finisher -- existed only in the logger's
memory and never made it out. It is generated here solely so the tree,
and the root PTS certified, are well defined; the three quarter segments
survive and are served from /segments/.
"""

from __future__ import annotations

import bisect
import datetime
import math
import os
import xml.etree.ElementTree as ET

COURSE_FILE = os.path.join(os.path.dirname(__file__), "course.gpx")

# --- the race -----------------------------------------------------------------

CHAMPION_BIB = "1313"          # the leader's recorder, as read in every segment
CHAMPION_NAME = "The Headless Harrier"   # led all three surviving segments
CHAMPION_TIME = "3:43.7"       # the gun-clock time of the finish; who crossed, nobody can prove
CHAMPION_TENTHS = 2237         # the same, in tenths of a second

# slug, results-page label, where along the course the quarter falls
SEGMENTS = (
    ("seg_025", "TRACE 0.25", "by Shields Street"),
    ("seg_050", "TRACE 0.50", "past Howes Street"),
    ("seg_075", "TRACE 0.75", "at Loomis Avenue"),
    ("finish", "TRACE FINISH", "the downtown line"),
)

# Quarter splits in tenths: 56.9 + 56.2 + 55.6 + 55.0 = 223.7. The leader
# negative-splits, as headless harriers do. Whether he is the finisher
# is the question the lost segment would have answered.
SPLITS = (569, 562, 556, 550)
GUN = datetime.datetime(2026, 10, 31, 6, 0, 0, tzinfo=datetime.timezone.utc)


# --- the official course ---------------------------------------------------------

def _course_points() -> list[tuple[float, float, float]]:
    """Lat/lon/ele along the official course, deduplicated, in order."""
    ns = "{http://www.topografix.com/GPX/1/1}"
    root = ET.parse(COURSE_FILE).getroot()
    pts: list[tuple[float, float, float]] = []
    for p in root.iter(ns + "trkpt"):
        lat, lon = float(p.get("lat")), float(p.get("lon"))
        ele_el = p.find(ns + "ele")
        ele = float(ele_el.text) if ele_el is not None else 0.0
        if pts and (pts[-1][0], pts[-1][1]) == (lat, lon):
            continue  # ridewithgps emits a duplicated first point
        pts.append((lat, lon, ele))
    return pts


POINTS = _course_points()


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """Haversine distance in meters; the course is short and flat enough."""
    r = 6371000.0
    la1, lo1 = math.radians(a[0]), math.radians(a[1])
    la2, lo2 = math.radians(b[0]), math.radians(b[1])
    h = math.sin((la2 - la1) / 2) ** 2 + \
        math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


CUM = [0.0]
for i in range(1, len(POINTS)):
    CUM.append(CUM[-1] + _dist(POINTS[i - 1], POINTS[i]))
TOTAL = CUM[-1]


def _at(frac: float) -> tuple[float, float, float]:
    """Interpolate a lat/lon/ele at a fraction of total course distance."""
    d = min(max(frac, 0.0), 1.0) * TOTAL
    i = min(bisect.bisect_right(CUM, d) - 1, len(POINTS) - 2)
    span = CUM[i + 1] - CUM[i] or 1.0
    t = (d - CUM[i]) / span
    a, b = POINTS[i], POINTS[i + 1]
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _time(tenths: int) -> str:
    stamp = GUN + datetime.timedelta(microseconds=tenths * 100_000)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S") + ".%dZ" % (stamp.microsecond // 100000)


# --- the segment files -----------------------------------------------------------

def _segment(idx: int) -> bytes:
    """The leader's recorder data for one quarter of the course.

    Five samples per segment, cut from the official course geometry,
    paced by the quarter split.
    """
    _slug, label, _place = SEGMENTS[idx]
    t0 = sum(SPLITS[:idx])
    t1 = t0 + SPLITS[idx]

    pts = []
    for j in range(5):
        frac = (idx + j / 4) / 4
        lat, lon, ele = _at(frac)
        pts.append(
            '      <trkpt lat="%.6f" lon="%.6f"><ele>%.1f</ele><time>%s</time></trkpt>'
            % (lat, lon, ele, _time(t0 + round((t1 - t0) * j / 4)))
        )

    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="PTS-Trace/1.0"'
        ' xmlns="http://www.topografix.com/GPX/1/1">\n'
        "  <metadata>\n"
        "    <name>MAM-2026 %s BIB-%s</name>\n"
        "    <desc>Mountain Ave Mile 2026 - %s - %s - %s</desc>\n"
        "    <keywords>MAM-2026,trace</keywords>\n"
        "  </metadata>\n"
        "  <trk>\n"
        "    <name>BIB-%s %s</name>\n"
        "    <trkseg>\n%s\n"
        "    </trkseg>\n"
        "  </trk>\n"
        "</gpx>\n"
    ) % (
        label, CHAMPION_BIB,
        label, CHAMPION_NAME, CHAMPION_TIME,
        CHAMPION_BIB, label,
        "\n".join(pts),
    )
    return body.encode()


def segments() -> dict[str, bytes]:
    return {slug: _segment(i) for i, (slug, _label, _place) in enumerate(SEGMENTS)}


def course_bytes() -> bytes:
    """The organizers' official course file, served verbatim."""
    with open(COURSE_FILE, "rb") as fh:
        return fh.read()
