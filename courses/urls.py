from django.urls import path
from . import views

urlpatterns = [
    # Groupes
    path('groupes/', views.groupes_list, name='admin_groupes'),
    path('groupes/ajouter/', views.groupe_ajouter, name='admin_groupe_ajouter'),
    path('groupes/<int:groupe_id>/', views.groupe_detail, name='admin_groupe_detail'),
    path('groupes/<int:groupe_id>/modifier/', views.groupe_modifier, name='admin_groupe_modifier'),
    path('groupes/<int:groupe_id>/ajouter-eleve/', views.groupe_ajouter_eleve, name='admin_groupe_ajouter_eleve'),

    # Créneaux
    path('creneaux/', views.creneaux_list, name='admin_creneaux'),
    path('creneaux/ajouter/', views.creneau_ajouter, name='admin_creneau_ajouter'),
    path('creneaux/<int:creneau_id>/modifier/', views.creneau_modifier, name='admin_creneau_modifier'),
    path('creneaux/<int:creneau_id>/toggle/', views.creneau_toggle, name='admin_creneau_toggle'),
]