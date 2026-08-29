import datetime
import logging
import secrets

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.db import transaction
# Alias volontairement PAS "_" : ce fichier utilise déjà "_" comme variable
# jetable un peu partout (ex: "annee, _, num_mois = mois.partition('-')")
# — un import "gettext as _" serait silencieusement écrasé dans ces
# fonctions et casserait tout appel _() placé après ce genre de ligne.
from django.utils.translation import gettext as gettext_, gettext_lazy as gettext_lazy_
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST
from accounts.decorators import role_required
from accounts.services import (
    invalider_sessions_utilisateur as _invalider_sessions_utilisateur,
    archiver_eleve, reactiver_eleve, archiver_prof, reactiver_prof,
    profs_pour_filtre, eleves_pour_filtre,
)
from core.utils import paginer
from inscriptions.models import InscriptionEleve

# Chantier i18n du 2026-08-28 : gettext_lazy (pas gettext_ eager ci-dessus) —
# cette liste est construite UNE SEULE FOIS à l'import du module, un gettext_
# eager figerait la langue active à ce moment-là pour toujours. gettext_lazy_
# renvoie un proxy résolu à l'AFFICHAGE (langue de la requête en cours), même
# mécanisme que Creneau.JOUR_CHOICES (courses.models) dont les 7 libellés
# sont d'ailleurs identiques (même msgid, une seule traduction à fournir).
JOURS_SEMAINE_AR = [
    gettext_lazy_('الاثنين'), gettext_lazy_('الثلاثاء'), gettext_lazy_('الأربعاء'), gettext_lazy_('الخميس'),
    gettext_lazy_('الجمعة'), gettext_lazy_('السبت'), gettext_lazy_('الأحد'),
]

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
    """Récupère un ?next= sûr (chemin interne au dashboard uniquement, jamais
    une URL externe — protection open-redirect), sinon retombe sur une page
    par défaut. Élargi de '/dashboard/admin/' à '/dashboard/' (Tâche du
    2026-08-18 bis) : ajouter_note_personnelle et consorts sont désormais
    utilisables depuis n'importe quel dashboard (mes_notes_personnelles,
    accessible à tous les rôles), pas seulement les pages admin — élargir le
    préfixe ne fait qu'AUTORISER plus de chemins internes, aucun appelant
    existant ne peut donc régresser."""
    from django.urls import reverse
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if next_url.startswith('/dashboard/'):
        return next_url
    return reverse(defaut)


@role_required('admin', 'mshrif', 'eleve', 'prof', 'superviseur')
def ajouter_note_personnelle(request, user_id):
    """Ajoute une note au carnet personnel (Tâche du 2026-08-18, élargie le
    même jour à un bloc-notes personnel pour tous) que request.user tient
    sur le profil de l'utilisateur user_id (profil_user est un simple User,
    voir accounts.models.NotePersonnelle.__doc__). POST only, auteur =
    request.user TOUJOURS (jamais un id envoyé par le client) : cette note
    n'appartient qu'à son auteur, aucune autre personne consultant le même
    profil ne la verra.

    Deux usages du MÊME modèle/de la MÊME vue, distingués par qui est ciblé :
      - مدير/مشرف écrivent une note sur le profil de N'IMPORTE QUEL élève/
        prof/مؤطر qu'ils consultent (comportement d'origine, inchangé) ;
      - tout autre rôle ne peut écrire QUE sur SON PROPRE profil (bloc-notes
        personnel "ملاحظاتي", voir mes_notes_personnelles) — jamais sur
        celui d'un tiers, aucune exception."""
    from django.http import HttpResponseForbidden
    from accounts.models import User, NotePersonnelle

    profil_user = get_object_or_404(User, id=user_id)
    if request.user.role not in ('admin', 'mshrif') and profil_user.id != request.user.id:
        return HttpResponseForbidden('لا يمكنك كتابة ملاحظة على ملف شخص آخر.')

    if request.method == 'POST':
        titre = request.POST.get('titre', '').strip()
        contenu = request.POST.get('contenu', '').strip()
        if contenu:
            NotePersonnelle.objects.create(
                profil_user=profil_user, auteur=request.user, titre=titre, contenu=contenu
            )
            messages.success(request, 'تمت إضافة الملاحظة.')
        else:
            messages.error(request, 'لا يمكن إضافة ملاحظة فارغة.')
    return redirect(_next_valide(request, defaut='admin_eleves'))


@role_required('admin', 'mshrif', 'eleve', 'prof', 'superviseur')
@require_POST
def modifier_note_personnelle(request, note_id):
    """Modifie une note personnelle — STRICTEMENT réservée à son propre
    auteur (vérification serveur, jamais une confiance dans le fait que le
    bouton "تعديل" n'était affiché QUE sur ses propres notes côté template) —
    même principe que chat.views.chat_supprimer_message."""
    from django.http import HttpResponseForbidden
    from accounts.models import NotePersonnelle

    note = get_object_or_404(NotePersonnelle, id=note_id)
    if note.auteur_id != request.user.id:
        return HttpResponseForbidden('لا يمكنك تعديل ملاحظة كتبها شخص آخر.')

    titre = request.POST.get('titre', '').strip()
    contenu = request.POST.get('contenu', '').strip()
    if contenu:
        note.titre = titre
        note.contenu = contenu
        note.save(update_fields=['titre', 'contenu', 'date_modification'])
        messages.success(request, 'تم تعديل الملاحظة.')
    else:
        messages.error(request, 'لا يمكن أن تكون الملاحظة فارغة.')
    return redirect(_next_valide(request, defaut='admin_eleves'))


@role_required('admin', 'mshrif', 'eleve', 'prof', 'superviseur')
@require_POST
def supprimer_note_personnelle(request, note_id):
    """Supprime une note personnelle — même garde STRICTE que
    modifier_note_personnelle ci-dessus (auteur == request.user)."""
    from django.http import HttpResponseForbidden
    from accounts.models import NotePersonnelle

    note = get_object_or_404(NotePersonnelle, id=note_id)
    if note.auteur_id != request.user.id:
        return HttpResponseForbidden('لا يمكنك حذف ملاحظة كتبها شخص آخر.')

    note.delete()
    messages.success(request, 'تم حذف الملاحظة.')
    return redirect(_next_valide(request, defaut='admin_eleves'))


_BASE_TEMPLATE_PAR_ROLE = {
    'eleve': 'dashboard/base_eleve.html',
    'prof': 'dashboard/base_prof.html',
    'superviseur': 'dashboard/base_superviseur.html',
    'admin': 'dashboard/base_admin.html',
    'mshrif': 'dashboard/base_mshrif.html',
}


@role_required('admin', 'mshrif', 'eleve', 'prof', 'superviseur')
def mes_notes_personnelles(request):
    """Page "ملاحظاتي" (Tâche du 2026-08-18 bis) — bloc-notes personnel que
    CHAQUE utilisateur, quel que soit son rôle, tient pour LUI-MÊME. Réutilise
    TEL QUEL le modèle accounts.NotePersonnelle déjà construit pour le carnet
    admin/مشرف sur les profils qu'ils consultent — ici profil_user == auteur
    == request.user, un simple cas particulier du même modèle, aucune
    duplication de schéma ni de vue de rendu (même partial
    _carnet_notes_personnelles.html, déjà strictement privé par construction :
    filtré sur auteur=request.user, donc personne d'autre — même pas
    مدير/مشرف — ne voit jamais ces notes)."""
    from accounts.models import NotePersonnelle

    context = {
        'notes_personnelles': NotePersonnelle.objects.filter(
            profil_user=request.user, auteur=request.user
        ),
        'base_template': _BASE_TEMPLATE_PAR_ROLE[request.user.role],
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/mes_notes_personnelles.html', context)


@role_required('eleve', 'prof', 'admin', 'mshrif')
def mes_notifications(request):
    """Page "عرض الكل" du panneau 🔔 الإشعارات (lien en bas du dropdown, voir
    dashboard/_header_raccourcis.html) — mêmes données que le dropdown, sans
    plafond d'affichage par groupe (limite=dashboard.notifications.
    LIMITE_FETCH au lieu de LIMITE_PAR_GROUPE). Ne marque RIEN comme lu ici
    (contrairement aux "pages cibles" elles-mêmes) : cette page n'est qu'une
    VUE D'ENSEMBLE qui pointe vers les vraies pages cibles — c'est en
    cliquant un événement (donc en arrivant sur eleve_seances/eleve_cartable/
    admin_inscription_eleve_detail/etc.) que la lecture se marque, jamais en
    survolant cette liste.

    admin/mshrif ajoutés au chantier du 2026-08-24 (voir dashboard.
    notifications.notifications_direction) — même page, juste une 3e branche."""
    from dashboard.notifications import notifications_eleve, notifications_prof, notifications_direction, LIMITE_FETCH

    if request.user.role == 'eleve':
        from accounts.models import Eleve
        eleve = get_object_or_404(Eleve, user=request.user)
        notif_groupes, notif_total = notifications_eleve(eleve, request.user, limite=LIMITE_FETCH)
        base_template = 'dashboard/base_eleve.html'
    elif request.user.role == 'prof':
        from accounts.models import Prof
        prof = get_object_or_404(Prof, user=request.user)
        notif_groupes, notif_total = notifications_prof(prof, request.user, limite=LIMITE_FETCH)
        base_template = 'dashboard/base_prof.html'
    else:  # 'admin' ou 'mshrif'
        notif_groupes, notif_total = notifications_direction(request.user, limite=LIMITE_FETCH)
        base_template = _base_template_admin_ou_mshrif(request)

    return render(request, 'dashboard/mes_notifications.html', {
        'notif_groupes': notif_groupes,
        'notif_total': notif_total,
        'base_template': base_template,
    })


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


def _creer_compte_prof(inscription):
    """Crée le compte User+Prof à partir d'une InscriptionProf — logique EXACTEMENT
    reprise de l'ancien corps de mshrif_valider_prof_final (extraite ici, Chantier
    d'ajout manuel du 2026-08-27), pour que les 2 points d'entrée qui créent
    réellement le compte final créent le compte de façon strictement identique,
    jamais 2 logiques qui pourraient diverger :
    - mshrif_valider_prof_final : validation finale étape 2/2 d'une candidature
      déjà pré-validée par le مدير (statut='validee_directeur').
    - admin_prof_ajouter_manuel : ajout manuel direct PAR le مشرف lui-même
      (statut créé directement à 'valide' — aucune attente, le مشرف est la
      dernière autorité du workflow, rien au-dessus de lui à faire attendre).

    Ne fait AUCUNE vérification de statut ni de conflit email — l'appelant reste
    responsable de ses propres gardes (voir mshrif_valider_prof_final pour le
    modèle des messages d'erreur associés). Retourne (prof, password_temp)."""
    from accounts.models import Prof
    from accounts.services import generer_presentation_publique
    from courses.utils import matrice_vers_lignes
    from django.contrib.auth import get_user_model

    User = get_user_model()
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
            # Chantier du 2026-08-27 — copiée telle quelle depuis la
            # candidature (voir InscriptionProf.charte_acceptee.__doc__) :
            # False/None pour un ajout manuel (inscription créée sans passer
            # par le formulaire public inscriptions.views.inscription_prof,
            # qui seul impose cette case), True/horodatée pour toute
            # candidature publique validée (bloquée sinon dès la soumission).
            charte_acceptee=inscription.charte_acceptee,
            date_acceptation_charte=inscription.date_acceptation_charte,
        )
        # Chantier du 2026-08-27 — voir accounts.models.Prof.presentation_publique
        # et accounts.services.generer_presentation_publique : générée une seule
        # fois ici, à la création du compte, jamais réécrite automatiquement
        # ensuite si مدير/مشرف la modifient à la main.
        prof.presentation_publique = generer_presentation_publique(prof)
        prof.save(update_fields=['presentation_publique'])

        matrice_vers_lignes(prof, inscription.disponibilites)

        inscription.statut = 'valide'
        inscription.save()

    return prof, password_temp


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

    # Panneau 🔔 الإشعارات (Chantier notifications du 2026-08-19) — calculé
    # UNIQUEMENT ici (page d'accueil), jamais en context processor global :
    # voir dashboard.notifications.__doc__ pour le choix d'architecture et
    # son coût réel.
    from dashboard.notifications import notifications_prof
    notif_groupes, notif_total = notifications_prof(prof, request.user)

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
        'notif_groupes': notif_groupes,
        'notif_total': notif_total,
    }
    return render(request, 'dashboard/prof.html', context)


@role_required('prof')
def prof_groupes(request):
    from accounts.models import Prof
    from chat.permissions import groupes_chat_accessibles_ids
    from courses.models import Groupe

    prof = get_object_or_404(Prof, user=request.user)
    groupes = Groupe.objects.filter(prof=prof).prefetch_related('eleves__user')

    return render(request, 'dashboard/prof_groupes.html', {
        'prof': prof,
        'groupes': groupes,
        # Icône 💬 chat (Chantier icône-chat du 2026-08-18) — voir
        # chat.permissions.groupes_chat_accessibles_ids.__doc__.
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
    })


@role_required('prof')
def prof_groupe_detail(request, groupe_id):
    from accounts.models import Prof
    from chat.permissions import peut_voir_chat_groupe
    from courses.models import Groupe

    prof = get_object_or_404(Prof, user=request.user)
    groupe = get_object_or_404(Groupe, id=groupe_id, prof=prof)

    return render(request, 'dashboard/prof_groupe_detail.html', {
        'prof': prof,
        'groupe': groupe,
        'peut_voir_chat': peut_voir_chat_groupe(request.user, groupe),
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

    # Tâche du 2026-08-17 : lien_effectif (Seance) tient compte d'une exception
    # de lien posée uniquement pour CETTE séance (voir Seance.lien_effectif) —
    # identique à seance.groupe.lien_reunion tant qu'aucune exception n'est
    # posée, donc aucun changement de comportement pour une séance normale.
    return redirect(seance.lien_effectif)


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

            # Critère ينتقل/يعيد (Tâche du 2026-08-18) — 'valide' par défaut si
            # rien n'est coché (comportement historique inchangé). On ignore
            # toute valeur POST qui ne serait pas l'une des 2 choix valides
            # plutôt que de faire confiance au client.
            resultat_memorisation = request.POST.get(f'resultat_memo_{eleve.id}', 'valide')
            if resultat_memorisation not in dict(Presence.RESULTAT_CHOICES):
                resultat_memorisation = 'valide'
            resultat_revision = request.POST.get(f'resultat_rev_{eleve.id}', 'valide')
            if resultat_revision not in dict(Presence.RESULTAT_CHOICES):
                resultat_revision = 'valide'

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
                    'resultat_memorisation': resultat_memorisation,
                    'resultat_revision': resultat_revision,
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
    groupes = Groupe.objects.filter(prof=prof, statut='actif')\
        .select_related('creneau').prefetch_related('creneau__slots')

    # Grille jours×heures réelle (Tâche 12 du 2026-07-25) — remplace la liste
    # de cartes, même patron que _grille_disponibilites.html (jours/heures
    # déjà factorisés dans courses.utils, réutilisés tels quels). Une cellule
    # par (jour, heure), jamais de lookup dict[jour, heure] dans le template
    # (impossible en Django templates) — donc construite ici sous forme de
    # lignes de cellules déjà dans l'ordre des colonnes.
    # Boucle sur creneau.slots.all() (1 à N, chantier de généralisation N
    # séances/semaine) au lieu du couple figé jour_1/jour_2.
    occupation = {}
    for groupe in groupes:
        creneau = groupe.creneau
        if not creneau:
            continue
        for slot in creneau.slots.all():
            for h in _heures_couvertes(slot.heure_debut, slot.heure_fin):
                occupation[(slot.jour, h)] = groupe

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
        messages.success(request, gettext_('تم إرسال طلب تعديل الأوقات المتاحة للتدريس، بانتظار موافقة الإدارة.'))
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
    from chat.permissions import groupes_chat_accessibles_ids
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
        # Icône 💬 chat sur "مجموعاتي" (Chantier redesign icône-chat du
        # 2026-08-19) — voir chat.permissions.groupes_chat_accessibles_ids.__doc__.
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
    })


@role_required('prof')
def prof_remuneration(request):
    from accounts.models import Prof
    from courses.models import TarifRemunerationGroupe, TarifRemunerationIndividuel
    from courses.utils import calculer_remuneration_prof
    from django.utils import timezone

    prof = get_object_or_404(Prof, user=request.user)
    aujourdhui = timezone.localdate()
    # Volontairement: ni majoration_mensuelle ni aucune donnée de classement/
    # évaluation ne sont chargées ni passées ici — voir courses.utils.calculer_remuneration_prof.
    return render(request, 'dashboard/prof_remuneration.html', {
        'remuneration': calculer_remuneration_prof(prof),
        'tarifs_groupe': TarifRemunerationGroupe.objects.filter(est_actif=True).order_by('tranche_age', 'nb_slots'),
        'tarifs_individuel': TarifRemunerationIndividuel.objects.all().order_by('tranche_age'),
        'aujourdhui': aujourdhui,
    })


@role_required('prof')
def prof_charte(request):
    """Lecture seule du ميثاق التدريس côté prof — Chantier du 2026-08-27 :
    l'acceptation se fait désormais au moment de la candidature (dernier champ
    d'inscriptions.views.inscription_prof, bloquant), plus jamais depuis cet
    espace. Cette page n'affiche donc plus que le contenu de la charte, sans
    aucune case à cocher ni option d'accepter/refuser — voir
    accounts.models.Prof.charte_acceptee.__doc__ pour l'historique."""
    from accounts.models import get_charte

    return render(request, 'dashboard/prof_charte.html', {
        'charte': get_charte(),
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

    # Marque le type 'hakiba' comme lu (panneau 🔔 الإشعارات, Chantier
    # notifications du 2026-08-19) — voir dashboard.notifications.__doc__.
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'hakiba')

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
    compris le contact). Lu par eleve_prof_detail.html ET, depuis le
    Chantier du 2026-08-27 (afficher_presentation_wizard uniquement), par
    templates/inscriptions/wizard_groupe.html."""
    from accounts.models import get_visibilite_prof

    CHAMPS = [
        'afficher_contact', 'afficher_ville', 'afficher_certifications',
        'afficher_niveau_memorisation', 'afficher_type_eleve_preference',
        'afficher_langues', 'afficher_outils_communication',
        'afficher_parcours_scolaire', 'afficher_parcours_educatif',
        'afficher_travail_actuel', 'afficher_presentation_wizard',
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

        # Chantier du moteur d'inscription configurable — délais anciennement
        # non configurables nulle part (10 jours pour le paiement n'existait
        # même pas en dur dans le code avant ce chantier, voir l'audit
        # préalable). Même patron de validation que admin_reglage_retention_
        # chat.duree_retention_jours : entier >= 1, sinon message d'erreur et
        # AUCUN champ du formulaire n'est sauvegardé (tout ou rien, pas de
        # sauvegarde partielle qui laisserait les toggles ouverte_* enregistrés
        # mais pas les délais).
        try:
            delai_paiement = int(request.POST.get('delai_paiement_jours', 0))
            delai_contact = int(request.POST.get('delai_contact_heures', 0))
        except ValueError:
            messages.error(request, 'يرجى إدخال أرقام صحيحة للمهل الزمنية.')
            return redirect('admin_gestion_inscriptions')
        if delai_paiement < 1 or delai_contact < 1:
            messages.error(request, 'يجب أن تكون كل مهلة زمنية يوماً/ساعة واحدة على الأقل.')
            return redirect('admin_gestion_inscriptions')
        parametres.delai_paiement_jours = delai_paiement
        parametres.delai_contact_heures = delai_contact

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
        # Tâche du 2026-08-17 (Phase 2 puis Phase 3, audit UX liens Meet) : TOUS
        # les groupes ACTIFS sans lien, avec OU SANS créneau (corrigé en Phase 3 —
        # un groupe sans créneau est un problème réel, pas un cas à ignorer, voir
        # courses.views.liens_meet_list). Un seul chiffre discret, pas une
        # nouvelle grosse carte, pour ne pas casser la composition existante de
        # la page (voir templates/dashboard/admin.html, à côté du lien
        # "متابعة الالتزام").
        'groupes_sans_lien_meet': Groupe.actifs.filter(lien_reunion='').count(),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    # Panneau 🔔 الإشعارات étendu au مدير/مشرف (chantier du 2026-08-24) —
    # voir dashboard.notifications.notifications_direction.__doc__.
    from dashboard.notifications import notifications_direction
    notif_groupes, notif_total = notifications_direction(request.user)
    context['notif_groupes'] = notif_groupes
    context['notif_total'] = notif_total
    return render(request, 'dashboard/admin.html', context)


@role_required('admin', 'mshrif')
def admin_inscriptions(request):
    """Liste unique des candidatures en attente, élèves et profs mélangés
    et triés par date de soumission — chaque ligne porte son propre type
    (voir type_demande, posé dynamiquement ici, pas un champ du modèle)
    pour que le template sache quel badge et quelles actions afficher."""
    from django.db.models import Q
    from inscriptions.models import InscriptionProf

    type_filtre = request.GET.get('type', '')
    q = request.GET.get('q', '').strip()

    eleves = []
    if type_filtre != 'prof':
        eleves_qs = InscriptionEleve.objects.filter(statut='en_attente')
        if q:
            eleves_qs = eleves_qs.filter(
                Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(email__icontains=q)
            )
        eleves = list(eleves_qs.order_by('-date_soumission'))
        for e in eleves:
            e.type_demande = 'eleve'

    profs = []
    if type_filtre != 'eleve':
        profs_qs = InscriptionProf.objects.filter(statut='en_attente')
        if q:
            profs_qs = profs_qs.filter(
                Q(nom__icontains=q) | Q(prenom__icontains=q) | Q(email__icontains=q)
            )
        profs = list(profs_qs.order_by('-date_soumission'))
        for p in profs:
            p.type_demande = 'prof'

    inscriptions = sorted(eleves + profs, key=lambda ins: ins.date_soumission, reverse=True)

    context = {
        'inscriptions': paginer(request, inscriptions, 10),
        'type_filtre': type_filtre,
        'q': q,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    # Page cible du panneau 🔔 "طلبات تسجيل جديدة" (chantier du 2026-08-24,
    # voir dashboard.notifications.notifications_direction) — juste avant le
    # render, jamais avant (au cas où une future évolution de cette vue
    # redirigerait plus tôt sans jamais afficher la page, même précaution que
    # les autres appelants de marquer_visite).
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'demandes_inscription')
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

        # Chantier du moteur d'inscription configurable (Étape 5E, engagement
        # explicite pris envers le client) : rattache automatiquement le
        # nouvel Eleve au groupe choisi PENDANT la candidature (registration.
        # utils.inscrire_eleve, InscriptionEleve.groupe_choisi) — SI ce choix
        # est encore valable AUJOURD'HUI, jamais fait confiance tel quel (le
        # groupe a pu être archivé/supprimé/rempli entre la candidature et la
        # validation, parfois des jours plus tard). raison_incompatibilite_
        # groupe est la MÊME fonction, avec les MÊMES règles bloquantes, que
        # celle utilisée par l'ajout manuel (courses.views.groupe_ajouter_eleve)
        # — aucune logique dupliquée. Si le choix n'est plus valable, RIEN
        # n'est fait ici silencieusement : un message avertit le مدير/مشرف
        # juste après la création du compte, pour qu'il assigne manuellement.
        resultat_groupe_choisi = None
        if inscription.groupe_choisi is not None:
            from courses.utils import raison_incompatibilite_groupe
            from courses.views import _ajouter_eleve_au_groupe

            raison = raison_incompatibilite_groupe(eleve, inscription.groupe_choisi)
            if raison is None:
                _ajouter_eleve_au_groupe(eleve, inscription.groupe_choisi)
                resultat_groupe_choisi = ('succes', inscription.groupe_choisi.nom, None)
            else:
                resultat_groupe_choisi = ('echec', inscription.groupe_choisi.nom, raison)

        # Change le statut
        inscription.statut = 'valide'
        inscription.save()

    if resultat_groupe_choisi:
        etat, nom_groupe, raison = resultat_groupe_choisi
        if etat == 'succes':
            messages.success(request, f'تم إلحاق الطالب تلقائياً بالمجموعة التي اختارها عند التسجيل: "{nom_groupe}".')
        else:
            messages.warning(
                request,
                f'الطالب كان قد اختار مجموعة "{nom_groupe}" عند التسجيل، لكن لم يعد بالإمكان إلحاقه بها تلقائياً '
                f'({raison}) — يرجى إضافته يدوياً إلى مجموعة مناسبة.'
            )

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
    """Audit du 2026-08-22 (page détail candidature pas à jour avec le
    nouveau moteur d'inscription configurable) : `a_reponses_nouveau_wizard`
    distingue une candidature du NOUVEAU parcours (registration.utils.
    inscrire_eleve, au moins une ReponseInscription) d'une candidature de
    l'ANCIEN formulaire à une page (aucune ReponseInscription, jamais créée
    par ce moteur) — même discriminant déjà utilisé par registration_tags.
    reponse_ou_ancien_champ pour 'programme'/'riwaya'.

    L'ancien moteur de suggestion (courses.utils.groupes_compatibles_pour_
    inscription, basé sur inscription.disponibilites + inscription.
    programme/riwaya, colonnes TOUJOURS vides pour une candidature du nouveau
    wizard) n'est calculé QUE pour une candidature legacy — inutile et
    trompeur sinon (retournerait "aucun groupe compatible" pour la quasi-
    totalité des candidatures Individuel, qui n'ont structurellement besoin
    d'aucun groupe). Pour le nouveau parcours, la page affiche directement
    groupe_choisi (déjà le résultat du VRAI moteur, registration.utils.
    groupes_compatibles_avec_age, au moment de l'inscription) ou l'état
    "attente" (DemandeNonSatisfaite liée, chantier "liberté totale du nombre
    de séances") — jamais une 2e suggestion recalculée après coup."""
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO, groupes_compatibles_pour_inscription
    from registration.models import get_presentation_inscription

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

    a_reponses_nouveau_wizard = inscription.reponses.exists()
    # Chantier du 2026-08-23 (Partie 3B, "étapes repositionnables/insérables
    # n'importe où") : programme/riwaya/type_offre/nb_seances_hebdo restent
    # affichés ci-dessus par leurs lignes DÉDIÉES existantes (reponse_ou_
    # ancien_champ, inscription.abonnement_type_offre/nb_slots_choisi) —
    # tout le RESTE des ReponseInscription (champs informatifs comme "Pays",
    # ET tout critère personnalisé attaché à une étape autre que 'programme',
    # ex: un champ ajouté sur 'identite' ou sur une étape personnalisée)
    # n'avait ENCORE AUCUN affichage ici avant cette correction — trou
    # identifié en préparant le test bout en bout de la Partie 3B : une
    # réponse réellement enregistrée mais jamais visible au مدير sur la
    # fiche de la candidature, alors que couverte par groupes_compatibles()
    # exactement comme programme/riwaya. Générique par construction (label
    # du champ, jamais un nom de critère en dur) — jamais 2 versions
    # maintenues séparément selon l'étape d'origine du champ.
    autres_reponses = (
        inscription.reponses.exclude(
            champ__critere__code__in=['programme', 'riwaya', 'type_offre', 'nb_seances_hebdo']
        ).select_related('champ', 'champ__critere', 'option').order_by('champ__etape__ordre', 'champ__ordre')
        if a_reponses_nouveau_wizard else inscription.reponses.none()
    )
    context = {
        'inscription': inscription,
        'conflit': conflit,
        'peut_accepter': peut_accepter,
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'valeurs_dispo': set(inscription.disponibilites),
        'a_reponses_nouveau_wizard': a_reponses_nouveau_wizard,
        'autres_reponses': autres_reponses,
        'presentation_inscription': get_presentation_inscription(),
        'demande_non_satisfaite': (
            inscription.demandes_non_satisfaites.first() if a_reponses_nouveau_wizard else None
        ),
        'groupes_suggeres': (
            [] if a_reponses_nouveau_wizard else groupes_compatibles_pour_inscription(inscription)
        ),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    # 2e "page cible" du panneau 🔔 "طلبات تسجيل جديدة" (voir dashboard.
    # notifications.notifications_direction) — chaque lien de notification
    # pointe ICI (la fiche d'une candidature précise), PAS vers admin_
    # inscriptions (la liste, déjà câblée plus haut). Sans cet appel, cliquer
    # une notification et lire la fiche ne faisait jamais baisser le badge :
    # seul un détour par la liste le faisait (bug rapporté le 2026-08-25).
    # Même précaution que les autres appelants de marquer_visite : juste
    # avant le render, jamais avant.
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'demandes_inscription')
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
    from django.utils import timezone
    from inscriptions.models import InscriptionProf
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)
    inscription.statut = 'validee_directeur'
    # Fonctionnalité 3 (2026-08-27) : horodatage DÉDIÉ de cette transition
    # précise — voir InscriptionProf.date_validee_directeur.__doc__, jamais
    # `date_soumission` (bien antérieur si ce dossier traînait en
    # 'en_attente'). Déclenche la notification مشرف, voir dashboard.
    # notifications.notifications_direction.
    inscription.date_validee_directeur = timezone.now()
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
    # Panneau 🔔 الإشعارات étendu au مدير/مشرف (chantier du 2026-08-24) —
    # voir dashboard.notifications.notifications_direction.__doc__.
    from dashboard.notifications import notifications_direction
    notif_groupes, notif_total = notifications_direction(request.user)
    context['notif_groupes'] = notif_groupes
    context['notif_total'] = notif_total
    return render(request, 'dashboard/dashboard_mshrif.html', context)


@role_required('mshrif')
def mshrif_inscriptions_profs(request):
    from inscriptions.models import InscriptionProf
    inscriptions = InscriptionProf.objects.filter(statut='validee_directeur').order_by('-date_soumission')
    context = {'inscriptions': paginer(request, inscriptions, 10)}
    context.update(_contexte_base_mshrif(request))
    # Fonctionnalité 3 (2026-08-27) : page cible du groupe de notification
    # 'profs_en_attente_validation' (voir dashboard.notifications.
    # notifications_direction) — juste avant le render, jamais avant (même
    # précaution que les autres appelants de marquer_visite).
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'profs_en_attente_validation')
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
    """Validation finale — étape 2/2. Délègue la création du compte à _creer_compte_prof
    (Chantier d'ajout manuel du 2026-08-27, extraite d'ici — voir sa docstring), partagée
    avec admin_prof_ajouter_manuel quand c'est le مشرف lui-même qui ajoute le prof."""
    from inscriptions.models import InscriptionProf

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

    prof, password_temp = _creer_compte_prof(inscription)

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
    des tarifs (courses.models.TarifRemunerationGroupe/TarifRemunerationIndividuel,
    Chantier du 2026-08-27 — voir leur docstring de dépréciation de TarifRemuneration)
    — auparavant une page séparée (admin_tarifs_remuneration), fusionnée ici pour
    éviter 2 pages distinctes sur le même sujet. Toujours en lecture seule pour ce
    rôle : voir admin_tarifs_remuneration/admin_tarif_remuneration_groupe_modifier/
    admin_tarif_remuneration_individuel_modifier pour l'édition, réservée au مدير
    sur la page d'origine, restée intacte."""
    from accounts.models import Prof
    from courses.models import TarifRemunerationGroupe, TarifRemunerationIndividuel
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
    # rapport — par prof, pour une donnée strictement identique). Adapté le
    # 2026-08-27 aux 2 nouvelles grilles (TarifRemunerationGroupe/Individuel),
    # même principe exact.
    tarifs_groupe_charges = {
        (t.tranche_age, t.nb_slots): t.montant
        for t in TarifRemunerationGroupe.objects.filter(est_actif=True)
    }
    tarifs_individuel_charges = {
        t.tranche_age: t.montant for t in TarifRemunerationIndividuel.objects.all()
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
        remuneration = calculer_remuneration_prof(
            prof, mois=mois_filtre or None,
            tarifs_groupe=tarifs_groupe_charges, tarifs_individuel=tarifs_individuel_charges,
        )
        base = remuneration['total_calcule']
        majoration = prof.majoration_mensuelle or 0
        total_base += base
        total_majoration += majoration
        lignes.append({
            'prof': prof,
            'base': base,
            'majoration': prof.majoration_mensuelle,
            'total': base + majoration,
            'archive': False,
            'tarif_manquant': bool(remuneration['tarifs_manquants']),
        })

    # Profs archivés : ajoutés à la suite, UNIQUEMENT s'ils ont encore un
    # montant dû ce mois (voir docstring ci-dessus).
    for prof in Prof.objects.filter(statut='archive').select_related('user').prefetch_related('groupes').order_by('user__first_name'):
        remuneration_archive = calculer_remuneration_prof(
            prof, mois=mois_filtre or None,
            tarifs_groupe=tarifs_groupe_charges, tarifs_individuel=tarifs_individuel_charges,
        )
        base = remuneration_archive['total_calcule']
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
            'tarif_manquant': bool(remuneration_archive['tarifs_manquants']),
        })

    from courses.utils import couverture_tarifs_remuneration_groupe

    context = {
        # Paginé pour l'affichage (Tâche 22 Partie F du 2026-07-26) — les totaux
        # ci-dessus restent calculés sur TOUS les profs, pas seulement la page
        # affichée (calculés avant toute pagination, aucun changement à faire).
        'lignes': paginer(request, lignes, 10),
        'total_base': total_base,
        'total_majoration': total_majoration,
        'total_general': total_base + total_majoration,
        'tarifs_groupe': TarifRemunerationGroupe.objects.filter(est_actif=True).order_by('tranche_age', 'nb_slots'),
        'tarifs_individuel': TarifRemunerationIndividuel.objects.all().order_by('tranche_age'),
        'couverture_groupe': couverture_tarifs_remuneration_groupe(),
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
    from accounts.models import CharteEnseignement, get_charte, CharteSanctionLigne

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

        # Chantier i18n du 2026-08-28 : traductions FR/EN saisies à la main
        # (mêmes noms d'input "{champ}_fr"/"{champ}_en" que
        # PresentationInscription), stockées en JSON — voir
        # CharteEnseignement.traductions/_localise pour le pourquoi du
        # JSONField plutôt que des colonnes par champ ici.
        traductions = {'fr': {}, 'en': {}}
        for champ in CharteEnseignement._CHAMPS_LOCALISABLES:
            for langue in ('fr', 'en'):
                traductions[langue][champ] = request.POST.get(f'{champ}_{langue}', '').strip()
        charte.traductions = traductions
        charte.save()

        violations = request.POST.getlist('sanction_violation')
        violations_fr = request.POST.getlist('sanction_violation_fr')
        violations_en = request.POST.getlist('sanction_violation_en')
        severites = request.POST.getlist('sanction_severite')
        charte.sanctions.all().delete()
        for ordre, (violation, violation_fr, violation_en, severite) in enumerate(
            zip(violations, violations_fr, violations_en, severites)
        ):
            if violation.strip():
                CharteSanctionLigne.objects.create(
                    charte=charte, ordre=ordre, violation=violation.strip(),
                    violation_fr=violation_fr.strip(), violation_en=violation_en.strip(),
                    severite=severite,
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
    annonces_non_lues = list(
        annonces_visibles_pour_eleve(eleve).exclude(lectures__user=request.user).order_by('-date_creation')
    )
    annonces_recentes = annonces_non_lues[:3]

    # Panneau 🔔 الإشعارات (Chantier notifications du 2026-08-19) — calculé
    # UNIQUEMENT ici (page d'accueil), jamais en context processor global :
    # voir dashboard.notifications.__doc__ pour le choix d'architecture et
    # son coût réel.
    from dashboard.notifications import notifications_eleve
    notif_groupes, notif_total = notifications_eleve(eleve, request.user)

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
        'notif_groupes': notif_groupes,
        'notif_total': notif_total,
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

    # Marque le type 'notes_seances' comme lu (panneau 🔔 الإشعارات, Chantier
    # notifications du 2026-08-19) — voir dashboard.notifications.__doc__.
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'notes_seances')

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
    from chat.permissions import groupes_chat_accessibles_ids
    from courses.models import BilanMensuel
    from django.contrib.auth import get_user_model
    User = get_user_model()
    from courses.models import DemandeChangementHalaka

    eleve = get_object_or_404(Eleve, user=request.user)
    return render(request, 'dashboard/eleve_profil.html', {
        'eleve': eleve,
        'groupes_precedents': eleve.historique_groupes.filter(date_fin__isnull=False).select_related('groupe'),
        'admins': User.objects.filter(role='admin'),
        # Icône 💬 chat (Chantier icône-chat du 2026-08-18) — voir
        # chat.permissions.groupes_chat_accessibles_ids.__doc__.
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
        # Bouton "تعديل" du téléphone — même pattern que Tâche 5 (lecture seule
        # par défaut, édition seulement après clic explicite).
        'modifier_telephone': request.GET.get('modifier_telephone') == '1',
        # Chantier du 2026-08-14 (bilan d'absences, accès élève ajouté) —
        # point d'entrée vers bilan_mensuel_detail, qui n'était accessible à
        # aucun rôle élève auparavant (aucun lien nulle part côté élève).
        'bilans_mensuels': BilanMensuel.objects.filter(eleve=eleve).order_by('-mois_reference'),
        # Fonctionnalité 4 (2026-08-27) : bouton "طلب تغيير الحلقة" désactivé/
        # remplacé par le statut de la demande en cours s'il y en a déjà une
        # (voir DemandeChangementHalaka.__doc__ — une seule en_attente à la fois).
        'demande_changement_halaka_en_attente': DemandeChangementHalaka.objects.filter(
            eleve=eleve, statut='en_attente',
        ).select_related('groupe_demande').first(),
    })


@role_required('eleve')
def eleve_demande_changement_halaka(request):
    """Fonctionnalité 4 (2026-08-27) : bouton "طلب تغيير الحلقة" côté élève
    (dashboard/eleve_profil.html) — GET affiche la liste des halakat
    compatibles (voir courses.utils.groupes_compatibles_sexe_age_pour_
    changement.__doc__ : sexe/âge SEULEMENT, programme/riwaya restent
    visibles sans filtre), POST crée la demande.

    Garde-fou "une seule demande en_attente à la fois" (décision explicite
    du client) vérifiée aux 2 bouts : le GET n'affiche même pas le
    formulaire s'il en existe déjà une (voir template), le POST la
    revérifie côté serveur (jamais une confiance aveugle dans un formulaire
    déjà affiché — même principe que partout ailleurs dans ce projet, ex:
    groupe_choisi revalidé à la soumission du wizard public)."""
    from accounts.models import Eleve, get_visibilite_prof
    from courses.models import DemandeChangementHalaka
    from courses.utils import groupes_compatibles_sexe_age_pour_changement

    eleve = get_object_or_404(Eleve, user=request.user)
    demande_en_attente = DemandeChangementHalaka.objects.filter(eleve=eleve, statut='en_attente').first()

    if request.method == 'POST':
        if demande_en_attente:
            messages.error(request, 'لديك بالفعل طلب تغيير حلقة قيد الانتظار — يجب معالجته أولاً قبل إرسال طلب جديد.')
            return redirect('eleve_profil')

        groupes_valides = {g.id: g for g in groupes_compatibles_sexe_age_pour_changement(eleve)}
        groupe_demande_id = request.POST.get('groupe_demande', '')
        groupe_demande = groupes_valides.get(int(groupe_demande_id)) if groupe_demande_id.isdigit() else None
        if not groupe_demande:
            messages.error(request, 'يجب اختيار حلقة صالحة من القائمة المقترحة.')
            return redirect('eleve_demande_changement_halaka')

        DemandeChangementHalaka.objects.create(
            eleve=eleve,
            groupe_actuel=eleve.groupes.first(),
            groupe_demande=groupe_demande,
        )
        messages.success(request, 'تم إرسال طلبك بنجاح — بانتظار معالجته من طرف الإدارة.')
        return redirect('eleve_profil')

    return render(request, 'dashboard/eleve_demande_changement_halaka.html', {
        'eleve': eleve,
        'demande_en_attente': demande_en_attente,
        'groupes_disponibles': groupes_compatibles_sexe_age_pour_changement(eleve) if not demande_en_attente else [],
        # Même réglage que le wizard public (templates/inscriptions/
        # wizard_groupe.html) pour la nubdha du prof — voir accounts.models.
        # VisibiliteProf.afficher_presentation_wizard.
        'visibilite': get_visibilite_prof(),
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
    from chat.permissions import groupes_chat_accessibles_ids
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
        # Icône 💬 chat sur "المجموعات المسندة" (Chantier redesign icône-chat du
        # 2026-08-19) — consommé par dashboard/_liste_groupes_mesnad.html, hérité
        # du contexte via {% include %} sans `only`, voir son commentaire.
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
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
    from chat.permissions import peut_voir_chat_groupe
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
        # Icône 💬 chat (Chantier icône-chat du 2026-08-18) — voir
        # chat.permissions.peut_voir_chat_groupe.__doc__.
        'peut_voir_chat': peut_voir_chat_groupe(request.user, groupe),
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
    """Tâche du 2026-08-17 (exceptions de séance) : déplacer une séance à une
    date/heure hors de son créneau habituel peut rendre le lien Meet PAR
    DÉFAUT du groupe indisponible (occupé par un autre groupe à ce nouveau
    moment précis). Dans ce cas :
      1. on ne sauvegarde PAS silencieusement le déplacement avec un lien en
         conflit — le formulaire est réaffiché avec une alerte + les liens
         réellement disponibles pour ce nouvel horaire (courses.utils.
         liens_meet_disponibles_pour_seance) ;
      2. si le مدير choisit un lien alternatif, il est posé UNIQUEMENT sur
         cette Seance (Seance.lien_meet_exceptionnel) — Groupe.lien_meet /
         Groupe.lien_reunion / Groupe.creneau ne sont JAMAIS modifiés ici ;
      3. si le lien par défaut du groupe reste disponible au nouvel horaire,
         il est conservé automatiquement, sans rien demander au مدير.
    La séance suivante (générée normalement pour la semaine d'après) n'hérite
    d'aucune exception : elle repart du lien par défaut du groupe."""
    from courses.models import Seance, LienMeet
    from courses.utils import (
        lien_effectif_disponible_pour_seance, liens_meet_disponibles_pour_seance,
        groupes_en_conflit_pour_lien_a_horaire_reel, horaire_reel_seance,
        description_conflit_lien_meet_seance,
    )

    seance = get_object_or_404(Seance, id=seance_id)

    def _reafficher_conflit(nouvelle_date, nouvelle_heure, remarque, raison=''):
        """Recalcule TOUJOURS la disponibilité pendant que seance.date/heure
        portent encore le NOUVEL horaire proposé (jamais après les avoir
        restaurés), puis restaure l'horaire ACTUEL de la séance pour le reste
        de l'affichage (ex: sous-titre "الموعد الحالي")."""
        liens_dispo = liens_meet_disponibles_pour_seance(seance)
        seance.date, seance.heure = ancien_date, ancien_heure
        return render(request, 'dashboard/admin_seance_deplacer.html', {
            'seance': seance,
            'conflit_meet': True,
            'raison_conflit': raison,
            'nouvelle_date': nouvelle_date,
            'nouvelle_heure': nouvelle_heure,
            'remarque_soumise': remarque,
            'liens_meet_disponibles': liens_dispo,
        })

    if request.method == 'POST':
        nouvelle_date = request.POST.get('date')
        nouvelle_heure = request.POST.get('heure')
        remarque = request.POST.get('remarque', '')
        lien_meet_exceptionnel_id = request.POST.get('lien_meet_exceptionnel')

        # Prévisualisation en mémoire (rien n'est encore sauvegardé) pour pouvoir
        # calculer la disponibilité au NOUVEL horaire avant tout engagement. Types
        # Python réels requis ICI (pas les chaînes brutes du POST) : horaire_reel_seance
        # appelle seance.date.weekday(), qui échoue sur une simple str — Django ne
        # convertit automatiquement une valeur assignée qu'à la sauvegarde, jamais à
        # la simple affectation d'attribut.
        ancien_date, ancien_heure = seance.date, seance.heure
        seance.date = datetime.datetime.strptime(nouvelle_date, '%Y-%m-%d').date()
        seance.heure = datetime.datetime.strptime(nouvelle_heure, '%H:%M').time()

        if lien_meet_exceptionnel_id:
            # Le مدير a explicitement choisi un lien alternatif suite à l'alerte
            # ci-dessous — revérifié ICI côté serveur (jamais une confiance dans
            # la liste proposée au tour précédent), sous verrou, même principe
            # que courses.views.lien_meet_attribuer_groupe.
            with transaction.atomic():
                lien_obj = get_object_or_404(LienMeet.objects.select_for_update(), id=lien_meet_exceptionnel_id)
                jour_code, heure_debut, heure_fin = horaire_reel_seance(seance)
                if not lien_obj.est_actif or groupes_en_conflit_pour_lien_a_horaire_reel(lien_obj, jour_code, heure_debut, heure_fin):
                    messages.error(request, f'تعذّر استخدام "{lien_obj}" لهذا الموعد — لم يعد متاحاً. أعد المحاولة.')
                    return _reafficher_conflit(nouvelle_date, nouvelle_heure, remarque)
                seance.lien_meet_exceptionnel = lien_obj
                seance.remarque = remarque
                seance.save()
            messages.success(request, f'تم تأجيل الحصة، مع استخدام "{lien_obj}" كرابط استثنائي لهذه الحصة فقط.')
            return redirect('admin_seances')

        # Aucun lien alternatif choisi : le lien EFFECTIF actuel de la séance
        # (celui du groupe, ou une exception déjà posée précédemment) reste-t-il
        # valable au NOUVEL horaire ?
        if not lien_effectif_disponible_pour_seance(seance):
            lien_actuel = LienMeet.objects.filter(url=seance.lien_effectif).first()
            raison = description_conflit_lien_meet_seance(lien_actuel, seance) if lien_actuel else ''
            return _reafficher_conflit(nouvelle_date, nouvelle_heure, remarque, raison)

        # Compatible (ou aucun lien à vérifier) : sauvegarde normale, lien par
        # défaut du groupe conservé automatiquement — rien à demander au مدير.
        seance.remarque = remarque
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
    from accounts.models import Eleve, NotePersonnelle
    from chat.permissions import groupes_chat_accessibles_ids
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
        # Icône 💬 chat sur "المجموعة الحالية" (Chantier redesign icône-chat du
        # 2026-08-19) — voir chat.permissions.groupes_chat_accessibles_ids.__doc__.
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
        # Carnet de notes personnelles (Tâche du 2026-08-18) — UNIQUEMENT les
        # notes de request.user lui-même sur ce profil, jamais celles d'un
        # autre مدير/مشرف (voir accounts.models.NotePersonnelle.__doc__).
        'notes_personnelles': NotePersonnelle.objects.filter(
            profil_user=eleve.user, auteur=request.user
        ),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_eleve_detail.html', context)


@role_required('admin', 'mshrif')
def admin_eleve_cartable_gestion(request):
    """Page centrale "إدارة حقيبة الطالب" (refonte du 2026-08-18 — remplace
    la gestion par fiche élève individuelle : demande explicite du client de
    calquer exactement le patron déjà en place pour la حقيبة الأستاذ, voir
    admin_hakiba_gestion). Formulaire d'ajout (choix du طالب inclus,
    contrairement à ElementHakiba qui cible plusieurs profs à la fois — un
    DocumentEleve appartient toujours à UN SEUL élève) + liste de tous les
    documents existants, tous élèves confondus.

    UN SEUL système de sélection des destinataires (correction UX du
    2026-08-18 ter) : le formulaire "ملف جديد" ci-dessous (كل الطلاب / فئة
    معينة / طلاب محددون — voir admin_eleve_cartable_ajouter pour la
    résolution de chaque mode). Un ancien filtre de catégorie séparé,
    au-dessus de la liste, a été retiré : il faisait doublon avec celui du
    formulaire ET utilisait en plus la mauvaise source de catégorie
    (cible_annonce_pour_eleve, basée âge/sexe de l'élève) au lieu de
    Groupe.categorie (demande explicite du client) — supprimé plutôt que
    corrigé, pour ne garder qu'un seul système de filtrage."""
    from accounts.models import Eleve, DocumentEleve
    from annonces.services import CANAUX

    documents = list(
        DocumentEleve.objects.select_related('eleve__user', 'ajoute_par').order_by('-date_ajout')
    )

    context = {
        'documents_cartable': documents,
        # Sélecteur "طلاب محددون" du formulaire d'ajout — tous les élèves actifs.
        'eleves_disponibles': Eleve.actifs.select_related('user').order_by('user__first_name', 'user__last_name'),
        # Labels نساء/رجال/أطفال du sous-toggle "فئة معينة" du formulaire.
        'canaux': CANAUX,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_eleve_cartable_gestion.html', context)


@role_required('admin', 'mshrif')
@require_POST
def admin_eleve_cartable_ajouter(request):
    """Ajoute un fichier au cartable d'un ou plusieurs élèves, depuis la page
    centrale "إدارة حقيبة الطالب" — 3 modes de ciblage (demande explicite du
    client, EXACTEMENT le même principe que حقيبة الأستاذ/admin_hakiba_ajouter,
    étendu d'un 3e mode) :
      - 'tous' : tous les élèves actifs (Eleve.actifs), comme
        ElementHakiba.tous_les_profs=True ;
      - 'categorie' : tous les élèves actifs appartenant à AU MOINS UN
        groupe ACTIF dont Groupe.categorie correspond (نساء/رجال/أطفال —
        mêmes 3 valeurs que les canaux d'annonces, Groupe.categorie
        réutilise directement Annonce.CIBLE_CHOICES, voir Groupe.categorie
        __doc__). SOURCE EXPLICITEMENT CONFIRMÉE PAR LE CLIENT :
        Groupe.categorie (champ saisi par le مدير), PAS
        Groupe.categorie_collectif (property dérivée du créneau) ni
        cible_annonce_pour_eleve (déduit de l'âge/sexe de l'élève — c'était
        la source utilisée par l'ancien filtre de liste, retiré, jamais
        celle du ciblage d'upload). Un élève sans groupe, ou dont aucun
        groupe n'a de categorie renseignée, n'apparaît simplement dans
        aucune catégorie précise (mais reste sélectionnable via 'tous' ou
        'specifique' — jamais une disparition silencieuse) ;
      - 'specifique' : élèves nommés un par un (recherche + sélection
        multiple), comme "أساتذة محددون" pour حقيبة الأستاذ.
    DocumentEleve reste une FK simple vers un seul élève (dossier personnel,
    pas de diffusion par M2M — voir son __doc__) : cibler plusieurs élèves
    crée donc une ligne PAR élève, chacune avec une copie du même fichier
    (fichier lu une seule fois, voir ContentFile ci-dessous — le curseur
    d'un fichier uploadé ne peut être relu qu'une fois avec .save() direct).
    Réservé à مدير/مشرف (pas le prof, décision confirmée)."""
    from django.core.files.base import ContentFile
    from accounts.models import Eleve, DocumentEleve

    fichier = request.FILES.get('fichier')
    if not fichier:
        messages.error(request, 'يجب إرفاق ملف.')
        return redirect('admin_eleve_cartable_gestion')

    erreur = _valider_fichier_hakiba(fichier)
    if erreur:
        messages.error(request, erreur)
        return redirect('admin_eleve_cartable_gestion')

    cible = request.POST.get('cible', 'specifique')
    if cible == 'tous':
        eleves_cibles = list(Eleve.actifs.all())
    elif cible == 'categorie':
        categorie = request.POST.get('categorie_cible', '')
        eleves_cibles = list(
            Eleve.actifs.filter(groupes__statut='actif', groupes__categorie=categorie).distinct()
        ) if categorie else []
        if not eleves_cibles:
            messages.error(request, 'يرجى اختيار فئة تضم طالباً واحداً على الأقل.')
            return redirect('admin_eleve_cartable_gestion')
    else:
        ids = [i for i in request.POST.getlist('eleves_cibles') if i.isdigit()]
        eleves_cibles = list(Eleve.objects.filter(id__in=ids))
        if not eleves_cibles:
            messages.error(request, 'يرجى اختيار طالب واحد على الأقل.')
            return redirect('admin_eleve_cartable_gestion')

    titre = request.POST.get('titre', '').strip()
    contenu = fichier.read()
    for eleve in eleves_cibles:
        DocumentEleve.objects.create(
            eleve=eleve, titre=titre,
            fichier=ContentFile(contenu, name=fichier.name),
            ajoute_par=request.user,
        )

    if len(eleves_cibles) == 1:
        messages.success(request, f'تمت إضافة الملف إلى حقيبة {eleves_cibles[0].user.get_full_name()}.')
    else:
        messages.success(request, f'تمت إضافة الملف إلى حقيبة {len(eleves_cibles)} طالباً.')
    return redirect('admin_eleve_cartable_gestion')


@role_required('admin', 'mshrif')
@require_POST
def admin_eleve_cartable_supprimer(request, document_id):
    from accounts.models import DocumentEleve

    document = get_object_or_404(DocumentEleve, id=document_id)
    if document.fichier:
        document.fichier.delete(save=False)
    document.delete()
    messages.success(request, 'تم حذف الملف من حقيبة الطالب.')
    return redirect('admin_eleve_cartable_gestion')


@role_required('eleve')
def eleve_cartable(request):
    """Page de lecture seule de l'élève sur SON PROPRE cartable — équivalent
    de prof_hakiba.html côté prof, même principe (مدير/مشرف déposent, la
    personne concernée consulte, aucune gestion possible d'ici)."""
    eleve = request.user.eleve
    documents = eleve.documents_cartable.select_related('ajoute_par')

    # Marque le type 'cartable' comme lu (panneau 🔔 الإشعارات, Chantier
    # notifications du 2026-08-19) — voir dashboard.notifications.__doc__.
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'cartable')

    return render(request, 'dashboard/eleve_cartable.html', {'documents': documents})


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
    from accounts.models import Prof, NotePersonnelle
    from chat.permissions import groupes_chat_accessibles_ids
    from courses.utils import calculer_remuneration_prof
    prof = get_object_or_404(Prof, id=prof_id)
    context = {
        'prof': prof,
        'inscription': prof.inscription,
        'remuneration': calculer_remuneration_prof(prof),
        # حقيبة الأستاذ retirée de cette fiche depuis la refonte du 2026-08-05 :
        # gestion désormais centralisée sur admin_hakiba_gestion, plus par prof.
        # Carnet de notes personnelles (Tâche du 2026-08-18) — système
        # INDÉPENDANT de prof.notes_admin ci-dessus (voir accounts.models.
        # NotePersonnelle.__doc__), uniquement les notes de request.user.
        'notes_personnelles': NotePersonnelle.objects.filter(
            profil_user=prof.user, auteur=request.user
        ),
        # Icône 💬 chat sur "المجموعات" (Chantier redesign icône-chat du
        # 2026-08-19) — voir chat.permissions.groupes_chat_accessibles_ids.__doc__.
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
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


# ==================== Fonctionnalité 4 (2026-08-27) : demandes de changement de halaka ====================
# Même patron que admin_demandes_disponibilite ci-dessus, MAIS accessible en
# ACTION (pas seulement en lecture) aux 2 rôles مدير ET مشرف — décision
# explicite du client pour ce chantier précis : "un seul des deux rôles
# suffit, peu importe lequel agit en premier" (contrairement à
# admin_demande_disponibilite_approuver/rejeter, réservées à role_required
# ('admin') seul, mshrif n'y étant que spectateur).

@role_required('admin', 'mshrif')
def admin_demandes_changement_halaka(request):
    from courses.models import DemandeChangementHalaka

    demandes = DemandeChangementHalaka.objects.filter(statut='en_attente').select_related(
        'eleve__user', 'groupe_actuel', 'groupe_demande'
    ).order_by('date_demande')
    context = {
        'demandes': demandes,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    # Page cible du groupe de notification 'demandes_changement_halaka' (voir
    # dashboard.notifications.notifications_direction) — juste avant le
    # render, jamais avant (même précaution que les autres appelants de
    # marquer_visite).
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'demandes_changement_halaka')
    return render(request, 'dashboard/admin_demandes_changement_halaka.html', context)


@role_required('admin', 'mshrif')
def admin_demande_changement_halaka_valider(request, demande_id):
    """Transfert automatique (décision explicite du client : "priorité à la
    simplicité côté مدير", aucune action manuelle supplémentaire ailleurs) —
    réutilise TEL QUEL _ajouter_eleve_au_groupe/_retirer_eleve_du_groupe
    (courses.views), les mêmes fonctions déjà utilisées par groupe_
    transferer_eleve pour un transfert décidé côté staff : la nouvelle ligne
    Groupe.eleves ET l'historique HistoriqueGroupeEleve restent cohérents
    avec TOUT le reste du projet, jamais une 2e façon de faire un transfert.

    Revalide raison_incompatibilite_groupe juste avant d'agir (jamais une
    confiance aveugle dans une liste affichée à l'élève potentiellement
    périmée entre-temps — ex: la halaka demandée s'est remplie, ou son
    créneau a changé depuis la demande) : bloque avec un message clair
    plutôt qu'un transfert incohérent."""
    from django.utils import timezone
    from courses.models import DemandeChangementHalaka
    from courses.utils import raison_incompatibilite_groupe
    from courses.views import _ajouter_eleve_au_groupe, _retirer_eleve_du_groupe

    demande = get_object_or_404(DemandeChangementHalaka, id=demande_id)
    if demande.statut != 'en_attente':
        messages.error(request, 'هذا الطلب لم يعد قيد الانتظار.')
        return redirect('admin_demandes_changement_halaka')

    if not demande.groupe_demande:
        messages.error(request, 'تعذّر قبول الطلب: الحلقة المطلوبة لم تعد موجودة.')
        return redirect('admin_demandes_changement_halaka')

    raison = raison_incompatibilite_groupe(demande.eleve, demande.groupe_demande)
    if raison:
        messages.error(request, f'تعذّر قبول الطلب: {raison}')
        return redirect('admin_demandes_changement_halaka')

    with transaction.atomic():
        if demande.groupe_actuel and demande.groupe_actuel.eleves.filter(id=demande.eleve_id).exists():
            _retirer_eleve_du_groupe(demande.eleve, demande.groupe_actuel)
        _ajouter_eleve_au_groupe(demande.eleve, demande.groupe_demande)
        demande.statut = 'validee'
        demande.date_traitement = timezone.now()
        demande.traite_par = request.user
        demande.save()
    messages.success(
        request,
        f'تم قبول طلب {demande.eleve.user.get_full_name()} ونقله إلى حلقة {demande.groupe_demande.nom}.'
    )
    return redirect('admin_demandes_changement_halaka')


@role_required('admin', 'mshrif')
def admin_demande_changement_halaka_refuser(request, demande_id):
    from django.utils import timezone
    from courses.models import DemandeChangementHalaka

    demande = get_object_or_404(DemandeChangementHalaka, id=demande_id)
    if demande.statut != 'en_attente':
        messages.error(request, 'هذا الطلب لم يعد قيد الانتظار.')
        return redirect('admin_demandes_changement_halaka')

    demande.statut = 'refusee'
    demande.date_traitement = timezone.now()
    demande.traite_par = request.user
    demande.save()
    messages.info(request, f'تم رفض طلب {demande.eleve.user.get_full_name()}.')
    return redirect('admin_demandes_changement_halaka')


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
    """Correction 5 (2026-08-22, suite au test local) : la liste est séparée
    en 2 sections claires ("Groupe"/"Individuel", TypeAbonnement.type_offre)
    au lieu d'une seule liste plate mélangeant les deux — même axe déjà
    utilisé partout ailleurs pour ce champ (registration.utils.
    abonnements_disponibles, GrillePrixAbonnement.__doc__). Toujours
    ordonnées par `ordre` À L'INTÉRIEUR de chaque section, jamais un tri
    global qui mélangerait à nouveau les 2 types.

    Fonctionnalité 1 (2026-08-27, archivage) : à l'intérieur de CHAQUE
    section, les abonnements actifs/archivés (TypeAbonnement.est_actif) sont
    en plus séparés en 2 listes — réutilise TEL QUEL le mécanisme de toggle
    existant (admin_abonnement_toggle), déjà exactement la sémantique
    "archivé" qu'il faut ici : est_actif=False est DÉJÀ filtré partout où un
    nouveau formulaire propose un abonnement (registration.utils.
    abonnements_disponibles, inscriptions.views ligne 232) alors que
    l'historique (InscriptionEleve.get_type_abonnement, etc.) ne filtre
    JAMAIS dessus — aucun conflit trouvé qui aurait justifié un champ
    distinct. _liste_abonnements_section.html affiche les archivés dans une
    section repliée par défaut (JS pur, même idiome que
    _historique_evaluations_eleve.html)."""
    from inscriptions.models import TypeAbonnement
    types_abonnement = TypeAbonnement.objects.all().order_by('ordre')

    def _actifs_et_archives(type_offre):
        du_type = [t for t in types_abonnement if t.type_offre == type_offre]
        return [t for t in du_type if t.est_actif], [t for t in du_type if not t.est_actif]

    actifs_groupe, archives_groupe = _actifs_et_archives('groupe')
    actifs_individuel, archives_individuel = _actifs_et_archives('individuel')
    context = {
        'types_abonnement_groupe': actifs_groupe,
        'archives_abonnement_groupe': archives_groupe,
        'types_abonnement_individuel': actifs_individuel,
        'archives_abonnement_individuel': archives_individuel,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_parametres_abonnements.html', context)


@role_required('admin', 'mshrif')
def admin_abonnement_ajouter(request):
    """Flux multi-étapes (Besoin 1, Chantier du 2026-08-27) — رمز → نوع
    (جماعي/فردي) → اسم معروض (affiché seulement après le choix du type,
    voir admin_abonnement_ajouter.html) → مدة (choix fermé) → عدد الحصص/
    الأسعار (cases cliquables du catalogue courses.models.OptionNbSeances).

    UNE SEULE vue/UN SEUL POST (page à étapes gérées en JS, comme
    templates/inscriptions/prof_formulaire.html — pas de session multi-page
    comme le wizard PUBLIC de registration/, réservé à un parcours candidat
    hors ligne) : crée le TypeAbonnement ET sa grille de prix en une seule
    transaction, fusionnant ce qui nécessitait avant ce chantier de créer
    PUIS modifier séparément (voir admin_abonnement_modifier).

    Blocage PAR CONTEXTE (décision explicite du client) : seules les cases
    du catalogue actif reçoivent un prix ICI — une case globalement créée
    mais non cochée/prix laissé vide pour CET abonnement n'est simplement
    pas ajoutée à sa grille (comportement identique à admin_abonnement_
    modifier, qui gère déjà l'ajout a posteriori d'une case oubliée).
    AU MOINS un prix est requis (sert de `prix` par défaut du TypeAbonnement,
    champ non-nullable) — le plus petit nb_slots reçu est utilisé, jamais
    un TypeAbonnement.prix inventé sans base réelle."""
    from inscriptions.models import GrillePrixAbonnement, TypeAbonnement
    from registration.utils import plage_nb_slots_grille_prix

    valeurs_nb_slots = plage_nb_slots_grille_prix()

    if request.method == 'POST':
        code = (request.POST.get('code') or '').strip()
        type_offre = request.POST.get('type_offre')
        label = (request.POST.get('label') or '').strip()
        duree = request.POST.get('duree', '').strip()
        cible_age = request.POST.get('cible_age', 'les_deux')
        ordre = request.POST.get('ordre', 0)

        erreurs = []
        if not code:
            erreurs.append('الرمز إلزامي.')
        elif TypeAbonnement.objects.filter(code=code).exists():
            erreurs.append(f'الرمز "{code}" مستخدم مسبقاً.')
        if type_offre not in ('groupe', 'individuel'):
            erreurs.append('يجب اختيار النوع (جماعي/فردي).')
        if not label:
            erreurs.append('الاسم المعروض إلزامي.')
        if duree not in dict(TypeAbonnement.DUREE_CHOICES):
            erreurs.append('يجب اختيار مدة صالحة.')

        prix_par_nb_slots = {}
        for nb_slots in valeurs_nb_slots:
            valeur_postee = (request.POST.get(f'prix_{nb_slots}') or '').strip()
            if valeur_postee:
                try:
                    prix_par_nb_slots[nb_slots] = float(valeur_postee)
                except ValueError:
                    erreurs.append(f'السعر المدخل لعدد الحصص {nb_slots} غير صالح.')
        if not prix_par_nb_slots:
            erreurs.append('يجب تحديد سعر واحد على الأقل لعدد حصص معين.')

        if erreurs:
            for erreur in erreurs:
                messages.error(request, erreur)
        else:
            with transaction.atomic():
                abonnement = TypeAbonnement.objects.create(
                    code=code, label=label, duree=duree, type_offre=type_offre, cible_age=cible_age,
                    prix=prix_par_nb_slots[min(prix_par_nb_slots)], ordre=ordre or 0,
                )
                for nb_slots, prix in prix_par_nb_slots.items():
                    GrillePrixAbonnement.objects.create(type_abonnement=abonnement, nb_slots=nb_slots, prix=prix)
            messages.success(request, 'تمت إضافة نوع الاشتراك بنجاح.')
            return redirect('admin_parametres_abonnements')

    return render(request, 'dashboard/admin_abonnement_ajouter.html', {
        'duree_choices': TypeAbonnement.DUREE_CHOICES,
        'options_nb_seances': valeurs_nb_slots,
        'valeurs_postees': request.POST if request.method == 'POST' else {},
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_abonnement_modifier(request, abonnement_id):
    """Page fusionnée (correction du 2026-08-22, chantier grille de prix
    incohérente/incomplète) : les infos générales du TypeAbonnement ET sa
    grille de prix par nombre de séances vivent désormais sur UNE SEULE
    page/UN SEUL formulaire — auparavant séparées (admin_abonnement_
    modifier + admin_abonnement_grille_prix), avec 2 notions de "prix"
    concurrentes et peu claires pour le مدير.

    TypeAbonnement.prix reste le seul champ "officiel" mais relabellisé
    "السعر الافتراضي" : le repli utilisé par prix_effectif() quand aucune
    ligne de grille n'existe pour le nb_slots demandé — jamais un prix
    concurrent, juste le cas par défaut.

    La grille elle-même reste décorrélée de nb_slots_reels_systeme() (groupes
    réels) — registration.utils.plage_nb_slots_grille_prix() (Chantier du
    2026-08-27 : catalogue courses.models.OptionNbSeances configurable, plus
    une plage fixe) reste la plage AUTORISÉE côté validation serveur (une
    ligne hors catalogue n'est jamais lue ni créée, quoi que le navigateur
    poste), même principe qu'avant ce chantier : un abonnement Individuel n'a besoin d'AUCUN
    groupe réel pour qu'un nombre de séances soit un choix valide (liberté
    totale depuis le chantier 5).

    Affichage refondu le 2026-08-22 (correction 6, suite au test local :
    "10 lignes fixes avec cases vides à remplir une par une, pas
    ergonomique, une case vide est ambiguë") : SEULES les lignes déjà
    configurées (GrillePrixAbonnement existante) sont affichées, éditables
    ou désactivables (case "نشط" déjà existante — jamais une suppression
    définitive, même convention que Creneau.est_actif partout ailleurs) ;
    "+ إضافة سعر لعدد حصص" (JS pur, pas de nouvelle route) propose un
    <select> limité aux nombres de séances 1..10 PAS ENCORE configurés, pour
    ajouter une nouvelle ligne. Les nombres non configurés restent listés
    explicitement dans le bandeau de couverture ci-dessous ("utilisent le
    prix par défaut"), jamais une case vide trompeuse.

    Soumission = 1 seule transaction : met à jour les champs du
    TypeAbonnement ET remplace les lignes de sa grille (update_or_create par
    nb_slots posté avec un prix non vide, suppression si laissé vide) — la
    boucle serveur reste sur TOUTE la plage 1..10 (jamais seulement les
    lignes affichées au chargement) : elle traite aussi bien les lignes déjà
    existantes que celles tout juste ajoutées côté client par le JS
    ci-dessus, sans avoir besoin d'un champ supplémentaire pour lister
    "les nb_slots soumis" — même idiome que l'ancienne page dédiée."""
    from inscriptions.models import GrillePrixAbonnement, TypeAbonnement
    from registration.utils import couverture_grille_prix, plage_nb_slots_grille_prix

    type_abonnement = get_object_or_404(TypeAbonnement, id=abonnement_id)
    valeurs = plage_nb_slots_grille_prix()

    if request.method == 'POST':
        with transaction.atomic():
            type_abonnement.label = request.POST.get('label')
            type_abonnement.duree = request.POST.get('duree', '').strip()
            type_abonnement.prix = request.POST.get('prix')
            type_abonnement.cible_age = request.POST.get('cible_age', 'les_deux')
            type_abonnement.ordre = request.POST.get('ordre', 0)
            type_abonnement.save()

            for nb_slots in valeurs:
                valeur_postee = (request.POST.get(f'prix_{nb_slots}') or '').strip()
                if valeur_postee == '':
                    GrillePrixAbonnement.objects.filter(type_abonnement=type_abonnement, nb_slots=nb_slots).delete()
                    continue
                GrillePrixAbonnement.objects.update_or_create(
                    type_abonnement=type_abonnement, nb_slots=nb_slots,
                    defaults={'prix': valeur_postee, 'est_actif': request.POST.get(f'actif_{nb_slots}') == 'on'},
                )
        messages.success(request, 'تم تعديل نوع الاشتراك بنجاح.')
        return redirect('admin_parametres_abonnements')

    lignes = list(type_abonnement.grille_prix.order_by('nb_slots'))
    nb_slots_configures = {ligne.nb_slots for ligne in lignes}
    nb_slots_disponibles = [n for n in valeurs if n not in nb_slots_configures]

    return render(request, 'dashboard/admin_abonnement_modifier.html', {
        'type_abonnement': type_abonnement,
        'lignes': lignes,
        'nb_slots_disponibles': nb_slots_disponibles,
        'couverture': couverture_grille_prix(type_abonnement),
        'duree_choices': TypeAbonnement.DUREE_CHOICES,
        'base_template': _base_template_admin_ou_mshrif(request),
        **_contexte_base_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_abonnement_toggle(request, abonnement_id):
    """Mécanisme INCHANGÉ (Fonctionnalité 1, 2026-08-27) : toggle simple de
    est_actif, comme avant. Seul le libellé des messages est aligné sur le
    vocabulaire "أرشفة/إعادة تفعيل" déjà utilisé pour Creneau.est_actif
    (templates/courses/admin_creneaux.html) — même sémantique exacte."""
    from inscriptions.models import TypeAbonnement
    type_abonnement = get_object_or_404(TypeAbonnement, id=abonnement_id)
    type_abonnement.est_actif = not type_abonnement.est_actif
    type_abonnement.save()
    messages.info(request, 'تم إعادة تفعيل نوع الاشتراك.' if type_abonnement.est_actif else 'تم أرشفة نوع الاشتراك — لن يظهر في استمارات التسجيل الجديدة.')
    return redirect('admin_parametres_abonnements')


@role_required('admin', 'mshrif')
def admin_abonnement_grille_prix(request, abonnement_id):
    """ANCIENNE page dédiée à la grille de prix — fusionnée dans
    admin_abonnement_modifier le 2026-08-22 (chantier grille de prix
    incohérente/incomplète : 2 pages avec 2 notions de "prix" différentes
    pour un même abonnement, source de confusion pour le مدير). Route
    conservée en simple redirection (jamais supprimée) pour tout ancien
    favori/lien déjà enregistré — aucune autre partie du code n'y référait
    plus (vérifié le 2026-08-22 : seuls admin_parametres_abonnements.html,
    ce fichier et les tests la mentionnaient)."""
    return redirect('admin_abonnement_modifier', abonnement_id=abonnement_id)


# ==================== ADMIN — GRILLE TARIFAIRE DE RÉMUNÉRATION DES PROFS ====================
# Refonte du 2026-08-27 (Chantier "salaire prof par nb séances/semaine") : l'ancienne
# grille fixe à 4 lignes (courses.models.TarifRemuneration, dépréciée — voir son
# docstring) est remplacée par 2 grilles distinctes :
# - TarifRemunerationGroupe (tranche_age × nb_slots) — EXTENSIBLE, comme
#   inscriptions.GrillePrixAbonnement (ajout/désactivation de lignes, jamais figée à 4).
# - TarifRemunerationIndividuel (tranche_age) — 2 lignes fixes, comme l'ancienne grille,
#   seul le montant est modifiable (jamais ajouté/supprimé).
# nb_slots proposé est TOUJOURS limité aux courses.models.OptionNbSeances actives
# (catalogue partagé avec la tarification élève, voir son docstring) — jamais une
# valeur libre.

@role_required('admin', 'mshrif')
def admin_tarifs_remuneration(request):
    # Fusionnée dans mshrif_remuneration (section repliable) pour le مشرف — cette
    # page reste la version complète (avec édition) réservée au مدير. Redirection
    # pour éviter un lien mort si l'ancienne URL était mise en favori côté مشرف,
    # qui n'a plus de lien sidebar direct vers ici.
    if request.user.role == 'mshrif':
        return redirect('mshrif_remuneration')

    from courses.models import OptionNbSeances, TarifRemunerationGroupe, TarifRemunerationIndividuel
    from courses.utils import couverture_tarifs_remuneration_groupe

    tarifs_groupe = TarifRemunerationGroupe.objects.all().order_by('tranche_age', 'nb_slots')
    context = {
        'tarifs_groupe_par_tranche': {
            'enfant': [t for t in tarifs_groupe if t.tranche_age == 'enfant'],
            'adulte': [t for t in tarifs_groupe if t.tranche_age == 'adulte'],
        },
        'tarifs_individuel': TarifRemunerationIndividuel.objects.all().order_by('tranche_age'),
        'couverture_groupe': couverture_tarifs_remuneration_groupe(),
        'options_nb_seances': OptionNbSeances.objects.filter(est_actif=True),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_tarifs_remuneration.html', context)


@role_required('admin')
def admin_tarif_remuneration_groupe_ajouter(request):
    """Ajoute (ou réactive) une ligne (tranche_age, nb_slots) — POST only,
    JAMAIS de vue GET dédiée (formulaire directement sur admin_tarifs_remuneration,
    même patron que admin_critere_option_ajouter). nb_slots revalidé contre le
    catalogue OptionNbSeances actif — jamais une confiance aveugle dans le POST
    (voir OptionNbSeances.__doc__)."""
    from courses.models import OptionNbSeances, TarifRemunerationGroupe

    if request.method == 'POST':
        tranche_age = request.POST.get('tranche_age')
        nb_slots_brut = request.POST.get('nb_slots')
        montant = request.POST.get('montant')
        valeurs_actives = set(OptionNbSeances.objects.filter(est_actif=True).values_list('valeur', flat=True))
        try:
            nb_slots = int(nb_slots_brut)
        except (TypeError, ValueError):
            nb_slots = None
        if tranche_age not in ('enfant', 'adulte') or nb_slots not in valeurs_actives or not montant:
            messages.error(request, 'بيانات غير صالحة — تحقق من الفئة العمرية وعدد الحصص والمبلغ.')
        else:
            TarifRemunerationGroupe.objects.update_or_create(
                tranche_age=tranche_age, nb_slots=nb_slots,
                defaults={'montant': montant, 'est_actif': True},
            )
            messages.success(request, 'تمت إضافة التعرفة بنجاح.')
    return redirect('admin_tarifs_remuneration')


@role_required('admin')
def admin_tarif_remuneration_groupe_modifier(request, tarif_id):
    from courses.models import TarifRemunerationGroupe
    tarif = get_object_or_404(TarifRemunerationGroupe, id=tarif_id)

    if request.method == 'POST':
        tarif.montant = request.POST.get('montant')
        tarif.est_actif = request.POST.get('est_actif') == 'on'
        tarif.save()
        messages.success(request, 'تم تعديل التعرفة بنجاح.')
        return redirect('admin_tarifs_remuneration')

    return render(request, 'dashboard/admin_tarif_remuneration_groupe_modifier.html', {
        'tarif': tarif,
        'base_template': _base_template_admin_ou_mshrif(request),
        **_contexte_base_mshrif(request),
    })


@role_required('admin')
def admin_tarif_remuneration_individuel_modifier(request, tarif_id):
    from courses.models import TarifRemunerationIndividuel
    tarif = get_object_or_404(TarifRemunerationIndividuel, id=tarif_id)

    if request.method == 'POST':
        tarif.montant = request.POST.get('montant')
        tarif.save()
        messages.success(request, 'تم تعديل التعرفة بنجاح.')
        return redirect('admin_tarifs_remuneration')

    return render(request, 'dashboard/admin_tarif_remuneration_individuel_modifier.html', {
        'tarif': tarif,
        'base_template': _base_template_admin_ou_mshrif(request),
        **_contexte_base_mshrif(request),
    })


# ==================== ADMIN — CATALOGUE "عدد الحصص الأسبوعية" (cases nb_slots) ====================
# Chantier "cases nb_slots configurables" du 2026-08-27 (Besoin 1.5) — catalogue
# PARTAGÉ entre la tarification élève (inscriptions.GrillePrixAbonnement, voir
# registration.utils.plage_nb_slots_grille_prix) et le barème salaire prof
# (TarifRemunerationGroupe ci-dessus). Seedé à 1/2/3 — le مدير/مشرف peut ajouter
# de nouvelles cases (ex: "4") ici ; jamais de suppression définitive, seulement
# un toggle actif/inactif (même convention que Creneau/TypeAbonnement).

@role_required('admin', 'mshrif')
def admin_options_nb_seances(request):
    from courses.models import OptionNbSeances
    context = {
        'options': OptionNbSeances.objects.all().order_by('valeur'),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_options_nb_seances.html', context)


@role_required('admin', 'mshrif')
def admin_option_nb_seances_ajouter(request):
    from courses.models import OptionNbSeances

    if request.method == 'POST':
        valeur_brute = (request.POST.get('valeur') or '').strip()
        try:
            valeur = int(valeur_brute)
        except (TypeError, ValueError):
            valeur = None
        if not valeur or valeur < 1:
            messages.error(request, 'عدد الحصص يجب أن يكون رقماً صحيحاً موجباً.')
        elif OptionNbSeances.objects.filter(valeur=valeur).exists():
            messages.error(request, f'العدد {valeur} موجود مسبقاً.')
        else:
            OptionNbSeances.objects.create(valeur=valeur, ordre=valeur)
            messages.success(
                request,
                f'تمت إضافة الحالة "{valeur} حصص/أسبوع" — لن تصبح قابلة للاستخدام في أي '
                'اشتراك أو تعرفة راتب قبل تحديد سعر/تعرفة خاصة بها.',
            )
    return redirect('admin_options_nb_seances')


@role_required('admin', 'mshrif')
def admin_option_nb_seances_toggle(request, option_id):
    from courses.models import OptionNbSeances
    option = get_object_or_404(OptionNbSeances, id=option_id)
    option.est_actif = not option.est_actif
    option.save()
    messages.info(request, 'تم تفعيل الحالة.' if option.est_actif else 'تم تعطيل الحالة.')
    return redirect('admin_options_nb_seances')


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
    from accounts.models import Superviseur, Prof, NotePersonnelle
    from chat.permissions import groupes_chat_accessibles_ids
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
        # Carnet de notes personnelles (Tâche du 2026-08-18) — cette page fait
        # déjà office de fiche détail مؤطر (bloc infos + gestion assignation),
        # voir accounts.models.NotePersonnelle.__doc__.
        'notes_personnelles': NotePersonnelle.objects.filter(
            profil_user=superviseur.user, auteur=request.user
        ),
        # Icône 💬 chat sur "المجموعات المسندة" (Chantier redesign icône-chat du
        # 2026-08-19) — consommé par dashboard/_liste_groupes_mesnad.html, vide
        # pour مشرف (voir chat.permissions.groupes_chat_accessibles_ids.__doc__),
        # donc l'icône ne s'affiche jamais pour lui sur cette page partagée.
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
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


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5A : CRUD Critere/
# CritereOption. Directeur ET مشرف ont un accès STRICTEMENT IDENTIQUE sur
# TOUTES ces vues (role_required('admin', 'mshrif') partout, sans exception,
# contrairement au patron admin-seul de admin_criteres/admin_critere_eleve_*
# plus haut dans ce fichier) — demande explicite et répétée du client pour ce
# système précis : "pas de hiérarchie entre eux dans cette interface".
# ============================================================================

@role_required('admin', 'mshrif')
def admin_criteres_inscription(request):
    from registration.models import Critere

    criteres = Critere.objects.all().order_by('ordre', 'id')
    context = {
        'criteres': criteres,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_criteres_inscription.html', context)


@role_required('admin', 'mshrif')
def admin_critere_inscription_ajouter(request):
    from django.core.exceptions import FieldDoesNotExist
    from courses.models import Groupe
    from registration.models import Critere

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if not code or Critere.objects.filter(code=code).exists():
            messages.error(request, 'الرمز إلزامي ويجب أن يكون فريداً — تحقق من عدم استخدامه من قبل.')
            return render(request, 'dashboard/admin_critere_inscription_ajouter.html', {
                'base_template': _base_template_admin_ou_mshrif(request),
                'valeurs_form': request.POST,
            })

        backend = request.POST.get('backend', 'eav')
        champ_modele_groupe = request.POST.get('champ_modele_groupe', '').strip()
        # Audit du 2026-08-23 (§1) : champ_modele_groupe était un simple champ
        # texte libre, jamais vérifié contre les vrais champs de Groupe —
        # une coquille (ou un nom inventé) créait un critère qui plantait le
        # wizard public en 500 dès qu'un candidat y répondait (FieldError
        # levée au moment du filtrage, jamais à la création). Vérifié ICI,
        # au seul endroit où ce champ est écrit (admin_critere_inscription_
        # modifier ne le touche jamais après coup, voir sa docstring).
        if backend == 'champ_groupe':
            if not champ_modele_groupe:
                messages.error(request, 'الرجاء تحديد اسم الحقل الحقيقي في نموذج المجموعة (Groupe).')
                return render(request, 'dashboard/admin_critere_inscription_ajouter.html', {
                    'base_template': _base_template_admin_ou_mshrif(request),
                    'valeurs_form': request.POST,
                })
            try:
                Groupe._meta.get_field(champ_modele_groupe)
            except FieldDoesNotExist:
                messages.error(
                    request,
                    f'الحقل "{champ_modele_groupe}" غير موجود فعلياً في نموذج المجموعة (Groupe) — '
                    f'تحقق من الاسم (حساس لحالة الأحرف).'
                )
                return render(request, 'dashboard/admin_critere_inscription_ajouter.html', {
                    'base_template': _base_template_admin_ou_mshrif(request),
                    'valeurs_form': request.POST,
                })

        critere = Critere.objects.create(
            code=code,
            label=request.POST.get('label', '').strip(),
            type_champ=request.POST.get('type_champ', 'choix_unique'),
            backend=backend,
            champ_modele_groupe=champ_modele_groupe,
            filtrable=request.POST.get('filtrable') == 'on',
            bloquant=request.POST.get('bloquant') == 'on',
            ordre=request.POST.get('ordre') or 0,
        )
        messages.success(request, f'تمت إضافة المعيار "{critere.label}" بنجاح.')
        return redirect('admin_critere_inscription_detail', critere.id)

    return render(request, 'dashboard/admin_critere_inscription_ajouter.html', {
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_critere_inscription_detail(request, critere_id):
    from registration.models import Critere, GroupeCritereValeur
    from registration.utils import couverture_critere

    critere = get_object_or_404(Critere, id=critere_id)
    context = {
        'critere': critere,
        'options': critere.options.all().order_by('ordre', 'id'),
        'couverture': couverture_critere(critere),
        'nb_champs_utilises': critere.champs.count(),
        # Chantier du 2026-08-25 : symétrique de couverture['groupes_manquants']
        # (déjà affiché) — ici les groupes DÉJÀ configurés pour ce critère, avec
        # une action pour les détacher un par un directement depuis cette page,
        # sans devoir ouvrir individuellement l'onglet "الخصائص" de chaque
        # groupe (courses.views.groupe_definir_critere). Uniquement pertinent
        # pour backend='eav' (seul backend qui stocke des GroupeCritereValeur,
        # voir GroupeCritereValeur.__doc__) — None sinon, même garde que
        # couverture_critere().
        'valeurs_groupes': (
            GroupeCritereValeur.objects.filter(critere=critere)
            .select_related('groupe', 'option').order_by('groupe__nom')
            if critere.backend == 'eav' else None
        ),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_critere_inscription_detail.html', context)


@role_required('admin', 'mshrif')
def admin_critere_inscription_modifier(request, critere_id):
    from registration.models import Critere
    from registration.utils import couverture_critere

    critere = get_object_or_404(Critere, id=critere_id)

    if request.method == 'POST':
        filtrable_demande = request.POST.get('filtrable') == 'on'
        confirme = request.POST.get('confirme') == '1'

        # Warning de configuration incomplète (Parties 7-8 du cahier des
        # charges) — évalué sur le backend ACTUEL du critère (jamais modifiable
        # depuis ce formulaire, voir plus bas) : couverture_critere renvoie None
        # pour champ_groupe/nb_slots, qui n'ont structurellement jamais de
        # "groupe non configuré" — aucun warning possible pour eux.
        couverture = couverture_critere(critere) if filtrable_demande else None
        if couverture and couverture['configures'] < couverture['total'] and not confirme:
            return render(request, 'dashboard/admin_critere_inscription_modifier.html', {
                'critere': critere,
                'couverture_warning': couverture,
                'valeurs_form': request.POST,
                'base_template': _base_template_admin_ou_mshrif(request),
            })

        critere.label = request.POST.get('label', '').strip()
        critere.type_champ = request.POST.get('type_champ', critere.type_champ)
        critere.filtrable = filtrable_demande
        critere.bloquant = request.POST.get('bloquant') == 'on'
        critere.ordre = request.POST.get('ordre') or 0
        critere.est_actif = request.POST.get('est_actif') == 'on'
        critere.save()
        messages.success(request, f'تم تعديل المعيار "{critere.label}" بنجاح.')
        return redirect('admin_critere_inscription_detail', critere.id)

    return render(request, 'dashboard/admin_critere_inscription_modifier.html', {
        'critere': critere,
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_critere_inscription_toggle(request, critere_id):
    from registration.models import Critere
    critere = get_object_or_404(Critere, id=critere_id)
    critere.est_actif = not critere.est_actif
    critere.save()
    messages.info(request, 'تم تفعيل المعيار.' if critere.est_actif else 'تم تعطيل المعيار — لن يظهر في نموذج التسجيل.')
    return redirect('admin_criteres_inscription')


@role_required('admin', 'mshrif')
def admin_critere_inscription_supprimer(request, critere_id):
    from django.db.models.deletion import ProtectedError
    from registration.models import Critere

    critere = get_object_or_404(Critere, id=critere_id)
    label = critere.label
    try:
        critere.delete()
        messages.success(request, f'تم حذف المعيار "{label}".')
    except ProtectedError:
        messages.error(
            request,
            f'تعذر حذف "{label}": هذا المعيار مستخدم بالفعل (في نموذج التسجيل، أو في إجابات/مجموعات '
            f'سابقة). يمكنك تعطيله بدلاً من حذفه للحفاظ على السجل التاريخي.'
        )
    return redirect('admin_criteres_inscription')


@role_required('admin', 'mshrif')
@require_POST
def admin_critere_inscription_detacher_groupe(request, critere_id, groupe_id):
    """Détache un critère (backend='eav') d'UN groupe précis, depuis la fiche
    du CRITÈRE (chantier du 2026-08-25 : GroupeCritereValeur.critere est
    on_delete=PROTECT — un critère assigné à ne serait-ce qu'un seul groupe
    ne peut jamais être supprimé tant que ce lien existe, voir admin_critere_
    inscription_supprimer). Réutilise TEL QUEL registration.utils.
    definir_valeurs_groupe(groupe, critere, []) — EXACTEMENT la même
    opération que courses.views.groupe_definir_critere quand aucune option
    n'est cochée, juste accessible depuis l'autre sens (la fiche critère,
    pratique pour détacher PLUSIEURS groupes d'affilée avant une suppression,
    sans ouvrir chaque fiche groupe une par une) : jamais une 2e façon
    d'écrire cette donnée."""
    from registration.models import Critere
    from registration.utils import definir_valeurs_groupe
    from courses.models import Groupe

    critere = get_object_or_404(Critere, id=critere_id)
    groupe = get_object_or_404(Groupe, id=groupe_id)
    if critere.backend != 'eav':
        messages.error(request, 'هذا المعيار مشتق تلقائياً ولا يمكن فك ارتباطه يدوياً.')
        return redirect('admin_critere_inscription_detail', critere.id)

    definir_valeurs_groupe(groupe, critere, [])
    messages.success(request, f'تم فك ارتباط "{critere.label}" عن مجموعة "{groupe.nom}".')
    return redirect('admin_critere_inscription_detail', critere.id)


# ---- Options d'un critère ----

@role_required('admin', 'mshrif')
def admin_critere_option_ajouter(request, critere_id):
    from registration.models import Critere, CritereOption

    critere = get_object_or_404(Critere, id=critere_id)
    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if not code or CritereOption.objects.filter(critere=critere, code=code).exists():
            messages.error(request, 'رمز الخيار إلزامي ويجب أن يكون فريداً ضمن هذا المعيار.')
            return redirect('admin_critere_inscription_detail', critere.id)

        CritereOption.objects.create(
            critere=critere, code=code,
            label=request.POST.get('label', '').strip(),
            ordre=request.POST.get('ordre') or 0,
        )
        messages.success(request, 'تمت إضافة الخيار بنجاح.')
    return redirect('admin_critere_inscription_detail', critere.id)


@role_required('admin', 'mshrif')
def admin_critere_option_modifier(request, option_id):
    from registration.models import CritereOption

    option = get_object_or_404(CritereOption, id=option_id)
    if request.method == 'POST':
        option.label = request.POST.get('label', '').strip()
        option.ordre = request.POST.get('ordre') or 0
        option.save()
        messages.success(request, 'تم تعديل الخيار بنجاح.')
        return redirect('admin_critere_inscription_detail', option.critere_id)

    return render(request, 'dashboard/admin_critere_option_modifier.html', {
        'option': option,
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_critere_option_toggle(request, option_id):
    from registration.models import CritereOption
    option = get_object_or_404(CritereOption, id=option_id)
    option.est_actif = not option.est_actif
    option.save()
    messages.info(request, 'تم تفعيل الخيار.' if option.est_actif else 'تم تعطيل الخيار.')
    return redirect('admin_critere_inscription_detail', option.critere_id)


@role_required('admin', 'mshrif')
def admin_critere_option_supprimer(request, option_id):
    from django.db.models.deletion import ProtectedError
    from registration.models import CritereOption

    option = get_object_or_404(CritereOption, id=option_id)
    critere_id = option.critere_id
    label = option.label
    try:
        option.delete()
        messages.success(request, f'تم حذف الخيار "{label}".')
    except ProtectedError:
        messages.error(
            request,
            f'تعذر حذف "{label}": هذا الخيار مستخدم بالفعل (في إجابات أو مجموعات سابقة). '
            f'يمكنك تعطيله بدلاً من حذفه.'
        )
    return redirect('admin_critere_inscription_detail', critere_id)


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5B : CRUD
# EtapeInscription / ChampInscription. Directeur ET مشرف,
# accès strictement identique (voir Étape 5A pour la justification).
# ============================================================================

@role_required('admin', 'mshrif')
def admin_etapes_inscription(request):
    from registration.models import EtapeInscription

    etapes = EtapeInscription.objects.all().order_by('ordre', 'id')
    context = {
        'etapes': etapes,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_etapes_inscription.html', context)


@role_required('admin', 'mshrif')
def admin_etape_inscription_ajouter(request):
    from registration.models import EtapeInscription

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if not code or EtapeInscription.objects.filter(code=code).exists():
            messages.error(request, 'الرمز إلزامي ويجب أن يكون فريداً.')
            return render(request, 'dashboard/admin_etape_inscription_ajouter.html', {
                'base_template': _base_template_admin_ou_mshrif(request),
                'valeurs_form': request.POST,
            })
        etape = EtapeInscription.objects.create(
            code=code,
            titre=request.POST.get('titre', '').strip(),
            ordre=request.POST.get('ordre') or 0,
        )
        messages.success(request, f'تمت إضافة المرحلة "{etape.titre}" بنجاح.')
        return redirect('admin_etape_inscription_detail', etape.id)

    return render(request, 'dashboard/admin_etape_inscription_ajouter.html', {
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_etape_inscription_detail(request, etape_id):
    from registration.models import Critere, EtapeInscription

    etape = get_object_or_404(EtapeInscription, id=etape_id)
    context = {
        'etape': etape,
        'champs': etape.champs.all().select_related('critere').order_by('ordre', 'id'),
        # ConfigurationChampStructurel (chantier du 2026-08-22) : affichés
        # dans la MÊME liste "الحقول" que les ChampInscription — le مدير voit
        # tout au même endroit, jamais "لا توجد حقول بعد" alors que des
        # champs structurels réels (nom/sexe/téléphone...) sont déjà en
        # place et utilisés.
        'champs_structurels': etape.champs_structurels.all().order_by('ordre', 'id'),
        # Chantier du 2026-08-23 (Partie 2, séparation Système A/B) :
        # SEULS les critères choix_unique/choix_multiple filtrent
        # réellement (voir registration.utils.groupes_compatibles — le
        # backend 'eav' ne compare jamais que des CritereOption, jamais du
        # texte libre). Un critère texte/nombre/date/email/téléphone/
        # booléen ne serait donc JAMAIS un choix utile ici, même si
        # 'filtrable' est coché dessus — filtré pour ne plus jamais
        # laisser le مدير se piéger en le liant à un champ "تصفية".
        'criteres_disponibles': Critere.objects.filter(
            est_actif=True, type_champ__in=['choix_unique', 'choix_multiple'],
        ).order_by('ordre'),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_etape_inscription_detail.html', context)


@role_required('admin', 'mshrif')
def admin_etape_inscription_modifier(request, etape_id):
    """Correction 8 (2026-08-22, navigation dynamique) : `ordre` pilote
    désormais RÉELLEMENT la page suivante visitée par l'élève (voir
    registration.utils.etape_suivante) — plus une simple valeur cosmétique.
    Une étape verrouillée (EtapeInscription.CODES_VERROUILLES) reste
    modifiable en titre/ordre, mais `est_actif` posté est ignoré : model.
    save() le réécrirait de toute façon (défense en profondeur), même
    principe exact que admin_champ_structurel_modifier."""
    from registration.models import EtapeInscription

    etape = get_object_or_404(EtapeInscription, id=etape_id)
    verrouillee = etape.est_verrouillee
    if request.method == 'POST':
        etape.titre = request.POST.get('titre', '').strip()
        etape.ordre = request.POST.get('ordre') or 0
        if not verrouillee:
            etape.est_actif = request.POST.get('est_actif') == 'on'
        etape.save()
        messages.success(request, f'تم تعديل المرحلة "{etape.titre}" بنجاح.')
        return redirect('admin_etape_inscription_detail', etape.id)

    return render(request, 'dashboard/admin_etape_inscription_modifier.html', {
        'etape': etape,
        'verrouillee': verrouillee,
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_etape_inscription_toggle(request, etape_id):
    from registration.models import EtapeInscription
    etape = get_object_or_404(EtapeInscription, id=etape_id)
    if etape.est_verrouillee:
        messages.error(
            request,
            f'"{etape.titre}" مرحلة أساسية للتسجيل ولا يمكن تعطيلها — راجع تفاصيل المرحلة لمعرفة السبب.'
        )
        return redirect('admin_etapes_inscription')
    etape.est_actif = not etape.est_actif
    etape.save()
    messages.info(request, 'تم تفعيل المرحلة.' if etape.est_actif else 'تم تعطيل المرحلة — لن تظهر في نموذج التسجيل.')
    return redirect('admin_etapes_inscription')


@role_required('admin', 'mshrif')
def admin_etape_inscription_supprimer(request, etape_id):
    from django.db.models.deletion import ProtectedError
    from registration.models import EtapeInscription

    etape = get_object_or_404(EtapeInscription, id=etape_id)
    titre = etape.titre
    if etape.est_verrouillee:
        # Contrairement au garde-fou ProtectedError ci-dessous (déclenché
        # seulement si des ChampInscription y sont déjà rattachés) : ces 5
        # étapes n'ont souvent AUCUN champ (groupe/abonnement/paiement/
        # confirmation/categorie_age ne rendent jamais de ChampInscription
        # générique) — ProtectedError ne se déclencherait donc jamais pour
        # elles, un vrai risque de suppression silencieuse sans ce garde
        # explicite.
        messages.error(request, f'"{titre}" مرحلة أساسية للتسجيل ولا يمكن حذفها.')
        return redirect('admin_etapes_inscription')
    try:
        etape.delete()
        messages.success(request, f'تم حذف المرحلة "{titre}".')
    except ProtectedError:
        messages.error(
            request,
            f'تعذر حذف "{titre}": هذه المرحلة تحتوي على حقول. احذف/انقل الحقول أولاً، أو عطّل المرحلة بدلاً من حذفها.'
        )
    return redirect('admin_etapes_inscription')


# ---- Champs d'une étape ----

def _parse_entier_optionnel(valeur_brute):
    """int ou None depuis un champ POST optionnel (ex: valeur_min/valeur_max,
    Partie 3, chantier du 2026-08-23) — chaîne vide ou non numérique ->
    None (aucune borne), jamais une erreur pour ce formulaire admin de
    confiance (même esprit que `ordre` ailleurs dans ce fichier, jamais
    validé non plus)."""
    valeur_brute = (valeur_brute or '').strip()
    if not valeur_brute:
        return None
    try:
        return int(valeur_brute)
    except ValueError:
        return None


@role_required('admin', 'mshrif')
def admin_champ_inscription_ajouter(request, etape_id):
    from registration.models import ChampInscription, Critere, EtapeInscription

    etape = get_object_or_404(EtapeInscription, id=etape_id)
    if request.method == 'POST':
        # Audit du 2026-08-23 (§2) : voir registration.models.EtapeInscription.
        # CODES_SANS_RENDU_GENERIQUE — ces 5 étapes n'affichent JAMAIS un
        # ChampInscription générique sur le wizard public, quel que soit
        # ce qu'on y attache ici. Bloqué à la source plutôt que de laisser
        # créer un champ invisible mais quand même validé (et potentiellement
        # bloquant si obligatoire) à la confirmation finale.
        if not etape.accepte_champs_generiques:
            messages.error(
                request,
                f'تعذرت الإضافة: مرحلة "{etape.titre}" لا تعرض أي حقل عام على نموذج التسجيل العلني '
                f'(لديها شاشتها الخاصة المبنية في الكود). أي حقل يُضاف هنا لن يظهر أبداً للمترشح — '
                f'استخدم مرحلة "المعلومات الشخصية" أو "اختيار البرنامج" أو أنشئ مرحلة مخصصة جديدة بدلاً من ذلك.'
            )
            return redirect('admin_etape_inscription_detail', etape.id)

        critere_id = request.POST.get('critere_id') or None
        critere = get_object_or_404(Critere, id=critere_id) if critere_id else None
        type_champ = request.POST.get('type_champ', '') if critere is None else ''

        ChampInscription.objects.create(
            etape=etape,
            critere=critere,
            type_champ=type_champ,
            # valeur_min/valeur_max (Partie 3) : sans objet hors type_champ=
            # 'nombre' — jamais enregistrées dans les autres cas, même si le
            # POST en contenait (champ caché côté client, mais jamais fait
            # confiance côté serveur).
            valeur_min=_parse_entier_optionnel(request.POST.get('valeur_min')) if type_champ == 'nombre' else None,
            valeur_max=_parse_entier_optionnel(request.POST.get('valeur_max')) if type_champ == 'nombre' else None,
            label=request.POST.get('label', '').strip(),
            obligatoire=request.POST.get('obligatoire') == 'on',
            ordre=request.POST.get('ordre') or 0,
        )
        messages.success(request, 'تمت إضافة الحقل بنجاح.')
    return redirect('admin_etape_inscription_detail', etape.id)


@role_required('admin', 'mshrif')
def admin_champ_inscription_modifier(request, champ_id):
    from registration.models import ChampInscription, Critere
    from registration.utils import couverture_critere

    champ = get_object_or_404(ChampInscription, id=champ_id)

    if request.method == 'POST':
        obligatoire_demande = request.POST.get('obligatoire') == 'on'
        confirme = request.POST.get('confirme') == '1'

        # Rendre un champ obligatoire alors que le critère lié n'est pas
        # entièrement couvert par les groupes actifs mérite le même
        # avertissement qu'activer filtrable=True (Parties 7-8) — un champ
        # obligatoire mais mal couvert bloquerait des candidats sans groupe
        # disponible pour eux.
        couverture = None
        if champ.critere and obligatoire_demande:
            couverture = couverture_critere(champ.critere)
        if couverture and couverture['configures'] < couverture['total'] and not confirme:
            return render(request, 'dashboard/admin_champ_inscription_modifier.html', {
                'champ': champ, 'couverture_warning': couverture,
                'base_template': _base_template_admin_ou_mshrif(request),
            })

        champ.label = request.POST.get('label', '').strip()
        champ.obligatoire = obligatoire_demande
        champ.ordre = request.POST.get('ordre') or 0
        champ.est_actif = request.POST.get('est_actif') == 'on'
        if champ.critere is None:
            champ.type_champ = request.POST.get('type_champ', champ.type_champ)
            # valeur_min/valeur_max (Partie 3, chantier du 2026-08-23) :
            # sans objet hors type_champ='nombre' — remises à None dans les
            # autres cas plutôt que de laisser une ancienne borne orpheline
            # et invisible si le مدير change le type après coup.
            if champ.type_champ == 'nombre':
                champ.valeur_min = _parse_entier_optionnel(request.POST.get('valeur_min'))
                champ.valeur_max = _parse_entier_optionnel(request.POST.get('valeur_max'))
            else:
                champ.valeur_min = None
                champ.valeur_max = None
        champ.save()
        messages.success(request, 'تم تعديل الحقل بنجاح.')
        return redirect('admin_etape_inscription_detail', champ.etape_id)

    return render(request, 'dashboard/admin_champ_inscription_modifier.html', {
        'champ': champ,
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_champ_inscription_toggle(request, champ_id):
    from registration.models import ChampInscription
    champ = get_object_or_404(ChampInscription, id=champ_id)
    champ.est_actif = not champ.est_actif
    champ.save()
    messages.info(request, 'تم تفعيل الحقل.' if champ.est_actif else 'تم تعطيل الحقل.')
    return redirect('admin_etape_inscription_detail', champ.etape_id)


@role_required('admin', 'mshrif')
def admin_champ_inscription_supprimer(request, champ_id):
    from django.db.models.deletion import ProtectedError
    from registration.models import ChampInscription

    champ = get_object_or_404(ChampInscription, id=champ_id)
    etape_id = champ.etape_id
    label = champ.label
    try:
        champ.delete()
        messages.success(request, f'تم حذف الحقل "{label}".')
    except ProtectedError:
        messages.error(
            request,
            f'تعذر حذف "{label}": هذا الحقل استُخدم بالفعل في طلبات تسجيل سابقة. '
            f'يمكنك تعطيله بدلاً من حذفه للحفاظ على السجل التاريخي.'
        )
    return redirect('admin_etape_inscription_detail', etape_id)


# ---- Champs structurels (chantier du 2026-08-22) ----
# Configuration d'AFFICHAGE des champs structurels fixes de InscriptionEleve
# (nom/nom_parent/sexe/telephone/date_naissance/email/job_actuel/
# niveau_scolaire) — voir registration.models.ConfigurationChampStructurel
# pour la décision complète. PAS de vue "ajouter" (les 8 lignes sont seedées
# une fois, jamais recréées depuis l'admin — même esprit que courses.models.
# TarifRemuneration, "grille fixe... seul le montant est modifiable") ni de
# vue "supprimer" (une vraie colonne ne peut pas disparaître : "supprimer"
# un champ structurel = le désactiver, même convention que Creneau.est_actif/
# ChampInscription.est_actif partout ailleurs dans ce projet).

@role_required('admin', 'mshrif')
def admin_champ_structurel_modifier(request, config_id):
    from registration.models import ConfigurationChampStructurel, EtapeInscription

    config = get_object_or_404(ConfigurationChampStructurel, id=config_id)
    verrouille = config.champ_cle in ConfigurationChampStructurel.CLES_VERROUILLEES
    sans_type_champ = config.champ_cle in ConfigurationChampStructurel.CLES_SANS_TYPE_CHAMP

    if request.method == 'POST':
        config.label = request.POST.get('label', '').strip() or config.label
        config.ordre = request.POST.get('ordre') or 0
        # Le reste est ignoré pour les clés verrouillées (sexe/date_naissance/
        # email) — model.save() les réécrit de toute façon (défense en
        # profondeur), mais autant ne pas prétendre les avoir pris en compte.
        if not verrouille:
            etape_id = request.POST.get('etape_id')
            if etape_id:
                config.etape = get_object_or_404(EtapeInscription, id=etape_id)
            config.obligatoire = request.POST.get('obligatoire') == 'on'
            config.est_actif = request.POST.get('est_actif') == 'on'
            if not sans_type_champ:
                config.type_champ = request.POST.get('type_champ', 'texte')
                config.placeholder = request.POST.get('placeholder', '').strip()
                config.texte_aide = request.POST.get('texte_aide', '').strip()
                config.regex_validation = request.POST.get('regex_validation', '').strip()
                config.message_erreur_regex = request.POST.get('message_erreur_regex', '').strip()
        config.save()
        messages.success(request, f'تم تعديل الحقل البنيوي "{config.label}" بنجاح.')
        return redirect('admin_etape_inscription_detail', config.etape_id)

    context = {
        'config': config,
        'verrouille': verrouille,
        'sans_type_champ': sans_type_champ,
        'etapes': EtapeInscription.objects.filter(est_actif=True).order_by('ordre'),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_champ_structurel_modifier.html', context)


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5C : MoyenPaiement +
# PresentationInscription. Directeur ET مشرف, accès strictement identique.
# ============================================================================

@role_required('admin', 'mshrif')
def admin_moyens_paiement(request):
    from payments.models import MoyenPaiement

    moyens = MoyenPaiement.objects.all().order_by('ordre', 'id')
    context = {
        'moyens': moyens,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_moyens_paiement.html', context)


@role_required('admin', 'mshrif')
def admin_moyen_paiement_ajouter(request):
    from payments.models import MoyenPaiement

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        if not code or MoyenPaiement.objects.filter(code=code).exists():
            messages.error(request, 'الرمز إلزامي ويجب أن يكون فريداً.')
            return render(request, 'dashboard/admin_moyen_paiement_ajouter.html', {
                'base_template': _base_template_admin_ou_mshrif(request),
                'valeurs_form': request.POST,
            })
        MoyenPaiement.objects.create(
            code=code,
            label=request.POST.get('label', '').strip(),
            coordonnees=request.POST.get('coordonnees', '').strip(),
            ordre=request.POST.get('ordre') or 0,
        )
        messages.success(request, 'تمت إضافة طريقة الدفع بنجاح.')
        return redirect('admin_moyens_paiement')

    return render(request, 'dashboard/admin_moyen_paiement_ajouter.html', {
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_moyen_paiement_modifier(request, moyen_id):
    from payments.models import MoyenPaiement
    moyen = get_object_or_404(MoyenPaiement, id=moyen_id)

    if request.method == 'POST':
        moyen.label = request.POST.get('label', '').strip()
        moyen.coordonnees = request.POST.get('coordonnees', '').strip()
        moyen.ordre = request.POST.get('ordre') or 0
        moyen.save()
        messages.success(request, 'تم تعديل طريقة الدفع بنجاح.')
        return redirect('admin_moyens_paiement')

    return render(request, 'dashboard/admin_moyen_paiement_modifier.html', {
        'moyen': moyen,
        'base_template': _base_template_admin_ou_mshrif(request),
    })


@role_required('admin', 'mshrif')
def admin_moyen_paiement_toggle(request, moyen_id):
    from payments.models import MoyenPaiement
    moyen = get_object_or_404(MoyenPaiement, id=moyen_id)
    moyen.est_actif = not moyen.est_actif
    moyen.save()
    messages.info(request, 'تم تفعيل طريقة الدفع.' if moyen.est_actif else 'تم تعطيل طريقة الدفع.')
    return redirect('admin_moyens_paiement')


@role_required('admin', 'mshrif')
def admin_presentation_inscription(request):
    from registration.models import get_presentation_inscription

    presentation = get_presentation_inscription()
    if request.method == 'POST':
        presentation.titre = request.POST.get('titre', '').strip()
        presentation.intro = request.POST.get('intro', '').strip()
        presentation.bouton_texte = request.POST.get('bouton_texte', '').strip() or 'متابعة التسجيل'
        presentation.message_bienvenue = request.POST.get('message_bienvenue', '').strip()
        # Chantier du 2026-08-22 ("liberté totale du nombre de séances") :
        # message affiché à wizard_groupe quand aucun groupe ne correspond
        # exactement — voir registration.models.DemandeNonSatisfaite.
        presentation.message_aucun_groupe_exact = request.POST.get('message_aucun_groupe_exact', '').strip()
        # Chantier du 2026-08-25 : texte de la carte "⏳ لا، أنتظر حتى يتم
        # إنشاء الحلقة" à côté des groupes proches (même écran ci-dessus).
        presentation.texte_attente_groupe = request.POST.get('texte_attente_groupe', '').strip()
        # Chantier i18n du 2026-08-28 ("Problème B") : traductions FR/EN saisies
        # à la main par le مدير/مشرف, toutes optionnelles — jamais required ici,
        # PresentationInscription._localise retombe sur l'arabe si vide.
        for champ in presentation._CHAMPS_LOCALISABLES:
            for langue in ('fr', 'en'):
                setattr(presentation, f'{champ}_{langue}', request.POST.get(f'{champ}_{langue}', '').strip())
        # Chantier du 2026-08-27 : matrice de disponibilités optionnelle EN
        # PLUS de la carte "attente" ci-dessus (jamais à sa place — voir
        # PresentationInscription.afficher_disponibilites_si_attente.__doc__).
        presentation.afficher_disponibilites_si_attente = request.POST.get('afficher_disponibilites_si_attente') == '1'
        presentation.save()
        messages.success(request, 'تم تحديث صفحة تقديم التسجيل بنجاح.')
        return redirect('admin_presentation_inscription')

    context = {
        'presentation': presentation,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_presentation_inscription.html', context)


@role_required('admin', 'mshrif')
def admin_demandes_non_satisfaites(request):
    """Liste + comptage par combinaison des DemandeNonSatisfaite (chantier
    du 2026-08-22, "liberté totale du nombre de séances") — objectif :
    identifier les combinaisons les plus demandées pour décider quels
    nouveaux groupes ouvrir. Regroupement en Python (pas de GROUP BY SQL
    lisible sur un JSONField) : le volume réel de ces demandes reste faible
    (un événement occasionnel, pas une table à fort trafic), une boucle
    Python est largement suffisante et bien plus lisible qu'une agrégation
    SQL sur JSON."""
    from collections import Counter
    from registration.models import Critere, CritereOption, DemandeNonSatisfaite

    demandes = list(DemandeNonSatisfaite.objects.select_related('inscription').order_by('-date_demande'))

    # Labels lisibles résolus à la LECTURE (Critere/CritereOption restent la
    # seule source de vérité, jamais dupliqués dans DemandeNonSatisfaite).
    criteres_par_code = {c.code: c for c in Critere.objects.all()}
    options_par_cle = {(o.critere_id, o.code): o for o in CritereOption.objects.select_related('critere')}

    def _libelles_criteres(criteres):
        """criteres : itérable de (code_critere, valeur) — accepte un
        dict.items() (demande individuelle) ou le tuple trié utilisé comme
        clé de regroupement ci-dessous, même logique dans les 2 cas."""
        libelles = []
        for code_critere, valeur in criteres:
            critere = criteres_par_code.get(code_critere)
            if critere is None:
                continue
            if critere.backend in ('nb_slots', 'champ_groupe'):
                libelles.append(f"{critere.label}: {valeur}")
            elif isinstance(valeur, (list, tuple)):
                labels = [options_par_cle[(critere.id, c)].label for c in valeur if (critere.id, c) in options_par_cle]
                if labels:
                    libelles.append(f"{critere.label}: {', '.join(labels)}")
            else:
                option = options_par_cle.get((critere.id, valeur))
                libelles.append(f"{critere.label}: {option.label if option else valeur}")
        return libelles

    # Détail ligne par ligne (correction du 2026-08-24) : les mêmes libellés
    # que "أكثر التركيبات طلباً" ci-dessous, mais par DEMANDE individuelle —
    # + le contact, pour que le مدير puisse agir directement depuis cette
    # page. inscription.{nom,telephone,email} priment sur le snapshot
    # (nom/telephone/email propres à DemandeNonSatisfaite, voir son
    # docstring) quand la candidature existe : plus susceptibles d'être à
    # jour si le candidat les a corrigés plus loin dans le wizard.
    for d in demandes:
        d.libelles = _libelles_criteres(d.criteres_json.items())
        if d.inscription:
            d.nom_contact = d.inscription.nom
            d.telephone_contact = d.inscription.telephone
            d.email_contact = d.inscription.email
        else:
            d.nom_contact = d.nom
            d.telephone_contact = d.telephone
            d.email_contact = d.email

    # Regroupe par (criteres_json, nb_slots) — âge/sexe restent des détails
    # individuels affichés par demande, pas un axe de regroupement (sinon
    # 2 demandes identiques par ailleurs mais d'âges différents ne
    # compteraient jamais comme "la même tendance"). criteres_json peut
    # contenir des LISTES en valeur (critères choix_multiple, voir
    # DemandeNonSatisfaite.criteres_json) — une liste n'est pas hashable,
    # donc pas utilisable telle quelle comme clé de dict/Counter (bug du
    # 2026-08-22, TypeError: unhashable type: 'list'). On la convertit en
    # tuple avant hachage, uniquement pour cette clé de regroupement —
    # jamais persisté, criteres_json lui-même reste un dict/liste normal.

    # Filtre "حالة التسجيل" (chantier du 2026-08-27) : complet = liée à une
    # InscriptionEleve (d.inscription_id), incomplet = candidat parti avant
    # la fin du wizard (même critère que le badge déjà affiché sur chaque
    # carte, voir _carte_demande_non_satisfaite.html). S'applique à la fois à
    # la liste détaillée "كل الطلبات" ET à "أكثر التركيبات طلباً" (les
    # tendances ne sont qu'un regroupement de ces mêmes demandes — les
    # calculer sur `demandes_affichees` plutôt que sur `demandes` garde les 2
    # sections cohérentes entre elles une fois le filtre actif). Seuls les
    # compteurs du haut ("إجمالي" et "تحولت إلى تسجيل فعلي") restent
    # globaux : ce sont des indicateurs d'ensemble sur toutes les demandes
    # (utiles pour décider quels groupes ouvrir), pas un résumé de ce qui est
    # affiché en dessous — les recalculer rendrait "تحولت إلى تسجيل فعلي"
    # trivial (0 ou = au total) dès qu'un filtre est actif.
    filtre_statut = request.GET.get('statut', '')
    if filtre_statut == 'complete':
        demandes_affichees = [d for d in demandes if d.inscription_id]
    elif filtre_statut == 'incomplete':
        demandes_affichees = [d for d in demandes if not d.inscription_id]
    else:
        demandes_affichees = demandes

    compteur = Counter()
    exemple_par_cle = {}
    for d in demandes_affichees:
        criteres_hashables = tuple(sorted(
            (k, tuple(v) if isinstance(v, list) else v)
            for k, v in d.criteres_json.items()
        ))
        cle = (criteres_hashables, d.nb_slots)
        compteur[cle] += 1
        exemple_par_cle.setdefault(cle, d)

    tendances = []
    for cle, nombre in compteur.most_common():
        criteres_dict, nb_slots = cle
        tendances.append({'libelles': _libelles_criteres(criteres_dict), 'nb_slots': nb_slots, 'nombre': nombre})

    context = {
        'demandes': demandes_affichees,
        'filtre_statut': filtre_statut,
        'tendances': tendances,
        'total': len(demandes),
        'nb_liees_a_une_inscription': sum(1 for d in demandes if d.inscription_id),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_demandes_non_satisfaites.html', context)


@role_required('admin', 'mshrif')
def admin_demande_non_satisfaite_detail(request, demande_id):
    """Détail d'UNE DemandeNonSatisfaite (chantier du 2026-08-25, "cartes
    cliquables" de admin_demandes_non_satisfaites) — même niveau d'info que
    la carte de la liste, présenté en fiche complète (même esprit que admin_
    inscription_eleve_detail).

    Résolution des libellés DUPLIQUÉE ici depuis admin_demandes_non_
    satisfaites (plutôt que factorisée en fonction commune) : cette page ne
    traite qu'UNE SEULE demande à la fois, aucun risque de N+1 à éviter ici
    contrairement à la liste — factoriser aurait forcé la liste à recalculer
    criteres_par_code/options_par_cle À CHAQUE ligne au lieu d'une fois pour
    toutes les demandes (voir la docstring de admin_demandes_non_satisfaites)."""
    from registration.models import Critere, CritereOption, DemandeNonSatisfaite

    demande = get_object_or_404(DemandeNonSatisfaite, id=demande_id)

    criteres_par_code = {c.code: c for c in Critere.objects.all()}
    options_par_cle = {(o.critere_id, o.code): o for o in CritereOption.objects.select_related('critere')}
    libelles = []
    for code_critere, valeur in demande.criteres_json.items():
        critere = criteres_par_code.get(code_critere)
        if critere is None:
            continue
        if critere.backend in ('nb_slots', 'champ_groupe'):
            libelles.append(f"{critere.label}: {valeur}")
        elif isinstance(valeur, (list, tuple)):
            labels = [options_par_cle[(critere.id, c)].label for c in valeur if (critere.id, c) in options_par_cle]
            if labels:
                libelles.append(f"{critere.label}: {', '.join(labels)}")
        else:
            option = options_par_cle.get((critere.id, valeur))
            libelles.append(f"{critere.label}: {option.label if option else valeur}")

    # inscription.{nom,telephone,email} priment sur le snapshot quand la
    # candidature existe — même règle que admin_demandes_non_satisfaites
    # (voir DemandeNonSatisfaite.nom.__doc__).
    if demande.inscription:
        nom_contact = demande.inscription.nom
        telephone_contact = demande.inscription.telephone
        email_contact = demande.inscription.email
    else:
        nom_contact = demande.nom
        telephone_contact = demande.telephone
        email_contact = demande.email

    context = {
        'demande': demande,
        'libelles': libelles,
        'nom_contact': nom_contact,
        'telephone_contact': telephone_contact,
        'email_contact': email_contact,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_demande_non_satisfaite_detail.html', context)


@role_required('admin', 'mshrif')
@require_POST
def admin_demande_non_satisfaite_supprimer(request, demande_id):
    """Suppression définitive d'une DemandeNonSatisfaite (chantier du
    2026-08-25) — retire cette demande de la liste ET de tous les
    comptages (total, tendances). Action destructive, confirmée côté
    template avant soumission (voir admin_demandes_non_satisfaites.html) —
    même patron que admin_eleve_cartable_supprimer (POST + csrf + confirm)."""
    from registration.models import DemandeNonSatisfaite

    demande = get_object_or_404(DemandeNonSatisfaite, id=demande_id)
    demande.delete()
    messages.success(request, 'تم حذف الطلب.')
    return redirect('admin_demandes_non_satisfaites')


# Options de nombre de séances (cases "عدد الحصص الأسبوعية" de l'étape 2 du
# wizard public) : vues admin déjà définies plus haut dans ce fichier
# (catalogue partagé courses.OptionNbSeances, chantier du 2026-08-27) — pas
# de doublon ici, voir registration.utils.valeurs_options_nb_seances_actives
# pour comment le wizard le réutilise.


# ==================== MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 7 ====================
# Ajout manuel d'une candidature élève par le Directeur ou le مشرف — même
# service que le wizard public (registration.utils.inscrire_eleve), même
# source de champs (registration.utils.evaluer_champs_actifs). Directeur et
# مشرف : accès strictement identique (role_required('admin', 'mshrif'), pas
# de hiérarchie entre eux, comme partout ailleurs dans ce chantier).

def _champs_identite_bruts(request):
    """Extrait les champs d'identité fixes depuis request.POST — même liste
    de clés que registration.views.wizard_identite (Étape 6A), jamais une 2e
    liste divergente. Le téléphone n'est PAS inclus ici : sa construction
    passe par inscriptions.views._construire_et_valider_telephone (voir
    admin_eleve_ajouter_manuel), qui a besoin de request en entier."""
    return {
        'nom': request.POST.get('nom', '').strip(),
        'nom_parent': request.POST.get('nom_parent', '').strip(),
        'sexe': request.POST.get('sexe', ''),
        'email': request.POST.get('email', '').strip(),
        'date_naissance': request.POST.get('date_naissance', ''),
        'job_actuel': request.POST.get('job_actuel', '').strip(),
        'niveau_scolaire': request.POST.get('niveau_scolaire', '').strip(),
    }


def _champs_pour_template(resultats, valeurs_form):
    """Transforme la sortie de evaluer_champs_actifs (liste de dicts {champ,
    paires, erreur, masque}) en une liste directement consommable par le
    template (chaque champ porte déjà sa valeur déjà soumise, le template
    n'a donc jamais besoin d'un lookup dict-par-variable, non supporté
    nativement par le moteur de templates Django). 'valeur' : scalaire (pour
    pré-remplir un input/select), 'valeurs_liste' : toujours une liste, même
    à un seul élément (pour rejouer un choix_multiple en champs cachés vers
    le round 'confirmation' sans en perdre aucun — voir admin_eleve_ajouter_
    manuel.html)."""
    champs = []
    for r in resultats:
        valeur_brute = (valeurs_form or {}).get(f"champ_{r['champ'].id}")
        if isinstance(valeur_brute, list):
            valeurs_liste = valeur_brute
            valeur = valeur_brute[0] if valeur_brute else ''
        else:
            valeurs_liste = [valeur_brute] if valeur_brute else []
            valeur = valeur_brute or ''
        champs.append({'champ': r['champ'], 'masque': r['masque'], 'valeur': valeur, 'valeurs_liste': valeurs_liste})
    return champs


@role_required('admin', 'mshrif')
def admin_eleve_ajouter_manuel(request):
    """Étape 7 du chantier du moteur d'inscription configurable — ajout manuel
    d'une candidature élève par le Directeur ou le مشرف (permissions
    strictement identiques, voir le décorateur ci-dessus), pour le cas d'une
    inscription prise par téléphone/en présentiel, jamais passée par le
    formulaire public.

    ZÉRO logique dupliquée avec le wizard public (registration/views.py,
    Étape 6) :
    - registration.utils.evaluer_champs_actifs() pour la liste des champs à
      afficher (toutes étapes actives, dans l'ordre) — LA MÊME requête
      ChampInscription que le wizard, jamais une 2e liste maintenue ici
      (voir AdminAjouterEleveManuelTests.test_meme_source_champs_actifs_
      que_wizard_public).
    - registration.utils.groupes_compatibles_avec_age()/statut_compatibilite_
      groupe() pour la compatibilité groupe — même règle exacte que celle que
      inscrire_eleve() applique en interne à la confirmation finale.
    - registration.utils.inscrire_eleve() pour la création finale, avec
      cree_par=request.user (contrairement au wizard public où cree_par=None)
      pour tracer qui a fait l'ajout manuel.
    - inscriptions.views._construire_et_valider_telephone(request) réutilisée
      TEL QUEL, exactement comme le wizard public (Étape 4 l'anticipait déjà
      explicitement pour "l'Étape 6/7").

    Différence de comportement AUTORISÉE, réservée à cette vue (jamais au
    formulaire public) : un désaccord sur un critère filtrable NON bloquant
    entre les réponses et le groupe choisi n'empêche pas la création — un
    avertissement est affiché, contournable par une confirmation explicite du
    Directeur/مشرف (confirme_override=True, transmis tel quel à inscrire_
    eleve()). L'âge et tout critère bloquant=True restent des contraintes
    dures, non contournables — inscrire_eleve() lui-même l'impose, pas cette
    vue (voir statut_compatibilite_groupe : jamais 'contournable' dans ces
    2 cas).

    Flux en 2 temps, sans état serveur (contrairement au wizard public : une
    saisie manuelle se fait en une seule session de travail continue, de
    simples champs cachés HTML suffisent) :
    1. round_form='identite' (par défaut) : nom/sexe/email/téléphone/date de
       naissance + tous les ChampInscription actifs, rendu générique. Soumis
       -> calcule les réponses, AUCUNE création à ce stade.
    2. round_form='confirmation' : choix du groupe (si le critère champ_groupe
       vaut 'groupe', liste calculée par groupes_compatibles_avec_age, comme
       wizard_groupe) et de l'abonnement, le reste en champs cachés (identité
       + champ_<id> déjà répondus, MÊME limite déjà acceptée par le wizard
       public : un choix_multiple n'est pas re-coché visuellement s'il faut
       revenir en arrière, voir wizard_programme.html). Soumis :
       - si un avertissement contournable existe et n'a pas encore été
         confirmé (confirme_override absent) -> réaffiche CE round avec le
         bandeau d'avertissement + un bouton de confirmation explicite, AUCUNE
         création.
       - sinon -> inscrire_eleve(donnees, cree_par=request.user,
         confirme_override=<coché ou non>) — SEUL point de création,
         identique au wizard public.

    Aucune vue de modification n'existe sur la candidature créée ni ses
    ReponseInscription (immutabilité, comme le public, voir registration/
    views.py) — succès redirige vers la fiche de candidature EXISTANTE
    (admin_inscription_eleve_detail), où le Directeur/مشرف la valide ensuite
    EXACTEMENT comme n'importe quelle autre candidature (admin_valider_eleve,
    déjà existant, inchangé par cette vue) : choix délibérément prudent et
    réversible — rien n'est activé automatiquement, un second geste explicite
    reste nécessaire avant la création réelle du compte élève. Documenté
    comme tel dans le résumé de fin de session : si le Directeur préfère à
    l'usage une validation immédiate en un seul clic pour ce cas précis
    (ajout manuel = déjà "vérifié" par construction), c'est un changement
    ultérieur simple (appeler admin_valider_eleve juste après), pas encore
    fait ici faute d'une confirmation explicite que ce comportement est
    voulu."""
    import json
    from courses.utils import _age_depuis_naissance, tranche_age_depuis_naissance
    from inscriptions.views import _construire_et_valider_telephone
    from registration.utils import (
        abonnements_avec_prix_effectif, champs_structurels_actifs, evaluer_champs_actifs,
        extraire_champs_depuis_post, groupes_avec_place_disponible, groupes_compatibles_avec_age,
        inscrire_eleve, nb_slots_repondu, reponses_pour_filtrage_depuis_resultats,
        statut_compatibilite_groupe, abonnements_disponibles,
    )

    round_form = request.POST.get('round_form', 'identite') if request.method == 'POST' else 'identite'

    def _rendre_round_identite(donnees_prefill=None):
        donnees_prefill = donnees_prefill or {}
        resultats = evaluer_champs_actifs(donnees_prefill)
        configs = champs_structurels_actifs('identite')
        for c in configs:
            c.valeur_actuelle = donnees_prefill.get(c.champ_cle, '')
        return render(request, 'dashboard/admin_eleve_ajouter_manuel.html', {
            'round_form': 'identite',
            'champs_affiches': _champs_pour_template(resultats, donnees_prefill),
            'configs_structurels': configs,
            'valeurs_form': donnees_prefill,
            'base_template': _base_template_admin_ou_mshrif(request),
            **_contexte_base_mshrif(request),
        })

    if request.method == 'POST' and request.POST.get('retour') == '1':
        # Bouton "تعديل المعلومات الشخصية" du round 2 -- repart du round 1
        # pre-rempli avec ce qui etait deja dans les champs caches du round 2
        # (jamais une validation, juste un retour en arriere, AUCUNE creation).
        return _rendre_round_identite({**_champs_identite_bruts(request), **extraire_champs_depuis_post(request.POST)})

    if round_form == 'identite':
        if request.method != 'POST':
            return _rendre_round_identite()

        # telephone (registration.models.ConfigurationChampStructurel) :
        # non-obligatoire configurable, même logique que wizard_identite —
        # skip la validation dédiée si vide ET non obligatoire, jamais
        # d'erreur bloquante dans ce cas.
        telephone_config = {c.champ_cle: c for c in champs_structurels_actifs('identite')}.get('telephone')
        telephone_brut = request.POST.get('telephone', '').strip()
        if telephone_config is not None and not telephone_config.obligatoire and not telephone_brut:
            telephone, erreur_tel = '', None
        else:
            telephone, erreur_tel = _construire_et_valider_telephone(request)
        if erreur_tel:
            messages.error(request, erreur_tel)
            return _rendre_round_identite({**_champs_identite_bruts(request), **extraire_champs_depuis_post(request.POST)})

        donnees = {
            **_champs_identite_bruts(request), 'telephone': telephone,
            **extraire_champs_depuis_post(request.POST),
        }
        resultats = evaluer_champs_actifs(donnees)
        reponses_pour_filtrage = reponses_pour_filtrage_depuis_resultats(resultats)
        critere_type_offre = next((c for c in reponses_pour_filtrage if c.backend == 'champ_groupe'), None)
        type_offre_valeur = reponses_pour_filtrage.get(critere_type_offre) if critere_type_offre else None

        date_naissance = None
        try:
            date_naissance = datetime.date.fromisoformat(donnees.get('date_naissance', ''))
        except (ValueError, TypeError):
            pass

        groupes, abonnements, type_age = None, [], None
        if date_naissance is not None:
            type_age = tranche_age_depuis_naissance(date_naissance)
            # abonnements_avec_prix_effectif (Étape 9, GrillePrixAbonnement,
            # 2026-08-21) : pose `.prix_affiche` sur chaque TypeAbonnement à
            # partir du nb_slots déjà répondu dans ce même round — même
            # fonction que wizard_abonnement, jamais 2 affichages qui
            # pourraient diverger pour la même combinaison.
            abonnements = abonnements_avec_prix_effectif(
                abonnements_disponibles(type_offre_valeur, type_age), nb_slots_repondu(donnees)
            )
            if type_offre_valeur == 'groupe':
                # groupes_avec_place_disponible (même correctif que registration.
                # views.wizard_groupe, 2026-08-21) : un groupe complet ne doit
                # jamais apparaître dans le <select> proposé au Directeur/مشرف.
                # exclure_caches_wizard_public=False (chantier du 2026-08-23) :
                # cette vue reste la porte manuelle Directeur/مشرف — un groupe
                # masqué du formulaire public doit rester sélectionnable ici.
                groupes = groupes_avec_place_disponible(
                    groupes_compatibles_avec_age(
                        reponses_pour_filtrage, date_naissance, donnees.get('sexe', ''),
                        exclure_caches_wizard_public=False,
                    )
                ).prefetch_related('valeurs_criteres__critere', 'valeurs_criteres__option')

        return render(request, 'dashboard/admin_eleve_ajouter_manuel.html', {
            'round_form': 'confirmation',
            'champs_affiches': _champs_pour_template(resultats, donnees),
            'valeurs_form': {**donnees, 'indicatif_pays': request.POST.get('indicatif_pays', ''),
                              'indicatif_pays_autre': request.POST.get('indicatif_pays_autre', ''),
                              'telephone_brut': request.POST.get('telephone', ''),
                              'telephone_confirmation': request.POST.get('telephone_confirmation', '')},
            'type_offre_valeur': type_offre_valeur,
            'groupes': groupes,
            'abonnements': abonnements,
            'age': _age_depuis_naissance(date_naissance) if date_naissance else None,
            'base_template': _base_template_admin_ou_mshrif(request),
            **_contexte_base_mshrif(request),
        })

    # ---- round_form == 'confirmation' ----
    telephone, erreur_tel = _construire_et_valider_telephone(request)
    if erreur_tel:
        messages.error(request, erreur_tel)
        return _rendre_round_identite({**_champs_identite_bruts(request), **extraire_champs_depuis_post(request.POST)})

    donnees = {
        **_champs_identite_bruts(request), 'telephone': telephone,
        **extraire_champs_depuis_post(request.POST),
        'groupe_id': request.POST.get('groupe_id', ''),
        'abonnement_code': request.POST.get('abonnement_code', ''),
        'continuer_sans_groupe': request.POST.get('continuer_sans_groupe', ''),
    }
    resultats = evaluer_champs_actifs(donnees)
    reponses_pour_filtrage = reponses_pour_filtrage_depuis_resultats(resultats)
    critere_type_offre = next((c for c in reponses_pour_filtrage if c.backend == 'champ_groupe'), None)
    type_offre_valeur = reponses_pour_filtrage.get(critere_type_offre) if critere_type_offre else None

    confirme = request.POST.get('confirme_override') == '1'
    groupe_id = donnees.get('groupe_id')

    date_naissance = None
    try:
        date_naissance = datetime.date.fromisoformat(donnees.get('date_naissance', ''))
    except (ValueError, TypeError):
        pass

    def _rendre_round_confirmation(avertissement=False):
        type_age = tranche_age_depuis_naissance(date_naissance) if date_naissance else None
        abonnements = (
            abonnements_avec_prix_effectif(
                abonnements_disponibles(type_offre_valeur, type_age), nb_slots_repondu(donnees)
            )
            if type_age else []
        )
        groupes = None
        if date_naissance is not None and type_offre_valeur == 'groupe':
            # exclure_caches_wizard_public=False : même raison que round 1
            # ci-dessus — porte admin, jamais affectée par ce masquage.
            groupes = groupes_avec_place_disponible(
                groupes_compatibles_avec_age(
                    reponses_pour_filtrage, date_naissance, donnees.get('sexe', ''),
                    exclure_caches_wizard_public=False,
                )
            ).prefetch_related('valeurs_criteres__critere', 'valeurs_criteres__option')
        return render(request, 'dashboard/admin_eleve_ajouter_manuel.html', {
            'round_form': 'confirmation',
            'champs_affiches': _champs_pour_template(resultats, donnees),
            'valeurs_form': {**donnees, 'indicatif_pays': request.POST.get('indicatif_pays', ''),
                              'indicatif_pays_autre': request.POST.get('indicatif_pays_autre', ''),
                              'telephone_brut': request.POST.get('telephone', ''),
                              'telephone_confirmation': request.POST.get('telephone_confirmation', '')},
            'type_offre_valeur': type_offre_valeur,
            'groupes': groupes,
            'abonnements': abonnements,
            'age': _age_depuis_naissance(date_naissance) if date_naissance else None,
            'groupe_id_selectionne': groupe_id,
            'abonnement_selectionne': donnees.get('abonnement_code'),
            'avertissement': avertissement,
            'base_template': _base_template_admin_ou_mshrif(request),
            **_contexte_base_mshrif(request),
        })

    if type_offre_valeur == 'groupe' and groupe_id and not confirme and date_naissance is not None:
        statut_compat = statut_compatibilite_groupe(groupe_id, reponses_pour_filtrage, date_naissance, donnees.get('sexe', ''))
        if statut_compat == 'contournable':
            messages.warning(
                request,
                'المجموعة المختارة لا تتوافق تماماً مع أحد المعايير غير الإلزامية — '
                'يمكنك تأكيد التسجيل رغم ذلك، أو اختيار مجموعة أخرى.',
            )
            return _rendre_round_confirmation(avertissement=True)

    inscription, erreurs = inscrire_eleve(donnees, cree_par=request.user, confirme_override=confirme)
    if erreurs:
        for erreur in erreurs:
            messages.error(request, erreur)
        return _rendre_round_confirmation(avertissement=False)

    messages.success(
        request,
        f'تم إنشاء طلب تسجيل "{inscription.nom}" بنجاح. راجع الطلب ثم اضغط "قبول الطلب" لإتمام إنشاء الحساب.',
    )
    return redirect('admin_inscription_eleve_detail', inscription_id=inscription.id)


# ==================== Chantier du 2026-08-27 : ajout manuel d'un prof ====================

@role_required('admin', 'mshrif')
def admin_prof_ajouter_manuel(request):
    """Ajout manuel d'une candidature InscriptionProf par مدير/مشرف (pour un
    prof recruté par téléphone/en présentiel, jamais passé par le formulaire
    public inscriptions.views.inscription_prof) — même besoin que
    admin_eleve_ajouter_manuel, mais InscriptionProf n'est PAS branché sur le
    moteur Critere/ChampInscription configurable (schéma fixe, contrairement à
    InscriptionEleve) : un formulaire dédié, à une seule soumission (pas de
    rounds), qui reprend les MÊMES champs que inscription_prof — jamais une
    2e liste de champs qui pourrait diverger de la candidature publique.

    Statut initial selon le rôle du créateur (décision explicite, Chantier du
    2026-08-27) :
    - مدير : statut créé directement à 'validee_directeur' (saute
      'en_attente' — le مدير l'a lui-même vérifié en l'ajoutant). Apparaît
      dans mshrif_inscriptions_profs comme toute candidature classique, en
      attente de validation finale du مشرف — AUCUN compte créé ici.
    - مشرف : statut créé directement à 'valide'. Le compte User+Prof est créé
      IMMÉDIATEMENT (_creer_compte_prof, même fonction que
      mshrif_valider_prof_final) — aucune attente : le مشرف est la DERNIÈRE
      autorité du workflow à 2 étapes, rien au-dessus de lui à faire
      attendre.

    Contrairement au formulaire public, l'audio (audio_enregistrement) et la
    matrice de disponibilités restent optionnels — un ajout manuel se fait
    souvent avec des infos incomplètes au premier passage, complétables
    ensuite depuis la fiche prof une fois le compte créé.

    Chantier du 2026-08-27 ("tout optionnel sauf le strict indispensable") :
    seuls nom/prenom/email/telephone restent obligatoires ici — ville, date de
    naissance, job actuel, niveau de mémorisation, parcours scolaire/
    enseignant, infos bancaires... sont tous devenus optionnels (voir
    InscriptionProf.date_naissance, rendue nullable pour l'occasion — les
    autres champs relâchés étaient déjà de simples CharField/TextField non
    null, aucune migration nécessaire pour eux). Le formulaire PUBLIC
    (inscriptions.views.inscription_prof) N'EST PAS concerné par ce
    relâchement — il continue d'exiger tous ces champs comme avant, seul cet
    ajout manuel devient plus permissif."""
    from django.utils import timezone
    from courses.utils import JOURS_SEMAINE_DISPO, generer_heures_grille
    from inscriptions.models import InscriptionProf
    from inscriptions.views import MESSAGE_EMAIL_DEJA_UTILISE, _construire_et_valider_telephone, _email_deja_utilise

    contexte_grille = {'jours': JOURS_SEMAINE_DISPO, 'heures': generer_heures_grille()}

    if request.method == 'POST':
        nom = request.POST.get('nom', '').strip()
        prenom = request.POST.get('prenom', '').strip()
        email = request.POST.get('email', '').strip()
        compte_bancaire = request.POST.get('compte_bancaire', '').strip()
        rib = request.POST.get('rib', '').strip()
        agence_bancaire = request.POST.get('agence_bancaire', '').strip()
        job_actuel = request.POST.get('job_actuel', '').strip()
        ville = request.POST.get('ville', '').strip()
        statut_familial = request.POST.get('statut_familial', '').strip()
        niveau_memorisation = request.POST.get('niveau_memorisation', '').strip()
        parcours_scolaire = request.POST.get('parcours_scolaire', '').strip()
        parcours_enseignant = request.POST.get('parcours_enseignant', '').strip()

        # Chantier du 2026-08-27 ("tout optionnel sauf le strict
        # indispensable") : seule une date de naissance LAISSÉE VIDE est
        # acceptée silencieusement (None, voir InscriptionProf.date_naissance,
        # rendue nullable) — une date SAISIE mais invalide reste, elle, une
        # vraie erreur (jamais une valeur corrompue enregistrée à la place
        # d'un message clair).
        date_naissance_brute = request.POST.get('date_naissance', '').strip()
        date_naissance = None
        date_naissance_invalide = False
        if date_naissance_brute:
            try:
                date_naissance = datetime.date.fromisoformat(date_naissance_brute)
            except ValueError:
                date_naissance_invalide = True

        # Seuls nom/prenom/email/telephone (validé plus bas via
        # _construire_et_valider_telephone, déjà inconditionnellement
        # obligatoire) restent indispensables — tous les autres champs de ce
        # formulaire sont désormais optionnels (un ajout manuel se fait
        # souvent avec un dossier incomplet, complétable ensuite depuis la
        # fiche prof une fois le compte créé, même logique déjà appliquée à
        # l'audio/aux disponibilités avant ce chantier, voir docstring de la vue).
        erreurs = []
        if not nom:
            erreurs.append('الاسم إلزامي.')
        if not prenom:
            erreurs.append('اللقب إلزامي.')
        if date_naissance_invalide:
            erreurs.append('تاريخ الميلاد غير صالح.')
        if not email:
            erreurs.append('البريد الإلكتروني إلزامي.')
        elif _email_deja_utilise(email):
            erreurs.append(MESSAGE_EMAIL_DEJA_UTILISE)

        telephone_complet = ''
        if not erreurs:
            telephone_complet, erreur_tel = _construire_et_valider_telephone(request)
            if erreur_tel:
                erreurs.append(erreur_tel)

        if erreurs:
            for erreur in erreurs:
                messages.error(request, erreur)
            return render(request, 'dashboard/admin_prof_ajouter_manuel.html', {
                'valeurs_form': request.POST,
                'dispo_selectionnees': set(request.POST.getlist('dispo')),
                **contexte_grille,
                'base_template': _base_template_admin_ou_mshrif(request),
                **_contexte_base_mshrif(request),
            })

        # Voir docstring ci-dessus pour le détail des différences avec une candidature publique.
        statut_initial = 'valide' if request.user.role == 'mshrif' else 'validee_directeur'
        # Fonctionnalité 3 (2026-08-27) : ce dossier entre DIRECTEMENT en
        # 'validee_directeur' à la création (créateur مدير) — voir
        # InscriptionProf.date_validee_directeur.__doc__, déclenche la
        # notification مشرف (dashboard.notifications.notifications_direction)
        # comme le flux classique admin_valider_prof. Reste None pour le cas
        # مشرف (statut_initial='valide', saute cette étape entièrement).
        date_validee_directeur = timezone.now() if statut_initial == 'validee_directeur' else None

        inscription = InscriptionProf.objects.create(
            nom=nom,
            prenom=prenom,
            date_naissance=date_naissance,
            telephone=telephone_complet,
            ville=ville,
            statut_familial=statut_familial,
            job_actuel=job_actuel,
            certifications=request.POST.get('certifications', '').strip(),
            niveau_memorisation=niveau_memorisation,
            parcours_scolaire=parcours_scolaire,
            parcours_enseignant=parcours_enseignant,
            gestion_eleve_faible=request.POST.get('gestion_eleve_faible', '').strip(),
            gestion_eleve_absent=request.POST.get('gestion_eleve_absent', '').strip(),
            email=email,
            langues=request.POST.getlist('langues'),
            outils_maitrises=request.POST.getlist('outils'),
            type_eleve_preference=request.POST.getlist('type_eleve'),
            contrainte_genre=request.POST.getlist('contrainte_genre'),
            compte_bancaire=compte_bancaire,
            rib=rib,
            agence_bancaire=agence_bancaire,
            audio_enregistrement=request.FILES.get('audio_enregistrement'),
            disponibilites=request.POST.getlist('dispo'),
            statut=statut_initial,
            date_validee_directeur=date_validee_directeur,
        )

        if statut_initial == 'valide':
            prof, password_temp = _creer_compte_prof(inscription)
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

        messages.success(
            request,
            f'تم إنشاء طلب الأستاذ "{inscription.nom} {inscription.prenom}" بنجاح — '
            f'بانتظار التصديق النهائي من المشرف قبل إنشاء الحساب.',
        )
        return redirect('admin_inscription_prof_detail', inscription_id=inscription.id)

    return render(request, 'dashboard/admin_prof_ajouter_manuel.html', {
        'valeurs_form': {},
        'dispo_selectionnees': set(),
        **contexte_grille,
        'base_template': _base_template_admin_ou_mshrif(request),
        **_contexte_base_mshrif(request),
    })


# ==================== Chantier du 2026-08-27 : nubdha (présentation publique) du prof ====================

@role_required('admin', 'mshrif')
def admin_prof_presentation_modifier(request, prof_id):
    """Modification du paragraphe Prof.presentation_publique (affiché dans les
    cartes halaka du wizard d'inscription, voir templates/inscriptions/
    wizard_groupe.html) — généré automatiquement une seule fois à la création
    du compte (accounts.services.generer_presentation_publique, appelée par
    _creer_compte_prof), jamais réécrit automatiquement ensuite : مدير ET
    مشرف peuvent l'affiner ici à tout moment, même patron que
    admin_prof_infos_complementaires_modifier (mais ouvert aux 2 rôles,
    décision explicite de ce chantier — contrairement à ce précédent, resté
    مدير seul)."""
    from accounts.models import Prof

    prof = get_object_or_404(Prof, id=prof_id)

    if request.method == 'POST':
        prof.presentation_publique = request.POST.get('presentation_publique', '').strip()
        prof.save(update_fields=['presentation_publique'])
        messages.success(request, 'تم تحديث نبذة التقديم بنجاح.')
        return redirect('admin_prof_detail', prof_id=prof.id)

    context = {
        'prof': prof,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_prof_presentation_modifier.html', context)


# ==================== Abonnés Telegram (notifications مدير/مشرف) ====================
# Chantier : remplace l'ancien chat_id unique codé en dur (settings.TELEGRAM_CHAT_ID)
# par un vrai système d'abonnement (telegram_bot.AbonneTelegram) — n'importe
# quel مدير/مشرف envoie /start au bot puis est validé ici. Les 2 rôles peuvent
# valider/rejeter/désactiver un abonné.

@role_required('admin', 'mshrif')
def admin_telegram_abonnes(request):
    from telegram_bot.models import AbonneTelegram

    context = {
        'en_attente': AbonneTelegram.objects.filter(en_attente_validation=True),
        'actifs': AbonneTelegram.objects.filter(est_actif=True),
        'inactifs': AbonneTelegram.objects.filter(est_actif=False, en_attente_validation=False),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_telegram_abonnes.html', context)


@role_required('admin', 'mshrif')
def admin_telegram_abonne_valider(request, abonne_id):
    from telegram_bot.models import AbonneTelegram
    from core.utils import envoyer_message_telegram_direct

    abonne = get_object_or_404(AbonneTelegram, id=abonne_id, en_attente_validation=True)
    abonne.est_actif = True
    abonne.en_attente_validation = False
    abonne.valide_par = request.user
    abonne.date_desabonnement = None
    abonne.save(update_fields=['est_actif', 'en_attente_validation', 'valide_par', 'date_desabonnement'])
    # Best-effort : informe l'abonné qu'il commence à recevoir les notifications
    # — jamais bloquant, même principe que tout envoi Telegram du projet.
    envoyer_message_telegram_direct(
        abonne.chat_id,
        '✅ تمت الموافقة على اشتراكك. ستبدأ في استقبال إشعارات منصة زدني علماً الآن.'
    )
    messages.success(request, f'تم قبول اشتراك {abonne} — سيبدأ في استقبال الإشعارات.')
    return redirect('admin_telegram_abonnes')


@role_required('admin', 'mshrif')
def admin_telegram_abonne_rejeter(request, abonne_id):
    from telegram_bot.models import AbonneTelegram

    abonne = get_object_or_404(AbonneTelegram, id=abonne_id, en_attente_validation=True)
    abonne.est_actif = False
    abonne.en_attente_validation = False
    abonne.save(update_fields=['est_actif', 'en_attente_validation'])
    messages.info(request, f'تم رفض اشتراك {abonne}.')
    return redirect('admin_telegram_abonnes')


@role_required('admin', 'mshrif')
def admin_telegram_abonne_desactiver(request, abonne_id):
    """Révocation manuelle d'un abonné déjà actif (menace, départ, erreur de
    validation...) — un /start ultérieur de sa part repassera de toute façon
    en file d'attente (voir telegram_bot.models.AbonneTelegram), donc aucune
    réactivation possible sans nouvelle validation ici."""
    from django.utils import timezone
    from telegram_bot.models import AbonneTelegram

    abonne = get_object_or_404(AbonneTelegram, id=abonne_id, est_actif=True)
    abonne.est_actif = False
    abonne.date_desabonnement = timezone.now()
    abonne.save(update_fields=['est_actif', 'date_desabonnement'])
    messages.info(request, f'تم إلغاء تفعيل اشتراك {abonne}.')
    return redirect('admin_telegram_abonnes')
