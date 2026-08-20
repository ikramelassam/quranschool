from django.db import migrations


def remplir_slots_depuis_jour_1_jour_2(apps, schema_editor):
    """Chantier de généralisation N séances/semaine — chaque Creneau existant
    obtient exactement 2 CreneauSlot (ordre=1 depuis le bloc "_1", ordre=2 depuis
    le bloc "_2"), copie fidèle de ce qui existait déjà, ni plus ni moins.
    AUCUNE donnée perdue : les colonnes jour_1/heure_debut_1/heure_fin_1/jour_2/
    heure_debut_2/heure_fin_2 restent intactes en base (suppression = migration
    séparée, plus tard, après validation en production — voir 0035_creneauslot).
    AUCUN Groupe ni Seance n'est touché ici : cette migration ne fait que copier
    des données de planning dans leur nouvelle représentation, elle ne régénère
    rien (etendre_seances n'est jamais appelé).

    Idempotente par construction : filtre explicitement les Creneau qui n'ont
    PAS encore de slots (slots__isnull=True) avant de les créer — un 2e passage
    accidentel de cette migration ne dupliquerait rien.

    Utilise les modèles HISTORIQUES (apps.get_model), même patron que
    0034_backfill_groupe_categorie_depuis_creneau."""
    Creneau = apps.get_model('courses', 'Creneau')
    CreneauSlot = apps.get_model('courses', 'CreneauSlot')

    a_creer = []
    for creneau in Creneau.objects.filter(slots__isnull=True).distinct():
        a_creer.append(CreneauSlot(
            creneau=creneau, ordre=1,
            jour=creneau.jour_1, heure_debut=creneau.heure_debut_1, heure_fin=creneau.heure_fin_1,
        ))
        a_creer.append(CreneauSlot(
            creneau=creneau, ordre=2,
            jour=creneau.jour_2, heure_debut=creneau.heure_debut_2, heure_fin=creneau.heure_fin_2,
        ))
    CreneauSlot.objects.bulk_create(a_creer)


def supprimer_slots_backfilles(apps, schema_editor):
    """Retour arrière : supprime TOUS les CreneauSlot d'ordre 1 ou 2 dont les
    valeurs correspondent encore exactement au jour_1/jour_2 actuel de leur
    Creneau (donc jamais modifiés depuis, ni via une future interface
    d'administration des slots) — ne touche jamais un slot 3+ (impossible à
    produire par cette migration) ni un slot 1/2 déjà édité manuellement, pour
    ne jamais faire disparaître une vraie donnée saisie après coup. Même
    prudence que le reste du projet : mieux vaut un reverse partiel/no-op
    qu'une perte de donnée silencieuse."""
    Creneau = apps.get_model('courses', 'Creneau')
    CreneauSlot = apps.get_model('courses', 'CreneauSlot')

    for creneau in Creneau.objects.all():
        CreneauSlot.objects.filter(
            creneau=creneau, ordre=1, jour=creneau.jour_1,
            heure_debut=creneau.heure_debut_1, heure_fin=creneau.heure_fin_1,
        ).delete()
        CreneauSlot.objects.filter(
            creneau=creneau, ordre=2, jour=creneau.jour_2,
            heure_debut=creneau.heure_debut_2, heure_fin=creneau.heure_fin_2,
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0035_creneauslot'),
    ]

    operations = [
        migrations.RunPython(remplir_slots_depuis_jour_1_jour_2, supprimer_slots_backfilles),
    ]
