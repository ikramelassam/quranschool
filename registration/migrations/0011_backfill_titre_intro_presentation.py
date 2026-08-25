from django.db import migrations

TITRE_DEFAUT = 'أهلاً بك في زدني علماً'
INTRO_DEFAUT = 'أهلاً بك في منصة زدني علماً لتعليم القرآن الكريم عن بعد.'


def rattraper_titre_intro_vides(apps, schema_editor):
    """Chantier du 2026-08-24 : titre/intro de PresentationInscription vivaient
    jusqu'ici uniquement comme `|default:"..."` codés en dur dans
    wizard_intro.html — invisibles et non modifiables par le مدير. Corrigé
    dans get_presentation_inscription() (le texte par défaut n'est désormais
    servi qu'À LA CRÉATION du singleton), mais ce correctif seul ne rattrape
    pas une ligne pk=1 déjà créée VIDE avant cette date (get_or_create ne
    retouche jamais une ligne existante). Uniquement si le champ est encore
    EXACTEMENT vide — jamais écrasé si le مدير (ou مشرف) a déjà tapé quoi que
    ce soit, même une seule lettre : même précaution que la migration 0006."""
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, titre='').update(titre=TITRE_DEFAUT)
    PresentationInscription.objects.filter(pk=1, intro='').update(intro=INTRO_DEFAUT)


def revenir_au_vide(apps, schema_editor):
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, titre=TITRE_DEFAUT).update(titre='')
    PresentationInscription.objects.filter(pk=1, intro=INTRO_DEFAUT).update(intro='')


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0010_demandenonsatisfaite_email_demandenonsatisfaite_nom_and_more'),
    ]

    operations = [
        migrations.RunPython(rattraper_titre_intro_vides, revenir_au_vide),
    ]
