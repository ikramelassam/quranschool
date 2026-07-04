from django.urls import path
from . import views

urlpatterns = [
    # Dashboards principaux
    path('eleve/', views.dashboard_eleve, name='dashboard_eleve'),
    path('prof/', views.dashboard_prof, name='dashboard_prof'),
    path('superviseur/', views.dashboard_superviseur, name='dashboard_superviseur'),
    path('admin/', views.dashboard_admin, name='dashboard_admin'),

    # Élève
    path('eleve/seances/', views.eleve_seances, name='eleve_seances'),
    path('eleve/profil/', views.eleve_profil, name='eleve_profil'),

    # Prof
    path('prof/groupes/', views.prof_groupes, name='prof_groupes'),
    path('prof/groupes/<int:groupe_id>/', views.prof_groupe_detail, name='prof_groupe_detail'),
    path('prof/seances/', views.prof_seances, name='prof_seances'),
    path('prof/seances/<int:seance_id>/', views.prof_seance_detail, name='prof_seance_detail'),
    path('prof/seances/<int:seance_id>/presence/', views.prof_presence_sauvegarder, name='prof_presence_sauvegarder'),
    path('prof/emploi/', views.prof_emploi, name='prof_emploi'),

    # Superviseur
    path('superviseur/seance/<int:seance_id>/', views.superviseur_seance_detail, name='superviseur_seance_detail'),

    # Admin — inscriptions
    path('admin/inscriptions/', views.admin_inscriptions, name='admin_inscriptions'),
    path('admin/inscriptions/eleve/<int:inscription_id>/', views.admin_inscription_eleve_detail, name='admin_inscription_eleve_detail'),
    path('admin/inscriptions/eleve/<int:inscription_id>/valider/', views.admin_valider_eleve, name='admin_valider_eleve'),
    path('admin/inscriptions/eleve/<int:inscription_id>/rejeter/', views.admin_rejeter_eleve, name='admin_rejeter_eleve'),
    path('admin/inscriptions/profs/', views.admin_inscriptions_profs, name='admin_inscriptions_profs'),
    path('admin/inscriptions/prof/<int:inscription_id>/', views.admin_inscription_prof_detail, name='admin_inscription_prof_detail'),
    path('admin/inscriptions/prof/<int:inscription_id>/valider/', views.admin_valider_prof, name='admin_valider_prof'),
    path('admin/inscriptions/prof/<int:inscription_id>/rejeter/', views.admin_rejeter_prof, name='admin_rejeter_prof'),

    # Admin — gestion
    path('admin/eleves/', views.admin_eleves, name='admin_eleves'),
    path('admin/eleves/<int:eleve_id>/', views.admin_eleve_detail, name='admin_eleve_detail'),
    path('admin/profs/', views.admin_profs, name='admin_profs'),
    path('admin/profs/<int:prof_id>/', views.admin_prof_detail, name='admin_prof_detail'),
    path('admin/seances/', views.admin_seances, name='admin_seances'),
    path('admin/seances/<int:seance_id>/annuler/', views.admin_seance_annuler, name='admin_seance_annuler'),
    path('admin/seances/<int:seance_id>/deplacer/', views.admin_seance_deplacer, name='admin_seance_deplacer'),
    path('admin/calendrier/', views.admin_calendrier, name='admin_calendrier'),
]
