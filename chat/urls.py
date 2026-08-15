from django.urls import path

from . import views

urlpatterns = [
    path('', views.chat_liste, name='chat_liste'),
    path('liste-partielle/', views.chat_liste_partial, name='chat_liste_partial'),
    path('<int:groupe_id>/', views.chat_conversation, name='chat_conversation'),
    path('<int:groupe_id>/panneau/', views.chat_panel, name='chat_panel'),
    path('<int:groupe_id>/messages/', views.chat_messages, name='chat_messages'),
    path('<int:groupe_id>/envoyer/', views.chat_envoyer, name='chat_envoyer'),
    path('<int:groupe_id>/lu/', views.chat_marquer_lu, name='chat_marquer_lu'),
    path('<int:groupe_id>/fichier/<int:message_id>/', views.chat_fichier, name='chat_fichier'),
]
