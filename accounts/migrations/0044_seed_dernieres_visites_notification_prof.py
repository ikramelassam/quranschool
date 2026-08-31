from django.db import migrations
from django.utils import timezone


# Même clé que dashboard.notifications.notifications_direction
# ('demandes_inscription_prof') — dupliquée ici en dur, jamais importée depuis
# le code applicatif réel (même principe que accounts/migrations/
# 0038_seed_dernieres_visites_notification_direction.py).
CLE = 'demandes_inscription_prof'


def seed_baseline(apps, schema_editor):
    """Amorce DerniereVisiteNotification à MAINTENANT pour tous les comptes
    admin (مدير) DÉJÀ existants — évite qu'ils voient d'un coup, le jour où le
    panneau 🔔 gagne le groupe "طلبات تسجيل أساتذة جديدة", TOUTES les
    candidatures profs déjà en attente (potentiellement anciennes) comme
    "nouvelles". Comptes créés APRÈS cette migration : pas besoin,
    dashboard.notifications._seuils() amorce alors à user.date_joined.

    مدير UNIQUEMENT (jamais 'mshrif') : cette cle est réservée au مدير, seul
    habilité à la pré-validation étape 1 — voir notifications_direction."""
    User = apps.get_model('accounts', 'User')
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')

    maintenant = timezone.now()
    a_creer = [
        DerniereVisiteNotification(user_id=user_id, cle=CLE, date_visite=maintenant)
        for user_id in User.objects.filter(role='admin').values_list('id', flat=True).iterator()
    ]
    DerniereVisiteNotification.objects.bulk_create(a_creer, batch_size=500, ignore_conflicts=True)


def revert(apps, schema_editor):
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')
    DerniereVisiteNotification.objects.filter(cle=CLE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0043_seed_dernieres_visites_notification_superviseur'),
    ]

    operations = [
        migrations.RunPython(seed_baseline, revert),
    ]
