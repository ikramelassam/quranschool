from django import template

register = template.Library()

# Ces champs (JSONField multi-valeurs, ou CharField sans choices=) n'ont pas
# de get_FOO_display() Django — les codes viennent des boutons de sélection
# des formulaires d'inscription (inscriptions/eleve_formulaire.html,
# inscriptions/prof_formulaire.html), reproduits ici à l'identique pour que
# la fiche admin affiche le même libellé arabe que ce que le candidat a vu.
LIBELLES = {
    'sexe': {
        'homme': 'ذكر',
        'femme': 'أنثى',
    },
    'statut_familial': {
        'celibataire': 'أعزب/عزباء',
        'marie': 'متزوج/ة',
        'divorce': 'مطلق/ة',
    },
    'langues': {
        'arabe': 'العربية',
        'francais': 'الفرنسية',
        'anglais': 'الإنجليزية',
        'autre': 'أخرى',
    },
    'outils_maitrises': {
        'whatsapp': 'واتساب',
        'meet': 'Google Meet',
        'zoom': 'Zoom',
    },
    'type_eleve_preference': {
        'enfants': 'أطفال',
        'adultes': 'بالغون',
        'les_deux': 'الاثنان',
    },
    'contrainte_genre': {
        'homme': 'ذكور فقط',
        'femme': 'إناث فقط',
        'mixte': 'مختلط',
    },
}


@register.filter
def libelle_arabe(code, categorie):
    """Traduit un code brut isolé (ex: sexe='homme') en libellé arabe.
    Retombe sur le code lui-même si absent du dictionnaire, plutôt que de
    masquer une valeur inattendue."""
    return LIBELLES.get(categorie, {}).get(code, code)


@register.filter
def libelles_arabes_liste(codes, categorie):
    """Équivalent de libelle_arabe pour une liste de codes (JSONField multi-
    valeurs), jointe avec la même ponctuation arabe (، ) déjà utilisée
    ailleurs dans ces mêmes fiches."""
    mapping = LIBELLES.get(categorie, {})
    return '، '.join(mapping.get(code, code) for code in codes)
