import datetime

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


# Chantier du 2026-08-24 : sélecteur de PÉRIODE ("من تاريخ"/"إلى تاريخ") sur
# /payments/eleve/, en remplacement du champ "combien de mois payer" retiré
# de l'inscription (voir registration.utils, plus de nombre_mois_payes) — un
# Paiement PAR mois de la période, jamais un seul Paiement "regroupé"
# (unique_together (eleve, mois_reference) inchangé, voir Paiement.__doc__
# et payments.views.suivi_paiements_eleves qui compte déjà mois par mois).
@override_settings(STORAGES=_STORAGES_TEST)
class EleveePaiementsPeriodeTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve()
        self.client = Client()
        self.client.force_login(self.eleve.user)

    def test_periode_dun_seul_mois_cree_un_seul_paiement_comme_avant(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-08-05', 'date_fin': '2026-08-20',
            'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        paiements = Paiement.objects.filter(eleve=self.eleve)
        self.assertEqual(paiements.count(), 1)
        self.assertEqual(paiements.first().mois_reference, datetime.date(2026, 8, 1))
        self.assertEqual(paiements.first().montant, 80)

    def test_periode_de_plusieurs_mois_cree_un_paiement_par_mois_meme_montant(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-06-15', 'date_fin': '2026-08-03',
            'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        paiements = Paiement.objects.filter(eleve=self.eleve).order_by('mois_reference')
        self.assertEqual(list(paiements.values_list('mois_reference', flat=True)), [
            datetime.date(2026, 6, 1), datetime.date(2026, 7, 1), datetime.date(2026, 8, 1),
        ])
        self.assertTrue(all(p.montant == 80 for p in paiements))
        # Chaque Paiement a bien SA PROPRE copie du justificatif (fichiers
        # distincts, pas le même objet UploadedFile épuisé après le 1er .save()).
        noms_fichiers = {p.screenshot.name for p in paiements}
        self.assertEqual(len(noms_fichiers), 3)
        for p in paiements:
            self.assertTrue(p.screenshot.storage.exists(p.screenshot.name))

    def test_mois_deja_existant_dans_la_periode_est_ignore_sans_erreur(self):
        Paiement.objects.create(eleve=self.eleve, montant=80, mois_reference=datetime.date(2026, 7, 1))
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-06-01', 'date_fin': '2026-08-01',
            'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        # Toujours UN SEUL Paiement pour juillet (celui déjà là), pas de doublon,
        # pas de 500 (IntegrityError unique_together évitée) — juin et août créés.
        self.assertEqual(
            Paiement.objects.filter(eleve=self.eleve, mois_reference__month=7).count(), 1
        )
        self.assertTrue(Paiement.objects.filter(eleve=self.eleve, mois_reference__month=6).exists())
        self.assertTrue(Paiement.objects.filter(eleve=self.eleve, mois_reference__month=8).exists())

    def test_date_fin_avant_date_debut_refusee_sans_rien_creer(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-08-01', 'date_fin': '2026-06-01',
            'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_periode_trop_longue_refusee_sans_rien_creer(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2020-01-01', 'date_fin': '2026-08-01',
            'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_dates_invalides_refusees_sans_rien_creer(self):
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': 'pas-une-date', 'date_fin': '2026-08-01',
            'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())

    def test_eleve_archive_ne_peut_pas_soumettre(self):
        self.eleve.statut = 'archive'
        self.eleve.save(update_fields=['statut'])
        reponse = self.client.post(reverse('eleve_paiements'), {
            'date_debut': '2026-08-01', 'date_fin': '2026-08-01',
            'montant': '80', 'screenshot': _screenshot(),
        })
        self.assertRedirects(reponse, reverse('eleve_paiements'))
        self.assertFalse(Paiement.objects.filter(eleve=self.eleve).exists())
