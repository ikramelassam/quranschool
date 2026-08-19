from django import template

register = template.Library()


@register.filter
def lien_seance_actif(seance):
    """Filtre gabarit pour courses.utils.lien_seance_est_actif — recalculé à
    chaque rendu de page (jamais mis en cache), voir _meet_icon.html
    (Point 15, Tâche du 2026-08-04)."""
    from courses.utils import lien_seance_est_actif as _lien_seance_est_actif
    return _lien_seance_est_actif(seance)

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


@register.filter
def wa_number(telephone):
    """Convertit un numéro marocain local (ex: '0663394165') au format
    international sans '+' attendu par les liens wa.me. Un numéro déjà saisi
    avec indicatif (ex: '212663394165') passe tel quel."""
    chiffres = ''.join(c for c in telephone if c.isdigit())
    if chiffres.startswith('0'):
        return '212' + chiffres[1:]
    return chiffres


# Convention marocaine (administration/quotidien), pas la convention machreqienne
# (كانون الثاني، شباط...) ni la forme standard mayo/يوليو/أغسطس — confirmée avec
# le client. Django ne peut pas fournir ça via |date:"F Y": LANGUAGE_CODE='en-us'
# et aucun LocaleMiddleware ne sont configurés (voir core/settings.py), donc ce
# filtre rendrait les mois en anglais ("January 2026") sans ce mapping explicite.
MOIS_AR = {
    1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل', 5: 'ماي', 6: 'يونيو',
    7: 'يوليوز', 8: 'غشت', 9: 'شتنبر', 10: 'أكتوبر', 11: 'نونبر', 12: 'دجنبر',
}


@register.filter
def mois_annee_ar(date_obj):
    """Formate une date en 'mois_arabe année' (ex: 'يناير 2026'), convention
    marocaine. Retombe sur une chaîne vide si date_obj est None."""
    if not date_obj:
        return ''
    return f'{MOIS_AR.get(date_obj.month, date_obj.month)} {date_obj.year}'


@register.filter
def jours_depuis(date_reference):
    """Nombre de jours écoulés depuis date_reference (aujourd'hui inclus comme
    jour 0). Utilisé pour le badge d'ancienneté de suspension ('موقوف منذ X
    يوم') — jamais un badge statique qui masquerait une suspension oubliée
    depuis des mois. Retombe sur une chaîne vide si date_reference est None."""
    from django.utils import timezone

    if not date_reference:
        return ''
    return (timezone.localdate() - date_reference).days


@register.filter
def depuis_relatif(date_reference):
    """Ancienneté relative en arabe, granularité fine (minute/heure/jour/
    semaine) — ex: 'منذ 3 دقائق', 'منذ ساعتين', 'منذ يومين', 'منذ 3 أسابيع'.
    Complète jours_depuis ci-dessus (qui ne renvoie qu'un entier de jours,
    pensé pour un badge de suspension) : ici il faut une phrase complète et
    plus granulaire, pour le panneau 🔔 الإشعارات (Chantier notifications du
    2026-08-19) où un événement vieux de quelques minutes doit se distinguer
    d'un événement vieux d'un jour. django.contrib.humanize n'est pas
    installé dans ce projet, et LANGUAGE_CODE='en-us' (settings.py) l'aurait
    de toute façon affiché en anglais ('2 hours ago') au milieu d'une
    interface entièrement arabe — un filtre maison est donc nécessaire, pas
    une case humanize à cocher.

    Duel arabe (2 exactement, pas juste "2 + pluriel générique") correctement
    distingué à CHAQUE palier — منذ دقيقتين/ساعتين/يومين/أسبوعين, jamais
    "منذ 2 دقائق" ou équivalent."""
    from django.utils import timezone

    if not date_reference:
        return ''
    delta = timezone.now() - date_reference
    secondes = delta.total_seconds()
    if secondes < 60:
        return 'الآن'

    minutes = int(secondes // 60)
    if minutes < 60:
        if minutes == 1:
            return 'منذ دقيقة'
        if minutes == 2:
            return 'منذ دقيقتين'
        return f'منذ {minutes} دقائق'

    heures = minutes // 60
    if heures < 24:
        if heures == 1:
            return 'منذ ساعة'
        if heures == 2:
            return 'منذ ساعتين'
        return f'منذ {heures} ساعات'

    jours = heures // 24
    if jours < 7:
        if jours == 1:
            return 'منذ يوم'
        if jours == 2:
            return 'منذ يومين'
        return f'منذ {jours} أيام'

    semaines = jours // 7
    if semaines == 1:
        return 'منذ أسبوع'
    if semaines == 2:
        return 'منذ أسبوعين'
    return f'منذ {semaines} أسابيع'


@register.filter
def tranche_age_ar(date_naissance):
    """'طفل'/'بالغ' calculé depuis une date de naissance, via la même règle
    centralisée que la grille de rémunération et la validation d'inscription
    (courses.utils.tranche_age_depuis_naissance, seuil AGE_SEUIL_ADULTE=18).
    Retombe sur une chaîne vide si date_naissance est None."""
    if not date_naissance:
        return ''
    from courses.utils import tranche_age_depuis_naissance

    return 'بالغ' if tranche_age_depuis_naissance(date_naissance) == 'adulte' else 'طفل'


# Icône + couleur du carré selon l'extension du fichier joint à un
# ElementHakiba (refonte du 2026-08-05) — même liste blanche que
# dashboard.views.EXTENSIONS_HAKIBA_AUTORISEES, reproduite ici uniquement
# pour le choix visuel (icone_hakiba/couleur_hakiba ne valident rien).
EXTENSIONS_ICONE_HAKIBA = {
    'document': (('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt'), '📄', '#2d5a1b'),
    'image': (('.jpg', '.jpeg', '.png', '.gif', '.webp'), '🖼️', '#1a6b8c'),
    'audio': (('.mp3', '.wav', '.m4a', '.ogg'), '🎵', '#7a3a9c'),
    'video': (('.mp4', '.mov', '.avi', '.webm', '.mkv'), '🎬', '#b3261e'),
}


@register.filter
def icone_hakiba(fichier):
    """Icône emoji d'un élément حقيبة الأستاذ : selon l'extension du fichier
    joint, ou 📝 si l'élément n'a que du texte (pas de fichier)."""
    import os
    if not fichier:
        return '📝'
    extension = os.path.splitext(str(fichier))[1].lower()
    for _categorie, (extensions, icone, _couleur) in EXTENSIONS_ICONE_HAKIBA.items():
        if extension in extensions:
            return icone
    return '📎'


@register.filter
def couleur_hakiba(fichier):
    """Couleur du carré-icône associé (voir icone_hakiba ci-dessus) — doré
    neutre pour un élément texte seul, gris pour une extension imprévue."""
    import os
    if not fichier:
        return '#9c7a2d'
    extension = os.path.splitext(str(fichier))[1].lower()
    for _categorie, (extensions, _icone, couleur) in EXTENSIONS_ICONE_HAKIBA.items():
        if extension in extensions:
            return couleur
    return '#666'


@register.filter
def noms_eleves(eleves_manager):
    """Joint les noms complets des élèves d'un groupe (eleve.user.get_full_name()),
    séparés par '، ' — utilisé sur les listes de séances à venir (prof + élève) pour
    afficher qui est dans la halqa sans clic supplémentaire. Passer le manager
    (ex: groupe.eleves, pas groupe.eleves.all) pour profiter du prefetch_related
    déjà fait côté vue plutôt que de redéclencher une requête.
    Exclut les élèves archivés (chantier d'archivage du 2026-08-03)."""
    return '، '.join(e.user.get_full_name() for e in eleves_manager.all() if e.statut != 'archive')
