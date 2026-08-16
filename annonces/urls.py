from django.urls import path

from . import views

urlpatterns = [
    path('', views.annonces_gestion, name='annonces_gestion'),
    path('ajouter/', views.annonce_ajouter, name='annonce_ajouter'),
    path('mes-annonces/', views.eleve_annonces, name='eleve_annonces'),
    path('<int:annonce_id>/toggle/', views.annonce_toggle, name='annonce_toggle'),
    path('fichier/<int:annonce_id>/', views.annonce_fichier, name='annonce_fichier'),
    # Catch-all volontairement en DERNIER (voir annonces.views.annonces_canal_detail) :
    # ne doit jamais intercepter 'ajouter/'/'mes-annonces/' ci-dessus.
    path('<str:cible>/', views.annonces_canal_detail, name='annonces_canal_detail'),
]
