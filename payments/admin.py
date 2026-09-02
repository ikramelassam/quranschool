from django.contrib import admin
from .models import Paiement, CycleAbonnement, ReglageRelanceWhatsApp

admin.site.register(Paiement)
admin.site.register(CycleAbonnement)
admin.site.register(ReglageRelanceWhatsApp)
