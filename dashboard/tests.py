import datetime
import time

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User, Eleve, Prof, Superviseur
from courses.models import (
    Groupe, Seance, Presence, BilanMensuel, HistoriqueGroupeEleve,
    DisponibiliteEleve, DisponibiliteProf, DemandeModificationDisponibilite,
)
from evaluations.models import Evaluation, CommentaireMensuel
from inscriptions.models import InscriptionEleve
from payments.models import Paiement


# Chantier du 2026-08-12 — suppression définitive de Eleve/Prof/Superviseur.
# Même précaution que inscriptions.tests (STORAGES) : toute page qui étend
# base_admin.html charge le logo du header, ce qui lève une ValueError sans
# cet override (whitenoise exige un manifeste jamais généré en local/tests).
_STORAGES_TEST = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _attendre_absence_fichier(storage, chemin, tentatives=5, delai=1.5):
    """Cloudinary (storage réel utilisé en local via CLOUDINARY_CLOUD_NAME, voir
    .env) n'est pas garanti strictement synchrone entre un DELETE et le EXISTS
    qui suit — léger délai de propagation constaté en pratique (le test
    isolé passe systématiquement, le même test au sein de la suite complète a
    déjà échoué une fois sur un simple exists() trop rapide). Ce n'est pas une
    tolérance sur notre code (le signal appelle bien storage.delete() de façon
    synchrone, voir payments.signals) — uniquement sur la cohérence éventuelle
    du service tiers. Échoue pour de vrai si le fichier est TOUJOURS là après
    ~7.5s cumulées."""
    for _ in range(tentatives):
        if not storage.exists(chemin):
            return True
        time.sleep(delai)
    return not storage.exists(chemin)


def _creer_admin():
    return User.objects.create_user(
        username='admin_test_suppr@zidni.test', email='admin_test_suppr@zidni.test',
        password='xX!test12345', role='admin', doit_changer_mot_de_passe=False,
    )


def _creer_mshrif():
    return User.objects.create_user(
        username='mshrif_test_suppr@zidni.test', email='mshrif_test_suppr@zidni.test',
        password='xX!test12345', role='mshrif', doit_changer_mot_de_passe=False,
    )


def _creer_eleve(email='eleve_test_suppr@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme')


def _creer_prof(email='prof_test_suppr@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='أستاذ', last_name='تجريبي', role='prof', doit_changer_mot_de_passe=False,
    )
    return Prof.objects.create(user=u, ville='الرباط', niveau_memorisation='كامل')


def _creer_superviseur(email='superviseur_test_suppr@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='مؤطر', last_name='تجريبي', role='superviseur', doit_changer_mot_de_passe=False,
    )
    return Superviseur.objects.create(user=u)


@override_settings(STORAGES=_STORAGES_TEST)
class EleveSuppressionDefinitiveTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)

    def test_suppression_reussie_emporte_tout_ce_qui_appartient_a_lelve(self):
        eleve = _creer_eleve()
        eleve_id, user_id = eleve.id, eleve.user_id
        groupe = Groupe.objects.create(nom='مجموعة تجريبية')
        seance = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 1), heure='14:00', type='normal')
        presence = Presence.objects.create(seance=seance, eleve=eleve)
        prof = _creer_prof('prof_bilan_eleve@zidni.test')
        bilan = BilanMensuel.objects.create(eleve=eleve, prof=prof, mois_reference=datetime.date(2026, 8, 1))
        histo = HistoriqueGroupeEleve.objects.create(eleve=eleve, groupe=groupe)
        dispo = DisponibiliteEleve.objects.create(eleve=eleve, jour_semaine='lun', heure_debut='14:00')
        inscription = InscriptionEleve.objects.create(
            nom='طالب تجريبي', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000000', email='eleve_test_suppr@zidni.test',
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='valide',
        )
        eleve.inscription = inscription
        eleve.save(update_fields=['inscription'])

        response = self.client.post(
            reverse('eleve_supprimer_definitivement', args=[eleve_id]),
            {'confirmation_nom': 'eleve_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_eleves'))

        self.assertFalse(User.objects.filter(id=user_id).exists())
        self.assertFalse(Eleve.objects.filter(id=eleve_id).exists())
        self.assertFalse(Presence.objects.filter(id=presence.id).exists())
        self.assertFalse(HistoriqueGroupeEleve.objects.filter(id=histo.id).exists())
        self.assertFalse(DisponibiliteEleve.objects.filter(id=dispo.id).exists())
        # Ce bilan appartient à L'ÉLÈVE supprimé ici (eleve=FK CASCADE, resté
        # ainsi à raison) — il disparaît avec lui, contrairement au test symétrique
        # côté Prof (ProfSuppressionDefinitiveTests) où c'est prof=FK(SET_NULL)
        # qui est exercé : même modèle, deux directions de suppression différentes.
        self.assertFalse(BilanMensuel.objects.filter(id=bilan.id).exists())

        # Détaché, pas supprimé : la candidature survit, avec son statut basculé
        # automatiquement par accounts.signals.rejeter_inscription_eleve_a_la_suppression.
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'rejete')

        # Le groupe lui-même n'est jamais touché.
        self.assertTrue(Groupe.objects.filter(id=groupe.id).exists())

    def test_page_confirmation_s_affiche_correctement(self):
        eleve = _creer_eleve()
        response = self.client.get(reverse('eleve_supprimer_definitivement', args=[eleve.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(eleve.user.email, response.content.decode('utf-8'))

    def test_paiements_et_justificatif_reellement_supprimes(self):
        """Correction du 2026-08-12 (décision explicite du client) : Paiement
        n'est plus bloquant, il est emporté en cascade comme le reste — y
        compris le fichier physique du justificatif sur le storage (pas
        seulement la ligne en base), via payments.signals."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        eleve = _creer_eleve()
        justificatif = SimpleUploadedFile(
            'recu_test_suppr.jpg', b'contenu-de-test-jetable', content_type='image/jpeg'
        )
        paiement = Paiement.objects.create(
            eleve=eleve, montant=80, mois_reference=datetime.date(2026, 8, 1), screenshot=justificatif,
        )
        storage = paiement.screenshot.storage
        chemin_fichier = paiement.screenshot.name
        self.assertTrue(storage.exists(chemin_fichier))

        # La page de confirmation avertit désormais du montant, sans bloquer.
        response_get = self.client.get(reverse('eleve_supprimer_definitivement', args=[eleve.id]))
        self.assertEqual(response_get.status_code, 200)
        contenu_get = response_get.content.decode('utf-8')
        self.assertIn('name="confirmation_nom"', contenu_get)
        self.assertIn('80', contenu_get)

        response = self.client.post(
            reverse('eleve_supprimer_definitivement', args=[eleve.id]),
            {'confirmation_nom': 'eleve_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_eleves'))

        self.assertFalse(User.objects.filter(id=eleve.user_id).exists())
        self.assertFalse(Paiement.objects.filter(id=paiement.id).exists())
        # Pas seulement détaché de la base : le fichier lui-même a disparu du storage.
        self.assertTrue(
            _attendre_absence_fichier(storage, chemin_fichier),
            'le fichier justificatif existe encore sur le storage après suppression',
        )

    def test_mauvais_email_ne_supprime_rien(self):
        eleve = _creer_eleve()
        response = self.client.post(
            reverse('eleve_supprimer_definitivement', args=[eleve.id]),
            {'confirmation_nom': 'mauvais@email.test'},
        )
        self.assertRedirects(response, reverse('admin_eleve_detail', args=[eleve.id]))
        self.assertTrue(User.objects.filter(id=eleve.user_id).exists())
        self.assertTrue(Eleve.objects.filter(id=eleve.id).exists())

    def test_mshrif_refuse(self):
        self.client.force_login(_creer_mshrif())
        eleve = _creer_eleve()
        response = self.client.post(
            reverse('eleve_supprimer_definitivement', args=[eleve.id]),
            {'confirmation_nom': 'eleve_test_suppr@zidni.test'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse('admin_eleves'))
        self.assertTrue(User.objects.filter(id=eleve.user_id).exists())
        self.assertTrue(Eleve.objects.filter(id=eleve.id).exists())


@override_settings(STORAGES=_STORAGES_TEST)
class ProfSuppressionDefinitiveTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)

    def test_suppression_reussie_detache_sans_effet_domino_sur_le_groupe(self):
        prof = _creer_prof()
        prof_id, user_id = prof.id, prof.user_id
        groupe = Groupe.objects.create(nom='مجموعة الأستاذ', prof=prof, statut='actif')
        dispo = DisponibiliteProf.objects.create(prof=prof, jour_semaine='lun', heure_debut='14:00')
        demande = DemandeModificationDisponibilite.objects.create(prof=prof)
        commentaire = CommentaireMensuel.objects.create(prof=prof, mois_reference=datetime.date(2026, 8, 1))
        eleve = _creer_eleve('eleve_bilan_prof@zidni.test')
        bilan = BilanMensuel.objects.create(eleve=eleve, prof=prof, mois_reference=datetime.date(2026, 8, 1))

        response = self.client.post(
            reverse('prof_supprimer_definitivement', args=[prof_id]),
            {'confirmation_nom': 'prof_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_profs'))

        self.assertFalse(User.objects.filter(id=user_id).exists())
        self.assertFalse(Prof.objects.filter(id=prof_id).exists())
        self.assertFalse(DisponibiliteProf.objects.filter(id=dispo.id).exists())
        self.assertFalse(DemandeModificationDisponibilite.objects.filter(id=demande.id).exists())
        self.assertFalse(CommentaireMensuel.objects.filter(id=commentaire.id).exists())

        # Le groupe survit, juste détaché (déjà SET_NULL avant ce chantier).
        groupe.refresh_from_db()
        self.assertIsNone(groupe.prof)

        # Le bilan survit sur le dossier de l'élève, juste détaché (corrigé par ce chantier).
        bilan.refresh_from_db()
        self.assertIsNone(bilan.prof)
        self.assertEqual(bilan.eleve_id, eleve.id)

    def test_page_confirmation_s_affiche_correctement(self):
        prof = _creer_prof()
        response = self.client.get(reverse('prof_supprimer_definitivement', args=[prof.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(prof.user.email, response.content.decode('utf-8'))

    def test_mauvais_email_ne_supprime_rien(self):
        prof = _creer_prof()
        response = self.client.post(
            reverse('prof_supprimer_definitivement', args=[prof.id]),
            {'confirmation_nom': 'mauvais@email.test'},
        )
        self.assertRedirects(response, reverse('admin_prof_detail', args=[prof.id]))
        self.assertTrue(Prof.objects.filter(id=prof.id).exists())

    def test_mshrif_refuse(self):
        self.client.force_login(_creer_mshrif())
        prof = _creer_prof()
        response = self.client.post(
            reverse('prof_supprimer_definitivement', args=[prof.id]),
            {'confirmation_nom': 'prof_test_suppr@zidni.test'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse('admin_profs'))
        self.assertTrue(Prof.objects.filter(id=prof.id).exists())


@override_settings(STORAGES=_STORAGES_TEST)
class SuperviseurSuppressionDefinitiveTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)

    def test_suppression_reussie_detache_sans_effet_domino_sur_le_prof(self):
        superviseur = _creer_superviseur()
        superviseur_id, user_id = superviseur.id, superviseur.user_id
        prof = _creer_prof('prof_supervise@zidni.test')
        superviseur.profs_assignes.add(prof)
        groupe = Groupe.objects.create(nom='مجموعة', prof=prof)
        seance = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 1), heure='14:00', type='normal')
        evaluation = Evaluation.objects.create(superviseur=superviseur, seance=seance, commentaire='ملاحظة')

        response = self.client.post(
            reverse('superviseur_supprimer_definitivement', args=[superviseur_id]),
            {'confirmation_nom': 'superviseur_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_superviseurs'))

        self.assertFalse(User.objects.filter(id=user_id).exists())
        self.assertFalse(Superviseur.objects.filter(id=superviseur_id).exists())

        # Le prof survit, simplement non supervisé désormais.
        self.assertTrue(Prof.objects.filter(id=prof.id).exists())

        # L'évaluation survit sur le dossier du prof, juste détachée (corrigé par ce chantier).
        evaluation.refresh_from_db()
        self.assertIsNone(evaluation.superviseur)
        self.assertEqual(evaluation.seance_id, seance.id)

    def test_page_confirmation_s_affiche_correctement(self):
        superviseur = _creer_superviseur()
        response = self.client.get(reverse('superviseur_supprimer_definitivement', args=[superviseur.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn(superviseur.user.email, response.content.decode('utf-8'))

    def test_mauvais_email_ne_supprime_rien(self):
        superviseur = _creer_superviseur()
        response = self.client.post(
            reverse('superviseur_supprimer_definitivement', args=[superviseur.id]),
            {'confirmation_nom': 'mauvais@email.test'},
        )
        self.assertRedirects(response, reverse('admin_superviseurs'))
        self.assertTrue(Superviseur.objects.filter(id=superviseur.id).exists())

    def test_mshrif_refuse(self):
        self.client.force_login(_creer_mshrif())
        superviseur = _creer_superviseur()
        response = self.client.post(
            reverse('superviseur_supprimer_definitivement', args=[superviseur.id]),
            {'confirmation_nom': 'superviseur_test_suppr@zidni.test'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse('admin_superviseurs'))
        self.assertTrue(Superviseur.objects.filter(id=superviseur.id).exists())


@override_settings(STORAGES=_STORAGES_TEST)
class AffichageDonneesDetacheesTests(TestCase):
    """Vérifie qu'une donnée détachée (auteur supprimé) s'affiche proprement —
    repli explicite '[حساب محذوف]', jamais un 'None' brut ni une page cassée."""

    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)

    def test_bilan_sans_prof_affiche_repli_et_reste_consultable_par_le_superviseur(self):
        eleve = _creer_eleve()
        # prof=None simule directement l'état après suppression définitive du prof
        # (SET_NULL) — pas besoin de repasser par tout le flux de suppression ici.
        bilan = BilanMensuel.objects.create(eleve=eleve, prof=None, mois_reference=datetime.date(2026, 8, 1))

        response = self.client.get(reverse('bilan_mensuel_detail', args=[eleve.id, '2026-08']))
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('[حساب محذوف]', contenu)
        self.assertNotRegex(contenu, r'بقلم\s*None')

        # Un مؤطر (n'importe lequel, sans supervision particulière sur ce dossier)
        # ne doit plus être bloqué par le contrôle de périmètre — voir le correctif
        # de dashboard.views.bilan_mensuel_detail (prof is not None).
        self.client.force_login(_creer_superviseur('autre_superviseur@zidni.test').user)
        response = self.client.get(reverse('bilan_mensuel_detail', args=[eleve.id, '2026-08']))
        self.assertEqual(response.status_code, 200)

    def test_evaluation_sans_superviseur_affiche_repli(self):
        groupe = Groupe.objects.create(nom='مجموعة')
        seance = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 1), heure='14:00', type='normal')
        Evaluation.objects.create(superviseur=None, seance=seance, commentaire='ملاحظة')

        response = self.client.get(reverse('admin_evaluation_detail', args=[seance.id]))
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('[حساب محذوف]', contenu)
        self.assertNotRegex(contenu, r'بواسطة\s*None')

        response = self.client.get(reverse('admin_evaluations'))
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('[حساب محذوف]', contenu)
