from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


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
    PAS de sous-catégorie 'garçons mineurs'/'filles mineures'.

    `cible` EST le canal (Chantier "canaux de diffusion" du 2026-08-16) : les
    3 valeurs de CIBLE_CHOICES sont exactement les 3 canaux Femmes/Hommes/
    Mineurs de l'interface — aucun modèle Channel séparé n'a été ajouté,
    `cible` jouait déjà ce rôle avant même que l'UI ne le présente comme tel
    (voir annonces.services.CANAUX pour le nom/icône/description d'affichage
    de chaque valeur). Une "publication" dans un canal = une Annonce."""
    CIBLE_CHOICES = [
        ('femmes_adultes', _('الطالبات البالغات')),
        ('hommes_adultes', _('الطلاب البالغون')),
        ('mineurs', _('الأطفال')),
    ]

    # Sous-ciblage optionnel à l'INTÉRIEUR du canal 'mineurs' (Point 3,
    # chantier catégorisation par âge du 2026-08-28) — les 3 mêmes tranches
    # d'âge précises que courses.utils.TRANCHES_AGE_PRECISES/chat.services.
    # ONGLETS_CHAT (التلقين/البراعم/اليافعون), dupliquées ICI plutôt
    # qu'importées : annonces reste volontairement indépendante de courses au
    # niveau des modèles (annonces.models est déjà importé PAR courses.models
    # pour Groupe.CATEGORIE_CHOICES — un import dans l'autre sens créerait un
    # cycle), même principe que EXTENSIONS_PAR_TYPE déjà dupliqué entre
    # chat.services et annonces.services pour la même raison.
    #
    # blank='' = "كل الأطفال" (comportement HISTORIQUE inchangé : toute
    # Annonce déjà existante a tranche_age='' et reste visible par tous les
    # enfants, aucun backfill n'a de sens ici — contrairement à Groupe, une
    # ancienne publication ne "vise" rétroactivement aucune tranche précise
    # connue). Un نشر ciblé sur UNE tranche est un choix explicite du مدير/
    # مشرف au moment de la publication, jamais déduit après coup.
    TRANCHE_AGE_CHOICES = [
        ('talqin', _('التلقين')),
        ('baraim', _('البراعم')),
        ('yafiun', _('اليافعون')),
    ]

    TYPE_FICHIER_CHOICES = [
        ('image', _('صورة')),
        ('video', _('فيديو')),
        ('audio', _('ملف صوتي')),
        ('document', _('مستند')),
    ]

    titre = models.CharField(max_length=200)
    contenu = models.TextField()
    cible = models.CharField(max_length=20, choices=CIBLE_CHOICES)
    # Voir TRANCHE_AGE_CHOICES ci-dessus — n'a de sens QUE si cible='mineurs',
    # ignoré partout ailleurs (jamais vérifié/appliqué pour femmes_adultes/
    # hommes_adultes, voir annonces.services.annonces_visibles_pour_eleve).
    tranche_age = models.CharField(max_length=10, choices=TRANCHE_AGE_CHOICES, blank=True, default='')
    # Réversible (pas de suppression définitive) — même principe que
    # Creneau.est_actif/Groupe.statut='archive' : une annonce publiée par
    # erreur peut être retirée sans perdre son historique.
    active = models.BooleanField(default=True)
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    # Pièce jointe optionnelle (Chantier "canaux" du 2026-08-16) — au plus UNE
    # par publication, exactement comme chat.models.Message (même patron :
    # fichier + nom original + taille, storage par défaut du projet donc déjà
    # Cloudinary en prod / /media/ en dev, voir core/settings.py STORAGES —
    # rien de spécifique à créer). type_fichier détermine le rendu côté
    # template (aperçu image / lecteur vidéo / lecteur audio / carte
    # document) — voir annonces.services.valider_piece_jointe.
    fichier = models.FileField(upload_to='annonces_attachments/%Y/%m/', null=True, blank=True)
    type_fichier = models.CharField(max_length=10, choices=TYPE_FICHIER_CHOICES, blank=True, default='')
    nom_fichier_original = models.CharField(max_length=255, blank=True, default='')
    taille_fichier_octets = models.PositiveIntegerField(null=True, blank=True)

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
