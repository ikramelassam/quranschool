from django.contrib import admin
from .models import InscriptionEleve, InscriptionProf, TypeAbonnement

admin.site.register(InscriptionEleve)
admin.site.register(InscriptionProf)
admin.site.register(TypeAbonnement)
