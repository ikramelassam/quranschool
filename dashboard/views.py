import datetime
import logging
import secrets

from django.shortcuts import render, redirect, get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from accounts.decorators import role_required
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
    secret de sécurité plutôt qu'à un simple tirage aléatoire."""
    return ''.join(secrets.choice(ALPHABET_MOT_DE_PASSE_TEMPORAIRE) for _ in range(longueur))


def envoyer_email_bienvenue(request, email, password_temp, prenom_nom):
    """Envoie le mot de passe temporaire + le lien de connexion au nouvel utilisateur (élève ou prof).
    Retourne True si l'email est parti, False sinon — une panne SMTP (identifiants, réseau...) ne doit
    jamais empêcher la création du compte, qui a déjà eu lieu au moment de l'appel."""
    from django.urls import reverse

    lien_connexion = request.build_absolute_uri(reverse('login'))
    try:
        send_mail(
            subject='مرحباً بك في منصة زدني علماً - معلومات الدخول',
            message=(
                f'مرحباً {prenom_nom},\n\n'
                f'تم قبول ملفك. يمكنك الآن تسجيل الدخول باستخدام:\n'
                f'البريد الإلكتروني: {email}\n'
                f'كلمة المرور المؤقتة: {password_temp}\n\n'
                f'رابط تسجيل الدخول: {lien_connexion}\n\n'
                f'ننصحك بتغيير كلمة المرور بعد أول تسجيل دخول.'
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


def _invalider_sessions_utilisateur(utilisateur, request=None):
    """Supprime toutes les sessions actives de cet utilisateur (déconnexion forcée
    sur tous les appareils), suite à un changement d'email par exemple.
    Si la requête courante appartient à ce même utilisateur (auto-modification),
    on fait tourner la clé de SA session courante d'abord (cycle_key: opération
    native Django qui recrée la ligne sous une nouvelle clé et supprime l'ancienne
    proprement) et on l'exclut de la suppression en masse, pour ne pas le
    déconnecter lui-même en plein milieu de son action."""
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    session_courante_a_garder = None
    if request is not None and request.user.is_authenticated and request.user.pk == utilisateur.pk:
        request.session.cycle_key()
        session_courante_a_garder = request.session.session_key

    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.session_key == session_courante_a_garder:
            continue
        data = session.get_decoded()
        if str(data.get('_auth_user_id')) == str(utilisateur.pk):
            session.delete()


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
    (voir bug connu #5 du CLAUDE.md: validation silencieuse sans création de compte)."""
    from accounts.models import Eleve, Prof
    from django.contrib.auth import get_user_model
    User = get_user_model()

    user_existant = User.objects.filter(email=email).first()
    if not user_existant:
        return {'conflit': False, 'user': None, 'orphelin': False}

    a_un_profil = Eleve.objects.filter(user=user_existant).exists() or Prof.objects.filter(user=user_existant).exists()
    return {'conflit': True, 'user': user_existant, 'orphelin': not a_un_profil}


@role_required('prof')
def dashboard_prof(request):
    from accounts.models import Prof
    from courses.models import Groupe, Seance
    from django.utils import timezone

    try:
        prof = Prof.objects.get(user=request.user)
    except Prof.DoesNotExist:
        return redirect('login')

    groupes = Groupe.objects.filter(prof=prof)
    seances = Seance.objects.filter(
        groupe__prof=prof
    ).order_by('-date')[:5]

    # Encart dédié "prochaine séance" (Tâche 10/écart 1 du 2026-07-25) — même
    # intention que dashboard_eleve.prochaine_seance : identifiable d'un coup
    # d'œil, plutôt que noyée dans "آخر الحصص" qui mélange passé/futur trié
    # par date décroissante.
    aujourdhui = timezone.localdate()
    prochaine_seance = Seance.objects.filter(
        groupe__prof=prof, date__gte=aujourdhui
    ).exclude(statut='terminee').select_related('groupe').order_by('date', 'heure').first()

    context = {
        'prof': prof,
        'groupes': groupes,
        'seances': seances,
        'prochaine_seance': prochaine_seance,
        'aujourdhui': aujourdhui,
        'total_eleves': sum(g.eleves.count() for g in groupes),
        'total_groupes': groupes.count(),
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


@role_required('prof')
def prof_seance_detail(request, seance_id):
    from accounts.models import Prof
    from courses.models import Seance, Presence
    from courses.quran_data import SOURATES

    prof = get_object_or_404(Prof, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof=prof)
    # Un élève suspendu/archivé ne doit plus apparaître dans les feuilles de
    # présence à venir (voir Tâche 3 du 2026-07-25) — son historique passé
    # n'est pas affecté, seule cette liste "à remplir maintenant" l'exclut.
    eleves = seance.groupe.eleves.filter(statut='actif')

    # Django templates ne peuvent pas faire presences[eleve.id] (lookup par variable).
    # On construit donc directement la liste (élève, présence) dans la vue.
    presences_par_eleve = {p.eleve_id: p for p in Presence.objects.filter(seance=seance)}
    eleves_presences = []
    premiere_non_remplie_trouvee = False
    for eleve in eleves:
        presence = presences_par_eleve.get(eleve.id)
        # Seule la première carte non encore remplie s'ouvre automatiquement —
        # les autres restent repliées pour garder le formulaire rapide sur mobile.
        ouvrir_par_defaut = not presence and not premiere_non_remplie_trouvee
        if not presence:
            premiere_non_remplie_trouvee = True
        eleves_presences.append({
            'eleve': eleve,
            'presence': presence,
            'ouvrir_par_defaut': ouvrir_par_defaut,
        })

    return render(request, 'dashboard/prof_seance_detail.html', {
        'prof': prof,
        'seance': seance,
        'eleves_presences': eleves_presences,
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

            # 4 critères numériques /20 (Tâche 9 du 2026-07-25) — remplacent
            # l'ancienne échelle qualitative pour toute nouvelle évaluation
            # (note_memorisation/note_revision ne sont plus jamais réécrits
            # depuis cette vue, voir Presence.note_memorisation).
            criteres_bruts = {
                'note_hifz': request.POST.get(f'note_hifz_{eleve.id}', ''),
                'note_muraja3a': request.POST.get(f'note_muraja3a_{eleve.id}', ''),
                'note_tilawa': request.POST.get(f'note_tilawa_{eleve.id}', ''),
                'note_mouwazaba': request.POST.get(f'note_mouwazaba_{eleve.id}', ''),
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

            # Les 4 critères /20 et les 2 consignes ne sont obligatoires que pour
            # un élève marqué présent — rien à noter/consigner pour une absence
            # (voir Tâche 9 du 2026-07-25).
            notes_validees = {}
            if statut == 'present':
                for champ, valeur_brute in criteres_bruts.items():
                    nom_critere = NOMS_CRITERES_NOTATION[champ]
                    if not valeur_brute:
                        erreurs.append(f'{eleve.user.get_full_name()}: يجب إدخال علامة {nom_critere}.')
                        ligne_invalide = True
                        continue
                    try:
                        valeur = int(valeur_brute)
                    except ValueError:
                        erreurs.append(f'{eleve.user.get_full_name()}: علامة {nom_critere} غير صحيحة.')
                        ligne_invalide = True
                        continue
                    if not (1 <= valeur <= 20):
                        erreurs.append(f'{eleve.user.get_full_name()}: علامة {nom_critere} يجب أن تكون بين 1 و20.')
                        ligne_invalide = True
                        continue
                    notes_validees[champ] = valeur
                if not consigne_memorisation.strip():
                    erreurs.append(f'{eleve.user.get_full_name()}: يجب تحديد "المطلوب حفظه".')
                    ligne_invalide = True
                if not consigne_revision.strip():
                    erreurs.append(f'{eleve.user.get_full_name()}: يجب تحديد "المطلوب مراجعته".')
                    ligne_invalide = True
            else:
                notes_validees = {champ: None for champ in criteres_bruts}
                consigne_memorisation = ''
                consigne_revision = ''

            if ligne_invalide:
                continue

            Presence.objects.update_or_create(
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
                    **notes_validees,
                }
            )

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


# 4 critères numériques /20 de Presence (Tâche 9 du 2026-07-25) — noms arabes
# affichés dans les messages d'erreur de prof_presence_sauvegarder.
NOMS_CRITERES_NOTATION = {
    'note_hifz': 'الحفظ',
    'note_muraja3a': 'المراجعة',
    'note_tilawa': 'التلاوة',
    'note_mouwazaba': 'المواظبة والسلوك',
}


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
    from django.contrib.auth import get_user_model
    User = get_user_model()
    prof = get_object_or_404(Prof, user=request.user)
    return render(request, 'dashboard/prof_profil.html', {
        'prof': prof,
        'superviseurs': prof.superviseurs.select_related('user').all(),
        'admins': User.objects.filter(role='admin'),
        'modifier_telephone': request.GET.get('modifier_telephone') == '1',
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
    """Page d'atterrissage حقيبة الأستاذ — regroupe ميثاق التدريس (prof_charte, déjà
    existant) et البرنامج العام (programme_general_detail) sous une seule entrée
    sidebar, même sidebar restant plate (aucune base_*.html du projet n'a de
    sous-menu) : un lien -> une page de cartes, comme les quick-links du مشرف."""
    return render(request, 'dashboard/prof_hakiba.html')


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

    eleves = Eleve.objects.filter(groupes__prof=prof).distinct().select_related('user').order_by('user__first_name')
    bilans = {b.eleve_id: b for b in BilanMensuel.objects.filter(prof=prof, mois_reference=mois_reference)}

    lignes = [{'eleve': eleve, 'bilan': bilans.get(eleve.id)} for eleve in eleves]

    return render(request, 'dashboard/prof_bilans_mensuels.html', {
        'lignes': lignes,
        'mois': mois,
        'mois_reference': mois_reference,
    })


@role_required('prof', 'admin', 'superviseur', 'mshrif')
def bilan_mensuel_detail(request, eleve_id, mois):
    """Page de saisie/consultation d'un bilan mensuel — unique pour les 4 rôles :
    le prof le crée/modifie (tant que modifiable_par_prof), les 3 autres rôles le
    consultent en lecture seule (le مؤطر scopé à ses profs assignés, comme pour le
    classement mensuel)."""
    from accounts.models import Eleve, Prof, Superviseur
    from courses.models import BilanMensuel
    from courses.utils import generer_brouillon_bilan_mensuel
    from django.http import HttpResponseForbidden

    eleve = get_object_or_404(Eleve, id=eleve_id)
    annee, _, num_mois = mois.partition('-')
    mois_reference = datetime.date(int(annee), int(num_mois), 1)

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
        if request.user.role == 'superviseur':
            superviseur = get_object_or_404(Superviseur, user=request.user)
            if prof not in superviseur.profs_assignes.all():
                return HttpResponseForbidden('هذا المعلم غير مسند إليك.')

    lecture_seule = request.user.role != 'prof' or not bilan.modifiable_par_prof

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
    }
    COULEUR_PAR_ROLE = {
        'prof': 'var(--color-role-prof)',
        'admin': 'var(--color-role-admin)',
        'superviseur': 'var(--color-role-superviseur)',
        'mshrif': 'var(--color-role-mshrif)',
    }
    context = {
        'eleve': eleve,
        'prof': prof,
        'bilan': bilan,
        'mois': mois,
        'mois_reference': mois_reference,
        'lecture_seule': lecture_seule,
        'base_template': BASE_TEMPLATE_PAR_ROLE[request.user.role],
        'couleur_role': COULEUR_PAR_ROLE[request.user.role],
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/bilan_mensuel_detail.html', context)


@role_required('admin', 'superviseur', 'mshrif')
def bilans_mensuels(request):
    """تقييم الطلاب — لائحة بيانات شهرية جاهزة (onglet "شهري", contenu inchangé
    depuis toujours) + onglet "حسب الحصة" (Tâche 21 du 2026-07-26) qui réutilise
    calculer_progression_eleve (même mécanisme que admin_eleve_detail.html,
    voir _historique_evaluations_eleve.html) pour l'élève actuellement filtré.
    Lecture seule pour مدير/مؤطر/مشرف, مؤطر scopé à ses profs assignés (même
    filtre que classement_mensuel_profs)."""
    from accounts.models import Prof, Eleve, Superviseur
    from courses.models import BilanMensuel, Presence
    from courses.utils import calculer_progression_eleve

    mois = request.GET.get('mois', '')
    prof_id = request.GET.get('prof', '')
    eleve_id = request.GET.get('eleve', '')
    onglet = request.GET.get('onglet', 'mensuel')

    bilans = BilanMensuel.objects.select_related('eleve__user', 'prof__user').order_by(
        '-mois_reference', 'eleve__user__first_name'
    )

    if request.user.role == 'superviseur':
        superviseur = get_object_or_404(Superviseur, user=request.user)
        bilans = bilans.filter(prof__in=superviseur.profs_assignes.all())

    if mois:
        annee, _, num_mois = mois.partition('-')
        bilans = bilans.filter(mois_reference__year=int(annee), mois_reference__month=int(num_mois))
    if prof_id:
        bilans = bilans.filter(prof_id=prof_id)
    if eleve_id:
        bilans = bilans.filter(eleve_id=eleve_id)

    bilans_page = paginer(request, bilans, 20)

    # Moyenne des 4 critères /20 du mois pour chaque bilan affiché — même
    # filtre (élève, prof, année/mois de la séance) que
    # generer_brouillon_bilan_mensuel, pas une nouvelle règle de calcul.
    def moyenne(valeurs):
        valeurs = [v for v in valeurs if v is not None]
        return round(sum(valeurs) / len(valeurs), 1) if valeurs else None

    for bilan in bilans_page:
        presences_mois = Presence.objects.filter(
            eleve=bilan.eleve, seance__groupe__prof=bilan.prof,
            seance__date__year=bilan.mois_reference.year, seance__date__month=bilan.mois_reference.month,
        )
        bilan.moyenne_hifz = moyenne([p.note_hifz for p in presences_mois])
        bilan.moyenne_muraja3a = moyenne([p.note_muraja3a for p in presences_mois])
        bilan.moyenne_tilawa = moyenne([p.note_tilawa for p in presences_mois])
        bilan.moyenne_mouwazaba = moyenne([p.note_mouwazaba for p in presences_mois])

    eleve_seance = None
    progression_seance = None
    if eleve_id:
        eleve_seance = Eleve.objects.filter(id=eleve_id).select_related('user').first()
        if eleve_seance:
            progression_seance = calculer_progression_eleve(eleve_seance)

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
        'bilans': bilans_page,
        'filtres': {'mois': mois, 'prof': prof_id, 'eleve': eleve_id},
        'onglet': onglet,
        'eleve_seance': eleve_seance,
        'progression_seance': progression_seance,
        'profs': Prof.objects.select_related('user').order_by('user__first_name'),
        'eleves': Eleve.objects.select_related('user').order_by('user__first_name'),
        'base_template': BASE_TEMPLATE_PAR_ROLE[request.user.role],
        'couleur_role': COULEUR_PAR_ROLE[request.user.role],
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/bilans_mensuels.html', context)


@role_required('admin', 'mshrif')
def dashboard_admin(request):
    from inscriptions.models import InscriptionEleve, InscriptionProf
    from accounts.models import Eleve, Prof
    from courses.models import Groupe

    dernieres_eleves = InscriptionEleve.objects.filter(
        statut='en_attente'
    ).order_by('-date_soumission')[:3]

    dernieres_profs = InscriptionProf.objects.filter(
        statut='en_attente'
    ).order_by('-date_soumission')[:3]

    context = {
        'total_eleves': Eleve.objects.count(),
        'total_profs': Prof.objects.count(),
        'total_groupes': Groupe.objects.count(),
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



@role_required('admin')
def admin_valider_eleve(request, inscription_id):
    from inscriptions.models import InscriptionEleve
    from accounts.models import Eleve
    from django.contrib.auth import get_user_model

    User = get_user_model()
    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)

    conflit = _verifier_conflit_email(inscription.email)
    if conflit['conflit']:
        if conflit['orphelin']:
            messages.error(
                request,
                f'تعذر القبول: يوجد حساب بهذا البريد الإلكتروني ({inscription.email}) '
                f'بدون ملف شخصي مرتبط (على الأرجح من اختبار سابق). '
                f'احذف الحساب اليتيم أولاً ثم أعد المحاولة.'
            )
        else:
            messages.error(
                request,
                f'تعذر القبول: يوجد حساب نشط بهذا البريد الإلكتروني ({inscription.email}) '
                f'مرتبط بملف شخصي آخر — التعارض يجب حله يدوياً قبل المتابعة.'
            )
        return redirect('admin_inscription_eleve_detail', inscription_id=inscription.id)

    password_temp = generer_mot_de_passe_temporaire()

    # Tout ou rien: si une étape échoue (ex: matrice de disponibilités malformée),
    # aucun compte à moitié créé ne doit rester en base — voir l'incident où une
    # exception après la création du compte (autrefois: échec d'envoi d'email non
    # rattrapé) laissait un User+Eleve actifs mais l'inscription bloquée "en attente"
    # pour toujours. L'envoi d'email reste hors transaction: il ne doit jamais faire
    # échouer ni retenir la transaction (appel réseau lent), et ne peut de toute façon
    # plus lever d'exception (voir envoyer_email_bienvenue).
    with transaction.atomic():
        # Crée le User — telephone/date_naissance copiés depuis l'inscription
        # (seule source qui les contient) pour que user.telephone/date_naissance
        # ne restent plus jamais vides sur les fiches admin/superviseur qui les
        # affichent directement (voir audit Tâche 2).
        user = User.objects.create_user(
            username=inscription.email,
            email=inscription.email,
            password=password_temp,
            first_name=inscription.nom,
            telephone=inscription.telephone,
            date_naissance=inscription.date_naissance,
            role='eleve'
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

    messages.success(
        request,
        f'تم قبول الطالب {inscription.nom}. كلمة المرور المؤقتة: {password_temp} '
        f'— بلّغها للطالب يدوياً (لا يوجد إرسال تلقائي موثوق عبر البريد الإلكتروني).'
    )
    return redirect('admin_inscriptions')

@role_required('admin')
def admin_rejeter_eleve(request, inscription_id):
    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)
    # Garde d'état: empêche de rejeter un dossier déjà traité (déjà accepté ou déjà
    # rejeté par un autre clic/onglet) — voir l'incident équivalent côté prof où une
    # candidature déjà rejetée pouvait être validée quand même faute de ce contrôle.
    if inscription.statut != 'en_attente':
        messages.error(
            request,
            f'تعذر الرفض: طلب {inscription.nom} لم يعد قيد الانتظار (تمت معالجته بالفعل).'
        )
        return redirect('admin_inscriptions')
    inscription.statut = 'rejete'
    inscription.save()
    messages.info(request, f'تم رفض طلب {inscription.nom}.')
    return redirect('admin_inscriptions')


@role_required('admin', 'mshrif')
def admin_inscription_eleve_detail(request, inscription_id):
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO, groupes_compatibles_pour_inscription

    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)
    if inscription.statut == 'valide':
        conflit = {'conflit': False, 'user': None, 'orphelin': False}
    else:
        conflit = _verifier_conflit_email(inscription.email)
    context = {
        'inscription': inscription,
        'conflit': conflit,
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
    d'un test), pour débloquer une validation d'inscription bloquée par un conflit d'email."""
    from accounts.models import Eleve, Prof
    from django.contrib.auth import get_user_model
    User = get_user_model()

    user = get_object_or_404(User, id=user_id)
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
    from inscriptions.models import InscriptionProf
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
    inscription.statut = 'rejete'
    inscription.save()
    messages.info(request, f'تم رفض طلب {inscription.nom}.')
    return redirect('admin_inscriptions')


# ==================== المشرف (mshrif) ====================
# Rôle au-dessus du مدير: valide en dernier les candidatures profs déjà pré-validées par le
# مدير (statut='validee_directeur') — c'est SEULEMENT à cette étape que le compte est créé.
# Voir PARTIE 1 du plan: workflow de validation prof en 2 étapes.

@role_required('mshrif')
def dashboard_mshrif(request):
    from accounts.models import Eleve, Prof
    from courses.models import Groupe, Presence
    from django.utils import timezone

    aujourdhui = timezone.localdate()
    presences_mois = Presence.objects.filter(seance__date__year=aujourdhui.year, seance__date__month=aujourdhui.month)
    nb_presences_total = presences_mois.count()
    nb_presences_ok = presences_mois.filter(statut='present').count()
    taux_presence = round((nb_presences_ok / nb_presences_total) * 100) if nb_presences_total else 0

    context = {
        'nb_eleves_actifs': Eleve.objects.filter(statut='actif').count(),
        'nb_profs': Prof.objects.count(),
        'nb_groupes_actifs': Groupe.objects.filter(statut='actif').count(),
        'taux_presence_mois': taux_presence,
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
    if inscription.statut != 'validee_directeur':
        messages.error(
            request,
            f'تعذر القبول النهائي: حالة طلب {inscription.nom} تغيّرت منذ فتح هذه الصفحة '
            f'(الحالة الحالية: {inscription.get_statut_display()}). لم يتم إنشاء أي حساب.'
        )
        return redirect('mshrif_inscription_prof_detail', inscription_id=inscription.id)

    conflit = _verifier_conflit_email(inscription.email)
    if conflit['conflit']:
        if conflit['orphelin']:
            messages.error(
                request,
                f'تعذر القبول: يوجد حساب بهذا البريد الإلكتروني ({inscription.email}) '
                f'بدون ملف شخصي مرتبط (على الأرجح من اختبار سابق). '
                f'احذف الحساب اليتيم أولاً ثم أعد المحاولة.'
            )
        else:
            messages.error(
                request,
                f'تعذر القبول: يوجد حساب نشط بهذا البريد الإلكتروني ({inscription.email}) '
                f'مرتبط بملف شخصي آخر — التعارض يجب حله يدوياً قبل المتابعة.'
            )
        return redirect('mshrif_inscription_prof_detail', inscription_id=inscription.id)

    password_temp = generer_mot_de_passe_temporaire()

    # Tout ou rien — voir le commentaire équivalent dans admin_valider_eleve.
    with transaction.atomic():
        # telephone/date_naissance copiés depuis l'inscription (voir audit Tâche 2).
        user = User.objects.create_user(
            username=inscription.email,
            email=inscription.email,
            password=password_temp,
            first_name=inscription.nom,
            last_name=inscription.prenom,
            telephone=inscription.telephone,
            date_naissance=inscription.date_naissance,
            role='prof'
        )
        prof = Prof.objects.create(
            user=user,
            ville=inscription.ville,
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
            inscription=inscription,
        )

        from courses.utils import matrice_vers_lignes
        matrice_vers_lignes(prof, inscription.disponibilites)

        inscription.statut = 'valide'
        inscription.save()

    envoyer_email_bienvenue(request, inscription.email, password_temp, f'{inscription.nom} {inscription.prenom}')

    messages.success(
        request,
        f'تم قبول المعلم {inscription.nom} نهائياً وإنشاء حسابه. كلمة المرور المؤقتة: {password_temp} '
        f'— بلّغها للمعلم يدوياً (لا يوجد إرسال تلقائي موثوق عبر البريد الإلكتروني).'
    )
    return redirect('mshrif_inscriptions_profs')


@role_required('mshrif')
def mshrif_rejeter_prof(request, inscription_id):
    from inscriptions.models import InscriptionProf
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
    inscription.statut = 'rejete'
    inscription.save()
    messages.info(request, f'تم رفض طلب {inscription.nom} نهائياً.')
    return redirect('mshrif_inscriptions_profs')


@role_required('mshrif')
def mshrif_remuneration(request):
    """الاستحقاقات — vue tabulaire de tous les profs pour le مشرف: montant de base
    (calculer_remuneration_prof) + majoration (visible ici, contrairement à la page prof
    qui ne la montre jamais) + total. Pas de filtre par mois: le calcul est toujours "à la
    volée" sur les élèves actifs actuels, aucune donnée mensuelle n'est historisée.

    Intègre aussi, en section repliable (fermée par défaut), la grille de référence
    des tarifs (courses.models.TarifRemuneration) — auparavant une page séparée
    (admin_tarifs_remuneration), fusionnée ici pour éviter 2 pages distinctes sur
    le même sujet. Toujours en lecture seule pour ce rôle : voir
    admin_tarifs_remuneration/admin_tarif_remuneration_modifier pour l'édition,
    réservée au مدير sur la page d'origine, restée intacte."""
    from accounts.models import Prof
    from courses.models import TarifRemuneration
    from courses.utils import calculer_remuneration_prof

    lignes = []
    total_base = 0
    total_majoration = 0
    for prof in Prof.objects.select_related('user').order_by('user__first_name'):
        base = calculer_remuneration_prof(prof)['total_calcule']
        majoration = prof.majoration_mensuelle or 0
        total_base += base
        total_majoration += majoration
        lignes.append({
            'prof': prof,
            'base': base,
            'majoration': prof.majoration_mensuelle,
            'total': base + majoration,
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
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/mshrif_remuneration.html', context)


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
    }
    return render(request, 'dashboard/eleve.html', context)


@role_required('eleve')
def eleve_seances(request):
    from accounts.models import Eleve
    from courses.models import Presence, Seance
    from django.utils import timezone

    eleve = get_object_or_404(Eleve, user=request.user)
    aujourdhui = timezone.localdate()

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
    })


@role_required('eleve')
def eleve_prof_detail(request, prof_id):
    from accounts.models import Eleve, Prof

    eleve = get_object_or_404(Eleve, user=request.user)
    prof = get_object_or_404(Prof.objects.filter(groupes__eleves=eleve).distinct(), id=prof_id)

    return render(request, 'dashboard/eleve_prof_detail.html', {
        'prof': prof,
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
    la liste sur autre chose)."""
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
    seances_retard = toutes_seances.filter(
        date__lt=aujourdhui, est_evaluee=False
    ).exclude(statut='annulee').order_by('-date', '-heure')

    # ===== Onglet "بالترتيب الزمني" (mirroir exact de prof_seances) =====
    seances_aujourdhui = toutes_seances.filter(date=aujourdhui).order_by('heure')
    seances_a_venir_qs = toutes_seances.filter(date__gt=aujourdhui).order_by('date', 'heure')
    nb_a_venir = seances_a_venir_qs.count()
    seances_a_venir = seances_a_venir_qs[:10]
    seances_a_venir_extra = seances_a_venir_qs[10:]
    # Complémentaire STRICT de seances_retard (via id__in) plutôt qu'une
    # condition dupliquée à la main — garantit qu'aucune séance ne peut
    # apparaître ni manquer des deux côtés à la fois.
    seances_passees_traitees = toutes_seances.filter(date__lt=aujourdhui).exclude(
        id__in=seances_retard.values('id')
    ).order_by('-date', '-heure')

    # ===== Onglet "حسب المعلم" (inchangé, alternative — plus affiché en même temps) =====
    profs_qs = profs_assignes.select_related('user').order_by('user__first_name')
    if prof_id:
        profs_qs = profs_qs.filter(id=prof_id)

    fiches_profs = []
    for prof in profs_qs:
        seances_prof = toutes_seances.filter(groupe__prof=prof)
        retard_prof = seances_prof.filter(
            date__lt=aujourdhui, est_evaluee=False
        ).exclude(statut='annulee').order_by('-date', '-heure')
        aujourdhui_prof = seances_prof.filter(date=aujourdhui).order_by('heure')
        a_venir_prof = seances_prof.filter(date__gt=aujourdhui).order_by('date', 'heure')
        traitees_prof = seances_prof.filter(date__lt=aujourdhui).exclude(
            id__in=retard_prof.values('id')
        ).order_by('-date', '-heure')

        if not (retard_prof.exists() or aujourdhui_prof.exists() or a_venir_prof.exists() or traitees_prof.exists()):
            continue

        fiches_profs.append({
            'prof': prof,
            'nb_retard': retard_prof.count(),
            'seances_retard': retard_prof,
            'seances_aujourdhui': aujourdhui_prof,
            'seances_a_venir': a_venir_prof[:5],
            'nb_a_venir': a_venir_prof.count(),
            'seances_traitees': traitees_prof[:5],
            'nb_traitees': traitees_prof.count(),
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

    return render(request, 'dashboard/superviseur.html', {
        'superviseur': superviseur,
        'aujourdhui': aujourdhui,
        'total_seances': toutes_seances.count(),
        'nb_retard': seances_retard.count(),
        'seances_retard': seances_retard,
        'seances_aujourdhui': seances_aujourdhui,
        'seances_a_venir': seances_a_venir,
        'seances_a_venir_extra': seances_a_venir_extra,
        'nb_a_venir': nb_a_venir,
        'seances_passees_traitees': paginer(request, seances_passees_traitees, 15),
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
    from django.db.models import Exists, OuterRef
    from accounts.models import Superviseur
    from courses.models import Seance
    from evaluations.models import Evaluation
    from evaluations.utils import moyenne_mensuelle_prof
    from django.utils import timezone

    superviseur = get_object_or_404(Superviseur, user=request.user)
    profs = superviseur.profs_assignes.select_related('user').prefetch_related('groupes__creneau').order_by('user__first_name')
    aujourdhui = timezone.localdate()

    fiches_profs = []
    for prof in profs:
        groupes_actifs = [g for g in prof.groupes.all() if g.statut == 'actif']
        types_presents = set()
        for g in groupes_actifs:
            if not g.creneau:
                continue
            if g.creneau.age_max < 18:
                types_presents.add('enfants')
            elif g.creneau.age_min >= 18:
                types_presents.add('adultes')
            else:
                types_presents.update({'enfants', 'adultes'})
        if types_presents == {'enfants', 'adultes'}:
            type_label = 'أطفال وبالغون'
        elif types_presents == {'enfants'}:
            type_label = 'أطفال'
        elif types_presents == {'adultes'}:
            type_label = 'بالغون'
        else:
            type_label = '—'

        resultat_moyenne = moyenne_mensuelle_prof(prof, aujourdhui.year, aujourdhui.month)

        fiches_profs.append({
            'prof': prof,
            'nb_groupes': len(groupes_actifs),
            'type_label': type_label,
            'moyenne_mensuelle': resultat_moyenne['moyenne'],
        })

    nb_evaluations_en_attente = Seance.objects.filter(
        groupe__prof__in=profs, statut='terminee', date__lt=aujourdhui
    ).annotate(
        est_evaluee=Exists(Evaluation.objects.filter(seance=OuterRef('pk')))
    ).filter(est_evaluee=False).count()

    from django.contrib.auth import get_user_model
    User = get_user_model()

    return render(request, 'dashboard/superviseur_profil.html', {
        'superviseur': superviseur,
        'fiches_profs': fiches_profs,
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


# ==================== ADMIN — SÉANCES ====================

@role_required('admin', 'mshrif')
def admin_seances(request):
    """Page d'exceptions: les séances normales sont générées automatiquement
    (voir courses.utils). Ici, l'admin peut seulement annuler ou déplacer
    une séance précise (prof malade, vacances...)."""
    from accounts.models import Prof
    from courses.models import Seance, Groupe
    from courses.utils import etendre_toutes_les_seances

    etendre_toutes_les_seances()

    groupe_id = request.GET.get('groupe', '')
    prof_id = request.GET.get('prof', '')
    date = request.GET.get('date', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')
    statut = request.GET.get('statut', '')

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
        'profs': Prof.objects.select_related('user').order_by('user__first_name'),
        'filtres': {
            'groupe': groupe_id,
            'prof': prof_id,
            'date': date,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'statut': statut,
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
    afficher_archives = request.GET.get('afficher_archives') == '1'

    eleves = Eleve.objects.all().select_related('user').order_by('id')
    if q:
        eleves = eleves.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(user__email__icontains=q)
        )
    if statut:
        eleves = eleves.filter(statut=statut)
    elif not afficher_archives:
        # Les archivés restent hors des listes actives par défaut (statut
        # réversible, pas une suppression — voir admin_eleve_archiver) sauf
        # si on les cherche explicitement via ce filtre ou le menu "الحالة".
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
            'afficher_archives': afficher_archives,
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
    eleve.statut = 'actif'
    eleve.date_suspension = None
    eleve.save(update_fields=['statut', 'date_suspension'])
    messages.success(request, f'تمت إعادة تفعيل الطالب {eleve.user.get_full_name()}.')
    return redirect('admin_eleve_detail', eleve_id=eleve.id)


@role_required('admin')
def admin_eleve_archiver(request, eleve_id):
    """Archive un élève — remplace toute suppression définitive: le compte,
    l'historique des séances/présences/paiements/évaluations restent intacts
    et interrogeables, seulement exclus des listes actives par défaut (voir
    filtre 'afficher les archivés' sur admin_eleves)."""
    from accounts.models import Eleve

    eleve = get_object_or_404(Eleve, id=eleve_id)
    eleve.statut = 'archive'
    eleve.date_suspension = None
    eleve.save(update_fields=['statut', 'date_suspension'])
    messages.info(request, f'تمت أرشفة الطالب {eleve.user.get_full_name()}.')
    return redirect('admin_eleve_detail', eleve_id=eleve.id)


@role_required('admin')
def admin_eleve_disponibilites(request, eleve_id):
    from accounts.models import Eleve
    from courses.models import DisponibiliteEleve
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO, matrice_vers_lignes_eleve

    eleve = get_object_or_404(Eleve, id=eleve_id)

    if request.method == 'POST':
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
    profs = Prof.objects.all().select_related('user').order_by('id')
    if q:
        profs = profs.filter(
            Q(user__first_name__icontains=q) |
            Q(user__last_name__icontains=q) |
            Q(ville__icontains=q)
        )

    context = {
        'profs': paginer(request, profs, 10),
        'q': q,
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
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_prof_detail.html', context)


@role_required('admin')
def admin_prof_majoration_modifier(request, prof_id):
    from accounts.models import Prof
    prof = get_object_or_404(Prof, id=prof_id)

    if request.method == 'POST':
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
    from accounts.models import Prof
    from courses.models import Seance
    from courses.utils import etendre_toutes_les_seances
    from django.utils import timezone

    etendre_toutes_les_seances()

    semaine_param = request.GET.get('semaine')
    prof_id = request.GET.get('prof', '')
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

    # Le filtre prof doit survivre à la navigation semaine précédente/suivante,
    # sinon changer de semaine le réinitialiserait silencieusement.
    suffixe_prof = f'&prof={prof_id}' if prof_id else ''

    context = {
        'jours': [
            {'date': jour, 'nom': JOURS_SEMAINE_AR[jour.weekday()], 'seances': seances_par_jour[jour]}
            for jour in jours_dates
        ],
        'lundi': lundi,
        'dimanche': jours_dates[-1],
        'semaine_precedente': (lundi - datetime.timedelta(days=7)).isoformat() + suffixe_prof,
        'semaine_suivante': (lundi + datetime.timedelta(days=7)).isoformat() + suffixe_prof,
        'profs': Prof.objects.select_related('user').order_by('user__first_name'),
        'filtres': {'prof': prof_id},
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


# ==================== ADMIN — VUE CENTRALISÉE DES ÉVALUATIONS ====================

LIMITE_EVALUATIONS_LISTE = 30


@role_required('admin', 'mshrif')
def admin_evaluations(request):
    from courses.models import Presence, Groupe
    from accounts.models import Prof, Eleve
    from evaluations.models import Evaluation

    groupe_id = request.GET.get('groupe', '')
    prof_id = request.GET.get('prof', '')
    eleve_id = request.GET.get('eleve', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    presences = Presence.objects.filter(seance__statut='terminee').select_related(
        'seance__groupe__prof__user', 'eleve__user'
    ).order_by('-seance__date', '-seance__heure')

    evaluations_profs = Evaluation.objects.select_related(
        'seance__groupe__prof__user', 'superviseur__user'
    ).prefetch_related('notes__critere').order_by('-seance__date')

    if groupe_id:
        presences = presences.filter(seance__groupe_id=groupe_id)
        evaluations_profs = evaluations_profs.filter(seance__groupe_id=groupe_id)
    if prof_id:
        presences = presences.filter(seance__groupe__prof_id=prof_id)
        evaluations_profs = evaluations_profs.filter(seance__groupe__prof_id=prof_id)
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
        'profs': Prof.objects.select_related('user').order_by('user__first_name'),
        'eleves': Eleve.objects.select_related('user').order_by('user__first_name'),
        'filtres': {
            'groupe': groupe_id,
            'prof': prof_id,
            'eleve': eleve_id,
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
    if request.user.role == 'superviseur':
        superviseur = get_object_or_404(Superviseur, user=request.user)
        profs = superviseur.profs_assignes.select_related('user')
    else:
        profs = Prof.objects.select_related('user')

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
    from accounts.models import Superviseur
    superviseurs = Superviseur.objects.select_related('user').prefetch_related('profs_assignes').order_by('user__first_name')
    context = {
        'superviseurs': superviseurs,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_superviseurs.html', context)


@role_required('admin')
def admin_superviseur_ajouter(request):
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

        password_temp = generer_mot_de_passe_temporaire()

        with transaction.atomic():
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password_temp,
                first_name=nom,
                telephone=telephone,
                role='superviseur'
            )
            Superviseur.objects.create(user=user)

        envoyer_email_bienvenue(request, email, password_temp, nom)

        messages.success(request, f'تمت إضافة المؤطر {nom}. كلمة المرور المؤقتة: {password_temp} — بلّغها له يدوياً (لا يوجد إرسال تلقائي موثوق عبر البريد الإلكتروني).')
        return redirect('admin_superviseurs')

    return render(request, 'dashboard/admin_superviseur_ajouter.html')


@role_required('admin', 'mshrif')
def admin_superviseur_assignations(request, superviseur_id):
    from accounts.models import Superviseur, Prof
    superviseur = get_object_or_404(Superviseur, id=superviseur_id)
    tous_les_profs = Prof.objects.select_related('user').order_by('user__first_name')

    if request.method == 'POST':
        profs_selectionnes = request.POST.getlist('profs')
        superviseur.profs_assignes.set(profs_selectionnes)
        messages.success(request, f'تم تحديث المعلمين المُسندين إلى {superviseur.user.get_full_name()}.')
        return redirect('admin_superviseurs')

    profs_assignes_ids = set(superviseur.profs_assignes.values_list('id', flat=True))

    context = {
        'superviseur': superviseur,
        'profs': tous_les_profs,
        'profs_assignes_ids': profs_assignes_ids,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/admin_superviseur_assignations.html', context)


# ==================== ADMIN — MODIFIER L'EMAIL D'UN UTILISATEUR ====================

@role_required('admin')
def admin_utilisateur_modifier_email(request, user_id):
    from django.contrib.auth import get_user_model
    from inscriptions.views import _email_deja_utilise

    User = get_user_model()
    utilisateur = get_object_or_404(User, id=user_id)
    next_url = _next_valide(request)

    if request.method == 'POST':
        nouvel_email = request.POST.get('nouvel_email', '').strip()
        confirmation_email = request.POST.get('confirmation_email', '').strip()

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

        ancien_email = utilisateur.email
        utilisateur.email = nouvel_email
        utilisateur.username = nouvel_email
        utilisateur.save()

        _invalider_sessions_utilisateur(utilisateur, request=request)
        email_envoye = envoyer_email_notification_changement_email(request, ancien_email, nouvel_email, utilisateur.get_full_name())

        if email_envoye:
            messages.success(request, f'تم تغيير البريد الإلكتروني إلى {nouvel_email} بنجاح. تم إشعار المستخدم على بريده الجديد.')
        else:
            messages.warning(request, f'تم تغيير البريد الإلكتروني إلى {nouvel_email} بنجاح، لكن تعذر إرسال بريد الإشعار. بلّغ المستخدم يدوياً.')
        return redirect(next_url)

    return render(request, 'dashboard/admin_utilisateur_modifier_email.html', {
        'utilisateur': utilisateur,
        'next': next_url,
    })


# ==================== ADMIN — MON COMPTE ====================

@role_required('admin')
def admin_mon_compte(request):
    from inscriptions.views import _email_deja_utilise

    if request.method == 'POST' and request.POST.get('action') == 'email':
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
