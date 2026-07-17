from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Eleve, Prof


@receiver(post_delete, sender=Eleve)
def rejeter_inscription_eleve_a_la_suppression(sender, instance, **kwargs):
    """Quand un Eleve (donc son User, en cascade) est supprimé — typiquement
    depuis /admin/ — la candidature liée restait auparavant bloquée à
    statut='valide' sans compte derrière (voir incident: mohamed, samira,
    farah...). On la repasse à 'rejete' (pas 'en_attente') pour que le
    bouton قبول ne tente jamais de recréer un compte en double dessus."""
    if instance.inscription_id:
        from inscriptions.models import InscriptionEleve
        InscriptionEleve.objects.filter(id=instance.inscription_id, statut='valide').update(statut='rejete')


@receiver(post_delete, sender=Prof)
def rejeter_inscription_prof_a_la_suppression(sender, instance, **kwargs):
    """Équivalent de rejeter_inscription_eleve_a_la_suppression pour un Prof."""
    if instance.inscription_id:
        from inscriptions.models import InscriptionProf
        InscriptionProf.objects.filter(id=instance.inscription_id, statut='valide').update(statut='rejete')
