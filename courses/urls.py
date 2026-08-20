from django.urls import path
from . import views

urlpatterns = [
    # Groupes
    path('groupes/', views.groupes_list, name='admin_groupes'),
    path('groupes/ajouter/', views.groupe_ajouter, name='admin_groupe_ajouter'),
    path('groupes/<int:groupe_id>/', views.groupe_detail, name='admin_groupe_detail'),
    path('groupes/<int:groupe_id>/modifier/', views.groupe_modifier, name='admin_groupe_modifier'),
    path('groupes/<int:groupe_id>/ajouter-eleve/', views.groupe_ajouter_eleve, name='admin_groupe_ajouter_eleve'),
    path('groupes/<int:groupe_id>/retirer-eleve/<int:eleve_id>/', views.groupe_retirer_eleve, name='admin_groupe_retirer_eleve'),
    path('groupes/<int:groupe_id>/transferer-eleve/<int:eleve_id>/', views.groupe_transferer_eleve, name='admin_groupe_transferer_eleve'),
    path('groupes/<int:groupe_id>/supprimer/', views.groupe_supprimer, name='admin_groupe_supprimer'),
    path('groupes/<int:groupe_id>/archiver/', views.groupe_archiver, name='admin_groupe_archiver'),
    path('groupes/<int:groupe_id>/reactiver/', views.groupe_reactiver, name='admin_groupe_reactiver'),
    path('groupes/<int:groupe_id>/supprimer-definitivement/', views.groupe_supprimer_definitivement, name='admin_groupe_supprimer_definitivement'),
    # Étape 5D — onglet "الخصائص" (moteur d'inscription configurable)
    path('groupes/<int:groupe_id>/criteres/<int:critere_id>/definir/', views.groupe_definir_critere, name='admin_groupe_definir_critere'),

    # Créneaux
    path('creneaux/', views.creneaux_list, name='admin_creneaux'),
    path('creneaux/ajouter/', views.creneau_ajouter, name='admin_creneau_ajouter'),
    path('creneaux/<int:creneau_id>/modifier/', views.creneau_modifier, name='admin_creneau_modifier'),
    path('creneaux/<int:creneau_id>/toggle/', views.creneau_toggle, name='admin_creneau_toggle'),
    path('creneaux/<int:creneau_id>/supprimer/', views.creneau_supprimer, name='admin_creneau_supprimer'),
    path('creneaux/<int:creneau_id>/supprimer-definitivement/', views.creneau_supprimer_definitivement, name='admin_creneau_supprimer_definitivement'),

    # Liens Google Meet
    path('liens-meet/', views.liens_meet_list, name='admin_liens_meet'),
    path('liens-meet/ajouter/', views.lien_meet_ajouter, name='admin_lien_meet_ajouter'),
    path('liens-meet/<int:lien_id>/toggle/', views.lien_meet_toggle, name='admin_lien_meet_toggle'),
    path('liens-meet/attribuer/<int:groupe_id>/', views.lien_meet_attribuer_groupe, name='admin_lien_meet_attribuer_groupe'),
]