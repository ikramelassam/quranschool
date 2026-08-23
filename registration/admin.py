from django.contrib import admin
from .models import (
    ChampInscription,
    Critere,
    CritereOption,
    EtapeInscription,
    GroupeCritereValeur,
    PresentationInscription,
    ReponseInscription,
)

# Django Admin natif enregistré ici pour usage technique/débogage uniquement — la
# vraie interface de configuration, utilisée par مدير/مشرف au quotidien, est le
# dashboard custom (voir dashboard/views.py, Étape 5 du chantier), pas /admin/.
# Même principe que courses/admin.py et inscriptions/admin.py.
admin.site.register(Critere)
admin.site.register(CritereOption)
admin.site.register(EtapeInscription)
admin.site.register(ChampInscription)
admin.site.register(ReponseInscription)
admin.site.register(GroupeCritereValeur)
admin.site.register(PresentationInscription)
