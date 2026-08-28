from django import template

register = template.Library()


@register.filter
def localise(objet, champ):
    """Filtre générique {{ objet|localise:"champ" }} — appelle objet._localise(champ)
    (chantier i18n du 2026-08-28). Utilisé pour CharteEnseignement/
    CharteSanctionLigne, tout objet qui suit ce patron (repli automatique sur
    l'arabe si la traduction FR/EN active n'est pas encore saisie) : Django
    n'autorise pas d'appeler une méthode avec un argument directement depuis un
    template (`objet.methode:arg` n'existe pas), d'où ce filtre plutôt qu'un
    appel direct à _localise."""
    return objet._localise(champ)


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
