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
    """(groupes, total) pour la cloche 🔔 côté مدير/مشرف (Chantier du
    2026-08-24 ; refontes successives des 2026-09-02).

    CENTRE DE NOTIFICATIONS AVEC HISTORIQUE (révision du 2026-09-02, option
    validée explicitement) :

      * `groupes` contient AU PLUS UN pseudo-groupe sans `label` — le template
        rend alors une LISTE PLATE (pas d'en-tête de type), triée par `date`
        STRICTEMENT décroissante (le plus récent en tête).

      * Le panneau montre l'HISTORIQUE : chaque demande d'inscription élève /
        candidature prof / changement de halaka apparaît, qu'elle soit encore
        en attente OU déjà traitée (acceptée/refusée). Chaque évènement porte :
          - `icone`       : 📝 / 👨‍🏫 / 🔄 / ⚠️ (type)
          - `statut_label`, `statut_ton` : pastille de statut côté template
            ('attente' ambre, 'ok' vert, 'ko' rouge, 'neutre' gris)
          - `non_lu`      : True UNIQUEMENT si l'évènement est encore
            actionnable par CE rôle ET postérieur à la dernière visite de sa
            page cible (marquer_visite). C'est `non_lu` qui alimente le badge.

      * `total` (le badge rouge) = nombre de `non_lu`. Visiter la page cible
        d'un type (marquer_visite) éteint le badge de ce type MAIS ne retire
        RIEN de la liste — les demandes restent visibles, juste sans surlignage.

      * Profondeur : les LIMITE_FETCH évènements les plus récents par source,
        fusionnés puis retriés ; le dropdown en affiche `limite`
        (LIMITE_LISTE_PLATE), la page « عرض الكل » LIMITE_FETCH.

    Les panneaux élève/prof/مؤطر, eux, restent un simple flux d'inédits
    groupé par type (chaque ligne par construction non lue) — voir
    _trier_groupes_par_recence.

    SOURCES :

    1. InscriptionEleve — TOUT statut (en_attente / valide / rejete). `cle`
    de lecture 'demandes_inscription', partagée مدير+مشرف (repère individuel
    par (user, cle)). `non_lu` sur 'en_attente' seulement. Lien : la fiche
    admin_inscription_eleve_detail (accepte tous les statuts).

    2. InscriptionProf — TOUT statut.
       - مدير : voit tous les statuts, `non_lu` sur 'en_attente' (`cle`
         'demandes_inscription_prof'). Lien : admin_inscription_prof_detail
         (aucune garde de statut).
       - مشرف : voit 'validee_directeur' + finaux, MASQUE 'en_attente' (pas
         encore de son ressort). `non_lu` sur 'validee_directeur' (`cle`
         'profs_en_attente_validation', horodatage date_validee_directeur).
         Lien : mshrif_inscription_prof_detail pour 'validee_directeur'
         (seul statut que cette vue accepte), sinon la liste
         mshrif_inscriptions_profs.

    3. DemandeChangementHalaka — TOUT statut (en_attente / validee / refusee),
    مدير + مشرف, `cle` 'demandes_changement_halaka'. `non_lu` sur 'en_attente'.
    Lien : la liste admin_demandes_changement_halaka.

    4. Élèves en retard de paiement (payments.cycles.eleves_en_retard) — pas
    d'historique propre (un élève quitte la liste dès qu'il paie), donc
    seulement l'état courant. `non_lu` = échéance postérieure à la dernière
    visite de paiements_retards (`cle` 'paiements_retard_eleves'). Pas de
    pastille de statut."""
    from inscriptions.models import InscriptionEleve, InscriptionProf
    from courses.models import DemandeChangementHalaka
    from payments.cycles import eleves_en_retard

    cles = ['demandes_inscription', 'demandes_changement_halaka', 'paiements_retard_eleves']
    if user.role == 'mshrif':
        cles.append('profs_en_attente_validation')
    if user.role == 'admin':
        cles.append('demandes_inscription_prof')
    seuils = _seuils(user, cles)

    est_mshrif = user.role == 'mshrif'

    # (libellé, ton) de pastille par statut — construits ici (jamais au niveau
    # module : `_` = gettext non-lazy, doit être résolu à chaque requête). Tous
    # les libellés réutilisent des msgid DÉJÀ traduits FR/EN (voir catalogue).
    statut_eleve = {
        'en_attente': (_('قيد الانتظار'), 'attente'),
        'valide': (_('مقبول'), 'ok'),
        'rejete': (_('مرفوض'), 'ko'),
    }
    statut_prof = {
        'en_attente': (_('قيد الانتظار'), 'attente'),
        'validee_directeur': (_('قيد الانتظار'), 'attente'),
        'valide': (_('مقبول نهائياً'), 'ok'),
        'rejete': (_('مرفوض'), 'ko'),
    }
    statut_halaka = {
        'en_attente': (_('قيد الانتظار'), 'attente'),
        'validee': (_('مقبولة'), 'ok'),
        'refusee': (_('مرفوضة'), 'ko'),
    }

    evenements = []

    # 1. Inscriptions élève — historique complet.
    for d in InscriptionEleve.objects.order_by('-date_soumission')[:LIMITE_FETCH]:
        libelle, ton = statut_eleve.get(d.statut, (d.get_statut_display(), 'neutre'))
        evenements.append({
            'texte': _('طلب تسجيل جديد: %(nom)s') % {'nom': d.nom},
            'url': reverse('admin_inscription_eleve_detail', args=[d.id]),
            'date': d.date_soumission,
            'icone': '📝',
            'statut_label': libelle,
            'statut_ton': ton,
            'non_lu': d.statut == 'en_attente' and d.date_soumission > seuils['demandes_inscription'],
        })

    # 2. Candidatures prof — historique complet. مشرف masque 'en_attente'.
    url_liste_profs_mshrif = reverse('mshrif_inscriptions_profs')
    for p in InscriptionProf.objects.order_by('-date_soumission')[:LIMITE_FETCH]:
        if est_mshrif and p.statut == 'en_attente':
            continue
        libelle, ton = statut_prof.get(p.statut, (p.get_statut_display(), 'neutre'))
        if est_mshrif:
            non_lu = bool(
                p.statut == 'validee_directeur'
                and p.date_validee_directeur
                and p.date_validee_directeur > seuils['profs_en_attente_validation']
            )
            url = (
                reverse('mshrif_inscription_prof_detail', args=[p.id])
                if p.statut == 'validee_directeur' else url_liste_profs_mshrif
            )
        else:
            non_lu = p.statut == 'en_attente' and p.date_soumission > seuils['demandes_inscription_prof']
            url = reverse('admin_inscription_prof_detail', args=[p.id])
        evenements.append({
            'texte': _('طلب تسجيل أستاذ جديد: %(nom)s %(prenom)s') % {'nom': p.nom, 'prenom': p.prenom},
            'url': url,
            'date': p.date_soumission,
            'icone': '👨‍🏫',
            'statut_label': libelle,
            'statut_ton': ton,
            'non_lu': non_lu,
        })

    # 3. Demandes de changement de halaka — historique complet.
    url_changement_halaka = reverse('admin_demandes_changement_halaka')
    for d in (
        DemandeChangementHalaka.objects.select_related('eleve__user')
        .order_by('-date_demande')[:LIMITE_FETCH]
    ):
        libelle, ton = statut_halaka.get(d.statut, (d.get_statut_display(), 'neutre'))
        evenements.append({
            'texte': _('طلب تغيير حلقة: %(nom)s') % {'nom': d.eleve.user.get_full_name()},
            'url': url_changement_halaka,
            'date': d.date_demande,
            'icone': '🔄',
            'statut_label': libelle,
            'statut_ton': ton,
            'non_lu': d.statut == 'en_attente' and d.date_demande > seuils['demandes_changement_halaka'],
        })

    # 4. Élèves en retard de paiement (état courant seulement, pas d'historique).
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
            'statut_label': '',
            'statut_ton': '',
            'non_lu': echeance_dt > seuils['paiements_retard_eleves'],
        })

    evenements.sort(key=lambda e: e['date'], reverse=True)

    total = sum(1 for e in evenements if e['non_lu'])
    groupes = (
        [{'icone': '', 'label': '', 'evenements': evenements[:limite]}]
        if evenements else []
    )
    return groupes, total
