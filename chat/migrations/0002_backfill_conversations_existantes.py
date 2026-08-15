from django.db import migrations


def creer_conversations_manquantes(apps, schema_editor):
    """Backfill (Point 25 du cahier des charges initial, finding CRITIQUE de
    l'audit du 2026-08-15) : crée une Conversation pour chaque Groupe créé
    AVANT ce chantier — le signal chat.signals.creer_conversation_pour_nouveau_groupe
    ne se déclenche qu'à la création (post_save created=True), jamais
    rétroactivement pour les lignes déjà en base.

    Utilise les modèles HISTORIQUES (apps.get_model), pas les vrais modèles
    applicatifs — bonne pratique standard pour les migrations de données,
    afin de ne jamais dépendre d'un code métier qui pourrait changer de forme
    plus tard indépendamment de cette migration (voir aussi
    chat.services.backfiller_conversations_manquantes, qui réplique la même
    logique simple mais avec les vrais modèles, pour rester testable/
    réutilisable en dehors du contexte d'une migration).

    Idempotent : filtre sur conversation__isnull=True (donc un 2e passage ne
    retrouve plus aucune ligne à traiter) ET get_or_create par sécurité
    supplémentaire ; la contrainte UNIQUE sur Conversation.groupe (OneToOneField,
    migration 0001) empêche de toute façon tout doublon réel en base."""
    Groupe = apps.get_model('courses', 'Groupe')
    Conversation = apps.get_model('chat', 'Conversation')
    for groupe in Groupe.objects.filter(conversation__isnull=True):
        Conversation.objects.get_or_create(groupe=groupe)


def ne_rien_faire_au_retour_arriere(apps, schema_editor):
    """Migration inverse volontairement no-op : on ne supprime JAMAIS de
    Conversation (et donc jamais l'historique des messages qu'elle contient)
    en revenant en arrière sur cette migration — même principe que le reste
    du projet, où aucune migration ne fait disparaître de données réelles
    au reverse."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(creer_conversations_manquantes, ne_rien_faire_au_retour_arriere),
    ]
