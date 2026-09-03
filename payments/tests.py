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


# Chantier « Paiement unique » du 2026-09-03 : le formulaire /payments/eleve/
# demande la DATE DE DÉBUT (choisie par l'élève, pré-remplie avec le début de
# son cycle ouvert), le NOMBRE DE MOIS et le MONTANT TOTAL viré. Résultat = UN
# SEUL Paiement (`nb_mois_couverts`, montant total, 1 justificatif). Le
# rapprochement avec les CycleAbonnement se fait au mois près sur la fenêtre
# couverte [mois_reference, +nb_mois_couverts[.
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
        p = paiements.first()
        self.assertEqual(p.mois_reference, datetime.date(2026, 8, 5))  # défaut = début du cycle
        self.assertEqual(p.nb_mois_couverts, 1)
        self.assertEqual(p.montant, 80)

    def test_plusieurs_mois_un_seul_paiement_montant_total(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'nb_mois': '3', 'montant': '240', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        paiements = Paiement.objects.filter(eleve=self.eleve)
        self.assertEqual(paiements.count(), 1)  # UN SEUL, pas trois
        p = paiements.first()
        self.assertEqual(p.mois_reference, datetime.date(2026, 8, 5))
        self.assertEqual(p.nb_mois_couverts, 3)
        self.assertEqual(p.montant, 240)
        self.assertEqual(p.periode_fin, datetime.date(2026, 11, 5))
        self.assertEqual(p.montant_par_mois, Decimal('80.00'))

    def test_eleve_choisit_sa_date_de_debut(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-10-15', 'nb_mois': '2', 'montant': '160', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        p = Paiement.objects.get(eleve=self.eleve)
        self.assertEqual(p.mois_reference, datetime.date(2026, 10, 15))
        self.assertEqual(p.nb_mois_couverts, 2)

    def test_montant_zero_ou_invalide_refuse_sans_rien_creer(self):
        for valeur in ('0', '-5', 'abc', ''):
            reponse = self.client.post(reverse('eleve_paiements'), {
                'nb_mois': '1', 'montant': valeur, 'screenshot': _screenshot(),
            })
            self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_mois_deja_couvert_refuse_la_soumission(self):
        # Paiement existant couvrant août+septembre.
        Paiement.objects.create(
            eleve=self.eleve, montant=160, mois_reference=datetime.date(2026, 8, 5), nb_mois_couverts=2,
        )
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-09-05', 'nb_mois': '2', 'montant': '160', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        # Rien de neuf : septembre est déjà couvert.
        self.assertEqual(Paiement.objects.filter(eleve=self.eleve).count(), 1)

    def test_paiement_rejete_ne_bloque_pas_un_nouveau_pour_le_meme_mois(self):
        Paiement.objects.create(
            eleve=self.eleve, montant=80, mois_reference=datetime.date(2026, 8, 5), statut='rejete',
        )
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-08-20', 'nb_mois': '1', 'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertEqual(Paiement.objects.filter(eleve=self.eleve).exclude(statut='rejete').count(), 1)

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


# La fiche /payments/admin/<id>/ montre « la durée de la demande » (span début
# → fin exclusive), jamais le détail mois par mois. Cas courant : un seul
# Paiement avec nb_mois_couverts. Fallback legacy : lot de Paiement d'1 mois.
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

    def test_detail_affiche_la_duree_totale_dun_paiement_multi_mois(self):
        p = Paiement.objects.create(
            eleve=self.eleve, montant=240, mois_reference=datetime.date(2026, 8, 5), nb_mois_couverts=3,
        )
        reponse = self.client.get(reverse('admin_paiement_detail', args=[p.id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context['periode_debut'], datetime.date(2026, 8, 5))
        self.assertEqual(reponse.context['periode_fin'], datetime.date(2026, 11, 5))

    def test_detail_ne_montre_pas_le_detail_mois_par_mois(self):
        p = Paiement.objects.create(
            eleve=self.eleve, montant=240, mois_reference=datetime.date(2026, 8, 5), nb_mois_couverts=3,
        )
        reponse = self.client.get(reverse('admin_paiement_detail', args=[p.id]))
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

    def test_fallback_legacy_regroupe_les_paiements_dun_mois_dune_meme_soumission(self):
        # Simule d'anciennes données : 2 Paiement d'1 mois, même montant, créés
        # coup sur coup (avant la migration 0011).
        p1 = Paiement.objects.create(eleve=self.eleve, montant=80, mois_reference=datetime.date(2026, 8, 5))
        Paiement.objects.create(eleve=self.eleve, montant=80, mois_reference=datetime.date(2026, 9, 5))
        reponse = self.client.get(reverse('admin_paiement_detail', args=[p1.id]))
        self.assertEqual(reponse.context['periode_debut'], datetime.date(2026, 8, 5))
        self.assertEqual(reponse.context['periode_fin'], datetime.date(2026, 10, 5))
