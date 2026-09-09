from django.db import migrations
from django.utils import timezone


# Même clé que dashboard.notifications.notifications_eleve
# ('paiements_acceptes') — dupliquée ici en dur, jamais importée depuis le
# code applicatif réel (même principe que accounts/migrations/
# 0048_seed_dernieres_visites_notification_paiements.py).
CLE = 'paiements_acceptes'


def seed_baseline(apps, schema_editor):
    """Chantier du 2026-09-09 (notif 🔔 « دفعات مقبولة » côté élève, miroir de
    la notif Telegram déplacée du dépôt vers la validation) — amorce
    DerniereVisiteNotification à MAINTENANT pour tous les comptes élève DÉJÀ
    existants : sans ça, dashboard.notifications._seuils() amorcerait à
    user.date_joined et l'élève verrait d'un coup, à sa prochaine visite,
    TOUS ses paiements déjà validés (potentiellement des mois d'historique)
    réinterprétés comme "nouveaux". Même patron que 0048 pour
    'nouveaux_paiements'. Comptes créés APRÈS cette migration : pas besoin,
    _seuils() amorce alors proprement à user.date_joined."""
    User = apps.get_model('accounts', 'User')
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')

    maintenant = timezone.now()
    a_creer = [
        DerniereVisiteNotification(user_id=user_id, cle=CLE, date_visite=maintenant)
        for user_id in User.objects.filter(role='eleve').values_list('id', flat=True).iterator()
    ]
    DerniereVisiteNotification.objects.bulk_create(a_creer, batch_size=500, ignore_conflicts=True)


def revert(apps, schema_editor):
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')
    DerniereVisiteNotification.objects.filter(cle=CLE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0049_programmegeneralparseances'),
    ]

    operations = [
        migrations.RunPython(seed_baseline, revert),
    ]
