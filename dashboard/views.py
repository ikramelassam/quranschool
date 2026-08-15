import datetime
import logging
import secrets

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.views.decorators.cache import never_cache
from accounts.decorators import role_required
from accounts.services import (
    invalider_sessions_utilisateur as _invalider_sessions_utilisateur,
    archiver_eleve, reactiver_eleve, archiver_prof, reactiver_prof,
    profs_pour_filtre, eleves_pour_filtre,
)
from core.utils import paginer
from inscriptions.models import InscriptionEleve

JOURS_SEMAINE_AR = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']

logger = logging.getLogger(__name__)

# Mot de passe temporaire assigné à tout nouveau compte (élève, prof, superviseur)
# lors de sa création. L'admin le communique manuellement (affiché sur la page
# après validation) en attendant que l'envoi d'email soit fiable en production.
# L'utilisateur est forcé de le changer à sa première connexion (voir
# accounts.middleware.ForcerChangementMotDePasseMiddleware).
# Généré aléatoirement à CHAQUE création de compte (voir generer_mot_de_passe_temporaire
# ci-dessous) — un mot de passe fixe partagé par tous les comptes permettrait à
# quiconque le connaissant de se connecter à la place du titulaire avant lui.
ALPHABET_MOT_DE_PASSE_TEMPORAIRE = 'ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
# Exclut 0/O et 1/l/I (ambigus à l'œil) — ce mot de passe est souvent recopié
# à la main ou lu à voix haute par un utilisateur non technique.


def generer_mot_de_passe_temporaire(longueur=10):
    """Mot de passe temporaire aléatoire et imprévisible, propre à ce compte.
    secrets (pas random): générateur cryptographiquement sûr, adapté à un
    secret de sécurité plutôt qu'à un simple tirage aléatoire. Réservé
    désormais aux flux مدير/مشرف uniquement (mot de passe oublié, self-
    service) — voir generer_mot_de_passe_sequentiel ci-dessous pour
    élève/prof/مؤطر (Points 13/14/17, décision du directeur du 2026-08-05)."""
    return ''.join(secrets.choice(ALPHABET_MOT_DE_PASSE_TEMPORAIRE) for _ in range(longueur))


def generer_mot_de_passe_sequentiel():
    """Mot de passe "zidanieilman<N>@@" pour élève/prof/مؤطر — remplace la
    génération aléatoire pour ces 3 rôles (décision du directeur du
    2026-08-05). N vient de accounts.models.CompteurMotDePasseSequentiel :
    un compteur UNIQUE partagé entre les 3 catégories (pas un compteur par
    rôle — plus simple à maintenir, aucun risque de collision, le format ne
    code de toute façon aucune information de rôle), garanti strictement
    croissant et atomique via l'auto-incrément natif de la base."""
    from accounts.models import CompteurMotDePasseSequentiel
    ligne = CompteurMotDePasseSequentiel.objects.create()
    return f'zidanieilman{ligne.id}@@'


URL_PLATEFORME = 'app.zidanieilman.com'
# Domaine affiché tel quel dans les messages d'acceptation (email + WhatsApp)
# -- Chantier du 2026-08-15 (refonte du texte d'acceptation, style fourni par
# le client) : domaine FIXE demandé explicitement, plutôt que
# request.build_absolute_uri (qui dépend de l'hôte de la requête -- pas
# garanti pointer vers ce sous-domaine précis, ex. en local).


def envoyer_email_bienvenue(request, email, password_temp, prenom_nom):
    """Envoie le message d'acceptation (identifiants de connexion) au nouvel
    utilisateur (élève, prof ou مؤطر) par email. Retourne True si l'email est
    parti, False sinon -- une panne SMTP (identifiants, réseau...) ne doit
    jamais empêcher la création du compte, qui a déjà eu lieu au moment de
    l'appel.

    Texte mis à jour le 2026-08-15 (refonte du message d'acceptation, style
    fourni par le client -- voir aussi construire_message_acceptation_
    whatsapp, même texte pour le canal WhatsApp). `request` n'est plus
    utilisé pour construire le lien de connexion (voir URL_PLATEFORME,
    domaine fixe désormais) mais reste dans la signature pour ne pas devoir
    modifier les 3 appelants (admin_valider_eleve, mshrif_valider_prof_final,
    admin_superviseur_ajouter) pour un changement qui ne concerne que le
    contenu du message."""
    try:
        send_mail(
            subject='مرحباً بك في منصة زدني علماً - معلومات الدخول',
            message=(
                f'السلام عليكم ورحمة الله وبركاته،\n\n'
                f'حياك الله {prenom_nom}،\n\n'
                f'يسرنا إخبارك بأنه تم قبولك للانضمام إلى منصة زدني علماً، ونسأل الله أن يوفقك ويبارك في جهودك.\n\n'
                f'يمكنك الدخول إلى المنصة عبر الرابط:\n\n'
                f'{URL_PLATEFORME}\n\n'
                f'بيانات الدخول الخاصة بك:\n\n'
                f'البريد الإلكتروني:\n'
                f'{email}\n\n'
                f'كلمة المرور:\n'
                f'{password_temp}\n\n'
                f'نسعد بانضمامك إلى زدني علماً، ونسأل الله أن يجعلها خطوة مباركة ونافعة.\n\n'
                f'بارك الله فيكم.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Échec de l'envoi de l'email de bienvenue à %s", email)
        return False


def envoyer_email_notification_changement_email(request, ancien_email, nouvel_email, prenom_nom):
    """Notifie le NOUVEL email qu'il vient d'être associé à ce compte suite à un changement.
    Retourne True si l'email est parti, False sinon — le changement d'email lui-même a déjà
    été enregistré en base au moment de l'appel, une panne SMTP ne doit jamais transformer
    ça en 500 (voir envoyer_email_bienvenue pour le même principe)."""
    from django.urls import reverse

    lien_connexion = request.build_absolute_uri(reverse('login'))
    try:
        send_mail(
            subject='تم تغيير البريد الإلكتروني لحسابك - زدني علماً',
            message=(
                f'مرحباً {prenom_nom},\n\n'
                f'نُعلمك بأنه تم تغيير البريد الإلكتروني المرتبط بحسابك على منصة زدني علماً '
                f'من {ancien_email} إلى {nouvel_email}.\n\n'
                f'يمكنك الآن تسجيل الدخول بهذا البريد الجديد:\n{lien_connexion}\n\n'
                f'إذا لم تطلب هذا التغيير، يرجى التواصل فوراً مع إدارة المنصة.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[nouvel_email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Échec de l'envoi de l'email de notification de changement à %s", nouvel_email)
        return False



def _next_valide(request, defaut='admin_eleves'):
    """Récupère un ?next= sûr (chemin interne au dashboard admin uniquement),
    sinon retombe sur une page par défaut."""
    from django.urls import reverse
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if next_url.startswith('/dashboard/admin/'):
        return next_url
    return reverse(defaut)


def _base_template_admin_ou_mshrif(request):
    """Pages admin réutilisées en lecture seule par المشرف (listes/fiches élèves-profs,
    évaluations) : garde son propre sidebar/couleur plutôt que celui du مدير."""
    return 'dashboard/base_mshrif.html' if request.user.role == 'mshrif' else 'dashboard/base_admin.html'


def _contexte_base_mshrif(request):
    """Contexte commun à toute page utilisant base_mshrif.html (badge sidebar du nombre de
    candidatures en attente) — un seul endroit à mettre à jour plutôt que de répéter la
    requête dans chacune des vues qui rendent ce sidebar."""
    if request.user.role != 'mshrif':
        return {}
    from inscriptions.models import InscriptionProf
    return {'nb_demandes_en_attente': InscriptionProf.objects.filter(statut='validee_directeur').count()}


def _verifier_conflit_email(email):
    """Vérifie si un User existe déjà pour cet email et s'il a un profil Eleve/Prof.
    Utilisé pour bloquer la validation d'une inscription en cas de conflit
    (voir bug connu #5 du CLAUDE.md: validation silencieuse sans création de compte).

    Correctif du 2026-08-10 (audit du chantier partage d'email) : depuis que plusieurs
    comptes élève peuvent partager un même email (voir admin_valider_eleve), cette
    fonction ne peut plus se contenter d'inspecter le PREMIER compte trouvé
    (l'ancien `.first()`) — un email peut désormais correspondre à plusieurs comptes
    dont les états diffèrent (ex: le compte le plus ancien archivé, un autre bien
    actif). Bug confirmé par test réel avant ce correctif : un 1er compte archivé
    masquait un 2e compte actif du même groupe familial et bloquait à tort la
    candidature d'un 3e membre. `user`/`orphelin`/`archive` restent calculés sur le
    même compte "représentatif" qu'avant (le premier par id, ordre inchangé) pour ne
    rien changer aux messages d'erreur existants (toujours utilisés tels quels côté
    prof, qui ne bénéficie d'aucun bypass) — seul le nouveau champ
    `partage_eleve_possible` regarde tout le groupe, pour la décision de bypass élève."""
    from accounts.models import Eleve, Prof
    from django.contrib.auth import get_user_model
    User = get_user_model()

    comptes_existants = list(User.objects.filter(email=email).order_by('pk'))
    if not comptes_existants:
        return {'conflit': False, 'user': None, 'orphelin': False, 'archive': False, 'partage_eleve_possible': False}

    # .objects (non filtré) volontairement pour chaque compte: un profil archivé
    # compte comme "a un profil" (donc pas orphelin) — l'archivage ne supprime
    # jamais le compte, voir accounts.services.archiver_eleve/archiver_prof.
    infos = []
    for u in comptes_existants:
        eleve = Eleve.objects.filter(user=u).first()
        prof = Prof.objects.filter(user=u).first()
        a_un_profil = eleve is not None or prof is not None
        est_archive = (eleve and eleve.statut == 'archive') or (prof and prof.statut == 'archive')
        infos.append({'user': u, 'orphelin': not a_un_profil, 'archive': bool(est_archive)})

    # Compte représentatif pour les champs historiques (messages d'erreur inchangés) :
    # le premier par id, exactement comme l'ancien `.first()`.
    principal = infos[0]

    # Bypass élève : possible dès qu'AU MOINS UN compte du groupe est un élève actif
    # (profil Eleve existant, non archivé) — peu importe l'état des AUTRES comptes
    # partageant cet email.
    partage_eleve_possible = any(
        info['user'].role == 'eleve' and not info['orphelin'] and not info['archive']
        for info in infos
    )

    return {
        'conflit': True,
        'user': principal['user'],
        'orphelin': principal['orphelin'],
        'archive': principal['archive'],
        'partage_eleve_possible': partage_eleve_possible,
    }


@role_required('prof')
def dashboard_prof(request):
    from accounts.models import Prof
    from courses.models import Groupe, Seance
    from courses.utils import navigation_mois_et_semaines, regrouper_seances_a_venir
    from django.utils import timezone

    try:
        prof = Prof.objects.get(user=request.user)
    except Prof.DoesNotExist:
        return redirect('login')

    groupes = Groupe.objects.filter(prof=prof)
    aujourdhui = timezone.localdate()

    # "آخر الحصص" — refonte agenda groupée (Tâche du 2026-08-05), même
    # traitement que "السجل السابق" côté مؤطر : réutilise
    # courses.utils.navigation_mois_et_semaines (extraite de
    # dashboard_superviseur) plutôt que de dupliquer la logique une 2e fois.
    # Aperçu immédiat = 3 dernières séances passées à plat, exclues ensuite du
    # regroupement par semaine pour ne jamais les afficher deux fois.
    toutes_seances_prof = Seance.objects.filter(groupe__prof=prof).select_related('groupe')
    apercu_seances = list(
        toutes_seances_prof.filter(date__lt=aujourdhui).order_by('-date', '-heure')[:3]
    )
    seances_hors_apercu = toutes_seances_prof.exclude(id__in=[s.id for s in apercu_seances])
    nav = navigation_mois_et_semaines(seances_hors_apercu, request, aujourdhui)

    # Encart dédié "prochaine séance" (Tâche 10/écart 1 du 2026-07-25) — même
    # intention que dashboard_eleve.prochaine_seance : identifiable d'un coup
    # d'œil, plutôt que noyée dans "آخر الحصص" qui mélange passé/futur trié
    # par date décroissante.
    prochaine_seance = Seance.objects.filter(
        groupe__prof=prof, date__gte=aujourdhui
    ).exclude(statut='terminee').select_related('groupe').order_by('date', 'heure').first()

    # ===== "القادمة" — section manquante (Point 1 du chantier groupé du
    # 2026-08-05) : avant ce correctif, seule "الحصة القادمة" (une séance
    # unique) était visible côté prof, rien ne montrait le reste des séances
    # à venir. Réutilise courses.utils.regrouper_seances_a_venir, partagée
    # avec dashboard_superviseur (voir sa docstring pour le détail). Comme
    # côté مؤطر : prochaine_seance retirée du "بقية هذا الأسبوع" pour ne pas
    # l'afficher deux fois, sans fausser nb_semaine_courante.
    a_venir = regrouper_seances_a_venir(toutes_seances_prof, aujourdhui)
    id_a_exclure = prochaine_seance.id if prochaine_seance else None
    bucket_semaine_courante = [
        s for s in a_venir['bucket_semaine_courante'] if s.id != id_a_exclure
    ]

    context = {
        'prof': prof,
        'groupes': groupes,
        'apercu_seances': apercu_seances,
        'bucket_semaine_courante': bucket_semaine_courante,
        'semaine_suivante': a_venir['semaine_suivante'],
        'mois_suivants': a_venir['mois_suivants'],
        'nb_semaine_courante': a_venir['nb_semaine_courante'],
        'semaines_agenda': nav['semaines'],
        'mois_nav_date': nav['mois_nav_date'],
        'mois_nav_param': nav['mois_nav_param'],
        'mois_precedent_param': nav['mois_precedent_param'],
        'mois_suivant_param': nav['mois_suivant_param'],
        'mois_suivant_autorise': nav['mois_suivant_autorise'],
        'prochaine_seance': prochaine_seance,
        'aujourdhui': aujourdhui,
        'total_eleves': sum(g.eleves.exclude(statut='archive').count() for g in groupes),
        'total_groupes': groupes.count(),
        # Remplace l'ancien len(seances[:5]) — comptait au mieux 5 même si le
        # prof avait un historique bien plus long ; total réel, cohérent avec
        # le fait que la liste ci-dessous n'est plus plafonnée à 5 non plus.
        'total_seances_passees': toutes_seances_prof.filter(date__lt=aujourdhui).count(),
    }
    return render(request, 'dashboard/prof.html', context)


@role_required('prof')
def prof_groupes(request):
    from accounts.models import Prof
    from courses.models import Groupe

    prof = get_object_or_404(Prof, user=request.user)
    groupes = Groupe.objects.filter(prof=prof).prefetch_related('eleves__user')

    return render(request, 'dashboard/prof_groupes.html', {
        'prof': prof,
        'groupes': groupes,
    })


@role_required('prof')
def prof_groupe_detail(request, groupe_id):
    from accounts.models import Prof
    from courses.models import Groupe

    prof = get_object_or_404(Prof, user=request.user)
    groupe = get_object_or_404(Groupe, id=groupe_id, prof=prof)

    return render(request, 'dashboard/prof_groupe_detail.html', {
        'prof': prof,
        'groupe': groupe,
        'eleves': groupe.eleves.all(),
    })


@role_required('prof')
def prof_seances(request):
    from accounts.models import Prof
    from courses.models import Groupe, Seance
    from django.utils import timezone

    prof = get_object_or_404(Prof, user=request.user)
    aujourdhui = timezone.localdate()
    groupe_id = request.GET.get('groupe', '')

    toutes_seances = Seance.objects.filter(groupe__prof=prof).select_related('groupe').prefetch_related('groupe__eleves__user')
    if groupe_id:
        toutes_seances = toutes_seances.filter(groupe_id=groupe_id)

    # Une séance "en retard" est une séance passée jamais remplie par le prof
    # (statut resté à 'planifiee' au lieu de passer à 'terminee' via
    # prof_presence_sauvegarder). Non paginée volontairement: le prof doit
    # voir tout son retard d'un coup, sans avoir à changer de page.
    seances_retard = toutes_seances.filter(
        date__lt=aujourdhui, statut='planifiee'
    ).order_by('-date', '-heure')

    seances_aujourdhui = toutes_seances.filter(date=aujourdhui).order_by('heure')
    seances_a_venir_qs = toutes_seances.filter(date__gt=aujourdhui).order_by('date', 'heure')
    nb_a_venir = seances_a_venir_qs.count()
    # On plafonne l'affichage des séances à venir: un emploi du temps récurrent
    # peut en générer des dizaines à l'avance, ce qui recréerait le scroll
    # qu'on cherche justement à éviter. Le prof les verra de toute façon
    # apparaître ici au fur et à mesure qu'elles se rapprochent.
    seances_a_venir = seances_a_venir_qs[:10]
    # Reste des séances à venir au-delà des 10 déjà visibles — rendu caché
    # dans le template et déplié en JS au clic sur le compteur, sans
    # rechargement (horizon de génération borné à 8 semaines).
    seances_a_venir_extra = seances_a_venir_qs[10:]
    seances_passees_traitees = toutes_seances.filter(date__lt=aujourdhui).exclude(
        statut='planifiee'
    ).order_by('-date', '-heure')

    return render(request, 'dashboard/prof_seances.html', {
        'prof': prof,
        'aujourdhui': aujourdhui,
        'total_seances': toutes_seances.count(),
        'nb_retard': seances_retard.count(),
        'seances_retard': seances_retard,
        'seances_aujourdhui': seances_aujourdhui,
        'seances_a_venir': seances_a_venir,
        'seances_a_venir_extra': seances_a_venir_extra,
        'nb_a_venir': nb_a_venir,
        'seances_passees_traitees': paginer(request, seances_passees_traitees, 15),
        'groupes': Groupe.objects.filter(prof=prof).order_by('nom'),
        'filtres': {'groupe': groupe_id},
    })


# ==================== LIEN DE SÉANCE (Point 15, Tâche du 2026-08-04) ====================

@role_required('admin', 'mshrif')
def admin_reglage_lien_seance(request):
    """Réglage global de la marge (minutes avant/après) pendant laquelle le
    lien de réunion d'une séance est cliquable — مدير ET مشرف, même patron
    que admin_gestion_inscriptions."""
    from courses.models import get_reglage_lien_seance

    reglage = get_reglage_lien_seance()
    if request.method == 'POST':
        try:
            marge_avant = int(request.POST.get('marge_avant_minutes', 0))
            marge_apres = int(request.POST.get('marge_apres_minutes', 0))
        except ValueError:
            messages.error(request, 'يرجى إدخال أرقام صحيحة.')
            return redirect('admin_reglage_lien_seance')
        if marge_avant < 0 or marge_apres < 0:
            messages.error(request, 'لا يمكن أن يكون الهامش رقماً سالباً.')
            return redirect('admin_reglage_lien_seance')
        reglage.marge_avant_minutes = marge_avant
        reglage.marge_apres_minutes = marge_apres
        reglage.derniere_modification_par = request.user
        reglage.save()
        messages.success(request, 'تم تحديث إعدادات هامش رابط الحصص بنجاح.')
        return redirect('admin_reglage_lien_seance')

    context = {
        'reglage': reglage,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_reglage_lien_seance.html', context)


@role_required('admin')
def admin_reglage_retention_chat(request):
    """Réglage de la durée de conservation des messages du chat (Point 12/35 du
    chantier chat) — مدير UNIQUEMENT (contrairement à la plupart des réglages
    voisins comme admin_reglage_lien_seance, ouverts à مشرف aussi) : le مشرف
    n'a de toute façon aucun accès au chat lui-même, donc pas de raison qu'il
    en règle la rétention. Même patron que ci-dessus (singleton, formulaire
    simple)."""
    from chat.models import get_configuration_chat

    config = get_configuration_chat()
    if request.method == 'POST':
        try:
            duree = int(request.POST.get('duree_retention_jours', 0))
        except ValueError:
            messages.error(request, 'يرجى إدخال رقم صحيح.')
            return redirect('admin_reglage_retention_chat')
        if duree < 1:
            messages.error(request, 'يجب أن تكون المدة يوماً واحداً على الأقل.')
            return redirect('admin_reglage_retention_chat')
        config.duree_retention_jours = duree
        config.derniere_modification_par = request.user
        config.save()
        messages.success(request, 'تم تحديث مدة الاحتفاظ برسائل الدردشة بنجاح.')
        return redirect('admin_reglage_retention_chat')

    return render(request, 'dashboard/admin_reglage_retention_chat.html', {
        'config': config,
        'base_template': 'dashboard/base_admin.html',
    })


@role_required('admin', 'mshrif', 'superviseur', 'prof', 'eleve')
def rejoindre_seance(request, seance_id):
    """Passerelle serveur pour le lien de réunion d'une séance — jamais un
    lien direct vers l'URL externe côté template : même si le bouton semble
    "actif" côté HTML, la fenêtre [début - marge_avant, fin + marge_apres]
    est revalidée ICI à CHAQUE accès (courses.utils.lien_seance_est_actif,
    qui relit l'horaire de la séance et le réglage de marge en base à chaque
    appel) avant toute redirection vers le lien réel. Un accès direct à
    cette URL hors fenêtre ne redirige jamais, quel que soit l'état du
    bouton côté client."""
    from accounts.models import Prof, Eleve, Superviseur
    from courses.models import Seance
    from courses.utils import lien_seance_est_actif

    seance = get_object_or_404(Seance, id=seance_id)

    role = request.user.role
    if role in ('admin', 'mshrif'):
        autorise = True
    elif role == 'prof':
        autorise = Prof.objects.filter(user=request.user, groupes=seance.groupe).exists()
    elif role == 'eleve':
        autorise = Eleve.objects.filter(user=request.user, groupes=seance.groupe).exists()
    elif role == 'superviseur':
        autorise = (
            seance.groupe.prof_id is not None
            and Superviseur.objects.filter(user=request.user, profs_assignes=seance.groupe.prof).exists()
        )
    else:
        autorise = False

    if not autorise:
        from django.http import Http404
        raise Http404

    if not lien_seance_est_actif(seance):
        BASE_TEMPLATE_PAR_ROLE = {
            'admin': 'dashboard/base_admin.html',
            'mshrif': 'dashboard/base_mshrif.html',
            'superviseur': 'dashboard/base_superviseur.html',
            'prof': 'dashboard/base_prof.html',
            'eleve': 'dashboard/base_eleve.html',
        }
        return render(request, 'dashboard/lien_seance_indisponible.html', {
            'seance': seance,
            'base_template': BASE_TEMPLATE_PAR_ROLE[role],
        })

    return redirect(seance.groupe.lien_reunion)


@role_required('prof')
def prof_seance_detail(request, seance_id):
    from accounts.models import Prof
    from courses.models import Seance, Presence, CritereEleve, NotePresence
    from courses.quran_data import SOURATES

    prof = get_object_or_404(Prof, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof=prof)
    # Un élève suspendu/archivé ne doit plus apparaître dans les feuilles de
    # présence à venir (voir Tâche 3 du 2026-07-25) — son historique passé
    # n'est pas affecté, seule cette liste "à remplir maintenant" l'exclut.
    eleves = seance.groupe.eleves.filter(statut='actif')

    # Critères dynamiques (Point 7, Tâche du 2026-08-04) — remplacent les 4
    # champs fixes note_hifz/note_muraja3a/note_tilawa/note_mouwazaba.
    criteres_actifs = list(CritereEleve.objects.filter(est_actif=True).order_by('ordre'))

    # Django templates ne peuvent pas faire presences[eleve.id] (lookup par variable).
    # On construit donc directement la liste (élève, présence) dans la vue.
    presences_par_eleve = {p.eleve_id: p for p in Presence.objects.filter(seance=seance)}
    # Même limitation pour les notes par critère : {(eleve_id, critere_id): note}.
    notes_par_cellule = {
        (n.presence.eleve_id, n.critere_id): n.note
        for n in NotePresence.objects.filter(presence__seance=seance).select_related('presence')
    }
    eleves_presences = []
    premiere_non_remplie_trouvee = False
    for eleve in eleves:
        presence = presences_par_eleve.get(eleve.id)
        # Seule la première carte non encore remplie s'ouvre automatiquement —
        # les autres restent repliées pour garder le formulaire rapide sur mobile.
        ouvrir_par_defaut = not presence and not premiere_non_remplie_trouvee
        if not presence:
            premiere_non_remplie_trouvee = True
        notes_criteres = [
            {'critere': c, 'note': notes_par_cellule.get((eleve.id, c.id))}
            for c in criteres_actifs
        ]
        eleves_presences.append({
            'eleve': eleve,
            'presence': presence,
            'ouvrir_par_defaut': ouvrir_par_defaut,
            'notes_criteres': notes_criteres,
        })

    return render(request, 'dashboard/prof_seance_detail.html', {
        'prof': prof,
        'seance': seance,
        'eleves_presences': eleves_presences,
        'criteres_actifs': criteres_actifs,
        'sourates': SOURATES,
        'statut_choices': Presence.STATUT_CHOICES,
        # Une séance restée 'planifiee' après le délai de 24h n'est pas forcément
        # vide : un seul élève avec une plage d'ayat invalide suffit à empêcher le
        # passage à 'terminee', même si tous les autres ont bien été enregistrés
        # (voir prof_presence_sauvegarder). Le bandeau doit refléter cette nuance
        # plutôt que de dire "rien n'a été fait" quand ce n'est pas le cas.
        'nb_presences_enregistrees': len(presences_par_eleve),
        'nb_total_eleves': len(eleves),
    })


@role_required('prof')
def prof_presence_sauvegarder(request, seance_id):
    from accounts.models import Prof, Eleve
    from courses.models import Seance, Presence

    prof = get_object_or_404(Prof, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof=prof)

    if not seance.modifiable_par_prof:
        if seance.statut == 'terminee':
            messages.error(request, 'تم تقييم هذه الحصة بالفعل — لم يعد بالإمكان تعديلها.')
        elif not seance.evaluable_par_prof:
            messages.error(request, 'لم تنتهِ هذه الحصة بعد — لا يمكن تقييمها قبل انتهائها فعلياً.')
        else:
            messages.error(request, 'انتهت مهلة تقييم هذه الحصة (24 ساعة من بدايتها) — لم يعد بالإمكان تقييمها.')
        return redirect('prof_seance_detail', seance_id=seance.id)

    if request.method == 'POST':
        from courses.models import CritereEleve, NotePresence

        # Critères dynamiques (Tâche du 2026-08-04, Point 7) — remplacent les 4
        # champs fixes note_hifz/note_muraja3a/note_tilawa/note_mouwazaba
        # (gelés désormais, jamais plus réécrits depuis cette vue, conservés
        # uniquement pour l'historique antérieur à cette migration). Champ HTML
        # attendu par élève : note_critere_<critere.id>_<eleve.id>.
        criteres_actifs = list(CritereEleve.objects.filter(est_actif=True).order_by('ordre'))

        # Un élève suspendu/archivé ne doit plus apparaître dans les feuilles de
        # présence à venir (voir Tâche 3 du 2026-07-25) — son historique passé
        # n'est pas affecté, seule cette liste "à remplir maintenant" l'exclut.
        eleves = seance.groupe.eleves.filter(statut='actif')
        erreurs = []
        for eleve in eleves:
            statut = request.POST.get(f'statut_{eleve.id}', 'absent')
            sourate_memorisee = request.POST.get(f'sourate_memo_{eleve.id}') or None
            ayah_debut_memorisation = request.POST.get(f'ayah_debut_memo_{eleve.id}') or None
            ayah_fin_memorisation = request.POST.get(f'ayah_fin_memo_{eleve.id}') or None
            sourate_revisee = request.POST.get(f'sourate_rev_{eleve.id}') or None
            ayah_debut_revision = request.POST.get(f'ayah_debut_rev_{eleve.id}') or None
            ayah_fin_revision = request.POST.get(f'ayah_fin_rev_{eleve.id}') or None
            remarque = request.POST.get(f'remarque_{eleve.id}', '')
            consigne_memorisation = request.POST.get(f'consigne_memo_{eleve.id}', '')
            consigne_revision = request.POST.get(f'consigne_rev_{eleve.id}', '')

            # Critères dynamiques /20 (Tâche du 2026-08-04, Point 7) — remplacent
            # l'ancienne échelle qualitative pour toute nouvelle évaluation
            # (note_memorisation/note_revision ne sont plus jamais réécrits
            # depuis cette vue, voir Presence.note_memorisation).
            notes_brutes = {
                critere.id: request.POST.get(f'note_critere_{critere.id}_{eleve.id}', '')
                for critere in criteres_actifs
            }

            # Une plage d'ayat inversée (fin < début) donnerait un nombre d'ayat
            # mémorisés/révisés négatif ou nul silencieusement (voir Presence.nb_ayat_memorises) —
            # on refuse d'enregistrer cette ligne plutôt que d'accepter une valeur incohérente.
            # De même, une fin au-delà du nombre réel d'ayat de la sourate choisie
            # (ex: ayah 300 pour الفاتحة qui n'en a que 7) doit être refusée — voir
            # _ayah_depasse_sourate et le commentaire de courses/quran_data.py qui
            # annonçait cette validation sans qu'elle ait jamais été implémentée.
            ligne_invalide = False
            if _ayah_incoherentes(ayah_debut_memorisation, ayah_fin_memorisation):
                erreurs.append(
                    f'{eleve.user.get_full_name()}: آية نهاية الحفظ ({ayah_fin_memorisation}) '
                    f'يجب أن تكون أكبر من أو تساوي آية البداية ({ayah_debut_memorisation}).'
                )
                ligne_invalide = True
            elif _ayah_depasse_sourate(sourate_memorisee, ayah_fin_memorisation):
                erreurs.append(
                    f'{eleve.user.get_full_name()}: آية نهاية الحفظ ({ayah_fin_memorisation}) '
                    f'تتجاوز عدد آيات {_nom_sourate(sourate_memorisee)} '
                    f'({_total_ayat_sourate(sourate_memorisee)} آية).'
                )
                ligne_invalide = True
            if _ayah_incoherentes(ayah_debut_revision, ayah_fin_revision):
                erreurs.append(
                    f'{eleve.user.get_full_name()}: آية نهاية المراجعة ({ayah_fin_revision}) '
                    f'يجب أن تكون أكبر من أو تساوي آية البداية ({ayah_debut_revision}).'
                )
                ligne_invalide = True
            elif _ayah_depasse_sourate(sourate_revisee, ayah_fin_revision):
                erreurs.append(
                    f'{eleve.user.get_full_name()}: آية نهاية المراجعة ({ayah_fin_revision}) '
                    f'تتجاوز عدد آيات {_nom_sourate(sourate_revisee)} '
                    f'({_total_ayat_sourate(sourate_revisee)} آية).'
                )
                ligne_invalide = True

            # Les critères /20 et les 2 consignes ne sont obligatoires que pour
            # un élève marqué présent — rien à noter/consigner pour une absence
            # (voir Tâche 9 du 2026-07-25).
            notes_validees = {}
            if statut == 'present':
                for critere in criteres_actifs:
                    valeur_brute = notes_brutes[critere.id]
                    if not valeur_brute:
                        erreurs.append(f'{eleve.user.get_full_name()}: يجب إدخال علامة {critere.nom_ar}.')
                        ligne_invalide = True
                        continue
                    try:
                        valeur = int(valeur_brute)
                    except ValueError:
                        erreurs.append(f'{eleve.user.get_full_name()}: علامة {critere.nom_ar} غير صحيحة.')
                        ligne_invalide = True
                        continue
                    if not (1 <= valeur <= 20):
                        erreurs.append(f'{eleve.user.get_full_name()}: علامة {critere.nom_ar} يجب أن تكون بين 1 و20.')
                        ligne_invalide = True
                        continue
                    notes_validees[critere.id] = valeur
                if not consigne_memorisation.strip():
                    erreurs.append(f'{eleve.user.get_full_name()}: يجب تحديد "المطلوب حفظه".')
                    ligne_invalide = True
                if not consigne_revision.strip():
                    erreurs.append(f'{eleve.user.get_full_name()}: يجب تحديد "المطلوب مراجعته".')
                    ligne_invalide = True
            else:
                # notes_validees reste vide -> toute note existante est effacée
                # ci-dessous (élève absent = rien à noter, même s'il avait déjà
                # des notes suite à une correction de statut).
                consigne_memorisation = ''
                consigne_revision = ''

            if ligne_invalide:
                continue

            presence, _ = Presence.objects.update_or_create(
                seance=seance,
                eleve=eleve,
                defaults={
                    'statut': statut,
                    'sourate_memorisee': sourate_memorisee,
                    'ayah_debut_memorisation': ayah_debut_memorisation,
                    'ayah_fin_memorisation': ayah_fin_memorisation,
                    'sourate_revisee': sourate_revisee,
                    'ayah_debut_revision': ayah_debut_revision,
                    'ayah_fin_revision': ayah_fin_revision,
                    'remarque': remarque,
                    'consigne_memorisation': consigne_memorisation,
                    'consigne_revision': consigne_revision,
                }
            )

            # Notes par critère dynamique (Point 7) — table de jonction dédiée,
            # plus les 4 champs fixes sur Presence (gelés, voir plus haut).
            for critere in criteres_actifs:
                if critere.id in notes_validees:
                    NotePresence.objects.update_or_create(
                        presence=presence, critere=critere,
                        defaults={'note': notes_validees[critere.id]},
                    )
                else:
                    NotePresence.objects.filter(presence=presence, critere=critere).delete()

        if erreurs:
            for erreur in erreurs:
                messages.error(request, erreur)
            messages.warning(request, 'تم حفظ باقي الطلاب. صحّح الآيات أعلاه ثم احفظ مجدداً لإتمام حصة الطلاب المذكورين.')
            return redirect('prof_seance_detail', seance_id=seance.id)

        seance.remarque_generale = request.POST.get('remarque_generale', '')
        seance.statut = 'terminee'
        seance.save()
        messages.success(request, 'تم حفظ الحضور والتقييمات بنجاح.')
        return redirect('prof_seances')

    return redirect('prof_seance_detail', seance_id=seance_id)


def _ayah_incoherentes(debut, fin):
    """True si les deux valeurs sont fournies et que fin < début (plage inversée)."""
    if not debut or not fin:
        return False
    try:
        return int(fin) < int(debut)
    except ValueError:
        return False


def _ayah_depasse_sourate(sourate, fin):
    """True si l'ayah de fin dépasse le nombre réel d'ayat de la sourate choisie
    (ex: ayah 300 pour الفاتحة qui n'en a que 7) — voir courses/quran_data.py,
    dont le commentaire annonçait cette validation sans qu'elle ait jamais été
    implémentée."""
    if not sourate or not fin:
        return False
    from courses.quran_data import SOURATES_NB_AYAT
    try:
        total_ayat = SOURATES_NB_AYAT.get(int(sourate))
        fin_int = int(fin)
    except ValueError:
        return False
    return bool(total_ayat) and fin_int > total_ayat


def _nom_sourate(sourate):
    from courses.quran_data import SOURATES_NOMS
    try:
        return SOURATES_NOMS.get(int(sourate), '')
    except ValueError:
        return ''


def _total_ayat_sourate(sourate):
    from courses.quran_data import SOURATES_NB_AYAT
    try:
        return SOURATES_NB_AYAT.get(int(sourate), '')
    except ValueError:
        return ''


@role_required('prof')
def prof_emploi(request):
    from accounts.models import Prof
    from courses.models import Groupe
    from courses.utils import JOUR_INDEX, JOURS_SEMAINE_DISPO, generer_heures_grille, _heures_couvertes
    from django.utils import timezone

    prof = get_object_or_404(Prof, user=request.user)
    groupes = Groupe.objects.filter(prof=prof, statut='actif').select_related('creneau')

    # Grille jours×heures réelle (Tâche 12 du 2026-07-25) — remplace la liste
    # de cartes, même patron que _grille_disponibilites.html (jours/heures
    # déjà factorisés dans courses.utils, réutilisés tels quels). Une cellule
    # par (jour, heure), jamais de lookup dict[jour, heure] dans le template
    # (impossible en Django templates) — donc construite ici sous forme de
    # lignes de cellules déjà dans l'ordre des colonnes.
    occupation = {}
    for groupe in groupes:
        creneau = groupe.creneau
        if not creneau:
            continue
        for jour, debut, fin in [
            (creneau.jour_1, creneau.heure_debut_1, creneau.heure_fin_1),
            (creneau.jour_2, creneau.heure_debut_2, creneau.heure_fin_2),
        ]:
            for h in _heures_couvertes(debut, fin):
                occupation[(jour, h)] = groupe

    jour_actuel = {v: k for k, v in JOUR_INDEX.items()}[timezone.localdate().weekday()]

    lignes_grille = []
    for heure in generer_heures_grille():
        lignes_grille.append({
            'heure': heure,
            'cellules': [
                {'jour_code': jour_code, 'groupe': occupation.get((jour_code, heure))}
                for jour_code, _ in JOURS_SEMAINE_DISPO
            ],
        })

    return render(request, 'dashboard/prof_emploi.html', {
        'prof': prof,
        'groupes': groupes,
        'jours': JOURS_SEMAINE_DISPO,
        'lignes_grille': lignes_grille,
        'jour_actuel': jour_actuel,
    })


@role_required('prof')
def prof_disponibilites(request):
    from accounts.models import Prof
    from courses.models import DisponibiliteProf, DemandeModificationDisponibilite
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    prof = get_object_or_404(Prof, user=request.user)
    demande_en_attente = DemandeModificationDisponibilite.objects.filter(prof=prof, statut='en_attente').first()

    matrice_active = set(
        f'{j}_{h.strftime("%H:%M")}'
        for j, h in DisponibiliteProf.objects.filter(prof=prof).values_list('jour_semaine', 'heure_debut')
    )

    if request.method == 'POST':
        nouvelle_matrice = request.POST.getlist('dispo')
        if demande_en_attente:
            demande_en_attente.nouvelle_matrice = nouvelle_matrice
            demande_en_attente.save()
        else:
            DemandeModificationDisponibilite.objects.create(prof=prof, nouvelle_matrice=nouvelle_matrice)
        messages.success(request, 'تم إرسال طلب تعديل الأوقات المتاحة للتدريس، بانتظار موافقة الإدارة.')
        return redirect('prof_disponibilites')

    valeurs_form = set(demande_en_attente.nouvelle_matrice) if demande_en_attente else matrice_active

    return render(request, 'dashboard/prof_disponibilites.html', {
        'demande_en_attente': demande_en_attente,
        'valeurs_actuelles': matrice_active,
        'valeurs_form': valeurs_form,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
    })


@role_required('prof')
def prof_profil(request):
    from accounts.models import Prof
    from courses.utils import calculer_remuneration_prof
    from django.contrib.auth import get_user_model
    User = get_user_model()
    prof = get_object_or_404(Prof, user=request.user)
    return render(request, 'dashboard/prof_profil.html', {
        'prof': prof,
        'superviseurs': prof.superviseurs.select_related('user').all(),
        'admins': User.objects.filter(role='admin'),
        'modifier_telephone': request.GET.get('modifier_telephone') == '1',
        # Montant affiché directement sur le profil (Tâche du 2026-08-05,
        # refonte visuelle) — même fonction que prof_remuneration, pas de
        # nouveau calcul dupliqué.
        'remuneration': calculer_remuneration_prof(prof),
    })


@role_required('prof')
def prof_remuneration(request):
    from accounts.models import Prof
    from courses.models import TarifRemuneration
    from courses.utils import calculer_remuneration_prof
    from django.utils import timezone

    prof = get_object_or_404(Prof, user=request.user)
    aujourdhui = timezone.localdate()
    # Volontairement: ni majoration_mensuelle ni aucune donnée de classement/
    # évaluation ne sont chargées ni passées ici — voir courses.utils.calculer_remuneration_prof.
    return render(request, 'dashboard/prof_remuneration.html', {
        'remuneration': calculer_remuneration_prof(prof),
        'tarifs': TarifRemuneration.objects.all().order_by('type_capacite', 'tranche_age'),
        'aujourdhui': aujourdhui,
    })


@role_required('prof')
def prof_charte(request):
    """Lecture seule + accusé de lecture du ميثاق التدريس côté prof — pas bloquant,
    un prof qui n'a pas encore coché garde l'accès normal au reste du site (voir le
    bandeau discret sur dashboard_prof)."""
    from accounts.models import Prof, get_charte
    from django.utils import timezone

    prof = get_object_or_404(Prof, user=request.user)

    if request.method == 'POST':
        prof.charte_acceptee = True
        prof.date_acceptation_charte = timezone.now()
        prof.save()
        messages.success(request, 'شكراً لك، تم تسجيل موافقتك على الميثاق.')
        return redirect('prof_charte')

    return render(request, 'dashboard/prof_charte.html', {
        'charte': get_charte(),
        'prof': prof,
    })


@role_required('prof')
def prof_hakiba(request):
    """Page d'atterrissage حقيبة الأستاذ — section "روابط ثابتة" (ميثاق التدريس +
    البرنامج العام, inchangés) + section "أضيفت من طرف الإدارة" listant les
    ElementHakiba qui concernent ce prof : soit ciblant tous les profs
    (tous_les_profs=True), soit le ciblant spécifiquement via profs_cibles
    (Tâche du 2026-08-04, Point 1 — refonte du 2026-08-05 : la gestion se
    fait désormais depuis la page centrale admin_hakiba_gestion, plus depuis
    la fiche individuelle du prof). Lecture seule pour le prof : aucune
    gestion possible depuis ici."""
    from django.db.models import Q
    from accounts.models import Prof, ElementHakiba

    prof = get_object_or_404(Prof, user=request.user)
    elements = ElementHakiba.objects.filter(
        Q(tous_les_profs=True) | Q(profs_cibles=prof)
    ).distinct().order_by('-date_ajout')
    return render(request, 'dashboard/prof_hakiba.html', {
        'elements_hakiba': elements,
    })


@role_required('prof', 'eleve', 'superviseur')
def programme_general_detail(request):
    """Lecture seule du البرنامج العام, édité par مدير/مشرف (voir
    admin_programme_general). Affichage conditionnel selon le rôle (voir Tâche 6b
    du 2026-07-25, complété Tâche 22 du 2026-07-26 pour مؤطر) :
    - élève : uniquement la version correspondant à son âge réel (même règle des
      18 ans que Tâche 1, courses.utils.tranche_age_depuis_naissance) ;
    - prof : la/les version(s) selon la tranche d'âge des élèves de ses groupes
      actifs (les deux si le prof enseigne aux deux tranches, ou si l'info est
      indéterminée faute d'élève avec âge connu — jamais rien caché sans raison) ;
    - مؤطر : même logique, agrégée sur tous ses profs assignés (Tâche 22) — plus
      "toujours les deux" comme avant, désormais cohérent avec prof/élève.
    """
    from accounts.models import get_programme_general, Prof
    from courses.utils import tranche_age_depuis_naissance

    programme = get_programme_general()
    montrer_enfants = True
    montrer_adultes = True

    def _tranches_enseignees_par(profs_qs):
        tranches = set()
        for prof in profs_qs:
            for groupe in prof.groupes.filter(statut='actif'):
                for eleve in groupe.eleves.filter(statut='actif').select_related('inscription'):
                    if eleve.inscription and eleve.inscription.date_naissance:
                        tranches.add(tranche_age_depuis_naissance(eleve.inscription.date_naissance))
        return tranches

    if request.user.role == 'eleve':
        from accounts.models import Eleve

        eleve = get_object_or_404(Eleve, user=request.user)
        if eleve.inscription and eleve.inscription.date_naissance:
            tranche = tranche_age_depuis_naissance(eleve.inscription.date_naissance)
            montrer_enfants = tranche == 'enfant'
            montrer_adultes = tranche == 'adulte'
        # Âge inconnu (dossier sans date de naissance) : les deux versions restent
        # affichées plutôt que de masquer silencieusement l'information.

    elif request.user.role == 'prof':
        prof = get_object_or_404(Prof, user=request.user)
        tranches_enseignees = _tranches_enseignees_par([prof])
        if tranches_enseignees:
            montrer_enfants = 'enfant' in tranches_enseignees
            montrer_adultes = 'adulte' in tranches_enseignees
        # Aucun élève avec âge connu (nouveau prof, groupes vides...) : les deux
        # versions restent affichées, même principe que pour l'élève ci-dessus.

    elif request.user.role == 'superviseur':
        from accounts.models import Superviseur

        superviseur = get_object_or_404(Superviseur, user=request.user)
        tranches_enseignees = _tranches_enseignees_par(superviseur.profs_assignes.all())
        if tranches_enseignees:
            montrer_enfants = 'enfant' in tranches_enseignees
            montrer_adultes = 'adulte' in tranches_enseignees
        # Aucun prof assigné, ou aucun élève avec âge connu chez eux : les deux
        # versions restent affichées, même principe que pour prof/élève.

    base_template = {
        'prof': 'dashboard/base_prof.html',
        'eleve': 'dashboard/base_eleve.html',
        'superviseur': 'dashboard/base_superviseur.html',
    }[request.user.role]

    return render(request, 'dashboard/programme_general_detail.html', {
        'programme': programme,
        'montrer_enfants': montrer_enfants,
        'montrer_adultes': montrer_adultes,
        'base_template': base_template,
    })


@role_required('admin', 'mshrif')
def admin_programme_general(request):
    """Édition du البرنامج العام — مدير ET مشرف désormais (élargi depuis مدير
    seul — voir Tâche 6b du 2026-07-25). Deux versions distinctes (أطفال/بالغون),
    chacune structurée en titre/intro/items comme UNE section de CharteEnseignement."""
    from accounts.models import get_programme_general

    programme = get_programme_general()
    if request.method == 'POST':
        programme.titre_enfants = request.POST.get('titre_enfants', '')
        programme.intro_enfants = request.POST.get('intro_enfants', '')
        programme.items_enfants = request.POST.get('items_enfants', '')
        programme.titre_adultes = request.POST.get('titre_adultes', '')
        programme.intro_adultes = request.POST.get('intro_adultes', '')
        programme.items_adultes = request.POST.get('items_adultes', '')
        programme.save()
        messages.success(request, 'تم تحديث البرنامج العام بنجاح.')
        return redirect('admin_programme_general')

    context = {
        'programme': programme,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_programme_general.html', context)


@role_required('admin', 'mshrif')
def admin_visibilite_prof(request):
    """Édition du réglage global de visibilité du profil prof côté élève —
    مدير ET مشرف, mêmes permissions que admin_programme_general (Tâche du
    2026-08-03, étendue le même jour à toutes les sections de la fiche, y
    compris le contact). Un seul réglage, lu uniquement par
    eleve_prof_detail.html au moment du rendu."""
    from accounts.models import get_visibilite_prof

    CHAMPS = [
        'afficher_contact', 'afficher_ville', 'afficher_certifications',
        'afficher_niveau_memorisation', 'afficher_type_eleve_preference',
        'afficher_langues', 'afficher_outils_communication',
        'afficher_parcours_scolaire', 'afficher_parcours_educatif',
        'afficher_travail_actuel',
    ]

    visibilite = get_visibilite_prof()
    if request.method == 'POST':
        for champ in CHAMPS:
            setattr(visibilite, champ, request.POST.get(champ) == '1')
        visibilite.save()
        messages.success(request, 'تم تحديث إعدادات الظهور بنجاح.')
        return redirect('admin_visibilite_prof')

    context = {
        'visibilite': visibilite,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_visibilite_prof.html', context)


@role_required('admin', 'mshrif')
def admin_gestion_inscriptions(request):
    """Ouverture/fermeture des inscriptions publiques par catégorie (élève
    adulte, élève enfant, prof) — مدير ET مشرف, même patron que
    admin_visibilite_prof (Tâche du 2026-08-04). N'affecte que la création de
    nouvelles candidatures (inscriptions.views.inscription_eleve_formulaire/
    inscription_prof) — jamais les candidatures déjà soumises ni leur
    traitement admin/مشرف."""
    from inscriptions.models import get_parametres_inscriptions

    parametres = get_parametres_inscriptions()
    if request.method == 'POST':
        parametres.ouverte_eleve_adulte = request.POST.get('ouverte_eleve_adulte') == '1'
        parametres.ouverte_eleve_enfant = request.POST.get('ouverte_eleve_enfant') == '1'
        parametres.ouverte_prof = request.POST.get('ouverte_prof') == '1'
        parametres.derniere_modification_par = request.user
        parametres.save()
        messages.success(request, 'تم تحديث إعدادات التسجيل بنجاح.')
        return redirect('admin_gestion_inscriptions')

    context = {
        'parametres': parametres,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_gestion_inscriptions.html', context)


@role_required('prof')
def prof_evaluations(request):
    """تقييماتي — liste de toutes les évaluations élève déjà soumises par ce prof
    (une Presence n'existe que si prof_presence_sauvegarder a réussi, donc toujours
    liée à une séance 'terminee'), filtrable par élève/groupe/plage de dates — même
    pattern que admin_evaluations (filtres + liste plate triée par date décroissante),
    réutilisé ici plutôt qu'inventé. Chaque ligne pointe vers prof_seance_detail, qui
    bascule déjà automatiquement en lecture seule verrouillée pour une séance
    'terminee' (voir Seance.modifiable_par_prof) — aucune nouvelle page de détail."""
    from accounts.models import Prof, Eleve
    from courses.models import Presence, Groupe

    prof = get_object_or_404(Prof, user=request.user)
    groupe_id = request.GET.get('groupe', '')
    eleve_id = request.GET.get('eleve', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    presences = Presence.objects.filter(seance__groupe__prof=prof).select_related(
        'eleve__user', 'seance__groupe'
    ).order_by('-seance__date', '-seance__heure')

    if groupe_id:
        presences = presences.filter(seance__groupe_id=groupe_id)
    if eleve_id:
        presences = presences.filter(eleve_id=eleve_id)
    if date_debut:
        presences = presences.filter(seance__date__gte=date_debut)
    if date_fin:
        presences = presences.filter(seance__date__lte=date_fin)

    # Regroupées par élève (Tâche 12 du 2026-07-25) — une liste chronologique
    # plate mélangeant tous les élèves ne dit rien sur la progression de
    # chacun ; un dict Python préserve l'ordre d'apparition (donc du plus
    # récemment évalué en premier, cohérent avec le tri -date déjà en place).
    blocs_par_eleve = {}
    for p in presences:
        bloc = blocs_par_eleve.setdefault(p.eleve_id, {'eleve': p.eleve, 'presences': []})
        bloc['presences'].append(p)

    def moyenne(valeurs):
        valeurs = [v for v in valeurs if v is not None]
        return round(sum(valeurs) / len(valeurs), 1) if valeurs else None

    for bloc in blocs_par_eleve.values():
        bloc['moyenne_hifz'] = moyenne([p.note_hifz for p in bloc['presences']])
        bloc['moyenne_muraja3a'] = moyenne([p.note_muraja3a for p in bloc['presences']])
        bloc['moyenne_tilawa'] = moyenne([p.note_tilawa for p in bloc['presences']])
        bloc['moyenne_mouwazaba'] = moyenne([p.note_mouwazaba for p in bloc['presences']])
        # Historique par séance potentiellement long sur une année scolaire —
        # limité à 10 + bouton "عرض الكل" (Tâche 22 Partie F du 2026-07-26),
        # même logique que suivi_paiements_eleves (toggle par bloc, id unique).
        bloc['presences_recentes'] = bloc['presences'][:10]
        bloc['presences_anciennes'] = bloc['presences'][10:]
        bloc['nb_presences_total'] = len(bloc['presences'])

    return render(request, 'dashboard/prof_evaluations.html', {
        # Liste des élèves (une carte par élève) — potentiellement longue si le
        # prof a beaucoup d'élèves, paginée comme le reste des listes du projet.
        'blocs_par_eleve': paginer(request, list(blocs_par_eleve.values()), 10),
        'groupes': Groupe.objects.filter(prof=prof).order_by('nom'),
        'eleves': Eleve.objects.filter(groupes__prof=prof).distinct().select_related('user').order_by('user__first_name'),
        'filtres': {
            'groupe': groupe_id,
            'eleve': eleve_id,
            'date_debut': date_debut,
            'date_fin': date_fin,
        },
    })


@role_required('prof')
def prof_bilans_mensuels(request):
    """Liste des élèves du prof pour le mois choisi, avec statut rempli/non rempli du
    bilan mensuel — point d'entrée pour remplir/consulter (voir bilan_mensuel_detail)."""
    from accounts.models import Prof, Eleve
    from courses.models import BilanMensuel
    from courses.utils import compter_absences_par_eleve
    from django.utils import timezone

    prof = get_object_or_404(Prof, user=request.user)
    mois = request.GET.get('mois', '')
    aujourdhui = timezone.localdate()
    if mois:
        annee, _, num_mois = mois.partition('-')
        annee, num_mois = int(annee), int(num_mois)
    else:
        annee, num_mois = aujourdhui.year, aujourdhui.month
        mois = f'{annee:04d}-{num_mois:02d}'
    mois_reference = datetime.date(annee, num_mois, 1)

    eleves = Eleve.actifs.filter(groupes__prof=prof).distinct().select_related('user').order_by('user__first_name')
    bilans = {b.eleve_id: b for b in BilanMensuel.objects.filter(prof=prof, mois_reference=mois_reference)}

    # حصيلة الغياب الشهرية (voir courses.utils.compter_absences_par_eleve) —
    # une seule requête groupée pour tous les élèves de la liste, pas une par
    # carte. Même définition d'absence que bilan_mensuel_detail (statut !=
    # 'present'), non filtrée par groupe (l'élève peut être absent d'une
    # séance d'un autre de ses groupes, comptée quand même — voir la
    # docstring du helper).
    absences = compter_absences_par_eleve([e.id for e in eleves], annee, num_mois)

    lignes = [
        {'eleve': eleve, 'bilan': bilans.get(eleve.id), 'nb_absences': absences.get(eleve.id, 0)}
        for eleve in eleves
    ]

    return render(request, 'dashboard/prof_bilans_mensuels.html', {
        'lignes': lignes,
        'mois': mois,
        'mois_reference': mois_reference,
    })


@role_required('prof', 'admin', 'superviseur', 'mshrif', 'eleve')
def bilan_mensuel_detail(request, eleve_id, mois):
    """Page de saisie/consultation d'un bilan mensuel — unique pour les 5 rôles
    (élève ajouté au Chantier du 2026-08-14, bilan d'absences — absent du
    décorateur jusque-là malgré la docstring d'origine qui prétendait "les
    3 autres rôles" en plus du prof, ce qui était déjà inexact) : le prof le
    crée/modifie (tant que modifiable_par_prof), les 4 autres rôles le
    consultent en lecture seule (le مؤطر scopé à ses profs assignés, comme
    pour le classement mensuel ; l'élève scopé à SON PROPRE bilan uniquement)."""
    from accounts.models import Eleve, Prof, Superviseur
    from courses.models import BilanMensuel
    from courses.utils import generer_brouillon_bilan_mensuel
    from django.http import HttpResponseForbidden

    eleve = get_object_or_404(Eleve, id=eleve_id)
    annee, _, num_mois = mois.partition('-')
    mois_reference = datetime.date(int(annee), int(num_mois), 1)

    if request.user.role == 'eleve':
        if eleve.user_id != request.user.id:
            return HttpResponseForbidden('هذا ليس بيانك الشهري.')

    if request.user.role == 'prof':
        prof = get_object_or_404(Prof, user=request.user)
        if not eleve.groupes.filter(prof=prof).exists():
            return HttpResponseForbidden('هذا الطالب ليس ضمن مجموعاتك.')
        bilan = BilanMensuel.objects.filter(eleve=eleve, prof=prof, mois_reference=mois_reference).first()
        if bilan is None:
            # Un élève suspendu/archivé ne doit générer aucune nouvelle activité
            # (même règle que pour les séances/présences, voir Tâche 3) — mais un
            # bilan déjà existant avant la suspension reste consultable/corrigeable
            # normalement, seule la CRÉATION d'un nouveau bilan est bloquée ici.
            if eleve.statut != 'actif':
                return HttpResponseForbidden('لا يمكن إنشاء بيان شهري جديد لطالب موقوف أو مؤرشف.')
            bilan = BilanMensuel.objects.create(
                eleve=eleve, prof=prof, mois_reference=mois_reference,
                **generer_brouillon_bilan_mensuel(eleve, prof, mois_reference),
            )
    else:
        bilan = get_object_or_404(BilanMensuel, eleve=eleve, mois_reference=mois_reference)
        prof = bilan.prof
        # prof peut être None (compte supprimé définitivement, voir migration
        # SET_NULL du 2026-08-12) — dans ce cas, ne pas bloquer la consultation
        # par le مؤطر : il n'y a plus de prof à qui restreindre l'accès, le
        # bilan doit rester consultable comme n'importe quelle donnée détachée.
        if request.user.role == 'superviseur' and prof is not None:
            superviseur = get_object_or_404(Superviseur, user=request.user)
            if prof not in superviseur.profs_assignes.all():
                return HttpResponseForbidden('هذا المعلم غير مسند إليك.')

    lecture_seule = request.user.role != 'prof' or not bilan.modifiable_par_prof

    # Chantier du 2026-08-14 (bilan d'absences) — calculé en temps réel à
    # CHAQUE affichage à partir de Presence, jamais figé/mis en cache : pas
    # scopé au prof de CE bilan (Presence.eleve suffit), pour rester correct
    # même si l'élève a changé de groupe/prof en cours de mois. Identique
    # pour les 5 rôles qui peuvent atteindre cette page — aucune donnée
    # cachée entre eux, le contexte est construit une seule fois ci-dessous.
    from courses.models import Presence
    presences_du_mois = list(
        Presence.objects.filter(
            eleve=eleve, seance__date__year=mois_reference.year, seance__date__month=mois_reference.month,
        ).select_related('seance').order_by('seance__date')
    )
    nb_present = sum(1 for p in presences_du_mois if p.statut == 'present')
    absences_du_mois = [p for p in presences_du_mois if p.statut != 'present']

    if request.method == 'POST' and not lecture_seule:
        bilan.memorisation = request.POST.get('memorisation', '')
        bilan.revision = request.POST.get('revision', '')
        bilan.remarques_discipline = request.POST.get('remarques_discipline', '')
        bilan.save()
        messages.success(request, 'تم حفظ البيان الشهري بنجاح.')
        return redirect('bilan_mensuel_detail', eleve_id=eleve.id, mois=mois)

    BASE_TEMPLATE_PAR_ROLE = {
        'prof': 'dashboard/base_prof.html',
        'admin': 'dashboard/base_admin.html',
        'superviseur': 'dashboard/base_superviseur.html',
        'mshrif': 'dashboard/base_mshrif.html',
        'eleve': 'dashboard/base_eleve.html',
    }
    COULEUR_PAR_ROLE = {
        'prof': 'var(--color-role-prof)',
        'admin': 'var(--color-role-admin)',
        'superviseur': 'var(--color-role-superviseur)',
        'mshrif': 'var(--color-role-mshrif)',
        'eleve': 'var(--color-role-eleve)',
    }
    context = {
        'eleve': eleve,
        'prof': prof,
        'bilan': bilan,
        'mois': mois,
        'mois_reference': mois_reference,
        'lecture_seule': lecture_seule,
        'presences_du_mois': presences_du_mois,
        'nb_present': nb_present,
        'absences_du_mois': absences_du_mois,
        'base_template': BASE_TEMPLATE_PAR_ROLE[request.user.role],
        'couleur_role': COULEUR_PAR_ROLE[request.user.role],
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/bilan_mensuel_detail.html', context)


@role_required('admin', 'mshrif')
def suivi_engagement_mensuel(request):
    """متابعة الالتزام الشهري (Tâche du 2026-08-07) — remplace la carte
    "نسبة الحضور هذا الشهر" du tableau de bord مشرف, dont le calcul (au
    niveau élève × séance, dénominateur = lignes Presence) donnait un 100%
    non représentatif dès qu'une seule petite séance individuelle était
    traitée (voir échange de clarification précédent). Cette page mesure la
    couverture au niveau SÉANCE (décision explicite du client, plus lisible)
    et distingue clairement 2 causes différentes : prof qui n'a pas rempli
    sa feuille de présence (Zone 2) vs مؤطر qui n'a pas encore évalué une
    séance déjà traitée (Zone 3) — tout le calcul vit dans
    courses.utils.calculer_suivi_mensuel_engagement, voir sa docstring pour
    le détail exact des périmètres.

    mois (GET, 'AAAA-MM') : même patron que mshrif_remuneration/
    bilans_mensuels — mois courant par défaut."""
    from courses.utils import calculer_suivi_mensuel_engagement
    from django.utils import timezone

    aujourdhui = timezone.localdate()
    mois_filtre = request.GET.get('mois', '')
    if mois_filtre:
        annee_str, _, mois_str = mois_filtre.partition('-')
        mois_reference = datetime.date(int(annee_str), int(mois_str), 1)
    else:
        mois_reference = aujourdhui.replace(day=1)

    donnees = calculer_suivi_mensuel_engagement(mois_reference)

    context = {
        'mois_filtre': mois_filtre,
        'mois_reference': mois_reference,
        'donnees': donnees,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/suivi_engagement_mensuel.html', context)


@role_required('admin', 'superviseur', 'mshrif')
def bilans_mensuels(request):
    """تقييم الطلاب — Niveau 1 (Point 11, Tâche du 2026-08-04) : parcours
    unique par GROUPE, remplace les anciens onglets "شهري" (liste plate de
    BilanMensuel) et "حسب الحصة" (vide tant qu'aucun élève n'était choisi
    depuis "شهري"). Filtre "الطالب" retiré (remplacé par "المجموعة") — ceci
    corrige au passage une fuite de périmètre : l'ancien menu déroulant
    listait TOUS les élèves de la plateforme, y compris pour un مؤطر, sans
    aucun scope. Le détail par séance d'un élève vit désormais sur une page
    séparée (voir bilans_mensuels_detail_seance) plutôt qu'un 2e onglet.
    Lecture seule pour مدير/مؤطر/مشرف, مؤطر scopé à ses profs assignés (même
    filtre que classement_mensuel_profs) — appliqué ici au niveau des GROUPES
    eux-mêmes (queryset de base), pas juste des données affichées."""
    from django.db.models import Avg
    from django.utils import timezone
    from accounts.models import Prof, Superviseur
    from courses.models import BilanMensuel, Groupe, NotePresence
    from courses.utils import compter_absences_par_eleve

    mois = request.GET.get('mois', '')
    prof_id = request.GET.get('prof', '')
    groupe_id = request.GET.get('groupe', '')

    groupes_scope = Groupe.objects.order_by('nom')
    if request.user.role == 'superviseur':
        superviseur = get_object_or_404(Superviseur, user=request.user)
        groupes_scope = groupes_scope.filter(prof__in=superviseur.profs_assignes.all())

    groupes = groupes_scope.select_related('prof__user').prefetch_related('eleves__user')
    if prof_id:
        groupes = groupes.filter(prof_id=prof_id)
    if groupe_id:
        groupes = groupes.filter(id=groupe_id)

    annee = mois_num = None
    if mois:
        annee_str, _, mois_str = mois.partition('-')
        annee, mois_num = int(annee_str), int(mois_str)

    # حصيلة الغياب الشهرية : contrairement à moyennes/bilan_texte ci-dessous
    # (qui restent volontairement "tout l'historique" tant qu'aucun mois
    # n'est choisi — comportement existant, inchangé), l'absence est
    # toujours affichée pour UN mois précis (défaut = mois en cours, voir la
    # demande) — jamais "toutes les absences depuis toujours" qui n'aurait
    # aucun sens pour une carte "غياب هذا الشهر".
    aujourdhui = timezone.localdate()
    annee_absences = annee or aujourdhui.year
    mois_absences = mois_num or aujourdhui.month
    mois_reference_absences = datetime.date(annee_absences, mois_absences, 1)

    groupes_accordeon = []
    for groupe in groupes:
        lignes_eleves = []
        # Une seule requête groupée par groupe (pas une par élève) — voir
        # courses.utils.compter_absences_par_eleve. Scopée à CE groupe
        # (groupe=groupe) : un élève présent dans 2 groupes supervisés ne
        # doit pas afficher le même total sous les 2 accordéons (Point 6,
        # éviter le double comptage).
        absences_groupe = compter_absences_par_eleve(
            [e.id for e in groupe.eleves.all()], annee_absences, mois_absences, groupe=groupe,
        )
        for eleve in groupe.eleves.all():
            moyennes_qs = NotePresence.objects.filter(
                presence__eleve=eleve, presence__seance__groupe=groupe, critere__est_actif=True,
            )
            bilan_qs = BilanMensuel.objects.filter(eleve=eleve, prof=groupe.prof)
            if annee:
                moyennes_qs = moyennes_qs.filter(
                    presence__seance__date__year=annee, presence__seance__date__month=mois_num
                )
                bilan_qs = bilan_qs.filter(mois_reference__year=annee, mois_reference__month=mois_num)

            moyennes_calc = moyennes_qs.values('critere__nom_ar', 'critere__ordre').annotate(
                moyenne=Avg('note')
            ).order_by('critere__ordre')
            moyennes = [{'nom_ar': m['critere__nom_ar'], 'moyenne': round(m['moyenne'], 1)} for m in moyennes_calc]

            bilan = bilan_qs.order_by('-mois_reference').first()
            # Choix arbitraire (BilanMensuel n'a pas de champ "texte" unique) :
            # les 3 champs qualitatifs (mémorisation/révision/discipline) sont
            # concaténés pour l'aperçu, tronqué côté template (truncatechars).
            bilan_texte = ''
            if bilan:
                bilan_texte = ' — '.join(filter(None, [bilan.memorisation, bilan.revision, bilan.remarques_discipline]))

            lignes_eleves.append({
                'eleve': eleve,
                'moyennes': moyennes,
                'bilan_texte': bilan_texte,
                'nb_absences': absences_groupe.get(eleve.id, 0),
            })

        groupes_accordeon.append({
            'groupe': groupe,
            'lignes_eleves': lignes_eleves,
            'nb_eleves': len(lignes_eleves),
        })

    BASE_TEMPLATE_PAR_ROLE = {
        'admin': 'dashboard/base_admin.html',
        'superviseur': 'dashboard/base_superviseur.html',
        'mshrif': 'dashboard/base_mshrif.html',
    }
    COULEUR_PAR_ROLE = {
        'admin': 'var(--color-role-admin-solid)',
        'superviseur': 'var(--color-role-superviseur-solid)',
        'mshrif': 'var(--color-role-mshrif-solid)',
    }
    context = {
        'groupes_accordeon': groupes_accordeon,
        'filtres': {'mois': mois, 'prof': prof_id, 'groupe': groupe_id},
        # Dropdowns de filtre scopés au périmètre du مؤطر (même correction de
        # fuite de périmètre que groupes_scope ci-dessus) — inchangés pour
        # مدير/مشرف (tout voir).
        'profs': Prof.objects.filter(groupes__in=groupes_scope).distinct().order_by('user__first_name')
                 if request.user.role == 'superviseur' else Prof.objects.select_related('user').order_by('user__first_name'),
        'groupes_filtre': groupes_scope,
        'mois_reference_absences': mois_reference_absences,
        'base_template': BASE_TEMPLATE_PAR_ROLE[request.user.role],
        'couleur_role': COULEUR_PAR_ROLE[request.user.role],
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/bilans_mensuels.html', context)


@role_required('admin', 'superviseur', 'mshrif')
def bilans_mensuels_detail_seance(request, groupe_id, eleve_id):
    """تقييم الطلاب — Niveau 2 (Point 11) : détail séance par séance d'un
    élève d'un groupe donné, atteint depuis une carte de groupe dépliée sur
    bilans_mensuels. Page séparée plutôt qu'un dépliage imbriqué sous la
    ligne élève : plus simple à implémenter correctement (pas d'accordéon
    dans un accordéon en JS) et réutilise tel quel calculer_progression_eleve
    + _historique_evaluations_eleve.html, déjà éprouvés ailleurs (Tâche 21 du
    2026-07-26). Scope مؤطر appliqué directement dans le get_object_or_404 du
    groupe (jamais une vérification a posteriori) : un accès direct par URL à
    un groupe/élève hors périmètre renvoie 404, pas les données."""
    from accounts.models import Eleve, Superviseur
    from courses.models import Groupe
    from courses.utils import calculer_progression_eleve

    groupes_scope = Groupe.objects.all()
    if request.user.role == 'superviseur':
        superviseur = get_object_or_404(Superviseur, user=request.user)
        groupes_scope = groupes_scope.filter(prof__in=superviseur.profs_assignes.all())

    groupe = get_object_or_404(groupes_scope, id=groupe_id)
    eleve = get_object_or_404(Eleve, id=eleve_id, groupes=groupe)

    mois = request.GET.get('mois', '')
    progression = calculer_progression_eleve(eleve, mois=mois)
    mois_reference = None
    if mois:
        annee_ms, _, num_mois_ms = mois.partition('-')
        mois_reference = datetime.date(int(annee_ms), int(num_mois_ms), 1)

    # Regroupement par mois (Point 3, refonte UX/UI du 2026-08-05) — UNIQUEMENT
    # sur "عرض كل التاريخ" (aucun mois filtré) : calculer_progression_eleve
    # restreint déjà "historique" à un seul mois quand mois= est fourni, donc
    # rien à regrouper dans ce cas (comportement inchangé, voir template).
    # Chaque mois replié par défaut — même limite de liste infinie que Point 1,
    # pour un élève ancien avec des dizaines de séances cumulées.
    historique_par_mois = None
    if not mois:
        from collections import OrderedDict
        groupes_mois = OrderedDict()
        # progression['historique'] est DÉJÀ trié du plus récent au plus ancien
        # (calculer_progression_eleve fait list(reversed(historique)) en
        # interne, pour que dashboard_eleve/admin_eleve_detail — qui réutilisent
        # cette même fonction — affichent la séance la plus récente en premier).
        # Parcouru tel quel (PAS re-reversé) : le premier mois rencontré est
        # donc le plus récent, ce qui construit directement l'OrderedDict dans
        # le bon ordre (plus récent -> plus ancien), séances de chaque mois
        # elles-mêmes déjà les plus récentes en premier (cohérent avec le
        # partial réutilisé tel quel ailleurs).
        for h in progression['historique']:
            cle = (h['date'].year, h['date'].month)
            groupes_mois.setdefault(cle, []).append(h)
        historique_par_mois = [
            {
                'date_ref': datetime.date(annee_h, mois_h, 1),
                'seances': items,
                'nb': len(items),
            }
            for (annee_h, mois_h), items in groupes_mois.items()
        ]

    BASE_TEMPLATE_PAR_ROLE = {
        'admin': 'dashboard/base_admin.html',
        'superviseur': 'dashboard/base_superviseur.html',
        'mshrif': 'dashboard/base_mshrif.html',
    }
    COULEUR_PAR_ROLE = {
        'admin': 'var(--color-role-admin-solid)',
        'superviseur': 'var(--color-role-superviseur-solid)',
        'mshrif': 'var(--color-role-mshrif-solid)',
    }
    context = {
        'groupe': groupe,
        'eleve': eleve,
        'progression': progression,
        'mois': mois,
        'mois_reference': mois_reference,
        'historique_par_mois': historique_par_mois,
        'base_template': BASE_TEMPLATE_PAR_ROLE[request.user.role],
        'couleur_role': COULEUR_PAR_ROLE[request.user.role],
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/bilans_mensuels_detail_seance.html', context)


@role_required('admin', 'mshrif')
def dashboard_admin(request):
    from inscriptions.models import InscriptionEleve, InscriptionProf
    from accounts.models import Eleve, Prof, Superviseur
    from courses.models import Groupe

    dernieres_eleves = InscriptionEleve.objects.filter(
        statut='en_attente'
    ).order_by('-date_soumission')[:3]

    dernieres_profs = InscriptionProf.objects.filter(
        statut='en_attente'
    ).order_by('-date_soumission')[:3]

    context = {
        # .actifs (exclut les archivés) — cohérent avec dashboard_mshrif.nb_eleves_actifs,
        # qui filtrait déjà; décision explicite du chantier d'archivage du 2026-08-03.
        'total_eleves': Eleve.actifs.count(),
        'total_profs': Prof.actifs.count(),
        'total_groupes': Groupe.objects.count(),
        # Pas de .actifs pour Superviseur : aucun champ de statut/archivage
        # sur ce modèle (voir docstring de admin_superviseurs) — total brut.
        'total_superviseurs': Superviseur.objects.count(),
        'total_pending': InscriptionEleve.objects.filter(statut='en_attente').count() +
                         InscriptionProf.objects.filter(statut='en_attente').count(),
        'dernieres_eleves': dernieres_eleves,
        'dernieres_profs': dernieres_profs,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin.html', context)


@role_required('admin', 'mshrif')
def admin_inscriptions(request):
    """Liste unique des candidatures en attente, élèves et profs mélangés
    et triés par date de soumission — chaque ligne porte son propre type
    (voir type_demande, posé dynamiquement ici, pas un champ du modèle)
    pour que le template sache quel badge et quelles actions afficher."""
    from inscriptions.models import InscriptionProf

    type_filtre = request.GET.get('type', '')

    eleves = []
    if type_filtre != 'prof':
        eleves = list(InscriptionEleve.objects.filter(statut='en_attente').order_by('-date_soumission'))
        for e in eleves:
            e.type_demande = 'eleve'

    profs = []
    if type_filtre != 'eleve':
        profs = list(InscriptionProf.objects.filter(statut='en_attente').order_by('-date_soumission'))
        for p in profs:
            p.type_demande = 'prof'

    inscriptions = sorted(eleves + profs, key=lambda ins: ins.date_soumission, reverse=True)

    context = {
        'inscriptions': paginer(request, inscriptions, 10),
        'type_filtre': type_filtre,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_inscriptions.html', context)


@role_required('admin', 'mshrif')
@never_cache
def confirmation_creation_compte(request):
    """Page de confirmation affichée juste après la création d'un compte élève
    (par مدير) ou professeur (validation finale par مشرف) — remplace l'ancien
    message flash en texte brut (qui ne pouvait pas contenir de bouton copier
    ni de lien WhatsApp, les messages Django étant échappés en HTML). Les
    infos transitent par la session, jamais par l'URL (mot de passe temporaire
    sensible) — lues puis immédiatement effacées (pop), donc un rafraîchissement
    de cette page renvoie proprement vers la liste plutôt que de les réafficher.
    @never_cache (Tâche du 2026-08-06) : même raison que sur
    admin_utilisateur_reinitialiser_mot_de_passe — un mot de passe déjà
    affiché ici ne doit jamais réapparaître via le bouton précédent du
    navigateur après une action ultérieure qui l'aurait rendu obsolète."""
    info = request.session.pop('confirmation_creation_compte', None)
    if not info:
        return redirect('dashboard_mshrif' if request.user.role == 'mshrif' else 'dashboard_admin')

    # Message d'acceptation (Chantier du 2026-08-15) — construire_message_
    # acceptation_whatsapp, PAS construire_message_mdp_whatsapp : cette page
    # n'affiche QUE des comptes qui viennent d'être créés/acceptés (jamais une
    # réinitialisation de mot de passe, qui reste sur construire_message_mdp_
    # whatsapp — même texte générique qu'avant, volontairement distinct).
    message_pret_a_envoyer = construire_message_acceptation_whatsapp(
        info.get('nom', ''), info['email'], info['password']
    )

    # Correction du 2026-08-14 (bug confirmé en test manuel) : UN SEUL contact
    # مدير résolu via _contact_admin_fixe() (le plus ancien compte role='admin'
    # avec téléphone renseigné) — pas TOUS les comptes role='admin'. Avant ce
    # correctif, chaque compte admin en base (y compris des résidus de test
    # jamais nettoyés) affichait son propre bouton "تواصل مع المدير",
    # dupliqué et incohérent sur cet écran.
    contact_admin = _contact_admin_fixe()
    if contact_admin and contact_admin.id == request.user.id:
        # مدير lui-même connecté (cas مؤطر — voir admin_superviseur_ajouter,
        # role_required('admin') seul) et il se trouve être LE contact fixe
        # résolu : s'envoyer une copie à soi-même n'a aucun sens (même
        # principe qu'admin_rejeter_eleve/admin_rejeter_prof).
        contact_admin = None

    context = {
        'info': info,
        'message_pret_a_envoyer': message_pret_a_envoyer,
        'libelle_personne_contact': f"مع {LIBELLE_PERSONNE_CONTACT.get(info['type_compte'], '')}",
        'texte_absence_personne': f"لا يوجد رقم هاتف مسجَّل لهذا {LIBELLE_PERSONNE_CONTACT.get(info['type_compte'], 'الحساب')}",
        # Bouton "تواصل مع المدير" : affiché pour prof (مشرف valide, informe
        # مدير) ET مؤطر (Tâche du 2026-08-06, point 4 — même écran désormais
        # réutilisé pour la création مؤطر). Jamais pour eleve (مدير valide
        # lui-même, rien à s'annoncer).
        'admins': (
            [contact_admin] if contact_admin and info['type_compte'] in ('prof', 'superviseur') else []
        ),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/confirmation_creation_compte.html', context)


@role_required('admin', 'mshrif')
@never_cache
def refus_confirme(request):
    """Écran partagé affiché juste APRÈS la confirmation d'un refus (POST sur
    admin_rejeter_eleve / admin_rejeter_prof / mshrif_rejeter_prof) — jamais
    avant. Correction du 2026-08-14 (bug de logique constaté en test manuel) :
    auparavant, les 2 boutons WhatsApp étaient déjà cliquables SUR le
    formulaire de refus, donc avant même le clic sur 'تأكيد الرفض' — un
    message de refus pouvait ainsi partir alors que la demande était encore
    'en_attente' en base (si مدير/مشرف changeait d'avis après l'envoi mais
    avant la confirmation). Reprend le pattern déjà en place pour
    confirmation_creation_compte : infos minimales en session (jamais l'URL),
    lues puis immédiatement effacées (pop) — un rafraîchissement renvoie
    proprement vers la liste plutôt que de réafficher l'écran.

    Le motif affiché ici est TOUJOURS relu depuis la base (inscription.
    motif_refus), jamais transporté par la session : celle-ci ne porte que
    l'identifiant du dossier, pas le texte du motif lui-même — impossible
    donc d'afficher autre chose que ce qui a réellement été enregistré."""
    from inscriptions.models import InscriptionEleve, InscriptionProf

    info = request.session.pop('refus_confirme', None)
    if not info:
        return redirect('dashboard_mshrif' if request.user.role == 'mshrif' else 'dashboard_admin')

    Modele = InscriptionEleve if info['type_demande'] == 'eleve' else InscriptionProf
    inscription = get_object_or_404(Modele, id=info['inscription_id'])

    # Garde de cohérence : ne construit un message de refus que si l'état en
    # base correspond bien à un refus déjà confirmé avec un motif enregistré
    # — ne devrait jamais échouer en usage normal (on vient de le confirmer
    # dans la même requête POST), mais évite d'afficher un écran WhatsApp
    # autour d'un motif vide/absent si l'état a changé entre-temps.
    if inscription.statut != 'rejete' or not inscription.motif_refus:
        return redirect(info['redirect_url_name'])

    message = (
        GABARIT_REFUS_AVANT_MOTIF.format(nom=info['nom_complet'])
        + inscription.motif_refus
        + GABARIT_REFUS_APRES_MOTIF
    )
    admin_contact = _contact_admin_fixe() if info.get('afficher_contact_admin') else None

    context = {
        'nom_complet': info['nom_complet'],
        'titre_refus': info['titre_refus'],
        'telephone_personne': inscription.telephone,
        'message': message,
        'libelle_personne': f"مع {info['nom_complet']}",
        'admins': [admin_contact] if admin_contact else [],
        'redirect_url_name': info['redirect_url_name'],
        'base_template': info['base_template'],
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/refus_confirme.html', context)


@role_required('admin')
def admin_valider_eleve(request, inscription_id):
    from inscriptions.models import InscriptionEleve
    from accounts.models import Eleve
    from django.contrib.auth import get_user_model

    User = get_user_model()
    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)

    conflit = _verifier_conflit_email(inscription.email)
    if conflit['conflit']:
        # Chantier du 2026-08-10 (partage d'email parent/enfant) : le SEUL cas
        # désormais autorisé à continuer est "un compte élève actif existe déjà
        # avec cet email" — bypass strictement scopé ici, à cette vue, à ce
        # rôle. _verifier_conflit_email elle-même reste inchangée et continue
        # de bloquer partout ailleurs (mshrif_valider_prof_final notamment —
        # 2 profs, ou un prof et un élève, ne peuvent toujours pas partager un
        # email).
        # Correctif du 2026-08-10 (audit) : `partage_eleve_possible` regarde TOUT
        # le groupe de comptes partageant cet email, pas seulement le premier —
        # un compte archivé ou orphelin AILLEURS dans le groupe ne doit plus
        # bloquer à tort tant qu'au moins un compte élève actif y existe.
        partage_email_autorise = conflit['partage_eleve_possible']
        if not partage_email_autorise:
            if conflit['orphelin']:
                messages.error(
                    request,
                    f'تعذر القبول: يوجد حساب بهذا البريد الإلكتروني ({inscription.email}) '
                    f'بدون ملف شخصي مرتبط (على الأرجح من اختبار سابق). '
                    f'احذف الحساب اليتيم أولاً ثم أعد المحاولة.'
                )
            elif conflit['archive']:
                messages.error(
                    request,
                    f'تعذر القبول: يوجد حساب مؤرشف بهذا البريد الإلكتروني ({inscription.email}). '
                    f'يجب إعادة تفعيل ذلك الحساب أولاً (أو تغيير بريده الإلكتروني) قبل قبول طلب جديد بنفس البريد.'
                )
            else:
                messages.error(
                    request,
                    f'تعذر القبول: يوجد حساب نشط بهذا البريد الإلكتروني ({inscription.email}) '
                    f'مرتبط بملف شخصي آخر (غير طالب) — التعارض يجب حله يدوياً قبل المتابعة.'
                )
            return redirect('admin_inscription_eleve_detail', inscription_id=inscription.id)

    password_temp = generer_mot_de_passe_sequentiel()

    # Tout ou rien: si une étape échoue (ex: matrice de disponibilités malformée),
    # aucun compte à moitié créé ne doit rester en base — voir l'incident où une
    # exception après la création du compte (autrefois: échec d'envoi d'email non
    # rattrapé) laissait un User+Eleve actifs mais l'inscription bloquée "en attente"
    # pour toujours. L'envoi d'email reste hors transaction: il ne doit jamais faire
    # échouer ni retenir la transaction (appel réseau lent), et ne peut de toute façon
    # plus lever d'exception (voir envoyer_email_bienvenue).
    with transaction.atomic():
        # select_for_update() : verrouille les lignes User existantes avec cet
        # email le temps de la transaction — empêche 2 validations concurrentes
        # du même email de calculer le même suffixe de username (vraie
        # protection contre la race condition, pas juste "en pratique c'est rare").
        # 0 compte existant (cas normal, 99% des validations) -> username = email,
        # comportement IDENTIQUE à avant ce chantier. Nème compte (partage
        # parent/enfant) -> username = "email__N", jamais affiché nulle part
        # (ni templates, ni connexion : EmailBackend authentifie par le champ
        # email, jamais par username — vérifié par audit avant ce chantier).
        # email reste, lui, strictement identique et partagé entre les comptes.
        nb_comptes_existants = User.objects.select_for_update().filter(email=inscription.email).count()
        username_technique = (
            inscription.email if nb_comptes_existants == 0
            else f'{inscription.email}__{nb_comptes_existants + 1}'
        )

        # Crée le User — telephone/date_naissance copiés depuis l'inscription
        # (seule source qui les contient) pour que user.telephone/date_naissance
        # ne restent plus jamais vides sur les fiches admin/superviseur qui les
        # affichent directement (voir audit Tâche 2).
        # doit_changer_mot_de_passe=False : élève ne passe JAMAIS par un
        # changement de mot de passe forcé (Points 13/14/17, décision du
        # directeur du 2026-08-05) — se connecte directement avec le mot de
        # passe fourni.
        user = User.objects.create_user(
            username=username_technique,
            email=inscription.email,
            password=password_temp,
            first_name=inscription.nom,
            telephone=inscription.telephone,
            date_naissance=inscription.date_naissance,
            role='eleve',
            doit_changer_mot_de_passe=False,
        )

        # Crée le profil Eleve
        eleve = Eleve.objects.create(
            user=user,
            sexe=inscription.sexe,
            statut='actif',
            inscription=inscription
        )

        from courses.utils import matrice_vers_lignes_eleve
        matrice_vers_lignes_eleve(eleve, inscription.disponibilites)

        # Change le statut
        inscription.statut = 'valide'
        inscription.save()

    envoyer_email_bienvenue(request, inscription.email, password_temp, inscription.nom)

    request.session['confirmation_creation_compte'] = {
        'type_compte': 'eleve',
        'nom': inscription.nom,
        'email': inscription.email,
        'password': password_temp,
        'telephone': inscription.telephone,
        'redirect_url_name': 'admin_inscriptions',
    }
    return redirect('confirmation_creation_compte')

# Gabarit de message de refus (Chantier du 2026-08-14, refonte UX ; texte mis à
# jour le 2026-08-15) — texte fourni par le client, salutation et clôture
# FIXES à l'exception du nom (placeholder {nom}) et du motif, qui varient.
# UNE SEULE définition, réutilisée par les 3 écrans de refus (admin_rejeter_eleve,
# admin_rejeter_prof, mshrif_rejeter_prof) via leur contexte commun — jamais
# recopiée en dur dans un template ou dupliquée par écran. Le template
# (refuser_inscription.html) assemble avant/motif/après pour l'aperçu live ET
# pour les liens WhatsApp, sans jamais réécrire ce texte lui-même.
#
# GABARIT_REFUS_AVANT_MOTIF contient {nom} — chacun des 4 points d'assemblage
# (les 3 vues ci-dessous + refus_confirme) appelle .format(nom=...) AVANT de
# concaténer avec le motif, jamais après : le nom fait partie du gabarit fixe,
# jamais du texte libre tapé par مدير/مشرف.
GABARIT_REFUS_AVANT_MOTIF = (
    'السلام عليكم ورحمة الله وبركاته،\n\n'
    'حياك الله {nom}،\n\n'
    'نشكر لك اهتمامك وتقدمك للانضمام إلى منصة زدني علماً.\n\n'
    'نأسف لإبلاغك بأنه لم يتم قبول طلبك في هذه المرحلة.\n\n'
    'سبب عدم القبول:\n'
)
GABARIT_REFUS_APRES_MOTIF = (
    '\n\nنسأل الله أن يوفقك ويكتب لك الخير حيث كان، وبارك الله فيكم.'
)


def _contact_admin_fixe():
    """Le compte مدير 'fixe' à contacter (Chantier du 2026-08-14, refus avec
    motif) : le plus ancien compte role='admin' AVEC un numéro renseigné —
    même champ User.telephone déjà utilisé par _contact_administration.html
    (Tâche 23 du 2026-07-26), pas un nouveau champ inventé. Peut retourner
    None si aucun compte admin n'a de téléphone renseigné — le bouton
    WhatsApp correspondant ne s'affiche simplement pas dans ce cas (voir
    _whatsapp_icon.html, qui gère déjà telephone=None/vide)."""
    from accounts.models import User
    return User.objects.filter(role='admin').exclude(telephone='').order_by('date_joined').first()


@role_required('admin')
def admin_rejeter_eleve(request, inscription_id):
    """Chantier du 2026-08-14 (refus avec motif) : GET affiche un formulaire
    (phrase-modèle réutilisable + texte libre modifiable + 2 boutons
    WhatsApp), POST l'enregistre. La garde d'état (dossier déjà traité) est
    vérifiée AVANT toute chose, pour GET comme pour POST — jamais de
    formulaire affiché ni de traitement accepté sur un dossier déjà
    accepté/rejeté entre-temps (même principe que l'ancienne version, juste
    appliqué aux deux méthodes HTTP maintenant qu'il y en a deux)."""
    from inscriptions.models import PhraseRefus

    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)
    if inscription.statut != 'en_attente':
        messages.error(
            request,
            f'تعذر الرفض: طلب {inscription.nom} لم يعد قيد الانتظار (تمت معالجته بالفعل).'
        )
        return redirect('admin_inscriptions')

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        if motif:
            inscription.statut = 'rejete'
            inscription.motif_refus = motif
            inscription.save()
            if request.POST.get('enregistrer_phrase') == 'on':
                PhraseRefus.objects.create(contexte='refus_eleve', texte=motif)
            # Redirection vers l'écran dédié refus_confirme (Correction du
            # 2026-08-14) : le refus est déjà enregistré en base à cet instant
            # (statut='rejete', motif_refus figé juste au-dessus) — les
            # boutons WhatsApp n'apparaissent qu'à PARTIR de là, jamais avant.
            request.session['refus_confirme'] = {
                'type_demande': 'eleve',
                'inscription_id': inscription.id,
                'nom_complet': inscription.nom,
                'titre_refus': 'تم رفض طلب الطالب',
                'afficher_contact_admin': False,
                'redirect_url_name': 'admin_inscriptions',
                'base_template': 'dashboard/base_admin.html',
            }
            return redirect('refus_confirme')
        messages.error(request, 'يجب كتابة سبب الرفض قبل التأكيد.')

    context = {
        'inscription': inscription,
        'nom_complet': inscription.nom,
        'telephone_personne': inscription.telephone,
        'motif_saisi': request.POST.get('motif', '') if request.method == 'POST' else '',
        'phrases': PhraseRefus.objects.filter(contexte='refus_eleve'),
        'gabarit_avant_motif': GABARIT_REFUS_AVANT_MOTIF.format(nom=inscription.nom),
        'gabarit_apres_motif': GABARIT_REFUS_APRES_MOTIF,
        'titre_refus': 'رفض طلب الطالب',
        'retour_url': reverse('admin_inscription_eleve_detail', args=[inscription.id]),
        'base_template': 'dashboard/base_admin.html',
    }
    return render(request, 'dashboard/refuser_inscription.html', context)


@role_required('admin', 'mshrif')
def admin_inscription_eleve_detail(request, inscription_id):
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO, groupes_compatibles_pour_inscription

    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)
    if inscription.statut == 'valide':
        conflit = {'conflit': False, 'user': None, 'orphelin': False, 'archive': False, 'partage_eleve_possible': False}
    else:
        conflit = _verifier_conflit_email(inscription.email)
    # Correctif du 2026-08-10 (audit du chantier partage d'email) : avant ce correctif,
    # le bouton "قبول" restait caché dès que conflit.conflit était vrai, MÊME quand
    # admin_valider_eleve aurait accepté (cas normal du partage d'email élève/élève) —
    # confirmé par test réel : impossible de valider la candidature d'un 2e membre de
    # la même famille depuis l'interface, alors que la même action fonctionnait via
    # l'URL directe. `peut_accepter` reprend EXACTEMENT la même décision que
    # admin_valider_eleve (conflit['partage_eleve_possible']) pour que ce que montre
    # cette page corresponde toujours à ce que fera réellement le clic sur "قبول".
    peut_accepter = (not conflit['conflit']) or conflit['partage_eleve_possible']
    context = {
        'inscription': inscription,
        'conflit': conflit,
        'peut_accepter': peut_accepter,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'valeurs_dispo': set(inscription.disponibilites),
        'groupes_suggeres': groupes_compatibles_pour_inscription(inscription),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_inscription_detail.html', context)


@role_required('admin', 'mshrif')
def admin_inscription_prof_detail(request, inscription_id):
    from inscriptions.models import InscriptionProf
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    inscription = get_object_or_404(InscriptionProf, id=inscription_id)

    # Le champ peut référencer un fichier qui n'existe plus (ou jamais existé) sur
    # le disque — évite d'afficher silencieusement un lecteur audio cassé.
    # .storage.exists() appelle Cloudinary en réseau (RawMediaCloudinaryStorage) :
    # une panne/lenteur ne doit jamais empêcher l'admin de consulter la fiche.
    audio_fichier_manquant = False
    audio_verification_echouee = False
    if inscription.audio_enregistrement:
        try:
            audio_fichier_manquant = not inscription.audio_enregistrement.storage.exists(inscription.audio_enregistrement.name)
        except Exception:
            logger.exception("Échec de la vérification Cloudinary pour l'audio de l'inscription %s", inscription.id)
            audio_verification_echouee = True

    context = {
        'inscription': inscription,
        'audio_fichier_manquant': audio_fichier_manquant,
        'audio_verification_echouee': audio_verification_echouee,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'valeurs_dispo': set(inscription.disponibilites),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_inscription_prof_detail.html', context)

@role_required('admin')
def admin_supprimer_user_orphelin(request, user_id):
    """Supprime un compte User sans profil Eleve/Prof (compte orphelin, généralement issu
    d'un test), pour débloquer une validation d'inscription bloquée par un conflit d'email.

    Correctif du 2026-08-10 (audit du chantier partage d'email) : مدير/مشرف n'ont
    STRUCTURELLEMENT jamais de profil Eleve/Prof (ce ne sont pas des rôles avec profil,
    contrairement à élève/prof/مؤطر) — sans ce garde-fou, un vrai compte مدير/مشرف dont
    l'email entre en collision avec une candidature était classé "orphelin de test" par
    _verifier_conflit_email, et ce bouton le supprimait alors DÉFINITIVEMENT. Confirmé
    par test réel avant ce correctif. Ces 2 rôles sont désormais refusés ici
    explicitement, quel que soit leur état de profil (qui sera de toute façon toujours
    absent pour eux — le refus est donc inconditionnel sur le rôle, pas une simple
    reformulation de la vérification de profil existante)."""
    from accounts.models import Eleve, Prof
    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User, id=user_id)

    if user.role in ('admin', 'mshrif'):
        messages.error(
            request,
            f'تعذر الحذف: هذا الحساب ({user.email}) هو حساب مدير أو مشرف — '
            f'لا يمكن حذفه من هنا مهما كانت حالته.'
        )
        return redirect(request.GET.get('next') or 'admin_inscriptions')

    a_un_profil = Eleve.objects.filter(user=user).exists() or Prof.objects.filter(user=user).exists()

    if a_un_profil:
        messages.error(request, 'تعذر الحذف: هذا الحساب مرتبط بملف شخصي نشط.')
    else:
        email = user.email
        user.delete()
        messages.success(request, f'تم حذف الحساب اليتيم ({email}). يمكنك الآن إعادة محاولة القبول.')

    next_url = request.GET.get('next') or 'admin_inscriptions'
    return redirect(next_url)

@role_required('admin')
def admin_valider_prof(request, inscription_id):
    """Pré-validation du مدير — étape 1/2. Ne crée AUCUN compte: passe juste le statut à
    'validee_directeur', qui n'apparaît plus dans la liste admin_inscriptions (elle ne concerne
    plus l'admin) mais devient visible pour le المشرف, seul habilité à créer le compte final
    (voir mshrif_valider_prof_final, qui reprend exactement la logique de création qui vivait
    ici auparavant)."""
    from inscriptions.models import InscriptionProf
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)
    inscription.statut = 'validee_directeur'
    inscription.save()
    messages.success(
        request,
        f'تم قبول طلب {inscription.nom} مبدئياً — بانتظار التصديق النهائي من المشرف قبل إنشاء الحساب.'
    )
    return redirect('admin_inscriptions')

@role_required('admin')
def admin_rejeter_prof(request, inscription_id):
    """Chantier du 2026-08-14 (refus avec motif) — voir la docstring de
    admin_rejeter_eleve pour le principe général (GET=formulaire,
    POST=enregistrement, garde d'état vérifiée avant tout)."""
    from inscriptions.models import InscriptionProf, PhraseRefus

    inscription = get_object_or_404(InscriptionProf, id=inscription_id)
    # Garde d'état: le مدير peut encore rejeter une candidature qu'il a lui-même déjà
    # pré-validée ('validee_directeur') — ex: il repère un problème avant que le المشرف
    # n'ait fini de traiter le dossier. Ce qui est bloqué, c'est d'agir sur un état FINAL
    # (déjà transformée en compte réel, ou déjà rejetée) — voir mshrif_valider_prof_final
    # pour le pendant côté المشرف, qui refuse désormais toute validation si ce rejet a
    # eu lieu entre-temps (race condition confirmée par l'audit de sécurité).
    if inscription.statut not in ('en_attente', 'validee_directeur'):
        messages.error(
            request,
            f'تعذر الرفض: طلب {inscription.nom} لم يعد قابلاً للرفض '
            f'(الحالة الحالية: {inscription.get_statut_display()}).'
        )
        return redirect('admin_inscriptions')

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        if motif:
            inscription.statut = 'rejete'
            inscription.motif_refus = motif
            inscription.save()
            if request.POST.get('enregistrer_phrase') == 'on':
                PhraseRefus.objects.create(contexte='refus_prof_etape1', texte=motif)
            # Voir le commentaire équivalent dans admin_rejeter_eleve.
            request.session['refus_confirme'] = {
                'type_demande': 'prof',
                'inscription_id': inscription.id,
                'nom_complet': f'{inscription.nom} {inscription.prenom}',
                'titre_refus': 'تم رفض طلب الأستاذ (المرحلة الأولى)',
                # Même raison qu'avant ce refactor : c'est مدير qui rejette ici
                # (étape 1), pas de sens à "prévenir مدير".
                'afficher_contact_admin': False,
                'redirect_url_name': 'admin_inscriptions',
                'base_template': 'dashboard/base_admin.html',
            }
            return redirect('refus_confirme')
        messages.error(request, 'يجب كتابة سبب الرفض قبل التأكيد.')

    context = {
        'inscription': inscription,
        'nom_complet': f'{inscription.nom} {inscription.prenom}',
        'telephone_personne': inscription.telephone,
        'motif_saisi': request.POST.get('motif', '') if request.method == 'POST' else '',
        'phrases': PhraseRefus.objects.filter(contexte='refus_prof_etape1'),
        'gabarit_avant_motif': GABARIT_REFUS_AVANT_MOTIF.format(nom=f'{inscription.nom} {inscription.prenom}'),
        'gabarit_apres_motif': GABARIT_REFUS_APRES_MOTIF,
        'titre_refus': 'رفض طلب الأستاذ (المرحلة الأولى)',
        'retour_url': reverse('admin_inscription_prof_detail', args=[inscription.id]),
        'base_template': 'dashboard/base_admin.html',
    }
    return render(request, 'dashboard/refuser_inscription.html', context)


# ==================== المشرف (mshrif) ====================
# Rôle au-dessus du مدير: valide en dernier les candidatures profs déjà pré-validées par le
# مدير (statut='validee_directeur') — c'est SEULEMENT à cette étape que le compte est créé.
# Voir PARTIE 1 du plan: workflow de validation prof en 2 étapes.

@role_required('mshrif')
def dashboard_mshrif(request):
    from accounts.models import Eleve, Prof, Superviseur
    from courses.models import Groupe

    context = {
        'nb_eleves_actifs': Eleve.objects.filter(statut='actif').count(),
        # .actifs (exclut les archivés) — même décision que dashboard_admin.total_profs.
        'nb_profs': Prof.actifs.count(),
        'nb_groupes_actifs': Groupe.objects.filter(statut='actif').count(),
        # Pas de .actifs pour Superviseur : aucun champ de statut/archivage
        # sur ce modèle (Tâche du 2026-08-07, voir docstring admin_superviseurs).
        'nb_superviseurs': Superviseur.objects.count(),
        # taux_presence_mois retiré (Tâche du 2026-08-07) : son calcul (niveau
        # élève × séance, dénominateur = lignes Presence) donnait un 100% non
        # représentatif dès qu'une seule petite séance individuelle était
        # traitée. Voir suivi_engagement_mensuel pour le remplacement.
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/dashboard_mshrif.html', context)


@role_required('mshrif')
def mshrif_inscriptions_profs(request):
    from inscriptions.models import InscriptionProf
    inscriptions = InscriptionProf.objects.filter(statut='validee_directeur').order_by('-date_soumission')
    context = {'inscriptions': paginer(request, inscriptions, 10)}
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/mshrif_inscriptions_profs.html', context)


@role_required('mshrif')
def mshrif_inscription_prof_detail(request, inscription_id):
    from inscriptions.models import InscriptionProf
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    inscription = get_object_or_404(InscriptionProf, id=inscription_id)

    # Garde d'état (correction du 2026-08-14, bug critique confirmé en test
    # manuel) : مشرف ne doit voir QUE les dossiers que مدير a explicitement
    # pré-validés ('validee_directeur') — jamais un dossier encore
    # 'en_attente' (مدير ne l'a pas encore traité) ni un dossier 'rejete'
    # (مدير l'a fermé définitivement, مشرف n'a plus rien à y faire). Avant ce
    # correctif, seule la LISTE (mshrif_inscriptions_profs, déjà filtrée sur
    # 'validee_directeur') protégeait مشرف — un accès direct par URL à cette
    # fiche de détail restait possible sur n'importe quel dossier, quel que
    # soit son statut. mshrif_valider_prof_final et mshrif_rejeter_prof
    # avaient déjà chacun leur propre garde bloquant l'ACTION ; celle-ci
    # bloque désormais aussi la simple CONSULTATION de la fiche.
    if inscription.statut != 'validee_directeur':
        messages.error(
            request,
            f'تعذر عرض هذا الطلب: حالة طلب {inscription.nom} ليست "بانتظار التصديق النهائي" '
            f'(الحالة الحالية: {inscription.get_statut_display()}).'
        )
        return redirect('mshrif_inscriptions_profs')

    conflit = _verifier_conflit_email(inscription.email)

    audio_fichier_manquant = False
    audio_verification_echouee = False
    if inscription.audio_enregistrement:
        try:
            audio_fichier_manquant = not inscription.audio_enregistrement.storage.exists(inscription.audio_enregistrement.name)
        except Exception:
            logger.exception("Échec de la vérification Cloudinary pour l'audio de l'inscription %s", inscription.id)
            audio_verification_echouee = True

    context = {
        'inscription': inscription,
        'conflit': conflit,
        'audio_fichier_manquant': audio_fichier_manquant,
        'audio_verification_echouee': audio_verification_echouee,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'valeurs_dispo': set(inscription.disponibilites),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/mshrif_inscription_prof_detail.html', context)


@role_required('mshrif')
def mshrif_valider_prof_final(request, inscription_id):
    """Validation finale — étape 2/2. Reprend EXACTEMENT la logique de création de compte qui
    vivait auparavant dans admin_valider_prof (même transaction.atomic(), mêmes champs copiés,
    même envoi d'email) — seule la source (مدير → المشرف) et le statut de départ changent."""
    from inscriptions.models import InscriptionProf
    from accounts.models import Prof
    from django.contrib.auth import get_user_model

    User = get_user_model()
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)

    # Garde d'état: le مدير a pu rejeter (ou re-traiter) ce dossier entre le moment où
    # le المشرف a ouvert cette fiche et celui où il clique "قبول نهائي" — sans ce
    # contrôle, la validation créerait quand même un compte réel et écraserait
    # silencieusement le rejet (race condition confirmée par l'audit de sécurité).
    # Redirige vers la LISTE, pas vers la fiche de détail (correction du
    # 2026-08-14) : mshrif_inscription_prof_detail porte désormais sa propre
    # garde sur ce même statut — y rediriger produirait un second redirect
    # immédiat vers la liste, avec un message d'erreur dupliqué.
    if inscription.statut != 'validee_directeur':
        messages.error(
            request,
            f'تعذر القبول النهائي: حالة طلب {inscription.nom} تغيّرت منذ فتح هذه الصفحة '
            f'(الحالة الحالية: {inscription.get_statut_display()}). لم يتم إنشاء أي حساب.'
        )
        return redirect('mshrif_inscriptions_profs')

    conflit = _verifier_conflit_email(inscription.email)
    if conflit['conflit']:
        if conflit['orphelin']:
            messages.error(
                request,
                f'تعذر القبول: يوجد حساب بهذا البريد الإلكتروني ({inscription.email}) '
                f'بدون ملف شخصي مرتبط (على الأرجح من اختبار سابق). '
                f'احذف الحساب اليتيم أولاً ثم أعد المحاولة.'
            )
        elif conflit['archive']:
            messages.error(
                request,
                f'تعذر القبول: يوجد حساب مؤرشف بهذا البريد الإلكتروني ({inscription.email}). '
                f'يجب إعادة تفعيل ذلك الحساب أولاً (أو تغيير بريده الإلكتروني) قبل قبول طلب جديد بنفس البريد.'
            )
        else:
            messages.error(
                request,
                f'تعذر القبول: يوجد حساب نشط بهذا البريد الإلكتروني ({inscription.email}) '
                f'مرتبط بملف شخصي آخر — التعارض يجب حله يدوياً قبل المتابعة.'
            )
        return redirect('mshrif_inscription_prof_detail', inscription_id=inscription.id)

    password_temp = generer_mot_de_passe_sequentiel()

    # Tout ou rien — voir le commentaire équivalent dans admin_valider_eleve.
    with transaction.atomic():
        # telephone/date_naissance copiés depuis l'inscription (voir audit Tâche 2).
        # doit_changer_mot_de_passe=False : voir commentaire dans admin_valider_eleve.
        user = User.objects.create_user(
            username=inscription.email,
            email=inscription.email,
            password=password_temp,
            first_name=inscription.nom,
            last_name=inscription.prenom,
            telephone=inscription.telephone,
            date_naissance=inscription.date_naissance,
            role='prof',
            doit_changer_mot_de_passe=False,
        )
        prof = Prof.objects.create(
            user=user,
            statut='actif',
            ville=inscription.ville,
            job_actuel=inscription.job_actuel,
            certifications=inscription.certifications,
            niveau_memorisation=inscription.niveau_memorisation,
            parcours_scolaire=inscription.parcours_scolaire,
            parcours_enseignant=inscription.parcours_enseignant,
            gestion_eleve_faible=inscription.gestion_eleve_faible,
            gestion_eleve_absent=inscription.gestion_eleve_absent,
            type_eleve_preference=inscription.type_eleve_preference,
            contrainte_genre=inscription.contrainte_genre,
            langues=inscription.langues,
            outils_maitrises=inscription.outils_maitrises,
            compte_bancaire=inscription.compte_bancaire,
            rib=inscription.rib,
            agence_bancaire=inscription.agence_bancaire,
            inscription=inscription,
        )

        from courses.utils import matrice_vers_lignes
        matrice_vers_lignes(prof, inscription.disponibilites)

        inscription.statut = 'valide'
        inscription.save()

    envoyer_email_bienvenue(request, inscription.email, password_temp, f'{inscription.nom} {inscription.prenom}')

    request.session['confirmation_creation_compte'] = {
        'type_compte': 'prof',
        'nom': f'{inscription.nom} {inscription.prenom}'.strip(),
        'email': inscription.email,
        'password': password_temp,
        'telephone': inscription.telephone,
        'redirect_url_name': 'mshrif_inscriptions_profs',
    }
    return redirect('confirmation_creation_compte')


@role_required('mshrif')
def mshrif_rejeter_prof(request, inscription_id):
    """Chantier du 2026-08-14 (refus avec motif) — voir la docstring de
    admin_rejeter_eleve pour le principe général."""
    from inscriptions.models import InscriptionProf, PhraseRefus

    inscription = get_object_or_404(InscriptionProf, id=inscription_id)
    # Garde d'état: même principe que mshrif_valider_prof_final — évite de rejeter
    # un dossier déjà traité entre-temps (déjà validé, ou déjà rejeté par un autre clic).
    if inscription.statut != 'validee_directeur':
        messages.error(
            request,
            f'تعذر الرفض: حالة طلب {inscription.nom} تغيّرت منذ فتح هذه الصفحة '
            f'(الحالة الحالية: {inscription.get_statut_display()}).'
        )
        return redirect('mshrif_inscriptions_profs')

    if request.method == 'POST':
        motif = request.POST.get('motif', '').strip()
        if motif:
            inscription.statut = 'rejete'
            inscription.motif_refus = motif
            inscription.save()
            if request.POST.get('enregistrer_phrase') == 'on':
                PhraseRefus.objects.create(contexte='refus_prof_etape2', texte=motif)
            # Voir le commentaire équivalent dans admin_rejeter_eleve.
            request.session['refus_confirme'] = {
                'type_demande': 'prof',
                'inscription_id': inscription.id,
                'nom_complet': f'{inscription.nom} {inscription.prenom}',
                'titre_refus': 'تم رفض طلب الأستاذ (المرحلة الثانية)',
                # Ici مشرف rejette et مدير est bien une personne différente —
                # le bouton garde tout son sens (contrairement aux 2 écrans où
                # c'est مدير qui agit sur lui-même).
                'afficher_contact_admin': True,
                'redirect_url_name': 'mshrif_inscriptions_profs',
                'base_template': 'dashboard/base_mshrif.html',
            }
            return redirect('refus_confirme')
        messages.error(request, 'يجب كتابة سبب الرفض قبل التأكيد.')

    context = {
        'inscription': inscription,
        'nom_complet': f'{inscription.nom} {inscription.prenom}',
        'telephone_personne': inscription.telephone,
        'motif_saisi': request.POST.get('motif', '') if request.method == 'POST' else '',
        'phrases': PhraseRefus.objects.filter(contexte='refus_prof_etape2'),
        'gabarit_avant_motif': GABARIT_REFUS_AVANT_MOTIF.format(nom=f'{inscription.nom} {inscription.prenom}'),
        'gabarit_apres_motif': GABARIT_REFUS_APRES_MOTIF,
        'titre_refus': 'رفض طلب الأستاذ (المرحلة الثانية)',
        'retour_url': reverse('mshrif_inscription_prof_detail', args=[inscription.id]),
        'base_template': 'dashboard/base_mshrif.html',
    }
    return render(request, 'dashboard/refuser_inscription.html', context)


@role_required('admin', 'mshrif')
def mshrif_remuneration(request):
    """متابعة رواتب الأساتذة (anciennement "الاستحقاقات", مشرف seul — élargi à
    مدير le 2026-08-05, Point 3 du chantier groupé : مدير n'avait jusqu'ici
    AUCUNE page pour voir combien chaque prof touche réellement, seulement le
    réglage des tarifs). Vue tabulaire de tous les profs : montant de base
    (calculer_remuneration_prof) + majoration (visible ici, contrairement à
    la page prof qui ne la montre jamais) + total.

    Profs ARCHIVÉS (Point 3) : jamais dans la liste normale, mais réaffichés
    à part avec un badge "(مؤرشف)" SI leur montant total ce mois est encore
    > 0 (ex: prof archivé mais dont les groupes ont encore des élèves actifs
    non réassignés) — jamais masqués silencieusement, pour que l'argent dû
    ne disparaisse jamais de cette vue par accident.

    mois (GET, 'AAAA-MM', Point 3) : filtre optionnel — voir la docstring de
    calculer_remuneration_prof pour sa portée EXACTE (ne change que "الحصص
    الفردية", jamais "المجموعات الجماعية", faute d'historisation de
    l'appartenance aux groupes dans ce projet — documenté aussi dans le
    template pour ne jamais laisser croire à une vraie vue historique
    complète).

    Intègre aussi, en section repliable (fermée par défaut), la grille de référence
    des tarifs (courses.models.TarifRemuneration) — auparavant une page séparée
    (admin_tarifs_remuneration), fusionnée ici pour éviter 2 pages distinctes sur
    le même sujet. Toujours en lecture seule pour ce rôle : voir
    admin_tarifs_remuneration/admin_tarif_remuneration_modifier pour l'édition,
    réservée au مدير sur la page d'origine, restée intacte."""
    from accounts.models import Prof
    from courses.models import TarifRemuneration
    from courses.utils import calculer_remuneration_prof
    from django.utils import timezone

    aujourdhui = timezone.localdate()
    mois_filtre = request.GET.get('mois', '')
    if mois_filtre:
        annee_str, _, mois_str = mois_filtre.partition('-')
        mois_reference = datetime.date(int(annee_str), int(mois_str), 1)
    else:
        mois_reference = aujourdhui.replace(day=1)

    # Chargée UNE fois et transmise à chaque appel (Tâche du 2026-08-06,
    # audit de performance point 8) : calculer_remuneration_prof la
    # rechargeait sinon à chaque prof (1 requête réseau — coûteuse, voir
    # rapport — par prof, pour une donnée strictement identique).
    tarifs_charges = {
        (t.type_capacite, t.tranche_age): t.montant
        for t in TarifRemuneration.objects.all()
    }

    lignes = []
    total_base = 0
    total_majoration = 0
    # prefetch_related('groupes') : évite 1 requête par prof pour
    # prof.groupes.all() à l'intérieur de calculer_remuneration_prof (même
    # tâche) — le reste du calcul (élèves par groupe, séances individuelles)
    # reste requêté normalement, changement plus structurel laissé de côté
    # (voir rapport).
    for prof in Prof.actifs.select_related('user').prefetch_related('groupes').order_by('user__first_name'):
        base = calculer_remuneration_prof(prof, mois=mois_filtre or None, tarifs=tarifs_charges)['total_calcule']
        majoration = prof.majoration_mensuelle or 0
        total_base += base
        total_majoration += majoration
        lignes.append({
            'prof': prof,
            'base': base,
            'majoration': prof.majoration_mensuelle,
            'total': base + majoration,
            'archive': False,
        })

    # Profs archivés : ajoutés à la suite, UNIQUEMENT s'ils ont encore un
    # montant dû ce mois (voir docstring ci-dessus).
    for prof in Prof.objects.filter(statut='archive').select_related('user').prefetch_related('groupes').order_by('user__first_name'):
        base = calculer_remuneration_prof(prof, mois=mois_filtre or None, tarifs=tarifs_charges)['total_calcule']
        majoration = prof.majoration_mensuelle or 0
        total = base + majoration
        if total <= 0:
            continue
        total_base += base
        total_majoration += majoration
        lignes.append({
            'prof': prof,
            'base': base,
            'majoration': prof.majoration_mensuelle,
            'total': total,
            'archive': True,
        })

    context = {
        # Paginé pour l'affichage (Tâche 22 Partie F du 2026-07-26) — les totaux
        # ci-dessus restent calculés sur TOUS les profs, pas seulement la page
        # affichée (calculés avant toute pagination, aucun changement à faire).
        'lignes': paginer(request, lignes, 10),
        'total_base': total_base,
        'total_majoration': total_majoration,
        'total_general': total_base + total_majoration,
        'tarifs': TarifRemuneration.objects.all().order_by('type_capacite', 'tranche_age'),
        'mois_reference': mois_reference,
        'mois_filtre': mois_filtre,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/mshrif_remuneration.html', context)


@role_required('admin', 'mshrif')
def admin_prof_remuneration_detail(request, prof_id):
    """Détail راتب d'UN prof, lecture seule pour مدير/مشرف — réutilise
    EXACTEMENT la même structure que راتبي (dashboard/_remuneration_detail.html,
    voir prof_remuneration) plutôt que de dupliquer le balisage groupes/
    individuel (Point 3 du chantier groupé, 2026-08-05). Accessible depuis
    chaque ligne de mshrif_remuneration."""
    from accounts.models import Prof
    from courses.utils import calculer_remuneration_prof
    from django.utils import timezone

    prof = get_object_or_404(Prof, id=prof_id)
    aujourdhui = timezone.localdate()
    mois_filtre = request.GET.get('mois', '')
    if mois_filtre:
        annee_str, _, mois_str = mois_filtre.partition('-')
        mois_reference = datetime.date(int(annee_str), int(mois_str), 1)
    else:
        mois_reference = aujourdhui.replace(day=1)

    context = {
        'prof': prof,
        'aujourdhui': aujourdhui,
        'mois_reference': mois_reference,
        'mois_filtre': mois_filtre,
        'remuneration': calculer_remuneration_prof(prof, mois=mois_filtre or None),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_prof_remuneration_detail.html', context)


@role_required('admin', 'superviseur', 'mshrif')
def mshrif_charte(request):
    """Gestion du ميثاق التدريس. Modification réservée à مدير et مشرف (élargi depuis
    مشرف seul — voir Tâche 6b du 2026-07-25) ; المؤطر y a accès en lecture seule.
    Contenu structuré en champs texte simples (voir accounts.models.CharteEnseignement)
    — ni مدير ni مشرف n'ont de compétence HTML, donc chaque section est éditée via des
    champs texte séparés, réinjectés dans le même squelette HTML fixe
    (templates/dashboard/_charte_contenu.html) à l'affichage. Les lignes du tableau de
    sanctions sont rechargées entièrement à chaque sauvegarde (plus simple et sans
    risque d'incohérence qu'un diff ligne par ligne, vu leur faible nombre)."""
    from accounts.models import get_charte, CharteSanctionLigne

    charte = get_charte()
    peut_modifier = request.user.role in ('admin', 'mshrif')

    if request.method == 'POST' and peut_modifier:
        charte.intro = request.POST.get('intro', '')
        charte.verset_ouverture = request.POST.get('verset_ouverture', '')
        charte.titre_bunud = request.POST.get('titre_bunud', '')

        charte.section1_titre = request.POST.get('section1_titre', '')
        charte.section1_intro = request.POST.get('section1_intro', '')
        charte.section1_items = request.POST.get('section1_items', '')

        charte.section2_titre = request.POST.get('section2_titre', '')
        charte.section2_intro = request.POST.get('section2_intro', '')
        charte.section2_items = request.POST.get('section2_items', '')

        charte.section3_titre = request.POST.get('section3_titre', '')
        charte.section3_intro = request.POST.get('section3_intro', '')
        charte.section3_items = request.POST.get('section3_items', '')
        charte.verset_rahma_texte = request.POST.get('verset_rahma_texte', '')
        charte.verset_rahma_reference = request.POST.get('verset_rahma_reference', '')
        charte.section3_conclusion = request.POST.get('section3_conclusion', '')

        charte.section4_titre = request.POST.get('section4_titre', '')
        charte.section4_intro = request.POST.get('section4_intro', '')
        charte.section4_items = request.POST.get('section4_items', '')

        charte.section5_titre = request.POST.get('section5_titre', '')
        charte.section5_intro = request.POST.get('section5_intro', '')
        charte.section5_note = request.POST.get('section5_note', '')

        charte.section6_titre = request.POST.get('section6_titre', '')
        charte.section6_intro = request.POST.get('section6_intro', '')
        charte.section6_items = request.POST.get('section6_items', '')

        charte.section7_titre = request.POST.get('section7_titre', '')
        charte.section7_intro = request.POST.get('section7_intro', '')
        charte.section7_items = request.POST.get('section7_items', '')
        charte.save()

        violations = request.POST.getlist('sanction_violation')
        severites = request.POST.getlist('sanction_severite')
        charte.sanctions.all().delete()
        for ordre, (violation, severite) in enumerate(zip(violations, severites)):
            if violation.strip():
                CharteSanctionLigne.objects.create(
                    charte=charte, ordre=ordre, violation=violation.strip(), severite=severite,
                )

        messages.success(request, 'تم تحديث ميثاق التدريس بنجاح.')
        return redirect('mshrif_charte')

    BASE_TEMPLATE_PAR_ROLE = {
        'admin': 'dashboard/base_admin.html',
        'superviseur': 'dashboard/base_superviseur.html',
        'mshrif': 'dashboard/base_mshrif.html',
    }
    COULEUR_PAR_ROLE = {
        'admin': 'var(--color-role-admin-solid)',
        'superviseur': 'var(--color-role-superviseur-solid)',
        'mshrif': 'var(--color-role-mshrif-solid)',
    }
    context = {
        'charte': charte,
        'base_template': BASE_TEMPLATE_PAR_ROLE[request.user.role],
        'couleur_role': COULEUR_PAR_ROLE[request.user.role],
        'lecture_stricte': not peut_modifier,
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/mshrif_charte.html', context)


TAILLE_MAX_LOGO_OCTETS = 2 * 1024 * 1024  # 2 Mo
EXTENSIONS_LOGO_VALIDES = ('.png', '.jpg', '.jpeg', '.webp', '.gif')


@role_required('mshrif')
def mshrif_logo(request):
    """Gestion du logo de la plateforme — المشرف uniquement. Validation manuelle
    (pas de Django Forms dans ce projet) : extension, taille, et ouverture réelle via
    Pillow (confirme que le fichier est vraiment une image, pas juste renommé)."""
    from accounts.models import get_logo_config
    from PIL import Image

    config = get_logo_config()

    if request.method == 'POST':
        fichier = request.FILES.get('logo')
        if not fichier:
            messages.error(request, 'يرجى اختيار ملف صورة.')
            return redirect('mshrif_logo')

        if not fichier.name.lower().endswith(EXTENSIONS_LOGO_VALIDES):
            messages.error(request, 'صيغة الملف غير مدعومة — استعمل PNG أو JPEG أو WEBP أو GIF.')
            return redirect('mshrif_logo')

        if fichier.size > TAILLE_MAX_LOGO_OCTETS:
            messages.error(request, 'حجم الملف كبير جداً — الحد الأقصى 2 ميغابايت.')
            return redirect('mshrif_logo')

        try:
            image = Image.open(fichier)
            image.verify()
            fichier.seek(0)  # verify() consomme le curseur du fichier, on le remet au début avant de sauvegarder
        except Exception:
            messages.error(request, 'الملف المرفوع ليس صورة صالحة.')
            return redirect('mshrif_logo')

        config.logo = fichier
        config.save()
        messages.success(request, 'تم تحديث شعار المنصة بنجاح — سيظهر الشعار الجديد في كل الصفحات.')
        return redirect('mshrif_logo')

    return render(request, 'dashboard/mshrif_logo.html', {'config': config})


# ==================== DASHBOARD ÉLÈVE ====================

@role_required('eleve')
def dashboard_eleve(request):
    from accounts.models import Eleve
    from courses.models import Seance, Presence
    from courses.utils import calculer_progression_eleve, calculer_hizb_precis, ring_dashoffset_hizb
    from django.utils import timezone

    try:
        eleve = Eleve.objects.get(user=request.user)
    except Eleve.DoesNotExist:
        return redirect('login')

    groupes = eleve.groupes.all()
    aujourdhui = timezone.localdate()

    progression = calculer_progression_eleve(eleve)
    hizb = calculer_hizb_precis(eleve)
    nb_hizb = hizb['nb_hizb_complets']
    ring_dashoffset = ring_dashoffset_hizb(nb_hizb)

    # Aperçu "dernier hifz par sourate": on part de l'historique (déjà
    # trié du plus récent au plus ancien par calculer_progression_eleve)
    # et on garde la 1ère occurrence de chaque sourate rencontrée, donc
    # triée par récence et non par numéro de sourate. Chaque entrée de
    # par_sourate porte déjà son propre pourcentage + dernière note.
    par_sourate_par_nom = {item['nom']: item for item in progression['par_sourate']}
    sourates_recentes = []
    vues = set()
    for h in progression['historique']:
        if h['sourate'] in vues:
            continue
        vues.add(h['sourate'])
        par = par_sourate_par_nom.get(h['sourate'])
        if par:
            sourates_recentes.append(par)
        if len(sourates_recentes) == 3:
            break

    # Prochaine séance: même filtre que eleve_seances (exclut seulement les
    # séances déjà terminées) — une séance annulée reste affichée avec son
    # motif, c'est une info que l'élève doit voir.
    prochaine_seance = Seance.objects.filter(
        groupe__in=groupes, date__gte=aujourdhui
    ).exclude(statut='terminee').select_related('groupe').prefetch_related('groupe__eleves__user').order_by('date', 'heure').first()

    dernieres_evaluations = Presence.objects.filter(
        eleve=eleve
    ).select_related('seance__groupe').order_by('-seance__date', '-seance__heure')[:3]

    # Encart "📌 المطلوب منك" (Tâche 9 du 2026-07-25) : les consignes de la
    # dernière séance évaluée, mises en avant sur la page d'accueil plutôt que
    # noyées dans l'historique (eleve_seances) — c'était le problème signalé.
    derniere_avec_consignes = Presence.objects.filter(
        eleve=eleve
    ).exclude(consigne_memorisation='', consigne_revision='').select_related(
        'seance__groupe'
    ).order_by('-seance__date', '-seance__heure').first()

    # Bannière "📢 إعلانات جديدة" (Chantier du 2026-08-15) : uniquement les
    # annonces de LA catégorie de cet élève (voir courses.utils.
    # cible_annonce_pour_eleve) pas encore lues — la page /annonces/mes-annonces/
    # (lien "عرض الكل") les marque lues à la visite, elles disparaissent alors
    # d'ici automatiquement. Import local (même convention que les autres
    # imports d'apps métier dans cette vue, ex: courses.models ci-dessus).
    from annonces.services import annonces_visibles_pour_eleve
    annonces_recentes = annonces_visibles_pour_eleve(eleve).exclude(
        lectures__user=request.user
    ).order_by('-date_creation')[:3]

    context = {
        'eleve': eleve,
        'groupe_principal': groupes.first(),
        'aujourdhui': aujourdhui,
        'total_seances': Presence.objects.filter(eleve=eleve).count(),
        'total_present': Presence.objects.filter(eleve=eleve, statut='present').count(),
        'nb_hizb_memorises': nb_hizb,
        'nb_sourates_distinctes': progression['nb_sourates_distinctes'],
        'hizb_en_cours': hizb['hizb_en_cours'],
        'ring_dashoffset': ring_dashoffset,
        'sourates_recentes': sourates_recentes,
        'prochaine_seance': prochaine_seance,
        'dernieres_evaluations': dernieres_evaluations,
        'derniere_avec_consignes': derniere_avec_consignes,
        'annonces_recentes': annonces_recentes,
    }
    return render(request, 'dashboard/eleve.html', context)


@role_required('eleve')
def eleve_seances(request):
    from accounts.models import Eleve
    from courses.models import Presence, Seance
    from courses.utils import compter_absences_par_eleve
    from django.utils import timezone

    eleve = get_object_or_404(Eleve, user=request.user)
    aujourdhui = timezone.localdate()

    # حصيلة الغياب الشهرية (Chantier du 2026-08-15) — l'élève choisit un mois
    # (défaut = mois en cours), scopé à SON PROPRE compte uniquement (eleve
    # vient de request.user ci-dessus, jamais d'un paramètre d'URL/GET —
    # aucun risque de fuite vers un autre élève). Même définition d'absence
    # que bilan_mensuel_detail/prof_bilans_mensuels/bilans_mensuels : statut
    # != 'present', non filtrée par groupe (voir courses.utils.
    # compter_absences_par_eleve).
    mois_absences = request.GET.get('mois', '')
    if mois_absences:
        annee_abs_str, _, mois_abs_str = mois_absences.partition('-')
        annee_absences, num_mois_absences = int(annee_abs_str), int(mois_abs_str)
    else:
        annee_absences, num_mois_absences = aujourdhui.year, aujourdhui.month
        mois_absences = f'{annee_absences:04d}-{num_mois_absences:02d}'
    mois_reference_absences = datetime.date(annee_absences, num_mois_absences, 1)
    nb_absences_mois = compter_absences_par_eleve([eleve.id], annee_absences, num_mois_absences).get(eleve.id, 0)

    # Cette page n'affichait auparavant que l'historique (via Presence, qui
    # n'existe qu'une fois la séance remplie par le prof). Une séance à venir
    # annulée ou déplacée par l'admin n'avait donc aucune vitrine pour
    # l'élève. On ajoute ici ses prochaines séances (à partir des groupes
    # auxquels il appartient), pour que ce changement lui soit visible.
    # Volontairement limité à 3 (contrairement aux 10 du prof/superviseur) :
    # pour l'élève c'est juste informatif, pas une file de travail à traiter —
    # nb_a_venir permet au template d'afficher un compteur du reste.
    seances_a_venir_qs = Seance.objects.filter(
        groupe__in=eleve.groupes.all(), date__gte=aujourdhui
    ).exclude(statut='terminee').select_related('groupe').prefetch_related('groupe__eleves__user').order_by('date', 'heure')
    nb_a_venir = seances_a_venir_qs.count()
    seances_a_venir = seances_a_venir_qs[:3]
    # Reste des séances à venir au-delà des 3 déjà visibles — rendu caché
    # dans le template et déplié en JS au clic sur le compteur, sans
    # rechargement (horizon de génération borné à 8 semaines).
    seances_a_venir_extra = seances_a_venir_qs[3:]

    # Le passé (évaluations à consulter) est plus prioritaire visuellement que
    # le futur (juste informatif) — voir le template, cette section s'affiche
    # en premier.
    presences = Presence.objects.filter(
        eleve=eleve
    ).order_by('-seance__date', '-seance__heure')

    return render(request, 'dashboard/eleve_seances.html', {
        'eleve': eleve,
        'aujourdhui': aujourdhui,
        'seances_a_venir': seances_a_venir,
        'seances_a_venir_extra': seances_a_venir_extra,
        'nb_a_venir': nb_a_venir,
        'presences': paginer(request, presences, 10),
        'mois_absences': mois_absences,
        'mois_reference_absences': mois_reference_absences,
        'nb_absences_mois': nb_absences_mois,
    })


@role_required('eleve')
def eleve_seance_detail(request, presence_id):
    from accounts.models import Eleve
    from courses.models import Presence

    eleve = get_object_or_404(Eleve, user=request.user)
    # Filtrer par eleve=eleve directement dans la requête (pas juste comparer après coup):
    # si l'ID appartient à un autre élève, la ligne ne matche pas -> 404, jamais de fuite de données.
    presence = get_object_or_404(Presence, id=presence_id, eleve=eleve)

    return render(request, 'dashboard/eleve_seance_detail.html', {
        'presence': presence,
    })


@role_required('eleve')
def eleve_profil(request):
    from accounts.models import Eleve
    from courses.models import BilanMensuel
    from django.contrib.auth import get_user_model
    User = get_user_model()
    eleve = get_object_or_404(Eleve, user=request.user)
    return render(request, 'dashboard/eleve_profil.html', {
        'eleve': eleve,
        'groupes_precedents': eleve.historique_groupes.filter(date_fin__isnull=False).select_related('groupe'),
        'admins': User.objects.filter(role='admin'),
        # Bouton "تعديل" du téléphone — même pattern que Tâche 5 (lecture seule
        # par défaut, édition seulement après clic explicite).
        'modifier_telephone': request.GET.get('modifier_telephone') == '1',
        # Chantier du 2026-08-14 (bilan d'absences, accès élève ajouté) —
        # point d'entrée vers bilan_mensuel_detail, qui n'était accessible à
        # aucun rôle élève auparavant (aucun lien nulle part côté élève).
        'bilans_mensuels': BilanMensuel.objects.filter(eleve=eleve).order_by('-mois_reference'),
    })


@role_required('eleve')
def eleve_prof_detail(request, prof_id):
    """Fiche prof — design carte avec avatar/initiales (Tâche du 2026-08-03,
    refonte visuelle). Seule page où les sections optionnelles de la fiche
    prof s'affichent côté élève, selon accounts.models.VisibiliteProf ;
    eleve_profil.html ne montre plus que le nom en lien simple vers ici."""
    from accounts.models import Eleve, Prof, get_visibilite_prof

    eleve = get_object_or_404(Eleve, user=request.user)
    prof = get_object_or_404(Prof.objects.filter(groupes__eleves=eleve).distinct(), id=prof_id)
    visibilite = get_visibilite_prof()

    # certifications est un TextField libre (pas une liste) — une pill par
    # diplôme suppose une séparation par virgule, convention la plus naturelle
    # pour ce genre de champ ; un seul élément si aucune virgule.
    certifications_liste = [c.strip() for c in prof.certifications.split(',') if c.strip()]

    a_du_contenu = any([
        visibilite.afficher_contact,
        visibilite.afficher_niveau_memorisation,
        visibilite.afficher_type_eleve_preference,
        visibilite.afficher_langues,
        visibilite.afficher_parcours_scolaire,
        visibilite.afficher_parcours_educatif,
        visibilite.afficher_certifications and certifications_liste,
        visibilite.afficher_outils_communication and prof.outils_maitrises,
        visibilite.afficher_travail_actuel and prof.job_actuel,
    ])

    return render(request, 'dashboard/eleve_prof_detail.html', {
        'prof': prof,
        'visibilite': visibilite,
        'certifications_liste': certifications_liste,
        'a_du_contenu': a_du_contenu,
    })


@role_required('eleve')
def eleve_progression(request):
    from accounts.models import Eleve
    from courses.utils import calculer_progression_eleve, calculer_hizb_precis, ring_dashoffset_hizb

    eleve = get_object_or_404(Eleve, user=request.user)
    progression = calculer_progression_eleve(eleve)
    hizb = calculer_hizb_precis(eleve)

    return render(request, 'dashboard/eleve_progression.html', {
        'eleve': eleve,
        'progression': progression,
        'nb_hizb_memorises': hizb['nb_hizb_complets'],
        'hizb_en_cours': hizb['hizb_en_cours'],
        'ring_dashoffset': ring_dashoffset_hizb(hizb['nb_hizb_complets']),
    })


# ==================== DASHBOARD SUPERVISEUR ====================

@role_required('superviseur')
def dashboard_superviseur(request):
    """Refonte UX du 2026-07-26 (Tâche 23) : réutilise EXACTEMENT le pattern
    déjà validé sur prof_seances (bandeau=ancre, cartes اليوم/الماضية/القادمة,
    +N replié en JS) au lieu de répéter 3 fois la même information (bandeau +
    liste plate + section "حسب المعلم"). "حسب المعلم" devient un onglet
    alternatif (fiches_profs, inchangé) plutôt qu'un 3e bloc affiché en
    permanence — bascule JS pure, les deux jeux de données sont déjà
    calculés côté serveur, aucun rechargement nécessaire.
    Ajout : "الحصة الحالية/التالية" (widget indépendant des filtres — le
    مؤطر doit toujours savoir quoi suivre maintenant, même s'il a filtré
    la liste sur autre chose).

    Refonte UX/UI du 2026-08-05 (Point 1) : la liste plate "الماضية" devenait
    interminable avec le temps. Remplacée par une vue agenda : 3 compteurs en
    tête (اليوم/غير مقيّمة/هذا الشهر), section اليوم inchangée, et "السجل
    السابق" — TOUTES les séances passées (متأخرة ET déjà évaluées confondues,
    fusionnées en un seul flux plutôt qu'une liste "متأخرة" à part toujours
    ouverte + une liste "traitées" à part — l'ancienne séparation ne facilitait
    pas la fusion demandée) groupées par semaine à l'intérieur d'un mois
    navigable (flèches précédent/suivant), chaque semaine repliée par défaut
    avec un badge "X غير مقيّمة" si elle en contient encore. Le compteur rouge
    en tête reste le signal "quelque chose à faire" à l'échelle de TOUT
    l'historique (pas seulement le mois affiché) — choix arbitraire fait sans
    confirmation : pas de bloc à part toujours déplié pour les séances en
    retard (l'ancien comportement), pour respecter à la lettre la consigne
    "chaque période passée repliée par défaut"."""
    from django.db.models import Exists, OuterRef
    from accounts.models import Superviseur
    from courses.models import Seance, Groupe
    from evaluations.models import Evaluation
    from django.utils import timezone

    superviseur = get_object_or_404(Superviseur, user=request.user)
    profs_assignes = superviseur.profs_assignes.all()
    aujourdhui = timezone.localdate()
    maintenant = timezone.now()

    prof_id = request.GET.get('prof', '')
    groupe_id = request.GET.get('groupe', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    toutes_seances = Seance.objects.filter(
        groupe__prof__in=profs_assignes,
    ).select_related('groupe__prof__user', 'groupe__creneau').annotate(
        est_evaluee=Exists(Evaluation.objects.filter(seance=OuterRef('pk')))
    )

    if prof_id:
        toutes_seances = toutes_seances.filter(groupe__prof_id=prof_id)
    if groupe_id:
        toutes_seances = toutes_seances.filter(groupe_id=groupe_id)
    if date_debut:
        toutes_seances = toutes_seances.filter(date__gte=date_debut)
    if date_fin:
        toutes_seances = toutes_seances.filter(date__lte=date_fin)

    # "En retard": toute séance passée, non annulée, jamais évaluée par ce
    # superviseur — QUE le prof ait bien clôturé la séance (statut='terminee')
    # OU qu'il ait carrément oublié de remplir sa feuille de présence (restée
    # 'planifiee' malgré une date passée). Corrigé le 2026-07-26 (Tâche 24,
    # Partie 2) : l'ancien filtre exigeait statut='terminee', ce qui faisait
    # atterrir les séances "oubliées" par le prof dans "seances_passees_traitees"
    # avec malgré tout un badge rouge "لم يتم تقييمها بعد" (le badge ne teste
    # jamais le statut) — décalage entre le chiffre de la bannière et le
    # nombre réel de cartes affichant ce badge/le bouton "تقييم الآن".
    # Conservé comme COMPTEUR global (tête de page) — n'est plus affiché comme
    # liste à part toujours ouverte, voir docstring ci-dessus.
    seances_retard = toutes_seances.filter(
        date__lt=aujourdhui, est_evaluee=False
    ).exclude(statut='annulee').order_by('-date', '-heure')

    # ===== Onglet "بالترتيب الزمني" (mirroir exact de prof_seances) =====
    seances_aujourdhui = toutes_seances.filter(date=aujourdhui).order_by('heure')

    nb_a_venir = toutes_seances.filter(date__gt=aujourdhui).count()

    # ===== "السجل السابق" — agenda groupé par semaine, mois navigable =====
    # Extrait dans courses.utils.navigation_mois_et_semaines (Tâche du
    # 2026-08-05) — réutilisé tel quel par dashboard_prof ("آخر الحصص"),
    # pour ne jamais dupliquer cette logique. borne_avant=True (défaut) :
    # les jours futurs du mois courant relèvent de "القادمة", jamais de
    # l'historique.
    from courses.utils import navigation_mois_et_semaines

    nav = navigation_mois_et_semaines(toutes_seances, request, aujourdhui)
    mois_nav_date = nav['mois_nav_date']
    mois_precedent_param = nav['mois_precedent_param']
    mois_suivant_param = nav['mois_suivant_param']
    mois_suivant_autorise = nav['mois_suivant_autorise']

    # Badge "X غير مقيّمة" par semaine — spécifique au مؤطر (une notion qui
    # n'existe pas côté prof), ajouté ici en post-traitement plutôt que dans
    # le helper partagé, qui reste générique.
    semaines_agenda = nav['semaines']
    for semaine in semaines_agenda:
        semaine['nb_non_evaluees'] = sum(
            1 for s in semaine['seances'] if not s.est_evaluee and s.statut != 'annulee'
        )

    # "X هذا الشهر" (compteur de tête) : toujours le mois calendaire RÉEL,
    # indépendant de la navigation ci-dessus (mois_nav ne fait naviguer QUE la
    # section "السجل السابق") — un instantané stable, comme les 2 autres
    # compteurs de tête.
    nb_seances_mois_courant = toutes_seances.filter(
        date__year=aujourdhui.year, date__month=aujourdhui.month
    ).count()

    # ===== Onglet "حسب المعلم" (inchangé, alternative — plus affiché en même temps) =====
    profs_qs = profs_assignes.select_related('user').order_by('user__first_name')
    if prof_id:
        profs_qs = profs_qs.filter(id=prof_id)

    # Tâche du 2026-08-06 (audit de performance, point 8, suite) : avant,
    # chaque prof re-filtrait toutes_seances SÉPARÉMENT (4 querysets) puis
    # chacun était réévalué 2-3 fois (.exists(), .count(), slicing,
    # itération template) — jusqu'à 9 requêtes SQL par prof, alors que
    # toutes_seances est déjà chargée avec tout le select_related
    # nécessaire (groupe__prof__user, groupe__creneau) plus haut. Un
    # select_related/prefetch_related supplémentaire n'aurait rien changé
    # ici (le coût n'est pas une relation manquante, c'est la RÉÉVALUATION
    # répétée du même queryset filtré) : matérialisée UNE fois par prof
    # (list()), puis tri/filtrage en Python sur les MÊMES conditions
    # qu'avant (est_evaluee déjà annoté, donc déjà un attribut Python sur
    # chaque objet — aucune requête supplémentaire pour le lire). Résultat
    # affiché strictement identique (mêmes séances, mêmes compteurs) —
    # vérifié séance par séance, pas seulement par comptage, voir script de
    # vérification.
    fiches_profs = []
    for prof in profs_qs:
        seances_prof_list = list(toutes_seances.filter(groupe__prof=prof))

        retard_prof = sorted(
            (s for s in seances_prof_list if s.date < aujourdhui and not s.est_evaluee and s.statut != 'annulee'),
            key=lambda s: (s.date, s.heure), reverse=True,
        )
        aujourdhui_prof = sorted(
            (s for s in seances_prof_list if s.date == aujourdhui),
            key=lambda s: s.heure,
        )
        a_venir_prof = sorted(
            (s for s in seances_prof_list if s.date > aujourdhui),
            key=lambda s: (s.date, s.heure),
        )
        retard_ids = {s.id for s in retard_prof}
        traitees_prof = sorted(
            (s for s in seances_prof_list if s.date < aujourdhui and s.id not in retard_ids),
            key=lambda s: (s.date, s.heure), reverse=True,
        )

        if not (retard_prof or aujourdhui_prof or a_venir_prof or traitees_prof):
            continue

        fiches_profs.append({
            'prof': prof,
            'nb_retard': len(retard_prof),
            'seances_retard': retard_prof,
            'seances_aujourdhui': aujourdhui_prof,
            'seances_a_venir': a_venir_prof[:5],
            'nb_a_venir': len(a_venir_prof),
            'seances_traitees': traitees_prof[:5],
            'nb_traitees': len(traitees_prof),
        })

    # ===== "الحصة الحالية/التالية" — toujours calculé sur TOUTES les séances
    # assignées, indépendamment des filtres GET (le but est de répondre à
    # "que dois-je suivre maintenant", pas "que dois-je suivre dans ma
    # sélection filtrée"). Fenêtre de 7 jours suffisante et bornée plutôt que
    # de charger tout l'horizon de génération. =====
    candidates_proches = Seance.objects.filter(
        groupe__prof__in=profs_assignes, statut='planifiee',
        date__gte=aujourdhui, date__lte=aujourdhui + datetime.timedelta(days=7),
    ).select_related('groupe__prof__user', 'groupe__creneau').order_by('date', 'heure')

    seance_en_cours = None
    seance_suivante = None
    for s in candidates_proches:
        debut = s.debut_datetime
        fin = s.fin_datetime or (debut + datetime.timedelta(hours=1))
        if debut <= maintenant <= fin:
            seance_en_cours = s
            break
        if debut > maintenant and seance_suivante is None:
            seance_suivante = s

    # ===== "القادمة" — section manquante (Point 1 du chantier groupé du
    # 2026-08-05) : avant ce correctif, seule LA prochaine séance
    # ("الحصة الحالية/التالية" ci-dessus) était visible ; rien ne montrait le
    # reste des séances à venir sur la période. Réutilise
    # courses.utils.regrouper_seances_a_venir (partagée avec dashboard_prof,
    # voir sa docstring) — scopée aux FILTRES actifs (prof/groupe/dates),
    # contrairement au widget "الحصة الحالية/التالية" ci-dessus qui reste
    # volontairement indépendant des filtres.
    from courses.utils import regrouper_seances_a_venir

    a_venir = regrouper_seances_a_venir(toutes_seances, aujourdhui)
    # seance_suivante peut ne pas appartenir à toutes_seances (elle ignore les
    # filtres GET) : le retirer si présente évite un doublon visuel sans
    # jamais fausser nb_semaine_courante (compté AVANT ce retrait).
    id_a_exclure = seance_suivante.id if seance_suivante else None
    bucket_semaine_courante = [
        s for s in a_venir['bucket_semaine_courante'] if s.id != id_a_exclure
    ]
    nb_semaine_courante = a_venir['nb_semaine_courante']

    return render(request, 'dashboard/superviseur.html', {
        'superviseur': superviseur,
        'aujourdhui': aujourdhui,
        'total_seances': toutes_seances.count(),
        'nb_retard': seances_retard.count(),
        'nb_seances_mois_courant': nb_seances_mois_courant,
        'seances_aujourdhui': seances_aujourdhui,
        'bucket_semaine_courante': bucket_semaine_courante,
        'semaine_suivante': a_venir['semaine_suivante'],
        'mois_suivants': a_venir['mois_suivants'],
        'nb_semaine_courante': nb_semaine_courante,
        'nb_a_venir': nb_a_venir,
        'semaines_agenda': semaines_agenda,
        'mois_nav_date': mois_nav_date,
        'mois_nav_param': nav['mois_nav_param'],
        'mois_precedent_param': mois_precedent_param,
        'mois_suivant_param': mois_suivant_param,
        'mois_suivant_autorise': mois_suivant_autorise,
        'seance_en_cours': seance_en_cours,
        'seance_suivante': seance_suivante,
        'fiches_profs': fiches_profs,
        'profs': profs_assignes.select_related('user').order_by('user__first_name'),
        'groupes': Groupe.objects.filter(prof__in=profs_assignes).order_by('nom'),
        'filtres': {
            'prof': prof_id,
            'groupe': groupe_id,
            'date_debut': date_debut,
            'date_fin': date_fin,
        },
    })


@role_required('superviseur')
def superviseur_seance_detail(request, seance_id):
    from accounts.models import Superviseur
    from courses.models import Seance, Presence

    superviseur = get_object_or_404(Superviseur, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof__in=superviseur.profs_assignes.all())
    presences = Presence.objects.filter(seance=seance)

    return render(request, 'dashboard/superviseur_seance_detail.html', {
        'seance': seance,
        'presences': presences,
    })


@role_required('superviseur')
def superviseur_profil(request):
    """Profil مؤطر — refondu en centre d'information sur son périmètre de
    supervision (Tâche 13 du 2026-07-25) : une carte enrichie par prof
    (contact, groupes, type d'élèves, note moyenne du mois), pas une simple
    liste de noms. Aucun nouveau calcul : la moyenne réutilise
    evaluations.utils.moyenne_mensuelle_prof (même fonction que le classement
    mensuel), le type enfants/adultes se lit depuis Creneau.age_min/age_max
    déjà en base (pas de nouvelle donnée), le nombre d'évaluations en attente
    réutilise le même filtre que dashboard_superviseur."""
    from django.db.models import Exists, OuterRef, Count
    from accounts.models import Superviseur
    from courses.models import Seance, Groupe
    from evaluations.models import Evaluation
    from django.utils import timezone

    superviseur = get_object_or_404(Superviseur, user=request.user)
    profs = superviseur.profs_assignes.select_related('user').prefetch_related('groupes__creneau').order_by('user__first_name')
    aujourdhui = timezone.localdate()

    # Bug signale le 04/08/2026 (2e ronde) : statut='terminee' excluait a tort
    # les seances restees 'planifiee' malgre une date passee (prof qui a
    # oublie de remplir sa feuille de presence) -- exactement le meme bug deja
    # corrige dans dashboard_superviseur (Tache 24, Partie 2 du 2026-07-26),
    # jamais reporte ici malgre le commentaire du docstring qui pretendait le
    # contraire. Desormais aligne EXACTEMENT sur seances_retard plus haut :
    # toute seance passee, non annulee, jamais evaluee -- quel que soit son
    # statut ('terminee' ou 'planifiee' oubliee).
    nb_evaluations_en_attente = Seance.objects.filter(
        groupe__prof__in=profs, date__lt=aujourdhui,
    ).exclude(statut='annulee').annotate(
        est_evaluee=Exists(Evaluation.objects.filter(seance=OuterRef('pk')))
    ).filter(est_evaluee=False).count()

    # "المجموعات المسندة" (Point 12, Tâche du 2026-08-04, restructurée en
    # liste PLATE le 04/08/2026 2e ronde — un prof en en-tête de section
    # donnait une hiérarchie visuelle prof→groupes non voulue ; chaque ligne
    # est maintenant un groupe, le prof affiché comme métadonnée dessus).
    # Tous les groupes ACTIFS des profs supervisés, triés par nom de groupe.
    # nb_eleves annotée (pas .eleves.count() dans le template) : évite un N+1
    # sur cette liste (chantier du 2026-08-06, point 8 — audit de performance).
    groupes_assignes = Groupe.objects.filter(
        prof__in=profs, statut='actif'
    ).select_related('prof__user', 'creneau').annotate(
        nb_eleves=Count('eleves', distinct=True)
    ).order_by('nom')

    from django.contrib.auth import get_user_model
    User = get_user_model()

    return render(request, 'dashboard/superviseur_profil.html', {
        'superviseur': superviseur,
        'groupes_assignes': groupes_assignes,
        'nb_profs': profs.count(),
        'nb_evaluations_en_attente': nb_evaluations_en_attente,
        'admins': User.objects.filter(role='admin'),
        'modifier_telephone': request.GET.get('modifier_telephone') == '1',
    })


@role_required('superviseur')
def superviseur_prof_detail(request, prof_id):
    from accounts.models import Superviseur, Prof

    superviseur = get_object_or_404(Superviseur, user=request.user)
    prof = get_object_or_404(Prof, id=prof_id, superviseurs=superviseur)

    return render(request, 'dashboard/superviseur_prof_detail.html', {
        'prof': prof,
    })


@role_required('superviseur')
def superviseur_groupe_detail(request, groupe_id):
    """Détail d'un groupe pour le مؤطر — lecture seule, clone de
    prof_groupe_detail (Point 12, Tâche du 2026-08-04). Restriction stricte :
    prof__in=superviseur.profs_assignes.all() dans le get_object_or_404 lui-même,
    pas une vérification a posteriori — un accès direct par URL à un groupe hors
    périmètre renvoie 404, jamais les données (test IDOR dédié, voir script de
    vérification).

    Enrichie le 2026-08-05 (Point 2, refonte UX/UI) : cette page est désormais
    LE point d'arrivée unique depuis "المجموعات المسندة" — elle regroupe ce
    qui obligeait auparavant à naviguer vers 2 pages filtrées séparées
    (dashboard_superviseur?groupe=X pour les séances, et nulle part pour un
    compte d'évaluations en attente PROPRE à ce groupe, qui n'existait qu'à
    l'échelle globale). Ajouts : avatar/badge de type dans l'en-tête,
    compteurs adultes/enfants (tranche_age_depuis_naissance, même source que
    la grille de rémunération), indicateur direct d'évaluations en attente
    scopé à CE groupe, avatar+statut par élève."""
    from accounts.models import Superviseur
    from courses.models import Groupe, Seance
    from courses.utils import tranche_age_depuis_naissance
    from evaluations.models import Evaluation
    from django.db.models import Exists, OuterRef
    from django.utils import timezone

    superviseur = get_object_or_404(Superviseur, user=request.user)
    groupe = get_object_or_404(Groupe, id=groupe_id, prof__in=superviseur.profs_assignes.all())
    aujourdhui = timezone.localdate()

    eleves = list(groupe.eleves.select_related('user').all())
    nb_adultes = nb_enfants = 0
    lignes_eleves = []
    for eleve in eleves:
        tranche = None
        if eleve.user.date_naissance:
            tranche = tranche_age_depuis_naissance(eleve.user.date_naissance)
            if tranche == 'adulte':
                nb_adultes += 1
            else:
                nb_enfants += 1
        lignes_eleves.append({'eleve': eleve, 'tranche': tranche})

    seances_groupe = Seance.objects.filter(groupe=groupe).annotate(
        est_evaluee=Exists(Evaluation.objects.filter(seance=OuterRef('pk')))
    )
    nb_non_evaluees = seances_groupe.filter(
        date__lt=aujourdhui, est_evaluee=False
    ).exclude(statut='annulee').count()
    nb_seances_ce_mois = seances_groupe.filter(
        date__year=aujourdhui.year, date__month=aujourdhui.month
    ).count()

    return render(request, 'dashboard/superviseur_groupe_detail.html', {
        'groupe': groupe,
        'eleves': eleves,
        'lignes_eleves': lignes_eleves,
        'nb_adultes': nb_adultes,
        'nb_enfants': nb_enfants,
        'nb_non_evaluees': nb_non_evaluees,
        'nb_seances_ce_mois': nb_seances_ce_mois,
    })


@role_required('superviseur')
def superviseur_hakiba(request):
    """حقيبة الأستاذ — vue LECTURE SEULE pour le مؤطر (Tâche du 2026-08-05,
    Point 3 du 2e correctif) : aucun bouton d'ajout/modification/suppression
    dans ce template, et les vues d'écriture (admin_hakiba_ajouter/
    admin_hakiba_supprimer) restent décorées @role_required('admin', 'mshrif')
    — 'superviseur' n'y figure pas, donc un POST direct est déjà bloqué
    structurellement par le décorateur existant (redirigé vers son propre
    dashboard, jamais traité), sans code supplémentaire à écrire ici.

    TOUS les éléments (pas seulement ceux des profs supervisés) : décision du
    2026-08-05 — la حقيبة est un contenu informationnel de l'administration
    (ميثاق، consignes, ressources), pas une donnée rattachée à un prof précis.
    La restreindre aux profs supervisés créerait une incohérence avec
    prof_hakiba.html lui-même, où CHAQUE prof voit déjà tous les éléments
    "tous les profs" indépendamment de qui le supervise."""
    from accounts.models import ElementHakiba

    elements = ElementHakiba.objects.select_related('ajoute_par').prefetch_related(
        'profs_cibles__user'
    ).all()
    return render(request, 'dashboard/superviseur_hakiba.html', {
        'elements_hakiba': elements,
    })


# ==================== ADMIN — SÉANCES ====================

@role_required('admin', 'mshrif')
def admin_seances(request):
    """Page d'exceptions: les séances normales sont générées automatiquement
    (voir courses.utils). Ici, l'admin peut seulement annuler ou déplacer
    une séance précise (prof malade, vacances...)."""
    from courses.models import Seance, Groupe
    from courses.utils import etendre_toutes_les_seances

    etendre_toutes_les_seances()

    groupe_id = request.GET.get('groupe', '')
    prof_id = request.GET.get('prof', '')
    date = request.GET.get('date', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')
    statut = request.GET.get('statut', '')
    afficher_archives = request.GET.get('afficher_archives') == '1'

    seances = Seance.objects.select_related('groupe').order_by('-date')
    if groupe_id:
        seances = seances.filter(groupe_id=groupe_id)
    if prof_id:
        seances = seances.filter(groupe__prof_id=prof_id)
    if date:
        seances = seances.filter(date=date)
    if date_debut:
        seances = seances.filter(date__gte=date_debut)
    if date_fin:
        seances = seances.filter(date__lte=date_fin)
    if statut:
        seances = seances.filter(statut=statut)

    context = {
        'seances': paginer(request, seances, 10),
        'groupes': Groupe.objects.order_by('nom'),
        'profs': profs_pour_filtre(afficher_archives, prof_id),
        'filtres': {
            'groupe': groupe_id,
            'prof': prof_id,
            'date': date,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'statut': statut,
            'afficher_archives': afficher_archives,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_seances.html', context)


@role_required('admin')
def admin_seance_annuler(request, seance_id):
    from courses.models import Seance
    seance = get_object_or_404(Seance, id=seance_id)
    # Garde d'état: une séance déjà 'terminee' a des présences réelles enregistrées par
    # le prof — l'annuler après coup laisserait une séance marquée "annulée" mais avec
    # des données de présence bien réelles dessous, une incohérence trompeuse pour
    # quiconque consulte l'historique ensuite (voir audit).
    if seance.statut != 'planifiee':
        messages.error(
            request,
            f'تعذر الإلغاء: هذه الحصة ليست في حالة "مبرمجة" حالياً (الحالة: {seance.get_statut_display()}).'
        )
        return redirect('admin_seances')
    seance.statut = 'annulee'
    seance.save()
    messages.info(request, 'تم إلغاء الحصة.')
    return redirect('admin_seances')


@role_required('admin')
def admin_seance_deplacer(request, seance_id):
    from courses.models import Seance
    seance = get_object_or_404(Seance, id=seance_id)

    if request.method == 'POST':
        seance.date = request.POST.get('date')
        seance.heure = request.POST.get('heure')
        seance.remarque = request.POST.get('remarque', '')
        seance.save()
        messages.success(request, 'تم تأجيل الحصة إلى الموعد الجديد.')
        return redirect('admin_seances')

    return render(request, 'dashboard/admin_seance_deplacer.html', {
        'seance': seance,
    })


# ==================== ADMIN — ÉLÈVES VALIDÉS ====================

@role_required('admin', 'mshrif')
def admin_eleves(request):
    from django.db.models import Q
    from accounts.models import Eleve
    from courses.models import Groupe

    q = request.GET.get('q', '').strip()
    statut = request.GET.get('statut', '')
    groupe_id = request.GET.get('groupe', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    eleves = Eleve.objects.all().select_related('user').order_by('id')
    if q:
        eleves = eleves.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(user__email__icontains=q)
        )
    if statut:
        eleves = eleves.filter(statut=statut)
    else:
        # Les archivés restent hors de la liste par défaut (statut réversible,
        # pas une suppression — voir admin_eleve_archiver) sauf recherche
        # explicite via le menu "الحالة" (seul filtre désormais — l'ancienne
        # case "إظهار المؤرشفين" faisait doublon et a été retirée).
        eleves = eleves.exclude(statut='archive')
    if groupe_id:
        eleves = eleves.filter(groupes__id=groupe_id)
    # Remplace l'ancien statut 'nouveau' (une donnée qui devenait fausse avec
    # le temps sans job de rafraîchissement) par un vrai filtre sur la date
    # d'inscription, ajustable par le directeur.
    if date_debut:
        eleves = eleves.filter(inscription__date_soumission__date__gte=date_debut)
    if date_fin:
        eleves = eleves.filter(inscription__date_soumission__date__lte=date_fin)

    context = {
        'eleves': paginer(request, eleves, 10),
        'q': q,
        'statut_choices': Eleve.STATUT_CHOICES,
        'groupes': Groupe.objects.order_by('nom'),
        'filtres': {
            'statut': statut,
            'groupe': groupe_id,
            'date_debut': date_debut,
            'date_fin': date_fin,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_eleves.html', context)


@role_required('admin', 'mshrif')
def admin_eleve_detail(request, eleve_id):
    from accounts.models import Eleve
    from courses.models import DisponibiliteEleve
    from courses.utils import calculer_progression_eleve, groupes_compatibles_pour_eleve, JOURS_SEMAINE_DISPO, generer_heures_grille

    eleve = get_object_or_404(Eleve, id=eleve_id)
    progression = calculer_progression_eleve(eleve)

    valeurs_form = set(
        f'{j}_{h.strftime("%H:%M")}'
        for j, h in DisponibiliteEleve.objects.filter(eleve=eleve).values_list('jour_semaine', 'heure_debut')
    )

    context = {
        'eleve': eleve,
        'inscription': eleve.inscription,
        'progression': progression,
        'groupes_suggeres': groupes_compatibles_pour_eleve(eleve),
        'groupes_precedents': eleve.historique_groupes.filter(date_fin__isnull=False).select_related('groupe'),
        'valeurs_form': valeurs_form,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_eleve_detail.html', context)


@role_required('admin')
def admin_eleve_suspendre(request, eleve_id):
    """Suspend un élève: date_suspension posée automatiquement à aujourd'hui
    (jamais laissée vide, contrairement à l'ancien statut 'موقوف' qui n'avait
    aucune trace de depuis quand — voir badge_suspension_eleve). N'affecte pas
    l'historique (séances/paiements/évaluations passés restent intacts et
    interrogeables); seul le prof cesse de le voir dans ses feuilles de
    présence à venir (voir prof_seance_detail/prof_presence_sauvegarder,
    filtrés sur statut='actif')."""
    from accounts.models import Eleve
    from django.utils import timezone

    eleve = get_object_or_404(Eleve, id=eleve_id)
    eleve.statut = 'suspendu'
    eleve.date_suspension = timezone.localdate()
    eleve.save(update_fields=['statut', 'date_suspension'])
    messages.info(request, f'تم إيقاف الطالب {eleve.user.get_full_name()}.')
    return redirect('admin_eleve_detail', eleve_id=eleve.id)


@role_required('admin')
def admin_eleve_reactiver(request, eleve_id):
    """Réactive un élève suspendu ou un élève archivé — même action de retour
    à 'actif' dans les deux cas, la seule différence étant l'état de départ."""
    from accounts.models import Eleve

    eleve = get_object_or_404(Eleve, id=eleve_id)
    reactiver_eleve(eleve)
    messages.success(request, f'تمت إعادة تفعيل الطالب {eleve.user.get_full_name()}.')
    return redirect('admin_eleve_detail', eleve_id=eleve.id)


@role_required('admin')
def admin_eleve_archiver(request, eleve_id):
    """Archive un élève — remplace toute suppression définitive: le compte,
    l'historique des séances/présences/paiements/évaluations restent intacts
    et interrogeables, seulement exclus des listes actives par défaut (voir
    filtre 'afficher les archivés' sur admin_eleves). Bloque aussi désormais la
    connexion et invalide immédiatement toute session en cours — voir
    accounts.services.archiver_eleve (chantier du 2026-08-03)."""
    from accounts.models import Eleve

    eleve = get_object_or_404(Eleve, id=eleve_id)
    archiver_eleve(eleve, request=request)
    messages.info(request, f'تمت أرشفة الطالب {eleve.user.get_full_name()} — لن يتمكن من تسجيل الدخول بعد الآن.')
    return redirect('admin_eleve_detail', eleve_id=eleve.id)


# ==================== SUPPRESSION DÉFINITIVE (chantier du 2026-08-12) ====================
# Distincte de admin_eleve_archiver/admin_prof_archiver (réversibles) : ici on
# supprime le User pour de vrai — مدير UNIQUEMENT (pas مشرف), confirmation par
# saisie EXACTE de l'email (identifiant garanti unique, contrairement au nom),
# transaction.atomic(), AUCUNE trace conservée après coup — même contrat que
# groupe_supprimer_definitivement/creneau_supprimer_definitivement (courses/
# views.py). Le detail exact de ce qui est réellement supprimé vs détaché
# (SET_NULL) a été audité champ par champ avant ce chantier — voir les 2
# migrations SET_NULL (BilanMensuel.prof, Evaluation.superviseur) qui
# l'accompagnent.

@role_required('admin', 'mshrif')
def eleve_supprimer_definitivement(request, eleve_id):
    """Paiement (montant + justificatif screenshot) est réellement emporté avec
    le reste, sans exception — décision explicite et informée du client (Tâche
    du 2026-08-12, revient sur le blocage initial de ce chantier) : le risque
    de conservation légale a été signalé et assumé par le client. Le fichier
    physique du justificatif est nettoyé du storage (Cloudinary en prod) via
    payments.signals.supprimer_justificatif_a_la_suppression, qui se déclenche
    automatiquement (post_delete) dès que chaque Paiement disparaît en cascade
    — pas de fichier orphelin laissé derrière."""
    from django.db.models import Sum
    from accounts.models import Eleve
    from payments.models import Paiement

    eleve = get_object_or_404(Eleve, id=eleve_id)
    paiements = Paiement.objects.filter(eleve=eleve)
    nb_paiements = paiements.count()
    total_paiements = paiements.aggregate(total=Sum('montant'))['total'] or 0

    if request.method != 'POST':
        return render(request, 'dashboard/admin_eleve_supprimer_definitivement.html', {
            'eleve': eleve,
            'nb_paiements': nb_paiements,
            'total_paiements': total_paiements,
            'nb_presences': eleve.presences.count(),
            'nb_bilans': eleve.bilans_mensuels.count(),
            'nb_groupes_historique': eleve.historique_groupes.count(),
            'nb_disponibilites': eleve.disponibilites.count(),
            'base_template': _base_template_admin_ou_mshrif(request),
        })

    confirmation = request.POST.get('confirmation_nom', '').strip()
    if confirmation != eleve.user.email:
        messages.error(request, 'البريد الإلكتروني المُدخل لا يطابق بالضبط — لم يتم حذف أي شيء.')
        return redirect('admin_eleve_detail', eleve_id=eleve.id)

    nom = eleve.user.get_full_name()
    with transaction.atomic():
        eleve.user.delete()

    messages.success(request, f'تم حذف حساب الطالب {nom} نهائياً.')
    return redirect('admin_eleves')


@role_required('admin')
def admin_eleve_disponibilites(request, eleve_id):
    from accounts.models import Eleve
    from courses.models import DisponibiliteEleve
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO, matrice_vers_lignes_eleve

    eleve = get_object_or_404(Eleve, id=eleve_id)

    if request.method == 'POST':
        if eleve.statut == 'archive':
            messages.error(request, 'تعذر التعديل: هذا الطالب مؤرشف.')
            return redirect('admin_eleve_detail', eleve_id=eleve.id)
        matrice_vers_lignes_eleve(eleve, request.POST.getlist('dispo'))
        messages.success(request, f'تم تحديث جدول تفرغ {eleve.user.get_full_name()}.')
        return redirect('admin_eleve_detail', eleve_id=eleve.id)

    valeurs_form = set(
        f'{j}_{h.strftime("%H:%M")}'
        for j, h in DisponibiliteEleve.objects.filter(eleve=eleve).values_list('jour_semaine', 'heure_debut')
    )

    # Lecture seule par défaut — un clic pour consulter ne doit jamais pouvoir
    # modifier par accident (voir Tâche 5 du 2026-07-25). Le mode édition n'est
    # activé qu'après un clic explicite sur "تعديل" (?modifier=1).
    mode_edition = request.GET.get('modifier') == '1'

    return render(request, 'dashboard/admin_eleve_disponibilites.html', {
        'eleve': eleve,
        'valeurs_form': valeurs_form,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'mode_edition': mode_edition,
    })


# ==================== ADMIN — PROFS VALIDÉS ====================

@role_required('admin', 'mshrif')
def admin_profs(request):
    from django.db.models import Q
    from accounts.models import Prof

    q = request.GET.get('q', '').strip()
    statut = request.GET.get('statut', '')

    profs = Prof.objects.all().select_related('user').order_by('id')
    if q:
        profs = profs.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(ville__icontains=q)
        )
    if statut:
        profs = profs.filter(statut=statut)
    else:
        # Même principe que admin_eleves: les profs archivés restent hors de la
        # liste par défaut (statut réversible, pas une suppression — voir
        # admin_prof_archiver) sauf recherche explicite via le menu "الحالة"
        # (seul filtre désormais — l'ancienne case "إظهار المؤرشفين" faisait
        # doublon et a été retirée).
        profs = profs.exclude(statut='archive')

    context = {
        'profs': paginer(request, profs, 10),
        'q': q,
        'statut_choices': Prof.STATUT_CHOICES,
        'filtres': {
            'statut': statut,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_profs.html', context)


@role_required('admin', 'mshrif')
def admin_prof_detail(request, prof_id):
    from accounts.models import Prof
    from courses.utils import calculer_remuneration_prof
    prof = get_object_or_404(Prof, id=prof_id)
    context = {
        'prof': prof,
        'inscription': prof.inscription,
        'remuneration': calculer_remuneration_prof(prof),
        # حقيبة الأستاذ retirée de cette fiche depuis la refonte du 2026-08-05 :
        # gestion désormais centralisée sur admin_hakiba_gestion, plus par prof.
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_prof_detail.html', context)


@role_required('admin')
def admin_prof_archiver(request, prof_id):
    """Archive un professeur — même principe que admin_eleve_archiver: aucune
    suppression, tout l'historique (séances/évaluations/rémunération passée)
    reste intact et interrogeable, seulement exclu des listes/sélecteurs actifs
    par défaut. Bloque aussi la connexion et invalide toute session en cours —
    voir accounts.services.archiver_prof (chantier du 2026-08-03)."""
    from accounts.models import Prof

    prof = get_object_or_404(Prof, id=prof_id)
    archiver_prof(prof, request=request)
    messages.info(request, f'تمت أرشفة الأستاذ {prof.user.get_full_name()} — لن يتمكن من تسجيل الدخول بعد الآن.')
    return redirect('admin_prof_detail', prof_id=prof.id)


@role_required('admin')
def admin_prof_reactiver(request, prof_id):
    """Réactive un professeur archivé: connexion, visibilité dans les listes/
    sélecteurs et éligibilité à la création de nouvelles données reviennent
    immédiatement."""
    from accounts.models import Prof

    prof = get_object_or_404(Prof, id=prof_id)
    reactiver_prof(prof)
    messages.success(request, f'تمت إعادة تفعيل الأستاذ {prof.user.get_full_name()}.')
    return redirect('admin_prof_detail', prof_id=prof.id)


@role_required('admin', 'mshrif')
def prof_supprimer_definitivement(request, prof_id):
    """Rien ne bloque ici (contrairement à eleve, voir Paiement) : aucune
    donnée financière n'est stockée par prof (la rémunération est calculée
    à la volée, jamais historisée — voir courses.utils.calculer_remuneration_prof).
    Le seul risque réel est que le montant actuellement dû pour le mois en
    cours devienne impossible à recalculer une fois le compte supprimé —
    affiché ici pour que le مدير le voie AVANT de confirmer, pas bloqué."""
    from accounts.models import Prof
    from courses.models import Groupe, DisponibiliteProf, DemandeModificationDisponibilite
    from evaluations.models import CommentaireMensuel
    from courses.utils import calculer_remuneration_prof

    prof = get_object_or_404(Prof, id=prof_id)

    if request.method != 'POST':
        remuneration = calculer_remuneration_prof(prof)
        return render(request, 'dashboard/admin_prof_supprimer_definitivement.html', {
            'prof': prof,
            'nb_groupes_actifs': Groupe.objects.filter(prof=prof, statut='actif').count(),
            'nb_disponibilites': DisponibiliteProf.objects.filter(prof=prof).count(),
            'nb_demandes_disponibilite': DemandeModificationDisponibilite.objects.filter(prof=prof).count(),
            'nb_commentaires_mensuels': CommentaireMensuel.objects.filter(prof=prof).count(),
            'remuneration_mois_courant': remuneration['total_calcule'],
            'base_template': _base_template_admin_ou_mshrif(request),
        })

    confirmation = request.POST.get('confirmation_nom', '').strip()
    if confirmation != prof.user.email:
        messages.error(request, 'البريد الإلكتروني المُدخل لا يطابق بالضبط — لم يتم حذف أي شيء.')
        return redirect('admin_prof_detail', prof_id=prof.id)

    nom = prof.user.get_full_name()
    with transaction.atomic():
        prof.user.delete()

    messages.success(request, f'تم حذف حساب الأستاذ {nom} نهائياً.')
    return redirect('admin_profs')


@role_required('admin')
def admin_prof_infos_complementaires_modifier(request, prof_id):
    """Modification par le مدير des infos COMPLÉMENTAIRES du prof (notes_admin,
    date_debut_effectif) — un troisième bloc à part, sans rapport avec la
    candidature (ni l'original figé, ni les données actuelles ci-dessous)."""
    from accounts.models import Prof

    prof = get_object_or_404(Prof, id=prof_id)

    if request.method == 'POST':
        prof.notes_admin = request.POST.get('notes_admin', '').strip()
        date_debut = request.POST.get('date_debut_effectif', '').strip()
        prof.date_debut_effectif = date_debut or None
        prof.save()
        messages.success(request, 'تم تحديث المعلومات الإضافية بنجاح.')
        return redirect('admin_prof_detail', prof_id=prof.id)

    context = {
        'prof': prof,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_prof_infos_complementaires_modifier.html', context)


# ==================== ADMIN/MSHRIF — حقيبة الأستاذ ====================
# Refonte du 2026-08-05 (remplace la v1 du 2026-08-04, Point 1, qui vivait
# sur la fiche de CHAQUE prof) — page centrale unique "إدارة حقيبة الأستاذ",
# accessible depuis le dossier "حقيبة المدير" de la sidebar. مدير ET مشرف
# peuvent tous deux ajouter/supprimer.

EXTENSIONS_HAKIBA_AUTORISEES = (
    # Documents
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt',
    # Images
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
    # Audio
    '.mp3', '.wav', '.m4a', '.ogg',
    # Vidéo
    '.mp4', '.mov', '.avi', '.webm', '.mkv',
)
# 20 Mo — plafond volontairement plus haut que l'ancien (10 Mo) pour laisser
# passer un enregistrement audio/vidéo court, sans ouvrir la porte à des
# fichiers énormes. Aucun exécutable/script dans la liste blanche ci-dessus.
TAILLE_MAX_HAKIBA_OCTETS = 20 * 1024 * 1024


def _valider_fichier_hakiba(fichier):
    """Validation stricte côté serveur (jamais confiance à l'attribut HTML
    'accept' seul, qui ne bloque rien à l'envoi réel). Renvoie un message
    d'erreur arabe si le fichier est refusé, None s'il est accepté."""
    import os
    extension = os.path.splitext(fichier.name)[1].lower()
    if extension not in EXTENSIONS_HAKIBA_AUTORISEES:
        return f'صيغة الملف "{extension}" غير مقبولة.'
    if fichier.size > TAILLE_MAX_HAKIBA_OCTETS:
        return f'حجم الملف كبير جداً ({fichier.size // (1024 * 1024)} م.ب). الحد الأقصى 20 م.ب.'
    return None


@role_required('admin', 'mshrif')
def admin_hakiba_gestion(request):
    """Page centrale "إدارة حقيبة الأستاذ" — formulaire d'ajout + liste de
    tous les éléments existants, tous profs confondus. Remplace la gestion
    par fiche individuelle (admin_prof_detail) de la v1."""
    from accounts.models import Prof, ElementHakiba

    elements = ElementHakiba.objects.select_related('ajoute_par').prefetch_related(
        'profs_cibles__user'
    ).all()
    context = {
        'elements_hakiba': elements,
        # Profs actifs seulement pour le sélecteur "أساتذة محددون" — cohérent
        # avec le chantier d'archivage (un prof archivé ne doit plus recevoir
        # de nouveau ciblage explicite, voir Prof.actifs).
        'profs_disponibles': Prof.actifs.select_related('user').order_by('user__first_name', 'user__last_name'),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_hakiba_gestion.html', context)


@role_required('admin', 'mshrif')
def admin_hakiba_ajouter(request):
    from accounts.models import Prof, ElementHakiba

    if request.method != 'POST':
        return redirect('admin_hakiba_gestion')

    titre = request.POST.get('titre', '').strip()
    contenu_texte = request.POST.get('contenu_texte', '').strip()
    fichier = request.FILES.get('fichier')
    cible = request.POST.get('cible', 'tous')

    # Au moins texte OU fichier requis — un élément complètement vide (même
    # avec un titre) est refusé, conformément à la consigne explicite du
    # 2026-08-05.
    if not contenu_texte and not fichier:
        messages.error(request, 'يجب إدخال نص أو إرفاق ملف على الأقل.')
        return redirect('admin_hakiba_gestion')

    if fichier:
        erreur = _valider_fichier_hakiba(fichier)
        if erreur:
            messages.error(request, erreur)
            return redirect('admin_hakiba_gestion')

    tous_les_profs = (cible != 'specifique')
    profs_selectionnes = []
    if not tous_les_profs:
        ids = [i for i in request.POST.getlist('profs_cibles') if i.isdigit()]
        profs_selectionnes = list(Prof.objects.filter(id__in=ids))
        if not profs_selectionnes:
            messages.error(request, 'يرجى اختيار أستاذ واحد على الأقل عند اختيار "أساتذة محددون".')
            return redirect('admin_hakiba_gestion')

    element = ElementHakiba(
        titre=titre,
        contenu_texte=contenu_texte,
        tous_les_profs=tous_les_profs,
        ajoute_par=request.user,
    )
    if fichier:
        element.fichier = fichier
    element.save()
    if not tous_les_profs:
        element.profs_cibles.set(profs_selectionnes)

    messages.success(request, 'تمت إضافة العنصر إلى حقيبة الأستاذ بنجاح.')
    return redirect('admin_hakiba_gestion')


@role_required('admin', 'mshrif')
def admin_hakiba_supprimer(request, element_id):
    from accounts.models import ElementHakiba

    element = get_object_or_404(ElementHakiba, id=element_id)
    if element.fichier:
        element.fichier.delete(save=False)
    element.delete()
    messages.success(request, 'تم حذف العنصر من حقيبة الأستاذ.')
    return redirect('admin_hakiba_gestion')


@role_required('admin')
def admin_prof_donnees_actuelles_modifier(request, prof_id):
    """Modification par le مدير des données ACTUELLES du prof (modèle Prof —
    ce que voient élève/مؤطر partout ailleurs sur le site). Volontairement
    séparé de l'original de candidature (InscriptionProf, jamais modifié
    depuis la plateforme, affiché à part en lecture seule sur admin_prof_detail)
    — architecture déjà en place (Prof est copié depuis InscriptionProf à la
    validation, voir mshrif_valider_prof_final), pas de duplication à ajouter :
    corriger une donnée ici ne touche jamais à la candidature d'origine."""
    from accounts.models import Prof

    prof = get_object_or_404(Prof, id=prof_id)

    if request.method == 'POST':
        prof.ville = request.POST.get('ville', '').strip()
        prof.job_actuel = request.POST.get('job_actuel', '').strip()
        prof.niveau_memorisation = request.POST.get('niveau_memorisation', '').strip()
        prof.certifications = request.POST.get('certifications', '').strip()
        prof.parcours_scolaire = request.POST.get('parcours_scolaire', '').strip()
        prof.parcours_enseignant = request.POST.get('parcours_enseignant', '').strip()
        prof.langues = request.POST.getlist('langues')
        prof.outils_maitrises = request.POST.getlist('outils_maitrises')
        prof.type_eleve_preference = request.POST.getlist('type_eleve_preference')
        prof.save()
        messages.success(request, 'تم تحديث البيانات الحالية للمعلم بنجاح.')
        return redirect('admin_prof_detail', prof_id=prof.id)

    context = {
        'prof': prof,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_prof_donnees_actuelles_modifier.html', context)


@role_required('admin')
def admin_prof_majoration_modifier(request, prof_id):
    from accounts.models import Prof
    prof = get_object_or_404(Prof, id=prof_id)

    if request.method == 'POST':
        if prof.statut == 'archive':
            messages.error(request, 'تعذر التعديل: هذا الأستاذ مؤرشف.')
            return redirect('admin_prof_detail', prof_id=prof.id)
        majoration = request.POST.get('majoration_mensuelle', '').strip()
        prof.majoration_mensuelle = majoration or None
        prof.save()
        messages.success(request, 'تم تحديث المنحة الشهرية.')

    return redirect('admin_prof_detail', prof_id=prof.id)


# ==================== ADMIN — DISPONIBILITÉS DES PROFS ====================

@role_required('admin', 'mshrif')
def admin_prof_disponibilites(request, prof_id):
    from accounts.models import Prof
    from courses.models import DisponibiliteProf
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO, matrice_vers_lignes

    prof = get_object_or_404(Prof, id=prof_id)

    if request.method == 'POST' and request.user.role == 'admin':
        if prof.statut == 'archive':
            messages.error(request, 'تعذر التعديل: هذا الأستاذ مؤرشف.')
            return redirect('admin_prof_detail', prof_id=prof.id)
        matrice_vers_lignes(prof, request.POST.getlist('dispo'))
        messages.success(request, f'تم تحديث جدول تفرغ {prof.user.get_full_name()}.')
        return redirect('admin_prof_detail', prof_id=prof.id)

    valeurs_form = set(
        f'{j}_{h.strftime("%H:%M")}'
        for j, h in DisponibiliteProf.objects.filter(prof=prof).values_list('jour_semaine', 'heure_debut')
    )

    # مشرف reste en lecture seule dans tous les cas (déjà en place). Pour مدير,
    # lecture seule par défaut désormais aussi — un clic pour consulter ne doit
    # jamais pouvoir modifier par accident (voir Tâche 5 du 2026-07-25) — le
    # mode édition n'est activé qu'après un clic explicite sur "تعديل".
    peut_modifier = request.user.role == 'admin'
    mode_edition = peut_modifier and request.GET.get('modifier') == '1'

    context = {
        'prof': prof,
        'valeurs_form': valeurs_form,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'base_template': _base_template_admin_ou_mshrif(request),
        'lecture_seule': not mode_edition,
        'peut_modifier': peut_modifier,
        'mode_edition': mode_edition,
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_prof_disponibilites.html', context)


@role_required('admin', 'mshrif')
def admin_demandes_disponibilite(request):
    from courses.models import DemandeModificationDisponibilite
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    demandes = DemandeModificationDisponibilite.objects.filter(
        statut='en_attente'
    ).select_related('prof__user').order_by('date_demande')

    demandes_avec_matrice = [
        {'demande': d, 'valeurs': set(d.nouvelle_matrice)}
        for d in demandes
    ]

    context = {
        'demandes': demandes_avec_matrice,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_demandes_disponibilite.html', context)


@role_required('admin')
def admin_demande_disponibilite_approuver(request, demande_id):
    from courses.models import DemandeModificationDisponibilite
    from courses.utils import matrice_vers_lignes
    from django.utils import timezone

    demande = get_object_or_404(DemandeModificationDisponibilite, id=demande_id, statut='en_attente')
    matrice_vers_lignes(demande.prof, demande.nouvelle_matrice)
    demande.statut = 'approuvee'
    demande.date_traitement = timezone.now()
    demande.save()
    messages.success(request, f'تم قبول تعديل جدول تفرغ {demande.prof.user.get_full_name()}.')
    return redirect('admin_demandes_disponibilite')


@role_required('admin')
def admin_demande_disponibilite_rejeter(request, demande_id):
    from courses.models import DemandeModificationDisponibilite
    from django.utils import timezone

    demande = get_object_or_404(DemandeModificationDisponibilite, id=demande_id, statut='en_attente')
    demande.statut = 'rejetee'
    demande.date_traitement = timezone.now()
    demande.save()
    messages.info(request, f'تم رفض طلب تعديل جدول تفرغ {demande.prof.user.get_full_name()}.')
    return redirect('admin_demandes_disponibilite')


# ==================== ADMIN — CALENDRIER ====================

@role_required('admin', 'mshrif')
def admin_calendrier(request):
    from courses.models import Seance
    from courses.utils import etendre_toutes_les_seances
    from django.utils import timezone

    etendre_toutes_les_seances()

    semaine_param = request.GET.get('semaine')
    prof_id = request.GET.get('prof', '')
    afficher_archives = request.GET.get('afficher_archives') == '1'
    try:
        reference = datetime.date.fromisoformat(semaine_param) if semaine_param else timezone.localdate()
    except ValueError:
        reference = timezone.localdate()

    lundi = reference - datetime.timedelta(days=reference.weekday())
    jours_dates = [lundi + datetime.timedelta(days=i) for i in range(7)]

    seances = Seance.objects.filter(
        date__gte=jours_dates[0], date__lte=jours_dates[-1]
    ).select_related('groupe', 'groupe__prof__user').order_by('date', 'heure')
    if prof_id:
        seances = seances.filter(groupe__prof_id=prof_id)

    seances_par_jour = {jour: [] for jour in jours_dates}
    for seance in seances:
        seances_par_jour[seance.date].append(seance)

    # Le filtre prof (et le toggle "afficher archivés") doit survivre à la navigation
    # semaine précédente/suivante, sinon changer de semaine le réinitialiserait
    # silencieusement.
    suffixe_prof = f'&prof={prof_id}' if prof_id else ''
    if afficher_archives:
        suffixe_prof += '&afficher_archives=1'

    context = {
        'jours': [
            {'date': jour, 'nom': JOURS_SEMAINE_AR[jour.weekday()], 'seances': seances_par_jour[jour]}
            for jour in jours_dates
        ],
        'lundi': lundi,
        'dimanche': jours_dates[-1],
        'semaine_precedente': (lundi - datetime.timedelta(days=7)).isoformat() + suffixe_prof,
        'semaine_suivante': (lundi + datetime.timedelta(days=7)).isoformat() + suffixe_prof,
        'profs': profs_pour_filtre(afficher_archives, prof_id),
        'filtres': {'prof': prof_id, 'afficher_archives': afficher_archives},
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_calendrier.html', context)


# ==================== ADMIN — PARAMÈTRES (TARIFS) ====================

@role_required('admin', 'mshrif')
def admin_parametres_abonnements(request):
    from inscriptions.models import TypeAbonnement
    types_abonnement = TypeAbonnement.objects.all().order_by('ordre')
    context = {
        'types_abonnement': types_abonnement,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_parametres_abonnements.html', context)


@role_required('admin', 'mshrif')
def admin_abonnement_ajouter(request):
    from inscriptions.models import TypeAbonnement

    if request.method == 'POST':
        TypeAbonnement.objects.create(
            code=request.POST.get('code'),
            label=request.POST.get('label'),
            prix=request.POST.get('prix'),
            cible_age=request.POST.get('cible_age', 'les_deux'),
            ordre=request.POST.get('ordre', 0),
        )
        messages.success(request, 'تمت إضافة نوع الاشتراك بنجاح.')
        return redirect('admin_parametres_abonnements')

    return render(request, 'dashboard/admin_abonnement_ajouter.html', {
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_abonnement_modifier(request, abonnement_id):
    from inscriptions.models import TypeAbonnement
    type_abonnement = get_object_or_404(TypeAbonnement, id=abonnement_id)

    if request.method == 'POST':
        type_abonnement.label = request.POST.get('label')
        type_abonnement.prix = request.POST.get('prix')
        type_abonnement.cible_age = request.POST.get('cible_age', 'les_deux')
        type_abonnement.ordre = request.POST.get('ordre', 0)
        type_abonnement.save()
        messages.success(request, 'تم تعديل نوع الاشتراك بنجاح.')
        return redirect('admin_parametres_abonnements')

    return render(request, 'dashboard/admin_abonnement_modifier.html', {
        'type_abonnement': type_abonnement,
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_abonnement_toggle(request, abonnement_id):
    from inscriptions.models import TypeAbonnement
    type_abonnement = get_object_or_404(TypeAbonnement, id=abonnement_id)
    type_abonnement.est_actif = not type_abonnement.est_actif
    type_abonnement.save()
    messages.info(request, 'تم تفعيل نوع الاشتراك.' if type_abonnement.est_actif else 'تم تعطيل نوع الاشتراك.')
    return redirect('admin_parametres_abonnements')


# ==================== ADMIN — GRILLE TARIFAIRE DE RÉMUNÉRATION DES PROFS ====================
# Grille fixe à 4 lignes (type_capacite × tranche_age) — contrairement à
# TypeAbonnement/Critere ci-dessus, pas d'ajout/suppression: seul le montant
# de chaque ligne existante est modifiable (voir courses.models.TarifRemuneration).

@role_required('admin', 'mshrif')
def admin_tarifs_remuneration(request):
    # Fusionnée dans mshrif_remuneration (section repliable) pour le مشرف — cette
    # page reste la version complète (avec édition) réservée au مدير. Redirection
    # pour éviter un lien mort si l'ancienne URL était mise en favori côté مشرف,
    # qui n'a plus de lien sidebar direct vers ici.
    if request.user.role == 'mshrif':
        return redirect('mshrif_remuneration')

    from courses.models import TarifRemuneration
    tarifs = TarifRemuneration.objects.all().order_by('type_capacite', 'tranche_age')
    context = {
        'tarifs': tarifs,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_tarifs_remuneration.html', context)


@role_required('admin')
def admin_tarif_remuneration_modifier(request, tarif_id):
    from courses.models import TarifRemuneration
    tarif = get_object_or_404(TarifRemuneration, id=tarif_id)

    if request.method == 'POST':
        tarif.montant = request.POST.get('montant')
        tarif.save()
        messages.success(request, 'تم تعديل التعرفة بنجاح.')
        return redirect('admin_tarifs_remuneration')

    return render(request, 'dashboard/admin_tarif_remuneration_modifier.html', {
        'tarif': tarif,
    })


# ==================== ADMIN — CRITÈRES D'ÉVALUATION (SUPERVISEUR) ====================

@role_required('admin', 'mshrif')
def admin_criteres(request):
    # Fusionnée dans classement_mensuel_profs (section repliable) pour le مشرف —
    # cette page reste la version complète (avec édition) réservée au مدير.
    # Redirection pour éviter un lien mort si l'ancienne URL était en favori côté
    # مشرف, qui n'a plus de lien sidebar direct vers ici.
    if request.user.role == 'mshrif':
        return redirect('classement_mensuel_profs')

    from evaluations.models import Critere
    criteres = Critere.objects.all().order_by('ordre')
    context = {
        'criteres': criteres,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_criteres.html', context)


@role_required('admin')
def admin_critere_ajouter(request):
    from evaluations.models import Critere

    if request.method == 'POST':
        Critere.objects.create(
            nom_ar=request.POST.get('nom_ar'),
            ordre=request.POST.get('ordre', 0),
        )
        messages.success(request, 'تمت إضافة المعيار بنجاح.')
        return redirect('admin_criteres')

    return render(request, 'dashboard/admin_critere_ajouter.html')


@role_required('admin')
def admin_critere_modifier(request, critere_id):
    from evaluations.models import Critere
    critere = get_object_or_404(Critere, id=critere_id)

    if request.method == 'POST':
        critere.nom_ar = request.POST.get('nom_ar')
        critere.ordre = request.POST.get('ordre', 0)
        critere.save()
        messages.success(request, 'تم تعديل المعيار بنجاح.')
        return redirect('admin_criteres')

    return render(request, 'dashboard/admin_critere_modifier.html', {
        'critere': critere,
    })


@role_required('admin')
def admin_critere_toggle(request, critere_id):
    from evaluations.models import Critere
    critere = get_object_or_404(Critere, id=critere_id)
    critere.est_actif = not critere.est_actif
    critere.save()
    messages.info(request, 'تم تفعيل المعيار.' if critere.est_actif else 'تم تعطيل المعيار.')
    return redirect('admin_criteres')


@role_required('admin')
def admin_critere_supprimer(request, critere_id):
    from evaluations.models import Critere, NoteEvaluation
    critere = get_object_or_404(Critere, id=critere_id)

    if NoteEvaluation.objects.filter(critere=critere).exists():
        messages.error(
            request,
            f'تعذر حذف "{critere.nom_ar}": هذا المعيار استُخدم في تقييمات سابقة. '
            f'يمكنك تعطيله بدلاً من حذفه للحفاظ على السجل التاريخي.'
        )
    else:
        nom = critere.nom_ar
        critere.delete()
        messages.success(request, f'تم حذف المعيار "{nom}".')

    return redirect('admin_criteres')


# ==================== ADMIN — CRITÈRES D'ÉVALUATION (ÉLÈVE) ====================
# Miroir exact des vues "CRITÈRES D'ÉVALUATION (SUPERVISEUR)" ci-dessus —
# Tâche du 2026-08-04 (Point 7). Contrairement à admin_criteres (qui redirige
# مشرف vers classement_mensuel_profs), مشرف consulte directement cette liste
# en lecture seule (mêmes conditionnels {% if request.user.role != 'mshrif' %}
# déjà présents dans le template cloné) : pas de page de classement élèves
# équivalente vers laquelle rediriger.

@role_required('admin', 'mshrif')
def admin_criteres_eleves(request):
    from courses.models import CritereEleve
    criteres = CritereEleve.objects.all().order_by('ordre')
    context = {
        'criteres': criteres,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_criteres_eleves.html', context)


@role_required('admin')
def admin_critere_eleve_ajouter(request):
    from courses.models import CritereEleve

    if request.method == 'POST':
        CritereEleve.objects.create(
            nom_ar=request.POST.get('nom_ar'),
            ordre=request.POST.get('ordre', 0),
        )
        messages.success(request, 'تمت إضافة المعيار بنجاح.')
        return redirect('admin_criteres_eleves')

    return render(request, 'dashboard/admin_critere_eleve_ajouter.html')


@role_required('admin')
def admin_critere_eleve_modifier(request, critere_id):
    from courses.models import CritereEleve
    critere = get_object_or_404(CritereEleve, id=critere_id)

    if request.method == 'POST':
        critere.nom_ar = request.POST.get('nom_ar')
        critere.ordre = request.POST.get('ordre', 0)
        critere.save()
        messages.success(request, 'تم تعديل المعيار بنجاح.')
        return redirect('admin_criteres_eleves')

    return render(request, 'dashboard/admin_critere_eleve_modifier.html', {
        'critere': critere,
    })


@role_required('admin')
def admin_critere_eleve_toggle(request, critere_id):
    from courses.models import CritereEleve
    critere = get_object_or_404(CritereEleve, id=critere_id)
    critere.est_actif = not critere.est_actif
    critere.save()
    messages.info(request, 'تم تفعيل المعيار.' if critere.est_actif else 'تم تعطيل المعيار.')
    return redirect('admin_criteres_eleves')


@role_required('admin')
def admin_critere_eleve_supprimer(request, critere_id):
    from courses.models import CritereEleve, NotePresence
    critere = get_object_or_404(CritereEleve, id=critere_id)

    if NotePresence.objects.filter(critere=critere).exists():
        messages.error(
            request,
            f'تعذر حذف "{critere.nom_ar}": هذا المعيار استُخدم في تقييمات سابقة. '
            f'يمكنك تعطيله بدلاً من حذفه للحفاظ على السجل التاريخي.'
        )
    else:
        nom = critere.nom_ar
        critere.delete()
        messages.success(request, f'تم حذف المعيار "{nom}".')

    return redirect('admin_criteres_eleves')


# ==================== ADMIN — VUE CENTRALISÉE DES ÉVALUATIONS ====================

LIMITE_EVALUATIONS_LISTE = 30


@role_required('admin', 'mshrif')
def admin_evaluations(request):
    from courses.models import Presence, Groupe
    from evaluations.models import Evaluation

    groupe_id = request.GET.get('groupe', '')
    prof_id = request.GET.get('prof', '')
    eleve_id = request.GET.get('eleve', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')
    afficher_archives = request.GET.get('afficher_archives') == '1'

    presences = Presence.objects.filter(seance__statut='terminee').select_related(
        'seance__groupe__prof__user', 'eleve__user'
    ).order_by('-seance__date', '-seance__heure')

    evaluations_profs = Evaluation.objects.select_related(
        'seance__groupe__prof__user', 'superviseur__user', 'prof__user'
    ).prefetch_related('notes__critere').order_by('-seance__date')

    if groupe_id:
        presences = presences.filter(seance__groupe_id=groupe_id)
        evaluations_profs = evaluations_profs.filter(seance__groupe_id=groupe_id)
    if prof_id:
        presences = presences.filter(seance__groupe__prof_id=prof_id)
        # Filtre sur evaluation.prof (le prof réellement évalué, figé à la
        # création — chantier du 2026-08-12), pas seance.groupe.prof (le prof
        # ACTUEL du groupe, qui peut avoir changé depuis) : plus exact, et
        # continue de fonctionner même si le groupe a changé de prof entretemps.
        evaluations_profs = evaluations_profs.filter(prof_id=prof_id)
    if eleve_id:
        presences = presences.filter(eleve_id=eleve_id)
    if date_debut:
        presences = presences.filter(seance__date__gte=date_debut)
        evaluations_profs = evaluations_profs.filter(seance__date__gte=date_debut)
    if date_fin:
        presences = presences.filter(seance__date__lte=date_fin)
        evaluations_profs = evaluations_profs.filter(seance__date__lte=date_fin)

    nb_presences_total = presences.count()
    nb_evaluations_profs_total = evaluations_profs.count()

    context = {
        'presences': presences[:LIMITE_EVALUATIONS_LISTE],
        'nb_presences_total': nb_presences_total,
        'evaluations_profs': evaluations_profs[:LIMITE_EVALUATIONS_LISTE],
        'nb_evaluations_profs_total': nb_evaluations_profs_total,
        'limite': LIMITE_EVALUATIONS_LISTE,
        'groupes': Groupe.objects.all().order_by('nom'),
        'profs': profs_pour_filtre(afficher_archives, prof_id),
        'eleves': eleves_pour_filtre(afficher_archives, eleve_id),
        'filtres': {
            'groupe': groupe_id,
            'prof': prof_id,
            'eleve': eleve_id,
            'afficher_archives': afficher_archives,
            'date_debut': date_debut,
            'date_fin': date_fin,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_evaluations.html', context)


@role_required('admin', 'mshrif')
def admin_evaluation_detail(request, seance_id):
    from courses.models import Seance, Presence
    from evaluations.models import Evaluation

    seance = get_object_or_404(Seance, id=seance_id)
    presences = Presence.objects.filter(seance=seance).select_related('eleve__user').order_by('eleve__user__first_name')
    evaluation = Evaluation.objects.filter(seance=seance).select_related('superviseur__user').prefetch_related('notes__critere').first()

    context = {
        'seance': seance,
        'presences': presences,
        'evaluation': evaluation,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_evaluation_detail.html', context)


# ==================== CLASSEMENT MENSUEL DES PROFS (مؤطر/superviseur + مدير/admin) ====================
# Jamais visible par un prof — trié par moyenne d'évaluation du mois, avec un
# commentaire libre par prof/mois (evaluations.models.CommentaireMensuel).

@role_required('admin', 'superviseur', 'mshrif')
def classement_mensuel_profs(request):
    from django.utils import timezone
    from accounts.models import Prof, Superviseur
    from evaluations.models import CommentaireMensuel, Critere
    from evaluations.utils import moyenne_mensuelle_prof

    mois = request.GET.get('mois', '')
    aujourdhui = timezone.localdate()
    if mois:
        annee, _, num_mois = mois.partition('-')
        annee, num_mois = int(annee), int(num_mois)
    else:
        annee, num_mois = aujourdhui.year, aujourdhui.month
        mois = f'{annee:04d}-{num_mois:02d}'
    mois_reference = datetime.date(annee, num_mois, 1)

    # مشرف voit tous les profs (comme مدير) — au-dessus de tous dans la hiérarchie,
    # seul مؤطر/superviseur reste scopé à ses profs assignés.
    # Classement du mois en cours (pas un historique) — un prof archivé n'a plus
    # rien à y faire, chantier d'archivage du 2026-08-03.
    if request.user.role == 'superviseur':
        superviseur = get_object_or_404(Superviseur, user=request.user)
        profs = superviseur.profs_assignes.exclude(statut='archive').select_related('user')
    else:
        profs = Prof.actifs.select_related('user')

    commentaires = {
        c.prof_id: c for c in CommentaireMensuel.objects.filter(
            prof__in=profs, mois_reference=mois_reference
        )
    }

    lignes = []
    for prof in profs:
        resultat = moyenne_mensuelle_prof(prof, annee, num_mois)
        commentaire = commentaires.get(prof.id)
        lignes.append({
            'prof': prof,
            'nb_evaluations': resultat['nb_evaluations'],
            'moyenne_mensuelle': resultat['moyenne'],
            'majoration_mensuelle': prof.majoration_mensuelle,
            'commentaire': commentaire.commentaire if commentaire else '',
        })

    # Tri décroissant par moyenne, profs sans évaluation ce mois-ci en dernier.
    lignes.sort(key=lambda l: (l['moyenne_mensuelle'] is None, -(l['moyenne_mensuelle'] or 0)))

    BASE_TEMPLATE_PAR_ROLE = {
        'admin': 'dashboard/base_admin.html',
        'superviseur': 'dashboard/base_superviseur.html',
        'mshrif': 'dashboard/base_mshrif.html',
    }
    COULEUR_PAR_ROLE = {
        'admin': 'var(--color-role-admin-solid)',
        'superviseur': 'var(--color-role-superviseur-solid)',
        'mshrif': 'var(--color-role-mshrif-solid)',
    }

    context = {
        # Classement déjà trié avant pagination (Tâche 22 Partie F du 2026-07-26) —
        # la pagination ne fait que découper le classement déjà ordonné, le rang
        # affiché sur chaque page reste donc cohérent (page 2 = rangs 11-20, etc.).
        'lignes': paginer(request, lignes, 10),
        'mois': mois,
        'mois_reference': mois_reference,
        'base_template': BASE_TEMPLATE_PAR_ROLE[request.user.role],
        'couleur_role': COULEUR_PAR_ROLE[request.user.role],
        'lecture_stricte': request.user.role == 'mshrif',
        # Section repliable de référence — fusion de admin_criteres (voir plus haut),
        # toujours en lecture seule ici quel que soit le rôle (l'édition reste
        # réservée au مدير sur la page d'origine, restée intacte).
        'criteres': Critere.objects.all().order_by('ordre'),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/classement_mensuel_profs.html', context)


@role_required('admin', 'superviseur')
def classement_mensuel_commentaire(request, prof_id):
    from django.urls import reverse
    from accounts.models import Prof
    from evaluations.models import CommentaireMensuel

    prof = get_object_or_404(Prof, id=prof_id)
    if prof.statut == 'archive':
        messages.error(request, f'تعذر الحفظ: {prof.user.get_full_name()} مؤرشف.')
        return redirect('classement_mensuel_profs')
    mois = request.POST.get('mois', '')
    annee, _, num_mois = mois.partition('-')
    mois_reference = datetime.date(int(annee), int(num_mois), 1)

    CommentaireMensuel.objects.update_or_create(
        prof=prof,
        mois_reference=mois_reference,
        defaults={
            'commentaire': request.POST.get('commentaire', ''),
            'redige_par': request.user,
        },
    )
    messages.success(request, 'تم حفظ الملاحظة.')
    return redirect(f"{reverse('classement_mensuel_profs')}?mois={mois}")


# ==================== ADMIN — ASSIGNATION SUPERVISEURS ↔ PROFS ====================

@role_required('admin', 'mshrif')
def admin_superviseurs(request):
    """Liste des مؤطرين, symétrique à admin_eleves/admin_profs (Tâche du
    2026-08-07 : ajout recherche déjà existante + avatar + nb de groupes
    total). مдير et مشرف y ont déjà accès tous les deux (ce dernier en
    lecture seule, voir le template) ; chaque ligne pointe vers
    admin_superviseur_assignations, qui sert AUSSI de page détail depuis le
    chantier du 2026-08-06 (bloc info en lecture seule + liste de gestion) —
    pas de page détail séparée créée ici, ça duplicerait ce bloc.

    Volontairement PAS ajouté malgré la demande initiale, faute de champ en
    base :
    - Filtre par statut actif/archivé : Superviseur n'a aucun champ de statut
      ni système d'archivage (contrairement à Eleve/Prof) — ajouter ça serait
      un chantier à part entière (statut, blocage de connexion, invalidation
      de session...), pas juste un filtre de liste.
    - Colonne "ville" : ni Superviseur ni User n'ont de champ ville."""
    from django.db.models import Q, Count
    from accounts.models import Superviseur

    q = request.GET.get('q', '').strip()
    superviseurs = Superviseur.objects.select_related('user').annotate(
        nb_profs_assignes=Count('profs_assignes', distinct=True),
        nb_groupes_total=Count('profs_assignes__groupes', distinct=True),
    ).order_by('user__first_name')
    if q:
        superviseurs = superviseurs.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(user__email__icontains=q)
        )

    context = {
        'superviseurs': paginer(request, superviseurs, 10),
        'q': q,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_superviseurs.html', context)


@role_required('admin')
def admin_superviseur_ajouter(request):
    """Création directe d'un compte مؤطر par مدير — PAS de candidature/
    InscriptionSuperviseur préalable (contrairement à élève/prof) : ce
    formulaire crée le compte immédiatement. Corrigé le 2026-08-06 (manque
    signalé par le client) : utilisait encore l'ANCIEN patron (mot de passe
    affiché en clair dans un message flash Django, jamais de bouton WhatsApp)
    — le seul des 3 flux de création à ne jamais avoir été migré vers
    confirmation_creation_compte (PRG + WhatsApp) lors du chantier du
    2026-08-05 qui avait migré élève/prof. Réutilise cette même page de
    confirmation (type_compte='superviseur' déjà géré) plutôt que d'en
    dupliquer une nouvelle."""
    from django.contrib.auth import get_user_model
    from accounts.models import Superviseur
    from inscriptions.views import _email_deja_utilise

    User = get_user_model()

    if request.method == 'POST':
        nom = request.POST.get('nom', '').strip()
        email = request.POST.get('email', '').strip()
        telephone = request.POST.get('telephone', '').strip()

        if _email_deja_utilise(email):
            messages.error(
                request,
                f'تعذر الإضافة: البريد الإلكتروني {email} مستخدم بالفعل من طرف حساب آخر أو طلب تسجيل قيد الدراسة.'
            )
            return render(request, 'dashboard/admin_superviseur_ajouter.html', {
                'old_nom': nom, 'old_email': email, 'old_telephone': telephone,
            })

        password_temp = generer_mot_de_passe_sequentiel()

        with transaction.atomic():
            # doit_changer_mot_de_passe=False : voir commentaire dans admin_valider_eleve.
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password_temp,
                first_name=nom,
                telephone=telephone,
                role='superviseur',
                doit_changer_mot_de_passe=False,
            )
            Superviseur.objects.create(user=user)

        envoyer_email_bienvenue(request, email, password_temp, nom)

        request.session['confirmation_creation_compte'] = {
            'type_compte': 'superviseur',
            'nom': nom,
            'email': email,
            'password': password_temp,
            'telephone': telephone,
            'redirect_url_name': 'admin_superviseurs',
        }
        return redirect('confirmation_creation_compte')

    return render(request, 'dashboard/admin_superviseur_ajouter.html')


@role_required('admin', 'mshrif')
@never_cache
def admin_superviseur_assignations(request, superviseur_id):
    """Page d'assignation profs↔مؤطر — مدير édite (cases à cocher), مشرف
    consulte en lecture seule (même template, 2 branches — voir
    admin_superviseur_assignations.html). Redessinée le 2026-08-06 (chantier
    groupé final, point 4) : avatar + nb de groupes déjà assignés en
    métadonnée pour chaque prof (utile au مدير pour juger la charge de
    travail avant d'assigner). @never_cache : même précaution que sur les
    pages de mot de passe (point 1) — évite qu'un bouton précédent du
    navigateur affiche un état d'assignation obsolète après une sauvegarde.

    "x - ✅" (point 2) : bug rapporté à nouveau malgré un premier test qui ne
    l'avait pas reproduit. Revérifié ici : le titre de admin_superviseur_
    assignations.html utilise directement {{ superviseur.user.get_full_name }}
    (aucune construction manuelle de chaîne, aucun "x" littéral nulle part
    dans ce fichier ni dans les 2 autres templates référençant profs_assignes
    — superviseur_profil.html, admin_superviseurs.html). Toujours pas
    reproduit après ce 2e passage. Cette page est de toute façon entièrement
    reconstruite ci-dessous (point 4) ; @never_cache ci-dessus élimine par
    ailleurs la piste la plus plausible restante (page mise en cache par le
    navigateur avant un correctif antérieur)."""
    from accounts.models import Superviseur, Prof
    from courses.models import Groupe
    from django.db.models import Count
    superviseur = get_object_or_404(Superviseur, id=superviseur_id)

    # Bloc d'info لecture seule (Tâche du 2026-08-06) : même requête que
    # superviseur_profil.html "المجموعات المسندة" (groupes_assignes), pour
    # que مدير voie d'un coup d'œil la situation actuelle avant de modifier
    # l'assignation en dessous. Réutilise dashboard/_liste_groupes_mesnad.html,
    # jamais dupliqué.
    groupes_actuels = Groupe.objects.filter(
        prof__in=superviseur.profs_assignes.all(), statut='actif'
    ).select_related('prof__user', 'creneau').annotate(
        nb_eleves=Count('eleves', distinct=True)
    ).order_by('nom')
    # Prof.actifs exclut les archivés de la liste à cocher — SAUF ceux déjà
    # assignés à ce مؤطر (gardés visibles, étiquetés "مؤرشف" dans le template)
    # pour ne pas les faire disparaître silencieusement d'un formulaire qui
    # remplace toute la liste à chaque sauvegarde (chantier du 2026-08-03).
    # nb_groupes annotée (pas .groupes.count() dans le template) : évite un
    # N+1 sur cette liste (point 8, audit de performance du même chantier).
    tous_les_profs = list(
        Prof.actifs.select_related('user')
        .annotate(nb_groupes=Count('groupes', distinct=True))
        .order_by('user__first_name')
    )
    profs_assignes_archives = superviseur.profs_assignes.filter(statut='archive').select_related('user').annotate(
        nb_groupes=Count('groupes', distinct=True)
    )
    tous_les_profs += [p for p in profs_assignes_archives if p not in tous_les_profs]

    if request.method == 'POST':
        # Revalidé côté serveur: n'accepte que des profs déjà actifs, ou déjà
        # assignés (pour ne pas désassigner un prof archivé par accident quand
        # son entrée reste cochée dans le formulaire soumis).
        ids_valides = {str(p.id) for p in tous_les_profs}
        profs_selectionnes = [pid for pid in request.POST.getlist('profs') if pid in ids_valides]
        superviseur.profs_assignes.set(profs_selectionnes)
        messages.success(request, f'تم تحديث المعلمين المُسندين إلى {superviseur.user.get_full_name()}.')
        return redirect('admin_superviseurs')

    profs_assignes_ids = set(superviseur.profs_assignes.values_list('id', flat=True))

    context = {
        'superviseur': superviseur,
        'profs': tous_les_profs,
        'profs_assignes_ids': profs_assignes_ids,
        'groupes_actuels': groupes_actuels,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_superviseur_assignations.html', context)


@role_required('admin', 'mshrif')
def superviseur_supprimer_definitivement(request, superviseur_id):
    """Rien ne bloque ici : après les migrations SET_NULL de ce chantier,
    toutes les relations de Superviseur (profs_assignes, Evaluation.superviseur,
    Seance.superviseur, CommentaireMensuel.redige_par) se détachent proprement
    sans effacer aucune donnée appartenant à un autre compte."""
    from accounts.models import Superviseur
    from evaluations.models import Evaluation

    superviseur = get_object_or_404(Superviseur, id=superviseur_id)

    if request.method != 'POST':
        return render(request, 'dashboard/admin_superviseur_supprimer_definitivement.html', {
            'superviseur': superviseur,
            'nb_profs_assignes': superviseur.profs_assignes.count(),
            'nb_evaluations': Evaluation.objects.filter(superviseur=superviseur).count(),
            'base_template': _base_template_admin_ou_mshrif(request),
        })

    confirmation = request.POST.get('confirmation_nom', '').strip()
    if confirmation != superviseur.user.email:
        messages.error(request, 'البريد الإلكتروني المُدخل لا يطابق بالضبط — لم يتم حذف أي شيء.')
        return redirect('admin_superviseurs')

    nom = superviseur.user.get_full_name()
    with transaction.atomic():
        superviseur.user.delete()

    messages.success(request, f'تم حذف حساب المؤطر {nom} نهائياً.')
    return redirect('admin_superviseurs')


# ==================== ADMIN — MODIFIER L'EMAIL D'UN UTILISATEUR ====================

@role_required('admin')
def admin_utilisateur_modifier_email(request, user_id):
    """Chantier du 2026-08-10 (partage d'email parent/enfant) : depuis
    admin_valider_eleve, plusieurs comptes élève actifs peuvent désormais
    partager le même email. Si le مدير change l'email de l'un d'eux, il faut
    décider si ça s'applique à lui seul ou à tous les comptes qui partagent
    actuellement son ANCIEN email — flux à 2 POST :
      1er POST (pas de 'portee' dans request.POST) : si l'ancien email de ce
      compte n'est partagé par personne, applique directement (comportement
      identique à avant ce chantier, aucune étape ajoutée). S'il EST partagé,
      n'applique rien encore — affiche un écran listant les autres comptes
      concernés et demandant explicitement la portée.
      2e POST ('portee' = 'un_seul' ou 'tous', renvoyé par cet écran) :
      applique enfin, à un seul compte ou à tous ceux qui partageaient
      l'ancien email, dans une transaction unique (tout ou rien)."""
    from django.contrib.auth import get_user_model
    from inscriptions.views import _email_deja_utilise

    User = get_user_model()
    utilisateur = get_object_or_404(User, id=user_id)
    next_url = _next_valide(request)

    if request.method == 'POST':
        nouvel_email = request.POST.get('nouvel_email', '').strip()
        confirmation_email = request.POST.get('confirmation_email', '').strip()
        portee = request.POST.get('portee')

        if not nouvel_email or nouvel_email != confirmation_email:
            messages.error(request, 'البريدان الإلكترونيان غير متطابقين.')
            return render(request, 'dashboard/admin_utilisateur_modifier_email.html', {
                'utilisateur': utilisateur,
                'next': next_url,
            })

        if nouvel_email == utilisateur.email:
            messages.info(request, 'لم يتغير البريد الإلكتروني.')
            return redirect(next_url)

        if _email_deja_utilise(nouvel_email, exclure_user_id=utilisateur.id):
            messages.error(
                request,
                f'تعذر التغيير: البريد الإلكتروني {nouvel_email} مستخدم بالفعل من طرف حساب آخر أو طلب تسجيل قيد الدراسة.'
            )
            return render(request, 'dashboard/admin_utilisateur_modifier_email.html', {
                'utilisateur': utilisateur,
                'next': next_url,
            })

        autres_comptes_meme_email = list(
            User.objects.filter(email=utilisateur.email).exclude(id=utilisateur.id).select_related()
        )

        if autres_comptes_meme_email and portee not in ('un_seul', 'tous'):
            # 1er POST sur un email partagé : rien n'est appliqué — on demande
            # explicitement la portée avant de toucher à quoi que ce soit.
            return render(request, 'dashboard/admin_utilisateur_modifier_email_confirmation_partage.html', {
                'utilisateur': utilisateur,
                'autres_comptes': autres_comptes_meme_email,
                'nouvel_email': nouvel_email,
                'next': next_url,
            })

        comptes_a_modifier = [utilisateur]
        if portee == 'tous':
            comptes_a_modifier += autres_comptes_meme_email

        ancien_email = utilisateur.email

        with transaction.atomic():
            for compte in comptes_a_modifier:
                # Préserve le suffixe technique du username (ex: "__2", voir
                # admin_valider_eleve) en ne remplaçant que le préfixe email —
                # username reste jamais affiché nulle part, mais doit rester
                # unique (contrainte Django native sur ce champ).
                compte.username = compte.username.replace(compte.email, nouvel_email, 1)
                compte.email = nouvel_email
                compte.save()
                _invalider_sessions_utilisateur(compte, request=request)

        # invalider_sessions_utilisateur : déconnexion immédiate de tous les
        # appareils — mécanisme réellement fonctionnel (vérifié par test réel,
        # pas seulement lecture de code, chantier du 2026-08-06 point 6),
        # gardé tel quel. envoyer_email_notification_changement_email reste
        # tenté (fire-and-forget, comme envoyer_email_bienvenue) mais Brevo
        # étant hors service actuellement, son résultat n'est plus utilisé
        # pour promettre quoi que ce soit à l'écran — voir
        # confirmation_modification_email, qui propose désormais un envoi
        # manuel via WhatsApp (point 5/6) plutôt qu'une promesse d'email.
        # Un seul envoi (au compte initialement ciblé), même si "tous" a été
        # choisi — tous les comptes concernés partagent la MÊME nouvelle
        # adresse, un 2e message à la même boîte serait redondant.
        envoyer_email_notification_changement_email(request, ancien_email, nouvel_email, utilisateur.get_full_name())

        request.session['confirmation_modification_email'] = {
            'user_id': utilisateur.id,
            'nom': utilisateur.get_full_name(),
            'nouvel_email': nouvel_email,
            'telephone': utilisateur.telephone,
            'role': utilisateur.role,
            'next': next_url,
            'nb_comptes_maj': len(comptes_a_modifier),
        }
        return redirect('confirmation_modification_email')

    return render(request, 'dashboard/admin_utilisateur_modifier_email.html', {
        'utilisateur': utilisateur,
        'next': next_url,
    })


@role_required('admin')
@never_cache
def confirmation_modification_email(request):
    """Page de confirmation affichée juste après un changement d'email
    (Tâche du 2026-08-06, point 6) — remplace la fausse promesse d'email
    automatique ("سيصله إشعار على بريده الجديد") par un bouton WhatsApp,
    Brevo étant hors service actuellement. Même patron PRG que
    confirmation_creation_compte / admin_utilisateur_reinitialiser_mot_de_passe :
    infos lues depuis la session puis immédiatement effacées. Réservée à
    مدير (comme admin_utilisateur_modifier_email qui l'alimente — le
    changement d'email n'est pas ouvert à مشرف)."""
    info = request.session.pop('confirmation_modification_email', None)
    if not info:
        return redirect('dashboard_admin')

    message_pret_a_envoyer = (
        "السلام عليكم ورحمة الله وبركاته\n"
        f"مرحبا {info['nom']}\n"
        "تم تحديث البريد الإلكتروني لحسابك، بريدك الجديد هو:\n"
        f"{info['nouvel_email']}\n"
        "المرجو استعماله عند تسجيل الدخول من الآن فصاعداً.\n"
        "بارك الله فيكم"
    )

    context = {
        'info': info,
        'message_pret_a_envoyer': message_pret_a_envoyer,
        'libelle_personne_contact': f"مع {LIBELLE_PERSONNE_CONTACT.get(info['role'], '')}",
    }
    return render(request, 'dashboard/confirmation_modification_email.html', context)


# ==================== ADMIN/MSHRIF — RÉINITIALISER UN MOT DE PASSE ====================
# Points 13/14/17, Tâche du 2026-08-04.
# Chantier du 2026-08-06 ("chantier groupé final", point 1) : never_cache
# (une réinitialisation ultérieure invaliderait un mot de passe déjà affiché ici
# — voir le bug ci-dessous) + boutons WhatsApp (point 5) + libellé de rôle
# partagé avec confirmation_creation_compte et confirmation_modification_email.

LIBELLE_PERSONNE_CONTACT = {'eleve': 'الطالب', 'prof': 'المعلم', 'superviseur': 'المؤطر'}


def construire_message_acceptation_whatsapp(nom, email, mot_de_passe):
    """Message WhatsApp d'acceptation — Chantier du 2026-08-15, texte fourni
    par le client. UNE SEULE définition, utilisée uniquement par
    confirmation_creation_compte (le seul écran qui affiche un compte qui
    vient d'être créé/accepté) — JAMAIS confondue avec construire_message_
    mdp_whatsapp (réutilisée, elle, par la réinitialisation de mot de passe :
    un mot de passe réinitialisé ne concerne pas une acceptation, le texte
    « تم قبولك للانضمام » n'y aurait aucun sens).

    Même texte que l'email d'acceptation (voir envoyer_email_bienvenue) —
    deux fonctions séparées car deux canaux avec des mécanismes d'envoi
    différents (send_mail vs lien wa.me pré-rempli affiché à l'écran), pas
    deux textes différents."""
    return (
        f"السلام عليكم ورحمة الله وبركاته،\n\n"
        f"حياك الله {nom}،\n\n"
        f"يسرنا إخبارك بأنه تم قبولك للانضمام إلى منصة زدني علماً، ونسأل الله أن يوفقك ويبارك في جهودك.\n\n"
        f"يمكنك الدخول إلى المنصة عبر الرابط:\n\n"
        f"{URL_PLATEFORME}\n\n"
        f"بيانات الدخول الخاصة بك:\n\n"
        f"البريد الإلكتروني:\n"
        f"{email}\n\n"
        f"كلمة المرور:\n"
        f"{mot_de_passe}\n\n"
        f"نسعد بانضمامك إلى زدني علماً، ونسأل الله أن يجعلها خطوة مباركة ونافعة.\n\n"
        f"بارك الله فيكم."
    )


def construire_message_mdp_whatsapp(email, mot_de_passe, nom=''):
    """Message WhatsApp UNIQUE pour tout écran communiquant un mot de passe
    (création de compte élève/prof/مؤطر, réinitialisation par مدير/مشرف) —
    Tâche du 2026-08-06 : un seul gabarit, jamais reformulé différemment
    d'un écran à l'autre, pour garantir la cohérence si modifié plus tard.
    Texte exact fourni par le client, à une exception près (voir nom
    ci-dessous).

    nom : ajouté au chantier du 2026-08-10 (partage d'email parent/enfant).
    Depuis ce chantier, plusieurs comptes élève peuvent partager le même
    بريد إلكتروني — sans le nom, le مدير qui envoie ce message ne peut plus
    savoir avec certitude à quel compte précis ce mot de passe appartient.
    Optionnel (nom='') pour ne rien changer aux appels qui n'ont pas cette
    info sous la main — la ligne n'apparaît alors simplement pas."""
    ligne_nom = f"الاسم: {nom}\n" if nom else ""
    return (
        "السلام عليكم\n"
        "حياك الله\n"
        f"{ligne_nom}"
        "هذا بريدك الالكتروني وهذه كلمة المرور\n"
        f"{email}\n"
        f"{mot_de_passe}\n"
        "بارك الله فيكم.."
    )


@role_required('admin', 'mshrif')
@never_cache
def admin_utilisateur_reinitialiser_mot_de_passe(request, user_id):
    """مدير ET مشرف peuvent réinitialiser le mot de passe d'un compte élève,
    prof ou مؤطر — JAMAIS celui d'un autre مدير/مشرف (vérifié ici, côté
    serveur, même si l'URL est appelée directement avec un ID manipulé).
    Le nouveau mot de passe n'est affiché qu'UNE SEULE FOIS (patron
    Post/Redirect/Get : généré au POST, stocké en session, lu puis
    immédiatement effacé — session.pop — au GET qui suit ; un rechargement
    de cette page ne le réaffiche jamais). Jamais stocké en clair : set_password
    hashe immédiatement, seul le hash atteint la base — la valeur en clair ne
    vit que le temps de cette requête + la traversée de session.

    @never_cache (Tâche du 2026-08-06) : un compte réel (ahmed naim) s'est
    retrouvé bloqué — ni son ancien ni son "nouveau" mot de passe ne
    fonctionnaient. Cause confirmée par test réel (pas de lecture de code) :
    le mécanisme lui-même est sain (une réinitialisation isolée invalide
    bien l'ancien mot de passe et le nouveau fonctionne immédiatement,
    prouvé par script de vérification avec un vrai login HTTP) — mais SI le
    مدير/مشرف réinitialise deux fois de suite (ex: il recharge/revient en
    arrière sur cette page après une première réinitialisation, croit que
    "rien ne s'est affiché" donc reclique), le premier mot de passe généré
    devient silencieusement invalide (le second l'écrase en base) sans
    aucun avertissement — s'il communique par erreur le PREMIER mot de passe
    (ex: via le bouton précédent du navigateur qui réaffiche une page mise
    en cache), ni l'ancien ni ce premier mot de passe ne fonctionnent plus.
    @never_cache empêche le navigateur de réafficher une version en cache de
    cette page (bouton précédent inclus) ; combiné à l'avertissement ajouté
    dans ForcerChangementMotDePasseMiddleware (autre cause possible de blocage
    silencieux, également corrigée) et aux boutons WhatsApp ci-dessous (qui
    évitent toute retranscription manuelle du mot de passe), ceci couvre les
    3 scénarios plausibles identifiés. Un seul compte est concerné à ce jour
    (vérifié : aucun autre compte n'a de mot_de_passe_reinitialise_par renseigné
    depuis le chantier mots de passe — pas de réparation en masse nécessaire)."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    User = get_user_model()
    utilisateur = get_object_or_404(User, id=user_id)
    next_url = _next_valide(request)

    if utilisateur.role not in ('eleve', 'prof', 'superviseur'):
        messages.error(request, 'لا يمكن إعادة تعيين كلمة مرور حساب مدير أو مشرف من هنا.')
        return redirect(next_url)

    if request.method == 'POST':
        nouveau_mdp = generer_mot_de_passe_sequentiel()
        utilisateur.set_password(nouveau_mdp)
        # Forcé explicitement à False (pas juste "laissé tel quel") : un
        # compte créé avant ce changement pourrait encore avoir True en
        # base (voir accounts.middleware.ForcerChangementMotDePasseMiddleware.
        # ROLES_EXEMPTES, qui l'ignore déjà pour ces 3 rôles, mais autant que
        # le champ reflète la réalité) — élève/prof/مؤطر ne passent JAMAIS
        # par un changement forcé, y compris après une réinitialisation.
        utilisateur.doit_changer_mot_de_passe = False
        utilisateur.mot_de_passe_reinitialise_par = request.user
        utilisateur.date_reinitialisation_mot_de_passe = timezone.now()
        utilisateur.save()
        _invalider_sessions_utilisateur(utilisateur, request=request)
        logger.info(
            "Mot de passe reinitialise pour %s (id=%s, role=%s) par %s (id=%s)",
            utilisateur.email, utilisateur.id, utilisateur.role, request.user.email, request.user.id,
        )
        request.session['mdp_reinitialise'] = {'user_id': utilisateur.id, 'mot_de_passe': nouveau_mdp}
        return redirect('admin_utilisateur_reinitialiser_mot_de_passe', user_id=utilisateur.id)

    mdp_genere = request.session.pop('mdp_reinitialise', None)
    if not mdp_genere or mdp_genere.get('user_id') != utilisateur.id:
        mdp_genere = None
    mot_de_passe_affiche = mdp_genere.get('mot_de_passe') if mdp_genere else None

    # Gabarit UNIQUE (Tâche du 2026-08-06) — voir construire_message_mdp_whatsapp.
    message_pret_a_envoyer = None
    if mot_de_passe_affiche:
        message_pret_a_envoyer = construire_message_mdp_whatsapp(
            utilisateur.email, mot_de_passe_affiche, nom=utilisateur.get_full_name()
        )

    contact_admin = _contact_admin_fixe()

    context = {
        'utilisateur': utilisateur,
        'next': next_url,
        'mdp_genere': mot_de_passe_affiche,
        'message_pret_a_envoyer': message_pret_a_envoyer,
        'libelle_personne_contact': f"مع {LIBELLE_PERSONNE_CONTACT.get(utilisateur.role, '')}",
        # Correction du 2026-08-14 (même bug qu'ailleurs, confirmé en test
        # manuel) : UN SEUL contact مدير résolu via _contact_admin_fixe() (le
        # plus ancien compte role='admin' avec téléphone renseigné) — pas TOUS
        # les comptes role='admin'. La comparaison d'id ci-dessous remplace
        # l'ancien .exclude(id=request.user.id) : cette vue est accessible à
        # مدير ET مشرف — sans elle, un مدير qui réinitialise lui-même un
        # mot de passe se verrait proposer un bouton "تواصل مع المدير"
        # pointant vers... lui-même. مشرف continue de voir le bouton
        # normalement (jamais exclu, puisqu'il n'est jamais dans role='admin').
        'admins': [contact_admin] if contact_admin and contact_admin.id != request.user.id else [],
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_utilisateur_reinitialiser_mot_de_passe.html', context)


# ==================== ADMIN / مشرف — MON COMPTE ====================

def _traiter_changement_email_compte(request):
    """Logique de changement d'email en self-service — partagée entre
    admin_mon_compte et mshrif_mon_compte (Tâche du 2026-08-08, point 1 :
    le مشرف gagne la même capacité que le مدير) pour ne pas la dupliquer
    une 2e fois. Pose les messages Django (succès/erreur), ne redirige
    PAS elle-même — c'est à l'appelant de le faire vers SA propre page
    ('admin_mon_compte' ou 'mshrif_mon_compte'), pour ne jamais renvoyer
    un مشرف vers une page admin (et inversement) après un POST.

    Ne touche PAS au changement de mot de passe forcé
    (accounts.views.password_change_view) : flux et rôles différents
    (bloque 3 rôles entiers, jamais atteint via cette page), volontairement
    resté séparé plutôt que fusionné."""
    from inscriptions.views import _email_deja_utilise

    mot_de_passe = request.POST.get('mot_de_passe_email', '')
    nouvel_email = request.POST.get('nouvel_email', '').strip()
    confirmation_email = request.POST.get('confirmation_email', '').strip()

    if not request.user.check_password(mot_de_passe):
        messages.error(request, 'كلمة المرور غير صحيحة.')
    elif not nouvel_email or nouvel_email != confirmation_email:
        messages.error(request, 'البريدان الإلكترونيان غير متطابقين.')
    elif nouvel_email == request.user.email:
        messages.info(request, 'لم يتغير البريد الإلكتروني.')
    elif _email_deja_utilise(nouvel_email, exclure_user_id=request.user.id):
        messages.error(request, f'تعذر التغيير: البريد الإلكتروني {nouvel_email} مستخدم بالفعل.')
    else:
        ancien_email = request.user.email
        request.user.email = nouvel_email
        request.user.username = nouvel_email
        request.user.save()
        _invalider_sessions_utilisateur(request.user, request=request)
        email_envoye = envoyer_email_notification_changement_email(request, ancien_email, nouvel_email, request.user.get_full_name())
        if email_envoye:
            messages.success(request, f'تم تغيير بريدك الإلكتروني إلى {nouvel_email} بنجاح.')
        else:
            messages.warning(request, f'تم تغيير بريدك الإلكتروني إلى {nouvel_email} بنجاح، لكن تعذر إرسال بريد الإشعار.')


@role_required('admin')
def admin_mon_compte(request):
    if request.method == 'POST' and request.POST.get('action') == 'contact':
        nom_complet = request.POST.get('nom_complet', '').strip()
        description_courte = request.POST.get('description_courte', '').strip()
        whatsapp_brut = request.POST.get('whatsapp', '').strip()

        chiffres_whatsapp = ''.join(c for c in whatsapp_brut if c.isdigit())
        if whatsapp_brut and not (9 <= len(chiffres_whatsapp) <= 15):
            messages.error(
                request,
                'رقم الواتساب غير صالح — يجب أن يحتوي على عدد أرقام صحيح '
                '(مثال: 0663394165 أو 212663394165).'
            )
            return redirect('admin_mon_compte')

        request.user.first_name = nom_complet
        request.user.last_name = ''
        request.user.description_courte = description_courte
        request.user.telephone = whatsapp_brut
        request.user.save(update_fields=['first_name', 'last_name', 'description_courte', 'telephone'])
        messages.success(request, 'تم تحديث معلومات التواصل بنجاح.')
        return redirect('admin_mon_compte')

    if request.method == 'POST' and request.POST.get('action') == 'email':
        _traiter_changement_email_compte(request)
        return redirect('admin_mon_compte')

    if request.method == 'POST' and request.POST.get('action') == 'password':
        from django.contrib.auth import update_session_auth_hash

        ancien = request.POST.get('ancien_mot_de_passe')
        nouveau = request.POST.get('nouveau_mot_de_passe')
        confirmation = request.POST.get('confirmation')

        if not request.user.check_password(ancien):
            messages.error(request, 'كلمة المرور الحالية غير صحيحة.')
        elif nouveau != confirmation:
            messages.error(request, 'كلمتا المرور الجديدتان غير متطابقتين.')
        elif len(nouveau) < 8:
            messages.error(request, 'يجب أن تحتوي كلمة المرور الجديدة على 8 أحرف على الأقل.')
        else:
            request.user.set_password(nouveau)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
        return redirect('admin_mon_compte')

    return render(request, 'dashboard/admin_mon_compte.html')


@role_required('mshrif')
def mshrif_mon_compte(request):
    """حسابي — équivalent مشرف de admin_mon_compte (Tâche du 2026-08-08,
    point 1). Le مشرف n'avait jusqu'ici accès qu'au changement de mot de
    passe (accounts.views.password_change_view, page séparée, toujours
    utilisée pour le changement FORCÉ — voir ForcerChangementMotDePasse
    Middleware, inchangée) — sans aucune capacité de changer son email.
    Fusionne email + mot de passe sur UNE page, comme pour le مدير, en
    réutilisant les mêmes partials (_carte_changer_email.html,
    _carte_changer_mot_de_passe.html) pour un rendu garanti identique.

    PAS de section "معلومات التواصل" (contrairement à admin_mon_compte) :
    volontairement absente — cette section alimente le bouton de contact
    WhatsApp affiché aux élèves/profs/مؤطرين, qui ne voient QUE le مدير
    (jamais le مشرف), donc sans objet ici."""
    if request.method == 'POST' and request.POST.get('action') == 'email':
        _traiter_changement_email_compte(request)
        return redirect('mshrif_mon_compte')

    if request.method == 'POST' and request.POST.get('action') == 'password':
        from django.contrib.auth import update_session_auth_hash

        ancien = request.POST.get('ancien_mot_de_passe')
        nouveau = request.POST.get('nouveau_mot_de_passe')
        confirmation = request.POST.get('confirmation')

        if not request.user.check_password(ancien):
            messages.error(request, 'كلمة المرور الحالية غير صحيحة.')
        elif nouveau != confirmation:
            messages.error(request, 'كلمتا المرور الجديدتان غير متطابقتين.')
        elif len(nouveau) < 8:
            messages.error(request, 'يجب أن تحتوي كلمة المرور الجديدة على 8 أحرف على الأقل.')
        else:
            request.user.set_password(nouveau)
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
        return redirect('mshrif_mon_compte')

    return render(request, 'dashboard/mshrif_mon_compte.html')


# ==================== RECHERCHE GLOBALE (مدير/مشرف) — Chantier du 2026-08-14 ====================

@role_required('admin', 'mshrif')
def api_recherche_globale(request):
    """Endpoint UNIQUE (A3) — dispatche côté serveur sur les 4 modèles via
    dashboard.recherche.rechercher_tout (toute la logique de filtrage/tri y
    vit, ce module ne fait que l'appeler et sérialiser). Permission déjà
    garantie par le décorateur : mدير et مشرف ont un accès identique aux 4
    querysets sous-jacents (voir docstring de dashboard.recherche), donc rien
    à filtrer en plus ici selon request.user.role.

    GET ?q=<terme> — pas de POST, pas d'effet de bord, safe à appeler depuis
    toutes les pages du dashboard (barre de recherche dans le template de
    base, voir base_admin.html/base_mshrif.html)."""
    from django.http import JsonResponse

    from dashboard.recherche import rechercher_tout
    from dashboard.templatetags.libelles_arabes import MOIS_AR

    q = request.GET.get('q', '')
    mois, categories = rechercher_tout(q)

    mois_payload = None
    if mois:
        annee, num_mois = mois.split('-')
        mois_payload = {
            'valeur': mois,
            'libelle': f'{MOIS_AR.get(int(num_mois), num_mois)} {annee}',
            'url': f"{reverse('bilans_mensuels')}?mois={mois}",
        }

    return JsonResponse({
        'mois': mois_payload,
        'categories': categories,
    })
