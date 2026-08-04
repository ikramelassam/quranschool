from django.db import migrations


# Correspondance exacte avec les libellés déjà utilisés dans les templates
# (prof_seance_detail.html, bilans_mensuels.html) pour les 4 anciens champs
# fixes — Tâche du 2026-08-04 (Point 7).
CRITERES_INITIAUX = [
    ('note_hifz', 'الحفظ', 1),
    ('note_muraja3a', 'المراجعة', 2),
    ('note_tilawa', 'التلاوة', 3),
    ('note_mouwazaba', 'المواظبة والسلوك', 4),
]


def seed_et_backfill(apps, schema_editor):
    CritereEleve = apps.get_model('courses', 'CritereEleve')
    NotePresence = apps.get_model('courses', 'NotePresence')
    Presence = apps.get_model('courses', 'Presence')

    criteres_par_champ = {}
    for champ, nom_ar, ordre in CRITERES_INITIAUX:
        critere = CritereEleve.objects.create(nom_ar=nom_ar, ordre=ordre, est_actif=True)
        criteres_par_champ[champ] = critere

    # Backfill : une ligne NotePresence par (Presence, critère) SEULEMENT si
    # l'ancien champ fixe correspondant n'est pas NULL -- aucune valeur
    # inventée, aucune perte (les 4 champs fixes restent en base, en lecture
    # seule, comme note_memorisation/note_revision avant eux).
    a_creer = []
    for p in Presence.objects.all().iterator():
        for champ, critere in criteres_par_champ.items():
            valeur = getattr(p, champ)
            if valeur is not None:
                a_creer.append(NotePresence(presence=p, critere=critere, note=valeur))
    NotePresence.objects.bulk_create(a_creer, batch_size=500)


def revert(apps, schema_editor):
    CritereEleve = apps.get_model('courses', 'CritereEleve')
    # NotePresence est supprimé en cascade avec CritereEleve.
    CritereEleve.objects.filter(nom_ar__in=[c[1] for c in CRITERES_INITIAUX]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0021_critereeleve_notepresence'),
    ]

    operations = [
        migrations.RunPython(seed_et_backfill, revert),
    ]
