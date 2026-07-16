from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
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
    return redirect('login')



def logout_view(request):
    logout(request)
    return redirect('login')


BASE_TEMPLATE_PAR_ROLE = {
    'eleve': 'dashboard/base_eleve.html',
    'prof': 'dashboard/base_prof.html',
    'superviseur': 'dashboard/base_superviseur.html',
    'admin': 'dashboard/base_admin.html',
}
COULEUR_PAR_ROLE = {
    'eleve': '#2d5a1b',
    'admin': '#2d5a1b',
    'prof': '#1a3a5c',
    'superviseur': '#6b3a2a',
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