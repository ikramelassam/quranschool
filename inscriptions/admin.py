from django.contrib import admin
from .models import GrillePrixAbonnement, InscriptionEleve, InscriptionProf, TypeAbonnement

admin.site.register(InscriptionEleve)
admin.site.register(InscriptionProf)
admin.site.register(TypeAbonnement)
admin.site.register(GrillePrixAbonnement)
