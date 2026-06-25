
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Eleve, Prof, Superviseur

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Informations supplémentaires', {
            'fields': ('role', 'telephone', 'date_naissance')
        }),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(Eleve)
admin.site.register(Prof)
admin.site.register(Superviseur)