"""Progression de mémorisation basée sur (حزب, ثمن) + sens de progression —
remplace l'ancien système basé sur les sourates/ayat pour le bloc الحفظ
(voir courses.models.ProgressionMemorisation et courses.models.PartieEvaluee).

Depuis le chantier du 2026-09-19, le bloc المراجعة est LUI AUSSI saisi en
حزب/ثمن (voir courses.models.Presence.hizb_debut_revision) — mais SANS
ProgressionMemorisation dédiée : juste une plage (من→إلى) libre par séance,
comme l'était l'ancienne saisie sourate/ayah. index_physique ci-dessous
(ordre PHYSIQUE, indépendant de tout sens) est la fonction utilisée pour
vérifier sa cohérence (fin >= début) — aucune des autres fonctions de ce
module (orientées "sens de progression") ne le concerne.

Le Coran est ici divisé en 60 أحزاب (numéro stable 1-60, ordre Mushaf), chacun
en 8 أثمان (1-8, ordre FIXE — jamais inversé selon le sens de progression, voir
position_suivante ci-dessous). Les noms sont ceux fournis par le client, dans
l'ordre des numéros de حزب."""

from django.utils.translation import gettext_lazy as _

NB_THUMN_PAR_HIZB = 8
NB_HIZB = 60

SENS_CHOICES = [
    ('tasaudi', _('تصاعدي')),
    ('tanazuli', _('تنازلي')),
]

HIZB_NOMS = [
    (1, _('الحمد')),
    (2, _('وإذا لقوا')),
    (3, _('سيقول')),
    (4, _('واذكروا')),
    (5, _('تلك الرسل')),
    (6, _('قل أؤنبئكم')),
    (7, _('لن تنالوا')),
    (8, _('يستبشرون')),
    (9, _('والمحصنات')),
    (10, _('الله لا إله إلا هو')),
    (11, _('لا يحب')),
    (12, _('رجلان')),
    (13, _('لتجدن')),
    (14, _('إنما يستجيب')),
    (15, _('ولو أننا')),
    (16, _('دعواهم')),
    (17, _('قال الملأ')),
    (18, _('وإذ نتقنا')),
    (19, _('واعلموا')),
    (20, _('إن كثيرا')),
    (21, _('إنما السبيل')),
    (22, _('أحسنوا')),
    (23, _('وما من دابة')),
    (24, _('وإلى مدين')),
    (25, _('وما أبرئ')),
    (26, _('أفمن يعلم')),
    (27, _('ألمر')),
    (28, _('وقال الله')),
    (29, _('سبحان')),
    (30, _('أولم يروا')),
    (31, _('قال ألم أقل')),
    (32, _('طه')),
    (33, _('اقترب')),
    (34, _('يا أيها الناس')),
    (35, _('قد أفلح')),
    (36, _('لا تتبعوا')),
    (37, _('يرجون')),
    (38, _('أنؤمن')),
    (39, _('جواب')),
    (40, _('وصلنا')),
    (41, _('ولا تجادلوا')),
    (42, _('ومن يسلم')),
    (43, _('ومن يقنت')),
    (44, _('يرزقكم')),
    (45, _('وما أنزلنا')),
    (46, _('فنبذناه')),
    (47, _('فمن أظلم')),
    (48, _('ويا قوم')),
    (49, _('إليه يرد')),
    (50, _('قل أولو جئتكم')),
    (51, _('ما خلقنا')),
    (52, _('لقد رضي')),
    (53, _('فما خطبكم')),
    (54, _('الرحمن')),
    (55, _('قد سمع')),
    (56, _('يسبح لله')),
    (57, _('تبارك')),
    (58, _('قل أوحي')),
    (59, _('عم')),
    (60, _('سبح')),
]

HIZB_NOMS_DICT = {numero: nom for numero, nom in HIZB_NOMS}


def nom_hizb(numero):
    return HIZB_NOMS_DICT.get(numero)


def hizb_suivant(hizb, sens):
    """Hizb suivant dans le sens de progression, ou None si la fin de la
    progression est atteinte (jamais de حزب 0 ou 61 — voir section 8 du
    cahier des charges). تصاعدي: le numéro DIMINUE (vers le حزب 1).
    تنازلي: le numéro AUGMENTE (vers le حزب 60)."""
    if sens == 'tasaudi':
        suivant = hizb - 1
    else:
        suivant = hizb + 1
    if suivant < 1 or suivant > NB_HIZB:
        return None
    return suivant


def position_est_terminale(hizb, thumn, sens):
    """True si (حزب، ثمن) est la toute DERNIÈRE position accessible dans ce
    sens (حزب 1 / ثمن 8 en تصاعدي, حزب 60 / ثمن 8 en تنازلي) — plus aucune
    position suivante possible. Utilisée pour marquer ProgressionMemorisation.
    terminee après une "الانتقال" dont le nouveau موقف حالي (voir
    dashboard.views.prof_presence_sauvegarder, chantier du 2026-09-14 v6) est
    désormais le point d'arrivée du travail enregistré, PLUS le résultat d'un
    +1 thumn automatique — cette fonction reste le seul moyen fiable de
    détecter la fin du parcours."""
    return thumn == NB_THUMN_PAR_HIZB and hizb_suivant(hizb, sens) is None


def position_vers_index(hizb, thumn, sens):
    """Coordonnée linéaire (0 à NB_HIZB*NB_THUMN_PAR_HIZB - 1 = 479) d'une
    position (حزب، ثمن) le long du parcours, DANS LE SENS DE PROGRESSION
    donné — usage STRICTEMENT interne (l'affichage reste toujours en
    حزب/ثمن, jamais en index brut).

    Correctif du 2026-09-14 (bug réel signalé par le client) : c'est la
    SEULE fonction autorisée à convertir une position en une valeur
    comparable/soustrayable — jamais une simple différence de numéros de
    حزب (voir distance_thumns ci-dessous), qui casse dès que le ثمن de
    départ n'est pas 1 (ex. départ 2/3 -> 3/4 : abs(3-2)=1 حزب "complet" +
    (thumn_actuel - 1) donnait à tort 8+3=11 au lieu des 9 ثمن réellement
    parcourus — l'ancien calcul oubliait de retrancher le ثمن de départ)."""
    if sens == 'tasaudi':
        rang_hizb = NB_HIZB - hizb  # تصاعدي : le حزب 60 est le 1er du parcours, le 1 le dernier
    else:
        rang_hizb = hizb - 1  # تنازلي : le حزب 1 est le 1er du parcours, le 60 le dernier
    return rang_hizb * NB_THUMN_PAR_HIZB + (thumn - 1)


def nouvelle_position_apres_seance(hizb_avant, thumn_avant, sens, action, plages_travaillees):
    """LA fonction centrale — SEULE source de vérité — pour déterminer le
    nouveau موقف حالي (ProgressionMemorisation.hizb_actuel/thumn_actuel)
    après une séance. Remplace l'usage de position_suivante ici (bug corrigé
    le 2026-09-14 v6, signalé par le client : "الانتقال" avançait la
    position AUTOMATIQUEMENT de +1 ثمن à partir du موقف الحالي, ignorant
    complètement le "إلى" réellement saisi dans المحفوظ في هذه الحصة — ex.
    موقف 2/5, travail 2/5->2/6, الانتقال donnait à tort 2/7 au lieu de 2/6).

    `plages_travaillees` : liste de tuples (hizb_fin, thumn_fin) — les points
    d'arrivée du/des من→إلى réellement enregistrés cette séance (courses.
    models.TravailSeance). `action` est une valeur de Presence.
    RESULTAT_CHOICES ('valide' = الانتقال, 'a_refaire' = إعادة الجزء).

    RÈGLE (demande explicite du client) :
    - 'a_refaire' (ou aucune plage enregistrée) : le parcours NE progresse
      PAS — retourne (hizb_avant, thumn_avant) inchangé. Aucun +1 ثمن.
    - 'valide' : le professeur a DÉJÀ indiqué où l'élève est arrivé (le إلى)
      — ce إلى devient DIRECTEMENT le nouveau موقف حالي, jamais recalculé ni
      avancé une seconde fois. S'il y a plusieurs plages non contiguës dans
      la même séance, on retient celle dont l'arrivée est la PLUS AVANCÉE le
      long du sens (jamais une simple addition de +1 ثمن à hizb_avant).

    Retourne (hizb, thumn, terminee) — terminee via position_est_terminale."""
    if action == 'a_refaire' or not plages_travaillees:
        hizb, thumn = hizb_avant, thumn_avant
    else:
        hizb, thumn = max(plages_travaillees, key=lambda pos: position_vers_index(pos[0], pos[1], sens))
    return hizb, thumn, position_est_terminale(hizb, thumn, sens)


def distance_thumns(hizb_depart, thumn_depart, hizb_actuel, thumn_actuel, sens):
    """Nombre de ثمن réellement parcourus entre نقطة الانطلاق et la position
    actuelle, DANS LE SENS de progression — LA seule formule à utiliser
    partout où une distance/progression doit être calculée (voir
    position_vers_index.__doc__ pour le bug qu'elle corrige). Toujours >= 0
    tant que la position actuelle est bien atteignable depuis le départ dans
    ce sens (garanti par position_suivante, qui ne fait jamais reculer)."""
    return (
        position_vers_index(hizb_actuel, thumn_actuel, sens)
        - position_vers_index(hizb_depart, thumn_depart, sens)
    )


def index_physique(hizb, thumn):
    """Position canonique FIXE (0 à 479) d'une position (حزب، ثمن) dans
    l'ORDRE PHYSIQUE du Coran (حزب 1 en premier, حزب 60 en dernier) —
    INDÉPENDANTE du sens de progression choisi par l'élève, contrairement à
    position_vers_index ci-dessus (qui dépend du sens et sert UNIQUEMENT à
    mesurer la distance le long du parcours OFFICIEL/continu, voir
    distance_thumns.__doc__).

    Chantier du 2026-09-14 v5 (retour client) : un élève peut mémoriser de
    façon NON continue (ex. حزب 1, 2 puis 5, 6 en sautant 3, 4) — la
    couverture RÉELLEMENT mémorisée est un concept PHYSIQUE (quels ثمن du
    Coran sont couverts), indépendant du sens d'étude déclaré. Cette fonction
    est la seule à utiliser pour agréger cette couverture (voir
    courses.utils.couverture_hifz_reelle), jamais position_vers_index qui
    donnerait une distance orientée dénuée de sens pour cet usage."""
    return (hizb - 1) * NB_THUMN_PAR_HIZB + (thumn - 1)


def position_depuis_index(index):
    """Inverse de index_physique : reconstitue (حزب، ثمن) à partir d'une
    position canonique (0 à 479)."""
    hizb, reste = divmod(index, NB_THUMN_PAR_HIZB)
    return hizb + 1, reste + 1


def position_suivante(hizb, thumn, sens, action):
    """Calcule LA POSITION IMMÉDIATEMENT SUIVANTE (+1 ثمن, ou passage au حزب
    suivant selon le sens) — un pas UNIQUE et FIXE, indépendant de ce qui a
    été réellement travaillé.

    ⚠️ NE PLUS UTILISER cette fonction pour faire avancer ProgressionMemorisation.
    hizb_actuel/thumn_actuel après une séance (bug corrigé le 2026-09-14 v6,
    signalé par le client) : "الانتقال" ne signifie PAS "position actuelle +1
    ثمن" mais "adopter le إلى de المحفوظ في هذه الحصة comme nouveau موقف
    حالي" — voir dashboard.views.prof_presence_sauvegarder, qui prend
    désormais directement l'extrémité de la plage TravailSeance enregistrée
    (via position_vers_index pour choisir le point le plus avancé s'il y a
    plusieurs plages), jamais ce +1 automatique. Cette fonction reste
    disponible pour d'éventuels autres besoins internes (et ses propres
    tests), mais n'est plus le mécanisme d'avancement de la position
    officielle.

    `action` est une valeur de Presence.RESULTAT_CHOICES ('valide' = الانتقال,
    'a_refaire' = إعادة الجزء). L'ordre des أثمان (1->8) NE CHANGE JAMAIS selon
    le sens : seul le passage d'un حزب au suivant dépend du sens. Retourne
    None si l'élève vient de terminer le dernier ثمن accessible dans son sens
    (fin de progression, jamais de position invalide)."""
    if action == 'a_refaire':
        return (hizb, thumn)

    if thumn < NB_THUMN_PAR_HIZB:
        return (hizb, thumn + 1)

    suivant = hizb_suivant(hizb, sens)
    if suivant is None:
        return None
    return (suivant, 1)
