from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages

def login_view(request):
    if request.user.is_authenticated:
        return redirect_by_role(request.user)
    
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        user = authenticate(request, username=email, password=password)
        
        if user is not None:
            login(request, user)
            return redirect_by_role(user)
        else:
            return render(request, 'accounts/login.html', {
                'error': 'البريد الإلكتروني أو كلمة المرور غير صحيحة'
            })
    
    return render(request, 'accounts/login.html')




def redirect_by_role(user):
    if user.role == 'eleve':
        return redirect('dashboard_eleve')
    elif user.role == 'prof':
        return redirect('dashboard_prof')
    elif user.role == 'superviseur':
        return redirect('dashboard_superviseur')
    elif user.role == 'admin':
        return redirect('dashboard_admin')
    elif user.role == 'mshrif':
        return redirect('dashboard_mshrif')
    return redirect('login')



def logout_view(request):
    logout(request)
    return redirect('login')


def mot_de_passe_oublie(request):
    """"نسيت كلمة المرور ؟" (Tâche 22 Partie E du 2026-07-26) — pas d'envoi email
    (Brevo non fiable, voir Partie D) : le mot de passe généré est envoyé au
    مدير via le bot Telegram déjà utilisé pour les notifications d'inscription
    (core.utils.envoyer_notification_telegram), à charge pour lui de le
    transmettre au titulaire du compte. Message affiché identique que l'email
    existe ou non, pour ne jamais révéler quels emails sont enregistrés."""
    from core.utils import envoyer_notification_telegram
    from dashboard.views import generer_mot_de_passe_temporaire

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        User = get_user_model()
        user = User.objects.filter(email=email).first()
        if user:
            nouveau_mot_de_passe = generer_mot_de_passe_temporaire()
            user.set_password(nouveau_mot_de_passe)
            user.doit_changer_mot_de_passe = True
            user.save()
            envoyer_notification_telegram(
                f'🔑 طلب "نسيت كلمة المرور"\n'
                f'الحساب: {email}\n'
                f'كلمة المرور الجديدة: {nouveau_mot_de_passe}\n'
                f'يرجى تبليغها لصاحب الحساب.'
            )
        messages.success(
            request,
            'إذا كان هذا البريد الإلكتروني مسجلاً لدينا، فقد تم إشعار الإدارة لإنشاء كلمة '
            'مرور جديدة — تواصل مع الإدارة للحصول عليها.'
        )
        # Reste sur la même page (au lieu de rediriger vers login) pour pouvoir
        # proposer tout de suite un contact direct avec le مدير (WhatsApp/email),
        # plutôt que de faire attendre le relais Telegram (Tâche du 2026-07-28).
        admin_principal = User.objects.filter(role='admin').order_by('id').first()
        return render(request, 'accounts/mot_de_passe_oublie.html', {
            'soumis': True,
            'admin_principal': admin_principal,
        })

    return render(request, 'accounts/mot_de_passe_oublie.html')


@login_required
def reinitialiser_mon_mot_de_passe(request):
    """Même mécanisme que mot_de_passe_oublie, pour un utilisateur déjà connecté
    qui veut réinitialiser (Tâche 22 Partie E) — accessible depuis sa page
    profil. Déconnecte immédiatement (l'ancien mot de passe devient invalide)."""
    from core.utils import envoyer_notification_telegram
    from dashboard.views import generer_mot_de_passe_temporaire

    if request.method == 'POST':
        nouveau_mot_de_passe = generer_mot_de_passe_temporaire()
        email = request.user.email
        request.user.set_password(nouveau_mot_de_passe)
        request.user.doit_changer_mot_de_passe = True
        request.user.save()
        envoyer_notification_telegram(
            f'🔑 طلب إعادة تعيين كلمة مرور (من داخل الحساب)\n'
            f'الحساب: {email}\n'
            f'كلمة المرور الجديدة: {nouveau_mot_de_passe}\n'
            f'يرجى تبليغها لصاحب الحساب.'
        )
        logout(request)
        messages.success(
            request,
            'تم إنشاء كلمة مرور جديدة وإشعار الإدارة بها — تواصل معها للحصول عليها، '
            'ثم سجّل الدخول من جديد.'
        )
        return redirect('login')
    return redirect_by_role(request.user)


@login_required
def modifier_telephone(request):
    """Modifie le téléphone du User connecté — partagé par élève/prof/مؤطر
    (Tâche 11 du 2026-07-25). Vue générique (n'agit que sur request.user),
    comme password_change_view : chaque page profil poste ici avec un champ
    caché 'next' (nom d'URL) pour revenir sur elle-même après sauvegarde."""
    if request.method == 'POST':
        request.user.telephone = request.POST.get('telephone', '').strip()
        request.user.save(update_fields=['telephone'])
        messages.success(request, 'تم تحديث رقم الهاتف بنجاح.')
        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
    return redirect_by_role(request.user)


BASE_TEMPLATE_PAR_ROLE = {
    'eleve': 'dashboard/base_eleve.html',
    'prof': 'dashboard/base_prof.html',
    'superviseur': 'dashboard/base_superviseur.html',
    'admin': 'dashboard/base_admin.html',
    'mshrif': 'dashboard/base_mshrif.html',
}
COULEUR_PAR_ROLE = {
    'eleve': '#2d5a1b',
    'admin': '#2d5a1b',
    'prof': '#1a3a5c',
    'superviseur': '#6b3a2a',
    'mshrif': '#1A0D00',
}


@login_required
def password_change_view(request):
    changement_force = request.user.doit_changer_mot_de_passe

    if request.method == 'POST':
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
            request.user.doit_changer_mot_de_passe = False
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
            return redirect_by_role(request.user)

    return render(request, 'accounts/password_change.html', {
        'base_template': BASE_TEMPLATE_PAR_ROLE.get(request.user.role, 'dashboard/base_eleve.html'),
        'couleur': COULEUR_PAR_ROLE.get(request.user.role, '#2d5a1b'),
        'changement_force': changement_force,
    })