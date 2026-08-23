from django.urls import path
from . import views

# Wizard public (Étape 6) — vit sous /registration/wizard/, complètement
# séparé de /register/student (l'ancien formulaire à une page, inscriptions.
# urls.py, INCHANGÉ et toujours en service en parallèle tant que ce nouveau
# parcours n'est pas validé en conditions réelles).
urlpatterns = [
    path('wizard/', views.wizard_intro, name='wizard_intro'),
    path('wizard/categorie-age/', views.wizard_categorie_age, name='wizard_categorie_age'),
    path('wizard/identite/', views.wizard_identite, name='wizard_identite'),
    path('wizard/programme/', views.wizard_programme, name='wizard_programme'),
    path('wizard/groupe/', views.wizard_groupe, name='wizard_groupe'),
    path('wizard/abonnement/', views.wizard_abonnement, name='wizard_abonnement'),
    path('wizard/paiement/', views.wizard_paiement, name='wizard_paiement'),
    path('wizard/confirmation/', views.wizard_confirmation, name='wizard_confirmation'),
    # Partie 3B (chantier du 2026-08-23) : une seule vue générique sert un
    # nombre illimité d'étapes personnalisées créées par le مدير — jamais un
    # path() par étape. Placée en dernier : les 7 chemins ci-dessus, plus
    # spécifiques, doivent toujours matcher en premier pour leurs propres codes.
    path('wizard/etape/<slug:code>/', views.wizard_etape_personnalisee, name='wizard_etape_personnalisee'),
]
