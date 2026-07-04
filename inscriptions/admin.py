from django.contrib import admin
from .models import InscriptionEleve, InscriptionProf, DisponibiliteInscription, TypeAbonnement

admin.site.register(InscriptionEleve)
admin.site.register(InscriptionProf)
admin.site.register(DisponibiliteInscription)
admin.site.register(TypeAbonnement)