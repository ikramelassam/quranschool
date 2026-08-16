from django.urls import path

from . import views

urlpatterns = [
    # Prof — gestion
    path('prof/', views.prof_examens_liste, name='examens_prof_liste'),
    path('prof/ajouter/', views.examen_ajouter, name='examens_prof_ajouter'),
    path('prof/<int:examen_id>/', views.examen_detail, name='examens_prof_detail'),
    path('prof/<int:examen_id>/modifier/', views.examen_modifier, name='examens_prof_modifier'),
    path('prof/<int:examen_id>/publier/', views.examen_publier, name='examens_prof_publier'),
    path('prof/<int:examen_id>/fermer/', views.examen_fermer, name='examens_prof_fermer'),
    path('prof/<int:examen_id>/copies/', views.examen_copies, name='examens_prof_copies'),

    # Prof — questions
    path('prof/<int:examen_id>/questions/ajouter/', views.question_ajouter, name='examens_question_ajouter'),
    path('prof/questions/<int:question_id>/modifier/', views.question_modifier, name='examens_question_modifier'),
    path('prof/questions/<int:question_id>/supprimer/', views.question_supprimer, name='examens_question_supprimer'),
    path('prof/questions/<int:question_id>/monter/', views.question_monter, name='examens_question_monter'),
    path('prof/questions/<int:question_id>/descendre/', views.question_descendre, name='examens_question_descendre'),

    # Prof — correction
    path('prof/copies/<int:copie_id>/', views.copie_correction, name='examens_copie_correction'),

    # Élève
    path('mes-examens/', views.eleve_examens_liste, name='examens_eleve_liste'),
    path('<int:examen_id>/avant/', views.eleve_examen_avant, name='examens_eleve_avant'),
    path('copie/<int:copie_id>/passer/', views.examen_passage, name='examens_passage'),
    path('copie/<int:copie_id>/questions/<int:question_id>/autosave/', views.reponse_autosave, name='examens_reponse_autosave'),
    path('copie/<int:copie_id>/soumettre/', views.examen_soumettre, name='examens_soumettre'),
    path('copie/<int:copie_id>/resultat/', views.eleve_copie_resultat, name='examens_eleve_resultat'),

    # Audio protégé (tous rôles avec accès examens)
    path('reponse/<int:reponse_id>/audio/', views.reponse_audio, name='examens_reponse_audio'),

    # Consultation — admin / mshrif / superviseur (lecture seule)
    path('consultation/', views.consultation_examens_liste, name='examens_consultation_liste'),
    path('consultation/<int:examen_id>/', views.consultation_examen_detail, name='examens_consultation_detail'),
    path('consultation/copie/<int:copie_id>/', views.consultation_copie_detail, name='examens_consultation_copie'),
]
