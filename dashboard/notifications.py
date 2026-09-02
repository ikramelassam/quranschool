"""Panneau 🔔 الإشعارات (Chantier notifications du 2026-08-19, étendu au
مدير/مشرف le 2026-08-24) — Option A validée explicitement avec
l'utilisateur : calcul à la volée, jamais un nouveau modèle stockant une
ligne par notification individuelle.

SCOPE VOLONTAIRE : ce module n'est appelé QUE depuis les pages d'accueil de
chaque rôle — dashboard_eleve/dashboard_prof à l'origine (Chantier du
2026-08-19), dashboard_admin/dashboard_mshrif depuis le 2026-08-24 (voir
notifications_direction ci-dessous), dashboard_superviseur depuis le
2026-08-31 (voir notifications_superviseur ci-dessous) — jamais depuis un
context processor
global comme chat.context_processors.chat_badge_context ou
annonces.context_processors.annonces_badge_context, qui eux tournent sur
CHAQUE page du site. Coût mesuré : 0 requête supplémentaire sur toute page
qui n'est pas la page d'accueil, contre une requête (mise en cache 15s, mais
ce cache est LocMemCache — donc par processus gunicorn, pas vraiment partagé,
voir settings.py qui ne déclare aucun CACHES) payée par chat/annonces sur
CHAQUE page. Ne pas migrer ce module vers un context processor sans
revalider ce choix explicitement — voir le rapport du chantier.

LECTURE PAR TYPE, PAS PAR NOTIFICATION INDIVIDUELLE (accounts.models.
DerniereVisiteNotification) : un seul timestamp par (user, cle) — visiter la
page cible marque tout ce type comme lu d'un coup. Conséquence assumée et
validée : chaque événement renvoyé par ce module est PAR CONSTRUCTION non lu
(il cesse d'apparaître dès que son type est visité) — aucun style
"lu/non-lu" par ligne individuelle n'est donc nécessaire côté template.

AMORÇAGE (évite une inondation de notifications rétroactives le jour de la
mise en service) : la toute première fois qu'un seuil est nécessaire pour un
(user, cle) qui n'a encore JAMAIS de ligne DerniereVisiteNotification, ce
seuil est immédiatement persisté à maintenant (voir _seuils ci-dessous)
plutôt que traité comme "depuis toujours" — un compte existant qui n'a
jamais visité la page cible ne voit donc jamais un badge géant le jour du
déploiement, seulement le contenu réellement publié APRÈS ce premier calcul.

ANTI-FAUSSE-NOTIFICATION : chaque requête ci-dessous filtre sur un champ
auto_now_add (jamais modifié après coup), jamais un champ auto_now — une
correction mineure d'un ElementHakiba/DocumentEleve/Evaluation déjà lu ne
redéclenche donc jamais le badge, seule une VRAIE création le fait.
"""
import datetime

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

# Fetch généreux (une seule requête, pas de 2e requête .count() séparée) —
# largement suffisant pour distinguer "0 / 1-9 / 9+" une fois passé dans
# abrege_badge côté template ; au-delà, la distinction exacte n'a de toute
# façon plus d'importance visuelle.
LIMITE_FETCH = 50
# Lignes affichées par groupe dans le panneau déroulant (pas dans le badge,
# qui lui reste sur le total réel) — même ordre de grandeur que l'ancienne
# zone "🔔 الإشعارات" supprimée (Chantier UX du 2026-08-16), qui plafonnait
# déjà à 5.
LIMITE_PAR_GROUPE = 5
# Lignes affichées dans le panneau déroulant de la DIRECTION (liste plate, pas
# groupée par type — voir notifications_direction) : un plafond global, pas
# par groupe. Plus large que LIMITE_PAR_GROUPE parce qu'il n'y a plus qu'une
# seule liste ; la page « عرض الكل » reste, elle, à LIMITE_FETCH.
LIMITE_LISTE_PLATE = 15


def _trier_groupes_par_recence(groupes):
    """Trie les groupes du panneau 🔔 de la PLUS RÉCENTE à la plus ancienne
    notification (antichronologique global) — le groupe dont l'évènement le
    plus récent est le plus récent passe en tête. Les évènements DANS chaque
    groupe sont déjà triés récent -> ancien par la requête qui les produit
    (order_by('-date…') / '-date_soumission' / '-date_ajout'…), donc
    groupe['evenements'][0]['date'] est bien le plus récent du groupe. Chaque
    groupe est par construction non vide (append gardé par `if evenements_*`).
    Modifie sur place et renvoie la liste."""
    groupes.sort(key=lambda g: g['evenements'][0]['date'], reverse=True)
    return groupes


def marquer_visite(user, cle):
    """Marque le type `cle` comme lu MAINTENANT pour `user` — à appeler
    depuis chaque vue "page cible" listée dans accounts.models.
    DerniereVisiteNotification.__doc__ (examens_eleve_liste, eleve_seances,
    eleve_cartable, evaluations_prof_recues, prof_hakiba, superviseur_hakiba),
    juste avant le render final (jamais avant, au cas où la vue redirige plus tôt sans
    jamais afficher la page — voir chaque appelant)."""
    from accounts.models import DerniereVisiteNotification

    DerniereVisiteNotification.objects.update_or_create(
        user=user, cle=cle, defaults={'date_visite': timezone.now()}
    )


def _seuils(user, cles):
    """Seuil de "nouveauté" par cle pour `user` — une seule requête pour
    toutes les clés demandées. Toute clé qui n'a encore jamais de ligne est
    amorcée à `user.date_joined` (PAS timezone.now() — voir correctif
    ci-dessous), en une seule requête bulk_create supplémentaire (pattern
    déjà établi dans ce projet, voir courses/migrations/
    0022_seed_criteres_eleves_et_backfill.py).

    CORRECTIF (bug détecté par les tests avant intégration, jamais expédié) :
    la 1ère version amorçait à timezone.now() pour EMPÊCHER une inondation
    rétroactive le jour du déploiement — mais "1ère fois qu'un seuil est
    calculé pour ce user" n'arrive pas QUE le jour du déploiement : c'est
    aussi VRAI de la toute première visite du dashboard par un compte tout
    nouvellement créé, pour qui du contenu réellement nouveau (créé APRÈS
    son inscription mais AVANT sa 1ère visite) était alors silencieusement
    avalé — jamais affiché, alors qu'il ne l'avait jamais vu. user.date_joined
    distingue proprement les deux cas : un compte déjà ancien voit une
    baseline ancienne (mêmes garanties d'origine), un compte tout neuf voit
    une baseline = sa date de création, donc tout contenu créé depuis compte
    bien comme nouveau. Le vrai "jour du déploiement, ne pas inonder les
    comptes DÉJÀ existants" reste couvert séparément par la migration de
    données accounts/migrations/0037_seed_dernieres_visites_notification.py
    (bulk_create à timezone.now() pour tous les eleve/prof déjà existants au
    moment du déploiement — cette fonction-ci ne le refait plus)."""
    from accounts.models import DerniereVisiteNotification

    existants = dict(
        DerniereVisiteNotification.objects.filter(user=user, cle__in=cles)
        .values_list('cle', 'date_visite')
    )
    manquants = [c for c in cles if c not in existants]
    if manquants:
        seuil_amorce = user.date_joined
        DerniereVisiteNotification.objects.bulk_create(
            [DerniereVisiteNotification(user=user, cle=c, date_visite=seuil_amorce) for c in manquants],
            ignore_conflicts=True,
        )
        for c in manquants:
            existants[c] = seuil_amorce
    return existants


def _datetime_seance(seance):
    """Horodatage d'affichage d'une séance (date + heure, timezone-aware) —
    utilisé comme proxy de date pour les événements 'notes_seances' (voir
    notifications_eleve : courses.Presence n'a AUCUN champ date propre)."""
    import datetime

    return timezone.make_aware(datetime.datetime.combine(seance.date, seance.heure))


def notifications_eleve(eleve, user, limite=LIMITE_PAR_GROUPE):
    """(groupes, total) pour le panneau 🔔 côté élève. `groupes` : liste de
    dicts {icone, label, evenements: [{texte, url, date}]} prêts pour le
    template, `total` : nombre réel d'événements (pas plafonné à `limite`,
    seul l'affichage l'est — voir dashboard.views.mes_notifications qui
    appelle avec limite=LIMITE_FETCH pour "عرض الكل"). Au plus 3 requêtes
    (une par type), toutes indexées et bornées à LIMITE_FETCH lignes — voir
    docstring du module pour le coût exact et pourquoi il est acceptable
    UNIQUEMENT sur une page d'accueil ou une page "voir tout" dédiée, jamais
    en context processor global."""
    from examens.models import Examen
    from courses.models import Presence
    from accounts.models import DocumentEleve

    seuils = _seuils(user, ['examens', 'notes_seances', 'cartable', 'paiements_retard'])
    groupes_eleve = eleve.groupes.all()

    examens = list(
        Examen.objects.filter(
            groupe__in=groupes_eleve, statut='publie',
            date_publication__gt=seuils['examens'],
        ).order_by('-date_publication')[:LIMITE_FETCH]
    )
    evenements_examens = [
        {'texte': _('اختبار جديد: %(titre)s') % {'titre': e.titre}, 'url': reverse('examens_eleve_liste'), 'date': e.date_publication}
        for e in examens
    ]

    # Presence n'a pas de champ date propre (voir courses.models.Presence) —
    # seance.date/heure comme proxy le plus proche disponible : cohérent car
    # la feuille de présence est remplie juste après la séance dans l'usage
    # normal (prof_presence_sauvegarder). Limite ASSUMÉE : un remplissage
    # très tardif d'une séance ancienne ne redéclenche pas le badge si la
    # date de la séance elle-même précède déjà la dernière visite — aucun
    # champ de meilleure précision n'existe sur ce modèle sans migration.
    seuil_notes_date = timezone.localtime(seuils['notes_seances']).date()
    notes = list(
        Presence.objects.filter(eleve=eleve, seance__date__gte=seuil_notes_date)
        .exclude(
            note_hifz__isnull=True, note_muraja3a__isnull=True,
            note_tilawa__isnull=True, note_mouwazaba__isnull=True,
        )
        .select_related('seance__groupe')
        .order_by('-seance__date', '-seance__heure')[:LIMITE_FETCH]
    )
    evenements_notes = [
        {
            'texte': _('تقييم جديد لحصة %(groupe)s') % {'groupe': p.seance.groupe.nom},
            'url': reverse('eleve_seances'),
            'date': _datetime_seance(p.seance),
        }
        for p in notes
        if _datetime_seance(p.seance) > seuils['notes_seances']
    ]

    # DocumentEleve.pour_eleve() (refonte du 2026-08-30) recalcule le ciblage
    # dynamique 'tous'/'categorie'/'specifique' à chaque appel — voir son
    # __doc__ — jamais un simple eleve.documents_cartable figé.
    docs = list(
        DocumentEleve.pour_eleve(eleve).filter(date_ajout__gt=seuils['cartable'])
        .order_by('-date_ajout')[:LIMITE_FETCH]
    )
    evenements_cartable = [
        {'texte': _('ملف جديد في حقيبتك: %(titre)s') % {'titre': d.titre or _('بدون عنوان')}, 'url': reverse('eleve_cartable'), 'date': d.date_ajout}
        for d in docs
    ]

    # Retard de paiement (chantier du 2026-09-01) — traité comme les autres
    # types : « nouveau » tant que l'élève n'a pas visité sa page de paiement
    # DEPUIS que le cycle est devenu échu (payments.views.eleve_paiements
    # appelle marquer_visite(user, 'paiements_retard')). L'évènement est
    # horodaté à `cycle.date_echeance` : visiter la page marque le seuil à
    # maintenant -> l'échéance (passée) repasse sous le seuil -> le badge se
    # vide. Un NOUVEAU cycle qui repasse en retard plus tard (élève toujours
    # pas à jour) relance la notification, exactement comme un nouvel examen
    # ou un nouveau fichier. L'état « en retard » lui-même reste visible en
    # permanence sur la page de paiement / la page متأخرون عن الدفع (مدير),
    # ce n'est que le badge 🔔 qui s'éteint après lecture.
    from payments.cycles import cycle_courant, cycle_est_en_retard

    cycle_paiement = cycle_courant(eleve)
    evenements_retard_paiement = []
    if cycle_est_en_retard(cycle_paiement):
        echeance_dt = timezone.make_aware(
            datetime.datetime.combine(cycle_paiement.date_echeance, datetime.time())
        )
        if echeance_dt > seuils['paiements_retard']:
            evenements_retard_paiement = [{
                'texte': _('لقد تأخّرت عن دفع اشتراكك — يرجى إرسال إثبات الدفع في أقرب وقت'),
                'url': reverse('eleve_paiements'),
                'date': echeance_dt,
            }]

    groupes = []
    if evenements_retard_paiement:
        groupes.append({'icone': '⚠️', 'label': _('دفع متأخر'), 'evenements': evenements_retard_paiement})
    if evenements_examens:
        groupes.append({'icone': '📝', 'label': _('اختبارات جديدة'), 'evenements': evenements_examens[:limite]})
    if evenements_notes:
        groupes.append({'icone': '📋', 'label': _('تقييمات جديدة على حصصك'), 'evenements': evenements_notes[:limite]})
    if evenements_cartable:
        groupes.append({'icone': '🎒', 'label': _('ملفات جديدة في حقيبتك'), 'evenements': evenements_cartable[:limite]})

    total = (
        len(evenements_retard_paiement)
        + len(evenements_examens) + len(evenements_notes) + len(evenements_cartable)
    )
    return _trier_groupes_par_recence(groupes), total


def notifications_prof(prof, user, limite=LIMITE_PAR_GROUPE):
    """(groupes, total) pour le panneau 🔔 côté prof — même patron que
    notifications_eleve ci-dessus. 2 requêtes (evaluations reçues + hakiba)."""
    from django.db.models import Q
    from accounts.models import ElementHakiba
    from evaluations.models import Evaluation

    seuils = _seuils(user, ['evaluations_recues', 'hakiba'])

    evaluations = list(
        Evaluation.objects.filter(prof=prof, date__gt=seuils['evaluations_recues'])
        .select_related('seance__groupe').order_by('-date')[:LIMITE_FETCH]
    )
    evenements_evaluations = [
        {
            'texte': _('تقييم جديد من المؤطر على حصة %(groupe)s') % {'groupe': e.seance.groupe.nom},
            'url': reverse('evaluations_prof_recues'),
            'date': e.date,
        }
        for e in evaluations
    ]

    elements = list(
        ElementHakiba.objects.filter(date_ajout__gt=seuils['hakiba'])
        .filter(Q(tous_les_profs=True) | Q(profs_cibles=prof))
        .distinct().order_by('-date_ajout')[:LIMITE_FETCH]
    )
    evenements_hakiba = [
        {'texte': _('ملف جديد في حقيبة الأستاذ: %(titre)s') % {'titre': el.titre or _('بدون عنوان')}, 'url': reverse('prof_hakiba'), 'date': el.date_ajout}
        for el in elements
    ]

    groupes = []
    if evenements_evaluations:
        groupes.append({'icone': '🧭', 'label': _('تقييمات جديدة من المؤطر'), 'evenements': evenements_evaluations[:limite]})
    if evenements_hakiba:
        groupes.append({'icone': '📁', 'label': _('ملفات جديدة في حقيبة الأستاذ'), 'evenements': evenements_hakiba[:limite]})

    total = len(evenements_evaluations) + len(evenements_hakiba)
    return _trier_groupes_par_recence(groupes), total


def notifications_superviseur(user, limite=LIMITE_PAR_GROUPE):
    """(groupes, total) pour le panneau 🔔 côté مؤطر (superviseur) — Chantier
    du 2026-08-31. UN SEUL déclencheur : un nouvel élément déposé dans la
    حقيبة الأستاذ par la direction (مدير/مشرف), exactement comme le groupe
    'hakiba' de notifications_prof ci-dessus, à une différence près : le مؤطر
    voit TOUS les éléments sans distinction de ciblage (voir dashboard.views.
    superviseur_hakiba.__doc__ — la حقيبة est un contenu informationnel de
    l'administration, pas une donnée rattachée à un prof précis), donc AUCUN
    filtre Q(tous_les_profs=True) | Q(profs_cibles=...) ici, contrairement au
    prof.

    `cle` = 'hakiba', LA MÊME que le prof : DerniereVisiteNotification est
    keyée par (user, cle), pas juste par cle — le repère de lecture du مؤطر
    reste donc le sien (posé par sa propre visite de superviseur_hakiba, voir
    marquer_visite là-bas), la visite d'un prof ne le marque jamais lu pour
    un مؤطر et inversement. 1 requête."""
    from accounts.models import ElementHakiba

    seuils = _seuils(user, ['hakiba'])

    elements = list(
        ElementHakiba.objects.filter(date_ajout__gt=seuils['hakiba'])
        .order_by('-date_ajout')[:LIMITE_FETCH]
    )
    evenements_hakiba = [
        {'texte': _('ملف جديد في حقيبة الأستاذ: %(titre)s') % {'titre': el.titre or _('بدون عنوان')}, 'url': reverse('superviseur_hakiba'), 'date': el.date_ajout}
        for el in elements
    ]

    groupes = []
    if evenements_hakiba:
        groupes.append({'icone': '📁', 'label': _('ملفات جديدة في حقيبة الأستاذ'), 'evenements': evenements_hakiba[:limite]})

    return _trier_groupes_par_recence(groupes), len(evenements_hakiba)


def notifications_direction(user, limite=LIMITE_LISTE_PLATE):
    """(groupes, total) pour le panneau 🔔 côté مدير/مشرف (Chantier du
    2026-08-24 ; refonte de la présentation le 2026-09-02).

    PRÉSENTATION — LISTE PLATE (révision du 2026-09-02, option (iii) validée
    explicitement) : `groupes` contient AU PLUS UN pseudo-groupe sans `label`,
    dont `evenements` est la fusion de TOUS les types ci-dessous, triée par
    `date` STRICTEMENT décroissante (le plus récent en tête). Chaque évènement
    porte une clé `icone` (rendue en tête de ligne côté template). AUCUN
    regroupement par type — décision prise pour garantir à la fois « le plus
    récent d'abord » ET « aucune demande ancienne reléguée hors de vue dans un
    groupe du bas » (le regroupement + tri par récence du groupe enterrait les
    inscriptions anciennes non traitées, cf. incident du 2026-09-02). Les
    panneaux élève/prof/مؤطر, eux, restent groupés par type
    (_trier_groupes_par_recence).

    BADGE ≠ PANNEAU (révision du 2026-09-02, décision explicite) — la cloche
    direction est un vrai CENTRE de notifications, pas un simple flux
    d'inédits :
      * `total` (le badge rouge sur l'icône) = uniquement les évènements NON
        LUS, c.-à-d. postérieurs à la dernière visite de leur page cible
        (marquer_visite). Visiter la page vide donc le badge de ce type.
      * `groupes[0]['evenements']` (le contenu du panneau) = TOUTE demande
        encore en attente, lue ou non, triée par date. Le panneau ne se vide
        JAMAIS tant qu'il reste quelque chose à traiter ; visiter la page ne
        retire rien de la liste (contrairement aux panneaux élève/prof, où
        chaque évènement est par construction non lu). Chaque évènement porte
        `non_lu` (bool) pour un marquage visuel côté template.

    ÉVÉNEMENTS FUSIONNÉS — 2 événements possibles :

    1. Nouvelle demande d'inscription élève (InscriptionEleve.
    date_soumission, auto_now_add — même garantie anti-fausse-notification
    que le reste du module, voir docstring en tête de fichier), qu'elle
    vienne du wizard public (registration.views, cree_par=None) OU de
    l'ajout manuel Directeur/مشرف (dashboard.views.admin_eleve_ajouter_
    manuel, cree_par=request.user) — inscrire_eleve() est le point de
    création UNIQUE pour les deux chemins (voir registration.utils.
    inscrire_eleve.__doc__), donc AUCUNE distinction de source n'est
    nécessaire ici : une seule requête couvre les deux.

    Un seul `cle` ('demandes_inscription') PARTAGÉ par مدير ET مشرف : les
    deux rôles pointent vers la même page cible (admin_inscriptions, voir
    dashboard.views.admin_inscriptions) et le même besoin — chacun garde
    NÉANMOINS son propre repère de lecture individuel, DerniereVisiteNotification
    étant déjà keyée par (user, cle) et pas juste par cle : la visite de
    l'un ne marque jamais "lu" pour l'autre.

    1bis. Nouvelle candidature PROF encore en attente de la pré-validation
    étape 1 (InscriptionProf.statut='en_attente', date_soumission
    auto_now_add — même garantie anti-fausse-notification que le reste du
    module). مدير UNIQUEMENT : cette pré-validation est @role_required('admin')
    (voir admin_valider_prof/admin_rejeter_prof), le مشرف n'agit qu'à
    l'étape 2 sur les 'validee_directeur' (groupe 2 ci-dessous) — lui
    montrer aussi les 'en_attente' serait du bruit sur lequel il ne peut
    rien faire. `cle` DÉDIÉE 'demandes_inscription_prof', PAS la
    'demandes_inscription' des élèves : repère de lecture distinct, pour
    que visiter la fiche d'un élève ne fasse pas disparaître les
    notifications profs et inversement (même précision que le correctif du
    2026-08-25). Marquée lue par admin_inscriptions (liste mixte) ET
    admin_inscription_prof_detail (fiche), exactement comme le couple
    liste/fiche du groupe 1. Mène vers la fiche (admin_inscription_prof_
    detail), comme le groupe 1.

    2. Candidature prof pré-validée par le مدير, en attente de la
    validation finale du مشرف (InscriptionProf.statut='validee_directeur')
    — Fonctionnalité 3 (2026-08-27, chantier annoncé mais volontairement
    reporté au 2026-08-24, voir l'ancienne version de cette docstring).
    مشرف UNIQUEMENT (jamais مدير : c'est lui qui déclenche cette transition,
    rien ne l'attend en retour) — filtré ici sur `user.role`, pas sur un
    `cle` séparé par rôle (inutile, un seul rôle le voit jamais). Repose sur
    InscriptionProf.date_validee_directeur, un horodatage DÉDIÉ posé par
    dashboard.views.admin_valider_prof/admin_prof_ajouter_manuel au moment
    exact de la transition (voir son docstring : jamais date_soumission,
    souvent bien antérieur si le dossier traînait en 'en_attente'). Mène vers
    la FICHE du candidat concerné (mshrif_inscription_prof_detail), comme le
    groupe 1 et le groupe 1bis ci-dessus — révision du 2026-09-02 (avant :
    lien vers la liste mshrif_inscriptions_profs, jugé trop indirect). La
    fiche détail appelle marquer_visite(user, 'profs_en_attente_validation')
    au même titre que la liste, donc lire la fiche vide bien le badge.

    3. Demande de changement de halaka par un élève (courses.models.
    DemandeChangementHalaka, statut='en_attente') — Fonctionnalité 4
    (2026-08-27). Visible par مدير ET مشرف (contrairement au groupe 2 :
    "un seul des deux rôles suffit pour trancher, peu importe lequel" —
    décision explicite du client), même `cle` partagée que le groupe 1
    ('demandes_inscription' NON réutilisée ici, un `cle` dédié
    'demandes_changement_halaka' — repère de lecture distinct, une visite
    de admin_inscriptions ne doit jamais marquer celui-ci comme lu). Mène
    vers la LISTE (admin_demandes_changement_halaka), même décision que le
    groupe 2 ci-dessus."""
    from inscriptions.models import InscriptionEleve, InscriptionProf
    from courses.models import DemandeChangementHalaka
    from payments.cycles import eleves_en_retard

    cles = ['demandes_inscription', 'demandes_changement_halaka', 'paiements_retard_eleves']
    if user.role == 'mshrif':
        cles.append('profs_en_attente_validation')
    if user.role == 'admin':
        cles.append('demandes_inscription_prof')
    seuils = _seuils(user, cles)

    # Chaque évènement : {texte, url, date, icone, non_lu}. `non_lu` = créé /
    # transité APRÈS la dernière visite de sa page cible (seuil) — c'est LUI
    # qui alimente le badge. Le panneau, lui, liste TOUT ce qui est encore en
    # attente, lu ou non (voir docstring : BADGE ≠ PANNEAU).
    evenements = []

    # 1. Demandes d'inscription élève en attente (مدير + مشرف).
    for d in (
        InscriptionEleve.objects.filter(statut='en_attente')
        .order_by('-date_soumission')[:LIMITE_FETCH]
    ):
        evenements.append({
            'texte': _('طلب تسجيل جديد: %(nom)s') % {'nom': d.nom},
            'url': reverse('admin_inscription_eleve_detail', args=[d.id]),
            'date': d.date_soumission,
            'icone': '📝',
            'non_lu': d.date_soumission > seuils['demandes_inscription'],
        })

    # 1bis. Nouvelles candidatures prof en attente de pré-validation étape 1,
    # مدير UNIQUEMENT (voir docstring).
    if user.role == 'admin':
        for p in (
            InscriptionProf.objects.filter(statut='en_attente')
            .order_by('-date_soumission')[:LIMITE_FETCH]
        ):
            evenements.append({
                'texte': _('طلب تسجيل أستاذ جديد: %(nom)s %(prenom)s') % {'nom': p.nom, 'prenom': p.prenom},
                'url': reverse('admin_inscription_prof_detail', args=[p.id]),
                'date': p.date_soumission,
                'icone': '👨‍🏫',
                'non_lu': p.date_soumission > seuils['demandes_inscription_prof'],
            })

    # 2. Candidatures prof pré-validées par le مدير, en attente du تصديق final
    # du مشرف, مشرف UNIQUEMENT (voir docstring). date_validee_directeur peut
    # être NULL sur d'anciens dossiers -> repli sur date_soumission pour le
    # tri d'affichage, et jamais « non lu » dans ce cas (rien de daté à comparer).
    if user.role == 'mshrif':
        for p in (
            InscriptionProf.objects.filter(statut='validee_directeur')
            .order_by('-date_validee_directeur', '-date_soumission')[:LIMITE_FETCH]
        ):
            evenements.append({
                'texte': _('طلب أستاذ بانتظار تصديقك: %(nom)s %(prenom)s') % {'nom': p.nom, 'prenom': p.prenom},
                'url': reverse('mshrif_inscription_prof_detail', args=[p.id]),
                'date': p.date_validee_directeur or p.date_soumission,
                'icone': '👨‍🏫',
                'non_lu': bool(
                    p.date_validee_directeur
                    and p.date_validee_directeur > seuils['profs_en_attente_validation']
                ),
            })

    # 3. Demandes de changement de halaka en attente (مدير + مشرف).
    url_changement_halaka = reverse('admin_demandes_changement_halaka')
    for d in (
        DemandeChangementHalaka.objects.filter(statut='en_attente')
        .select_related('eleve__user').order_by('-date_demande')[:LIMITE_FETCH]
    ):
        evenements.append({
            'texte': _('طلب تغيير حلقة: %(nom)s') % {'nom': d.eleve.user.get_full_name()},
            'url': url_changement_halaka,
            'date': d.date_demande,
            'icone': '🔄',
            'non_lu': d.date_demande > seuils['demandes_changement_halaka'],
        })

    # 4. Élèves en retard de paiement (مدير + مشرف). eleves_en_retard() renvoie
    # déjà la liste complète ; on la garde entière, `non_lu` = échéance
    # postérieure à la dernière visite de la page متأخرون عن الدفع.
    url_retards = reverse('paiements_retards')
    for eleve, cycle in eleves_en_retard():
        echeance_dt = timezone.make_aware(
            datetime.datetime.combine(cycle.date_echeance, datetime.time())
        )
        evenements.append({
            'texte': _('%(nom)s متأخر عن دفع الاشتراك') % {'nom': eleve.user.get_full_name()},
            'url': url_retards,
            'date': echeance_dt,
            'icone': '⚠️',
            'non_lu': echeance_dt > seuils['paiements_retard_eleves'],
        })

    evenements.sort(key=lambda e: e['date'], reverse=True)

    # Badge = uniquement les non-lus (se vide quand toutes les pages cibles ont
    # été visitées). Panneau = toute la liste triée, plafonnée à `limite`.
    total = sum(1 for e in evenements if e['non_lu'])
    groupes = (
        [{'icone': '', 'label': '', 'evenements': evenements[:limite]}]
        if evenements else []
    )
    return groupes, total
