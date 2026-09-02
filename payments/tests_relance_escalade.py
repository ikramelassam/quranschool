"""Escalade + relance QUOTIDIENNE des retards de paiement — chantier du
2026-09-02 (surcouche du chantier « cycles d'abonnement » du 2026-09-01).

Fichier séparé de tests_cycles.py à dessein (ce dernier était en cours
d'édition par un autre chantier au moment de l'écriture)."""
import datetime

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import DerniereVisiteNotification, Eleve, User
from inscriptions.models import get_parametres_inscriptions
from payments import cycles

_STORAGES_TEST = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _creer_eleve(email, inscrit_depuis_jours=400):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='طالب', last_name='اختبار', role='eleve', doit_changer_mot_de_passe=False,
    )
    u.date_joined = timezone.now() - datetime.timedelta(days=inscrit_depuis_jours)
    u.save(update_fields=['date_joined'])
    return Eleve.objects.create(user=u, sexe='homme')


def _rendre_en_retard(eleve, jours):
    cycles.demarrer_cycles(eleve)
    cycle = cycles.cycle_courant(eleve)
    cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=jours)
    cycle.save(update_fields=['date_echeance'])
    return cycle


class PhaseRelanceEleveTests(TestCase):
    def test_ancien_eleve_escalade_complete(self):
        eleve = _creer_eleve('ancien_phase@zidni.test', inscrit_depuis_jours=400)
        cycle = _rendre_en_retard(eleve, 0)
        attendu = {
            0: cycles.PHASE_SILENCE,
            1: cycles.PHASE_SIMPLE,
            7: cycles.PHASE_SIMPLE,
            8: cycles.PHASE_AVERT_2J,
            9: cycles.PHASE_AVERT_1J,
            10: cycles.PHASE_CRITIQUE,
            20: cycles.PHASE_CRITIQUE,
        }
        for jours, phase in attendu.items():
            cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=jours)
            self.assertEqual(cycles.phase_relance_eleve(eleve, cycle), phase, f'J+{jours}')

    def test_nouvel_eleve_silence_jusqua_j5(self):
        eleve = _creer_eleve('nouveau_phase@zidni.test', inscrit_depuis_jours=10)
        cycle = _rendre_en_retard(eleve, 0)
        for jours in (1, 3, 4):
            cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=jours)
            self.assertEqual(cycles.phase_relance_eleve(eleve, cycle), cycles.PHASE_SILENCE, f'J+{jours}')
        cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=5)
        self.assertEqual(cycles.phase_relance_eleve(eleve, cycle), cycles.PHASE_SIMPLE)
        # À partir de J+8, nouvel et ancien élève suivent le même décompte.
        cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=8)
        self.assertEqual(cycles.phase_relance_eleve(eleve, cycle), cycles.PHASE_AVERT_2J)

    def test_est_nouvel_eleve_respecte_le_parametre(self):
        eleve = _creer_eleve('seuil_nouveau@zidni.test', inscrit_depuis_jours=45)
        params = get_parametres_inscriptions()
        params.delai_grace_nouvel_eleve_mois = 1  # ~30 j
        params.save(update_fields=['delai_grace_nouvel_eleve_mois'])
        self.assertFalse(cycles.est_nouvel_eleve(eleve))
        params.delai_grace_nouvel_eleve_mois = 3  # ~90 j
        params.save(update_fields=['delai_grace_nouvel_eleve_mois'])
        self.assertTrue(cycles.est_nouvel_eleve(eleve))


@override_settings(STORAGES=_STORAGES_TEST)
class NotificationQuotidienneTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve('relance_quotidienne@zidni.test', inscrit_depuis_jours=400)
        self.cycle = _rendre_en_retard(self.eleve, 3)  # ancien élève, J+3 -> PHASE_SIMPLE
        # Réarmement à minuit : l'ancre = « aujourd'hui 00:00 », toujours <= maintenant.
        params = get_parametres_inscriptions()
        params.heure_relance_paiement = datetime.time(0, 0)
        params.save(update_fields=['heure_relance_paiement'])

    def _seuil(self, quand):
        DerniereVisiteNotification.objects.update_or_create(
            user=self.eleve.user, cle='paiements_retard', defaults={'date_visite': quand},
        )

    def _notif_retard(self):
        from dashboard.notifications import notifications_eleve
        groupes, _total = notifications_eleve(self.eleve, self.eleve.user)
        for g in groupes:
            if g['label'] == 'دفع متأخر':
                return g['evenements'][0]['texte']
        return None

    def test_notif_visible_le_lendemain_dune_visite(self):
        # heure_relance = 00:00 (setUp) -> l'ancre = « aujourd'hui 00:00 » (locale).
        # Dernière visite = hier midi -> l'ancre du jour lui est postérieure ->
        # la notif réapparaît aujourd'hui.
        hier_midi = timezone.localtime().replace(
            hour=12, minute=0, second=0, microsecond=0
        ) - datetime.timedelta(days=1)
        self._seuil(hier_midi)
        self.assertIsNotNone(self._notif_retard())

    def test_notif_masquee_juste_apres_la_visite(self):
        self._seuil(timezone.now())
        self.assertIsNone(self._notif_retard())

    def test_texte_simple_a_j3(self):
        self._seuil(timezone.now() - datetime.timedelta(days=2))
        self.assertIn('تأخّرت', self._notif_retard())

    def test_texte_avertissement_2j_a_j8(self):
        self.cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=8)
        self.cycle.save(update_fields=['date_echeance'])
        self._seuil(timezone.now() - datetime.timedelta(days=2))
        self.assertIn('يومين', self._notif_retard())

    def test_nouvel_eleve_pas_de_notif_avant_j5(self):
        self.eleve.user.date_joined = timezone.now() - datetime.timedelta(days=10)
        self.eleve.user.save(update_fields=['date_joined'])
        self._seuil(timezone.now() - datetime.timedelta(days=2))
        self.assertIsNone(self._notif_retard())  # J+3, nouvel élève -> silence


@override_settings(STORAGES=_STORAGES_TEST)
class PageDirectionAlerteRougeTests(TestCase):
    """Page متأخرون عن الدفع : alerte rouge « حان وقت الأرشفة » dès J+8."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin_alerte_rouge@zidni.test', email='admin_alerte_rouge@zidni.test',
            password='xX!test12345', first_name='مدير', role='admin', doit_changer_mot_de_passe=False,
        )

    def _page(self):
        self.client.force_login(self.admin)
        return self.client.get(reverse('paiements_retards'))

    def test_alerte_rouge_des_j8(self):
        _rendre_en_retard(_creer_eleve('urgent_dir@zidni.test'), 8)
        self.assertContains(self._page(), 'حان وقت الأرشفة')

    def test_pas_dalerte_a_j3(self):
        _rendre_en_retard(_creer_eleve('calme_dir@zidni.test'), 3)
        self.assertNotContains(self._page(), 'حان وقت الأرشفة')
