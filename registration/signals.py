from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import ChampInscription, EtapeInscription, RegleCondition


def _supprimer_regles_ciblant(instance):
    """Supprime toute RegleCondition dont `cible` (GenericForeignKey) pointe vers
    `instance`. Nécessaire car cible_content_type/cible_object_id ne sont PAS une
    vraie ForeignKey PostgreSQL (la cible change de modèle selon le type) — aucun
    ON DELETE automatique ne s'applique, contrairement à toutes les autres relations
    de registration.models (voir la politique PROTECT/CASCADE dans son docstring).
    Sans ce nettoyage explicite, supprimer une EtapeInscription/un ChampInscription
    laisserait une RegleCondition orpheline, invisible en base."""
    from django.contrib.contenttypes.models import ContentType

    ct = ContentType.objects.get_for_model(instance)
    RegleCondition.objects.filter(cible_content_type=ct, cible_object_id=instance.pk).delete()


@receiver(pre_delete, sender=EtapeInscription)
def nettoyer_regles_a_la_suppression_etape(sender, instance, **kwargs):
    _supprimer_regles_ciblant(instance)


@receiver(pre_delete, sender=ChampInscription)
def nettoyer_regles_a_la_suppression_champ(sender, instance, **kwargs):
    _supprimer_regles_ciblant(instance)
