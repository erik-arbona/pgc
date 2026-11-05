"""Tests for the CSV export of the load of a coordination (T6.4).

Implements: docs/backlog_fase2.md T6.4; Porta 1 (the calculated load matches the Excel); D69
(coordination scope), D101.
"""

# The fixtures come from other test modules; F811 flags every test that uses them.
# ruff: noqa: F811

import csv
import io
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.dsd.load_export import HEADER, csv_text, format_number, render_csv
from apps.dsd.models import TeachingUnit
from apps.dsd.services import assign_teacher, set_minimum_reason
from apps.dsd.tests.test_assignment import unit_of, world  # noqa: F401
from apps.dsd.tests.test_below_minimum import board, open_cell  # noqa: F401

pytestmark = pytest.mark.django_db

D = Decimal


# --- the pure parts ----------------------------------------------------------------------------


def test_numbers_use_the_decimal_comma_with_two_places():
    """A Portuguese Excel reads 10,50 as a number, not 10.50."""
    assert format_number(D("10.5")) == "10,50"
    assert format_number(D("0")) == "0,00"
    assert format_number(D("1234.567")) == "1234,57"


def test_a_missing_number_is_an_empty_cell():
    """A range without a minimum has nothing to write."""
    assert format_number(None) == ""


def test_text_that_looks_like_a_formula_is_neutralised():
    """Excel would run =, +, - or @ at the start of a cell (spreadsheet injection)."""
    for dangerous in ("=SUM(A1:A9)", "+1", "-1", "@cmd", "\tx", "\rx"):
        assert csv_text(dangerous) == "'" + dangerous


def test_ordinary_text_is_left_alone():
    """Names and labels are not changed."""
    assert csv_text("Maria da Silva") == "Maria da Silva"
    assert csv_text("") == ""
    assert csv_text(None) == ""


def test_the_file_has_a_bom_semicolons_and_crlf():
    """UTF-8 with BOM (accents in Excel), ';' as separator, CRLF between rows."""
    data = render_csv([["a", "b;c"], ["1", "2"]])
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    assert text == 'a;"b;c"\r\n1;2\r\n'


# --- the export of a coordination --------------------------------------------------------------


def url(world, coordination=None):
    """The URL of the CSV of a coordination."""
    return reverse(
        "dsd:coordination_load_csv",
        args=[world["semester"].dsd.pk, (coordination or world["coordination"]).pk],
    )


def rows_of(response):
    """The rows of the CSV in a response, as dictionaries by header."""
    text = response.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def test_the_file_is_a_csv_download_with_the_documented_header(board, client):
    """Content type, attachment name and the columns."""
    client.force_login(board["coordinator"])
    response = client.get(url(board))
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    assert ".csv" in response["Content-Disposition"]
    first = response.content.decode("utf-8-sig").splitlines()[0]
    assert first.split(";") == list(HEADER)


def test_the_figures_are_those_of_the_live_load(board, client):
    """Porta 1: the file says what the screen says (D70-D74)."""
    open_cell(board)
    assign_teacher(board["coordinator"], unit_of(board, "A", "T"), board["mine"])
    assign_teacher(board["coordinator"], unit_of(board, "A", "P"), board["mine"])
    client.force_login(board["coordinator"])
    row = next(r for r in rows_of(client.get(url(board))) if r["Identificador"] == "T1")
    # theory 2 h + practice 3 h, first semester only
    assert row["Horas letivas 1.º semestre"] == "5,00"
    assert row["Horas letivas 2.º semestre"] == "0,00"
    assert row["Horas letivas anuais"] == "5,00"
    assert row["Mínimo"] == "6,00" and row["Máximo"] == "12,00"
    assert row["Estado"] == "abaixo do mínimo"
    assert row["Total geral"] != ""


def test_every_teacher_of_the_coordination_has_a_row(board, client):
    """The two active teachers; not the inactive one, not the other coordination's."""
    client.force_login(board["coordinator"])
    identifiers = {r["Identificador"] for r in rows_of(client.get(url(board)))}
    assert identifiers == {"T1", "T2"}


def test_a_teacher_of_another_coordination_with_a_lesson_here_is_flagged(board, client):
    """Shown, with the flag, as on the overview."""
    TeachingUnit.objects.filter(pk=unit_of(board, "A", "T").pk).update(teacher=board["foreign"])
    client.force_login(board["coordinator"])
    rows = {r["Identificador"]: r for r in rows_of(client.get(url(board)))}
    assert rows["T3"]["Outra coordenação"] == "sim"
    assert rows["T1"]["Outra coordenação"] == ""


def test_the_file_carries_no_management_notes(board, client):
    """Numbers and the state only: no reason below the minimum, no comment of the board."""
    open_cell(board)
    set_minimum_reason(
        board["coordinator"], board["mine"], board["semester"].dsd, "Motivo reservado"
    )
    client.force_login(board["coordinator"])
    assert "Motivo reservado" not in client.get(url(board)).content.decode("utf-8-sig")


def test_a_name_that_looks_like_a_formula_is_neutralised_in_the_file(board, client):
    """Spreadsheet injection through a teacher's name."""
    board["mine"].name = '=HYPERLINK("http://x")'
    board["mine"].save()
    client.force_login(board["coordinator"])
    text = client.get(url(board)).content.decode("utf-8-sig")
    assert ";=HYPERLINK" not in text
    assert "'=HYPERLINK" in text


def test_who_may_download_it(board, client):
    """The coordinator of the coordination, the manager and the board of the Faculty."""
    for user in (board["coordinator"], board["manager"], board["ce"]):
        client.force_login(user)
        assert client.get(url(board)).status_code == 200


def test_who_may_not_download_it(board, client):
    """Another coordination, another Faculty, a teacher account."""
    for user in (board["other_coordinator"], board["other_ce"], board["teacher_user"]):
        client.force_login(user)
        assert client.get(url(board)).status_code == 403


def test_the_download_needs_a_session(board, client):
    """Anonymous users go to the login."""
    assert client.get(url(board)).status_code == 302


def test_the_overview_offers_the_download(board, client):
    """A link on the overview page, for who may use it."""
    client.force_login(board["coordinator"])
    overview = reverse(
        "dsd:coordination_overview", args=[board["semester"].dsd.pk, board["coordination"].pk]
    )
    assert url(board) in client.get(overview).content.decode()


def test_over_the_maximum_the_state_has_no_excess_and_the_extra_hours_have_a_column(board, client):
    """The excess is a number of its own, so Excel can compare it; the state is only words."""
    from apps.staff.models import LoadRange

    LoadRange.objects.update(maximum_hours=D("8"))
    open_cell(board)
    for label, kind in (("A", "T"), ("A", "P"), ("B", "T"), ("B", "P")):
        assign_teacher(board["coordinator"], unit_of(board, label, kind), board["mine"])
    client.force_login(board["coordinator"])
    row = next(r for r in rows_of(client.get(url(board))) if r["Identificador"] == "T1")
    assert row["Estado"] == "acima do máximo"
    assert row["Horas extra"] == "2,00"
    assert row["Horas letivas anuais"] == "10,00"


def test_a_teacher_of_another_coordination_only_has_what_the_screen_shows(board, client):
    """Review of T6.4: preparation, other activities, the total and the extra hours of a teacher
    of another coordination are not this coordinator's business (D69, D100)."""
    from apps.dsd.models import OtherActivity
    from apps.dsd.services import add_activity

    open_cell(board)
    add_activity(
        board["manager"],
        board["foreign"],
        board["semester"],
        OtherActivity.Kind.RESEARCH,
        "Reservado",
        D("4"),
    )
    TeachingUnit.objects.filter(pk=unit_of(board, "A", "T").pk).update(teacher=board["foreign"])
    client.force_login(board["coordinator"])
    rows = {r["Identificador"]: r for r in rows_of(client.get(url(board)))}
    foreign = rows["T3"]
    assert foreign["Horas letivas anuais"] != ""  # the screen shows the annual hours
    assert foreign["Estado"] != ""  # and the state
    for column in (
        "Categoria",
        "Tipo",
        "Horas extra",
        "Preparação 1.º semestre",
        "Preparação 2.º semestre",
        "Outras atividades 1.º semestre",
        "Outras atividades 2.º semestre",
        "Total geral",
    ):
        assert foreign[column] == "", column
    assert rows["T1"]["Total geral"] != ""  # the teachers of this coordination keep everything


def test_a_dsd_without_semesters_is_a_404(board, client):
    """No semester to read: 404, not a server error (review of T6.4)."""
    from apps.academic.models import AcademicYear
    from apps.dsd.models import Dsd

    empty = Dsd.objects.create(academic_year=AcademicYear.objects.create(start_year=2031))
    client.force_login(board["coordinator"])
    response = client.get(
        reverse("dsd:coordination_load_csv", args=[empty.pk, board["coordination"].pk])
    )
    assert response.status_code == 404


def test_the_download_is_not_cached(board, client):
    """A file with personal data must not be kept by a browser or a proxy."""
    client.force_login(board["coordinator"])
    control = client.get(url(board))["Cache-Control"]
    assert "no-store" in control or "no-cache" in control


def test_a_tiny_negative_number_is_not_written_as_minus_zero():
    """-0.001 rounds to zero: the cell says 0,00, never -0,00."""
    assert format_number(D("-0.001")) == "0,00"
