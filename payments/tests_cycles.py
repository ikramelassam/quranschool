"""Cycles d'abonnement / relances de paiement — chantier du 2026-09-01.
Voir payments.models.CycleAbonnement / payments.cycles."""
import datetime

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import Eleve, User
from payments import cycles
from payments.models import Paiement

_STORAGES_TEST = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _creer_eleve(email):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='طالب', last_name='اختبار', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme')


def _admin(email='admin_retards_test@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='مدير', role='admin', doit_changer_mot_de_passe=False,
    )


def _mois_decale(reference, n):
    """1er jour du mois situé `n` mois après le mois de `reference`."""
    total = (reference.year * 12 + reference.month - 1) + n
    return datetime.date(total // 12, total % 12 + 1, 1)


@override_settings(STORAGES=_STORAGES_TEST)
class CycleAbonnementTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve('eleve_cycle_test@zidni.test')

    def _rendre_echu(self, jours=1):
        cycle = cycles.cycle_courant(self.eleve)
        cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=jours)
        cycle.save(update_fields=['date_echeance'])
        return cycle

    def test_demarrer_cycles_cree_cycle1_echeance_a_10_jours(self):
        cycles.demarrer_cycles(self.eleve)
        cycle = cycles.cycle_courant(self.eleve)
        self.assertEqual(cycle.numero, 1)
        self.assertEqual(cycle.date_echeance, cycle.date_debut + datetime.timedelta(days=10))

    def test_demarrer_cycles_est_idempotent(self):
        cycles.demarrer_cycles(self.eleve)
        cycles.demarrer_cycles(self.eleve)
        self.assertEqual(self.eleve.cycles_abonnement.count(), 1)

    def test_pas_en_retard_avant_echeance(self):
        cycles.demarrer_cycles(self.eleve)
        self.assertFalse(cycles.est_en_retard(self.eleve))

    def test_en_retard_apres_echeance_sans_paiement(self):
        cycles.demarrer_cycles(self.eleve)
        self._rendre_echu()
        self.assertTrue(cycles.est_en_retard(self.eleve))

    def test_paiement_en_attente_suspend_la_relance(self):
        cycles.demarrer_cycles(self.eleve)
        cycle = self._rendre_echu()
        Paiement.objects.create(
            eleve=self.eleve, montant=80, mois_reference=cycle.date_debut, statut='en_attente',
        )
        self.assertFalse(cycles.est_en_retard(self.eleve))

    def test_paiement_valide_fait_avancer_le_cycle(self):
        cycles.demarrer_cycles(self.eleve)
        cycle1 = cycles.cycle_courant(self.eleve)
        Paiement.objects.create(
            eleve=self.eleve, montant=80,
            mois_reference=cycle1.date_debut.replace(day=15), statut='valide',
        )
        cycles.reconcilier(self.eleve)
        cycle1.refresh_from_db()
        self.assertTrue(cycle1.regle)
        cycle2 = cycles.cycle_courant(self.eleve)
        self.assertEqual(cycle2.numero, 2)
        self.assertEqual(cycle2.date_debut, cycle1.date_fin_couverte + datetime.timedelta(days=1))
        self.assertEqual(cycle2.date_echeance, cycle1.date_fin_couverte + datetime.timedelta(days=10))
        self.assertEqual(cycle1.montant_regle, 80)

    def test_couverture_multi_mois_contigus_credite_jusquau_dernier(self):
        cycles.demarrer_cycles(self.eleve)
        cycle1 = cycles.cycle_courant(self.eleve)
        for i in range(3):
            Paiement.objects.create(
                eleve=self.eleve, montant=80,
                mois_reference=_mois_decale(cycle1.date_debut, i).replace(day=5), statut='valide',
            )
        cycles.reconcilier(self.eleve)
        cycle1.refresh_from_db()
        troisieme_mois = _mois_decale(cycle1.date_debut, 2)
        self.assertEqual(cycle1.date_fin_couverte.month, troisieme_mois.month)
        self.assertEqual(cycle1.date_fin_couverte.year, troisieme_mois.year)

    def test_trou_dans_la_couverture_ne_credite_pas_au_dela(self):
        cycles.demarrer_cycles(self.eleve)
        cycle1 = cycles.cycle_courant(self.eleve)
        m0 = cycle1.date_debut
        Paiement.objects.create(eleve=self.eleve, montant=80, mois_reference=_mois_decale(m0, 0).replace(day=3), statut='valide')
        Paiement.objects.create(eleve=self.eleve, montant=80, mois_reference=_mois_decale(m0, 2).replace(day=3), statut='valide')
        cycles.reconcilier(self.eleve)
        cycle1.refresh_from_db()
        self.assertTrue(cycle1.regle)
        self.assertEqual(cycle1.date_fin_couverte.month, _mois_decale(m0, 0).month)

    def test_redemarrer_cycle_courant_reporte_lecheance_a_aujourdhui(self):
        cycles.demarrer_cycles(self.eleve)
        cycle = cycles.cycle_courant(self.eleve)
        cycle.date_debut = timezone.localdate() - datetime.timedelta(days=40)
        cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=30)
        cycle.save(update_fields=['date_debut', 'date_echeance'])
        cycles.redemarrer_cycle_courant(self.eleve)
        cycle.refresh_from_db()
        self.assertEqual(cycle.date_debut, timezone.localdate())
        self.assertEqual(cycle.date_echeance, timezone.localdate() + datetime.timedelta(days=10))

    def test_eleve_archive_exclu_de_eleves_en_retard(self):
        cycles.demarrer_cycles(self.eleve)
        self._rendre_echu(jours=5)
        self.assertIn(self.eleve.id, [e.id for e, c in cycles.eleves_en_retard()])
        self.eleve.statut = 'archive'
        self.eleve.save(update_fields=['statut'])
        self.assertNotIn(self.eleve.id, [e.id for e, c in cycles.eleves_en_retard()])

    def test_eleves_en_retard_nombre_de_requetes_borne_independamment_du_nombre_deleves(self):
        # Perf : jamais O(nombre d'élèves) — 2 requêtes quel que soit l'effectif
        # (voir cycles.cycles_ouverts_en_retard). Ici on en met 12 en retard.
        for i in range(12):
            e = _creer_eleve(f'perf_retard_{i}@zidni.test')
            cycles.demarrer_cycles(e)
            c = cycles.cycle_courant(e)
            c.date_echeance = timezone.localdate() - datetime.timedelta(days=2)
            c.save(update_fields=['date_echeance'])
        with self.assertNumQueries(2):  # cycles+users, puis paiements — jamais O(élèves)
            resultat = cycles.eleves_en_retard()
        self.assertEqual(len(resultat), 12)
        with self.assertNumQueries(3):  # + prefetch groupes pour la page dédiée
            self.assertEqual(len(cycles.eleves_en_retard(avec_groupes=True)), 12)

    def test_eleves_en_retard_une_seule_requete_si_aucun_candidat(self):
        cycles.demarrer_cycles(self.eleve)  # pas échu
        with self.assertNumQueries(1):
            self.assertEqual(cycles.eleves_en_retard(), [])


@override_settings(STORAGES=_STORAGES_TEST)
class RetardsIntegrationTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve('eleve_retard_integ@zidni.test')
        cycles.demarrer_cycles(self.eleve)
        cycle = cycles.cycle_courant(self.eleve)
        cycle.date_echeance = timezone.localdate() - datetime.timedelta(days=3)
        cycle.save(update_fields=['date_echeance'])
        self.admin = _admin()
        # Le badge 🔔 suit DerniereVisiteNotification, amorcé à user.date_joined.
        # On recule celui des 2 comptes pour que l'échéance (reculée de 3 j
        # ci-dessus) soit bien POSTÉRIEURE au seuil d'amorçage → notif visible
        # tant que la page cible n'a pas été visitée.
        vieux = timezone.now() - datetime.timedelta(days=60)
        User.objects.filter(pk__in=[self.eleve.user_id, self.admin.pk]).update(date_joined=vieux)
        self.eleve.user.refresh_from_db()
        self.admin.refresh_from_db()

    def test_notification_eleve_contient_le_groupe_retard(self):
        from dashboard.notifications import notifications_eleve

        groupes, total = notifications_eleve(self.eleve, self.eleve.user)
        self.assertIn('دفع متأخر', [g['label'] for g in groupes])
        self.assertGreaterEqual(total, 1)

    def test_notification_directeur_liste_leleve(self):
        from dashboard.notifications import notifications_direction

        groupes, _total = notifications_direction(self.admin)
        textes = [e['texte'] for g in groupes for e in g['evenements']]
        self.assertTrue(any(self.eleve.user.get_full_name() in t for t in textes))

    def test_badge_eleve_seteint_apres_visite_de_sa_page_paiement(self):
        from dashboard.notifications import notifications_eleve

        self.client.force_login(self.eleve.user)
        self.client.get(reverse('eleve_paiements'))
        groupes, total = notifications_eleve(self.eleve, self.eleve.user)
        self.assertNotIn('دفع متأخر', [g['label'] for g in groupes])
        # …mais l'élève reste bien « en retard » (l'état, pas le badge).
        self.assertTrue(cycles.est_en_retard(self.eleve))

    def test_badge_directeur_seteint_apres_visite_de_la_page_retards(self):
        from dashboard.notifications import notifications_direction

        self.client.force_login(self.admin)
        self.client.get(reverse('paiements_retards'))
        groupes, _total = notifications_direction(self.admin)
        textes = [e['texte'] for g in groupes for e in g['evenements']]
        self.assertFalse(any(self.eleve.user.get_full_name() in t for t in textes))
        # La page dédiée, elle, liste toujours l'élève même badge éteint.
        reponse = self.client.get(reverse('paiements_retards'))
        self.assertContains(reponse, self.eleve.user.get_full_name())

    def test_page_paiements_retards_liste_leleve(self):
        self.client.force_login(self.admin)
        reponse = self.client.get(reverse('paiements_retards'))
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, self.eleve.user.get_full_name())

    def test_page_paiements_retards_interdite_a_leleve(self):
        self.client.force_login(self.eleve.user)
        self.assertEqual(self.client.get(reverse('paiements_retards')).status_code, 302)

    def test_validation_paiement_fait_disparaitre_le_retard(self):
        cycle = cycles.cycle_courant(self.eleve)
        paiement = Paiement.objects.create(
            eleve=self.eleve, montant=80, mois_reference=cycle.date_debut, statut='en_attente',
        )
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_paiement_valider', args=[paiement.id]))
        self.assertFalse(cycles.est_en_retard(self.eleve))
