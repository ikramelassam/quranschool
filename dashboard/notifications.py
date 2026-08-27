"""Panneau 🔔 الإشعارات (Chantier notifications du 2026-08-19, étendu au
مدير/مشرف le 2026-08-24) — Option A validée explicitement avec
l'utilisateur : calcul à la volée, jamais un nouveau modèle stockant une
ligne par notification individuelle.

SCOPE VOLONTAIRE : ce module n'est appelé QUE depuis les pages d'accueil de
chaque rôle — dashboard_eleve/dashboard_prof à l'origine (Chantier du
2026-08-19), dashboard_admin/dashboard_mshrif depuis le 2026-08-24 (voir
notifications_direction ci-dessous) — jamais depuis un context processor
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
from django.urls import reverse
from django.utils import timezone

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


def marquer_visite(user, cle):
    """Marque le type `cle` comme lu MAINTENANT pour `user` — à appeler
    depuis chaque vue "page cible" listée dans accounts.models.
    DerniereVisiteNotification.__doc__ (examens_eleve_liste, eleve_seances,
    eleve_cartable, evaluations_prof_recues, prof_hakiba), juste avant le
    render final (jamais avant, au cas où la vue redirige plus tôt sans
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

    seuils = _seuils(user, ['examens', 'notes_seances', 'cartable'])
    groupes_eleve = eleve.groupes.all()

    examens = list(
        Examen.objects.filter(
            groupe__in=groupes_eleve, statut='publie',
            date_publication__gt=seuils['examens'],
        ).order_by('-date_publication')[:LIMITE_FETCH]
    )
    evenements_examens = [
        {'texte': f'اختبار جديد: {e.titre}', 'url': reverse('examens_eleve_liste'), 'date': e.date_publication}
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
            'texte': f'تقييم جديد لحصة {p.seance.groupe.nom}',
            'url': reverse('eleve_seances'),
            'date': _datetime_seance(p.seance),
        }
        for p in notes
        if _datetime_seance(p.seance) > seuils['notes_seances']
    ]

    docs = list(
        eleve.documents_cartable.filter(date_ajout__gt=seuils['cartable'])
        .order_by('-date_ajout')[:LIMITE_FETCH]
    )
    evenements_cartable = [
        {'texte': f'ملف جديد في حقيبتك: {d.titre or "بدون عنوان"}', 'url': reverse('eleve_cartable'), 'date': d.date_ajout}
        for d in docs
    ]

    groupes = []
    if evenements_examens:
        groupes.append({'icone': '📝', 'label': 'اختبارات جديدة', 'evenements': evenements_examens[:limite]})
    if evenements_notes:
        groupes.append({'icone': '📋', 'label': 'تقييمات جديدة على حصصك', 'evenements': evenements_notes[:limite]})
    if evenements_cartable:
        groupes.append({'icone': '🎒', 'label': 'ملفات جديدة في حقيبتك', 'evenements': evenements_cartable[:limite]})

    total = len(evenements_examens) + len(evenements_notes) + len(evenements_cartable)
    return groupes, total


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
            'texte': f'تقييم جديد من المؤطر على حصة {e.seance.groupe.nom}',
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
        {'texte': f'ملف جديد في حقيبة الأستاذ: {el.titre or "بدون عنوان"}', 'url': reverse('prof_hakiba'), 'date': el.date_ajout}
        for el in elements
    ]

    groupes = []
    if evenements_evaluations:
        groupes.append({'icone': '🧭', 'label': 'تقييمات جديدة من المؤطر', 'evenements': evenements_evaluations[:limite]})
    if evenements_hakiba:
        groupes.append({'icone': '📁', 'label': 'ملفات جديدة في حقيبة الأستاذ', 'evenements': evenements_hakiba[:limite]})

    total = len(evenements_evaluations) + len(evenements_hakiba)
    return groupes, total


def notifications_direction(user, limite=LIMITE_PAR_GROUPE):
    """(groupes, total) pour le panneau 🔔 côté مدير/مشرف (Chantier du
    2026-08-24) — même patron que notifications_eleve/notifications_prof
    ci-dessus. 2 événements possibles :

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
    souvent bien antérieur si le dossier traînait en 'en_attente'). Mène
    vers la LISTE (mshrif_inscriptions_profs), pas vers chaque fiche
    individuelle (décision explicite de ce chantier, contrairement au
    groupe 1 ci-dessus qui pointe chaque évènement vers sa propre fiche)."""
    from inscriptions.models import InscriptionEleve, InscriptionProf

    cles = ['demandes_inscription']
    if user.role == 'mshrif':
        cles.append('profs_en_attente_validation')
    seuils = _seuils(user, cles)

    demandes = list(
        InscriptionEleve.objects.filter(
            statut='en_attente', date_soumission__gt=seuils['demandes_inscription'],
        ).order_by('-date_soumission')[:LIMITE_FETCH]
    )
    evenements_demandes = [
        {
            'texte': f'طلب تسجيل جديد: {d.nom}',
            'url': reverse('admin_inscription_eleve_detail', args=[d.id]),
            'date': d.date_soumission,
        }
        for d in demandes
    ]

    evenements_profs_en_attente = []
    if user.role == 'mshrif':
        profs_en_attente = list(
            InscriptionProf.objects.filter(
                statut='validee_directeur', date_validee_directeur__gt=seuils['profs_en_attente_validation'],
            ).order_by('-date_validee_directeur')[:LIMITE_FETCH]
        )
        url_liste_profs = reverse('mshrif_inscriptions_profs')
        evenements_profs_en_attente = [
            {
                'texte': f'طلب أستاذ بانتظار تصديقك: {p.nom} {p.prenom}',
                'url': url_liste_profs,
                'date': p.date_validee_directeur,
            }
            for p in profs_en_attente
        ]

    groupes = []
    if evenements_demandes:
        groupes.append({
            'icone': '📝', 'label': 'طلبات تسجيل جديدة', 'evenements': evenements_demandes[:limite],
        })
    if evenements_profs_en_attente:
        groupes.append({
            'icone': '👨‍🏫', 'label': 'طلبات أساتذة بانتظار تصديقك',
            'evenements': evenements_profs_en_attente[:limite],
        })

    return groupes, len(evenements_demandes) + len(evenements_profs_en_attente)
