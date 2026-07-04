import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from django.contrib import messages
from accounts.decorators import role_required
from core.utils import paginer
from inscriptions.models import InscriptionEleve

JOURS_SEMAINE_AR = ['الاثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']


def envoyer_email_bienvenue(email, password_temp, prenom_nom):
    """Envoie le mot de passe temporaire au nouvel utilisateur (élève ou prof)."""
    send_mail(
        subject='مرحباً بك في منصة زدني علماً - معلومات الدخول',
        message=(
            f'مرحباً {prenom_nom},\n\n'
            f'تم قبول ملفك. يمكنك الآن تسجيل الدخول باستخدام:\n'
            f'البريد الإلكتروني: {email}\n'
            f'كلمة المرور المؤقتة: {password_temp}\n\n'
            f'ننصحك بتغيير كلمة المرور بعد أول تسجيل دخول.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[email],
        fail_silently=False,
    )


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
            quantite_memorisee = request.POST.get(f'memorisee_{eleve.id}', '')
            quantite_revisee = request.POST.get(f'revisee_{eleve.id}', '')
            note_memorisation = request.POST.get(f'note_memo_{eleve.id}', '')
            note_revision = request.POST.get(f'note_rev_{eleve.id}', '')
            remarque = request.POST.get(f'remarque_{eleve.id}', '')

            Presence.objects.update_or_create(
                seance=seance,
                eleve=eleve,
                defaults={
                    'statut': statut,
                    'quantite_memorisee': quantite_memorisee,
                    'quantite_revisee': quantite_revisee,
                    'note_memorisation': note_memorisation,
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

    # Crée le User seulement s'il n'existe pas déjà
    if not User.objects.filter(email=inscription.email).exists():
        
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

        envoyer_email_bienvenue(inscription.email, password_temp, inscription.nom)

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
    return render(request, 'dashboard/admin_inscription_detail.html', {
        'inscription': inscription,
    })

@role_required('admin')
def admin_inscription_prof_detail(request, inscription_id):
    from inscriptions.models import InscriptionProf
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)
    return render(request, 'dashboard/admin_inscription_prof_detail.html', {
        'inscription': inscription,
    })

@role_required('admin')
def admin_valider_prof(request, inscription_id):
    from inscriptions.models import InscriptionProf
    from accounts.models import Prof
    from django.contrib.auth import get_user_model
    import random, string

    User = get_user_model()
    inscription = get_object_or_404(InscriptionProf, id=inscription_id)

    if not User.objects.filter(email=inscription.email).exists():
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

        envoyer_email_bienvenue(inscription.email, password_temp, f'{inscription.nom} {inscription.prenom}')

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
    from courses.models import Seance
    seances = Seance.objects.filter(
        statut='terminee'
    ).order_by('-date')[:10]

    return render(request, 'dashboard/superviseur.html', {
        'seances': seances,
    })


@role_required('superviseur')
def superviseur_seance_detail(request, seance_id):
    from courses.models import Seance, Presence
    from evaluations.models import Evaluation

    seance = get_object_or_404(Seance, id=seance_id)
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
