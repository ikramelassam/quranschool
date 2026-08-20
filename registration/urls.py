from django.urls import path
from . import views

# Rempli à l'Étape 6 (wizard public) — vide pour l'instant, cette app n'expose encore
# aucune vue. Le CRUD dashboard (Étape 5) vit dans dashboard/urls.py, pas ici, pour
# rester cohérent avec la convention déjà établie du projet (dashboard = toutes les
# vues des dashboards, zéro modèle ; les autres apps = modèles + logique métier).
urlpatterns = []
