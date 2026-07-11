import datetime

JOUR_INDEX = {'lun': 0, 'mar': 1, 'mer': 2, 'jeu': 3, 'ven': 4, 'sam': 5, 'dim': 6}

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
        h = (datetime.datetime.combine(datetime.date.today(), h) + datetime.timedelta(hours=1)).time()
    return heures


def _heures_couvertes(heure_debut, heure_fin):
    """Liste des heures pleines couvertes par un intervalle [heure_debut, heure_fin)."""
    heures = []
    h = heure_debut
    while h < heure_fin:
        heures.append(h)
        h = (datetime.datetime.combine(datetime.date.today(), h) + datetime.timedelta(hours=1)).time()
    return heures


def creneaux_manquants_pour_prof(prof, creneau):
    """Vérifie que le prof est disponible sur toutes les heures couvertes par
    les 2 blocs du créneau. Retourne la liste des (jour, heure) manquants
    (liste vide = compatible)."""
    from .models import DisponibiliteProf

    dispo_prof = set(DisponibiliteProf.objects.filter(prof=prof).values_list('jour_semaine', 'heure_debut'))
    manquants = []
    for jour, debut, fin in [
        (creneau.jour_1, creneau.heure_debut_1, creneau.heure_fin_1),
        (creneau.jour_2, creneau.heure_debut_2, creneau.heure_fin_2),
    ]:
        for h in _heures_couvertes(debut, fin):
            if (jour, h) not in dispo_prof:
                manquants.append((jour, h))
    return manquants


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

    aujourd_hui = datetime.date.today()
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

    aujourd_hui = datetime.date.today()
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
            'total_ayat_sourate': total_ayat_sourate,
            'pourcentage': min(pourcentage, 100),
        })
    par_sourate_liste.sort(key=lambda item: item['numero'])

    return {
        'total_ayat_memorises': total_ayat,
        'nb_sourates_distinctes': len(par_sourate),
        'par_sourate': par_sourate_liste,
        'historique': list(reversed(historique)),
    }
