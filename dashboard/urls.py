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
    path('eleve/demande-changement-halaka/', views.eleve_demande_changement_halaka, name='eleve_demande_changement_halaka'),
    path('eleve/profs/<int:prof_id>/', views.eleve_prof_detail, name='eleve_prof_detail'),
    path('eleve/progression/', views.eleve_progression, name='eleve_progression'),
    path('eleve/cartable/', views.eleve_cartable, name='eleve_cartable'),

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
    path('prof/hakiba/', views.prof_hakiba, name='prof_hakiba'),
    path('programme-general/', views.programme_general_detail, name='programme_general_detail'),

    # Superviseur
    path('superviseur/seance/<int:seance_id>/', views.superviseur_seance_detail, name='superviseur_seance_detail'),
    path('superviseur/profil/', views.superviseur_profil, name='superviseur_profil'),
    path('superviseur/profs/<int:prof_id>/', views.superviseur_prof_detail, name='superviseur_prof_detail'),
    path('superviseur/groupes/<int:groupe_id>/', views.superviseur_groupe_detail, name='superviseur_groupe_detail'),
    path('superviseur/hakiba/', views.superviseur_hakiba, name='superviseur_hakiba'),

    # Confirmation partagée après création de compte (élève ou prof)
    path('admin/confirmation-compte/', views.confirmation_creation_compte, name='confirmation_creation_compte'),

    # Écran partagé post-refus (élève ou prof, étape 1 ou 2) — affiché
    # SEULEMENT après confirmation en base (voir refus_confirme).
    path('admin/refus-confirme/', views.refus_confirme, name='refus_confirme'),

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
    path('admin/profs/<int:prof_id>/remuneration/', views.admin_prof_remuneration_detail, name='admin_prof_remuneration_detail'),
    path('mshrif/charte/', views.mshrif_charte, name='mshrif_charte'),
    path('mshrif/logo/', views.mshrif_logo, name='mshrif_logo'),

    # Admin — gestion
    path('admin/eleves/', views.admin_eleves, name='admin_eleves'),
    path('admin/eleves/<int:eleve_id>/', views.admin_eleve_detail, name='admin_eleve_detail'),
    path('admin/eleves/<int:eleve_id>/disponibilites/', views.admin_eleve_disponibilites, name='admin_eleve_disponibilites'),
    path('admin/eleves/<int:eleve_id>/suspendre/', views.admin_eleve_suspendre, name='admin_eleve_suspendre'),
    path('admin/eleves/<int:eleve_id>/reactiver/', views.admin_eleve_reactiver, name='admin_eleve_reactiver'),
    path('admin/eleves/<int:eleve_id>/archiver/', views.admin_eleve_archiver, name='admin_eleve_archiver'),
    path('admin/eleves/<int:eleve_id>/supprimer-definitivement/', views.eleve_supprimer_definitivement, name='eleve_supprimer_definitivement'),
    path('admin/cartable-eleve/', views.admin_eleve_cartable_gestion, name='admin_eleve_cartable_gestion'),
    path('admin/cartable-eleve/ajouter/', views.admin_eleve_cartable_ajouter, name='admin_eleve_cartable_ajouter'),
    path('admin/cartable/<int:document_id>/supprimer/', views.admin_eleve_cartable_supprimer, name='admin_eleve_cartable_supprimer'),
    path('admin/profs/', views.admin_profs, name='admin_profs'),
    path('admin/profs/<int:prof_id>/', views.admin_prof_detail, name='admin_prof_detail'),
    path('admin/profs/<int:prof_id>/infos-complementaires/', views.admin_prof_infos_complementaires_modifier, name='admin_prof_infos_complementaires_modifier'),
    path('admin/profs/<int:prof_id>/presentation/', views.admin_prof_presentation_modifier, name='admin_prof_presentation_modifier'),
    path('admin/hakiba/', views.admin_hakiba_gestion, name='admin_hakiba_gestion'),
    path('admin/hakiba/ajouter/', views.admin_hakiba_ajouter, name='admin_hakiba_ajouter'),
    path('admin/hakiba/<int:element_id>/supprimer/', views.admin_hakiba_supprimer, name='admin_hakiba_supprimer'),
    path('admin/profs/<int:prof_id>/donnees-actuelles/modifier/', views.admin_prof_donnees_actuelles_modifier, name='admin_prof_donnees_actuelles_modifier'),
    path('admin/profs/<int:prof_id>/disponibilites/', views.admin_prof_disponibilites, name='admin_prof_disponibilites'),
    path('admin/profs/<int:prof_id>/majoration/', views.admin_prof_majoration_modifier, name='admin_prof_majoration_modifier'),
    path('admin/profs/<int:prof_id>/archiver/', views.admin_prof_archiver, name='admin_prof_archiver'),
    path('admin/profs/<int:prof_id>/reactiver/', views.admin_prof_reactiver, name='admin_prof_reactiver'),
    path('admin/profs/<int:prof_id>/supprimer-definitivement/', views.prof_supprimer_definitivement, name='prof_supprimer_definitivement'),
    path('admin/demandes-disponibilite/', views.admin_demandes_disponibilite, name='admin_demandes_disponibilite'),
    path('admin/demandes-disponibilite/<int:demande_id>/approuver/', views.admin_demande_disponibilite_approuver, name='admin_demande_disponibilite_approuver'),
    path('admin/demandes-disponibilite/<int:demande_id>/rejeter/', views.admin_demande_disponibilite_rejeter, name='admin_demande_disponibilite_rejeter'),

    # Fonctionnalité 4 (2026-08-27) — demandes de changement de halaka (élève)
    path('admin/demandes-changement-halaka/', views.admin_demandes_changement_halaka, name='admin_demandes_changement_halaka'),
    path('admin/demandes-changement-halaka/<int:demande_id>/valider/', views.admin_demande_changement_halaka_valider, name='admin_demande_changement_halaka_valider'),
    path('admin/demandes-changement-halaka/<int:demande_id>/refuser/', views.admin_demande_changement_halaka_refuser, name='admin_demande_changement_halaka_refuser'),
    path('admin/seances/', views.admin_seances, name='admin_seances'),
    path('admin/seances/<int:seance_id>/annuler/', views.admin_seance_annuler, name='admin_seance_annuler'),
    path('admin/seances/<int:seance_id>/deplacer/', views.admin_seance_deplacer, name='admin_seance_deplacer'),
    path('admin/calendrier/', views.admin_calendrier, name='admin_calendrier'),

    # Admin — paramètres (tarifs)
    path('admin/parametres/abonnements/', views.admin_parametres_abonnements, name='admin_parametres_abonnements'),
    path('admin/parametres/abonnements/ajouter/', views.admin_abonnement_ajouter, name='admin_abonnement_ajouter'),
    path('admin/parametres/abonnements/<int:abonnement_id>/modifier/', views.admin_abonnement_modifier, name='admin_abonnement_modifier'),
    path('admin/parametres/abonnements/<int:abonnement_id>/toggle/', views.admin_abonnement_toggle, name='admin_abonnement_toggle'),
    path('admin/parametres/abonnements/<int:abonnement_id>/grille-prix/', views.admin_abonnement_grille_prix, name='admin_abonnement_grille_prix'),

    # Admin — grille tarifaire de rémunération des profs
    path('admin/parametres/remuneration/', views.admin_tarifs_remuneration, name='admin_tarifs_remuneration'),
    path('admin/parametres/remuneration/groupe/ajouter/', views.admin_tarif_remuneration_groupe_ajouter, name='admin_tarif_remuneration_groupe_ajouter'),
    path('admin/parametres/remuneration/groupe/<int:tarif_id>/modifier/', views.admin_tarif_remuneration_groupe_modifier, name='admin_tarif_remuneration_groupe_modifier'),
    path('admin/parametres/remuneration/individuel/<int:tarif_id>/modifier/', views.admin_tarif_remuneration_individuel_modifier, name='admin_tarif_remuneration_individuel_modifier'),

    # Admin — catalogue partagé "عدد الحصص الأسبوعية" (Besoin 1.5)
    path('admin/parametres/options-nb-seances/', views.admin_options_nb_seances, name='admin_options_nb_seances'),
    path('admin/parametres/options-nb-seances/ajouter/', views.admin_option_nb_seances_ajouter, name='admin_option_nb_seances_ajouter'),
    path('admin/parametres/options-nb-seances/<int:option_id>/toggle/', views.admin_option_nb_seances_toggle, name='admin_option_nb_seances_toggle'),

    # Admin — critères d'évaluation (superviseur)
    path('admin/criteres/', views.admin_criteres, name='admin_criteres'),
    path('admin/criteres/ajouter/', views.admin_critere_ajouter, name='admin_critere_ajouter'),
    path('admin/criteres/<int:critere_id>/modifier/', views.admin_critere_modifier, name='admin_critere_modifier'),
    path('admin/criteres/<int:critere_id>/toggle/', views.admin_critere_toggle, name='admin_critere_toggle'),
    path('admin/criteres/<int:critere_id>/supprimer/', views.admin_critere_supprimer, name='admin_critere_supprimer'),

    path('admin/criteres-eleves/', views.admin_criteres_eleves, name='admin_criteres_eleves'),
    path('admin/criteres-eleves/ajouter/', views.admin_critere_eleve_ajouter, name='admin_critere_eleve_ajouter'),
    path('admin/criteres-eleves/<int:critere_id>/modifier/', views.admin_critere_eleve_modifier, name='admin_critere_eleve_modifier'),
    path('admin/criteres-eleves/<int:critere_id>/toggle/', views.admin_critere_eleve_toggle, name='admin_critere_eleve_toggle'),
    path('admin/criteres-eleves/<int:critere_id>/supprimer/', views.admin_critere_eleve_supprimer, name='admin_critere_eleve_supprimer'),

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
    path('admin/superviseurs/<int:superviseur_id>/supprimer-definitivement/', views.superviseur_supprimer_definitivement, name='superviseur_supprimer_definitivement'),

    # Admin — modification d'email (n'importe quel utilisateur) et compte admin
    path('admin/utilisateurs/<int:user_id>/modifier-email/', views.admin_utilisateur_modifier_email, name='admin_utilisateur_modifier_email'),
    path('admin/utilisateurs/confirmation-modification-email/', views.confirmation_modification_email, name='confirmation_modification_email'),
    path('admin/utilisateurs/<int:user_id>/reinitialiser-mot-de-passe/', views.admin_utilisateur_reinitialiser_mot_de_passe, name='admin_utilisateur_reinitialiser_mot_de_passe'),
    path('admin/mon-compte/', views.admin_mon_compte, name='admin_mon_compte'),
    path('mshrif/mon-compte/', views.mshrif_mon_compte, name='mshrif_mon_compte'),
    path('admin/programme-general/', views.admin_programme_general, name='admin_programme_general'),
    path('admin/visibilite-prof/', views.admin_visibilite_prof, name='admin_visibilite_prof'),
    path('admin/gestion-inscriptions/', views.admin_gestion_inscriptions, name='admin_gestion_inscriptions'),
    path('admin/reglage-lien-seance/', views.admin_reglage_lien_seance, name='admin_reglage_lien_seance'),
    path('admin/reglage-retention-chat/', views.admin_reglage_retention_chat, name='admin_reglage_retention_chat'),
    path('seances/<int:seance_id>/rejoindre/', views.rejoindre_seance, name='rejoindre_seance'),

    # Bilans mensuels élèves (prof: saisie ; مدير/مؤطر/مشرف: lecture seule)
    path('prof/evaluations/', views.prof_evaluations, name='prof_evaluations'),
    path('prof/bilans/', views.prof_bilans_mensuels, name='prof_bilans_mensuels'),
    path('bilans/', views.bilans_mensuels, name='bilans_mensuels'),
    path('bilans/groupe/<int:groupe_id>/eleve/<int:eleve_id>/', views.bilans_mensuels_detail_seance, name='bilans_mensuels_detail_seance'),
    path('bilans/<int:eleve_id>/<str:mois>/', views.bilan_mensuel_detail, name='bilan_mensuel_detail'),

    # Tâche du 2026-08-07 : remplace la carte "نسبة الحضور هذا الشهر" (biaisée, voir diagnostic)
    path('suivi-engagement/', views.suivi_engagement_mensuel, name='suivi_engagement_mensuel'),

    # Recherche globale (مدير/مشرف) — Chantier du 2026-08-14
    path('api/recherche-globale/', views.api_recherche_globale, name='api_recherche_globale'),

    # Carnet de notes personnelles (مدير/مشرف sur un profil consulté) — Tâche du 2026-08-18
    path('admin/utilisateurs/<int:user_id>/notes/ajouter/', views.ajouter_note_personnelle, name='ajouter_note_personnelle'),
    path('admin/notes/<int:note_id>/modifier/', views.modifier_note_personnelle, name='modifier_note_personnelle'),
    path('admin/notes/<int:note_id>/supprimer/', views.supprimer_note_personnelle, name='supprimer_note_personnelle'),
    # Bloc-notes personnel "ملاحظاتي" (tous rôles, sur soi-même) — Tâche du 2026-08-18 bis
    path('mes-notes/', views.mes_notes_personnelles, name='mes_notes_personnelles'),
    # Panneau 🔔 الإشعارات — "عرض الكل" (eleve/prof uniquement) — Chantier notifications du 2026-08-19
    path('mes-notifications/', views.mes_notifications, name='mes_notifications'),

    # ==================== MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5A ====================
    # Directeur ET مشرف, accès strictement identique (role_required('admin', 'mshrif')
    # sur chaque vue, voir dashboard/views.py) — pas de hiérarchie entre eux ici.
    path('admin/criteres-inscription/', views.admin_criteres_inscription, name='admin_criteres_inscription'),
    path('admin/criteres-inscription/ajouter/', views.admin_critere_inscription_ajouter, name='admin_critere_inscription_ajouter'),
    path('admin/criteres-inscription/<int:critere_id>/', views.admin_critere_inscription_detail, name='admin_critere_inscription_detail'),
    path('admin/criteres-inscription/<int:critere_id>/modifier/', views.admin_critere_inscription_modifier, name='admin_critere_inscription_modifier'),
    path('admin/criteres-inscription/<int:critere_id>/toggle/', views.admin_critere_inscription_toggle, name='admin_critere_inscription_toggle'),
    path('admin/criteres-inscription/<int:critere_id>/supprimer/', views.admin_critere_inscription_supprimer, name='admin_critere_inscription_supprimer'),
    path('admin/criteres-inscription/<int:critere_id>/detacher-groupe/<int:groupe_id>/', views.admin_critere_inscription_detacher_groupe, name='admin_critere_inscription_detacher_groupe'),
    path('admin/criteres-inscription/<int:critere_id>/options/ajouter/', views.admin_critere_option_ajouter, name='admin_critere_option_ajouter'),
    path('admin/criteres-inscription/options/<int:option_id>/modifier/', views.admin_critere_option_modifier, name='admin_critere_option_modifier'),
    path('admin/criteres-inscription/options/<int:option_id>/toggle/', views.admin_critere_option_toggle, name='admin_critere_option_toggle'),
    path('admin/criteres-inscription/options/<int:option_id>/supprimer/', views.admin_critere_option_supprimer, name='admin_critere_option_supprimer'),

    # ---- Étape 5B : Étapes / Champs / Règles conditionnelles ----
    path('admin/etapes-inscription/', views.admin_etapes_inscription, name='admin_etapes_inscription'),
    path('admin/etapes-inscription/ajouter/', views.admin_etape_inscription_ajouter, name='admin_etape_inscription_ajouter'),
    path('admin/etapes-inscription/<int:etape_id>/', views.admin_etape_inscription_detail, name='admin_etape_inscription_detail'),
    path('admin/etapes-inscription/<int:etape_id>/modifier/', views.admin_etape_inscription_modifier, name='admin_etape_inscription_modifier'),
    path('admin/etapes-inscription/<int:etape_id>/toggle/', views.admin_etape_inscription_toggle, name='admin_etape_inscription_toggle'),
    path('admin/etapes-inscription/<int:etape_id>/supprimer/', views.admin_etape_inscription_supprimer, name='admin_etape_inscription_supprimer'),
    path('admin/etapes-inscription/<int:etape_id>/champs/ajouter/', views.admin_champ_inscription_ajouter, name='admin_champ_inscription_ajouter'),
    path('admin/champs-inscription/<int:champ_id>/modifier/', views.admin_champ_inscription_modifier, name='admin_champ_inscription_modifier'),
    path('admin/champs-inscription/<int:champ_id>/toggle/', views.admin_champ_inscription_toggle, name='admin_champ_inscription_toggle'),
    path('admin/champs-inscription/<int:champ_id>/supprimer/', views.admin_champ_inscription_supprimer, name='admin_champ_inscription_supprimer'),
    path('admin/champs-structurels/<int:config_id>/modifier/', views.admin_champ_structurel_modifier, name='admin_champ_structurel_modifier'),

    # ---- Étape 5C : Moyens de paiement / Présentation de l'inscription ----
    path('admin/moyens-paiement/', views.admin_moyens_paiement, name='admin_moyens_paiement'),
    path('admin/moyens-paiement/ajouter/', views.admin_moyen_paiement_ajouter, name='admin_moyen_paiement_ajouter'),
    path('admin/moyens-paiement/<int:moyen_id>/modifier/', views.admin_moyen_paiement_modifier, name='admin_moyen_paiement_modifier'),
    path('admin/moyens-paiement/<int:moyen_id>/toggle/', views.admin_moyen_paiement_toggle, name='admin_moyen_paiement_toggle'),
    path('admin/presentation-inscription/', views.admin_presentation_inscription, name='admin_presentation_inscription'),
    path('admin/demandes-non-satisfaites/', views.admin_demandes_non_satisfaites, name='admin_demandes_non_satisfaites'),
    path('admin/demandes-non-satisfaites/<int:demande_id>/', views.admin_demande_non_satisfaite_detail, name='admin_demande_non_satisfaite_detail'),
    path('admin/demandes-non-satisfaites/<int:demande_id>/supprimer/', views.admin_demande_non_satisfaite_supprimer, name='admin_demande_non_satisfaite_supprimer'),

    # ---- Étape 7 : ajout manuel d'une candidature élève (Directeur/مشرف) ----
    path('admin/eleves/ajouter-manuel/', views.admin_eleve_ajouter_manuel, name='admin_eleve_ajouter_manuel'),

    # ---- Chantier du 2026-08-27 : ajout manuel d'une candidature prof (مدير/مشرف) ----
    path('admin/profs/ajouter-manuel/', views.admin_prof_ajouter_manuel, name='admin_prof_ajouter_manuel'),
]
