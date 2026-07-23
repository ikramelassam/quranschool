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
    """Vérifie qu'un élève peut être assigné à un groupe donné, selon TOUS les
    critères métier (place restante, horaire, programme, riwaya, âge, sexe,
    type d'abonnement). Retourne une chaîne expliquant le premier critère non
    respecté, ou None si le groupe est compatible. Utilisée à la fois pour la
    suggestion automatique (affichage) et comme garde-fou serveur avant toute
    assignation (sécurité), afin qu'aucune des deux voies ne puisse être
    contournée par l'autre. Voir raison_incompatibilite_groupe_inscription,
    l'équivalent pour une candidature pas encore acceptée — les deux
    fonctions doivent rester alignées critère par critère."""
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

    if inscription.programme != creneau.type_seance:
        return "نوع الحلقة (حفظ/تثبيت) لا يتوافق مع برنامج الطالب."

    if inscription.riwaya != creneau.riwaya:
        return "رواية الحلقة لا تتوافق مع رواية الطالب."

    age = _age_depuis_naissance(inscription.date_naissance)
    if age < creneau.age_min or age > creneau.age_max:
        return "عمر الطالب لا يقع ضمن الفئة العمرية لهذه الحلقة."

    if creneau.sexe_cible != 'mixte' and creneau.sexe_cible != inscription.sexe:
        return "جنس الطالب لا يتوافق مع الفئة المستهدفة لهذه الحلقة."

    type_offre = inscription.abonnement_type_offre()
    if type_offre and type_offre != groupe.type_capacite:
        return "نوع الاشتراك (فردي/جماعي) لا يتوافق مع نوع هذه المجموعة."

    manquants = creneaux_manquants_pour_eleve(eleve, creneau)
    if manquants:
        return "جدول تفرغ الطالب لا يغطي كامل مواعيد هذه الحلقة."

    return None


def raison_incompatibilite_groupe_inscription(inscription, groupe):
    """Équivalent de raison_incompatibilite_groupe pour une candidature
    (InscriptionEleve) pas encore acceptée: pas de Eleve/DisponibiliteEleve
    en base, les critères sont lus directement depuis l'inscription."""
    if groupe.eleves.count() >= groupe.capacite_max:
        return "المجموعة مكتملة العدد."

    creneau = groupe.creneau
    if not creneau:
        return "لا يوجد جدول زمني محدد لهذه المجموعة."

    if inscription.programme != creneau.type_seance:
        return "نوع الحلقة (حفظ/تثبيت) لا يتوافق مع برنامج الطالب."

    if inscription.riwaya != creneau.riwaya:
        return "رواية الحلقة لا تتوافق مع رواية الطالب."

    age = _age_depuis_naissance(inscription.date_naissance)
    if age < creneau.age_min or age > creneau.age_max:
        return "عمر الطالب لا يقع ضمن الفئة العمرية لهذه الحلقة."

    if creneau.sexe_cible != 'mixte' and creneau.sexe_cible != inscription.sexe:
        return "جنس الطالب لا يتوافق مع الفئة المستهدفة لهذه الحلقة."

    type_offre = inscription.abonnement_type_offre()
    if type_offre and type_offre != groupe.type_capacite:
        return "نوع الاشتراك (فردي/جماعي) لا يتوافق مع نوع هذه المجموعة."

    manquants = creneaux_manquants_pour_matrice(inscription.disponibilites, creneau)
    if manquants:
        return "جدول تفرغ الطالب لا يغطي كامل مواعيد هذه الحلقة."

    return None


def groupes_compatibles_pour_eleve(eleve):
    """Liste des groupes actifs compatibles avec un élève, selon tous les
    critères vérifiés par raison_incompatibilite_groupe."""
    from .models import Groupe

    candidats = Groupe.objects.filter(statut='actif').exclude(eleves=eleve).select_related('creneau', 'prof__user')
    return [g for g in candidats if raison_incompatibilite_groupe(eleve, g) is None]


def groupes_compatibles_pour_inscription(inscription):
    """Équivalent de groupes_compatibles_pour_eleve pour une candidature pas
    encore acceptée (affichage informatif sur la fiche de candidature, avant
    que le directeur clique accepter/refuser)."""
    from .models import Groupe

    candidats = Groupe.objects.filter(statut='actif').select_related('creneau', 'prof__user')
    return [g for g in candidats if raison_incompatibilite_groupe_inscription(inscription, g) is None]


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


def etendre_toutes_les_seances():
    """Appelée à chaque visite des pages séances/calendrier admin: pousse l'horizon
    de génération de tous les groupes actifs ayant un créneau, sans jamais retoucher
    aux semaines déjà couvertes."""
    from .models import Groupe

    for groupe in Groupe.objects.filter(statut='actif', creneau__isnull=False):
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


def calculer_progression_eleve(eleve):
    """Suivi de progression cumulé d'un élève, basé sur les ayats mémorisés
    (nb_ayat_memorises de chaque Presence). Compté en ayats, pas en pages
    (la pagination du mushaf varie selon l'édition/riwaya, l'ayah est universel).

    Pour chaque sourate touchée, la couverture affichée est l'étendue
    (ayah_debut le plus bas -> ayah_fin le plus haut vus sur toutes les
    séances) plutôt qu'une fusion exacte d'intervalles: en pratique la
    mémorisation progresse de façon linéaire dans une sourate, donc cette
    étendue reflète correctement l'avancement sans complexité inutile.
    """
    from .models import Presence
    from .quran_data import SOURATES_NOMS, SOURATES_NB_AYAT

    presences = Presence.objects.filter(
        eleve=eleve, sourate_memorisee__isnull=False
    ).select_related('seance').order_by('seance__date', 'seance__heure')

    total_ayat = 0
    par_sourate = {}
    historique = []

    for p in presences:
        nb = p.nb_ayat_memorises
        total_ayat += nb

        historique.append({
            'date': p.seance.date,
            'groupe': p.seance.groupe.nom,
            'sourate': p.nom_sourate_memorisee,
            'ayah_debut': p.ayah_debut_memorisation,
            'ayah_fin': p.ayah_fin_memorisation,
            'nb_ayat': nb,
            'note_code': p.note_memorisation,
            'note_display': p.get_note_memorisation_display() if p.note_memorisation else None,
        })

        numero = p.sourate_memorisee
        if numero not in par_sourate:
            par_sourate[numero] = {
                'debut': p.ayah_debut_memorisation,
                'fin': p.ayah_fin_memorisation,
            }
        else:
            par_sourate[numero]['debut'] = min(par_sourate[numero]['debut'], p.ayah_debut_memorisation)
            par_sourate[numero]['fin'] = max(par_sourate[numero]['fin'], p.ayah_fin_memorisation)
        # Écrasé à chaque passage (ordre chronologique croissant) -> reste
        # la note de la séance la PLUS RÉCENTE pour cette sourate.
        par_sourate[numero]['note_code'] = p.note_memorisation
        par_sourate[numero]['note_display'] = p.get_note_memorisation_display() if p.note_memorisation else None

    par_sourate_liste = []
    for numero, bornes in par_sourate.items():
        total_ayat_sourate = SOURATES_NB_AYAT.get(numero, 0)
        couverts = bornes['fin'] - bornes['debut'] + 1
        pourcentage = round((couverts / total_ayat_sourate) * 100) if total_ayat_sourate else 0
        par_sourate_liste.append({
            'numero': numero,
            'nom': SOURATES_NOMS.get(numero),
            'ayah_debut': bornes['debut'],
            'ayah_fin': bornes['fin'],
            'ayat_couverts': couverts,
            'total_ayat_sourate': total_ayat_sourate,
            'pourcentage': min(pourcentage, 100),
            'note_code': bornes['note_code'],
            'note_display': bornes['note_display'],
        })
    par_sourate_liste.sort(key=lambda item: item['numero'])

    return {
        'total_ayat_memorises': total_ayat,
        'nb_sourates_distinctes': len(par_sourate),
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
    """{numero_sourate: [ayah_min, ayah_fin_max]} agrégé sur toutes les
    Presence de l'élève avec mémorisation enregistrée. Même hypothèse que
    calculer_progression_eleve: l'étendue entre le début le plus bas et la
    fin la plus haute vus sur toutes les séances, pas une fusion exacte
    d'intervalles (la mémorisation progresse en pratique de façon continue
    dans une sourate)."""
    from .models import Presence

    couverture = {}
    valeurs = Presence.objects.filter(
        eleve=eleve, sourate_memorisee__isnull=False
    ).values_list('sourate_memorisee', 'ayah_debut_memorisation', 'ayah_fin_memorisation')
    for numero, debut, fin in valeurs:
        if numero not in couverture:
            couverture[numero] = [debut, fin]
        else:
            couverture[numero][0] = min(couverture[numero][0], debut)
            couverture[numero][1] = max(couverture[numero][1], fin)
    return couverture


def _quart_est_couvert(quart, couverture):
    """Un quart de hizb (quran_data.HIZB_QUARTERS) est couvert si la
    mémorisation enregistrée de l'élève recouvre ENTIÈREMENT sa plage
    d'ayat, sourate par sourate — un quart peut chevaucher 2 sourates
    consécutives à sa frontière (ex: hizb 45, quart 3 = 36:60 -> 37:21)."""
    from .quran_data import SOURATES_NB_AYAT

    (sourate_debut, ayah_debut), (sourate_fin, ayah_fin) = quart
    for sourate in range(sourate_debut, sourate_fin + 1):
        if sourate not in couverture:
            return False
        debut_couvert, fin_couvert = couverture[sourate]
        borne_debut = ayah_debut if sourate == sourate_debut else 1
        borne_fin = ayah_fin if sourate == sourate_fin else SOURATES_NB_AYAT[sourate]
        if debut_couvert > borne_debut or fin_couvert < borne_fin:
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


AGE_SEUIL_ADULTE = 18  # seuil enfant/adulte pour la grille tarifaire — confirmé par le client (moins de 18 = enfant, 18 et plus = adulte)


def _tranche_age_eleve(eleve):
    """'enfant'/'adulte' selon AGE_SEUIL_ADULTE, ou None si l'âge est inconnu
    (élève sans dossier d'inscription lié, ou dossier sans date de naissance —
    Eleve n'a pas de date_naissance propre, la seule source fiable est
    eleve.inscription.date_naissance). Jamais d'hypothèse silencieuse ici:
    un âge inconnu doit rester visible comme tel dans le détail du calcul,
    vu l'impact direct sur une somme d'argent réelle."""
    if eleve.inscription is None or eleve.inscription.date_naissance is None:
        return None
    age = _age_depuis_naissance(eleve.inscription.date_naissance)
    return 'adulte' if age >= AGE_SEUIL_ADULTE else 'enfant'


def calculer_remuneration_prof(prof):
    """Rémunération mensuelle d'un prof selon la grille TarifRemuneration
    (type_capacite du groupe × tranche d'âge de chaque élève actif). Détail
    par groupe pour que le calcul soit vérifiable. Ne retourne QUE le calcul
    de base de la grille — majoration_mensuelle (Prof) n'est ni lue ni
    additionnée ici: elle ne doit jamais atteindre la page du prof, même
    fondue dans un total, voir templates/dashboard/prof_remuneration.html."""
    from .models import TarifRemuneration

    tarifs = {
        (t.type_capacite, t.tranche_age): t.montant
        for t in TarifRemuneration.objects.all()
    }

    detail = []
    total_calcule = 0
    for groupe in prof.groupes.all():
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

        tarif_enfant = tarifs.get((groupe.type_capacite, 'enfant'), 0)
        tarif_adulte = tarifs.get((groupe.type_capacite, 'adulte'), 0)
        montant_enfants = nb_enfants * tarif_enfant
        montant_adultes = nb_adultes * tarif_adulte
        sous_total = montant_enfants + montant_adultes
        total_calcule += sous_total

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
    }
