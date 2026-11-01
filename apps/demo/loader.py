"""Builds the fictitious data set described in docs/dados_ficticios.md.

Implements: docs/dados_ficticios.md (the part phase 1 supports); CLAUDE.md rule 8 (no real data in
the repository) and rule 7 (every write audited); D65.

Everything is created only if it does not exist yet, so loading twice changes nothing, and nothing
is ever deleted. Writes go through ``audited_save`` and the same services the screens use, with no
actor (the system). Names are clearly fictitious and the hour ranges are test values, not real
values of the University.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.academic.models import (
    AcademicYear,
    ClassGroup,
    ClassType,
    Coordination,
    Course,
    CrossCourseSubject,
    Faculty,
    StudyPlan,
    Subject,
)
from apps.academic.services import (
    create_class_group,
    save_cross_course_group,
    save_subject_with_loads,
)
from apps.core.audit import audited_save
from apps.core.models import Profile, RoleAssignment, ScopeKind
from apps.rooms.models import Room, RoomType
from apps.staff.models import Category, LoadRange, Position, Teacher
from apps.staff.services import save_load_range, save_teacher_with_positions

DEMO_PASSWORD = "demo1234"
RANGES_FROM = date(2026, 1, 1)

# Weekly hours by class type code and the semester hours they imply with 15 weeks (D60).
LOAD_PATTERNS = [
    ({"T": 3, "P": 2}, 75),
    ({"T": 2, "TP": 2}, 60),
    ({"T": 4}, 60),
    ({"T": 2, "L": 2}, 60),
]

# (code, name, level, faculty code, coordination that runs the course's second subject)
COURSES = [
    ("A", "Curso A", Course.Level.BACHELOR, "FT1", "C2"),
    ("B", "Curso B", Course.Level.BACHELOR, "FT1", "C2"),
    ("C", "Curso C", Course.Level.BACHELOR, "FT2", "C3"),
    ("M", "Curso M", Course.Level.MASTER, "FT1", "C4"),
]

# (identifier, name, type, category, coordination, positions)
TEACHERS = [
    ("DT001", "Docente A", Teacher.Type.FULL_TIME, "Doutor", "C1", []),
    ("DT002", "Docente B", Teacher.Type.FULL_TIME, "Doutor", "C1", ["Presidente de conselho"]),
    ("DT003", "Docente C", Teacher.Type.FULL_TIME, "Mestre", "C2", ["Assessor"]),
    ("DT004", "Docente D", Teacher.Type.FULL_TIME, "Mestre", "C3", []),
    ("DT005", "Docente E", Teacher.Type.FULL_TIME, "Licenciado", "C4", []),
    ("DT006", "Docente F", Teacher.Type.HABITUAL_COLLABORATOR, "Mestre", "C1", []),
    ("DT007", "Docente G", Teacher.Type.HABITUAL_COLLABORATOR, "Licenciado", "C2", []),
    ("DT008", "Docente H", Teacher.Type.COMPETITION, "Doutor", "C3", []),
]

# (kind, reference, minimum, maximum): test values, not real values of the University.
RANGES = [
    (LoadRange.Kind.CATEGORY, "Licenciado", 10, 20),
    (LoadRange.Kind.CATEGORY, "Mestre", 8, 18),
    (LoadRange.Kind.CATEGORY, "Doutor", 6, 16),
    (LoadRange.Kind.POSITION, "Assessor", 4, 12),
    (LoadRange.Kind.POSITION, "Presidente de conselho", 2, 8),
    (LoadRange.Kind.TEACHER_TYPE, Teacher.Type.HABITUAL_COLLABORATOR, None, 20),
    (LoadRange.Kind.TEACHER_TYPE, Teacher.Type.COMPETITION, None, 18),
]

# (building, number, name, room type code, capacity)
ROOMS = [
    ("Edifício 1", "S101", "", "SALA", 40),
    ("Edifício 1", "S102", "", "SALA", 30),
    ("Edifício 1", "S103", "", "SALA", 12),  # too small for most exams
    ("Edifício 2", "L1", "", "LAB", 20),
    ("Edifício 2", "L2", "", "LAB", 25),
    ("Edifício 3", "A1", "Auditório de Teste", "AUD", 200),
]

# (username, first name, last name, profile, scope kind, scope reference)
ACCOUNTS = [
    ("demo_gestor", "Demo", "Gestor", Profile.PGC_MANAGER, ScopeKind.FACULTY, "all faculties"),
    ("demo_coordenador", "Demo", "Coordenador", Profile.COORDINATOR, ScopeKind.COORDINATION, "C1"),
    ("demo_ce", "Demo", "Conselho Executivo", Profile.EXECUTIVE_BOARD, ScopeKind.FACULTY, "FT1"),
    ("demo_patrimonio", "Demo", "Património", Profile.FACILITIES, ScopeKind.NONE, None),
    ("demo_consulta", "Demo", "Consulta", Profile.VIEWER, ScopeKind.NONE, None),
    ("demo_docente", "Demo", "Docente", Profile.TEACHER, ScopeKind.TEACHER, "DT001"),
]


@dataclass
class DemoLoader:
    """Loads the data set; ``created`` counts what this run created, by kind."""

    passwords: bool
    created: dict[str, int] = field(default_factory=dict)

    def _count(self, kind: str) -> None:
        """Count one created record."""
        self.created[kind] = self.created.get(kind, 0) + 1

    def _ensure(self, model, lookup: dict, defaults: dict | None = None, kind: str = ""):
        """Return the record with this natural key, creating it (audited) if it is missing."""
        found = model.objects.filter(**lookup).first()
        if found is not None:
            return found
        record = model(**lookup, **(defaults or {}))
        audited_save(record, None, "")
        self._count(kind or model.__name__)
        return record

    # --- structure ----------------------------------------------------------------------------

    def load(self) -> None:
        """Create the whole data set."""
        year = self._ensure(AcademicYear, {"start_year": 2026})
        faculties = {
            code: self._ensure(Faculty, {"code": code}, {"name": f"Faculdade de Teste {code[-1]}"})
            for code in ("FT1", "FT2")
        }
        coordinations = {
            code: self._ensure(
                Coordination,
                {"faculty": faculties[faculty], "name": f"Coordenação de Teste {code[-1]}"},
            )
            for code, faculty in (("C1", "FT1"), ("C2", "FT1"), ("C3", "FT2"), ("C4", "FT2"))
        }
        courses, plans = {}, {}
        for code, name, level, faculty, _second in COURSES:
            courses[code] = self._ensure(
                Course, {"faculty": faculties[faculty], "name": name, "level": level}
            )
            plans[code] = self._ensure(StudyPlan, {"course": courses[code], "academic_year": year})
        subjects = self._load_subjects(plans, coordinations)
        self._load_cross_course_group(subjects, courses)
        self._load_class_groups(courses, year)
        teachers = self._load_teachers(coordinations)
        self._load_ranges()
        self._load_rooms()
        self._load_accounts(faculties, coordinations, teachers)

    def _load_subjects(self, plans: dict, coordinations: dict) -> dict:
        """Create 8 subjects per course: years 1 and 2, two semesters, two subjects each."""
        class_types = {ct.code: ct for ct in ClassType.objects.all()}
        subjects = {}
        for code, _name, _level, _faculty, second in COURSES:
            for (year, semester), position in self._cells():
                for n in (1, 2):
                    subject_code = f"{code}{year}{semester}{n}"
                    existing = Subject.objects.filter(
                        study_plan=plans[code], code=subject_code
                    ).first()
                    if existing is not None:
                        subjects[subject_code] = existing
                        continue
                    hours, semester_hours = LOAD_PATTERNS[(position + n) % len(LOAD_PATTERNS)]
                    cross = (code in "ABC") and (year, semester, n) == (1, 1, 1)
                    subject = Subject(
                        study_plan=plans[code],
                        code=subject_code,
                        name="Introdução à Programação" if cross else f"Disciplina {subject_code}",
                        ects=Decimal("6"),
                        curricular_year=year,
                        semester=semester,
                        # The first subject of every course is run by coordination 1, which
                        # therefore has subjects in several courses.
                        coordination=coordinations["C1" if n == 1 else second],
                        semester_hours=Decimal(75 if cross else semester_hours),
                        programme="Programa de teste." if cross else "",
                    )
                    loads = {
                        class_types[c].pk: Decimal(h)
                        for c, h in ({"T": 3, "P": 2} if cross else hours).items()
                    }
                    save_subject_with_loads(subject, loads, None, "", save_subject=True)
                    self._count("Subject")
                    subjects[subject_code] = subject
        return subjects

    @staticmethod
    def _cells():
        """Yield ((curricular year, semester), position) for years 1-2 and semesters 1-2."""
        cells = [(1, 1), (1, 2), (2, 1), (2, 2)]
        return [(cell, index) for index, cell in enumerate(cells)]

    def _load_cross_course_group(self, subjects: dict, courses: dict) -> None:
        """Declare 'Introdução à Programação' in courses A and B, and leave course C out."""
        if CrossCourseSubject.objects.filter(name="Introdução à Programação").exists():
            return
        group = CrossCourseSubject(name="Introdução à Programação")
        save_cross_course_group(
            group,
            [subjects["A111"], subjects["B111"], subjects["C111"]],
            [courses["A"], courses["B"]],
            None,
            "",
            save_group=True,
        )
        self._count("CrossCourseSubject")

    def _load_class_groups(self, courses: dict, year: AcademicYear) -> None:
        """One turma per course, and two (A and B) in the same year for course A."""
        for code, labels in (("A", ["A", "B"]), ("B", [""]), ("C", [""]), ("M", [""])):
            for label in labels:
                if ClassGroup.objects.filter(
                    course=courses[code], intake_year=year, label=label
                ).exists():
                    continue
                create_class_group(courses[code], year, label, actor=None)
                self._count("ClassGroup")

    # --- staff, rooms and accounts ---------------------------------------------------------------

    def _load_teachers(self, coordinations: dict) -> dict:
        """Create the teachers of every category and type, some with positions."""
        positions = {
            name: self._ensure(Position, {"name": name})
            for name in ("Assessor", "Presidente de conselho")
        }
        teachers = {}
        for identifier, name, kind, category, coordination, held in TEACHERS:
            existing = Teacher.objects.filter(identifier=identifier).first()
            if existing is not None:
                teachers[identifier] = existing
                continue
            teacher = Teacher(
                identifier=identifier,
                name=name,
                coordination=coordinations[coordination],
                category=Category.objects.get(name=category),
                teacher_type=kind,
            )
            save_teacher_with_positions(
                teacher, {positions[p].pk for p in held}, None, "", save_teacher=True
            )
            self._count("Teacher")
            teachers[identifier] = teacher
        return teachers

    def _load_ranges(self) -> None:
        """Create the test hour ranges that apply to every teacher."""
        for kind, reference, minimum, maximum in RANGES:
            fields = {"kind": kind, "valid_from": RANGES_FROM}
            if kind == LoadRange.Kind.CATEGORY:
                fields["category"] = Category.objects.get(name=reference)
            elif kind == LoadRange.Kind.POSITION:
                fields["position"] = Position.objects.get(name=reference)
            else:
                fields["teacher_type"] = reference
            if LoadRange.objects.filter(**fields).exists():
                continue
            save_load_range(
                LoadRange(
                    **fields,
                    minimum_hours=None if minimum is None else Decimal(minimum),
                    maximum_hours=Decimal(maximum),
                ),
                None,
                "",
            )
            self._count("LoadRange")

    def _load_rooms(self) -> None:
        """Create rooms of several types and capacities, one of them tiny."""
        for building, number, name, type_code, capacity in ROOMS:
            self._ensure(
                Room,
                {"building": building, "number": number},
                {
                    "name": name,
                    "room_type": RoomType.objects.get(code=type_code),
                    "capacity": capacity,
                },
            )

    def _load_accounts(self, faculties: dict, coordinations: dict, teachers: dict) -> None:
        """Create one account per profile; passwords only where local login is allowed."""
        user_model = get_user_model()
        for username, first, last, profile, kind, reference in ACCOUNTS:
            if user_model.objects.filter(username=username).exists():
                continue
            user = user_model(username=username, first_name=first, last_name=last)
            if self.passwords:
                user.set_password(DEMO_PASSWORD)
            else:
                user.set_unusable_password()
            audited_save(user, None, "")
            self._count("User")
            if kind == ScopeKind.FACULTY and reference == "all faculties":
                scope_ids = [f.pk for f in faculties.values()]
            elif kind == ScopeKind.FACULTY:
                scope_ids = [faculties[reference].pk]
            elif kind == ScopeKind.COORDINATION:
                scope_ids = [coordinations[reference].pk]
            elif kind == ScopeKind.TEACHER:
                scope_ids = [teachers[reference].pk]
            else:
                scope_ids = [None]
            for scope_id in scope_ids:
                audited_save(
                    RoleAssignment(user=user, profile=profile, scope_kind=kind, scope_id=scope_id),
                    None,
                    "",
                )
                self._count("RoleAssignment")
