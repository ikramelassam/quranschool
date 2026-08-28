from django.contrib import admin

from .models import AbonneTelegram


@admin.register(AbonneTelegram)
class AbonneTelegramAdmin(admin.ModelAdmin):
    list_display = (
        'chat_id', 'nom', 'telegram_username',
        'est_actif', 'en_attente_validation', 'date_abonnement',
    )
    list_filter = ('est_actif', 'en_attente_validation')
    search_fields = ('chat_id', 'nom', 'telegram_username')
