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

    # Note : l'ancien écran séparé « الحلقات » (créneaux/*) a été retiré le
    # 2026-09-04 (chantier « fusion horaire/groupe », décision explicite du
    # client) — l'horaire (jour/heure/âge/sexe/type/riwaya) se saisit
    # désormais DIRECTEMENT dans le formulaire du groupe, un Creneau privé
    # étant créé automatiquement derrière (jamais partagé entre 2 groupes,
    # voir courses.views.groupe_ajouter/groupe_modifier). Le modèle Creneau
    # lui-même n'est PAS supprimé — seules ces 6 routes CRUD disparaissent.

    # Liens Google Meet
    path('liens-meet/', views.liens_meet_list, name='admin_liens_meet'),
    path('liens-meet/ajouter/', views.lien_meet_ajouter, name='admin_lien_meet_ajouter'),
    path('liens-meet/<int:lien_id>/toggle/', views.lien_meet_toggle, name='admin_lien_meet_toggle'),
    path('liens-meet/attribuer/<int:groupe_id>/', views.lien_meet_attribuer_groupe, name='admin_lien_meet_attribuer_groupe'),
]