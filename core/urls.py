"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include, reverse_lazy
from django.views.generic import RedirectView
from inscriptions import views as inscriptions_views
from registration import views as registration_views

urlpatterns = [
    path('', RedirectView.as_view(url=reverse_lazy('login'), permanent=False)),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('dashboard/', include('dashboard.urls')),
    path('inscriptions/', include('inscriptions.urls')),
    path('courses/', include('courses.urls')),
    path('payments/', include('payments.urls')),
    path('evaluations/', include('evaluations.urls')),
    path('chat/', include('chat.urls')),
    path('annonces/', include('annonces.urls')),
    path('examens/', include('examens.urls')),
    path('registration/', include('registration.urls')),
    path('telegram/', include('telegram_bot.urls')),

    # Tâche du 2026-08-07 — URLs publiques d'inscription renommées en anglais,
    # propres et mémorisables (demande explicite du client). Montées ici, à la
    # racine, plutôt que sous /inscriptions/ : ce sont les 2 SEULES routes
    # concernées. name= identique aux routes déjà utilisées partout via
    # {% url 'inscription_prof' %}/{% url 'inscription_eleve_choix' %} — aucun
    # template à modifier, la résolution suit automatiquement le nom. Les
    # anciennes URLs /inscriptions/prof/ et /inscriptions/eleve/choix/
    # redirigent (301, voir inscriptions/urls.py) vers celles-ci, au cas où
    # elles auraient déjà été partagées.
    path('register/teacher', inscriptions_views.inscription_prof, name='inscription_prof'),
    # Bascule du 2026-08-24 (décision explicite du Directeur, voir registration/
    # MIGRATION_NOTES.md) : /register/student pointe désormais vers le NOUVEAU
    # moteur d'inscription configurable (registration.views.wizard_categorie_age
    # — Étape -1 du wizard, بالغ/طفل, même position exacte dans le parcours que
    # l'ancien inscription_eleve_choix qu'il remplace) au lieu de l'ancien
    # formulaire à une page. name='inscription_eleve_choix' VOLONTAIREMENT
    # CONSERVÉ (pas renommé en 'wizard_categorie_age' malgré le nom qui ne
    # correspond plus littéralement à la vue) : c'est ce nom qui est référencé
    # partout (templates/accounts/login.html, la redirection legacy
    # /inscriptions/eleve/choix/) — le conserver évite de toucher un seul
    # template, la résolution suit automatiquement la nouvelle cible.
    #
    # ANCIEN FORMULAIRE (inscriptions.views.inscription_eleve_*, inscriptions/
    # urls.py) : PAS supprimé, laissé DORMANT — décision explicite suivant
    # MIGRATION_NOTES.md ("garder les vues et les URLs en place tant qu'un
    # doute subsiste — les supprimer est une étape séparée, plus tardive").
    # Plus aucun lien public n'y mène (le bouton "التسجيل كطالب" de login.html
    # suit désormais ce name= vers le wizard), mais son code reste intact et
    # instantanément restaurable (il suffit de repointer cette ligne) en cas
    # de souci avec le nouveau parcours.
    path('register/student', registration_views.wizard_categorie_age, name='inscription_eleve_choix'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
