from django.urls import path
from . import views

urlpatterns = [
    # Dashboards principaux
    path('eleve/', views.dashboard_eleve, name='dashboard_eleve'),
    path('prof/', views.dashboard_prof, name='dashboard_prof'),
    path('superviseur/', views.dashboard_superviseur, name='dashboard_superviseur'),
    path('admin/', views.dashboard_admin, name='dashboard_admin'),
    path('mshrif/', views.dashboard_mshrif, name='dashboard_mshrif'),

    # Élève
    path('eleve/seances/', views.eleve_seances, name='eleve_seances'),
    path('eleve/seances/<int:presence_id>/', views.eleve_seance_detail, name='eleve_seance_detail'),
    path('eleve/profil/', views.eleve_profil, name='eleve_profil'),
    path('eleve/profs/<int:prof_id>/', views.eleve_prof_detail, name='eleve_prof_detail'),
    path('eleve/progression/', views.eleve_progression, name='eleve_progression'),

    # Prof
    path('prof/groupes/', views.prof_groupes, name='prof_groupes'),
    path('prof/groupes/<int:groupe_id>/', views.prof_groupe_detail, name='prof_groupe_detail'),
    path('prof/seances/', views.prof_seances, name='prof_seances'),
    path('prof/seances/<int:seance_id>/', views.prof_seance_detail, name='prof_seance_detail'),
    path('prof/seances/<int:seance_id>/presence/', views.prof_presence_sauvegarder, name='prof_presence_sauvegarder'),
    path('prof/emploi/', views.prof_emploi, name='prof_emploi'),
    path('prof/disponibilites/', views.prof_disponibilites, name='prof_disponibilites'),
    path('prof/profil/', views.prof_profil, name='prof_profil'),
    path('prof/remuneration/', views.prof_remuneration, name='prof_remuneration'),
    path('prof/charte/', views.prof_charte, name='prof_charte'),

    # Superviseur
    path('superviseur/seance/<int:seance_id>/', views.superviseur_seance_detail, name='superviseur_seance_detail'),
    path('superviseur/profil/', views.superviseur_profil, name='superviseur_profil'),
    path('superviseur/profs/<int:prof_id>/', views.superviseur_prof_detail, name='superviseur_prof_detail'),

    # Admin — inscriptions
    path('admin/inscriptions/', views.admin_inscriptions, name='admin_inscriptions'),
    path('admin/inscriptions/eleve/<int:inscription_id>/', views.admin_inscription_eleve_detail, name='admin_inscription_eleve_detail'),
    path('admin/inscriptions/eleve/<int:inscription_id>/valider/', views.admin_valider_eleve, name='admin_valider_eleve'),
    path('admin/inscriptions/eleve/<int:inscription_id>/rejeter/', views.admin_rejeter_eleve, name='admin_rejeter_eleve'),
    path('admin/inscriptions/prof/<int:inscription_id>/', views.admin_inscription_prof_detail, name='admin_inscription_prof_detail'),
    path('admin/inscriptions/prof/<int:inscription_id>/valider/', views.admin_valider_prof, name='admin_valider_prof'),
    path('admin/inscriptions/prof/<int:inscription_id>/rejeter/', views.admin_rejeter_prof, name='admin_rejeter_prof'),
    path('admin/users/<int:user_id>/supprimer-orphelin/', views.admin_supprimer_user_orphelin, name='admin_supprimer_user_orphelin'),

    # المشرف — validation finale des candidatures profs (étape 2/2)
    path('mshrif/candidatures-profs/', views.mshrif_inscriptions_profs, name='mshrif_inscriptions_profs'),
    path('mshrif/candidatures-profs/<int:inscription_id>/', views.mshrif_inscription_prof_detail, name='mshrif_inscription_prof_detail'),
    path('mshrif/candidatures-profs/<int:inscription_id>/valider/', views.mshrif_valider_prof_final, name='mshrif_valider_prof_final'),
    path('mshrif/candidatures-profs/<int:inscription_id>/rejeter/', views.mshrif_rejeter_prof, name='mshrif_rejeter_prof'),
    path('mshrif/remuneration/', views.mshrif_remuneration, name='mshrif_remuneration'),
    path('mshrif/charte/', views.mshrif_charte, name='mshrif_charte'),

    # Admin — gestion
    path('admin/eleves/', views.admin_eleves, name='admin_eleves'),
    path('admin/eleves/<int:eleve_id>/', views.admin_eleve_detail, name='admin_eleve_detail'),
    path('admin/eleves/<int:eleve_id>/disponibilites/', views.admin_eleve_disponibilites, name='admin_eleve_disponibilites'),
    path('admin/profs/', views.admin_profs, name='admin_profs'),
    path('admin/profs/<int:prof_id>/', views.admin_prof_detail, name='admin_prof_detail'),
    path('admin/profs/<int:prof_id>/disponibilites/', views.admin_prof_disponibilites, name='admin_prof_disponibilites'),
    path('admin/profs/<int:prof_id>/majoration/', views.admin_prof_majoration_modifier, name='admin_prof_majoration_modifier'),
    path('admin/demandes-disponibilite/', views.admin_demandes_disponibilite, name='admin_demandes_disponibilite'),
    path('admin/demandes-disponibilite/<int:demande_id>/approuver/', views.admin_demande_disponibilite_approuver, name='admin_demande_disponibilite_approuver'),
    path('admin/demandes-disponibilite/<int:demande_id>/rejeter/', views.admin_demande_disponibilite_rejeter, name='admin_demande_disponibilite_rejeter'),
    path('admin/seances/', views.admin_seances, name='admin_seances'),
    path('admin/seances/<int:seance_id>/annuler/', views.admin_seance_annuler, name='admin_seance_annuler'),
    path('admin/seances/<int:seance_id>/deplacer/', views.admin_seance_deplacer, name='admin_seance_deplacer'),
    path('admin/calendrier/', views.admin_calendrier, name='admin_calendrier'),

    # Admin — paramètres (tarifs)
    path('admin/parametres/abonnements/', views.admin_parametres_abonnements, name='admin_parametres_abonnements'),
    path('admin/parametres/abonnements/ajouter/', views.admin_abonnement_ajouter, name='admin_abonnement_ajouter'),
    path('admin/parametres/abonnements/<int:abonnement_id>/modifier/', views.admin_abonnement_modifier, name='admin_abonnement_modifier'),
    path('admin/parametres/abonnements/<int:abonnement_id>/toggle/', views.admin_abonnement_toggle, name='admin_abonnement_toggle'),

    # Admin — grille tarifaire de rémunération des profs
    path('admin/parametres/remuneration/', views.admin_tarifs_remuneration, name='admin_tarifs_remuneration'),
    path('admin/parametres/remuneration/<int:tarif_id>/modifier/', views.admin_tarif_remuneration_modifier, name='admin_tarif_remuneration_modifier'),

    # Admin — critères d'évaluation (superviseur)
    path('admin/criteres/', views.admin_criteres, name='admin_criteres'),
    path('admin/criteres/ajouter/', views.admin_critere_ajouter, name='admin_critere_ajouter'),
    path('admin/criteres/<int:critere_id>/modifier/', views.admin_critere_modifier, name='admin_critere_modifier'),
    path('admin/criteres/<int:critere_id>/toggle/', views.admin_critere_toggle, name='admin_critere_toggle'),
    path('admin/criteres/<int:critere_id>/supprimer/', views.admin_critere_supprimer, name='admin_critere_supprimer'),

    # Admin — vue centralisée des évaluations
    path('admin/evaluations/', views.admin_evaluations, name='admin_evaluations'),
    path('admin/evaluations/seance/<int:seance_id>/', views.admin_evaluation_detail, name='admin_evaluation_detail'),

    # Classement mensuel des profs (مؤطر/superviseur + مدير/admin uniquement)
    path('classement-mensuel/', views.classement_mensuel_profs, name='classement_mensuel_profs'),
    path('classement-mensuel/<int:prof_id>/commentaire/', views.classement_mensuel_commentaire, name='classement_mensuel_commentaire'),

    # Admin — assignation superviseurs ↔ profs
    path('admin/superviseurs/', views.admin_superviseurs, name='admin_superviseurs'),
    path('admin/superviseurs/ajouter/', views.admin_superviseur_ajouter, name='admin_superviseur_ajouter'),
    path('admin/superviseurs/<int:superviseur_id>/assignations/', views.admin_superviseur_assignations, name='admin_superviseur_assignations'),

    # Admin — modification d'email (n'importe quel utilisateur) et compte admin
    path('admin/utilisateurs/<int:user_id>/modifier-email/', views.admin_utilisateur_modifier_email, name='admin_utilisateur_modifier_email'),
    path('admin/mon-compte/', views.admin_mon_compte, name='admin_mon_compte'),

    # Bilans mensuels élèves (prof: saisie ; مدير/مؤطر/مشرف: lecture seule)
    path('prof/bilans/', views.prof_bilans_mensuels, name='prof_bilans_mensuels'),
    path('bilans/', views.bilans_mensuels, name='bilans_mensuels'),
    path('bilans/<int:eleve_id>/<str:mois>/', views.bilan_mensuel_detail, name='bilan_mensuel_detail'),
]
