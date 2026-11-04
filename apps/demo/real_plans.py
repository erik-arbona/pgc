"""Parser of the real study plans (Markdown tables) of EIC and TM.

Implements: D78 (the real plans may be in the repository), D79 (tracks: a subject is common or of
one track), D60 (contact hours = weekly hours x weeks). Pure Python: no Django, no database.

The file is the Markdown version of the official curricular plans (``docs/Planos_EIC_TM.md``):
one ``##`` heading per course, ``###`` headings for the year and semester (semesters numbered
1 to 8 across the course), and for the years in which the course splits, a ``###`` heading per
track followed by ``####`` headings per semester. The parser never guesses: a row whose hours
do not add up, a Total row that does not match its columns, or a subject that is half shared
between tracks stops the load with a message naming it.

What it does not load, and reports instead (``ParsedPlans.skipped``): the UCT tables of the last
semester, which have no weekly hours (Q27), and the optional subjects behind the "Opção
Condicionada" slot (Q28). The practical/laboratory column "P/L" is loaded as the practical class
type (Q26).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# The plans have one combined practical/laboratory column; it is loaded as this class type (Q26).
PL_CLASS_TYPE = "P"

_COURSE = re.compile(r"^## Licenciatura em (?P<name>.+) \((?P<code>\w+)\)\s*$")
_YEAR_SEMESTER = re.compile(r"^### (?P<year>\d)\.º Ano — (?P<sem>\d)\.º Semestre\s*$")
_TRACK = re.compile(r"^### (?P<year>\d)\.º Ano — Percurso \d+: (?P<name>.+) \((?P<code>\w+)\)\s*$")
_VARIANT = re.compile(r"^### (?P<year>\d)\.º Ano — Variante (?P<name>.+?)\s*$")
_TRACK_SEMESTER = re.compile(r"^#### (?P<sem>\d)\.º Semestre — .+$")
_OPTIONAL = re.compile(r"^### \d\.º Semestre — Unidades Curriculares Opcionais")
_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")

_PLAN_COLUMNS = 11  # name, area, T, TP, P/L, weekly total, HC, HEA, total, CTS, notes
_UCT_COLUMNS = 6  # name, HC, HEA, total, CTS, notes


@dataclass(frozen=True)
class PlanRow:
    """One subject row of a plan table, as written."""

    course: str
    semester_number: int
    track: str | None
    name: str
    area: str
    t: Decimal
    tp: Decimal
    pl: Decimal
    hc: Decimal
    hea: Decimal
    ects: Decimal


@dataclass(frozen=True)
class PlanTrack:
    """A track (percurso or variante) of a course and the curricular year it starts in."""

    course: str
    code: str
    name: str
    first_year: int


@dataclass(frozen=True)
class Skipped:
    """Something in the file that is reported and not loaded.

    Attributes:
        kind: ``"uct"`` for a UCT table, ``"optional"`` for an optional subject.
        course: course code.
        description: what was skipped (the subject name, or where the UCT table is).
    """

    kind: str
    course: str
    description: str


@dataclass(frozen=True)
class ParsedPlans:
    """The content of the file, before merging the subjects shared by tracks."""

    courses: dict[str, str]
    tracks: tuple[PlanTrack, ...]
    rows: tuple[PlanRow, ...]
    skipped: tuple[Skipped, ...]


@dataclass(frozen=True)
class PlanSubject:
    """A subject to load: common (no track) or of one track.

    Attributes:
        course: course code.
        code: generated placeholder code, unique in the course and stable between runs.
        name: name of the subject.
        area: scientific area as written (CETE, CHSA, ...); informative only.
        semester_number: semester of the course, 1 to 8.
        curricular_year: curricular year, 1 to 4.
        semester: semester inside the year, 1 or 2.
        track: code of the track, or ``None`` for a common subject or one before the tracks.
        weekly: weekly hours by class type code (zero values left out).
        semester_hours: contact hours of the semester.
        ects: credits.
    """

    course: str
    code: str
    name: str
    area: str
    semester_number: int
    curricular_year: int
    semester: int
    track: str | None
    weekly: dict[str, Decimal]
    semester_hours: Decimal
    ects: Decimal


def semester_position(number: int) -> tuple[int, int]:
    """Return the curricular year and the semester inside the year of a course semester.

    Args:
        number: semester of the course, 1 to 8.

    Returns:
        ``(curricular_year, semester)``; semester 7 is the 1st semester of the 4th year.
    """
    return (number + 1) // 2, 1 if number % 2 == 1 else 2


def _number(cell: str) -> Decimal:
    """Read a table cell as a number; a dash or an empty cell is zero."""
    cell = cell.replace("*", "").strip()
    return Decimal(0) if cell in ("", "–", "-") else Decimal(cell)


def _cells(line: str) -> list[str]:
    """Split a Markdown table line into its trimmed cells."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


class _Table:
    """Running sums of one plan table, checked against its Total row."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.sums = [Decimal(0)] * 8  # T, TP, P/L, weekly, HC, HEA, total, CTS

    def add(self, values: list[Decimal]) -> None:
        """Add the numeric columns of a subject row."""
        self.sums = [a + b for a, b in zip(self.sums, values, strict=True)]

    def check(self, declared: list[Decimal]) -> None:
        """Compare the declared Total row with the sums.

        Raises:
            ValueError: if any column differs.
        """
        if declared != self.sums:
            raise ValueError(
                f"{self.label}: the Total row {declared} differs from the rows {self.sums}"
            )


def parse_plans(text: str, weeks: Decimal = Decimal(15)) -> ParsedPlans:
    """Read the plans from the Markdown text.

    Args:
        text: the content of the plans file.
        weeks: weeks of a semester; contact hours must equal weekly hours times this (D60).

    Returns:
        The courses, tracks, subject rows and what was skipped.

    Raises:
        ValueError: if a row or a Total row is inconsistent, naming it.
    """
    courses: dict[str, str] = {}
    tracks: list[PlanTrack] = []
    rows: list[PlanRow] = []
    skipped: list[Skipped] = []
    course: str | None = None
    semester_number: int | None = None
    track: str | None = None
    optional = False
    label = ""
    table: _Table | None = None
    in_table = False
    table_kind = ""

    for line in text.splitlines():
        if not line.startswith("|"):
            in_table = False
            table = None
            heading = _heading(line)
            if heading is None:
                continue
            kind, data = heading
            if kind == "course":
                course = data["code"]
                courses[course] = data["name"]
                semester_number, track, optional = None, None, False
            elif kind == "other":
                course = None if line.startswith("## ") else course
                if line.startswith("## "):
                    semester_number, track, optional = None, None, False
            elif kind == "semester":
                semester_number, track, optional = data["number"], None, False
            elif kind == "track":
                track = data["code"]
                optional = False
                tracks.append(PlanTrack(course, track, data["name"], data["year"]))
            elif kind == "track_semester":
                semester_number, optional = data["number"], False
            elif kind == "optional":
                semester_number, track, optional = None, None, True
            continue

        if _SEPARATOR.match(line):
            continue
        cells = _cells(line)
        if not in_table:  # first line of a table: the header
            in_table = True
            table_kind = "other"
            if cells[0] == "Unidade Curricular" and len(cells) == _PLAN_COLUMNS:
                table_kind = "plan"
                label = f"{course} semester {semester_number} {track or ''}".strip()
                table = _Table(label)
            elif cells[0] == "Unidade Curricular" and len(cells) == _UCT_COLUMNS:
                table_kind = "uct"
                skipped.append(
                    Skipped(
                        "uct",
                        course or "",
                        f"{course} semester {semester_number} {track or ''}".strip(),
                    )
                )
            continue
        if table_kind != "plan" or course is None:
            continue
        name = cells[0].replace("*", "").strip()
        values = [_number(c) for c in cells[2:10]]
        if name == "Total":
            table.check(values)
            continue
        if optional:
            skipped.append(Skipped("optional", course, name))
            continue
        t, tp, pl, weekly, hc, hea, total, ects = values
        if weekly != t + tp + pl:
            raise ValueError(f"{label} / {name}: the weekly hours do not add up")
        if hc != weekly * weeks:
            raise ValueError(
                f"{label} / {name}: contact hours {hc} differ from weekly {weekly} x {weeks}"
            )
        if hc + hea != total:
            raise ValueError(f"{label} / {name}: HC + HEA differs from the total")
        table.add(values)
        rows.append(
            PlanRow(course, semester_number, track, name, cells[1], t, tp, pl, hc, hea, ects)
        )

    return ParsedPlans(courses, tuple(tracks), tuple(rows), tuple(skipped))


def _heading(line: str) -> tuple[str, dict] | None:
    """Classify a Markdown heading line, or return ``None`` if it is not one."""
    if not line.startswith("#"):
        return None
    if m := _COURSE.match(line):
        return "course", {"code": m["code"], "name": m["name"]}
    if m := _YEAR_SEMESTER.match(line):
        # The second number of the heading is already the semester of the course (1 to 8).
        return "semester", {"number": int(m["sem"])}
    if m := _TRACK.match(line):
        return "track", {"code": m["code"], "name": m["name"], "year": int(m["year"])}
    if m := _VARIANT.match(line):
        return "track", {"code": m["name"], "name": m["name"], "year": int(m["year"])}
    if m := _TRACK_SEMESTER.match(line):
        return "track_semester", {"number": int(m["sem"])}
    if _OPTIONAL.match(line):
        return "optional", {}
    return "other", {}


def resolve_subjects(parsed: ParsedPlans) -> tuple[PlanSubject, ...]:
    """Merge the subjects shared by tracks and give every subject its placeholder code.

    A subject that appears with identical numbers in the table of every track of a semester is
    common to them (no track, one row, D79); one that appears in a single track belongs to it.

    Args:
        parsed: the result of ``parse_plans``.

    Returns:
        The subjects to load, by course and semester, in the order of the file.

    Raises:
        ValueError: if a subject has different numbers in different tracks, or is shared by some
            but not all of the tracks of a semester (partial sharing is not modelled).
    """
    result: list[PlanSubject] = []
    for course in parsed.courses:
        numbers = sorted({r.semester_number for r in parsed.rows if r.course == course})
        for number in numbers:
            rows = [r for r in parsed.rows if r.course == course and r.semester_number == number]
            year, semester = semester_position(number)
            counter = 0
            for row, track in _merge(rows, course, number):
                counter += 1
                weekly = {
                    c: h for c, h in (("T", row.t), ("TP", row.tp), (PL_CLASS_TYPE, row.pl)) if h
                }
                result.append(
                    PlanSubject(
                        course=course,
                        code=f"{course}-S{number:02d}-{counter:02d}",
                        name=row.name,
                        area=row.area,
                        semester_number=number,
                        curricular_year=year,
                        semester=semester,
                        track=track,
                        weekly=weekly,
                        semester_hours=row.hc,
                        ects=row.ects,
                    )
                )
    return tuple(result)


def _merge(rows: list[PlanRow], course: str, number: int) -> list[tuple[PlanRow, str | None]]:
    """Decide the track of each row of one semester, merging the common subjects."""
    track_codes = list(dict.fromkeys(r.track for r in rows if r.track is not None))
    if not track_codes:
        return [(r, None) for r in rows]
    by_name: dict[str, list[PlanRow]] = {}
    for row in rows:
        by_name.setdefault(row.name, []).append(row)
    merged: list[tuple[PlanRow, str | None]] = []
    for name, group in by_name.items():
        if len(track_codes) == 1 or len(group) == 1:
            merged.extend((r, r.track) for r in group)
        elif len(group) == len(track_codes):
            keys = {(r.area, r.t, r.tp, r.pl, r.hc, r.ects) for r in group}
            if len(keys) != 1:
                raise ValueError(
                    f"{course} semester {number}: '{name}' has different numbers in the tracks"
                )
            merged.append((group[0], None))
        else:
            raise ValueError(
                f"{course} semester {number}: '{name}' is shared by some but not all tracks"
            )
    order = {r.name: i for i, r in enumerate(rows)}
    merged.sort(key=lambda pair: order[pair[0].name])
    return merged
