from django.db import migrations

# Ordre/labels reprennent EXACTEMENT ce qui était codé en dur dans
# wizard_identite.html avant ce chantier (2026-08-22) — un seed qui change
# le comportement visible du jour au lendemain serait une régression
# silencieuse, pas une migration neutre. Seul niveau_scolaire est NOUVEAU
# (n'existait pas avant), ajouté à la fin.
CHAMPS_STRUCTURELS = [
    ('nom', 'الاسم الكامل', 1, True),
    ('nom_parent', 'اسم ولي الأمر (إن كان المسجَّل قاصراً)', 2, False),
    ('sexe', 'الجنس', 3, True),
    ('email', 'البريد الإلكتروني', 4, True),
    ('telephone', 'الهاتف', 5, True),
    ('date_naissance', 'تاريخ الميلاد', 6, True),
    ('job_actuel', 'العمل الحالي (أو عمل ولي الأمر إن كان المسجَّل قاصراً)', 7, False),
    ('niveau_scolaire', 'المستوى الدراسي', 8, False),
]


def seed_champs_structurels(apps, schema_editor):
    EtapeInscription = apps.get_model('registration', 'EtapeInscription')
    ConfigurationChampStructurel = apps.get_model('registration', 'ConfigurationChampStructurel')

    etape_identite, _ = EtapeInscription.objects.get_or_create(
        code='identite', defaults={'titre': 'المعلومات الشخصية', 'ordre': 1},
    )
    for champ_cle, label, ordre, obligatoire in CHAMPS_STRUCTURELS:
        ConfigurationChampStructurel.objects.get_or_create(
            champ_cle=champ_cle,
            defaults={
                'label': label, 'ordre': ordre, 'etape': etape_identite,
                'obligatoire': obligatoire, 'est_actif': True,
            },
        )


def retirer_champs_structurels(apps, schema_editor):
    ConfigurationChampStructurel = apps.get_model('registration', 'ConfigurationChampStructurel')
    ConfigurationChampStructurel.objects.filter(
        champ_cle__in=[c[0] for c in CHAMPS_STRUCTURELS]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0003_configurationchampstructurel'),
    ]

    operations = [
        migrations.RunPython(seed_champs_structurels, retirer_champs_structurels),
    ]
