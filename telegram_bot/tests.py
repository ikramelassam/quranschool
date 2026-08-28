import json
from unittest.mock import Mock, patch

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import User
from core.utils import envoyer_notification_telegram
from .models import AbonneTelegram

MOT_DE_PASSE = 'xX!test12345'
SECRET_TEST = 'secret-de-test-webhook'
TOKEN_TEST = '123456:token-de-test'


def _reponse_mock(status_code=200, texte=''):
    """Fausse réponse requests.post — .ok suit status_code < 400 comme la
    vraie classe requests.Response (pas un simple attribut codé en dur)."""
    reponse = Mock(status_code=status_code, text=texte)
    reponse.ok = status_code < 400
    return reponse


def _update_message(chat_id, texte, first_name='طالب', last_name='', username=''):
    return {
        'update_id': 1,
        'message': {
            'chat': {'id': chat_id, 'type': 'private'},
            'text': texte,
            'from': {'first_name': first_name, 'last_name': last_name, 'username': username},
        },
    }


def _creer_admin(email='admin_telegram@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مدير', last_name='تجريبي', role='admin', doit_changer_mot_de_passe=False,
    )


def _creer_mshrif(email='mshrif_telegram@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مشرف', last_name='تجريبي', role='mshrif', doit_changer_mot_de_passe=False,
    )


def _creer_eleve(email='eleve_telegram@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )


@override_settings(TELEGRAM_WEBHOOK_SECRET=SECRET_TEST, TELEGRAM_BOT_TOKEN=TOKEN_TEST)
class WebhookSecuriteTest(TestCase):
    """Le secret_token est la SEULE protection du webhook (pas de CSRF Django
    possible face à Telegram) — doit rejeter tout ce qui ne le porte pas."""

    def setUp(self):
        self.client = Client(SERVER_NAME='localhost')
        self.url = reverse('telegram_webhook')
        # La migration 0002 seed un abonné réel (chat_id=settings.TELEGRAM_CHAT_ID)
        # dans la base de test — ces tests veulent partir d'une base réellement
        # vide, indépendamment de la config .env locale.
        AbonneTelegram.objects.all().delete()

    def test_sans_header_secret_rejete(self):
        reponse = self.client.post(
            self.url, data=json.dumps(_update_message(111, '/start')), content_type='application/json'
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(AbonneTelegram.objects.count(), 0)

    def test_mauvais_secret_rejete(self):
        reponse = self.client.post(
            self.url, data=json.dumps(_update_message(111, '/start')), content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='mauvais-secret',
        )
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(AbonneTelegram.objects.count(), 0)

    @override_settings(TELEGRAM_WEBHOOK_SECRET='')
    def test_secret_non_configure_rejette_tout(self):
        """Même avec le bon header côté appelant, un secret vide côté serveur
        (jamais configuré) doit rejeter — jamais un secret vide == vide."""
        reponse = self.client.post(
            self.url, data=json.dumps(_update_message(111, '/start')), content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='',
        )
        self.assertEqual(reponse.status_code, 403)

    def test_get_refuse(self):
        reponse = self.client.get(self.url, HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SECRET_TEST)
        self.assertEqual(reponse.status_code, 405)

    def test_corps_json_invalide_ne_plante_pas(self):
        reponse = self.client.post(
            self.url, data='ceci-nest-pas-du-json', content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SECRET_TEST,
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(AbonneTelegram.objects.count(), 0)


@override_settings(TELEGRAM_WEBHOOK_SECRET=SECRET_TEST, TELEGRAM_BOT_TOKEN=TOKEN_TEST)
@patch('core.utils.requests.post')
class WebhookStartStopTest(TestCase):

    def setUp(self):
        self.client = Client(SERVER_NAME='localhost')
        self.url = reverse('telegram_webhook')
        # La migration 0002 seed un abonné réel (chat_id=settings.TELEGRAM_CHAT_ID)
        # dans la base de test — ces tests veulent partir d'une base réellement
        # vide, indépendamment de la config .env locale.
        AbonneTelegram.objects.all().delete()

    def _start(self, chat_id, **kwargs):
        return self.client.post(
            self.url, data=json.dumps(_update_message(chat_id, '/start', **kwargs)),
            content_type='application/json', HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SECRET_TEST,
        )

    def _stop(self, chat_id):
        return self.client.post(
            self.url, data=json.dumps(_update_message(chat_id, '/stop')),
            content_type='application/json', HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SECRET_TEST,
        )

    def test_start_nouveau_chat_id_cree_en_attente(self, mock_post):
        mock_post.return_value = _reponse_mock()
        reponse = self._start(555, first_name='أحمد', username='ahmed_tg')

        self.assertEqual(reponse.status_code, 200)
        abonne = AbonneTelegram.objects.get(chat_id=555)
        self.assertTrue(abonne.en_attente_validation)
        self.assertFalse(abonne.est_actif)
        self.assertEqual(abonne.nom, 'أحمد')
        self.assertEqual(abonne.telegram_username, 'ahmed_tg')
        mock_post.assert_called_once()  # message de confirmation envoyé à l'abonné

    def test_start_sur_actif_ne_duplique_pas_et_reste_actif(self, mock_post):
        mock_post.return_value = _reponse_mock()
        AbonneTelegram.objects.create(chat_id=555, est_actif=True, en_attente_validation=False)

        self._start(555)

        self.assertEqual(AbonneTelegram.objects.filter(chat_id=555).count(), 1)
        abonne = AbonneTelegram.objects.get(chat_id=555)
        self.assertTrue(abonne.est_actif)
        self.assertFalse(abonne.en_attente_validation)

    def test_start_sur_desactive_repasse_en_attente(self, mock_post):
        """Décision de sécurité : jamais de réactivation directe, même pour un
        abonné déjà connu et déjà validé par le passé."""
        mock_post.return_value = _reponse_mock()
        AbonneTelegram.objects.create(
            chat_id=555, est_actif=False, en_attente_validation=False,
        )

        self._start(555)

        abonne = AbonneTelegram.objects.get(chat_id=555)
        self.assertFalse(abonne.est_actif)
        self.assertTrue(abonne.en_attente_validation)

    def test_stop_desactive_abonne_actif(self, mock_post):
        mock_post.return_value = _reponse_mock()
        AbonneTelegram.objects.create(chat_id=555, est_actif=True, en_attente_validation=False)

        self._stop(555)

        abonne = AbonneTelegram.objects.get(chat_id=555)
        self.assertFalse(abonne.est_actif)
        self.assertIsNotNone(abonne.date_desabonnement)

    def test_stop_chat_id_inconnu_ne_cree_rien(self, mock_post):
        mock_post.return_value = _reponse_mock()
        self._stop(999)
        self.assertEqual(AbonneTelegram.objects.count(), 0)
        mock_post.assert_called_once()  # réponse "non abonné" quand même envoyée

    def test_message_quelconque_ne_cree_aucun_abonne(self, mock_post):
        mock_post.return_value = _reponse_mock()
        self.client.post(
            self.url, data=json.dumps(_update_message(555, 'salut')),
            content_type='application/json', HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=SECRET_TEST,
        )
        self.assertEqual(AbonneTelegram.objects.count(), 0)
        mock_post.assert_called_once()  # message d'aide envoyé


class AdminValidationAbonneTest(TestCase):

    def setUp(self):
        self.client = Client(SERVER_NAME='localhost')
        self.abonne = AbonneTelegram.objects.create(
            chat_id=777, nom='Test', est_actif=False, en_attente_validation=True,
        )

    def _login(self, user):
        self.client.force_login(user)

    @patch('core.utils.requests.post')
    def test_admin_valide_abonne(self, mock_post):
        mock_post.return_value = _reponse_mock()
        admin = _creer_admin()
        self._login(admin)

        reponse = self.client.get(reverse('admin_telegram_abonne_valider', args=[self.abonne.id]))

        self.assertEqual(reponse.status_code, 302)
        self.abonne.refresh_from_db()
        self.assertTrue(self.abonne.est_actif)
        self.assertFalse(self.abonne.en_attente_validation)
        self.assertEqual(self.abonne.valide_par, admin)

    @patch('core.utils.requests.post')
    def test_mshrif_peut_aussi_valider(self, mock_post):
        """مدير et مشرف à parité — les 2 rôles peuvent valider un abonné."""
        mock_post.return_value = _reponse_mock()
        mshrif = _creer_mshrif()
        self._login(mshrif)

        self.client.get(reverse('admin_telegram_abonne_valider', args=[self.abonne.id]))

        self.abonne.refresh_from_db()
        self.assertTrue(self.abonne.est_actif)

    def test_admin_rejette_abonne(self):
        admin = _creer_admin()
        self._login(admin)

        self.client.get(reverse('admin_telegram_abonne_rejeter', args=[self.abonne.id]))

        self.abonne.refresh_from_db()
        self.assertFalse(self.abonne.est_actif)
        self.assertFalse(self.abonne.en_attente_validation)

    def test_admin_desactive_abonne_actif(self):
        admin = _creer_admin()
        self._login(admin)
        actif = AbonneTelegram.objects.create(chat_id=888, est_actif=True, en_attente_validation=False)

        self.client.get(reverse('admin_telegram_abonne_desactiver', args=[actif.id]))

        actif.refresh_from_db()
        self.assertFalse(actif.est_actif)
        self.assertIsNotNone(actif.date_desabonnement)

    def test_eleve_ne_peut_pas_acceder_a_la_liste(self):
        """@role_required('admin', 'mshrif') — un élève connecté est redirigé,
        jamais laissé accéder à la liste des abonnés."""
        eleve = _creer_eleve()
        self._login(eleve)

        reponse = self.client.get(reverse('admin_telegram_abonnes'))

        self.assertEqual(reponse.status_code, 302)
        self.assertNotEqual(reponse.url, reverse('admin_telegram_abonnes'))


@override_settings(TELEGRAM_BOT_TOKEN=TOKEN_TEST)
class EnvoyerNotificationTelegramTest(TestCase):
    """core.utils.envoyer_notification_telegram — boucle sur les abonnés actifs,
    isolation des échecs par destinataire."""

    def setUp(self):
        # Voir WebhookSecuriteTest.setUp — même nécessité de partir d'une base
        # vide, indépendamment de l'abonné seedé par la migration 0002.
        AbonneTelegram.objects.all().delete()

    def test_aucun_abonne_actif_retourne_false(self):
        AbonneTelegram.objects.create(chat_id=1, est_actif=False, en_attente_validation=True)
        self.assertFalse(envoyer_notification_telegram('test'))

    @patch('core.utils.requests.post')
    def test_diffuse_a_tous_les_abonnes_actifs(self, mock_post):
        mock_post.return_value = _reponse_mock()
        AbonneTelegram.objects.create(chat_id=1, est_actif=True, en_attente_validation=False)
        AbonneTelegram.objects.create(chat_id=2, est_actif=True, en_attente_validation=False)
        AbonneTelegram.objects.create(chat_id=3, est_actif=False, en_attente_validation=False)

        resultat = envoyer_notification_telegram('nouvelle candidature')

        self.assertTrue(resultat)
        self.assertEqual(mock_post.call_count, 2)  # pas le 3e, inactif

    @patch('core.utils.requests.post')
    def test_echec_sur_un_destinataire_nempeche_pas_les_autres(self, mock_post):
        """Un abonné en échec (réseau/HTTP) ne doit jamais empêcher l'envoi
        aux autres — chaque envoi est isolé."""
        abonne_ok = AbonneTelegram.objects.create(chat_id=1, est_actif=True, en_attente_validation=False)
        abonne_ko = AbonneTelegram.objects.create(chat_id=2, est_actif=True, en_attente_validation=False)

        def side_effect(url, data, timeout):
            if data['chat_id'] == abonne_ko.chat_id:
                return _reponse_mock(status_code=500, texte='erreur serveur')
            return _reponse_mock(status_code=200)

        mock_post.side_effect = side_effect

        resultat = envoyer_notification_telegram('test')

        self.assertTrue(resultat)  # au moins un envoi a réussi (abonne_ok)
        self.assertEqual(mock_post.call_count, 2)  # les 2 ont bien été tentés
        # Un échec HTTP simple (500) n'est PAS un blocage (403) — aucune
        # désactivation automatique, contrairement au test 403 ci-dessous.
        abonne_ko.refresh_from_db()
        self.assertTrue(abonne_ko.est_actif)

    @patch('core.utils.requests.post')
    def test_403_desactive_automatiquement_le_destinataire_bloque(self, mock_post):
        abonne_bloque = AbonneTelegram.objects.create(chat_id=1, est_actif=True, en_attente_validation=False)
        abonne_ok = AbonneTelegram.objects.create(chat_id=2, est_actif=True, en_attente_validation=False)

        def side_effect(url, data, timeout):
            if data['chat_id'] == abonne_bloque.chat_id:
                return _reponse_mock(status_code=403, texte='Forbidden: bot was blocked by the user')
            return _reponse_mock(status_code=200)

        mock_post.side_effect = side_effect

        resultat = envoyer_notification_telegram('test')

        self.assertTrue(resultat)  # abonne_ok a quand même reçu le message
        abonne_bloque.refresh_from_db()
        self.assertFalse(abonne_bloque.est_actif)
        self.assertIsNotNone(abonne_bloque.date_desabonnement)
        self.assertTrue(AbonneTelegram.objects.filter(id=abonne_bloque.id).exists())  # jamais supprimé

        abonne_ok.refresh_from_db()
        self.assertTrue(abonne_ok.est_actif)  # non affecté par l'échec de l'autre

    @patch('core.utils.requests.post')
    def test_403_repasse_en_attente_au_prochain_start(self, mock_post):
        """Vérifie la cohérence bout en bout avec la règle de sécurité du
        webhook : un abonné auto-désactivé par 403 doit être traité EXACTEMENT
        comme un /stop volontaire par le webhook (repasse en attente, jamais
        de réactivation directe)."""
        mock_post.return_value = _reponse_mock(status_code=403)
        abonne = AbonneTelegram.objects.create(chat_id=1, est_actif=True, en_attente_validation=False)
        envoyer_notification_telegram('test')
        abonne.refresh_from_db()
        self.assertFalse(abonne.est_actif)

        from telegram_bot.views import _gerer_start
        mock_post.return_value = _reponse_mock(status_code=200)
        _gerer_start(abonne.chat_id, 'نفس الشخص', '')

        abonne.refresh_from_db()
        self.assertFalse(abonne.est_actif)
        self.assertTrue(abonne.en_attente_validation)
