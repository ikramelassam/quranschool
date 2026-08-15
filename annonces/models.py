from django.conf import settings
from django.db import models


class Annonce(models.Model):
    """Annonce envoyée par مدير/مشرف à une catégorie d'élèves (Chantier du
    2026-08-15). Le ciblage est TOUJOURS l'une des 3 catégories métier
    ci-dessous — jamais un âge/sexe saisi séparément à la main : voir
    courses.utils.cible_annonce_pour_eleve, seule fonction qui calcule, à
    partir de l'âge (date_naissance) et du sexe déjà existants sur Eleve,
    dans laquelle de ces 3 catégories tombe un élève donné. Aucune donnée
    redondante stockée ici pour représenter cette classification.

    IMPORTANT (règle métier explicite du client) : 'mineurs' regroupe TOUS
    les élèves de moins de 18 ans, filles ET garçons confondus — il n'existe
    PAS de sous-catégorie 'garçons mineurs'/'filles mineures'."""
    CIBLE_CHOICES = [
        ('femmes_adultes', 'الطالبات البالغات'),
        ('hommes_adultes', 'الطلاب البالغون'),
        ('mineurs', 'الطلاب القاصرون'),
    ]

    titre = models.CharField(max_length=200)
    contenu = models.TextField()
    cible = models.CharField(max_length=20, choices=CIBLE_CHOICES)
    # Réversible (pas de suppression définitive) — même principe que
    # Creneau.est_actif/Groupe.statut='archive' : une annonce publiée par
    # erreur peut être retirée sans perdre son historique.
    active = models.BooleanField(default=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titre

    class Meta:
        ordering = ['-date_creation']
        verbose_name = "Annonce"
        verbose_name_plural = "Annonces"


class LectureAnnonce(models.Model):
    """Marque qu'un élève a consulté cette annonce — même patron que
    chat.models.LectureConversation (une ligne = lu par cet utilisateur),
    utilisé pour le badge 'غير مقروءة' de la sidebar élève et pour ne mettre
    en avant, sur le tableau de bord, que les annonces réellement nouvelles."""
    annonce = models.ForeignKey(Annonce, on_delete=models.CASCADE, related_name='lectures')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    date_lecture = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('annonce', 'user')
        verbose_name = "Lecture d'annonce"
        verbose_name_plural = "Lectures d'annonces"
