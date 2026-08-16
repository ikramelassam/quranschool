from django import template

register = template.Library()


@register.filter
def get_item(dictionnaire, cle):
    """Lookup par clé variable dans un dict — les templates Django
    n'acceptent pas dictionnaire[variable] nativement (seulement
    dictionnaire.cle_litterale). Utilisé pour reponses[question.id] dans
    templates/examens/passage.html (même bug de fond que 'presences[eleve.id]'
    documenté historiquement pour prof_seance_detail.html — corrigé ici dès
    le départ par un filtre dédié plutôt que reproduit)."""
    if dictionnaire is None:
        return None
    return dictionnaire.get(cle)
