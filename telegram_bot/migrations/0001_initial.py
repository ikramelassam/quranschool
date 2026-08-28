import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AbonneTelegram',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chat_id', models.BigIntegerField(help_text='chat_id Telegram du destinataire (identifiant numérique, pas le @username).', unique=True)),
                ('nom', models.CharField(blank=True, default='', max_length=150)),
                ('telegram_username', models.CharField(blank=True, default='', max_length=150)),
                ('est_actif', models.BooleanField(default=False)),
                ('en_attente_validation', models.BooleanField(default=True)),
                ('date_abonnement', models.DateTimeField(auto_now_add=True)),
                ('date_desabonnement', models.DateTimeField(blank=True, null=True)),
                ('valide_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Abonné Telegram',
                'verbose_name_plural': 'Abonnés Telegram',
                'ordering': ['-date_abonnement'],
            },
        ),
    ]
