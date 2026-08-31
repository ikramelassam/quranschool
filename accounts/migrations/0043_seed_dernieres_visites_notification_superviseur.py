from django.db import migrations
from django.utils import timezone


# Même clé que dashboard.notifications.notifications_superviseur ('hakiba',
# partagée avec notifications_prof) — dupliquée ici en dur, jamais importée
# depuis le code applicatif réel (même principe que accounts/migrations/
# 0037_seed_dernieres_visites_notification.py, qui a établi ce patron pour
# eleve/prof, et 0038 pour admin/mshrif).
CLE_SUPERVISEUR = 'hakiba'


def seed_baseline(apps, schema_editor):
    """Amorce DerniereVisiteNotification à MAINTENANT pour tous les comptes
    superviseur (مؤطر) DÉJÀ existants — évite qu'ils voient d'un coup, le jour
    de l'extension du panneau 🔔 الإشعارات à leur rôle (chantier du
    2026-08-31), TOUS les éléments déjà déposés dans la حقيبة الأستاذ
    (potentiellement anciens) réinterprétés comme "nouveaux". Les comptes
    créés APRÈS cette migration n'en ont pas besoin : dashboard.notifications.
    _seuils() amorce alors à user.date_joined, ce qui est correct pour eux
    (voir sa docstring).

    NB : 0037 a déjà semé 'hakiba' pour role='prof' uniquement — cette
    migration-ci ne touche que role='superviseur', ignore_conflicts garde
    l'opération idempotente si elle croisait malgré tout une ligne existante."""
    User = apps.get_model('accounts', 'User')
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')

    maintenant = timezone.now()
    a_creer = [
        DerniereVisiteNotification(user_id=user_id, cle=CLE_SUPERVISEUR, date_visite=maintenant)
        for user_id in User.objects.filter(role='superviseur').values_list('id', flat=True).iterator()
    ]
    DerniereVisiteNotification.objects.bulk_create(a_creer, batch_size=500, ignore_conflicts=True)


def revert(apps, schema_editor):
    """Ne supprime QUE les repères 'hakiba' des comptes superviseur — ceux des
    profs (semés par 0037) restent intacts."""
    User = apps.get_model('accounts', 'User')
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')

    ids_superviseurs = User.objects.filter(role='superviseur').values_list('id', flat=True)
    DerniereVisiteNotification.objects.filter(
        cle=CLE_SUPERVISEUR, user_id__in=list(ids_superviseurs)
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0042_remove_documenteleve_eleve_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_baseline, revert),
    ]
