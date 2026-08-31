from django import template
from django.utils.translation import gettext_lazy as _
from django.utils.translation import gettext as gettext_

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
# Toutes marquées traduisibles (gettext_lazy) : utilisées entre autres par
# eleve_prof_detail.html et prof_profil.html (chantier traduction FR/EN,
# 2026-08-27/28), et par les fiches مدير/مشرف (audit du 2026-08-28,
# 'statut_familial' inclus depuis ce chantier-là).
LIBELLES = {
    'sexe': {
        'homme': _('ذكر'),
        'femme': _('أنثى'),
    },
    'statut_familial': {
        'celibataire': _('أعزب/عزباء'),
        'marie': _('متزوج/ة'),
        'divorce': _('مطلق/ة'),
    },
    'langues': {
        'arabe': _('العربية'),
        'francais': _('الفرنسية'),
        'anglais': _('الإنجليزية'),
        'autre': _('أخرى'),
    },
    'outils_maitrises': {
        'whatsapp': _('واتساب'),
        'meet': 'Google Meet',
        'zoom': 'Zoom',
    },
    'type_eleve_preference': {
        'enfants': _('أطفال'),
        'adultes': _('بالغون'),
        'les_deux': _('الاثنان'),
    },
    'contrainte_genre': {
        'homme': _('ذكور فقط'),
        'femme': _('إناث فقط'),
        'mixte': _('مختلط'),
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
    # str() force le rendu des libellés gettext_lazy (__proxy__) : str.join
    # exige de vraies chaînes, or LIBELLES contient des proxies paresseux.
    return '، '.join(str(mapping.get(code, code)) for code in codes)


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
    1: _('يناير'), 2: _('فبراير'), 3: _('مارس'), 4: _('أبريل'), 5: _('ماي'), 6: _('يونيو'),
    7: _('يوليوز'), 8: _('غشت'), 9: _('شتنبر'), 10: _('أكتوبر'), 11: _('نونبر'), 12: _('دجنبر'),
}


@register.filter
def mois_annee_ar(date_obj):
    """Formate une date en 'mois année' (ex: 'يناير 2026' / 'Janvier 2026' /
    'January 2026' selon la langue active), convention marocaine pour les
    noms de mois arabes. Retombe sur une chaîne vide si date_obj est None.
    Noms de mois passés par gettext_lazy (chantier i18n du 2026-08-28) —
    unique source pour tous les appelants de ce filtre (eleve_paiements.html,
    eleve_profil.html/bilans_mensuels, dashboard.views...), jamais dupliqués."""
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
        return gettext_('الآن')

    # À partir de 3 (jamais 1 ni 2, gérés à part ci-dessus) : une SEULE forme
    # plurielle en fr/en (contrairement à l'arabe, sans dual/singulier ici),
    # donc un simple gettext() suffit — pas besoin de ngettext(), que notre
    # compilateur .mo maison (build_i18n2.py, entrées simples msgid->msgstr,
    # jamais msgid_plural) ne sait de toute façon pas résoudre correctement
    # (vérifié : ngettext() retombait silencieusement sur l'arabe faute
    # d'entrée plurielle compilée dans le catalogue).
    minutes = int(secondes // 60)
    if minutes < 60:
        if minutes == 1:
            return gettext_('منذ دقيقة')
        if minutes == 2:
            return gettext_('منذ دقيقتين')
        return gettext_('منذ %(n)s دقائق') % {'n': minutes}

    heures = minutes // 60
    if heures < 24:
        if heures == 1:
            return gettext_('منذ ساعة')
        if heures == 2:
            return gettext_('منذ ساعتين')
        return gettext_('منذ %(n)s ساعات') % {'n': heures}

    jours = heures // 24
    if jours < 7:
        if jours == 1:
            return gettext_('منذ يوم')
        if jours == 2:
            return gettext_('منذ يومين')
        return gettext_('منذ %(n)s أيام') % {'n': jours}

    semaines = jours // 7
    if semaines == 1:
        return gettext_('منذ أسبوع')
    if semaines == 2:
        return gettext_('منذ أسبوعين')
    return gettext_('منذ %(n)s أسابيع') % {'n': semaines}


@register.filter
def tranche_age_ar(date_naissance):
    """'طفل'/'بالغ' calculé depuis une date de naissance, via la même règle
    centralisée que la grille de rémunération et la validation d'inscription
    (courses.utils.tranche_age_depuis_naissance, seuil AGE_SEUIL_ADULTE=18).
    Retombe sur une chaîne vide si date_naissance est None."""
    if not date_naissance:
        return ''
    from courses.utils import tranche_age_depuis_naissance

    return gettext_('بالغ') if tranche_age_depuis_naissance(date_naissance) == 'adulte' else gettext_('طفل')


@register.filter
def tranche_age_precise_ar(date_naissance):
    """Label arabe de la tranche d'âge précise (Partie B, 2026-08-24 —
    التلقين/البراعم/اليافعون, voir courses.utils.tranche_age_precise.__doc__)
    calculée depuis une date de naissance. Chaîne vide si date_naissance est
    None, ou si l'âge réel tombe hors 5-18 ans (adulte) — jamais une valeur
    trompeuse dans ce cas, même principe que tranche_age_ar ci-dessus."""
    if not date_naissance:
        return ''
    from courses.utils import tranche_age_precise

    resultat = tranche_age_precise(date_naissance)
    return resultat[1] if resultat else ''


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
