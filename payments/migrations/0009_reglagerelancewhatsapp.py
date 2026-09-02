# Generated for the WhatsApp payment-reminder feature (2026-09-02)

from django.db import migrations, models
import django.db.models.deletion

# Copie figée du défaut (patron migration = snapshot) — la source de vérité
# vivante est payments.models.MESSAGE_RELANCE_WHATSAPP_DEFAUT.
MESSAGE_RELANCE_WHATSAPP_DEFAUT = (
    'السلام عليكم ورحمة الله وبركاته\n'
    'نذكّركم بأن اشتراك الطالب {nom} قد تجاوز أجل الدفع بتاريخ {date_echeance} '
    '(متأخر بـ {jours_retard} يوماً).\n'
    'نرجو تسوية الوضعية في أقرب وقت وجزاكم الله خيراً.'
)


def creer_singleton(apps, schema_editor):
    """Crée la ligne pk=1 avec le message par défaut — même précaution que
    registration/migrations/0014 : le singleton doit exister avec un vrai
    texte dès le déploiement, sans attendre qu'un مدير/مشرف ouvre la page."""
    ReglageRelanceWhatsApp = apps.get_model('payments', 'ReglageRelanceWhatsApp')
    ReglageRelanceWhatsApp.objects.get_or_create(
        pk=1, defaults={'message': MESSAGE_RELANCE_WHATSAPP_DEFAUT}
    )


def supprimer_singleton(apps, schema_editor):
    ReglageRelanceWhatsApp = apps.get_model('payments', 'ReglageRelanceWhatsApp')
    ReglageRelanceWhatsApp.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0046_documenteleve_titre_en_documenteleve_titre_fr_and_more'),
        ('payments', '0008_cycleabonnement_cycle_abo_retard_idx'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReglageRelanceWhatsApp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField(blank=True)),
                ('date_modification', models.DateTimeField(auto_now=True)),
                ('derniere_modification_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='accounts.user')),
            ],
            options={
                'verbose_name': 'Réglage relance WhatsApp',
                'verbose_name_plural': 'Réglage relance WhatsApp',
            },
        ),
        migrations.RunPython(creer_singleton, supprimer_singleton),
    ]
