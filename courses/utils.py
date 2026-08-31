import datetime

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

JOUR_INDEX = {'lun': 0, 'mar': 1, 'mer': 2, 'jeu': 3, 'ven': 4, 'sam': 5, 'dim': 6}
JOUR_INDEX_INVERSE = {valeur: code for code, valeur in JOUR_INDEX.items()}

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
    ('lun', _('الاثنين')), ('mar', _('الثلاثاء')), ('mer', _('الأربعاء')),
    ('jeu', _('الخميس')), ('ven', _('الجمعة')), ('sam', _('السبت')), ('dim', _('الأحد')),
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
    """Cœur commun de creneaux_manquants_pour_*: heures de TOUS les CreneauSlot du
    créneau (1 à N, chantier de généralisation N séances/semaine — auparavant limité
    aux 2 blocs jour_1/jour_2 figés) non couvertes par l'ensemble dispo de tuples
    (jour, heure_debut)."""
    manquants = []
    for slot in creneau.slots.all():
        for h in _heures_couvertes(slot.heure_debut, slot.heure_fin):
            if (slot.jour, h) not in dispo:
                manquants.append((slot.jour, h))
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
    critères BLOQUANTS uniquement (place restante, horaire du groupe, âge,
    type d'abonnement). Retourne une chaîne expliquant le premier critère non
    respecté, ou None si le groupe est compatible. Utilisée à la fois pour la
    suggestion automatique (affichage) et comme garde-fou serveur avant toute
    assignation (sécurité), afin qu'aucune des deux voies ne puisse être
    contournée par l'autre. Voir raison_incompatibilite_groupe_inscription,
    l'équivalent pour une candidature pas encore acceptée — les deux
    fonctions doivent rester alignées critère par critère.

    Programme/riwaya/sexe ne sont PLUS bloquants depuis la Tâche 14 (demande
    client explicite) : voir avertissements_groupe pour ces 3 critères,
    désormais informatifs seulement.

    Disponibilité horaire de l'élève : n'est PLUS bloquante depuis le
    chantier du 2026-08-16 (demande client explicite), alignée sur le même
    changement déjà appliqué au prof (Tâche du 2026-08-09, voir
    avertissements_prof_creneau) — voir avertissements_groupe pour ce
    critère, désormais informatif seulement.

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

    return None


def avertissements_groupe(eleve, groupe):
    """Critères informatifs (non bloquants) pour un couple (eleve, groupe) :
    programme, riwaya, sexe (non bloquants depuis la Tâche 14) et
    disponibilité horaire (non bloquante depuis le chantier du 2026-08-16 —
    voir le commentaire équivalent dans raison_incompatibilite_groupe).
    Retourne la liste des messages d'avertissement à afficher — liste vide si
    tout correspond. À appeler uniquement après avoir vérifié
    raison_incompatibilite_groupe (aucune garantie ici si creneau/inscription
    sont absents).

    Le message de disponibilité reste SILENCIEUX si l'élève n'a rien déclaré
    (matrice de disponibilités vide) — même logique que
    avertissements_prof_creneau côté prof : l'absence de déclaration n'est
    pas une preuve d'incompatibilité, seule une contradiction explicite avec
    une disponibilité réellement déclarée déclenche l'avertissement."""
    from .models import Creneau

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

    manquants = creneaux_manquants_pour_eleve(eleve, creneau)
    if manquants and eleve.disponibilites.exists():
        jours_dict = dict(Creneau.JOUR_CHOICES)
        details = '، '.join(f'{jours_dict.get(j, j)} {h.strftime("%H:%M")}' for j, h in manquants)
        avertissements.append(
            f'تنبيه: التوقيت المختار لا يتوافق بالكامل مع جدول تفرغ هذا الطالب المصرَّح به عند تسجيله — '
            f'غير متفرغ حسب تصريحه في: {details}.'
        )
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
    TOUS les critères (y compris programme/riwaya/sexe/disponibilité horaire,
    même si Tâche 14 puis le chantier du 2026-08-16 les ont rendus non
    bloquants pour l'ajout manuel) : cette liste sert de suggestion "idéale"
    en un clic, distincte de l'ajout manuel qui accepte désormais ces
    critères avec un simple avertissement."""
    from .models import Groupe

    candidats = Groupe.objects.filter(statut='actif').exclude(eleves=eleve).select_related('creneau', 'prof__user')
    return [
        g for g in candidats
        if raison_incompatibilite_groupe(eleve, g) is None and not avertissements_groupe(eleve, g)
    ]


def groupes_compatibles_sexe_age_pour_changement(eleve):
    """Liste des groupes actifs dont le créneau correspond au sexe et à
    l'âge de l'élève UNIQUEMENT — Fonctionnalité 4 (2026-08-27, demande de
    changement de halaka par l'élève). Décision explicite du client pour ce
    chantier précis : PAS le même filtre strict que groupes_compatibles_
    pour_eleve ci-dessus (qui exige AUSSI programme/riwaya/disponibilité
    horaire/capacité/type d'offre) — "les autres critères (programme,
    riwaya) restent visibles sans filtre supplémentaire pour l'instant".

    Réutilise les 2 mêmes critères, calculés EXACTEMENT comme dans
    raison_incompatibilite_groupe ci-dessus (creneau.age_min/age_max,
    creneau.sexe_cible) — seule différence : capacité/type d'offre/
    programme/riwaya/disponibilité ne sont PAS vérifiés ici (delta
    assumé, voir dashboard.views.eleve_demande_changement_halaka qui
    revalide malgré tout raison_incompatibilite_groupe juste avant le
    transfert effectif, au moment de la validation مدير/مشرف — jamais une
    confiance aveugle dans cette liste affichée à l'élève).

    Exclut le(s) groupe(s) où l'élève est DÉJÀ (inutile de "changer" vers sa
    propre halaka actuelle) — même .exclude(eleves=eleve) que groupes_
    compatibles_pour_eleve. Retourne une liste vide (jamais une exception)
    si l'élève n'a aucune inscription liée pour en déduire l'âge (voir
    Eleve.inscription, nullable — SET_NULL)."""
    from .models import Groupe

    inscription = eleve.inscription
    if not inscription:
        return []
    age = _age_depuis_naissance(inscription.date_naissance)

    candidats = (
        Groupe.objects.filter(statut='actif')
        .exclude(eleves=eleve)
        .exclude(creneau__isnull=True)
        .select_related('creneau', 'prof__user')
        .prefetch_related('creneau__slots')
    )
    return [
        g for g in candidats
        if g.creneau.age_min <= age <= g.creneau.age_max
        and (g.creneau.sexe_cible == 'mixte' or g.creneau.sexe_cible == eleve.sexe)
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


def remplacer_slots_creneau(creneau, slots_donnees):
    """Remplace l'ENSEMBLE des CreneauSlot d'un créneau par `slots_donnees` (liste
    ordonnée de dicts {'jour', 'heure_debut', 'heure_fin'}) — même idiome que
    matrice_vers_lignes/matrice_vers_lignes_eleve juste au-dessus : on remplace
    toujours l'ensemble existant, jamais on n'accumule. Utilisé par
    courses.views.creneau_ajouter/creneau_modifier (formulaire à nombre de slots
    dynamique, 1 à N — plus de couple figé jour_1/jour_2). L'ordre de la liste
    fournie devient l'ordre (CreneauSlot.ordre, 1-indexé) des slots créés."""
    from .models import CreneauSlot

    CreneauSlot.objects.filter(creneau=creneau).delete()
    lignes = [
        CreneauSlot(
            creneau=creneau, ordre=i + 1,
            jour=s['jour'], heure_debut=s['heure_debut'], heure_fin=s['heure_fin'],
        )
        for i, s in enumerate(slots_donnees)
    ]
    CreneauSlot.objects.bulk_create(lignes)


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

    # Chantier de généralisation N séances/semaine : auparavant 2 tuples figés
    # (jour_1/jour_2), désormais 1 à N depuis les CreneauSlot réels du créneau — le
    # nombre de séances hebdomadaires d'un groupe est TOUJOURS déterminé par le
    # nombre réel de CreneauSlot, jamais stocké ni supposé ailleurs.
    creneaux_jour = [(slot.jour, slot.heure_debut) for slot in creneau.slots.all()]

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


def etendre_toutes_les_seances():
    """Pousse l'horizon de génération de tous les groupes actifs ayant un
    créneau, sans jamais retoucher aux semaines déjà couvertes — voir
    etendre_toutes_les_seances_opportuniste ci-dessous pour la version
    THROTTLÉE réellement appelée depuis les vues (celle-ci reste appelable
    directement, ex. depuis un test ou une future commande de management).

    Exclut les groupes dont le prof est archivé (chantier du 2026-08-03): pas de
    plantage, mais plus aucune nouvelle séance générée pour un groupe sans prof
    actif — les séances déjà générées restent intactes, à annuler/reporter ou à
    faire reprendre par un nouveau prof manuellement (voir admin_prof_detail,
    bannière d'avertissement affichée quand un prof archivé a encore des groupes).

    select_related('creneau').prefetch_related('creneau__slots') (Correctif
    perf du 2026-08-30) : sans ça, etendre_seances(groupe) déclenchait 1
    requête pour lire groupe.creneau PUIS 1 requête pour creneau.slots.all(),
    PAR GROUPE actif — sur une école à 20-30 groupes, ~40-60 requêtes rien
    que pour cette lecture, en plus de la requête "dernière séance" restée
    par groupe (celle-ci dépend du groupe, pas batchable aussi simplement
    sans changer la logique d'incrémentation — voir la note de throttling
    ci-dessous, qui règle le vrai problème : la fréquence d'appel)."""
    from .models import Groupe

    groupes = Groupe.objects.filter(
        statut='actif', creneau__isnull=False
    ).exclude(prof__statut='archive').select_related('creneau').prefetch_related('creneau__slots')
    for groupe in groupes:
        etendre_seances(groupe)


def etendre_toutes_les_seances_opportuniste():
    """Version throttlée (Correctif perf du 2026-08-30, voir
    AUDIT_PERFORMANCE_2026-08-30.md) d'etendre_toutes_les_seances — à appeler
    depuis les vues à la place de la fonction ci-dessus, MÊME PATRON que
    chat.services.purge_opportuniste (déjà en place pour la purge du chat).

    Avant ce correctif, dashboard.views.admin_seances/admin_calendrier
    appelaient etendre_toutes_les_seances() SANS AUCUN throttle, À CHAQUE
    ouverture de page — y compris à chaque filtre/recherche appliqué dessus
    (un filtre recharge entièrement la page, donc rejoue tout du début) :
    signalé lent par le client précisément dans ce cas ("quand on applique
    des filtres... ça devient très lent"), alors que le filtre lui-même
    n'a rien à voir — c'est ce balayage de TOUS les groupes actifs, rejoué à
    chaque requête, qui payait le prix à chaque fois. L'horizon de génération
    (HORIZON_SEMAINES = 8 semaines) n'a besoin d'être poussé qu'occasionnellement
    (1h ici, largement suffisant) — pas à chaque clic sur un filtre."""
    from django.core.cache import cache

    cle_cache = 'seances_extension_derniere_execution'
    if cache.get(cle_cache):
        return
    cache.set(cle_cache, True, 60 * 60)
    etendre_toutes_les_seances()


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
            {'nom': n.critere.nom_localise, 'note': n.note, 'ordre': n.critere.ordre}
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
            # Critère ينتقل/يعيد (Tâche du 2026-08-18) — affiché sur CHAQUE
            # séance du journal, y compris celles exclues du cumul ci-dessous
            # (voir le commentaire juste après cette boucle).
            'resultat_memorisation': p.resultat_memorisation,
            'resultat_memorisation_display': p.get_resultat_memorisation_display(),
            'resultat_revision': p.resultat_revision,
            'resultat_revision_display': p.get_resultat_revision_display(),
        })

        # historique ci-dessus garde TOUTE séance, même يعيد (transparence du
        # journal séance par séance) — seul le CUMUL de progression ci-dessous
        # exclut resultat_memorisation='a_refaire' (Tâche du 2026-08-18),
        # même règle que _couverture_ayat_par_sourate (calculer_hizb_precis).
        if p.sourate_memorisee is None or p.resultat_memorisation != 'valide':
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


def compter_absences_par_eleve(eleve_ids, annee, mois, groupe=None):
    """Nombre d'absences du mois par élève — {eleve_id: nb} — via UNE seule
    requête groupée (pas une par élève, voir prof_bilans_mensuels/
    bilans_mensuels dans dashboard.views). Même définition d'absence que le
    bilan_mensuel_detail (Chantier du 2026-08-14) : statut != 'present'
    (absent_excuse ET absent comptent tous les deux). groupe=None (par
    défaut) compte TOUTES les Presence de l'élève ce mois-là, quel que soit
    le groupe — même choix que bilan_mensuel_detail ("reste correct même si
    l'élève a changé de groupe/prof en cours de mois"). groupe=<Groupe>
    restreint aux séances de ce groupe précis — utilisé par bilans_mensuels
    (accordéon مؤطر/مدير/مشرف) qui affiche déjà ses autres statistiques
    (moyennes) par (élève, groupe), pour qu'un élève présent dans plusieurs
    groupes supervisés n'affiche pas deux fois le même total sous deux
    groupes différents."""
    from django.db.models import Count
    from .models import Presence

    qs = Presence.objects.filter(
        eleve_id__in=eleve_ids,
        seance__date__year=annee,
        seance__date__month=mois,
    ).exclude(statut='present')
    if groupe is not None:
        qs = qs.filter(seance__groupe=groupe)
    compte = qs.values('eleve_id').annotate(nb=Count('id'))
    return {row['eleve_id']: row['nb'] for row in compte}


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
    # resultat_memorisation='valide' (Tâche du 2026-08-18) : un passage marqué
    # يعيد par le prof (RESULTAT_CHOICES) ne compte PAS dans la couverture —
    # exclu ici, seule source d'où dérive calculer_hizb_precis. La valeur par
    # défaut du champ ('valide') garantit que tout Presence antérieur à ce
    # critère continue de compter exactement comme avant son ajout.
    valeurs = Presence.objects.filter(
        eleve=eleve, sourate_memorisee__isnull=False, resultat_memorisation='valide'
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


# ==================== TRANCHES D'ÂGE PRÉCISES (Partie B, 2026-08-24) ====================
# Sous-catégorisation à 3 niveaux DEMANDÉE PAR LE CLIENT, réservée à
# l'AFFICHAGE (badge groupe, Chat, parcours d'inscription) — PURE fonction
# du calendrier, JAMAIS stockée sur aucun modèle (même principe que
# Groupe.categorie_collectif ci-dessus : recalculée à chaque lecture, un
# élève change de tranche automatiquement le jour de son anniversaire, sans
# aucune action ni migration de données).
#
# NE REMPLACE PAS le système enfant/adulte existant (AGE_SEUIL_ADULTE=18,
# tranche_age_depuis_naissance ci-dessus) : les 3 tranches couvrent
# exactement 5-18 ans, c'est-à-dire l'INTÉRIEUR de la catégorie "enfant"
# existante (qui reste, elle, la SEULE source de vérité pour l'ouverture des
# inscriptions par catégorie, le filtrage réel des groupes par Creneau.
# age_min/age_max, et le choix "بالغ/طفل" de wizard_categorie_age — AUCUN de
# ces mécanismes n'est modifié ici). Un élève de moins de 5 ans ou de 18 ans
# et plus (adulte) n'appartient à AUCUNE des 3 tranches (retourne None) —
# jamais une tranche approximative/erronée pour ces cas hors périmètre.
TRANCHES_AGE_PRECISES = [
    ('talqin', _('التلقين'), 5, 7),
    ('baraim', _('البراعم'), 8, 13),
    ('yafiun', _('اليافعون'), 14, 18),
]


def tranche_age_precise(date_naissance):
    """(code, label) de la tranche d'âge précise correspondant à
    `date_naissance` aujourd'hui, ou None si l'âge réel ne tombe dans
    AUCUNE des 3 tranches (hors 5-18 ans). None aussi si date_naissance est
    None (élève sans date de naissance renseignée — ne devrait pas arriver
    en pratique, date_naissance étant verrouillée obligatoire, mais jamais
    une exception ici)."""
    if date_naissance is None:
        return None
    age = _age_depuis_naissance(date_naissance)
    for code, label, age_min, age_max in TRANCHES_AGE_PRECISES:
        if age_min <= age <= age_max:
            return code, label
    return None


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


def cible_annonce_pour_eleve(eleve):
    """Catégorie de ciblage des annonces (annonces.models.Annonce.CIBLE_CHOICES)
    pour cet Eleve : 'mineurs' (< AGE_SEUIL_ADULTE, filles ET garçons ensemble
    — aucune séparation par sexe pour les mineurs, décision explicite du
    client, Chantier du 2026-08-15), sinon 'femmes_adultes'/'hommes_adultes'
    selon Eleve.sexe. None si l'âge est inconnu (même garde-fou que
    _tranche_age_eleve — pas d'inscription liée ou date de naissance
    manquante) ou si le sexe d'un élève adulte n'est ni 'homme' ni 'femme'
    (jamais une supposition silencieuse sur qui reçoit une annonce)."""
    tranche = _tranche_age_eleve(eleve)
    if tranche is None:
        return None
    if tranche == 'enfant':
        return 'mineurs'
    if eleve.sexe == 'femme':
        return 'femmes_adultes'
    if eleve.sexe == 'homme':
        return 'hommes_adultes'
    return None


def lien_seance_est_actif(seance):
    """True si l'heure actuelle tombe dans la fenêtre [début - marge_avant,
    fin + marge_apres] de cette séance — Point 15, Tâche du 2026-08-04.
    Recalculé à CHAQUE appel à partir des valeurs actuelles en base (jamais
    mis en cache) : un changement d'horaire de la séance ou du réglage de
    marge se reflète immédiatement au prochain appel, sans action
    supplémentaire. fin_datetime retombe sur debut_datetime si le groupe n'a
    pas/plus de créneau (voir Seance.fin_datetime), donc la fenêtre se
    réduit à [début - marge_avant, début + marge_apres] dans ce cas. False
    si aucun lien n'est actif pour cette séance (rien à activer — voir
    Seance.lien_effectif, qui utilise le lien exceptionnel de la séance s'il
    est posé, Tâche du 2026-08-17, sinon celui du groupe) ou si la séance
    est annulée."""
    import datetime
    from .models import ReglageLienSeance

    if not seance.lien_effectif or seance.statut == 'annulee':
        return False

    reglage, _ = ReglageLienSeance.objects.get_or_create(pk=1)
    debut = seance.debut_datetime
    fin = seance.fin_datetime or debut
    fenetre_debut = debut - datetime.timedelta(minutes=reglage.marge_avant_minutes)
    fenetre_fin = fin + datetime.timedelta(minutes=reglage.marge_apres_minutes)
    return fenetre_debut <= timezone.now() <= fenetre_fin


# ==================== POOL DE LIENS GOOGLE MEET (Tâche du 2026-08-17) ====================
# Un Creneau porte 2 créneaux hebdomadaires fixes (jour_1/heure_debut_1/heure_fin_1
# et jour_2/heure_debut_2/heure_fin_2) — un Groupe a UN SEUL Creneau, donc UN SEUL
# lien Meet suffit pour TOUTES ses séances (les Seance générées héritent du lien de
# leur groupe, jamais un lien par séance). La disponibilité d'un LienMeet n'est
# JAMAIS stockée : toujours recalculée à la volée à partir des groupes ACTIFS qui
# l'utilisent déjà (voir Groupe.actifs) — ce n'est pas un système de réservation.

def creneaux_se_chevauchent(creneau_a, creneau_b):
    """True si au moins UN des CreneauSlot de creneau_a chevauche au moins UN des
    CreneauSlot de creneau_b (comparaison de toutes les combinaisons possibles — un
    seul chevauchement suffit). Généralisé au chantier N séances/semaine : chaque
    créneau peut désormais avoir 1 à N slots, plus 2 fixes — la comparaison N×M
    remplace l'ancienne comparaison 2×2. Même jour de la semaine obligatoire. Deux
    intervalles [debut_a, fin_a) et [debut_b, fin_b) se chevauchent ssi
    debut_a < fin_b ET debut_b < fin_a — des bornes qui se touchent exactement
    (ex: 14:00-15:00 et 15:00-16:00) NE sont PAS un chevauchement (14:00-15:00 vs
    15:00-16:00 → 15:00 < 15:00 est faux)."""
    slots_a = [(s.jour, s.heure_debut, s.heure_fin) for s in creneau_a.slots.all()]
    slots_b = [(s.jour, s.heure_debut, s.heure_fin) for s in creneau_b.slots.all()]
    return any(
        _intervalle_hebdo_chevauche(jour_a, debut_a, fin_a, jour_b, debut_b, fin_b)
        for jour_a, debut_a, fin_a in slots_a
        for jour_b, debut_b, fin_b in slots_b
    )


def _intervalle_hebdo_chevauche(jour_a, debut_a, fin_a, jour_b, debut_b, fin_b):
    """Brique de base d'UN SEUL couple (jour, début, fin) contre un autre —
    même jour de la semaine obligatoire, bornes qui se touchent = pas de
    chevauchement. Extraite de creneaux_se_chevauchent (Tâche du 2026-08-17)
    pour être réutilisée telle quelle par les exceptions de séance
    (horaire RÉEL ponctuel d'une Seance déplacée, pas les 2 créneaux
    hebdomadaires complets d'un Groupe) — même formule, un seul endroit."""
    return jour_a == jour_b and debut_a < fin_b and debut_b < fin_a


def groupes_en_conflit_pour_lien(lien_meet, creneau, groupe_exclu=None):
    """Liste des groupes ACTIFS (Groupe.actifs — un groupe archivé ne bloque
    jamais un lien), avec un Creneau assigné, utilisant déjà `lien_meet`, dont
    l'horaire chevauche `creneau`. `groupe_exclu` (le groupe en cours de
    création/modification) est toujours écarté de la comparaison avec
    lui-même. Renvoie toujours une liste (jamais un QuerySet paresseux) — sert
    à la fois à décider (bool via lien_meet_est_disponible) et à composer un
    message d'erreur précis (quel groupe, quel horaire)."""
    from .models import Groupe

    if creneau is None or lien_meet is None:
        return []
    candidats = Groupe.actifs.filter(lien_meet=lien_meet, creneau__isnull=False).select_related('creneau')
    if groupe_exclu is not None:
        candidats = candidats.exclude(pk=groupe_exclu.pk)
    return [g for g in candidats if creneaux_se_chevauchent(g.creneau, creneau)]


def lien_meet_est_disponible(lien_meet, creneau, groupe_exclu=None):
    """True si `lien_meet` peut être assigné à `creneau` sans chevaucher
    l'horaire d'un groupe actif qui l'utilise déjà. Un groupe sans Creneau
    n'a par définition aucun conflit possible (rien à comparer)."""
    if creneau is None:
        return True
    return len(groupes_en_conflit_pour_lien(lien_meet, creneau, groupe_exclu)) == 0


def liens_meet_disponibles(creneau, groupe_exclu=None):
    """Liens Meet ACTIFS sans aucun conflit d'horaire pour `creneau` — ce que
    l'interface doit proposer en priorité au مدير. Ne présuppose rien sur
    `creneau` (peut être None : dans ce cas tous les liens actifs sont
    renvoyés, rien à comparer)."""
    from .models import LienMeet
    return [
        lien for lien in LienMeet.objects.filter(est_actif=True)
        if lien_meet_est_disponible(lien, creneau, groupe_exclu)
    ]


def _message_conflit_depuis_groupes(groupes_en_conflit):
    """Compose le message arabe à partir d'une liste DÉJÀ calculée de groupes
    en conflit (chaîne vide si la liste est vide) — extrait de
    description_conflit_lien_meet (Correctif du 2026-08-30, voir
    matrice_disponibilite_liens_meet.__doc__) pour être réutilisé aussi bien
    par le chemin unitaire (1 seul couple lien/créneau) que par le chemin en
    lot (toute une grille de couples), sans dupliquer la formulation du
    message dans 2 endroits qui pourraient diverger."""
    if not groupes_en_conflit:
        return ''
    noms = '، '.join(f'"{g.nom}"' for g in groupes_en_conflit)
    return f'يتعارض مع توقيت مجموعة {noms}.'


def description_conflit_lien_meet(lien_meet, creneau, groupe_exclu=None):
    """Message arabe court expliquant POURQUOI `lien_meet` est indisponible
    pour `creneau` (nom du/des groupe(s) en conflit) — chaîne vide si
    disponible. Utilisé côté formulaire (JSON pour le JS + erreur serveur)
    pour vérifier UN SEUL couple (ex: validation serveur à la sauvegarde d'un
    groupe) — pour toute une grille de couples à la fois, voir
    matrice_disponibilite_liens_meet ci-dessous, pas cette fonction appelée
    en boucle."""
    conflits = groupes_en_conflit_pour_lien(lien_meet, creneau, groupe_exclu)
    return _message_conflit_depuis_groupes(conflits)


def matrice_disponibilite_liens_meet(liens, creneaux, groupe_exclu=None):
    """Version "en lot" de groupes_en_conflit_pour_lien : calcule, pour CHAQUE
    couple (lien, créneau) parmi `liens` x `creneaux`, la liste des groupes
    actifs en conflit — EXACTEMENT le même résultat que d'appeler
    groupes_en_conflit_pour_lien(lien, creneau, groupe_exclu) couple par
    couple, mais avec un nombre de requêtes SQL FIXE (4, voir plus bas) au
    lieu d'une (en réalité 2 à 4, voir groupes_en_conflit_pour_lien/
    creneaux_se_chevauchent) PAR COUPLE.

    Correctif du 2026-08-30 : /courses/groupes/<id>/modifier/ (et
    /courses/groupes/ajouter/, toutes les deux via _liens_meet_contexte)
    évaluaient la disponibilité ET le message de conflit de CHAQUE lien Meet
    actif pour CHAQUE créneau actif indépendamment — mesuré en conditions
    réelles (21 créneaux actifs x 16 liens actifs) : ~800 requêtes SQL et
    ~88 secondes de temps de réponse, très au-dessus du `--timeout 30` de
    gunicorn (Procfile) → l'admin recevait "Internal Server Error" à chaque
    ouverture de la page de modification/création d'un groupe, pas de façon
    intermittente. liens_meet_list (page du pool de liens Meet) avait la
    même faiblesse structurelle pour une raison différente (une requête par
    groupe sans lien x par lien actif).

    Principe : au lieu d'une requête par couple, TOUT ce dont le calcul a
    besoin est chargé UNE SEULE FOIS puis le chevauchement horaire est
    calculé en mémoire (aucune requête supplémentaire, `creneaux_se_chevauchent`
    lit `.slots.all()` depuis le cache de prefetch Django) :
    - 1 requête (+1 pour le prefetch) : tous les groupes ACTIFS candidats
      (creneau assigné, lien_meet parmi `liens`), avec les CreneauSlot de LEUR
      créneau déjà préchargés ;
    - 1 requête (+1 pour le prefetch) : les CreneauSlot de TOUS les `creneaux`
      demandés, y compris s'ils viennent d'instances déjà en mémoire sans
      prefetch (ex: liens_meet_list, qui passe des `groupe.creneau` obtenus
      via select_related — jamais prefetched pour `.slots`) — re-requêtés
      par id ici plutôt que de faire confiance à l'appelant, pour rester
      correct quel que soit ce qu'il passe.

    Les fonctions unitaires (groupes_en_conflit_pour_lien/lien_meet_est_disponible/
    liens_meet_disponibles/description_conflit_lien_meet) restent INCHANGÉES et
    restent le bon choix pour vérifier UN SEUL couple (ex: revalidation serveur
    au moment de sauvegarder un groupe, courses.views.groupe_ajouter/
    groupe_modifier) — cette fonction est réservée aux écrans qui doivent
    évaluer TOUTES les combinaisons à la fois.

    `creneaux` accepte une queryset ou une liste d'instances Creneau (peuvent
    contenir des doublons, ex. plusieurs groupes partageant le même créneau —
    dédupliqués ici). `groupe_exclu` s'applique globalement à toute la grille
    (un seul groupe en cours d'édition, comme _liens_meet_contexte) — pour un
    groupe_exclu DIFFÉRENT par créneau (cas de liens_meet_list, chaque groupe
    de la liste s'exclut lui-même), appeler avec groupe_exclu=None puis
    retirer le groupe de la liste retournée pour chaque couple, en Python
    (voir courses.views.liens_meet_list).

    Retourne {(lien.id, creneau.id): [groupe, ...]} — liste vide = disponible."""
    from .models import Creneau, Groupe

    liens_ids = [lien.id for lien in liens]
    creneaux_par_id = {creneau.id: creneau for creneau in creneaux}
    if not liens_ids or not creneaux_par_id:
        return {}

    candidats = (
        Groupe.actifs.filter(lien_meet_id__in=liens_ids, creneau__isnull=False)
        .select_related('creneau')
        .prefetch_related('creneau__slots')
    )
    if groupe_exclu is not None:
        candidats = candidats.exclude(pk=groupe_exclu.pk)

    candidats_par_lien = {}
    for groupe in candidats:
        candidats_par_lien.setdefault(groupe.lien_meet_id, []).append(groupe)

    creneaux_avec_slots = {
        creneau.id: creneau
        for creneau in Creneau.objects.filter(id__in=creneaux_par_id.keys()).prefetch_related('slots')
    }

    resultat = {}
    for lien_id in liens_ids:
        groupes_candidats = candidats_par_lien.get(lien_id, [])
        for creneau_id, creneau_cible in creneaux_avec_slots.items():
            resultat[(lien_id, creneau_id)] = [
                g for g in groupes_candidats if creneaux_se_chevauchent(g.creneau, creneau_cible)
            ]
    return resultat


# ==================== EXCEPTIONS DE SÉANCE (Tâche du 2026-08-17) ====================
# Une Seance individuelle peut être déplacée à une date/heure hors de son créneau
# hebdomadaire habituel (admin_seance_deplacer, existant) — auquel cas le lien Meet
# PAR DÉFAUT du groupe (Groupe.lien_meet/lien_reunion) peut se retrouver en conflit
# avec un AUTRE groupe qui l'utilise à ce nouveau moment précis. Contrairement à
# groupes_en_conflit_pour_lien (qui compare 2 Creneau hebdomadaires complets), les
# fonctions ci-dessous comparent un horaire RÉEL ponctuel (jour de la semaine + heures
# d'UNE SEULE occurrence) aux créneaux hebdomadaires récurrents des autres groupes.
# Elles ne remplacent ni ne dupliquent la logique de conflit existante : elles
# réutilisent _intervalle_hebdo_chevauche, la même brique de comparaison.
#
# Portée volontairement limitée (proportionnée au besoin, pas de système de
# réservation) : seul le conflit contre l'horaire RÉCURRENT normal des autres
# groupes est vérifié ici. Deux exceptions différentes (2 séances de 2 groupes
# différents déplacées la même semaine sur le même lien) ne sont PAS comparées
# entre elles — cas non demandé, laissé de côté pour ne pas construire un système
# de réservation complexe.

def groupes_en_conflit_pour_lien_a_horaire_reel(lien_meet, jour_code, heure_debut, heure_fin):
    """Équivalent ponctuel de groupes_en_conflit_pour_lien : groupes ACTIFS
    utilisant déjà `lien_meet` par défaut, dont au moins un des CreneauSlot
    HEBDOMADAIRES (1 à N, chantier de généralisation N séances/semaine) chevauche
    l'horaire RÉEL (jour_code, heure_debut, heure_fin) fourni. Le groupe
    propriétaire de la séance exceptionnelle n'est PAS exclu de la recherche : si
    le nouvel horaire chevauche accidentellement un AUTRE slot hebdomadaire de ce
    même groupe, c'est un vrai conflit (double réservation du même lien par le
    même groupe), pas un faux positif — contrairement à groupe_exclu utilisé
    ailleurs pour "ce groupe peut-il GARDER ce lien pour son propre créneau",
    question différente."""
    from .models import Groupe

    if lien_meet is None:
        return []
    candidats = Groupe.actifs.filter(lien_meet=lien_meet, creneau__isnull=False)\
        .select_related('creneau').prefetch_related('creneau__slots')
    conflits = []
    for groupe in candidats:
        slots = [(s.jour, s.heure_debut, s.heure_fin) for s in groupe.creneau.slots.all()]
        if any(
            _intervalle_hebdo_chevauche(jour_code, heure_debut, heure_fin, jour, debut, fin)
            for jour, debut, fin in slots
        ):
            conflits.append(groupe)
    return conflits


def horaire_reel_seance(seance):
    """(jour_code, heure_debut, heure_fin) réels d'une Seance — jour de la
    semaine de sa DATE effective (pas du Creneau du groupe, qui peut être
    différent après un déplacement exceptionnel), heure de début propre à la
    séance, heure de fin dérivée de Seance.fin_datetime (même logique déjà
    utilisée par lien_seance_est_actif — retombe sur le début si le groupe
    n'a pas/plus de créneau du tout)."""
    jour_code = JOUR_INDEX_INVERSE[seance.date.weekday()]
    fin_dt = seance.fin_datetime or seance.debut_datetime
    return jour_code, seance.heure, fin_dt.time()


def liens_meet_disponibles_pour_seance(seance):
    """Liens Meet ACTIFS disponibles pour l'horaire RÉEL de `seance` — même
    principe que liens_meet_disponibles(creneau), mais comparé à un horaire
    ponctuel réel (Tâche du 2026-08-17, exceptions de séance)."""
    from .models import LienMeet

    jour_code, heure_debut, heure_fin = horaire_reel_seance(seance)
    return [
        lien for lien in LienMeet.objects.filter(est_actif=True)
        if not groupes_en_conflit_pour_lien_a_horaire_reel(lien, jour_code, heure_debut, heure_fin)
    ]


def lien_effectif_disponible_pour_seance(seance):
    """True si le lien EFFECTIF actuel de la séance (seance.lien_effectif —
    exceptionnel si posé, sinon celui du groupe) reste libre à l'horaire réel
    ACTUEL de la séance. Sert à décider, après un déplacement, si le lien par
    défaut du groupe peut être conservé automatiquement (section 3 du
    cahier des charges) ou si le مدير doit être alerté. Un lien "hors pool"
    (legacy, ex. WhatsApp — jamais enregistré comme LienMeet) est toujours
    considéré disponible : cette vérification ne concerne que les liens
    gérés par le pool centralisé."""
    from .models import LienMeet

    url = seance.lien_effectif
    if not url:
        return True
    lien = LienMeet.objects.filter(url=url, est_actif=True).first()
    if lien is None:
        return True
    jour_code, heure_debut, heure_fin = horaire_reel_seance(seance)
    return not groupes_en_conflit_pour_lien_a_horaire_reel(lien, jour_code, heure_debut, heure_fin)


def description_conflit_lien_meet_seance(lien_meet, seance):
    """Équivalent ponctuel de description_conflit_lien_meet — message arabe
    court nommant le/les groupe(s) en conflit avec `lien_meet` à l'horaire
    réel de `seance` ; chaîne vide si disponible."""
    jour_code, heure_debut, heure_fin = horaire_reel_seance(seance)
    conflits = groupes_en_conflit_pour_lien_a_horaire_reel(lien_meet, jour_code, heure_debut, heure_fin)
    if not conflits:
        return ''
    noms = '، '.join(f'"{g.nom}"' for g in conflits)
    return f'يتعارض مع توقيت مجموعة {noms}.'


def calculer_remuneration_prof(prof, mois=None, tarifs_groupe=None, tarifs_individuel=None):
    """Rémunération mensuelle d'un prof. Détail par groupe pour que le calcul
    soit vérifiable. Ne retourne QUE le calcul de base de la grille —
    majoration_mensuelle (Prof) n'est ni lue ni additionnée ici: elle ne doit
    jamais atteindre la page du prof, même fondue dans un total, voir
    templates/dashboard/prof_remuneration.html.

    Toujours "à la volée" sur l'état actuel, jamais historisé (voir
    mshrif_remuneration) — donc pas de "mois passé" distinct à préserver ici :
    chaque affichage de cette fonction, quelle que soit la date à laquelle on
    la consulte, ne montre QUE le mois en cours.

    Refonte du 2026-08-27 (Chantier "salaire prof par nb séances/semaine") —
    remplace TarifRemuneration (déprécié, voir son docstring) par 2 sources :
    - TarifRemunerationGroupe(tranche_age, nb_slots) pour type_capacite='groupe' :
      montant fixe par élève actif par mois, SELON LE NOMBRE DE SÉANCES/SEMAINE
      du groupe (groupe.creneau.slots.count(), même source de vérité que
      registration.utils partout ailleurs) — avant ce chantier, un même tarif
      s'appliquait à un groupe de 1 comme de 3 séances/semaine.
    - TarifRemunerationIndividuel(tranche_age) pour type_capacite='individuel' :
      35 د.م. (valeur seed) PAR SÉANCE réellement tenue — le COMPTAGE des
      séances (Seance.statut='terminee' ET Presence.statut='present') est
      repris À L'IDENTIQUE de la correction du 2026-08-04 (Point 6), déjà
      correct ; seule la SOURCE du montant/د.م. change ici.

    'tarif_manquant' (nouveau, par ligne de detail ET au niveau du résultat via
    'tarifs_manquants') — blocage PAR CONTEXTE (décision explicite du client) :
    si AUCUNE ligne active n'existe pour (tranche_age, nb_slots) demandée,
    JAMAIS un montant inventé à 0 ou une exception : la ligne concernée est
    marquée 'tarif_manquant': True (montant réellement 0 dans le total, mais
    signalé CLAIREMENT, jamais silencieusement — voir couverture_tarifs_
    remuneration_groupe() pour le bandeau مدير/مشرف correspondant, et
    templates/dashboard/_remuneration_detail.html pour son affichage côté prof).

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

    tarifs_groupe/tarifs_individuel (optionnels, dicts {(tranche_age, nb_slots):
    montant} / {tranche_age: montant}, Tâche du 2026-08-06 — audit de
    performance, point 8, adapté au 2026-08-27 pour les 2 nouvelles grilles) :
    évite de refaire une requête à CHAQUE appel quand cette fonction est
    rappelée en boucle sur plusieurs profs (mshrif_remuneration) — la grille
    tarifaire est la même pour tout le monde, un seul appelant qui boucle
    peut la charger UNE fois et la transmettre ici. None (défaut) = ancien
    comportement inchangé (requête interne), pour les appelants à un seul
    prof (prof_remuneration, admin_prof_remuneration_detail)."""
    from .models import TarifRemunerationGroupe, TarifRemunerationIndividuel, Presence, Seance

    if tarifs_groupe is None:
        tarifs_groupe = {
            (t.tranche_age, t.nb_slots): t.montant
            for t in TarifRemunerationGroupe.objects.filter(est_actif=True)
        }
    if tarifs_individuel is None:
        tarifs_individuel = {
            t.tranche_age: t.montant for t in TarifRemunerationIndividuel.objects.all()
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
    tarifs_manquants = []

    for groupe in prof.groupes.all():
        nb_slots_groupe = groupe.creneau.slots.count() if groupe.creneau_id else None

        if groupe.type_capacite == 'individuel':
            tarif_enfant = tarifs_individuel.get('enfant')
            tarif_adulte = tarifs_individuel.get('adulte')
        else:
            # Manquant si aucune OptionNbSeances n'est encore rattachée au
            # groupe (aucun créneau — nb_slots_groupe=None, impossible à
            # tarifer) OU si aucune ligne active n'existe pour ce nb_slots
            # précis — jamais un repli sur un autre nb_slots.
            tarif_enfant = tarifs_groupe.get(('enfant', nb_slots_groupe)) if nb_slots_groupe else None
            tarif_adulte = tarifs_groupe.get(('adulte', nb_slots_groupe)) if nb_slots_groupe else None

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
                nb_enfants_actifs * (tarif_enfant or 0) + nb_adultes_actifs * (tarif_adulte or 0)
            )
            individuel_nb_seances_confirmees += presences_mois.count()
            individuel_nb_seances_prevues += nb_seances_prevues_groupe
        else:
            # Groupes — nombre d'élèves actifs × tarif mensuel selon nb_slots.
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

        # Manquant = un tarif absent (None) alors que des élèves de cette
        # tranche sont réellement concernés — jamais un montant à 0 silencieux.
        tarif_manquant = False
        if nb_enfants and tarif_enfant is None:
            tarif_manquant = True
            tarifs_manquants.append({
                'groupe': groupe, 'tranche_age': 'enfant', 'nb_slots': nb_slots_groupe,
                'type_capacite': groupe.type_capacite,
            })
        if nb_adultes and tarif_adulte is None:
            tarif_manquant = True
            tarifs_manquants.append({
                'groupe': groupe, 'tranche_age': 'adulte', 'nb_slots': nb_slots_groupe,
                'type_capacite': groupe.type_capacite,
            })

        montant_enfants = nb_enfants * (tarif_enfant or 0)
        montant_adultes = nb_adultes * (tarif_adulte or 0)
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
            'nb_slots': nb_slots_groupe,
            'tarif_manquant': tarif_manquant,
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
        'tarifs_manquants': tarifs_manquants,
    }


def couverture_tarifs_remuneration_groupe():
    """{'total', 'configures', 'combinaisons_manquantes'} — combinaisons
    (tranche_age × OptionNbSeances actives) sans ligne TarifRemunerationGroupe
    active, même esprit que registration.utils.couverture_grille_prix (Besoin 3,
    "notification obligatoire"). Recalculée à CHAQUE appel, jamais mise en
    cache — même philosophie que le reste des fonctions 'couverture_*' du
    projet. Affichée en bandeau PERSISTANT (jamais un badge 🔔 dismissible,
    voir TarifRemunerationGroupe.__doc__) sur admin_tarifs_remuneration."""
    from .models import OptionNbSeances, TarifRemuneration, TarifRemunerationGroupe

    valeurs_nb_slots = list(OptionNbSeances.objects.filter(est_actif=True).values_list('valeur', flat=True))
    tranches = [code for code, _label in TarifRemuneration.TRANCHE_AGE_CHOICES]
    combinaisons = [(t, n) for t in tranches for n in valeurs_nb_slots]
    configurees = set(
        TarifRemunerationGroupe.objects.filter(est_actif=True, nb_slots__in=valeurs_nb_slots)
        .values_list('tranche_age', 'nb_slots')
    )
    manquantes = [c for c in combinaisons if c not in configurees]
    return {
        'total': len(combinaisons),
        'configures': len(combinaisons) - len(manquantes),
        'combinaisons_manquantes': manquantes,
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


# ==================== PHOTO DE GROUPE (Tâche du 2026-08-17) ====================

TAILLE_MAX_PHOTO_GROUPE_OCTETS = 5 * 1024 * 1024  # 5 Mo
EXTENSIONS_PHOTO_GROUPE_VALIDES = ('.png', '.jpg', '.jpeg', '.webp', '.gif')


def valider_photo_groupe(fichier):
    """Renvoie un message d'erreur arabe si `fichier` est refusé comme photo de
    groupe, None s'il est accepté — même patron de validation que
    dashboard.views.mshrif_logo (extension + taille + ouverture réelle via
    Pillow, pour confirmer que le fichier est vraiment une image et pas juste
    renommé). Validation TOUJOURS serveur, jamais sur la seule confiance du
    <input accept=...> côté client."""
    from PIL import Image

    if not fichier.name.lower().endswith(EXTENSIONS_PHOTO_GROUPE_VALIDES):
        return 'صيغة الملف غير مدعومة — استعمل PNG أو JPEG أو WEBP أو GIF.'
    if fichier.size > TAILLE_MAX_PHOTO_GROUPE_OCTETS:
        return 'حجم الملف كبير جداً — الحد الأقصى 5 ميغابايت.'
    try:
        image = Image.open(fichier)
        image.verify()
        fichier.seek(0)  # verify() consomme le curseur du fichier, on le remet au début avant de sauvegarder
    except Exception:
        return 'الملف المرفوع ليس صورة صالحة.'
    return None


# ==================== BACKFILL Groupe.categorie DEPUIS LE CRÉNEAU (Chantier du 2026-08-19) ====================

def categorie_derivee_du_creneau(creneau):
    """'mineurs'/'hommes_adultes'/'femmes_adultes' si le créneau permet de
    trancher SANS AMBIGUÏTÉ, sinon None — jamais deviné. Même règle que
    Groupe.categorie_collectif (courses/models.py), mais SANS sa restriction
    type_capacite=='groupe' : contrairement à categorie_collectif (réservée
    aux groupes collectifs pour la navigation par pastilles, voir son
    docstring), Groupe.categorie s'applique à N'IMPORTE QUEL type de groupe
    (individuel compris, voir Groupe.categorie.__doc__) — la dérivation
    âge/sexe du créneau est tout aussi fiable pour un groupe individuel que
    pour un groupe collectif, donc réutilisée ici sans cette restriction.
    None si : créneau à cheval enfant/adulte, ou adulte des deux sexes
    (sexe_cible='mixte') — aucun cas réel de ce type observé lors de l'audit
    du 2026-08-19, mais gardé None plutôt que de deviner, même principe que
    categorie_collectif."""
    if creneau.age_max < AGE_SEUIL_ADULTE:
        return 'mineurs'
    if creneau.age_min >= AGE_SEUIL_ADULTE:
        if creneau.sexe_cible == 'homme':
            return 'hommes_adultes'
        if creneau.sexe_cible == 'femme':
            return 'femmes_adultes'
    return None


def backfiller_categorie_depuis_creneau():
    """Remplit Groupe.categorie pour tout groupe dont la catégorie est encore
    vide ET dont le créneau assigné permet une déduction sans ambiguïté
    (categorie_derivee_du_creneau) — demande explicite du client suite à
    l'audit du 2026-08-19 (31 groupes réels, 19 auto-classifiables sans
    ambiguïté, 2 cas ambigus à cheval enfant/adulte, 8 sans créneau —
    laissés vides dans les 3 cas, jamais devinés). N'écrase JAMAIS une
    catégorie déjà renseignée manuellement — filtre sur categorie='' AVANT
    tout calcul, qu'elle coïncide ou non avec ce que la dérivation aurait
    donné. Idempotent : un 2e passage ne retrouve plus aucune ligne à
    traiter (les groupes remplis au 1er passage ne sont plus categorie='').
    Retourne le nombre de groupes réellement remplis.

    Fonction séparée de la migration de données (qui, elle, utilise les
    modèles historiques via apps.get_model — bonne pratique Django, voir
    courses/migrations/0034_backfill_groupe_categorie_depuis_creneau.py)
    pour rester testable/réutilisable directement avec les vrais modèles,
    même patron que chat.services.backfiller_conversations_manquantes."""
    from .models import Groupe

    nb_remplis = 0
    groupes = Groupe.objects.filter(categorie='', creneau__isnull=False).select_related('creneau')
    for groupe in groupes:
        categorie = categorie_derivee_du_creneau(groupe.creneau)
        if categorie:
            groupe.categorie = categorie
            groupe.save(update_fields=['categorie'])
            nb_remplis += 1
    return nb_remplis
