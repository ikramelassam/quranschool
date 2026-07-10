from django.db import migrations

ANCIENS_CRITERES_TEST = ['الالتزام بالوقت', 'طريقة التدريس']

CRITERES_REELS = [
    (1, 'التمكن من حفظ القرآن برواية ورش'),
    (2, 'التمكن من قواعد التجويد بشقيها النظري والتطبيقي'),
    (3, 'التمكن من تقنيات التهجي وتعليم القراءة'),
    (4, 'ارساء قواعد التجويد اثناء تصحيح التلاوة'),
    (5, 'تصحيح النطق ومخارج الحروف'),
    (6, 'توجيه الطلاب الى التكرار الجماعي والفردي'),
    (7, 'انسجام المتعلمين والمتعلمات داخل الحلقة'),
    (8, 'العناية بملء استمارة التقييم'),
    (9, 'احترام البرنامج'),
    (10, 'مشاركة الشاشة أثناء الشرح'),
    (11, 'القاء درس التجويد'),
    (12, 'القاء درس تربوي'),
    (13, 'توجيه ونصحهم'),
    (14, 'الدخول في الوقت'),
    (15, 'الخروج في الوقت'),
]


def seed_criteres(apps, schema_editor):
    Critere = apps.get_model('evaluations', 'Critere')
    NoteEvaluation = apps.get_model('evaluations', 'NoteEvaluation')

    # Retire les criteres de test, seulement s'ils n'ont jamais ete utilises
    # dans une vraie evaluation (securite: ne jamais casser une note existante).
    for nom in ANCIENS_CRITERES_TEST:
        for critere in Critere.objects.filter(nom_ar=nom):
            if not NoteEvaluation.objects.filter(critere=critere).exists():
                critere.delete()

    for ordre, nom_ar in CRITERES_REELS:
        Critere.objects.get_or_create(
            nom_ar=nom_ar,
            defaults={'ordre': ordre, 'est_actif': True},
        )


def reverse_seed_criteres(apps, schema_editor):
    Critere = apps.get_model('evaluations', 'Critere')
    NoteEvaluation = apps.get_model('evaluations', 'NoteEvaluation')

    noms = [nom_ar for _, nom_ar in CRITERES_REELS]
    for critere in Critere.objects.filter(nom_ar__in=noms):
        if not NoteEvaluation.objects.filter(critere=critere).exists():
            critere.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('evaluations', '0002_critere_est_actif_alter_evaluation_commentaire'),
    ]

    operations = [
        migrations.RunPython(seed_criteres, reverse_seed_criteres),
    ]
