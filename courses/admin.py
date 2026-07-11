from django.contrib import admin
from .models import Groupe, Seance, DisponibiliteProf, DemandeModificationDisponibilite, Presence, Creneau

admin.site.register(Creneau)
admin.site.register(Groupe)
admin.site.register(Seance)
admin.site.register(DisponibiliteProf)
admin.site.register(DemandeModificationDisponibilite)
admin.site.register(Presence)
