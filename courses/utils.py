import datetime

from django.utils import timezone

JOUR_INDEX = {'lun': 0, 'mar': 1, 'mer': 2, 'jeu': 3, 'ven': 4, 'sam': 5, 'dim': 6}

# Couleurs (fond, texte) par code — source unique utilisée partout où une
# Presence est affichée (admin, élève, superviseur), pour que la même note
# ou le même statut ait toujours la même couleur.
NOTE_COULEURS = {
    'mumtaz': ('#e8f5e9', '#1b5e20'),
    'hasan_jiddan': ('#eef7e5', '#2d5a1b'),
    'hasan': ('#f3f7d8', '#6b7a1f'),
    'mustahsan': ('#fff3cd', '#8a6d00'),
    'mutawassit': ('#ffe4c4', '#b35900'),
    'doun_mutawassit': ('#fce4e4', '#dc3545'),
}
STATUT_COULEURS = {
    'present': ('#e8f5e9', '#2d5a1b'),
    'absent_excuse': ('#fff3cd', '#856404'),
    'absent': ('#fce4e4', '#dc3545'),
}


def style_note(code):
    """Style inline (fond + texte) pour une pastille de note de Presence."""
    fond, texte = NOTE_COULEURS.get(code, ('#f0f0f0', '#888'))
    return f'background:{fond}; color:{texte};'


def style_statut(code):
    """Style inline (fond + texte) pour une pastille de statut de Presence."""
    fond, texte = STATUT_COULEURS.get(code, ('#f0f0f0', '#888'))
    return f'background:{fond}; color:{texte};'

HORIZON_SEMAINES = 8

JOURS_SEMAINE_DISPO = [
    ('lun', 'الاثنين'), ('mar', 'الثلاثاء'), ('mer', 'الأربعاء'),
    ('jeu', 'الخميس'), ('ven', 'الجمعة'), ('sam', 'السبت'), ('dim', 'الأحد'),
]


def generer_heures_grille():
    """Liste des heures pleines de la grille de disponibilités, de l'ouverture
    à la fermeture de l'école (settings.HEURE_OUVERTURE_ECOLE / _FERMETURE_ECOLE)."""
    from django.conf import settings

    heures = []
    h = settings.HEURE_OUVERTURE_ECOLE
    while h < settings.HEURE_FERMETURE_ECOLE:
        heures.append(h)
        h = (datetime.datetime.combine(timezone.localdate(), h) + datetime.timedelta(hours=1)).time()
    return heures


def _heures_couvertes(heure_debut, heure_fin):
    """Liste des heures pleines couvertes par un intervalle [heure_debut, heure_fin)."""
    heures = []
    h = heure_debut
    while h < heure_fin:
        heures.append(h)
        h = (datetime.datetime.combine(timezone.localdate(), h) + datetime.timedelta(hours=1)).time()
    return heures


def fusionner_intervalles(intervalles):
    """Fusionne une liste de (debut, fin) inclusifs en intervalles non
    chevauchants triés, en fusionnant aussi les intervalles contigus (fin+1 ==
    debut suivant, aucun trou entre les deux). Seule implémentation de fusion
    d'intervalles du projet — réutilisée par calculer_progression_eleve
    (compteur total d'ayat mémorisés) ET _couverture_ayat_par_sourate (système
    hizb/ربع الحزب), qui souffraient tous deux du même bug avant Tâche 6c du
    2026-07-25 : prendre l'étendue min/max entre séances au lieu d'une vraie
    union, ce qui recomptait des ayat déjà couverts par une séance précédente
    (ex: 1-10 puis 1-74 comptait 84 versets au lieu de 74) et pouvait déclarer
    couvert un intervalle jamais mémorisé entre deux plages non contiguës
    (ex: 1-10 puis 60-74 donnait l'étendue [1,74], pas les deux blocs [1,10]
    et [60,74] réellement couverts)."""
    if not intervalles:
        return []
    tries = sorted(intervalles)
    fusionnes = [list(tries[0])]
    for debut, fin in tries[1:]:
        dernier = fusionnes[-1]
        if debut <= dernier[1] + 1:
            dernier[1] = max(dernier[1], fin)
        else:
            fusionnes.append([debut, fin])
    return [(d, f) for d, f in fusionnes]


def _age_depuis_naissance(naissance):
    aujourd_hui = timezone.localdate()
    return aujourd_hui.year - naissance.year - ((aujourd_hui.month, aujourd_hui.day) < (naissance.month, naissance.day))


def _creneaux_manquants(dispo, creneau):
    """Cœur commun de creneaux_manquants_pour_*: heures des 2 blocs du créneau
    non couvertes par l'ensemble dispo de tuples (jour, heure_debut)."""
    manquants = []
    for jour, debut, fin in [
        (creneau.jour_1, creneau.heure_debut_1, creneau.heure_fin_1),
        (creneau.jour_2, creneau.heure_debut_2, creneau.heure_fin_2),
    ]:
        for h in _heures_couvertes(debut, fin):
            if (jour, h) not in dispo:
                manquants.append((jour, h))
    return manquants


def creneaux_manquants_pour_prof(prof, creneau):
    """Vérifie que le prof est disponible sur toutes les heures couvertes par
    les 2 blocs du créneau. Retourne la liste des (jour, heure) manquants
    (liste vide = compatible)."""
    from .models import DisponibiliteProf

    dispo_prof = set(DisponibiliteProf.objects.filter(prof=prof).values_list('jour_semaine', 'heure_debut'))
    return _creneaux_manquants(dispo_prof, creneau)


def creneaux_manquants_pour_eleve(eleve, creneau):
    """Équivalent de creneaux_manquants_pour_prof pour un élève déjà accepté
    (matrice stockée dans DisponibiliteEleve)."""
    from .models import DisponibiliteEleve

    dispo_eleve = set(DisponibiliteEleve.objects.filter(eleve=eleve).values_list('jour_semaine', 'heure_debut'))
    return _creneaux_manquants(dispo_eleve, creneau)


def creneaux_manquants_pour_matrice(disponibilites_matrice, creneau):
    """Équivalent de creneaux_manquants_pour_eleve pour une candidature pas
    encore acceptée: la matrice est encore la liste JSON brute de
    InscriptionEleve.disponibilites (ex: ['lun_14:00', ...]), pas des lignes
    DisponibiliteEleve en base. Même parsing que matrice_vers_lignes_eleve."""
    dispo = set()
    for entree in disponibilites_matrice:
        jour, heure_str = entree.split('_')
        dispo.add((jour, datetime.datetime.strptime(heure_str, '%H:%M').time()))
    return _creneaux_manquants(dispo, creneau)


def raison_incompatibilite_groupe(eleve, groupe):
    """Vérifie qu'un élève peut être assigné à un groupe donné, selon les
    critères BLOQUANTS uniquement (place restante, horaire, âge, type
    d'abonnement, disponibilité). Retourne une chaîne expliquant le premier
    critère non respecté, ou None si le groupe est compatible. Utilisée à la
    fois pour la suggestion automatique (affichage) et comme garde-fou
    serveur avant toute assignation (sécurité), afin qu'aucune des deux voies
    ne puisse être contournée par l'autre. Voir
    raison_incompatibilite_groupe_inscription, l'équivalent pour une
    candidature pas encore acceptée — les deux fonctions doivent rester
    alignées critère par critère.

    Programme/riwaya/sexe ne sont PLUS bloquants depuis la Tâche 14 (demande
    client explicite) : voir avertissements_groupe pour ces 3 critères,
    désormais informatifs seulement.

    Élève archivé: bloquant depuis le chantier d'archivage du 2026-08-03 — c'est
    le seul point de passage commun à l'ajout, au transfert et à la confirmation
    malgré avertissement, donc le bon (et unique) endroit pour l'interdire."""
    if eleve.statut == 'archive':
        return "الطالب مؤرشف — يجب إعادة تفعيله أولاً قبل إضافته إلى مجموعة."

    if groupe.eleves.filter(id=eleve.id).exists():
        return "الطالب منضم بالفعل إلى هذه المجموعة."

    if groupe.eleves.count() >= groupe.capacite_max:
        return "المجموعة مكتملة العدد."

    creneau = groupe.creneau
    if not creneau:
        return "لا يوجد جدول زمني محدد لهذه المجموعة."

    inscription = eleve.inscription
    if not inscription:
        return "لا يوجد ملف تسجيل مرتبط بهذا الطالب لمقارنة المعايير."

    age = _age_depuis_naissance(inscription.date_naissance)
    if age < creneau.age_min or age > creneau.age_max:
        return "عمر الطالب لا يقع ضمن الفئة العمرية لهذه الحلقة."

    type_offre = inscription.abonnement_type_offre()
    if type_offre and type_offre != groupe.type_capacite:
        return "نوع الاشتراك (فردي/جماعي) لا يتوافق مع نوع هذه المجموعة."

    manquants = creneaux_manquants_pour_eleve(eleve, creneau)
    if manquants:
        return "جدول تفرغ الطالب لا يغطي كامل مواعيد هذه الحلقة."

    return None


def avertissements_groupe(eleve, groupe):
    """Critères informatifs (non bloquants depuis la Tâche 14) pour un couple
    (eleve, groupe) : programme, riwaya, sexe. Retourne la liste des messages
    d'avertissement à afficher — liste vide si tout correspond. À appeler
    uniquement après avoir vérifié raison_incompatibilite_groupe (aucune
    garantie ici si creneau/inscription sont absents)."""
    creneau = groupe.creneau
    inscription = eleve.inscription
    if not creneau or not inscription:
        return []

    avertissements = []
    if inscription.programme != creneau.type_seance:
        avertissements.append("نوع الحلقة (حفظ/تثبيت) لا يتوافق مع برنامج الطالب.")
    if inscription.riwaya != creneau.riwaya:
        avertissements.append("رواية الحلقة لا تتوافق مع رواية الطالب.")
    if creneau.sexe_cible != 'mixte' and creneau.sexe_cible != inscription.sexe:
        avertissements.append("جنس الطالب لا يتوافق مع الفئة المستهدفة لهذه الحلقة.")
    return avertissements


def raison_incompatibilite_groupe_inscription(inscription, groupe):
    """Équivalent de raison_incompatibilite_groupe pour une candidature
    (InscriptionEleve) pas encore acceptée: pas de Eleve/DisponibiliteEleve
    en base, les critères sont lus directement depuis l'inscription.

    Programme/riwaya/sexe ne sont plus bloquants depuis la Tâche 14 — voir
    avertissements_groupe_inscription."""
    if groupe.eleves.count() >= groupe.capacite_max:
        return "المجموعة مكتملة العدد."

    creneau = groupe.creneau
    if not creneau:
        return "لا يوجد جدول زمني محدد لهذه المجموعة."

    age = _age_depuis_naissance(inscription.date_naissance)
    if age < creneau.age_min or age > creneau.age_max:
        return "عمر الطالب لا يقع ضمن الفئة العمرية لهذه الحلقة."

    type_offre = inscription.abonnement_type_offre()
    if type_offre and type_offre != groupe.type_capacite:
        return "نوع الاشتراك (فردي/جماعي) لا يتوافق مع نوع هذه المجموعة."

    manquants = creneaux_manquants_pour_matrice(inscription.disponibilites, creneau)
    if manquants:
        return "جدول تفرغ الطالب لا يغطي كامل مواعيد هذه الحلقة."

    return None


def avertissements_groupe_inscription(inscription, groupe):
    """Équivalent de avertissements_groupe pour une candidature pas encore
    acceptée."""
    creneau = groupe.creneau
    if not creneau:
        return []

    avertissements = []
    if inscription.programme != creneau.type_seance:
        avertissements.append("نوع الحلقة (حفظ/تثبيت) لا يتوافق مع برنامج الطالب.")
    if inscription.riwaya != creneau.riwaya:
        avertissements.append("رواية الحلقة لا تتوافق مع رواية الطالب.")
    if creneau.sexe_cible != 'mixte' and creneau.sexe_cible != inscription.sexe:
        avertissements.append("جنس الطالب لا يتوافق مع الفئة المستهدفة لهذه الحلقة.")
    return avertissements


def _categorie_age_creneau(creneau):
    """'enfants' si le créneau est entièrement sous AGE_SEUIL_ADULTE, 'adultes'
    si entièrement au-dessus, 'mixte' s'il chevauche les deux (aucune
    catégorie unique à comparer dans ce cas). Règle confirmée par le client
    pour avertissements_prof_creneau (Tâche 18, Partie C, 2026-07-26)."""
    if creneau.age_max < AGE_SEUIL_ADULTE:
        return 'enfants'
    if creneau.age_min >= AGE_SEUIL_ADULTE:
        return 'adultes'
    return 'mixte'


def avertissements_prof_creneau(prof, creneau):
    """Avertissements non bloquants (Tâche 18, Partie C ; complété le
    2026-08-09) si l'horaire, la tranche d'âge ou le sexe cible du créneau
    ne correspondent pas à ce que le prof a déclaré. Dans les 3 cas, le
    مدير peut confirmer et enregistrer quand même — voir groupe_ajouter/
    groupe_modifier, qui affichent ces messages et exigent confirme='1'
    avant d'enregistrer si la liste n'est pas vide.

    Historique du critère horaire : jusqu'au 2026-08-09, une
    incompatibilité d'horaire (creneaux_manquants_pour_prof) bloquait
    l'enregistrement sans recours, séparément de ces avertissements
    (contrairement à l'âge/au sexe, déjà non bloquants). Décision
    explicite du client : les 3 critères suivent désormais EXACTEMENT le
    même mécanisme — creneaux_manquants_pour_prof reste la fonction qui
    calcule l'incompatibilité, mais elle n'est plus jamais bloquante par
    elle-même, seulement remontée ici comme avertissement.

    Reste SILENCIEUX si le prof n'a rien déclaré (dispo vide, ou aucune
    préférence d'âge/genre cochée) — l'absence de déclaration n'est pas une
    preuve d'incompatibilité, seule une contradiction explicite avec une
    valeur réellement déclarée déclenche un avertissement (confirmé par le
    client pour l'âge/le genre ; même logique appliquée à l'horaire — un
    prof qui n'a rempli AUCUNE case de sa matrice de disponibilités
    n'affiche aucun avertissement horaire, cas couvert par
    creneaux_manquants_pour_prof lui-même qui ne peut renvoyer de créneaux
    manquants que là où le prof a au moins une disponibilité ailleurs)."""
    from .models import Creneau

    avertissements = []

    manquants = creneaux_manquants_pour_prof(prof, creneau)
    if manquants and prof.disponibilites.exists():
        jours_dict = dict(Creneau.JOUR_CHOICES)
        details = '، '.join(f'{jours_dict.get(j, j)} {h.strftime("%H:%M")}' for j, h in manquants)
        avertissements.append(
            f'تنبيه: التوقيت المختار لا يتوافق بالكامل مع جدول تفرغ هذا الأستاذ المصرَّح به عند تسجيله — '
            f'غير متفرغ حسب تصريحه في: {details}.'
        )

    categorie = _categorie_age_creneau(creneau)
    if categorie != 'mixte' and prof.type_eleve_preference:
        if categorie not in prof.type_eleve_preference and 'les_deux' not in prof.type_eleve_preference:
            avertissements.append("الفئة العمرية المستهدفة لهذه الحلقة لا تتوافق مع تفضيل المعلم المصرَّح به عند تسجيله.")

    if creneau.sexe_cible != 'mixte' and prof.contrainte_genre:
        if creneau.sexe_cible not in prof.contrainte_genre and 'mixte' not in prof.contrainte_genre:
            avertissements.append("جنس الفئة المستهدفة لهذه الحلقة لا يتوافق مع تفضيل المعلم المصرَّح به عند تسجيله.")

    return avertissements


def groupes_compatibles_pour_eleve(eleve):
    """Liste des groupes actifs compatibles avec un élève. Reste strict sur
    TOUS les critères (y compris programme/riwaya/sexe, même si Tâche 14 les
    a rendus non bloquants pour l'ajout manuel) : cette liste sert de
    suggestion "idéale" en un clic, distincte de l'ajout manuel qui accepte
    désormais ces 3 critères avec un simple avertissement."""
    from .models import Groupe

    candidats = Groupe.objects.filter(statut='actif').exclude(eleves=eleve).select_related('creneau', 'prof__user')
    return [
        g for g in candidats
        if raison_incompatibilite_groupe(eleve, g) is None and not avertissements_groupe(eleve, g)
    ]


def groupes_compatibles_pour_inscription(inscription):
    """Équivalent de groupes_compatibles_pour_eleve pour une candidature pas
    encore acceptée (affichage informatif sur la fiche de candidature, avant
    que le directeur clique accepter/refuser)."""
    from .models import Groupe

    candidats = Groupe.objects.filter(statut='actif').select_related('creneau', 'prof__user')
    return [
        g for g in candidats
        if raison_incompatibilite_groupe_inscription(inscription, g) is None
        and not avertissements_groupe_inscription(inscription, g)
    ]


def matrice_vers_lignes(prof, valeurs):
    """Remplace les DisponibiliteProf d'un prof par les valeurs de la matrice
    (liste de chaînes 'jour_HH:MM'). Utilisé à la fois pour la copie initiale
    depuis une candidature et pour l'approbation d'une demande de modification."""
    from .models import DisponibiliteProf

    DisponibiliteProf.objects.filter(prof=prof).delete()
    lignes = []
    for entree in valeurs:
        jour, heure_str = entree.split('_')
        lignes.append(DisponibiliteProf(prof=prof, jour_semaine=jour, heure_debut=heure_str))
    DisponibiliteProf.objects.bulk_create(lignes)


def matrice_vers_lignes_eleve(eleve, valeurs):
    """Équivalent de matrice_vers_lignes pour un élève. Contrairement au prof,
    l'élève n'a pas de workflow de demande — seul l'admin appelle ceci
    (copie initiale à la validation, ou édition directe depuis sa fiche)."""
    from .models import DisponibiliteEleve

    DisponibiliteEleve.objects.filter(eleve=eleve).delete()
    lignes = []
    for entree in valeurs:
        jour, heure_str = entree.split('_')
        lignes.append(DisponibiliteEleve(eleve=eleve, jour_semaine=jour, heure_debut=heure_str))
    DisponibiliteEleve.objects.bulk_create(lignes)


def etendre_seances(groupe, horizon_semaines=HORIZON_SEMAINES):
    """Complète les séances d'un groupe jusqu'à horizon_semaines à partir d'aujourd'hui.

    Ne repart JAMAIS en arrière: on continue toujours à partir du jour suivant
    la dernière séance déjà connue pour ce groupe. Ça évite de recréer une
    séance qu'un admin aurait annulée ou déplacée (point 4) dans une semaine
    déjà générée.
    """
    from .models import Seance

    creneau = groupe.creneau
    if not creneau:
        return

    aujourd_hui = timezone.localdate()
    limite = aujourd_hui + datetime.timedelta(weeks=horizon_semaines)

    derniere_seance = Seance.objects.filter(groupe=groupe).order_by('-date').first()
    depart = aujourd_hui
    if derniere_seance and derniere_seance.date >= depart:
        depart = derniere_seance.date + datetime.timedelta(days=1)

    if depart > limite:
        return

    creneaux_jour = [
        (creneau.jour_1, creneau.heure_debut_1),
        (creneau.jour_2, creneau.heure_debut_2),
    ]

    a_creer = []
    jour_courant = depart
    while jour_courant <= limite:
        for jour_code, heure in creneaux_jour:
            if jour_courant.weekday() == JOUR_INDEX[jour_code]:
                a_creer.append(Seance(
                    groupe=groupe,
                    date=jour_courant,
                    heure=heure,
                    type='normal',
                    statut='planifiee',
                ))
        jour_courant += datetime.timedelta(days=1)

    if a_creer:
        Seance.objects.bulk_create(a_creer)


CLE_CACHE_HORIZON_SEANCES_ETENDU = 'seances_horizon_etendu'
DUREE_CACHE_HORIZON_SEANCES_SECONDES = 3600  # 1h — voir docstring ci-dessous


def etendre_toutes_les_seances():
    """Appelée à chaque visite des pages séances/calendrier admin: pousse l'horizon
    de génération de tous les groupes actifs ayant un créneau, sans jamais retoucher
    aux semaines déjà couvertes.

    Exclut les groupes dont le prof est archivé (chantier du 2026-08-03): pas de
    plantage, mais plus aucune nouvelle séance générée pour un groupe sans prof
    actif — les séances déjà générées restent intactes, à annuler/reporter ou à
    faire reprendre par un nouveau prof manuellement (voir admin_prof_detail,
    bannière d'avertissement affichée quand un prof archivé a encore des groupes).

    Garde-fou (audit de performance du 2026-08-11) : cette fonction relisait/
    écrivait pour TOUS les groupes actifs à CHAQUE chargement de admin_calendrier
    ou admin_seances, même quand rien n'avait besoin d'être étendu — mesuré à
    ~2,4s/22 requêtes rien que pour vérifier, plus une écriture systématique tant
    que l'horizon glissant de 8 semaines n'est pas rattrapé. Le cache par défaut
    de Django (LocMemCache, actif sans configuration supplémentaire) sert de
    verrou temporel simple : ne relance le vrai travail qu'au plus une fois par
    heure. Effet secondaire assumé et sans risque : le bord de l'horizon glissant
    (8 semaines à l'avance) peut avancer jusqu'à ~1h plus tard que si la fonction
    tournait à chaque requête — jamais de séance déjà visible qui disparaît, et
    la création/le changement de créneau d'un groupe continue de générer SES
    séances immédiatement via regenerer_pour_nouveau_creneau (inchangé, appelé
    séparément). Avec 2 workers Gunicorn, le verrou est par processus (LocMemCache
    n'est pas partagé entre eux) : au pire, le vrai travail peut s'exécuter 2 fois
    dans la même heure au lieu d'une seule — toujours une réduction massive par
    rapport à "à chaque requête"."""
    from django.core.cache import cache
    from .models import Groupe

    if cache.get(CLE_CACHE_HORIZON_SEANCES_ETENDU):
        return
    cache.set(CLE_CACHE_HORIZON_SEANCES_ETENDU, True, DUREE_CACHE_HORIZON_SEANCES_SECONDES)

    groupes = Groupe.objects.filter(statut='actif', creneau__isnull=False).exclude(prof__statut='archive')
    for groupe in groupes:
        etendre_seances(groupe)


def regenerer_pour_nouveau_creneau(groupe):
    """À appeler quand le créneau d'un groupe est assigné pour la première fois
    ou changé pour un autre. Supprime les séances futures non terminées (elles
    ne correspondent plus au nouvel horaire) puis régénère depuis aujourd'hui."""
    from .models import Seance

    aujourd_hui = timezone.localdate()
    Seance.objects.filter(
        groupe=groupe,
        date__gte=aujourd_hui,
    ).exclude(statut='terminee').delete()

    etendre_seances(groupe)


def calculer_progression_eleve(eleve, mois=None):
    """Suivi de progression cumulé d'un élève, basé sur les ayats mémorisés
    (nb_ayat_memorises de chaque Presence). Compté en ayats, pas en pages
    (la pagination du mushaf varie selon l'édition/riwaya, l'ayah est universel).

    Pour chaque sourate touchée, les plages de toutes les séances sont
    fusionnées via fusionner_intervalles avant de compter les ayat couverts —
    jamais une simple étendue min/max (voir Tâche 6c du 2026-07-25) : une
    révision sur une plage déjà couverte n'ajoute rien, et deux plages non
    contiguës (ex: 1-10 puis 60-74) restent deux blocs distincts (25 ayat au
    total) plutôt qu'une étendue [1,74] qui compterait à tort des ayat jamais
    mémorisés (11-59) comme acquis.

    mois: filtre optionnel 'AAAA-MM' (ex: '2026-01') — ne restreint QUE les
    Presence prises en compte, à ce mois précis. None (par défaut) = tout
    l'historique, comportement inchangé pour tous les appels existants
    (dashboard_eleve, eleve_progression, admin_eleve_detail). Utilisé
    uniquement par dashboard.views.bilans_mensuels_detail_seance (Niveau 2 de
    تقييم الطلاب, Point 11 du 2026-08-04 — anciennement l'onglet 'حسب الحصة')
    pour respecter le filtre 'الشهر' actif (Tâche du 2026-08-03) — avant ce
    paramètre, ce mode ignorait silencieusement le filtre et affichait
    toujours tout l'historique, même avec ?mois=X dans l'URL."""
    from django.db.models import Q
    from .models import Presence, NotePresence
    from .quran_data import SOURATES_NOMS, SOURATES_NB_AYAT

    # Élargi (Tâche 9 — bug signalé le 2026-07-25) : une Presence avec des
    # critères numériques /20 mais sans sourate_memorisee (l'élève n'a pas
    # mémorisé de nouveau passage ce jour-là, mais a bien été noté/consigné)
    # était auparavant totalement exclue de l'historique — invisible partout
    # où admin_eleve_detail.html et eleve_progression.html réutilisent
    # progression.historique pour afficher l'évaluation d'une séance.
    # notes_criteres__isnull=False (Point 7, Tâche du 2026-08-04) remplace
    # l'ancien test note_hifz__isnull=False -- ce dernier champ est gelé et ne
    # sera plus jamais rempli pour une nouvelle Presence. distinct() nécessaire
    # : la jointure sur notes_criteres peut dupliquer la ligne Presence.
    presences = Presence.objects.filter(eleve=eleve).filter(
        Q(sourate_memorisee__isnull=False) | Q(notes_criteres__isnull=False)
    ).distinct()
    if mois:
        annee, _, num_mois = mois.partition('-')
        presences = presences.filter(seance__date__year=annee, seance__date__month=num_mois)
    presences = presences.select_related('seance').order_by('seance__date', 'seance__heure')

    notes_par_presence = {}
    for n in NotePresence.objects.filter(presence__eleve=eleve).select_related('critere'):
        notes_par_presence.setdefault(n.presence_id, []).append(
            {'nom_ar': n.critere.nom_ar, 'note': n.note, 'ordre': n.critere.ordre}
        )
    for liste in notes_par_presence.values():
        liste.sort(key=lambda x: x['ordre'])

    intervalles_par_sourate = {}
    notes_par_sourate = {}
    historique = []

    for p in presences:
        nb = p.nb_ayat_memorises

        historique.append({
            'date': p.seance.date,
            'groupe': p.seance.groupe.nom,
            'sourate': p.nom_sourate_memorisee,
            'ayah_debut': p.ayah_debut_memorisation,
            'ayah_fin': p.ayah_fin_memorisation,
            'nb_ayat': nb,
            'note_code': p.note_memorisation,
            'note_display': p.get_note_memorisation_display() if p.note_memorisation else None,
            # Critères dynamiques (Point 7, Tâche du 2026-08-04) — remplacent
            # les 4 anciens champs fixes note_hifz/note_muraja3a/note_tilawa/
            # note_mouwazaba (gelés, plus jamais réécrits).
            'notes_criteres': notes_par_presence.get(p.id, []),
            'consigne_memorisation': p.consigne_memorisation,
            'consigne_revision': p.consigne_revision,
            # Remarque par séance (Point 11, Tâche du 2026-08-04) — existait déjà
            # sur Presence mais n'était jusqu'ici jamais incluse dans historique.
            'remarque': p.remarque,
        })

        if p.sourate_memorisee is None:
            continue

        numero = p.sourate_memorisee
        intervalles_par_sourate.setdefault(numero, []).append(
            (p.ayah_debut_memorisation, p.ayah_fin_memorisation)
        )
        # Écrasé à chaque passage (ordre chronologique croissant) -> reste
        # la note de la séance la PLUS RÉCENTE pour cette sourate.
        notes_par_sourate[numero] = {
            'note_code': p.note_memorisation,
            'note_display': p.get_note_memorisation_display() if p.note_memorisation else None,
        }

    total_ayat = 0
    par_sourate_liste = []
    for numero, intervalles_bruts in intervalles_par_sourate.items():
        fusionnes = fusionner_intervalles(intervalles_bruts)
        couverts = sum(fin - debut + 1 for debut, fin in fusionnes)
        total_ayat += couverts

        total_ayat_sourate = SOURATES_NB_AYAT.get(numero, 0)
        pourcentage = round((couverts / total_ayat_sourate) * 100) if total_ayat_sourate else 0
        par_sourate_liste.append({
            'numero': numero,
            'nom': SOURATES_NOMS.get(numero),
            'ayah_debut': fusionnes[0][0],
            'ayah_fin': fusionnes[-1][1],
            'plages_texte': '، '.join(f'{debut}-{fin}' for debut, fin in fusionnes),
            'ayat_couverts': couverts,
            'total_ayat_sourate': total_ayat_sourate,
            'pourcentage': min(pourcentage, 100),
            'note_code': notes_par_sourate[numero]['note_code'],
            'note_display': notes_par_sourate[numero]['note_display'],
        })
    par_sourate_liste.sort(key=lambda item: item['numero'])

    return {
        'total_ayat_memorises': total_ayat,
        'nb_sourates_distinctes': len(intervalles_par_sourate),
        'par_sourate': par_sourate_liste,
        'historique': list(reversed(historique)),
    }


def generer_brouillon_bilan_mensuel(eleve, prof, mois_reference):
    """Agrège les Presence du mois (eleve, prof, mois) en un brouillon texte pour les
    champs memorisation/revision d'un nouveau BilanMensuel — un point de départ que le
    prof relit et corrige avant de sauvegarder, pas un résumé figé. Ne couvre PAS les
    remarques de discipline (aucune donnée par séance équivalente à agréger)."""
    from .models import Presence

    presences = Presence.objects.filter(
        eleve=eleve, seance__groupe__prof=prof,
        seance__date__year=mois_reference.year, seance__date__month=mois_reference.month,
    ).select_related('seance').order_by('seance__date')

    lignes_memorisation = []
    lignes_revision = []
    for p in presences:
        if p.sourate_memorisee:
            note = f' — {p.get_note_memorisation_display()}' if p.note_memorisation else ''
            lignes_memorisation.append(
                f'{p.seance.date:%d-%m}: {p.nom_sourate_memorisee} '
                f'({p.ayah_debut_memorisation}-{p.ayah_fin_memorisation}){note}'
            )
        if p.sourate_revisee:
            note = f' — {p.get_note_revision_display()}' if p.note_revision else ''
            lignes_revision.append(
                f'{p.seance.date:%d-%m}: {p.nom_sourate_revisee} '
                f'({p.ayah_debut_revision}-{p.ayah_fin_revision}){note}'
            )

    return {
        'memorisation': '\n'.join(lignes_memorisation),
        'revision': '\n'.join(lignes_revision),
    }


RING_CIRCONFERENCE_HIZB = 452.39  # 2*pi*72, rayon du cercle SVG (voir templates/dashboard/_ring_hizb.html)

FRACTION_QUART = {1: '1/4', 2: '1/2', 3: '3/4'}


def _couverture_ayat_par_sourate(eleve):
    """{numero_sourate: [(debut, fin), ...]} — intervalles réellement fusionnés
    (fusionner_intervalles) sur toutes les Presence de l'élève avec
    mémorisation enregistrée, pas une étendue min/max (voir Tâche 6c du
    2026-07-25) : deux plages non contiguës d'une même sourate (ex: 1-10 puis
    60-74) restent deux blocs séparés, jamais fusionnés à tort en [1,74] qui
    déclarerait couverts des ayat jamais mémorisés (11-59)."""
    from .models import Presence

    brut = {}
    valeurs = Presence.objects.filter(
        eleve=eleve, sourate_memorisee__isnull=False
    ).values_list('sourate_memorisee', 'ayah_debut_memorisation', 'ayah_fin_memorisation')
    for numero, debut, fin in valeurs:
        brut.setdefault(numero, []).append((debut, fin))
    return {numero: fusionner_intervalles(intervalles) for numero, intervalles in brut.items()}


def _quart_est_couvert(quart, couverture):
    """Un quart de hizb (quran_data.HIZB_QUARTERS) est couvert si la
    mémorisation enregistrée de l'élève recouvre ENTIÈREMENT sa plage
    d'ayat, sourate par sourate — un quart peut chevaucher 2 sourates
    consécutives à sa frontière (ex: hizb 45, quart 3 = 36:60 -> 37:21). Une
    plage de quart doit être entièrement contenue dans UN SEUL intervalle
    fusionné de la sourate — jamais à cheval sur deux blocs disjoints, qui
    signifierait un trou non mémorisé entre les deux (voir Tâche 6c)."""
    from .quran_data import SOURATES_NB_AYAT

    (sourate_debut, ayah_debut), (sourate_fin, ayah_fin) = quart
    for sourate in range(sourate_debut, sourate_fin + 1):
        intervalles = couverture.get(sourate)
        if not intervalles:
            return False
        borne_debut = ayah_debut if sourate == sourate_debut else 1
        borne_fin = ayah_fin if sourate == sourate_fin else SOURATES_NB_AYAT[sourate]
        if not any(debut <= borne_debut and fin >= borne_fin for debut, fin in intervalles):
            return False
    return True


def calculer_hizb_precis(eleve):
    """Progression réelle dans les 60 hizb, basée sur les VRAIES sourates/ayat
    mémorisés (pas sur un total d'ayat cumulé en supposant une progression
    linéaire depuis le début du Coran — un élève peut commencer par le
    hizb 60 ou mémoriser des sourates au milieu du Coran).

    Chaque hizb est découpé en 4 quarts (quran_data.HIZB_QUARTERS, le
    découpage universel du Coran). Un hizb ne compte comme complet que si
    ses 4 quarts sont couverts. Retourne le nombre total de hizb complets
    et la liste de tous les hizb partiellement couverts (1 à 3 quarts sur
    4), chacun avec sa fraction — un élève peut mémoriser dans plusieurs
    hizb non consécutifs à la fois, donc pas de "hizb en cours" unique."""
    from .quran_data import HIZB_QUARTERS

    couverture = _couverture_ayat_par_sourate(eleve)

    nb_hizb_complets = 0
    hizb_en_cours = []
    for numero_hizb, quarts in enumerate(HIZB_QUARTERS, start=1):
        nb_quarts_couverts = sum(1 for quart in quarts if _quart_est_couvert(quart, couverture))
        if nb_quarts_couverts == 4:
            nb_hizb_complets += 1
        elif nb_quarts_couverts > 0:
            hizb_en_cours.append({
                'numero': numero_hizb,
                'quarts_couverts': nb_quarts_couverts,
                'fraction': FRACTION_QUART[nb_quarts_couverts],
            })

    return {
        'nb_hizb_complets': nb_hizb_complets,
        'hizb_en_cours': hizb_en_cours,
    }


def ring_dashoffset_hizb(nb_hizb_complets):
    """Remplissage de l'anneau SVG de progression du hifz (accueil élève +
    page "تقدمي في الحفظ", composant _ring_hizb.html), proportionnel au
    nombre de hizb complets sur 60."""
    return round(RING_CIRCONFERENCE_HIZB * (1 - nb_hizb_complets / 60), 1)


AGE_SEUIL_ADULTE = 18  # seuil enfant/adulte — confirmé par le client (moins de 18 = enfant, 18 et plus = adulte)


def tranche_age_depuis_naissance(date_naissance):
    """'enfant' (< AGE_SEUIL_ADULTE) ou 'adulte' (>= AGE_SEUIL_ADULTE). Seule
    fonction faisant autorité sur cette catégorisation dans tout le projet —
    réutilisée par la grille de rémunération (_tranche_age_eleve) ET par la
    validation du formulaire d'inscription élève (inscriptions.views)."""
    age = _age_depuis_naissance(date_naissance)
    return 'adulte' if age >= AGE_SEUIL_ADULTE else 'enfant'


def age_correspond_a_categorie(date_naissance, type_age):
    """True si la catégorie choisie à l'inscription (type_age: 'enfant'/'adulte',
    le paramètre d'URL du formulaire) correspond à l'âge réel calculé depuis
    date_naissance. Garde-fou serveur, indépendant de tout JS — voir
    inscriptions.views.inscription_eleve_formulaire."""
    return tranche_age_depuis_naissance(date_naissance) == type_age


def _tranche_age_eleve(eleve):
    """'enfant'/'adulte' pour un Eleve déjà validé, ou None si l'âge est
    inconnu (élève sans dossier d'inscription lié, ou dossier sans date de
    naissance — Eleve n'a pas de date_naissance propre, la seule source
    fiable est eleve.inscription.date_naissance). Jamais d'hypothèse
    silencieuse ici: un âge inconnu doit rester visible comme tel dans le
    détail du calcul, vu l'impact direct sur une somme d'argent réelle."""
    if eleve.inscription is None or eleve.inscription.date_naissance is None:
        return None
    return tranche_age_depuis_naissance(eleve.inscription.date_naissance)


def lien_seance_est_actif(seance):
    """True si l'heure actuelle tombe dans la fenêtre [début - marge_avant,
    fin + marge_apres] de cette séance — Point 15, Tâche du 2026-08-04.
    L'horaire de la séance elle-même est toujours lu tel quel depuis l'objet
    passé en argument (jamais mis en cache ici). Le réglage de marge (avant/
    après) passe en revanche par get_reglage_lien_seance() depuis le
    2026-08-11 — CORRIGÉ : cette fonction faisait auparavant son propre
    ReglageLienSeance.objects.get_or_create(pk=1) séparé, doublon exact de
    get_reglage_lien_seance() (models.py) qui court-circuitait sa mise en
    cache. Appelée une fois PAR CARTE DE SÉANCE affichée (_meet_icon.html) —
    c'était la cause confirmée des ~25 requêtes restantes mesurées sur
    dashboard_prof. Effet de bord assumé de la mise en cache (voir
    get_reglage_lien_seance()) : un changement de MARGE par l'admin peut
    mettre jusqu'à ~60s à se refléter sur un autre processus Gunicorn que
    celui qui a enregistré le changement — jamais plus, jamais pour
    l'horaire de la séance elle-même. fin_datetime retombe sur debut_datetime
    si le groupe n'a pas/plus de créneau (voir Seance.fin_datetime), donc la
    fenêtre se réduit à [début - marge_avant, début + marge_apres] dans ce
    cas. False si le groupe n'a aucun lien de réunion renseigné (rien à
    activer) ou si la séance est annulée."""
    import datetime
    from .models import get_reglage_lien_seance

    if not seance.groupe.lien_reunion or seance.statut == 'annulee':
        return False

    reglage = get_reglage_lien_seance()
    debut = seance.debut_datetime
    fin = seance.fin_datetime or debut
    fenetre_debut = debut - datetime.timedelta(minutes=reglage.marge_avant_minutes)
    fenetre_fin = fin + datetime.timedelta(minutes=reglage.marge_apres_minutes)
    return fenetre_debut <= timezone.now() <= fenetre_fin


def calculer_remuneration_prof(prof, mois=None, tarifs=None):
    """Rémunération mensuelle d'un prof selon la grille TarifRemuneration
    (type_capacite du groupe × tranche d'âge). Détail par groupe pour que le
    calcul soit vérifiable. Ne retourne QUE le calcul de base de la grille —
    majoration_mensuelle (Prof) n'est ni lue ni additionnée ici: elle ne doit
    jamais atteindre la page du prof, même fondue dans un total, voir
    templates/dashboard/prof_remuneration.html.

    Toujours "à la volée" sur l'état actuel, jamais historisé (voir
    mshrif_remuneration) — donc pas de "mois passé" distinct à préserver ici :
    chaque affichage de cette fonction, quelle que soit la date à laquelle on
    la consulte, ne montre QUE le mois en cours.

    Correction du 2026-08-04 (Point 6, bug signalé par le client) : pour un
    groupe type_capacite='individuel', l'ancien calcul multipliait le tarif
    par le nombre d'élèves ACTIFS actuels du groupe — un montant mensuel FIXE
    par élève inscrit, peu importe le nombre de séances réellement tenues ce
    mois-ci. Désormais compté PAR SÉANCE individuelle réellement tenue ce
    mois (Seance.statut='terminee') ET où l'élève était marqué présent
    (Presence.statut='present') — une séance individuelle annulée, restée
    'planifiee', ou où l'unique élève était absent, n'est pas payée. Les
    groupes (type_capacite='groupe') gardent EXACTEMENT l'ancien calcul
    (nombre d'élèves actifs × tarif mensuel), volontairement inchangé.

    Champs ajoutés le 2026-08-05 (chantier groupé, Point 2 — refonte de
    راتبي) pour séparer clairement groupes/individuel à l'affichage, SANS
    changer 'detail'/'total_calcule' (toujours le mélange complet, requis tel
    quel par prof_remuneration.html, admin_prof_detail.html et
    mshrif_remuneration — jamais retouchés ici) :
    - detail_groupes : sous-ensemble de detail, uniquement type_capacite
      != 'individuel' (affichage inchangé de "المجموعات الجماعية").
    - a_des_groupes_individuels : condition d'affichage de la section
      "الحصص الفردية" (absente si False — jamais un bloc vide/à 0).
    - individuel_reel : somme des sous_total des groupes individuels
      (= le montant déjà "gagné" ce mois, séances confirmées présentes).
    - individuel_projection : "si toutes les séances prévues ce mois étaient
      tenues" — basée sur les élèves ACTIFS actuels de chaque groupe
      individuel (pas sur l'historique de présence) × le nombre de séances
      programmées ce mois pour ce groupe (annulées exclues, elles ne seront
      plus tenues).
    - individuel_nb_seances_confirmees / individuel_nb_seances_prevues /
      individuel_pourcentage : pour le ratio "X من Y حصص" et la barre de
      progression.

    mois (optionnel, 'AAAA-MM', Tâche du 2026-08-05, Point 3 — page مدير/مشرف
    "متابعة رواتب الأساتذة") : None (défaut) = mois calendaire réel,
    comportement inchangé. Un autre mois ne change QUE le calcul "الحصص
    الفردية" (basé sur de vraies dates de Seance/Presence, donc exact pour
    n'importe quel mois passé). "المجموعات الجماعية" reste TOUJOURS basé sur
    les élèves ACTIFS actuels, quel que soit le mois choisi — aucune
    historisation de l'appartenance aux groupes n'existe dans ce projet, donc
    ce sous-total n'est jamais rétroactivement exact pour un mois passé.
    Documenté explicitement dans l'UI (voir mshrif_remuneration.html) pour ne
    jamais laisser croire à une vraie vue historique complète.

    tarifs (optionnel, dict {(type_capacite, tranche_age): montant}, Tâche
    du 2026-08-06 — audit de performance, point 8) : évite de refaire
    TarifRemuneration.objects.all() à CHAQUE appel quand cette fonction est
    rappelée en boucle sur plusieurs profs (mshrif_remuneration) — la grille
    tarifaire est la même pour tout le monde, un seul appelant qui boucle
    peut la charger UNE fois et la transmettre ici. None (défaut) = ancien
    comportement inchangé (requête interne), pour les appelants à un seul
    prof (prof_remuneration, admin_prof_remuneration_detail)."""
    from .models import TarifRemuneration, Presence, Seance

    if tarifs is None:
        tarifs = {
            (t.type_capacite, t.tranche_age): t.montant
            for t in TarifRemuneration.objects.all()
        }
    aujourdhui = timezone.localdate()
    if mois:
        annee_str, _, mois_str = mois.partition('-')
        annee_calc, mois_calc = int(annee_str), int(mois_str)
    else:
        annee_calc, mois_calc = aujourdhui.year, aujourdhui.month

    detail = []
    total_calcule = 0
    a_des_groupes_individuels = False
    individuel_reel = 0
    individuel_projection = 0
    individuel_nb_seances_confirmees = 0
    individuel_nb_seances_prevues = 0

    for groupe in prof.groupes.all():
        tarif_enfant = tarifs.get((groupe.type_capacite, 'enfant'), 0)
        tarif_adulte = tarifs.get((groupe.type_capacite, 'adulte'), 0)

        if groupe.type_capacite == 'individuel':
            a_des_groupes_individuels = True
            # Une ligne par séance individuelle réellement tenue ce mois-ci
            # (présence confirmée par le prof), pas un montant mensuel fixe.
            presences_mois = Presence.objects.filter(
                seance__groupe=groupe, seance__statut='terminee', statut='present',
                seance__date__year=annee_calc, seance__date__month=mois_calc,
            ).select_related('eleve__inscription')
            nb_enfants = 0
            nb_adultes = 0
            nb_age_inconnu = 0
            for p in presences_mois:
                tranche = _tranche_age_eleve(p.eleve)
                if tranche == 'enfant':
                    nb_enfants += 1
                elif tranche == 'adulte':
                    nb_adultes += 1
                else:
                    nb_age_inconnu += 1

            # Projection : nombre de séances programmées ce mois (annulées
            # exclues) × ce que rapporterait chacune si tenue par les élèves
            # ACTIFS actuels du groupe.
            nb_seances_prevues_groupe = Seance.objects.filter(
                groupe=groupe, date__year=annee_calc, date__month=mois_calc,
            ).exclude(statut='annulee').count()
            nb_enfants_actifs = 0
            nb_adultes_actifs = 0
            for eleve in groupe.eleves.filter(statut='actif').select_related('inscription'):
                tranche = _tranche_age_eleve(eleve)
                if tranche == 'enfant':
                    nb_enfants_actifs += 1
                elif tranche == 'adulte':
                    nb_adultes_actifs += 1
            individuel_projection += nb_seances_prevues_groupe * (
                nb_enfants_actifs * tarif_enfant + nb_adultes_actifs * tarif_adulte
            )
            individuel_nb_seances_confirmees += presences_mois.count()
            individuel_nb_seances_prevues += nb_seances_prevues_groupe
        else:
            # Groupes — calcul INCHANGÉ (nombre d'élèves actifs × tarif mensuel).
            nb_enfants = 0
            nb_adultes = 0
            nb_age_inconnu = 0
            for eleve in groupe.eleves.filter(statut='actif').select_related('inscription'):
                tranche = _tranche_age_eleve(eleve)
                if tranche == 'enfant':
                    nb_enfants += 1
                elif tranche == 'adulte':
                    nb_adultes += 1
                else:
                    nb_age_inconnu += 1

        montant_enfants = nb_enfants * tarif_enfant
        montant_adultes = nb_adultes * tarif_adulte
        sous_total = montant_enfants + montant_adultes
        total_calcule += sous_total
        if groupe.type_capacite == 'individuel':
            individuel_reel += sous_total

        detail.append({
            'groupe': groupe,
            'nb_enfants': nb_enfants,
            'nb_adultes': nb_adultes,
            'tarif_enfant': tarif_enfant,
            'tarif_adulte': tarif_adulte,
            'montant_enfants': montant_enfants,
            'montant_adultes': montant_adultes,
            'sous_total': sous_total,
            'nb_age_inconnu': nb_age_inconnu,
        })

    return {
        'detail': detail,
        'total_calcule': total_calcule,
        'detail_groupes': [d for d in detail if d['groupe'].type_capacite != 'individuel'],
        'a_des_groupes_individuels': a_des_groupes_individuels,
        'individuel_reel': individuel_reel,
        'individuel_projection': individuel_projection,
        'individuel_nb_seances_confirmees': individuel_nb_seances_confirmees,
        'individuel_nb_seances_prevues': individuel_nb_seances_prevues,
        'individuel_pourcentage': (
            round(individuel_nb_seances_confirmees / individuel_nb_seances_prevues * 100)
            if individuel_nb_seances_prevues else 0
        ),
    }


def navigation_mois_et_semaines(seances_qs, request, aujourdhui, borne_avant=True):
    """Agenda groupé par semaine à l'intérieur d'un mois navigable — extrait
    de dashboard_superviseur (Point 1, Tâche du 2026-08-05) pour être
    réutilisé tel quel par dashboard_prof (Tâche du même jour, "آخر الحصص")
    plutôt que de dupliquer cette logique deux fois, comme demandé.

    seances_qs : queryset de Seance déjà filtré/scopé par l'appelant (par
    prof, par مؤطر...), PAS encore borné par mois — cette fonction s'en
    charge.
    aujourdhui : timezone.localdate() de l'appelant (pas recalculé ici, pour
    ne jamais désynchroniser "aujourd'hui" entre deux parties d'une même vue).
    borne_avant : True (par défaut) = n'inclut que les séances strictement
    passées (date__lt=aujourdhui) — usage "historique/آخر الحصص". False =
    inclut tout le mois choisi sans restriction de date (utile si un futur
    appelant veut aussi une vue "à venir" groupée par ce même mécanisme).

    mois_nav (GET, format 'AAAA-MM') : mois courant par défaut. La navigation
    "mois suivant" est bloquée au-delà du mois calendaire réel (pas de sens à
    naviguer vers un mois qui n'a pas encore commencé pour une vue
    "historique"). Retourne un dict prêt à fusionner dans le contexte du
    template : semaines (plus récente en premier, chaque item = {debut, fin,
    seances, nb}), mois_nav_date, mois_nav_param, mois_precedent_param,
    mois_suivant_param, mois_suivant_autorise."""
    import calendar

    mois_nav_param = request.GET.get('mois_nav', '')
    try:
        annee_nav, mois_nav_num = map(int, mois_nav_param.split('-'))
        mois_nav_date = datetime.date(annee_nav, mois_nav_num, 1)
    except (ValueError, TypeError):
        annee_nav, mois_nav_num = aujourdhui.year, aujourdhui.month
        mois_nav_date = datetime.date(annee_nav, mois_nav_num, 1)

    mois_precedent_date = (mois_nav_date - datetime.timedelta(days=1)).replace(day=1)
    dernier_jour_mois_nav = calendar.monthrange(annee_nav, mois_nav_num)[1]
    mois_suivant_date = datetime.date(annee_nav, mois_nav_num, dernier_jour_mois_nav) + datetime.timedelta(days=1)
    mois_suivant_autorise = mois_suivant_date <= datetime.date(aujourdhui.year, aujourdhui.month, 1)

    seances_mois_nav = seances_qs.filter(date__year=annee_nav, date__month=mois_nav_num)
    if borne_avant:
        seances_mois_nav = seances_mois_nav.filter(date__lt=aujourdhui)
    seances_mois_nav = seances_mois_nav.order_by('-date', '-heure')

    semaines_dict = {}
    for s in seances_mois_nav:
        debut_semaine = s.date - datetime.timedelta(days=s.date.isoweekday() - 1)
        semaines_dict.setdefault(debut_semaine, []).append(s)

    semaines = [
        {
            'debut': debut_semaine,
            'fin': debut_semaine + datetime.timedelta(days=6),
            'seances': semaines_dict[debut_semaine],
            'nb': len(semaines_dict[debut_semaine]),
        }
        for debut_semaine in sorted(semaines_dict.keys(), reverse=True)
    ]

    return {
        'semaines': semaines,
        'mois_nav_date': mois_nav_date,
        'mois_nav_param': f'{annee_nav}-{mois_nav_num:02d}',
        'mois_precedent_param': f'{mois_precedent_date.year}-{mois_precedent_date.month:02d}',
        'mois_suivant_param': f'{mois_suivant_date.year}-{mois_suivant_date.month:02d}',
        'mois_suivant_autorise': mois_suivant_autorise,
    }


def regrouper_seances_a_venir(seances_qs, aujourdhui):
    """Section "القادمة" — séances futures (Tâche du 2026-08-05, Point 1,
    RETRAVAILLÉE le 2026-08-06 suite à un signalement réel : l'ancienne
    version groupait par SEMAINE indéfiniment — avec plusieurs mois de
    séances programmées à l'avance, ça produisait une pile de 8+ accordéons
    hebdomadaires, chacun individuellement repliable mais son EN-TÊTE
    toujours visible : à l'écran, ça reste une liste à peu près aussi
    "plate" que si rien n'était replié. Désormais : "بقية هذا الأسبوع" à
    plat (inchangé), "الأسبوع القادم" seule semaine encore détaillée
    (repliable mais OUVERTE par défaut), puis tout le reste regroupé en UN
    SEUL résumé replié PAR MOIS calendaire (ex: "سبتمبر 2026 — 12 حصة").
    Réutilisée telle quelle par dashboard_superviseur ET dashboard_prof.

    seances_qs : déjà scopé par l'appelant (par prof, par مؤطر, filtres GET
    éventuels...), PAS encore borné aux séances futures — cette fonction
    s'en charge (date__gt=aujourdhui, "aujourd'hui" est déjà couvert par la
    section "اليوم"/"الحصة القادمة" ailleurs sur la page).

    Ne PAS pré-exclure ici la séance déjà affichée séparément par le widget
    "الحصة القادمة/التالية" — nb_semaine_courante doit rester le compte VRAI
    de "cette semaine" (elle en fait partie). C'est à l'appelant de retirer
    cette séance de bucket_semaine_courante avant de l'afficher, sans
    fausser le compteur.

    Retourne : bucket_semaine_courante (liste, à afficher DÉPLIÉE),
    semaine_suivante ({debut, fin, seances, nb} ou None — à afficher
    DÉPLIÉE par défaut, mais repliable), mois_suivants (liste de
    {mois_ref, seances, nb} — un par mois calendaire au-delà de la semaine
    suivante, triés chronologiquement, toutes REPLIÉES), nb_semaine_courante
    (compteur "X qui vient cette semaine", "vrai" total, cohérent avec le
    libellé)."""
    fin_semaine_courante = aujourdhui + datetime.timedelta(days=7 - aujourdhui.isoweekday())
    fin_semaine_suivante = fin_semaine_courante + datetime.timedelta(days=7)
    seances_a_venir = list(seances_qs.filter(date__gt=aujourdhui).order_by('date', 'heure'))

    bucket_semaine_courante = [s for s in seances_a_venir if s.date <= fin_semaine_courante]
    apres_semaine_courante = [s for s in seances_a_venir if s.date > fin_semaine_courante]
    seances_semaine_suivante = [s for s in apres_semaine_courante if s.date <= fin_semaine_suivante]
    au_dela = [s for s in apres_semaine_courante if s.date > fin_semaine_suivante]

    semaine_suivante = None
    if seances_semaine_suivante:
        semaine_suivante = {
            'debut': fin_semaine_courante + datetime.timedelta(days=1),
            'fin': fin_semaine_suivante,
            'seances': seances_semaine_suivante,
            'nb': len(seances_semaine_suivante),
        }

    mois_dict = {}
    for s in au_dela:
        cle = (s.date.year, s.date.month)
        mois_dict.setdefault(cle, []).append(s)

    mois_suivants = [
        {
            'mois_ref': datetime.date(annee, mois, 1),
            'seances': mois_dict[(annee, mois)],
            'nb': len(mois_dict[(annee, mois)]),
        }
        for (annee, mois) in sorted(mois_dict.keys())
    ]

    return {
        'bucket_semaine_courante': bucket_semaine_courante,
        'semaine_suivante': semaine_suivante,
        'mois_suivants': mois_suivants,
        'nb_semaine_courante': len(bucket_semaine_courante),
    }


def calculer_suivi_mensuel_engagement(mois):
    """Page "متابعة الالتزام الشهري" (Tâche du 2026-08-07, complétée le
    2026-08-07 2e ronde) — suite directe du diagnostic sur "نسبة الحضور هذا
    الشهر" : ce chiffre mesurait "% de présent PARMI les feuilles remplies"
    (dénominateur = lignes Presence, donc élève × séance, avec le biais
    découvert : une seule séance individuelle traitée suffit à afficher
    100%). Remplacé par 4 indicateurs, 2 niveaux différents et volontairement
    distincts (le client a insisté pour que les deux coexistent) :

    - نسبة تغطية الحضور / حصص لم يسجلها الأستاذ / حصص لم يقيّمها المؤطر :
      niveau SÉANCE (pas élève × séance, décision explicite du client pour
      rester lisible) — mesurent la discipline administrative (est-ce
      qu'une feuille a été remplie/évaluée), pas le contenu.
    - نسبة الحضور الفعلي (من الحصص المسجلة) : niveau ÉLÈVE × SÉANCE
      (volontairement différent des 3 premiers, c'est l'ancien calcul de
      "نسبة الحضور هذا الشهر" mais explicitement RESTREINT aux séances déjà
      enregistrées ce mois — le biais initial venait de l'appliquer à TOUT
      le mois avec un dénominateur minuscule, pas du niveau de calcul en
      lui-même, qui reste la bonne question une fois qu'on sait sur quoi il
      porte réellement).

    mois : date au 1er jour du mois (même convention que
    calculer_remuneration_prof/mshrif_remuneration).

    "Séance passée" = date < aujourd'hui (aligné sur le filtre déjà utilisé
    par superviseur_profil.nb_evaluations_en_attente), séances annulées
    TOUJOURS exclues de tous les indicateurs (une séance annulée n'a pas à
    être "traitée" par personne, et ses éventuelles lignes Presence ne
    reflètent pas une vraie présence).

    "حصص لم يقيّمها المؤطر" est volontairement plus strict que
    nb_evaluations_en_attente (qui compte TOUTE séance passée non évaluée,
    même jamais traitée par le prof) : ici on ne compte que les séances
    DÉJÀ traitées (Presence existe) mais pas encore évaluées — sinon
    l'indicateur mélangerait deux causes différentes (prof absent vs مؤطر
    en retard).

    Zone 2/3 (par prof / par مؤطر) : TOUS les profs / TOUS les مؤطرين du
    système apparaissent désormais (Bug signalé le 2026-08-07 : la version
    précédente sautait toute entité à total=0, ce qui vidait quasi
    entièrement la Zone 3 dès qu'un seul mois avait peu de séances traitées
    — un مؤطر dont aucun prof supervisé n'a de séance traitée ce mois-ci
    n'est pas "sans donnée à afficher", c'est une donnée en soi). 'taux' est
    None quand nb_total=0 (aucun pourcentage n'a de sens sur 0/0) — à
    l'appelant (template) de l'afficher comme "0 من 0", jamais comme un
    faux 0% ou 100%. Le tri (croissant, pire en premier) place les None à
    la fin : "pas de donnée" n'est pas la même chose que "mauvaise
    performance mesurée".

    Une boucle Python par entité (pas une seule requête agrégée) car chaque
    ligne a besoin de la liste précise des séances manquantes pour son
    accordéon déplié — accepté tel quel vu le nombre réduit de profs/
    مؤطرين réels de cette école (même ordre de grandeur que
    mshrif_remuneration, jamais identifié comme un point chaud lors de
    l'audit de performance du 2026-08-06). À revisiter si le nombre de
    profs grossit significativement.

    ligne_sans_prof / ligne_sans_superviseur (Tâche du 2026-08-07, 3e ronde) :
    2 cas structurels distincts découverts en creusant un écart signalé par
    le client entre le compteur du haut et la somme des listes détaillées —
    (1) une séance dont le GROUPE n'a aucun prof (groupe.prof=NULL, comptait
    dans nb_non_traitees sans apparaître dans aucune ligne de Zone 2, la
    boucle étant indexée par prof), (2) une séance déjà traitée dont le prof
    n'a AUCUN مؤطر assigné (compte dans nb_non_evaluees mais ne peut
    structurellement apparaître dans aucune ligne de Zone 3, qui est scopée
    par profs_assignes). Les 2 restent None/vide si aucun cas de ce type —
    pas affichés en permanence comme les profs/مؤطرين réels, ce ne sont pas
    des entités à suivre mais des anomalies à signaler seulement si elles
    existent."""
    from django.db.models import Exists, OuterRef
    from django.utils import timezone
    from accounts.models import Prof, Superviseur
    from courses.models import Seance, Presence
    from evaluations.models import Evaluation

    aujourdhui = timezone.localdate()
    annee, mois_num = mois.year, mois.month

    seances_passees = Seance.objects.filter(
        date__year=annee, date__month=mois_num, date__lt=aujourdhui,
    ).exclude(statut='annulee').annotate(
        a_presence=Exists(Presence.objects.filter(seance=OuterRef('pk')))
    )

    nb_total_passees = seances_passees.count()
    nb_traitees = seances_passees.filter(a_presence=True).count()
    nb_non_traitees = nb_total_passees - nb_traitees
    taux_couverture = round((nb_traitees / nb_total_passees) * 100) if nb_total_passees else None

    # Détail complet des non-évaluées (pas juste le compte) : nécessaire pour
    # distinguer, dans la liste elle-même, celles dont le prof n'a AUCUN
    # مؤطر assigné (Tâche du 2026-08-07, 3e ronde — signalé par le client :
    # ces séances comptaient dans le total global sans qu'on sache qu'aucun
    # مؤطر ne peut structurellement les évaluer, laissant croire à un retard
    # normal alors que personne n'en a la responsabilité).
    seances_non_evaluees_toutes = list(
        seances_passees.filter(a_presence=True, evaluation__isnull=True)
        .select_related('groupe', 'groupe__prof__user')
    )
    nb_non_evaluees = len(seances_non_evaluees_toutes)
    seances_non_evaluees_sans_superviseur = [
        s for s in seances_non_evaluees_toutes
        if s.groupe is None or s.groupe.prof is None or not s.groupe.prof.superviseurs.exists()
    ]
    nb_non_evaluees_sans_superviseur = len(seances_non_evaluees_sans_superviseur)

    # --- نسبة الحضور الفعلي (من الحصص المسجلة) : niveau élève × séance,
    # restreint aux mêmes séances passées/non-annulées que le reste de la
    # page (pas tout le mois — c'est précisément ça qui biaisait l'ancien
    # calcul). nb_traitees (déjà calculé ci-dessus) EST le "X" du texte
    # "من أصل X حصة مسجلة" : c'est exactement le nombre de séances qui ont
    # au moins une ligne Presence.
    presences_sur_seances_traitees = Presence.objects.filter(seance__in=seances_passees)
    nb_lignes_presence = presences_sur_seances_traitees.count()
    nb_present_reel = presences_sur_seances_traitees.filter(statut='present').count()
    taux_presence_reel = round((nb_present_reel / nb_lignes_presence) * 100) if nb_lignes_presence else None

    # --- Zone 2 : تسجيل الحضور — الأساتذة ---
    lignes_profs = []
    for prof in Prof.objects.select_related('user').all():
        qs_prof = seances_passees.filter(groupe__prof=prof)
        total = qs_prof.count()
        traitees = qs_prof.filter(a_presence=True).count()
        lignes_profs.append({
            'prof': prof,
            'taux': round((traitees / total) * 100) if total else None,
            'nb_traitees': traitees,
            'nb_total': total,
            'seances_non_traitees': list(
                qs_prof.filter(a_presence=False).select_related('groupe').order_by('date')
            ) if total else [],
        })
    lignes_profs.sort(key=lambda l: (l['taux'] is None, l['taux'] if l['taux'] is not None else 0))

    # Séances passées dont le GROUPE n'a aucun prof assigné (groupe.prof=NULL,
    # SET_NULL — arrive si le prof est supprimé, ou données mal formées comme
    # le "DbgGroupe" trouvé et nettoyé le 2026-08-07). Avant ce correctif,
    # ces séances comptaient dans nb_non_traitees SANS apparaître dans aucune
    # ligne de Zone 2 (la boucle est indexée par prof) — invisibles alors
    # qu'elles pesaient dans le total affiché en haut. Ligne à part, affichée
    # SEULEMENT si non vide (contrairement aux profs réels, "0 groupe sans
    # prof" n'est pas une donnée utile à afficher en permanence).
    qs_sans_prof = seances_passees.filter(groupe__prof__isnull=True)
    total_sans_prof = qs_sans_prof.count()
    ligne_sans_prof = None
    if total_sans_prof:
        traitees_sans_prof = qs_sans_prof.filter(a_presence=True).count()
        ligne_sans_prof = {
            'label': 'بدون أستاذ معيّن',
            'taux': round((traitees_sans_prof / total_sans_prof) * 100),
            'nb_traitees': traitees_sans_prof,
            'nb_total': total_sans_prof,
            'seances_non_traitees': list(
                qs_sans_prof.filter(a_presence=False).select_related('groupe').order_by('date')
            ),
        }

    # --- Zone 3 : تقييم الحصص — المؤطرون ---
    lignes_superviseurs = []
    for superviseur in Superviseur.objects.select_related('user').all():
        # Périmètre = séances DÉJÀ traitées des profs qu'il supervise, comme défini
        # par le client (pas les séances jamais traitées, qui ne dépendent pas de lui).
        qs_sup = seances_passees.filter(
            groupe__prof__in=superviseur.profs_assignes.all(), a_presence=True,
        )
        total = qs_sup.count()
        evaluees = qs_sup.filter(evaluation__isnull=False).count()
        lignes_superviseurs.append({
            'superviseur': superviseur,
            'taux': round((evaluees / total) * 100) if total else None,
            'nb_evaluees': evaluees,
            'nb_total': total,
            'seances_non_evaluees': list(
                qs_sup.filter(evaluation__isnull=True).select_related('groupe', 'groupe__prof__user').order_by('date')
            ) if total else [],
        })
    lignes_superviseurs.sort(key=lambda l: (l['taux'] is None, l['taux'] if l['taux'] is not None else 0))

    # Séances déjà traitées mais dont le prof n'a AUCUN مؤطر assigné —
    # comptent dans nb_non_evaluees (le total global reste inchangé, comme
    # demandé) mais ne peuvent structurellement apparaître dans AUCUNE ligne
    # ci-dessus (qs_sup est scopé par profs_assignes). Ligne à part pour que
    # le مدير voie qu'il faut assigner un مؤطر, plutôt que de laisser croire
    # à un retard d'évaluation normal. Affichée seulement si non vide.
    ligne_sans_superviseur = None
    if nb_non_evaluees_sans_superviseur:
        ligne_sans_superviseur = {
            'label': 'بدون مؤطر مسؤول',
            'seances_non_evaluees': sorted(seances_non_evaluees_sans_superviseur, key=lambda s: s.date),
        }

    return {
        'mois': mois,
        'nb_total_passees': nb_total_passees,
        'nb_traitees': nb_traitees,
        'nb_non_traitees': nb_non_traitees,
        'taux_couverture': taux_couverture,
        'nb_non_evaluees': nb_non_evaluees,
        'nb_non_evaluees_sans_superviseur': nb_non_evaluees_sans_superviseur,
        'taux_presence_reel': taux_presence_reel,
        'nb_present_reel': nb_present_reel,
        'nb_lignes_presence': nb_lignes_presence,
        'lignes_profs': lignes_profs,
        'ligne_sans_prof': ligne_sans_prof,
        'lignes_superviseurs': lignes_superviseurs,
        'ligne_sans_superviseur': ligne_sans_superviseur,
    }


def creneau_peut_etre_supprime(creneau):
    """Tâche du 2026-08-08 — un حذف réel n'est proposé que si ce créneau
    n'est référencé nulle part : ni par un groupe (Groupe.creneau,
    SET_NULL — donc pas d'erreur de contrainte possible, mais on bloque
    quand même par précaution : orpheliner silencieusement le créneau
    d'un groupe existant serait une perte de donnée invisible), ni par
    une candidature en cours (InscriptionEleve.creneau_souhaite,
    related_name='inscriptions', SET_NULL aussi — même raisonnement).
    Sinon, "تعطيل" (est_actif=False, déjà existant) reste la seule
    option — cohérent avec le principe déjà établi partout ailleurs
    dans ce projet (archivage réversible plutôt que suppression dès
    qu'une donnée réelle est en jeu)."""
    return creneau.groupes.count() == 0 and creneau.inscriptions.count() == 0


def groupe_peut_etre_supprime(groupe):
    """Tâche du 2026-08-08 — un حذف réel n'est proposé que si ce groupe
    n'a STRICTEMENT aucune trace d'activité :
    - aucune séance (Seance.groupe est CASCADE — supprimer un groupe
      avec des séances détruirait en cascade les Presence ET les
      Evaluation liées, donc l'historique réel de cours ; c'est
      exactement le cas qu'il faut bloquer) ;
    - aucun élève actuellement inscrit (Groupe.eleves, M2M) — ajouté
      au-delà de ce qui était explicitement demandé : un groupe à 0
      séance peut quand même avoir des élèves déjà affectés (créé puis
      jamais utilisé, mais pas vide), les désinscrire silencieusement
      via un حذف serait une surprise ;
    - aucune trace dans HistoriqueGroupeEleve (même un élève retiré
      depuis reste une trace réelle d'activité, pas seulement
      l'appartenance actuelle).

    Note honnête : Paiement n'est PAS vérifiable ici — dans ce schéma,
    Paiement est lié à Eleve, jamais directement à Groupe (aucune FK
    Paiement→Groupe n'existe), donc "aucun paiement lié à ce groupe" ne
    peut pas être vérifié littéralement. Les 3 critères ci-dessus
    couvrent tout ce qui est réellement rattaché à un Groupe dans ce
    schéma."""
    return (
        groupe.seances.count() == 0
        and groupe.eleves.count() == 0
        and groupe.historique_eleves.count() == 0
    )
