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

    # Tâche du 2026-08-07 — URLs publiques d'inscription renommées en anglais,
    # propres et mémorisables (demande explicite du client). Montées ici, à la
    # racine, plutôt que sous /inscriptions/ : ce sont les 2 SEULES routes
    # concernées, le reste du parcours (formulaire élève, confirmation) reste
    # inchangé sous /inscriptions/. name= identique aux routes déjà utilisées
    # partout via {% url 'inscription_prof' %}/{% url 'inscription_eleve_choix' %}
    # — aucun template à modifier, la résolution suit automatiquement le nom.
    # Les anciennes URLs /inscriptions/prof/ et /inscriptions/eleve/choix/
    # redirigent (301, voir inscriptions/urls.py) vers celles-ci, au cas où
    # elles auraient déjà été partagées.
    path('register/teacher', inscriptions_views.inscription_prof, name='inscription_prof'),
    path('register/student', inscriptions_views.inscription_eleve_choix, name='inscription_eleve_choix'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
