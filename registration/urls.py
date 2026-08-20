from django.urls import path
from . import views

# Wizard public (Étape 6) — vit sous /registration/wizard/, complètement
# séparé de /register/student (l'ancien formulaire à une page, inscriptions.
# urls.py, INCHANGÉ et toujours en service en parallèle tant que ce nouveau
# parcours n'est pas validé en conditions réelles).
urlpatterns = [
    path('wizard/', views.wizard_intro, name='wizard_intro'),
    path('wizard/identite/', views.wizard_identite, name='wizard_identite'),
    path('wizard/programme/', views.wizard_programme, name='wizard_programme'),
    path('wizard/groupe/', views.wizard_groupe, name='wizard_groupe'),
    path('wizard/abonnement/', views.wizard_abonnement, name='wizard_abonnement'),
    path('wizard/paiement/', views.wizard_paiement, name='wizard_paiement'),
    path('wizard/confirmation/', views.wizard_confirmation, name='wizard_confirmation'),
]
