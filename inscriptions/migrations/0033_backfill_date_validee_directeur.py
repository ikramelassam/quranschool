from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    """Fonctionnalité 3 (2026-08-27, notification مشرف) : les dossiers DÉJÀ
    en 'validee_directeur' au moment de ce déploiement (pré-validés par le
    مدير AVANT que ce chantier n'existe) n'ont jamais eu leur
    date_validee_directeur posée — laissée à NULL, ils resteraient
    invisibles pour toujours dans dashboard.notifications.notifications_
    direction() (un filtre __gt sur NULL n'est jamais vrai), alors qu'ils
    sont bel et bien encore en attente réelle de traitement مشرف.

    Amorcé à timezone.now() (comme accounts/migrations/
    0037_seed_dernieres_visites_notification.py pour le même problème côté
    élève) : ces dossiers apparaissent donc une fois, au prochain calcul du
    panneau 🔔, plutôt que de disparaître silencieusement — pas une
    inondation rétroactive (un seul évènement par dossier réellement en
    attente), à l'opposé du risque que ce module cherche à éviter ailleurs."""
    InscriptionProf = apps.get_model('inscriptions', 'InscriptionProf')
    InscriptionProf.objects.filter(
        statut='validee_directeur', date_validee_directeur__isnull=True,
    ).update(date_validee_directeur=timezone.now())


def revenir_en_arriere(apps, schema_editor):
    # Pas de retour en arrière significatif : on ne sait plus distinguer un
    # dossier amorcé par CETTE migration d'un dossier validé normalement
    # juste après — remettre à NULL romprait le suivi réel. No-op assumé
    # (même principe que d'autres migrations de données de ce projet, ex:
    # inscriptions/migrations/0029_convertir_duree_texte_libre_vers_codes.py).
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('inscriptions', '0032_inscriptionprof_date_validee_directeur'),
    ]

    operations = [
        migrations.RunPython(backfill, revenir_en_arriere),
    ]
