from django import template

register = template.Library()

# Même dégradé rouge->vert que courses.utils.NOTE_COULEURS, réadapté aux
# 5 niveaux de NoteEvaluation.NOTE_CHOICES (0 à 4).
NOTE_EVALUATION_COULEURS = {
    0: ('#fce4e4', '#dc3545'),
    1: ('#ffe4c4', '#b35900'),
    2: ('#fff3cd', '#8a6d00'),
    3: ('#eef7e5', '#2d5a1b'),
    4: ('#e8f5e9', '#1b5e20'),
}


@register.filter
def note_evaluation_style(note):
    """Style inline (fond+texte) pour une pastille de NoteEvaluation (0-4)."""
    fond, texte = NOTE_EVALUATION_COULEURS.get(note, ('#f0f0f0', '#888'))
    return f'background:{fond}; color:{texte};'
