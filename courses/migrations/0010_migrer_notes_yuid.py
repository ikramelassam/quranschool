from django.db import migrations


def migrer_yuid_vers_doun_mutawassit(apps, schema_editor):
    """L'ancienne échelle à 4 niveaux avait 'يعيد' (yuid) comme note la plus
    basse. La nouvelle échelle à 6 niveaux n'a pas d'équivalent exact — on la
    fait correspondre à 'دون متوسط' (doun_mutawassit), le niveau le plus bas
    de la nouvelle échelle, l'équivalence la plus proche."""
    Presence = apps.get_model('courses', 'Presence')
    Presence.objects.filter(note_memorisation='yuid').update(note_memorisation='doun_mutawassit')
    Presence.objects.filter(note_revision='yuid').update(note_revision='doun_mutawassit')


def revenir_a_yuid(apps, schema_editor):
    """Reverse: recolle 'doun_mutawassit' vers 'yuid'. Approximatif si de
    nouvelles lignes ont été notées 'doun_mutawassit' après cette migration
    (elles seront aussi reversées), mais c'est le seul mapping inverse cohérent."""
    Presence = apps.get_model('courses', 'Presence')
    Presence.objects.filter(note_memorisation='doun_mutawassit').update(note_memorisation='yuid')
    Presence.objects.filter(note_revision='doun_mutawassit').update(note_revision='yuid')


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0009_alter_presence_note_choices'),
    ]

    operations = [
        migrations.RunPython(migrer_yuid_vers_doun_mutawassit, revenir_a_yuid),
    ]
