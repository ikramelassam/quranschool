from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Anciennes URLs (Tâche du 2026-08-07) — redirection permanente (301) vers
    # les nouvelles routes /register/teacher et /register/student (voir
    # core/urls.py, où name='inscription_eleve_choix'/'inscription_prof' vivent
    # désormais). Gardées ici, sans nom, au cas où l'ancienne adresse aurait
    # déjà été partagée ou enregistrée quelque part — jamais un lien mort.
    path('eleve/choix/', RedirectView.as_view(pattern_name='inscription_eleve_choix', permanent=True)),
    path('prof/', RedirectView.as_view(pattern_name='inscription_prof', permanent=True)),

    path('eleve/formulaire/<str:type_age>/', views.inscription_eleve_formulaire, name='inscription_eleve_formulaire'),
    path('confirmation/', views.inscription_confirmation, name='inscription_confirmation'),
]