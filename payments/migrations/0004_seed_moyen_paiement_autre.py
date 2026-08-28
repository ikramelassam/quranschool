# Generated for Chantier du 2026-08-27 ("طريقة أخرى" — option de paiement pour
# les élèves sans compte bancaire).

from django.db import migrations

# Même patron que inscriptions.migrations.0004_seed_types_abonnement (modèle
# décrit dans MoyenPaiement.__doc__ comme suivant exactement ce patron) : les
# lignes CIH/Barid Bank déjà en base ont été créées à la main par le
# مدير/مشرف depuis dashboard.views.admin_moyen_paiement_ajouter (AUCUNE
# migration de seed pour elles — rien à reproduire ici), mais une NOUVELLE
# option ajoutée par ce chantier suit le même besoin que les tarifs
# d'abonnement initiaux : la rendre disponible dès le déploiement, sans
# attendre une saisie manuelle en production. `coordonnees` reste un texte de
# départ MODIFIABLE ensuite par le مدير/مشرف via ce même formulaire — voir
# MoyenPaiement.coordonnees.__doc__ ("texte libre pour rester adaptable").
# ordre=999 : toujours après les moyens existants (CIH/Barid Bank...), quel
# que soit leur ordre réel en base (jamais deviné/dupliqué ici) — "طريقة
# أخرى" a naturellement sa place en dernier dans la liste.
CODE_AUTRE = 'autre'
LABEL_AUTRE = 'طريقة أخرى'
COORDONNEES_INITIALES = (
    'إذا لم يكن لديك حساب بنكي، يرجى التواصل مع الإدارة لتحديد طريقة دفع مناسبة.'
)


def creer_moyen_autre(apps, schema_editor):
    MoyenPaiement = apps.get_model('payments', 'MoyenPaiement')
    MoyenPaiement.objects.get_or_create(
        code=CODE_AUTRE,
        defaults={'label': LABEL_AUTRE, 'coordonnees': COORDONNEES_INITIALES, 'ordre': 999},
    )


def supprimer_moyen_autre(apps, schema_editor):
    MoyenPaiement = apps.get_model('payments', 'MoyenPaiement')
    MoyenPaiement.objects.filter(code=CODE_AUTRE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0003_moyenpaiement'),
    ]

    operations = [
        migrations.RunPython(creer_moyen_autre, supprimer_moyen_autre),
    ]
