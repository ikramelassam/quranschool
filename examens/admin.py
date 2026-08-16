from django.contrib import admin

from .models import ChoixQuestion, Copie, Examen, Question, Reponse


class ChoixQuestionInline(admin.TabularInline):
    model = ChoixQuestion
    extra = 0


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0
    show_change_link = True


@admin.register(Examen)
class ExamenAdmin(admin.ModelAdmin):
    list_display = ('titre', 'groupe', 'prof', 'statut', 'date_debut', 'date_limite', 'duree_minutes')
    list_filter = ('statut',)
    search_fields = ('titre', 'groupe__nom')
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('examen', 'ordre', 'type_question', 'enonce', 'points')
    list_filter = ('type_question',)
    inlines = [ChoixQuestionInline]


@admin.register(Copie)
class CopieAdmin(admin.ModelAdmin):
    list_display = ('examen', 'eleve', 'statut', 'date_debut', 'date_soumission', 'note_totale')
    list_filter = ('statut', 'soumission_automatique')
    search_fields = ('eleve__user__first_name', 'eleve__user__last_name', 'examen__titre')
    readonly_fields = [f.name for f in Copie._meta.fields]


@admin.register(Reponse)
class ReponseAdmin(admin.ModelAdmin):
    list_display = ('copie', 'question', 'statut_correction', 'points_obtenus')
    list_filter = ('statut_correction',)
    readonly_fields = [f.name for f in Reponse._meta.fields]
