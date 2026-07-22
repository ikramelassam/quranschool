from django import template

register = template.Library()


@register.filter
def parse_items(texte):
    """Transforme le contenu d'un champ *_items (un point par ligne, format libre
    "التسمية: الوصف") en liste de dicts {'label': ..., 'texte': ...} pour affichage
    en <li><strong>label:</strong> texte</li>. Le ':' est optionnel — sans lui, le
    point s'affiche comme texte simple (label=None)."""
    points = []
    for ligne in (texte or '').split('\n'):
        ligne = ligne.strip()
        if not ligne:
            continue
        if ':' in ligne:
            label, _, reste = ligne.partition(':')
            points.append({'label': label.strip(), 'texte': reste.strip()})
        else:
            points.append({'label': None, 'texte': ligne})
    return points
