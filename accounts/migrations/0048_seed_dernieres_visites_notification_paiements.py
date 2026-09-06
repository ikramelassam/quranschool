from django.db import migrations
from django.utils import timezone


# Même clé que dashboard.notifications.notifications_direction
# ('nouveaux_paiements') — dupliquée ici en dur, jamais importée depuis le
# code applicatif réel (même principe que accounts/migrations/
# 0038_seed_dernieres_visites_notification_direction.py).
CLE = 'nouveaux_paiements'


def seed_baseline(apps, schema_editor):
    """Audit du 2026-09-05 (chantier notif paiement du 2026-09-04, commit
    b961b56, oublié à l'époque) — amorce DerniereVisiteNotification à
    MAINTENANT pour tous les comptes admin/mshrif DÉJÀ existants : évite
    qu'ils voient d'un coup, à leur prochaine visite, TOUS les paiements
    encore 'en_attente' déjà en base (potentiellement anciens) réinterprétés
    comme "nouveaux" — même patron que 0038 pour 'demandes_inscription'.
    Comptes créés APRÈS cette migration : pas besoin, dashboard.
    notifications._seuils() amorce alors à user.date_joined."""
    User = apps.get_model('accounts', 'User')
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')

    maintenant = timezone.now()
    a_creer = [
        DerniereVisiteNotification(user_id=user_id, cle=CLE, date_visite=maintenant)
        for user_id in User.objects.filter(role__in=['admin', 'mshrif']).values_list('id', flat=True).iterator()
    ]
    DerniereVisiteNotification.objects.bulk_create(a_creer, batch_size=500, ignore_conflicts=True)


def revert(apps, schema_editor):
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')
    DerniereVisiteNotification.objects.filter(cle=CLE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0047_add_email_btree_index'),
    ]

    operations = [
        migrations.RunPython(seed_baseline, revert),
    ]
