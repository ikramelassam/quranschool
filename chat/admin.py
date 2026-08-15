from django.contrib import admin

from .models import Conversation, Message, LectureConversation, ConfigurationChat


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('groupe', 'date_creation')
    search_fields = ('groupe__nom',)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'auteur_nom', 'auteur_role', 'type_message', 'date_envoi')
    list_filter = ('type_message', 'auteur_role')
    search_fields = ('auteur_nom', 'contenu')
    readonly_fields = [f.name for f in Message._meta.fields]


@admin.register(ConfigurationChat)
class ConfigurationChatAdmin(admin.ModelAdmin):
    list_display = ('duree_retention_jours', 'derniere_modification_par', 'date_modification')

    def has_add_permission(self, request):
        # Singleton (comme LogoConfig/CharteEnseignement) : une seule ligne,
        # jamais d'ajout depuis /admin/ au-delà de la première.
        return not ConfigurationChat.objects.exists()


admin.site.register(LectureConversation)
