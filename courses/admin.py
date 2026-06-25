from django.contrib import admin
from .models import Groupe, Seance, Disponibilite, Presence, Creneau

admin.site.register(Creneau)
admin.site.register(Groupe)
admin.site.register(Seance)
admin.site.register(Disponibilite)
admin.site.register(Presence)