import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from accounts.decorators import role_required
from core.utils import paginer
from inscriptions.models import InscriptionEleve

JOURS_SEMAINE_AR = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']


def envoyer_email_bienvenue(request, email, password_temp, prenom_nom):
    """Envoie le mot de passe temporaire + le lien de connexion au nouvel utilisateur (élève ou prof)."""
    from django.urls import reverse

    lien_connexion = request.build_absolute_uri(reverse('login'))
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


def envoyer_email_notification_changement_email(request, ancien_email, nouvel_email, prenom_nom):
    """Notifie le NOUVEL email qu'il vient d'être associé à ce compte suite à un changement."""
    from django.urls import reverse

    lien_connexion = request.build_absolute_uri(reverse('login'))
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

    try:
        prof = Prof.objects.get(user=request.user)
    except Prof.DoesNotExist:
        return redirect('login')

    groupes = Groupe.objects.filter(prof=prof)
    seances = Seance.objects.filter(
        groupe__prof=prof
    ).order_by('-date')[:5]

    context = {
        'prof': prof,
        'groupes': groupes,
        'seances': seances,
        'total_eleves': sum(g.eleves.count() for g in groupes),
        'total_groupes': groupes.count(),
    }
    return render(request, 'dashboard/prof.html', context)


@role_required('prof')
def prof_groupes(request):
    from accounts.models import Prof
    from courses.models import Groupe

    prof = get_object_or_404(Prof, user=request.user)
    groupes = Groupe.objects.filter(prof=prof)

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
    from courses.models import Seance

    prof = get_object_or_404(Prof, user=request.user)
    seances = Seance.objects.filter(
        groupe__prof=prof
    ).order_by('-date')

    return render(request, 'dashboard/prof_seances.html', {
        'prof': prof,
        'seances': paginer(request, seances, 10),
    })


@role_required('prof')
def prof_seance_detail(request, seance_id):
    from accounts.models import Prof
    from courses.models import Seance, Presence
    from courses.quran_data import SOURATES

    prof = get_object_or_404(Prof, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof=prof)
    eleves = seance.groupe.eleves.all()

    # Django templates ne peuvent pas faire presences[eleve.id] (lookup par variable).
    # On construit donc directement la liste (élève, présence) dans la vue.
    presences_par_eleve = {p.eleve_id: p for p in Presence.objects.filter(seance=seance)}
    eleves_presences = [
        {'eleve': eleve, 'presence': presences_par_eleve.get(eleve.id)}
        for eleve in eleves
    ]

    return render(request, 'dashboard/prof_seance_detail.html', {
        'prof': prof,
        'seance': seance,
        'eleves_presences': eleves_presences,
        'sourates': SOURATES,
    })


@role_required('prof')
def prof_presence_sauvegarder(request, seance_id):
    from accounts.models import Prof, Eleve
    from courses.models import Seance, Presence

    prof = get_object_or_404(Prof, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof=prof)

    if request.method == 'POST':
        eleves = seance.groupe.eleves.all()
        for eleve in eleves:
            statut = request.POST.get(f'statut_{eleve.id}', 'absent')
            sourate_memorisee = request.POST.get(f'sourate_memo_{eleve.id}') or None
            ayah_debut_memorisation = request.POST.get(f'ayah_debut_memo_{eleve.id}') or None
            ayah_fin_memorisation = request.POST.get(f'ayah_fin_memo_{eleve.id}') or None
            note_memorisation = request.POST.get(f'note_memo_{eleve.id}', '')
            sourate_revisee = request.POST.get(f'sourate_rev_{eleve.id}') or None
            ayah_debut_revision = request.POST.get(f'ayah_debut_rev_{eleve.id}') or None
            ayah_fin_revision = request.POST.get(f'ayah_fin_rev_{eleve.id}') or None
            note_revision = request.POST.get(f'note_rev_{eleve.id}', '')
            remarque = request.POST.get(f'remarque_{eleve.id}', '')

            Presence.objects.update_or_create(
                seance=seance,
                eleve=eleve,
                defaults={
                    'statut': statut,
                    'sourate_memorisee': sourate_memorisee,
                    'ayah_debut_memorisation': ayah_debut_memorisation,
                    'ayah_fin_memorisation': ayah_fin_memorisation,
                    'note_memorisation': note_memorisation,
                    'sourate_revisee': sourate_revisee,
                    'ayah_debut_revision': ayah_debut_revision,
                    'ayah_fin_revision': ayah_fin_revision,
                    'note_revision': note_revision,
                    'remarque': remarque,
                }
            )

        seance.statut = 'terminee'
        seance.save()
        messages.success(request, 'تم حفظ الحضور والتقييمات بنجاح.')
        return redirect('prof_seances')

    return redirect('prof_seance_detail', seance_id=seance_id)


@role_required('prof')
def prof_emploi(request):
    from accounts.models import Prof
    from courses.models import Groupe

    prof = get_object_or_404(Prof, user=request.user)
    groupes = Groupe.objects.filter(prof=prof, statut='actif')

    return render(request, 'dashboard/prof_emploi.html', {
        'prof': prof,
        'groupes': groupes,
    })


@role_required('admin')
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
    }
    return render(request, 'dashboard/admin.html', context)
@role_required('admin')
def admin_inscriptions(request):
    inscriptions = InscriptionEleve.objects.filter(
        statut='en_attente'
    ).order_by('-date_soumission')

    return render(request, 'dashboard/admin_inscriptions.html', {
        'inscriptions': paginer(request, inscriptions, 10),
    })



@role_required('admin')
def admin_valider_eleve(request, inscription_id):
    from inscriptions.models import InscriptionEleve
    from accounts.models import Eleve
    from django.contrib.auth import get_user_model
    import random, string

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

    # Génère mot de passe temporaire
    password_temp = ''.join(random.choices(string.ascii_letters + string.digits, k=8))

    # Crée le User
    user = User.objects.create_user(
        username=inscription.email,
        email=inscription.email,
        password=password_temp,
        first_name=inscription.nom,
        role='eleve'
    )

    # Crée le profil Eleve
    Eleve.objects.create(
        user=user,
        sexe=inscription.sexe,
        statut='actif',
        inscription=inscription
    )

    envoyer_email_bienvenue(request, inscription.email, password_temp, inscription.nom)

    # Change le statut
    inscription.statut = 'valide'
    inscription.save()

    messages.success(request, f'تم قبول الطالب {inscription.nom} وإرسال معلومات الدخول له.')
    return redirect('admin_inscriptions')

@role_required('admin')
def admin_rejeter_eleve(request, inscription_id):
    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)
    inscription.statut = 'rejete'
    inscription.save()
    messages.info(request, f'تم رفض طلب {inscription.nom}.')
    return redirect('admin_inscriptions')


@role_required('admin')
def admin_inscription_eleve_detail(request, inscription_id):
    inscription = get_object_or_404(InscriptionEleve, id=inscription_id)
    if inscription.statut == 'valide':
        conflit = {'conflit': False, 'user': None, 'orphelin': False}
    else:
        conflit = _verifier_conflit_email(inscription.email)
    return render(request, 'dashboard/admin_inscription_detail.html', {
        'inscription': inscription,
        'conflit': conflit,
    })

@role_required('admin')
def admin_inscription_prof_detail(request, inscription_id):
    from inscriptions.models import InscriptionProf
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)
    if inscription.statut == 'valide':
        conflit = {'conflit': False, 'user': None, 'orphelin': False}
    else:
        conflit = _verifier_conflit_email(inscription.email)
    return render(request, 'dashboard/admin_inscription_prof_detail.html', {
        'inscription': inscription,
        'conflit': conflit,
    })

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
    from inscriptions.models import InscriptionProf
    from accounts.models import Prof
    from django.contrib.auth import get_user_model
    import random, string

    User = get_user_model()
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)

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
        return redirect('admin_inscription_prof_detail', inscription_id=inscription.id)

    password_temp = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user = User.objects.create_user(
        username=inscription.email,
        email=inscription.email,
        password=password_temp,
        first_name=inscription.nom,
        last_name=inscription.prenom,
        role='prof'
    )
    Prof.objects.create(
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

    envoyer_email_bienvenue(request, inscription.email, password_temp, f'{inscription.nom} {inscription.prenom}')

    inscription.statut = 'valide'
    inscription.save()
    messages.success(request, f'تم قبول المعلم {inscription.nom} وإرسال معلومات الدخول له.')
    return redirect('admin_inscriptions_profs')

@role_required('admin')
def admin_rejeter_prof(request, inscription_id):
    from inscriptions.models import InscriptionProf
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)
    inscription.statut = 'rejete'
    inscription.save()
    messages.info(request, f'تم رفض طلب {inscription.nom}.')
    return redirect('admin_inscriptions_profs')

@role_required('admin')
def admin_inscriptions_profs(request):
    from inscriptions.models import InscriptionProf
    inscriptions = InscriptionProf.objects.filter(
        statut='en_attente'
    ).order_by('-date_soumission')

    return render(request, 'dashboard/admin_inscriptions_profs.html', {
        'inscriptions': paginer(request, inscriptions, 10),
    })


# ==================== DASHBOARD ÉLÈVE ====================

@role_required('eleve')
def dashboard_eleve(request):
    from accounts.models import Eleve
    from courses.models import Seance, Presence

    try:
        eleve = Eleve.objects.get(user=request.user)
    except Eleve.DoesNotExist:
        return redirect('login')

    groupes = eleve.groupes.all()
    presences = Presence.objects.filter(
        eleve=eleve
    ).order_by('-seance__date')[:10]

    context = {
        'eleve': eleve,
        'groupes': groupes,
        'presences': presences,
        'total_seances': Presence.objects.filter(eleve=eleve).count(),
        'total_present': Presence.objects.filter(eleve=eleve, statut='present').count(),
    }
    return render(request, 'dashboard/eleve.html', context)


@role_required('eleve')
def eleve_seances(request):
    from accounts.models import Eleve
    from courses.models import Presence

    eleve = get_object_or_404(Eleve, user=request.user)
    presences = Presence.objects.filter(
        eleve=eleve
    ).order_by('-seance__date')

    return render(request, 'dashboard/eleve_seances.html', {
        'eleve': eleve,
        'presences': paginer(request, presences, 10),
    })


@role_required('eleve')
def eleve_profil(request):
    from accounts.models import Eleve
    eleve = get_object_or_404(Eleve, user=request.user)
    return render(request, 'dashboard/eleve_profil.html', {
        'eleve': eleve,
    })


# ==================== DASHBOARD SUPERVISEUR ====================

@role_required('superviseur')
def dashboard_superviseur(request):
    from accounts.models import Superviseur
    from courses.models import Seance

    superviseur = get_object_or_404(Superviseur, user=request.user)
    seances = Seance.objects.filter(
        statut='terminee',
        groupe__prof__in=superviseur.profs_assignes.all(),
    ).order_by('-date')[:10]

    return render(request, 'dashboard/superviseur.html', {
        'seances': seances,
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


# ==================== ADMIN — SÉANCES ====================

@role_required('admin')
def admin_seances(request):
    """Page d'exceptions: les séances normales sont générées automatiquement
    (voir courses.utils). Ici, l'admin peut seulement annuler ou déplacer
    une séance précise (prof malade, vacances...)."""
    from courses.models import Seance
    from courses.utils import etendre_toutes_les_seances

    etendre_toutes_les_seances()

    seances = Seance.objects.all().order_by('-date')
    return render(request, 'dashboard/admin_seances.html', {
        'seances': paginer(request, seances, 10),
    })


@role_required('admin')
def admin_seance_annuler(request, seance_id):
    from courses.models import Seance
    seance = get_object_or_404(Seance, id=seance_id)
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

@role_required('admin')
def admin_eleves(request):
    from accounts.models import Eleve
    eleves = Eleve.objects.all().select_related('user').order_by('id')
    return render(request, 'dashboard/admin_eleves.html', {
        'eleves': paginer(request, eleves, 10),
    })


@role_required('admin')
def admin_eleve_detail(request, eleve_id):
    from accounts.models import Eleve
    eleve = get_object_or_404(Eleve, id=eleve_id)
    return render(request, 'dashboard/admin_eleve_detail.html', {
        'eleve': eleve,
        'inscription': eleve.inscription,
    })


# ==================== ADMIN — PROFS VALIDÉS ====================

@role_required('admin')
def admin_profs(request):
    from accounts.models import Prof
    profs = Prof.objects.all().select_related('user').order_by('id')
    return render(request, 'dashboard/admin_profs.html', {
        'profs': paginer(request, profs, 10),
    })


@role_required('admin')
def admin_prof_detail(request, prof_id):
    from accounts.models import Prof
    prof = get_object_or_404(Prof, id=prof_id)
    return render(request, 'dashboard/admin_prof_detail.html', {
        'prof': prof,
        'inscription': prof.inscription,
    })


# ==================== ADMIN — CALENDRIER ====================

@role_required('admin')
def admin_calendrier(request):
    from courses.models import Seance
    from courses.utils import etendre_toutes_les_seances

    etendre_toutes_les_seances()

    semaine_param = request.GET.get('semaine')
    try:
        reference = datetime.date.fromisoformat(semaine_param) if semaine_param else datetime.date.today()
    except ValueError:
        reference = datetime.date.today()

    lundi = reference - datetime.timedelta(days=reference.weekday())
    jours_dates = [lundi + datetime.timedelta(days=i) for i in range(7)]

    seances = Seance.objects.filter(
        date__gte=jours_dates[0], date__lte=jours_dates[-1]
    ).select_related('groupe', 'groupe__prof__user').order_by('date', 'heure')

    seances_par_jour = {jour: [] for jour in jours_dates}
    for seance in seances:
        seances_par_jour[seance.date].append(seance)

    return render(request, 'dashboard/admin_calendrier.html', {
        'jours': [
            {'date': jour, 'nom': JOURS_SEMAINE_AR[jour.weekday()], 'seances': seances_par_jour[jour]}
            for jour in jours_dates
        ],
        'lundi': lundi,
        'dimanche': jours_dates[-1],
        'semaine_precedente': (lundi - datetime.timedelta(days=7)).isoformat(),
        'semaine_suivante': (lundi + datetime.timedelta(days=7)).isoformat(),
    })


# ==================== ADMIN — PARAMÈTRES (TARIFS) ====================

@role_required('admin')
def admin_parametres_abonnements(request):
    from inscriptions.models import TypeAbonnement
    types_abonnement = TypeAbonnement.objects.all().order_by('ordre')
    return render(request, 'dashboard/admin_parametres_abonnements.html', {
        'types_abonnement': types_abonnement,
    })


@role_required('admin')
def admin_abonnement_ajouter(request):
    from inscriptions.models import TypeAbonnement

    if request.method == 'POST':
        TypeAbonnement.objects.create(
            code=request.POST.get('code'),
            label=request.POST.get('label'),
            prix=request.POST.get('prix'),
            ordre=request.POST.get('ordre', 0),
        )
        messages.success(request, 'تمت إضافة نوع الاشتراك بنجاح.')
        return redirect('admin_parametres_abonnements')

    return render(request, 'dashboard/admin_abonnement_ajouter.html')


@role_required('admin')
def admin_abonnement_modifier(request, abonnement_id):
    from inscriptions.models import TypeAbonnement
    type_abonnement = get_object_or_404(TypeAbonnement, id=abonnement_id)

    if request.method == 'POST':
        type_abonnement.label = request.POST.get('label')
        type_abonnement.prix = request.POST.get('prix')
        type_abonnement.ordre = request.POST.get('ordre', 0)
        type_abonnement.save()
        messages.success(request, 'تم تعديل نوع الاشتراك بنجاح.')
        return redirect('admin_parametres_abonnements')

    return render(request, 'dashboard/admin_abonnement_modifier.html', {
        'type_abonnement': type_abonnement,
    })


@role_required('admin')
def admin_abonnement_toggle(request, abonnement_id):
    from inscriptions.models import TypeAbonnement
    type_abonnement = get_object_or_404(TypeAbonnement, id=abonnement_id)
    type_abonnement.est_actif = not type_abonnement.est_actif
    type_abonnement.save()
    messages.info(request, 'تم تفعيل نوع الاشتراك.' if type_abonnement.est_actif else 'تم تعطيل نوع الاشتراك.')
    return redirect('admin_parametres_abonnements')


# ==================== ADMIN — CRITÈRES D'ÉVALUATION (SUPERVISEUR) ====================

@role_required('admin')
def admin_criteres(request):
    from evaluations.models import Critere
    criteres = Critere.objects.all().order_by('ordre')
    return render(request, 'dashboard/admin_criteres.html', {
        'criteres': criteres,
    })


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


@role_required('admin')
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

    return render(request, 'dashboard/admin_evaluations.html', {
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
    })


@role_required('admin')
def admin_evaluation_detail(request, seance_id):
    from courses.models import Seance, Presence
    from evaluations.models import Evaluation

    seance = get_object_or_404(Seance, id=seance_id)
    presences = Presence.objects.filter(seance=seance).select_related('eleve__user').order_by('eleve__user__first_name')
    evaluation = Evaluation.objects.filter(seance=seance).select_related('superviseur__user').prefetch_related('notes__critere').first()

    return render(request, 'dashboard/admin_evaluation_detail.html', {
        'seance': seance,
        'presences': presences,
        'evaluation': evaluation,
    })


# ==================== ADMIN — ASSIGNATION SUPERVISEURS ↔ PROFS ====================

@role_required('admin')
def admin_superviseurs(request):
    from accounts.models import Superviseur
    superviseurs = Superviseur.objects.select_related('user').prefetch_related('profs_assignes').order_by('user__first_name')
    return render(request, 'dashboard/admin_superviseurs.html', {
        'superviseurs': superviseurs,
    })


@role_required('admin')
def admin_superviseur_assignations(request, superviseur_id):
    from accounts.models import Superviseur, Prof
    superviseur = get_object_or_404(Superviseur, id=superviseur_id)
    tous_les_profs = Prof.objects.select_related('user').order_by('user__first_name')

    if request.method == 'POST':
        profs_selectionnes = request.POST.getlist('profs')
        superviseur.profs_assignes.set(profs_selectionnes)
        messages.success(request, f'تم تحديث المعلمين المُسندين إلى {superviseur.user.get_full_name}.')
        return redirect('admin_superviseurs')

    profs_assignes_ids = set(superviseur.profs_assignes.values_list('id', flat=True))

    return render(request, 'dashboard/admin_superviseur_assignations.html', {
        'superviseur': superviseur,
        'profs': tous_les_profs,
        'profs_assignes_ids': profs_assignes_ids,
    })


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
        envoyer_email_notification_changement_email(request, ancien_email, nouvel_email, utilisateur.get_full_name())

        messages.success(request, f'تم تغيير البريد الإلكتروني إلى {nouvel_email} بنجاح. تم إشعار المستخدم على بريده الجديد.')
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
            envoyer_email_notification_changement_email(request, ancien_email, nouvel_email, request.user.get_full_name())
            messages.success(request, f'تم تغيير بريدك الإلكتروني إلى {nouvel_email} بنجاح.')
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
