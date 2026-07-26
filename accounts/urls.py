from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('mot-de-passe/', views.password_change_view, name='password_change'),
    path('mot-de-passe-oublie/', views.mot_de_passe_oublie, name='mot_de_passe_oublie'),
    path('reinitialiser-mon-mot-de-passe/', views.reinitialiser_mon_mot_de_passe, name='reinitialiser_mon_mot_de_passe'),
    path('telephone/', views.modifier_telephone, name='modifier_telephone'),
]