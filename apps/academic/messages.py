"""User-facing texts (pt-PT) for the codes returned by the cross-course domain rules.

Implements: D47, D55. The domain module returns codes, not sentences, so that it stays
free of the interface language; this module maps each code to a translatable message.
"""

from django.utils.translation import gettext_lazy as _

from .cross_course import GroupError, WarningKind

GROUP_ERROR_TEXT = {
    GroupError.TOO_FEW_COURSES: _(
        "Uma disciplina transversal precisa de membros de pelo menos dois cursos."
    ),
    GroupError.TOO_FEW_ALLOWED: _(
        "Indique pelo menos dois cursos em que a disciplina é transversal."
    ),
    GroupError.ALLOWED_NOT_IN_MEMBERS: _(
        "Os cursos indicados têm de ser cursos de disciplinas do grupo."
    ),
}

WARNING_TEXT = {
    WarningKind.SEMESTER_DIFFERS: _(
        "O semestre é diferente entre as disciplinas: não se poderão juntar turmas."
    ),
    WarningKind.SEMESTER_HOURS_DIFFER: _("A carga semestral é diferente entre as disciplinas."),
    WarningKind.CLASS_LOAD_DIFFERS: _(
        "A carga semanal do tipo de aula %(type)s é diferente entre as disciplinas."
    ),
}
