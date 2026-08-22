from django.db import migrations

ANCIEN_TEXTE = (
    'نأسف، لا توجد حالياً مجموعة تتوافق تماماً مع اختياراتك. '
    'يمكنك الاطلاع أدناه على المجموعات القريبة المتاحة، أو متابعة التسجيل '
    'وسيتواصل معك فريقنا لإيجاد الحل الأنسب.'
)
NOUVEAU_TEXTE = (
    'لم نجد أي حلقة تجمع بالضبط بين كل المعايير التي اخترتها (البرنامج، '
    'الرواية، عدد الحصص...). يمكنك الانضمام إلى إحدى الحلقات القريبة '
    'أدناه، أو اختيار الانتظار حتى يتم إنشاء حلقة تناسبك تماماً.'
)


def rendre_le_message_plus_concret(apps, schema_editor):
    """Chantier du 2026-08-22 (retour du test en local) : le message par
    défaut était trop vague — mis à jour ici pour dire explicitement
    qu'aucune combinaison exacte n'existe, plutôt que de le laisser en
    l'état pour tous les environnements déjà migrés vers 0005. UNIQUEMENT
    si le texte est encore EXACTEMENT l'ancien défaut — jamais écrasé si le
    مدير l'a déjà personnalisé (même précaution que get_presentation_
    inscription() lui-même : ne jamais réécrire un choix humain)."""
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, message_aucun_groupe_exact=ANCIEN_TEXTE).update(
        message_aucun_groupe_exact=NOUVEAU_TEXTE
    )


def revenir_a_lancien_texte(apps, schema_editor):
    PresentationInscription = apps.get_model('registration', 'PresentationInscription')
    PresentationInscription.objects.filter(pk=1, message_aucun_groupe_exact=NOUVEAU_TEXTE).update(
        message_aucun_groupe_exact=ANCIEN_TEXTE
    )


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0005_presentationinscription_message_aucun_groupe_exact_and_more'),
    ]

    operations = [
        migrations.RunPython(rendre_le_message_plus_concret, revenir_a_lancien_texte),
    ]
