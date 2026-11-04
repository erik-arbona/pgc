"""Loader of the real study plans (EIC and TM) into the database.

Implements: D78 (real study plans in the repository; people stay fictitious), D79 (tracks, common
subjects), D60. It creates courses, plan versions, tracks and subjects through the audited
services, never deletes anything and is safe to run twice: every record is found by its natural
key before it is created, and subjects by plan, name, year, semester and track, so that a code
edited by the manager does not produce a duplicate.

It cannot know the Faculty of the courses or the coordination of each subject, so it takes them
from the caller (existing records, or clearly marked placeholders). The plans carry no SII
references: ``sii_ref`` stays empty (D66, D77).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    Faculty,
    StudyPlan,
    Subject,
    Track,
)
from apps.academic.services import create_class_group, save_subject_with_loads
from apps.core.audit import audited_save

from .real_plans import ParsedPlans, PlanSubject

# The start year of each plan. EIC says "2023/2024"; TM only gives "fevereiro de 2024", a date
# of the document and not an academic year, so 2024 is an assumption the caller can change.
DEFAULT_PLAN_YEARS = {"EIC": 2023, "TM": 2024}

PLACEHOLDER_FACULTY_CODE = "PORCONF"
PLACEHOLDER_FACULTY_NAME = "Faculdade por confirmar (planos reais)"
PLACEHOLDER_COORDINATION_NAME = "Coordenação por atribuir"


@dataclass
class RealPlanLoader:
    """Loads the parsed plans; ``created`` counts what this run created, by kind.

    Attributes:
        faculty: Faculty the courses belong to.
        coordination: coordination given to every subject (the real one is unknown).
        years: start year of the plan of each course code.
        with_turmas: also create example turmas, a cohort and one per track.
    """

    faculty: Faculty
    coordination: Coordination
    years: dict[str, int]
    with_turmas: bool = False
    created: dict[str, int] = field(default_factory=dict)

    def _count(self, kind: str) -> None:
        """Count one created record."""
        self.created[kind] = self.created.get(kind, 0) + 1

    def _ensure(self, model, lookup: dict, defaults: dict | None = None):
        """Return the record with this natural key, creating it (audited) if it is missing."""
        found = model.objects.filter(**lookup).first()
        if found is not None:
            return found
        record = model(**lookup, **(defaults or {}))
        audited_save(record, None, "")
        self._count(model.__name__)
        return record

    def load(self, parsed: ParsedPlans, subjects: tuple[PlanSubject, ...]) -> None:
        """Create the courses, plans, tracks, subjects and, optionally, the example turmas.

        Args:
            parsed: the parsed file.
            subjects: the subjects to load, as returned by ``resolve_subjects``.

        Raises:
            KeyError: if a course of the file has no start year in ``years``.
            ValidationError: if a record is refused (for example D60 does not hold).
        """
        class_types = {ct.code: ct for ct in ClassType.objects.all()}
        for code, name in parsed.courses.items():
            year = self._ensure(AcademicYear, {"start_year": self.years[code]})
            course = self._ensure(
                Course,
                {"faculty": self.faculty, "name": name, "level": Course.Level.BACHELOR},
            )
            plan = self._ensure(StudyPlan, {"course": course, "academic_year": year})
            tracks = {
                t.code: self._ensure(
                    Track,
                    {"study_plan": plan, "code": t.code},
                    {"name": t.name, "first_curricular_year": t.first_year},
                )
                for t in parsed.tracks
                if t.course == code
            }
            for subject in (s for s in subjects if s.course == code):
                self._load_subject(plan, tracks.get(subject.track), subject, class_types)
            if self.with_turmas:
                self._load_turmas(course, year, tracks)

    def _load_subject(self, plan, track, wanted: PlanSubject, class_types: dict) -> None:
        """Create one subject with its weekly hours unless it already exists."""
        exists = Subject.objects.filter(
            study_plan=plan,
            name=wanted.name,
            curricular_year=wanted.curricular_year,
            semester=wanted.semester,
            track=track,
        ).exists()
        if exists:
            return
        subject = Subject(
            study_plan=plan,
            code=wanted.code,
            name=wanted.name,
            ects=wanted.ects,
            curricular_year=wanted.curricular_year,
            semester=wanted.semester,
            coordination=self.coordination,
            semester_hours=wanted.semester_hours,
            track=track,
        )
        loads = {class_types[code].pk: hours for code, hours in wanted.weekly.items()}
        save_subject_with_loads(subject, loads, None, "", save_subject=True)
        self._count("Subject")

    def _load_turmas(self, course: Course, year: AcademicYear, tracks: dict) -> None:
        """Create the cohort turma and one turma per track of a course, if missing."""
        for track in (None, *tracks.values()):
            if ClassGroup.objects.filter(course=course, intake_year=year, track=track).exists():
                continue
            create_class_group(course, year, track=track, actor=None)
            self._count("ClassGroup")
