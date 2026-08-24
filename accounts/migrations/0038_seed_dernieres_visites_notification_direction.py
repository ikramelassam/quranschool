from django.db import migrations
from django.utils import timezone


# Même clé que dashboard.notifications.notifications_direction
# ('demandes_inscription') — dupliquée ici en dur, jamais importée depuis le
# code applicatif réel (même principe que accounts/migrations/
# 0037_seed_dernieres_visites_notification.py, qui a établi ce patron pour
# eleve/prof).
CLE_DIRECTION = 'demandes_inscription'


def seed_baseline(apps, schema_editor):
    """Amorce DerniereVisiteNotification à MAINTENANT pour tous les comptes
    admin/mshrif DÉJÀ existants — évite qu'ils voient d'un coup, le jour de
    l'extension du panneau 🔔 الإشعارات à leur rôle (chantier du 2026-08-24),
    TOUTES les candidatures déjà en attente (potentiellement anciennes)
    réinterprétées comme "nouvelles". Les comptes créés APRÈS cette migration
    n'en ont pas besoin : dashboard.notifications._seuils() amorce alors à
    user.date_joined, ce qui est correct pour eux (voir sa docstring)."""
    User = apps.get_model('accounts', 'User')
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')

    maintenant = timezone.now()
    a_creer = [
        DerniereVisiteNotification(user_id=user_id, cle=CLE_DIRECTION, date_visite=maintenant)
        for user_id in User.objects.filter(role__in=['admin', 'mshrif']).values_list('id', flat=True).iterator()
    ]
    DerniereVisiteNotification.objects.bulk_create(a_creer, batch_size=500, ignore_conflicts=True)


def revert(apps, schema_editor):
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')
    DerniereVisiteNotification.objects.filter(cle=CLE_DIRECTION).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0037_seed_dernieres_visites_notification'),
    ]

    operations = [
        migrations.RunPython(seed_baseline, revert),
    ]
