from django.urls import path
from . import views

urlpatterns = [
    path('eleve/choix/', views.inscription_eleve_choix, name='inscription_eleve_choix'),
    path('eleve/formulaire/<str:type_age>/', views.inscription_eleve_formulaire, name='inscription_eleve_formulaire'),
    path('confirmation/', views.inscription_confirmation, name='inscription_confirmation'),
    path('prof/', views.inscription_prof, name='inscription_prof'),
]