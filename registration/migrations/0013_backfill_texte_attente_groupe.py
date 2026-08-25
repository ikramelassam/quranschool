from django.db import migrations

TEXTE_DEFAUT = (
    '⏳ لا، أنتظر حتى يتم إنشاء الحلقة\n'
    'سيتواصل معك فريقنا خلال 24 ساعة فور توفر حلقة تناسب اختياراتك بالضبط.'
)


def rattraper_texte_vide(apps, schema_editor):
    """Chantier du 2026-08-25 : la carte "⏳ لا، أنتظر حتى يتم إنشاء الحلقة"
    (écran wizard_groupe quand aucun groupe n'existe pour la combinaison
    exacte) vivait jusqu'ici codée en dur dans wizard_groupe.html — invisible
    et non modifiable par le مدير/مشرف. Le nouveau champ texte_attente_groupe
    ne reçoit son texte par défaut qu'À LA CRÉATION du singleton (voir
    get_presentation_inscription), donc rattrapage nécessaire pour la ligne
    pk=1 déjà créée avant cette migration — même précaution que 0011 :
    uniquement si le champ est encore EXACTEMENT vide, jamais écrasé si le
    مدير/مشرف a déjà tapé quoi que ce soit."""
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, texte_attente_groupe='').update(
        texte_attente_groupe=TEXTE_DEFAUT
    )


def revenir_au_vide(apps, schema_editor):
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, texte_attente_groupe=TEXTE_DEFAUT).update(
        texte_attente_groupe=''
    )


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0012_presentationinscription_texte_attente_groupe'),
    ]

    operations = [
        migrations.RunPython(rattraper_texte_vide, revenir_au_vide),
    ]
