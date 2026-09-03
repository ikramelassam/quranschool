import datetime
from decimal import Decimal

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import Eleve, User
from .models import Paiement

# Même précaution que dashboard.tests/registration.tests (STORAGES) : toute
# page qui charge le logo (header/sidebar, via accounts.context_processors.
# logo_context) lève une ValueError sans cet override en environnement de test.
_STORAGES_TEST = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _creer_eleve(email='eleve_paiements_test@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='طالب', last_name='اختبار', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme')


def _screenshot():
    return SimpleUploadedFile('recu.jpg', b'contenu-de-test-jetable', content_type='image/jpeg')


# Chantier « cycle roulant ancré sur le jour d'inscription » du 2026-09-03 :
# le formulaire /payments/eleve/ demande COMBIEN de mois l'élève paie
# ("nb_mois") + le MONTANT TOTAL viré ("montant"), réparti à parts égales sur
# les périodes. La période commence toujours au début du cycle d'abonnement
# ouvert (jour d'ancrage 10→10…) — sinon « 10 sep → 10 oct » saisi à la main
# comptait deux mois calendaires. Un Paiement PAR mois de période
# (unique_together (eleve, mois_reference) inchangé), mois_reference = date de
# début de la période (rapprochement avec les cycles au mois près).
@override_settings(STORAGES=_STORAGES_TEST)
class EleveePaiementsPeriodeTests(TestCase):
    def setUp(self):
        from payments import cycles
        self.eleve = _creer_eleve()
        # Cycle 1 ancré au 5 août 2026 -> périodes 5/08→5/09, 5/09→5/10…
        cycles.demarrer_cycles(self.eleve, date_reference=datetime.date(2026, 8, 5))
        self.client = Client()
        self.client.force_login(self.eleve.user)

    def test_un_seul_mois_cree_un_seul_paiement_ancre_sur_le_cycle(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': '1', 'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        paiements = Paiement.objects.filter(eleve=self.eleve)
        self.assertEqual(paiements.count(), 1)
        self.assertEqual(paiements.first().mois_reference, datetime.date(2026, 8, 5))
        self.assertEqual(paiements.first().montant, 80)

    def test_montant_total_reparti_a_parts_egales_sur_les_mois(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': '3', 'montant': '240', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        paiements = Paiement.objects.filter(eleve=self.eleve).order_by('mois_reference')
        self.assertEqual(list(paiements.values_list('mois_reference', flat=True)), [
            datetime.date(2026, 8, 5), datetime.date(2026, 9, 5), datetime.date(2026, 10, 5),
        ])
        # 240 / 3 = 80 par mois, tous les Paiement frères au même montant.
        self.assertTrue(all(p.montant == 80 for p in paiements))
        # Chaque Paiement a bien SA PROPRE copie du justificatif (fichiers
        # distincts, pas le même objet UploadedFile épuisé après le 1er .save()).
        noms_fichiers = {p.screenshot.name for p in paiements}
        self.assertEqual(len(noms_fichiers), 3)
        for p in paiements:
            self.assertTrue(p.screenshot.storage.exists(p.screenshot.name))

    def test_montant_total_non_divisible_arrondi_au_centime(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': '3', 'montant': '250', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        montants = set(Paiement.objects.filter(eleve=self.eleve).values_list('montant', flat=True))
        # 250 / 3 = 83.33 (arrondi au centime), même valeur sur les 3 frères.
        self.assertEqual(montants, {Decimal('83.33')})

    def test_montant_zero_ou_invalide_refuse_sans_rien_creer(self):
        for valeur in ('0', '-5', 'abc', ''):
            reponse = self.client.post(reverse('eleve_paiements'), {
                'nb_mois': '1', 'montant': valeur, 'screenshot': _screenshot(),
            })
            self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_mois_deja_existant_dans_la_periode_est_ignore_sans_erreur(self):
        Paiement.objects.create(eleve=self.eleve, montant=80, mois_reference=datetime.date(2026, 9, 20))
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': '3', 'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        # Toujours UN SEUL Paiement pour septembre (celui déjà là), pas de
        # doublon, pas de 500 (IntegrityError unique_together évitée) — août et
        # octobre créés.
        self.assertEqual(
            Paiement.objects.filter(eleve=self.eleve, mois_reference__month=9).count(), 1
        )
        self.assertTrue(Paiement.objects.filter(eleve=self.eleve, mois_reference__month=8).exists())
        self.assertTrue(Paiement.objects.filter(eleve=self.eleve, mois_reference__month=10).exists())

    def test_nb_mois_zero_ou_negatif_refuse_sans_rien_creer(self):
        for valeur in ('0', '-2'):
            reponse = self.client.post(reverse('eleve_paiements'), {
                'nb_mois': valeur, 'montant': '80', 'screenshot': _screenshot(),
            })
            self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_nb_mois_trop_grand_refuse_sans_rien_creer(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': '99', 'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_nb_mois_non_numerique_refuse_sans_rien_creer(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': 'pas-un-nombre', 'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_eleve_archive_ne_peut_pas_soumettre(self):
        self.eleve.statut = 'archive'
        self.eleve.save(update_fields=['statut'])
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': '1', 'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())


# La fiche /payments/admin/<id>/ doit montrer « la durée de la demande » :
# un règlement de plusieurs mois crée un Paiement par période, la vue les
# regroupe (même élève, même montant, même soumission) et affiche UNIQUEMENT
# le span début → fin exclusive de la période totale — pas le détail mois
# par mois (demande utilisateur : « juste la durée, pas l'historique »).
@override_settings(STORAGES=_STORAGES_TEST)
class AdminPaiementDetailPeriodeTests(TestCase):
    def setUp(self):
        from payments import cycles
        self.eleve = _creer_eleve()
        cycles.demarrer_cycles(self.eleve, date_reference=datetime.date(2026, 8, 5))
        self.admin = User.objects.create_user(
            username='admin_detail_periode@zidni.test', email='admin_detail_periode@zidni.test',
            password='xX!test12345', role='admin', doit_changer_mot_de_passe=False,
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def _payer(self, nb_mois):
        c = Client()
        c.force_login(self.eleve.user)
        # montant = TOTAL viré ; 80 د.م./mois -> total = 80 * nb_mois, réparti
        # à parts égales (chaque Paiement frère porte donc 80).
        c.post(reverse('eleve_paiements'), {
            'nb_mois': str(nb_mois), 'montant': str(80 * nb_mois), 'screenshot': _screenshot(),
        })
        return list(Paiement.objects.filter(eleve=self.eleve, montant=80).order_by('mois_reference'))

    def test_detail_affiche_la_duree_totale_de_la_demande(self):
        paiements = self._payer(3)  # 5/08, 5/09, 5/10 -> demande 5/08 -> 5/11 exclu
        reponse = self.client.get(reverse('admin_paiement_detail', args=[paiements[0].id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context['periode_debut'], datetime.date(2026, 8, 5))
        self.assertEqual(reponse.context['periode_fin'], datetime.date(2026, 11, 5))
        self.assertContains(reponse, '05/08/2026')
        self.assertContains(reponse, '05/11/2026')

    def test_detail_ne_montre_pas_le_detail_mois_par_mois(self):
        paiements = self._payer(3)  # bornes intermédiaires 5/09 et 5/10
        reponse = self.client.get(reverse('admin_paiement_detail', args=[paiements[0].id]))
        self.assertNotIn('lot_periodes', reponse.context)
        self.assertNotContains(reponse, '05/09/2026')
        self.assertNotContains(reponse, '05/10/2026')

    def test_detail_paiement_isole_duree_dun_seul_mois(self):
        p = Paiement.objects.create(
            eleve=self.eleve, montant=55, mois_reference=datetime.date(2026, 8, 5),
        )
        reponse = self.client.get(reverse('admin_paiement_detail', args=[p.id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context['periode_debut'], datetime.date(2026, 8, 5))
        self.assertEqual(reponse.context['periode_fin'], datetime.date(2026, 9, 5))

    def test_lot_ne_melange_pas_deux_soumissions_de_montants_differents(self):
        self._payer(2)  # montant 80
        autre = Paiement.objects.create(
            eleve=self.eleve, montant=999, mois_reference=datetime.date(2026, 10, 5),
        )
        reponse = self.client.get(reverse('admin_paiement_detail', args=[autre.id]))
        self.assertEqual(reponse.context['periode_debut'], datetime.date(2026, 10, 5))
        self.assertEqual(reponse.context['periode_fin'], datetime.date(2026, 11, 5))
