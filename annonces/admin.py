from django.contrib import admin

from .models import Annonce, LectureAnnonce


@admin.register(Annonce)
class AnnonceAdmin(admin.ModelAdmin):
    list_display = ('titre', 'cible', 'active', 'cree_par', 'date_creation')
    list_filter = ('cible', 'active')
    search_fields = ('titre', 'contenu')


admin.site.register(LectureAnnonce)
