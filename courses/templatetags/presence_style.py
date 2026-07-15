from django import template

from courses.utils import style_note, style_statut

register = template.Library()


@register.filter
def note_style(code):
    """Style inline (fond+texte) pour une pastille de note (voir courses.utils)."""
    return style_note(code)


@register.filter
def statut_style(code):
    """Style inline (fond+texte) pour une pastille de statut (voir courses.utils)."""
    return style_statut(code)
