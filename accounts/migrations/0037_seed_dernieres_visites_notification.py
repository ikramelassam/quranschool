from django.db import migrations
from django.utils import timezone


# Mêmes clés que dashboard.notifications (examens/notes_seances/cartable
# côté élève, evaluations_recues/hakiba côté prof) — dupliquées ici en dur
# car une migration de données ne doit JAMAIS importer le code applicatif
# réel (celui-ci pourrait changer plus tard sans que cette migration figée
# dans l'historique ne bouge — bonne pratique Django, même principe que
# chat/migrations/0002_backfill_conversations_existantes.py).
CLES_ELEVE = ('examens', 'notes_seances', 'cartable')
CLES_PROF = ('evaluations_recues', 'hakiba')


def seed_baseline(apps, schema_editor):
    """Amorce DerniereVisiteNotification à MAINTENANT (date du déploiement)
    pour tous les comptes eleve/prof DÉJÀ existants — évite qu'ils voient
    d'un coup, le jour de la mise en service du panneau 🔔 الإشعارات, tout
    leur historique déjà ancien (examens déjà publiés, notes déjà mises,
    fichiers déjà déposés...) réinterprété comme "nouveau". Les comptes créés
    APRÈS cette migration n'en ont pas besoin : dashboard.notifications.
    _seuils() amorce alors à user.date_joined, ce qui est correct pour eux
    (voir sa docstring pour la distinction entre les deux cas)."""
    User = apps.get_model('accounts', 'User')
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')

    maintenant = timezone.now()
    a_creer = []
    for user_id in User.objects.filter(role='eleve').values_list('id', flat=True).iterator():
        a_creer.extend(
            DerniereVisiteNotification(user_id=user_id, cle=cle, date_visite=maintenant)
            for cle in CLES_ELEVE
        )
    for user_id in User.objects.filter(role='prof').values_list('id', flat=True).iterator():
        a_creer.extend(
            DerniereVisiteNotification(user_id=user_id, cle=cle, date_visite=maintenant)
            for cle in CLES_PROF
        )
    DerniereVisiteNotification.objects.bulk_create(a_creer, batch_size=500, ignore_conflicts=True)


def revert(apps, schema_editor):
    DerniereVisiteNotification = apps.get_model('accounts', 'DerniereVisiteNotification')
    DerniereVisiteNotification.objects.filter(cle__in=CLES_ELEVE + CLES_PROF).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0036_alter_superviseur_options_dernierevisitenotification'),
    ]

    operations = [
        migrations.RunPython(seed_baseline, revert),
    ]
