from django.shortcuts import render
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout

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