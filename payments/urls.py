from django.urls import path
from . import views

urlpatterns = [
    path('eleve/', views.eleve_paiements, name='eleve_paiements'),
    path('admin/', views.admin_paiements, name='admin_paiements'),
    path('admin/<int:paiement_id>/', views.admin_paiement_detail, name='admin_paiement_detail'),
    path('admin/<int:paiement_id>/valider/', views.admin_paiement_valider, name='admin_paiement_valider'),
    path('admin/<int:paiement_id>/rejeter/', views.admin_paiement_rejeter, name='admin_paiement_rejeter'),
]
