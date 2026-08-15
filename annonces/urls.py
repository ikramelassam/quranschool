from django.urls import path

from . import views

urlpatterns = [
    path('', views.annonces_gestion, name='annonces_gestion'),
    path('ajouter/', views.annonce_ajouter, name='annonce_ajouter'),
    path('<int:annonce_id>/toggle/', views.annonce_toggle, name='annonce_toggle'),
    path('mes-annonces/', views.eleve_annonces, name='eleve_annonces'),
]
