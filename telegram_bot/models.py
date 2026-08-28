from django.conf import settings
from django.db import models


class AbonneTelegram(models.Model):
    """Un compte Telegram abonné aux notifications du مدير/مشرف (nouvelle
    candidature élève/prof, paiement soumis, mot de passe oublié) — voir
    core.utils.envoyer_notification_telegram, qui envoie à TOUS les abonnés
    actifs plutôt qu'à un chat_id unique codé en dur dans l'environnement
    (ancien système, remplacé par ce chantier).

    Cycle de vie :
    - /start sur un chat_id inconnu → crée la ligne EN ATTENTE
      (en_attente_validation=True, est_actif=False). Aucune notification tant
      qu'un مدير/مشرف ne l'a pas validée depuis le dashboard (voir
      dashboard.views.admin_telegram_abonnes / admin_telegram_abonne_valider).
    - /stop → désactive (est_actif=False, date_desabonnement renseignée) SANS
      supprimer la ligne, pour garder l'historique.
    - /start sur une ligne désactivée (par /stop, par rejet/désactivation
      admin, OU auto-désactivée après un 403 Telegram "bot bloqué" — voir
      core.utils.envoyer_notification_telegram) repasse SYSTÉMATIQUEMENT en
      file d'attente (en_attente_validation=True) — jamais de réactivation
      automatique. Décision de sécurité explicite : le nom du bot n'étant pas
      un secret (n'importe qui peut lui envoyer /start), seule cette
      validation humaine protège les notifications sensibles (candidatures,
      paiements) d'un abonnement non désiré.

    Table volontairement simple (pas de champ "statut" séparé) : un rejet
    explicite par un مدير/مشرف et un /stop volontaire aboutissent au même état
    (est_actif=False, en_attente_validation=False) — le comportement au /start
    suivant (repasser en file d'attente) est identique dans les deux cas, donc
    aucune distinction supplémentaire n'était nécessaire."""

    chat_id = models.BigIntegerField(
        unique=True,
        help_text="chat_id Telegram du destinataire (identifiant numérique, pas le @username).",
    )
    # Capturés automatiquement depuis message.from au moment du /start — permet
    # au مدير/مشرف de savoir QUI valider dans le dashboard sans deviner à partir
    # d'un simple chat_id numérique. Peuvent être vides (compte Telegram sans
    # username, ou first_name non transmis dans de rares cas).
    nom = models.CharField(max_length=150, blank=True, default='')
    telegram_username = models.CharField(max_length=150, blank=True, default='')

    est_actif = models.BooleanField(default=False)
    en_attente_validation = models.BooleanField(default=True)

    date_abonnement = models.DateTimeField(auto_now_add=True)
    date_desabonnement = models.DateTimeField(null=True, blank=True)

    # Audit — related_name='+' comme les autres FK d'audit du projet
    # (User.mot_de_passe_reinitialise_par, ParametresInscriptions.derniere_modification_par).
    valide_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+'
    )

    class Meta:
        ordering = ['-date_abonnement']
        verbose_name = 'Abonné Telegram'
        verbose_name_plural = 'Abonnés Telegram'

    def __str__(self):
        return self.nom or self.telegram_username or str(self.chat_id)
