from django.urls import path
from . import views

urlpatterns = [
    path('seance/<int:seance_id>/evaluer/', views.superviseur_evaluer, name='superviseur_evaluer'),
    path('seance/<int:seance_id>/', views.superviseur_evaluation_detail, name='superviseur_evaluation_detail'),
]
