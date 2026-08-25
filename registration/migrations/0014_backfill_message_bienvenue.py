from django.db import migrations

MESSAGE_DEFAUT = (
    'أهلاً بك في عائلة زدني علماً 🌱\n'
    'يسعدنا انضمامك إلينا، ونتمنى لك رحلة موفقة في حفظ ومراجعة القرآن الكريم.'
)


def rattraper_message_vide(apps, schema_editor):
    """Bug réel trouvé le 2026-08-25 : message_bienvenue (le texte affiché sur
    wizard_confirmation.html après l'inscription, caché par
    {% if message_bienvenue %}) n'a JAMAIS reçu de texte par défaut depuis sa
    création (0001_initial) — contrairement à titre/intro (migration 0011) et
    texte_attente_groupe (migration 0013). Résultat : le bloc de bienvenue ne
    s'affichait jamais en production tant qu'un مدير/مشرف n'allait pas remplir
    ce champ à la main sur /dashboard/admin/presentation-inscription/.
    Corrigé dans get_presentation_inscription() (le texte par défaut n'est
    désormais servi qu'À LA CRÉATION du singleton), mais ce correctif seul ne
    rattrape pas une ligne pk=1 déjà créée VIDE avant cette date — même
    précaution que 0011/0013 : uniquement si le champ est encore EXACTEMENT
    vide, jamais écrasé si le مدير/مشرف a déjà tapé quoi que ce soit."""
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, message_bienvenue='').update(
        message_bienvenue=MESSAGE_DEFAUT
    )


def revenir_au_vide(apps, schema_editor):
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, message_bienvenue=MESSAGE_DEFAUT).update(
        message_bienvenue=''
    )


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0013_backfill_texte_attente_groupe'),
    ]

    operations = [
        migrations.RunPython(rattraper_message_vide, revenir_au_vide),
    ]
