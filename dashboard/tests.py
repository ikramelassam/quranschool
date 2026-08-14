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
from inscriptions.models import InscriptionEleve, InscriptionProf, PhraseRefus
from payments.models import Paiement
from dashboard.views import GABARIT_REFUS_AVANT_MOTIF, GABARIT_REFUS_APRES_MOTIF


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

    def test_mshrif_autorise(self):
        """مشرف a désormais accès aux 3 suppressions définitives (Tâche du
        2026-08-13, point 3) — inversion assumée de l'ancien test_mshrif_refuse,
        qui documentait le comportement opposé avant cette décision."""
        self.client.force_login(_creer_mshrif())
        eleve = _creer_eleve()
        response = self.client.post(
            reverse('eleve_supprimer_definitivement', args=[eleve.id]),
            {'confirmation_nom': 'eleve_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_eleves'))
        self.assertFalse(User.objects.filter(id=eleve.user_id).exists())
        self.assertFalse(Eleve.objects.filter(id=eleve.id).exists())


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

    def test_evaluation_disparait_en_cascade_alors_que_presence_et_bilan_survivent(self):
        """Tâche du 2026-08-13, point 6 — verrouille dans le MÊME test les deux
        comportements opposés pour ne pas les confondre : Evaluation.prof est
        CASCADE (le prof est le SUJET évalué, voir evaluations.models.Evaluation),
        alors que Presence (via l'élève, jamais touché ici) et BilanMensuel.prof
        (SET_NULL, voir courses.models.BilanMensuel) survivent tous les deux à
        la suppression du même prof."""
        prof = _creer_prof()
        prof_id = prof.id
        eleve = _creer_eleve('eleve_cascade_eval@zidni.test')
        groupe = Groupe.objects.create(nom='مجموعة التقييم', prof=prof, statut='actif')
        groupe.eleves.add(eleve)
        seance = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 1), heure='14:00', type='normal')
        superviseur = _creer_superviseur('superviseur_cascade_eval@zidni.test')

        presence = Presence.objects.create(seance=seance, eleve=eleve, statut='present')
        bilan = BilanMensuel.objects.create(eleve=eleve, prof=prof, mois_reference=datetime.date(2026, 8, 1))
        evaluation = Evaluation.objects.create(
            superviseur=superviseur, prof=prof, seance=seance, commentaire='ملاحظة',
        )
        evaluation_id = evaluation.id

        response = self.client.post(
            reverse('prof_supprimer_definitivement', args=[prof_id]),
            {'confirmation_nom': 'prof_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_profs'))

        # CASCADE : l'évaluation du prof disparaît avec lui.
        self.assertFalse(Evaluation.objects.filter(id=evaluation_id).exists())

        # SET_NULL / non concerné : Presence et BilanMensuel survivent, juste
        # détachés pour le bilan (l'élève, lui, n'a pas bougé).
        presence.refresh_from_db()
        self.assertEqual(presence.eleve_id, eleve.id)
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

    def test_mshrif_autorise(self):
        """Voir même commentaire que EleveSuppressionDefinitiveTests.test_mshrif_autorise."""
        self.client.force_login(_creer_mshrif())
        prof = _creer_prof()
        response = self.client.post(
            reverse('prof_supprimer_definitivement', args=[prof.id]),
            {'confirmation_nom': 'prof_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_profs'))
        self.assertFalse(Prof.objects.filter(id=prof.id).exists())


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

    def test_mshrif_autorise(self):
        """Voir même commentaire que EleveSuppressionDefinitiveTests.test_mshrif_autorise."""
        self.client.force_login(_creer_mshrif())
        superviseur = _creer_superviseur()
        response = self.client.post(
            reverse('superviseur_supprimer_definitivement', args=[superviseur.id]),
            {'confirmation_nom': 'superviseur_test_suppr@zidni.test'},
        )
        self.assertRedirects(response, reverse('admin_superviseurs'))
        self.assertFalse(Superviseur.objects.filter(id=superviseur.id).exists())


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


@override_settings(STORAGES=_STORAGES_TEST)
class RechercheGlobaleTests(TestCase):
    """Chantier 1 du 2026-08-14 — recherche globale (مدير/مشرف)."""

    def setUp(self):
        self.admin = _creer_admin()

    def _rechercher(self, q):
        return self.client.get(reverse('api_recherche_globale'), {'q': q})

    def test_resultats_exacts_par_categorie(self):
        self.client.force_login(self.admin)
        eleve = _creer_eleve('eleve_recherche@zidni.test')
        eleve.user.first_name, eleve.user.last_name = 'أحمد', 'الفاسي'
        eleve.user.save()
        prof = _creer_prof('prof_recherche@zidni.test')
        prof.user.first_name, prof.user.last_name = 'كريم', 'العلمي'
        prof.user.save()
        prof.ville = 'الدار البيضاء'
        prof.save()
        superviseur = _creer_superviseur('superviseur_recherche@zidni.test')
        superviseur.user.first_name, superviseur.user.last_name = 'سعيد', 'بنعلي'
        superviseur.user.save()
        groupe = Groupe.objects.create(nom='مجموعة الفجر الفريدة', statut='actif')

        data = self._rechercher('الفاسي').json()
        cat = next(c for c in data['categories'] if c['cle'] == 'eleves')
        self.assertEqual(len(cat['resultats']), 1)
        self.assertEqual(cat['resultats'][0]['id'], eleve.id)

        data = self._rechercher('الدار البيضاء').json()
        cat = next(c for c in data['categories'] if c['cle'] == 'profs')
        self.assertEqual([r['id'] for r in cat['resultats']], [prof.id])

        data = self._rechercher('بنعلي').json()
        cat = next(c for c in data['categories'] if c['cle'] == 'superviseurs')
        self.assertEqual([r['id'] for r in cat['resultats']], [superviseur.id])

        data = self._rechercher('الفجر الفريدة').json()
        cat = next(c for c in data['categories'] if c['cle'] == 'groupes')
        self.assertEqual([r['id'] for r in cat['resultats']], [groupe.id])

    def test_voir_tout_groupes_transmet_q_et_filtre_reellement(self):
        """Correction du 2026-08-14 : le lien 'voir tous les résultats' de la
        catégorie groupes doit transmettre ?q= à admin_groupes (courses.
        groupes_list), comme les autres catégories le font déjà — et cette
        page doit réellement filtrer, pas juste accepter le paramètre sans
        effet."""
        self.client.force_login(self.admin)
        for i in range(7):
            Groupe.objects.create(nom=f'مجموعة الفجر الفريدة {i}', statut='actif')
        Groupe.objects.create(nom='مجموعة بدون علاقة بالبحث', statut='actif')

        data = self._rechercher('الفجر الفريدة').json()
        cat = next(c for c in data['categories'] if c['cle'] == 'groupes')
        self.assertTrue(cat['a_plus'])
        self.assertIsNotNone(cat['voir_tout_url'])
        self.assertIn('?q=', cat['voir_tout_url'])

        response = self.client.get(cat['voir_tout_url'])
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('الفجر الفريدة', contenu)
        self.assertNotIn('مجموعة بدون علاقة بالبحث', contenu)

    def test_tolerance_aux_fautes_de_frappe_via_trigram(self):
        """icontains seul ne matcherait PAS 'Ahmad' contre 'Ahmed' — ce test
        échouerait si le trigram_similar était retiré du filtrage."""
        self.client.force_login(self.admin)
        eleve = _creer_eleve('eleve_trigram@zidni.test')
        eleve.user.first_name, eleve.user.last_name = 'Ahmed', 'Test'
        eleve.user.save()

        data = self._rechercher('Ahmad').json()
        cat = next(c for c in data['categories'] if c['cle'] == 'eleves')
        self.assertIn(eleve.id, [r['id'] for r in cat['resultats']])

    def test_match_exact_en_tete(self):
        self.client.force_login(self.admin)
        exact = _creer_eleve('exact_recherche@zidni.test')
        exact.user.first_name, exact.user.last_name = 'Nour', 'Amrani'
        exact.user.save()
        approche = _creer_eleve('approche_recherche@zidni.test')
        approche.user.first_name, approche.user.last_name = 'Nourane', 'Amranioui'
        approche.user.save()

        data = self._rechercher('Nour Amrani').json()
        cat = next(c for c in data['categories'] if c['cle'] == 'eleves')
        ids = [r['id'] for r in cat['resultats']]
        self.assertIn(exact.id, ids)
        # Le match exact (iexact sur au moins un champ n'existe pas ici sur le nom
        # complet, mais first_name='Nour' est exact pour `exact`) doit sortir
        # avant l'approximatif s'il apparaît aussi dans les résultats.
        if approche.id in ids:
            self.assertLess(ids.index(exact.id), ids.index(approche.id))

    def test_mshrif_voit_exactement_les_memes_resultats_que_admin(self):
        """مشرف n'est PAS scopé différemment de مدير sur Eleve/Prof/Superviseur/
        Groupe (vérifié dans admin_eleves/admin_profs/admin_superviseurs —
        aucune des 3 vues ne filtre par rôle sur le queryset). Ce test
        verrouille cette identité pour la recherche globale aussi, contre une
        future régression accidentelle."""
        eleve = _creer_eleve('eleve_scope_recherche@zidni.test')
        eleve.user.first_name = 'ScopeTest'
        eleve.user.save()

        self.client.force_login(self.admin)
        resultats_admin = self._rechercher('ScopeTest').json()

        self.client.logout()
        self.client.force_login(_creer_mshrif())
        resultats_mshrif = self._rechercher('ScopeTest').json()

        self.assertEqual(resultats_admin['categories'], resultats_mshrif['categories'])

    def test_autres_roles_refuses(self):
        eleve_connecte = _creer_eleve('eleve_acces_recherche@zidni.test')
        self.client.force_login(eleve_connecte.user)
        response = self._rechercher('test')
        # role_required redirige vers le dashboard du rôle, pas de JSON renvoyé.
        self.assertEqual(response.status_code, 302)

    def test_requete_vide_courte_et_speciale_sans_crash(self):
        self.client.force_login(self.admin)
        for q in ['', 'a', "%_'; DROP TABLE accounts_user;--", 'x' * 500]:
            response = self._rechercher(q)
            self.assertEqual(response.status_code, 200)
        data = self._rechercher('').json()
        self.assertEqual(data['categories'], [])

    def test_detection_du_mois(self):
        self.client.force_login(self.admin)
        for q in ['07/2026', '2026-07']:
            data = self._rechercher(q).json()
            self.assertIsNotNone(data['mois'])
            self.assertEqual(data['mois']['valeur'], '2026-07')
        # Une requête normale ne doit jamais être prise pour un mois.
        data = self._rechercher('Ahmed').json()
        self.assertIsNone(data['mois'])

    def test_une_seule_requete_sql_quel_que_soit_le_nombre_de_categories(self):
        """LE vrai verrou de perf, déterministe (contrairement au chrono
        ci-dessous, sensible à la latence réseau — voir sa docstring) :
        rechercher_tout doit toujours tenir en 1 aller-retour SQL (union() de
        4 projections), jamais 4 requêtes séparées (1 par modèle) ni un N+1
        caché dans la construction titre/contexte. Mesuré sur l'appel direct
        à rechercher_tout (pas via self.client) : passer par le Client ajoute
        2 requêtes de session/auth (session_key puis get_user) qui ne sont
        pas spécifiques à cette vue — n'importe quelle page authentifiée les
        paie, ça brouillerait la mesure de CE composant précis."""
        eleve = _creer_eleve('eleve_nb_requetes@zidni.test')
        eleve.user.first_name = 'NbRequetesTest'
        eleve.user.save()

        from dashboard.recherche import rechercher_tout
        with self.assertNumQueries(1):
            mois, categories = rechercher_tout('NbRequetesTest')
        self.assertTrue(any(c['resultats'] for c in categories))

    def test_temps_de_reponse_mesure(self):
        """Chrono informatif, PAS le verrou principal (voir le test précédent,
        déterministe) : la base de dev/test est un Postgres DISTANT (Supabase,
        pooler eu-west-1 — voir docstring perf de dashboard.recherche), donc
        chaque mesure inclut une latence réseau réelle et variable, hors du
        contrôle du code applicatif (mesuré manuellement entre 150ms et
        ~2400ms selon les conditions réseau du moment — dépassé une fois les
        2000ms initiaux au sein de la suite complète, probablement de la
        contention réseau avec les tests voisins — pour une même requête
        après optimisation à 1 seul aller-retour SQL). Seuil volontairement
        très généreux (5s) : sert à attraper une VRAIE régression grossière
        (ex: un retour accidentel à 4 requêtes séparées, ou un N+1), pas à
        garantir un SLA réseau que ce test ne peut pas contrôler — c'est
        test_une_seule_requete_sql_... ci-dessus qui verrouille réellement
        la performance, de façon déterministe."""
        self.client.force_login(self.admin)
        for i in range(15):
            e = _creer_eleve(f'perf_recherche_{i}@zidni.test')
            e.user.first_name = f'PerfTest{i}'
            e.user.save()

        debut = time.monotonic()
        response = self._rechercher('PerfTest')
        duree_ms = (time.monotonic() - debut) * 1000
        self.assertEqual(response.status_code, 200)
        self.assertLess(duree_ms, 5000, f"recherche anormalement lente : {duree_ms:.0f}ms")


@override_settings(STORAGES=_STORAGES_TEST)
class SelectsCherchablesTests(TestCase):
    """Chantier 2 du 2026-08-14 — selects cherchables. Le comportement de
    filtrage lui-même est du JS pur (voir templates/dashboard/_select_cherchable.html) :
    non testable ici sans navigateur (aucun outil de ce type disponible dans
    cette session). Ce qui EST vérifié côté serveur : le composant est bien
    inclus dans les 5 bases (une seule fois, pas dupliqué), l'attribut
    data-select-cherchable est bien posé sur les <select> validés au B1, et
    la soumission de formulaire reste identique à avant (aucune régression
    backend — l'attribut est inerte côté serveur, il ne change ni le name ni
    la value envoyés)."""

    def setUp(self):
        self.admin = _creer_admin()

    def test_composant_inclus_une_seule_fois_par_page_sur_les_5_roles(self):
        cas = [
            (self.admin, 'admin_eleves', {}),
            (_creer_mshrif(), 'admin_evaluations', {}),
        ]
        for user, url_name, kwargs in cas:
            self.client.force_login(user)
            response = self.client.get(reverse(url_name, kwargs=kwargs))
            self.assertEqual(response.status_code, 200)
            contenu = response.content.decode('utf-8')
            self.assertEqual(
                contenu.count('sc-wrap { position: relative'), 1,
                f"composant _select_cherchable dupliqué ou absent sur {url_name}",
            )

        prof = _creer_prof('prof_sc_test@zidni.test')
        self.client.force_login(prof.user)
        response = self.client.get(reverse('prof_seances'))
        self.assertEqual(response.content.decode('utf-8').count('sc-wrap { position: relative'), 1)

        eleve = _creer_eleve('eleve_sc_test@zidni.test')
        self.client.force_login(eleve.user)
        response = self.client.get(reverse('dashboard_eleve'))
        # Aucun select converti côté élève (voir B1), mais le composant reste
        # inclus par cohérence des 5 bases (DRY) — présent même sans select à activer.
        self.assertEqual(response.content.decode('utf-8').count('sc-wrap { position: relative'), 1)

        superviseur = _creer_superviseur('superviseur_sc_test@zidni.test')
        self.client.force_login(superviseur.user)
        response = self.client.get(reverse('dashboard_superviseur'))
        self.assertEqual(response.content.decode('utf-8').count('sc-wrap { position: relative'), 1)

    def test_marqueur_present_sur_les_selects_valides_au_b1(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_evaluations'))
        contenu = response.content.decode('utf-8')
        for name in ['groupe', 'prof', 'eleve']:
            self.assertIn(
                f'<select name="{name}" class="form-select" data-select-cherchable>', contenu,
            )

    def test_marqueur_absent_des_listes_a_choix_fixes(self):
        """Contre-preuve : un select exclu au B1 (statut, choix figé court) ne
        doit PAS porter le marqueur."""
        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_eleves'))
        contenu = response.content.decode('utf-8')
        self.assertIn('<select name="statut" class="form-select">', contenu)
        self.assertNotIn('<select name="statut" class="form-select" data-select-cherchable>', contenu)

    def test_soumission_transfert_eleve_identique_a_avant_sans_destination(self):
        """L'attribut data-select-cherchable est inerte côté serveur : le
        comportement (name=destination_id, required) est inchangé — vérifié
        ici sur le chemin d'erreur existant (déjà présent avant ce chantier),
        qui doit rester identique."""
        self.client.force_login(self.admin)
        groupe = Groupe.objects.create(nom='مجموعة SC مصدر')
        eleve = _creer_eleve('eleve_transfert_sc@zidni.test')
        response = self.client.post(
            reverse('admin_groupe_transferer_eleve', args=[groupe.id, eleve.id]),
            {},  # pas de destination_id, exactement comme un select vide avant ce chantier
        )
        self.assertRedirects(response, reverse('admin_groupe_detail', args=[groupe.id]))

    def test_soumission_ajout_eleve_identique_a_avant(self):
        """Même principe : le name="eleve_id" et sa valeur POST sont
        inchangés, la validation métier existante (ici : pas de créneau sur
        le groupe, donc rejet) réagit exactement comme avant ce chantier."""
        self.client.force_login(self.admin)
        groupe = Groupe.objects.create(nom='مجموعة SC destination')
        eleve = _creer_eleve('eleve_ajout_sc@zidni.test')
        response = self.client.post(
            reverse('admin_groupe_ajouter_eleve', args=[groupe.id]),
            {'eleve_id': str(eleve.id)},
        )
        self.assertRedirects(response, reverse('admin_groupe_detail', args=[groupe.id]))
        self.assertFalse(groupe.eleves.filter(id=eleve.id).exists())  # rejeté : pas de créneau, comme avant

    def test_permissions_inchangees_mshrif_ne_voit_toujours_pas_les_actions_edition(self):
        """La conversion en select cherchable ne doit RIEN changer aux règles
        de permission déjà en place — même bloc {% if role != 'mshrif' %}
        qu'avant ce chantier, non touché."""
        mshrif = _creer_mshrif()
        self.client.force_login(mshrif)
        groupe = Groupe.objects.create(nom='مجموعة SC مشرف')
        response = self.client.get(reverse('admin_groupe_detail', args=[groupe.id]))
        contenu = response.content.decode('utf-8')
        self.assertNotIn('name="eleve_id"', contenu)
        self.assertNotIn('name="destination_id"', contenu)

        # مشرف garde bien accès aux FILTRES cherchables qui lui sont destinés.
        response = self.client.get(reverse('admin_evaluations'))
        self.assertIn('data-select-cherchable', response.content.decode('utf-8'))


def _creer_inscription_eleve(**overrides):
    valeurs = dict(
        nom='طالب مرشح للاختبار', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
        telephone='0600000010', email='candidat_e_refus@zidni.test',
        programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
    )
    valeurs.update(overrides)
    return InscriptionEleve.objects.create(**valeurs)


def _creer_inscription_prof(**overrides):
    valeurs = dict(
        nom='أستاذ مرشح', prenom='للاختبار', date_naissance=datetime.date(1990, 1, 1),
        telephone='0600000011', ville='الرباط', statut_familial='married', job_actuel='enseignant',
        certifications='x', niveau_memorisation='كامل', parcours_scolaire='x', parcours_enseignant='x',
        compte_bancaire='x', rib='x', agence_bancaire='x', gestion_eleve_faible='x', gestion_eleve_absent='x',
        email='candidat_p_refus@zidni.test',
    )
    valeurs.update(overrides)
    return InscriptionProf.objects.create(**valeurs)


@override_settings(STORAGES=_STORAGES_TEST)
class RefusInscriptionAvecMotifTests(TestCase):
    """Chantier 3 du 2026-08-14 — refus avec motif + phrases réutilisables + WhatsApp."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    # --- C1 : motif figé, indépendant des phrases-modèles ---

    def test_motif_fige_meme_apres_suppression_de_la_phrase_liee(self):
        self.client.force_login(self.admin)
        phrase = PhraseRefus.objects.create(contexte='refus_eleve', texte='دخل غير كافٍ حالياً')
        inscription = _creer_inscription_eleve()

        self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': phrase.texte},
        )
        phrase.delete()  # la phrase-modèle disparaît...

        inscription.refresh_from_db()
        self.assertEqual(inscription.motif_refus, 'دخل غير كافٍ حالياً')  # ...le motif figé survit intact
        self.assertEqual(inscription.statut, 'rejete')

    # --- C2/C3 : 3 listes de phrases strictement cloisonnées par contexte ---

    def test_chaque_contexte_ne_voit_que_sa_propre_liste_de_phrases(self):
        PhraseRefus.objects.create(contexte='refus_eleve', texte='PHRASE_ELEVE')
        PhraseRefus.objects.create(contexte='refus_prof_etape1', texte='PHRASE_PROF_ETAPE1')
        PhraseRefus.objects.create(contexte='refus_prof_etape2', texte='PHRASE_PROF_ETAPE2')

        self.client.force_login(self.admin)
        ins_eleve = _creer_inscription_eleve(email='cloison_e@zidni.test')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[ins_eleve.id])).content.decode('utf-8')
        self.assertIn('PHRASE_ELEVE', html)
        self.assertNotIn('PHRASE_PROF_ETAPE1', html)
        self.assertNotIn('PHRASE_PROF_ETAPE2', html)

        ins_prof1 = _creer_inscription_prof(email='cloison_p1@zidni.test')
        html = self.client.get(reverse('admin_rejeter_prof', args=[ins_prof1.id])).content.decode('utf-8')
        self.assertIn('PHRASE_PROF_ETAPE1', html)
        self.assertNotIn('PHRASE_ELEVE', html)
        self.assertNotIn('PHRASE_PROF_ETAPE2', html)

        self.client.force_login(self.mshrif)
        ins_prof2 = _creer_inscription_prof(email='cloison_p2@zidni.test', statut='validee_directeur')
        html = self.client.get(reverse('mshrif_rejeter_prof', args=[ins_prof2.id])).content.decode('utf-8')
        self.assertIn('PHRASE_PROF_ETAPE2', html)
        self.assertNotIn('PHRASE_ELEVE', html)
        self.assertNotIn('PHRASE_PROF_ETAPE1', html)

    def test_enregistrer_phrase_la_place_dans_le_bon_contexte_uniquement(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='save_phrase@zidni.test')
        self.client.post(
            reverse('admin_rejeter_prof', args=[inscription.id]),
            {'motif': 'NOUVELLE_PHRASE_TEST', 'enregistrer_phrase': 'on'},
        )
        self.assertTrue(PhraseRefus.objects.filter(contexte='refus_prof_etape1', texte='NOUVELLE_PHRASE_TEST').exists())
        self.assertFalse(PhraseRefus.objects.filter(contexte='refus_eleve', texte='NOUVELLE_PHRASE_TEST').exists())
        self.assertFalse(PhraseRefus.objects.filter(contexte='refus_prof_etape2', texte='NOUVELLE_PHRASE_TEST').exists())

    def test_sans_cocher_la_case_aucune_phrase_nest_enregistree(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='no_save_phrase@zidni.test')
        self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': 'MOTIF_SANS_SAUVEGARDE'},  # pas de enregistrer_phrase
        )
        self.assertFalse(PhraseRefus.objects.filter(texte='MOTIF_SANS_SAUVEGARDE').exists())
        inscription.refresh_from_db()
        self.assertEqual(inscription.motif_refus, 'MOTIF_SANS_SAUVEGARDE')  # le motif, lui, est bien figé

    # --- C10 : gardes d'état préservées avec le passage en formulaire POST ---

    def test_garde_etat_refus_eleve_deja_traite(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='garde_e@zidni.test', statut='valide')
        response = self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': 'trop tard'},
        )
        self.assertRedirects(response, reverse('admin_inscriptions'))
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'valide')  # inchangé
        self.assertEqual(inscription.motif_refus, '')

    def test_garde_etat_refus_prof_etape1_deja_rejete(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='garde_p1@zidni.test', statut='rejete')
        response = self.client.post(
            reverse('admin_rejeter_prof', args=[inscription.id]),
            {'motif': 'trop tard'},
        )
        self.assertRedirects(response, reverse('admin_inscriptions'))
        inscription.refresh_from_db()
        self.assertEqual(inscription.motif_refus, '')

    def test_garde_etat_refus_prof_etape2_pas_encore_pre_valide(self):
        self.client.force_login(self.mshrif)
        inscription = _creer_inscription_prof(email='garde_p2@zidni.test', statut='en_attente')
        response = self.client.post(
            reverse('mshrif_rejeter_prof', args=[inscription.id]),
            {'motif': 'trop tôt'},
        )
        self.assertRedirects(response, reverse('mshrif_inscriptions_profs'))
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'en_attente')
        self.assertEqual(inscription.motif_refus, '')

    def test_motif_vide_ne_rejette_rien_et_reaffiche_le_formulaire(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='motif_vide@zidni.test')
        response = self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': '   '},  # blanc pur
        )
        self.assertEqual(response.status_code, 200)  # réaffiche le formulaire, pas de redirect
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'en_attente')

    # --- Permissions par rôle sur chacun des 3 écrans ---

    def test_permissions_eleve_connecte_refuse_sur_les_3_ecrans(self):
        eleve = _creer_eleve('eleve_refus_perm@zidni.test')
        ins_eleve = _creer_inscription_eleve(email='perm_e@zidni.test')
        ins_prof = _creer_inscription_prof(email='perm_p@zidni.test', statut='validee_directeur')
        self.client.force_login(eleve.user)
        self.assertEqual(self.client.get(reverse('admin_rejeter_eleve', args=[ins_eleve.id])).status_code, 302)
        self.assertEqual(self.client.get(reverse('admin_rejeter_prof', args=[ins_prof.id])).status_code, 302)
        self.assertEqual(self.client.get(reverse('mshrif_rejeter_prof', args=[ins_prof.id])).status_code, 302)

    def test_permissions_mshrif_ne_peut_pas_refuser_a_letape_1(self):
        """L'étape 1 (admin_rejeter_prof) reste strictement مدير — مشرف n'agit
        qu'à l'étape 2 (mshrif_rejeter_prof), même avec ce nouveau formulaire."""
        self.client.force_login(self.mshrif)
        inscription = _creer_inscription_prof(email='perm_mshrif_e1@zidni.test')
        response = self.client.get(reverse('admin_rejeter_prof', args=[inscription.id]))
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, reverse('admin_rejeter_prof', args=[inscription.id]))

    def test_permissions_admin_ne_peut_pas_utiliser_lecran_etape2(self):
        """admin_rejeter_prof (étape 1) et mshrif_rejeter_prof (étape 2) restent
        deux vues séparées avec des décorateurs de rôle distincts."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='perm_admin_e2@zidni.test', statut='validee_directeur')
        response = self.client.get(reverse('mshrif_rejeter_prof', args=[inscription.id]))
        self.assertEqual(response.status_code, 302)

    # --- WhatsApp : présence des boutons, contact مدير résolu ---

    def test_deux_boutons_whatsapp_presents_avec_bon_numero_sur_mshrif_rejeter_prof(self):
        """Correction du 2026-08-14 : le bouton "مراسلة المدير" n'a de sens
        que lorsque مشرف agit (voir test_bouton_contacter_directeur_absent_
        quand_cest_lui_qui_agit pour les 2 écrans où مدير agit sur lui-même) —
        c'est donc ICI, sur mshrif_rejeter_prof, que les 2 numéros doivent
        apparaître ensemble."""
        self.admin.telephone = '0611223344'
        self.admin.save()
        inscription = _creer_inscription_prof(email='wa_test_mshrif@zidni.test', statut='validee_directeur')
        self.client.force_login(self.mshrif)
        html = self.client.get(reverse('mshrif_rejeter_prof', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('212611223344', html)  # wa_number(0611223344) — contact مدير

    def test_bouton_personne_whatsapp_present_avec_bon_numero_sur_admin_rejeter_eleve(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='wa_test@zidni.test', telephone='0699887766')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('212699887766', html)  # wa_number(0699887766)

    # --- Refonte UX du 2026-08-14 : gabarit de message centralisé ---

    def test_motif_refus_stocke_en_base_est_le_motif_seul_jamais_le_gabarit(self):
        """La colonne motif_refus ne doit JAMAIS contenir la salutation/clôture
        du gabarit — uniquement le texte tapé par l'utilisateur."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='gabarit_motif_seul@zidni.test')
        self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': 'الملف غير مكتمل'},
        )
        inscription.refresh_from_db()
        self.assertEqual(inscription.motif_refus, 'الملف غير مكتمل')
        self.assertNotIn('السلام عليكم', inscription.motif_refus)
        self.assertNotIn('نسأل الله', inscription.motif_refus)

    def test_gabarit_complet_transmis_a_la_page_pour_lapercu_et_whatsapp(self):
        """Le gabarit complet (salutation + clôture fixes, fournies par le
        client) doit être présent sur la page — c'est lui qui alimente à la
        fois l'aperçu live et les 2 liens WhatsApp, tous deux calculés en JS
        à partir des MÊMES constantes Python, jamais réécrites dans le
        template ni dupliquées entre les 3 écrans de refus."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='gabarit_complet@zidni.test')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('السلام عليكم ورحمة الله وبركاته', html)
        self.assertIn('نسأل الله أن يوفقكم', html)
        # Même gabarit sur les 3 écrans — pas 3 textes différents recopiés à la main.
        inscription_prof = _creer_inscription_prof(email='gabarit_complet_prof1@zidni.test')
        html_prof1 = self.client.get(reverse('admin_rejeter_prof', args=[inscription_prof.id])).content.decode('utf-8')
        self.assertIn('السلام عليكم ورحمة الله وبركاته', html_prof1)

        self.client.force_login(self.mshrif)
        inscription_prof2 = _creer_inscription_prof(email='gabarit_complet_prof2@zidni.test', statut='validee_directeur')
        html_prof2 = self.client.get(reverse('mshrif_rejeter_prof', args=[inscription_prof2.id])).content.decode('utf-8')
        self.assertIn('السلام عليكم ورحمة الله وبركاته', html_prof2)

    def test_gabarit_est_bien_une_constante_python_unique(self):
        """Verrou structurel : une seule définition du gabarit dans tout le
        code (dashboard.views), pas une par écran de refus."""
        self.assertIn('سبب الرفض', GABARIT_REFUS_AVANT_MOTIF)
        self.assertIn('نسأل الله', GABARIT_REFUS_APRES_MOTIF)

    def test_variables_js_du_gabarit_correctement_quotees(self):
        """Régression du 2026-08-14 (test manuel) : |escapejs échappe les
        caractères spéciaux mais N'AJOUTE PAS les guillemets englobants — un
        `var x = {{ v|escapejs }};` sans guillemets produit du JS invalide dès
        que le texte contient un espace (ex: texte arabe), et une
        SyntaxError silencieuse dans un <script> tue TOUT le reste du script
        (dont majTout(), qui alimente l'aperçu ET les liens WhatsApp) — c'est
        exactement pourquoi l'aperçu restait vide, confirmé par exécution JS
        réelle (Node/jsdom) sur le HTML rendu. Vérifié ici de façon statique
        (guillemets présents autour de {{ }}), le comportement réel étant
        confirmé une fois manuellement hors suite (jsdom non disponible en
        dépendance de test)."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='scope_apercu_quote@zidni.test')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[inscription.id])).content.decode('utf-8')
        self.assertIn("var gabaritAvant = '", html)
        self.assertIn("var gabaritApres = '", html)
        self.assertIn("var nomPersonne = '", html)

    def test_bouton_contacter_directeur_absent_quand_cest_lui_qui_agit(self):
        """Correction du 2026-08-14 (test manuel) : sur les 2 écrans où c'est
        مدير lui-même qui rejette (élève, prof étape 1), "envoyer une copie
        au مدير" n'a aucun sens — retiré. Conservé sur mshrif_rejeter_prof où
        c'est bien مشرف qui agit et مدير une personne différente."""
        self.admin.telephone = '0611223344'
        self.admin.save()

        self.client.force_login(self.admin)
        ins_eleve = _creer_inscription_eleve(email='bouton_directeur_eleve@zidni.test')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[ins_eleve.id])).content.decode('utf-8')
        self.assertNotIn('id="wa_admin"', html)

        ins_prof1 = _creer_inscription_prof(email='bouton_directeur_prof1@zidni.test')
        html = self.client.get(reverse('admin_rejeter_prof', args=[ins_prof1.id])).content.decode('utf-8')
        self.assertNotIn('id="wa_admin"', html)

        self.client.force_login(self.mshrif)
        ins_prof2 = _creer_inscription_prof(email='bouton_directeur_prof2@zidni.test', statut='validee_directeur')
        html = self.client.get(reverse('mshrif_rejeter_prof', args=[ins_prof2.id])).content.decode('utf-8')
        self.assertIn('id="wa_admin"', html)


@override_settings(STORAGES=_STORAGES_TEST)
class BilanAbsencesTests(TestCase):
    """Chantier 4 du 2026-08-14 — carte de bilan d'absences sur bilan_mensuel_detail."""

    def setUp(self):
        self.prof = _creer_prof('prof_bilan_abs@zidni.test')
        self.eleve = _creer_eleve('eleve_bilan_abs@zidni.test')
        self.groupe = Groupe.objects.create(nom='مجموعة بيان الغياب', prof=self.prof)
        self.groupe.eleves.add(self.eleve)
        self.mois = '2026-08'
        self.mois_reference = datetime.date(2026, 8, 1)
        # 2 présences, 1 absence non-excusée, 1 absence excusée.
        dates_statuts = [
            (datetime.date(2026, 8, 1), 'present'),
            (datetime.date(2026, 8, 3), 'absent'),
            (datetime.date(2026, 8, 5), 'present'),
            (datetime.date(2026, 8, 8), 'absent_excuse'),
        ]
        for date, statut in dates_statuts:
            seance = Seance.objects.create(groupe=self.groupe, date=date, heure='14:00', type='normal')
            Presence.objects.create(seance=seance, eleve=self.eleve, statut=statut)
        BilanMensuel.objects.create(eleve=self.eleve, prof=self.prof, mois_reference=self.mois_reference)

    def _bloc_absences(self, html):
        debut = html.find('id="detail_absences"')
        fin = html.find('</div>', html.find('</div>', debut) + 1)
        return html[debut:fin]

    def test_total_present_absent_correct(self):
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois])).content.decode('utf-8')
        self.assertIn('2 حضور', html)
        self.assertIn('2 غياب', html)
        self.assertIn('4 حصص', html)

    def test_seules_les_absences_apparaissent_dans_le_detail_deplie(self):
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois])).content.decode('utf-8')
        bloc = self._bloc_absences(html)
        self.assertIn('03-08-2026', bloc)  # absent
        self.assertIn('08-08-2026', bloc)  # absent_excuse
        self.assertNotIn('01-08-2026', bloc)  # present — ne doit JAMAIS apparaître ici
        self.assertNotIn('05-08-2026', bloc)  # present — ne doit JAMAIS apparaître ici

    def test_distinction_excuse_non_excuse_dans_le_detail(self):
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois])).content.decode('utf-8')
        bloc = self._bloc_absences(html)
        self.assertIn('غياب مبرر', bloc)
        self.assertIn('غياب غير مبرر', bloc)

    def test_contenu_identique_pour_les_3_roles_qui_consultent(self):
        """D4 : élève, prof, مؤطر doivent voir EXACTEMENT le même total et le
        même détail d'absences — aucune donnée cachée entre eux."""
        superviseur = _creer_superviseur('sup_bilan_abs@zidni.test')
        superviseur.profs_assignes.add(self.prof)

        blocs = {}
        for user, label in [(self.eleve.user, 'eleve'), (self.prof.user, 'prof'), (superviseur.user, 'superviseur')]:
            self.client.force_login(user)
            html = self.client.get(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois])).content.decode('utf-8')
            blocs[label] = self._bloc_absences(html)

        self.assertEqual(blocs['eleve'], blocs['prof'])
        self.assertEqual(blocs['prof'], blocs['superviseur'])

    def test_calcul_en_temps_reel_reflete_un_changement_de_presence(self):
        """D5 : pas de valeur figée — une Presence modifiée après coup doit
        immédiatement changer le total au prochain affichage."""
        self.client.force_login(self.eleve.user)
        url = reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois])
        html_avant = self.client.get(url).content.decode('utf-8')
        self.assertIn('2 غياب', html_avant)

        # Un absent_excuse redevient present.
        Presence.objects.filter(eleve=self.eleve, statut='absent_excuse').update(statut='present')

        html_apres = self.client.get(url).content.decode('utf-8')
        self.assertIn('1 غياب', html_apres)
        self.assertIn('3 حضور', html_apres)

    # --- D6 : permissions héritées, aucune nouvelle règle ---

    def test_permission_eleve_ne_voit_que_son_propre_bilan(self):
        autre_eleve = _creer_eleve('autre_eleve_bilan_abs@zidni.test')
        self.client.force_login(autre_eleve.user)
        response = self.client.get(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois]))
        self.assertEqual(response.status_code, 403)

    def test_permission_prof_hors_de_ses_groupes_refuse(self):
        """Comportement déjà en place (branche 'prof' de la vue), pas une
        nouvelle règle : un prof dont l'élève n'est dans AUCUN de ses
        groupes reçoit 403, avant même d'atteindre la logique de la carte."""
        autre_prof = _creer_prof('autre_prof_bilan_abs@zidni.test')
        self.client.force_login(autre_prof.user)
        response = self.client.get(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois]))
        self.assertEqual(response.status_code, 403)

    def test_permission_superviseur_non_assigne_refuse(self):
        superviseur_non_assigne = _creer_superviseur('sup_non_assigne_bilan_abs@zidni.test')
        self.client.force_login(superviseur_non_assigne.user)
        response = self.client.get(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois]))
        self.assertEqual(response.status_code, 403)

    def test_lien_depuis_le_profil_eleve_pointe_vers_le_bon_mois(self):
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('eleve_profil')).content.decode('utf-8')
        self.assertIn(reverse('bilan_mensuel_detail', args=[self.eleve.id, self.mois]), html)


@override_settings(STORAGES=_STORAGES_TEST)
class CommentairesTemplateInvisiblesTests(TestCase):
    """Régression du 2026-08-14 — un commentaire Django multi-lignes écrit en
    syntaxe {# ... #} (au lieu de {% comment %}...{% endcomment %}) n'est PAS
    reconnu par le tokenizer de Django dès qu'il contient un retour à la
    ligne (regex {#.*?#} sans re.DOTALL) : le texte du commentaire fuit alors
    tel quel dans le HTML envoyé au navigateur. C'est exactement ce qui s'est
    produit sur _recherche_globale.html, _select_cherchable.html,
    bilan_mensuel_detail.html, admin_inscription_detail.html et
    refuser_inscription.html (tous {% comment %} depuis correctif). Ce test
    couvre les 5 base_*.html — donc, transitivement, les deux partials
    (_recherche_globale, _select_cherchable) qu'ils incluent — pour empêcher
    qu'un futur commentaire multi-lignes mal formé ne refuie en silence."""

    MARQUEURS = [
        'Chantier du 2026-08-14',
        'UN SEUL composant',
        'Amélioration progressive',
        'PARTAGÉE par les 3 écrans',
        'identique pour les 5 rôles',
        'consultable ici même après coup',
    ]

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.prof = _creer_prof('prof_comment_test@zidni.test')
        self.eleve = _creer_eleve('eleve_comment_test@zidni.test')
        self.superviseur = _creer_superviseur('sup_comment_test@zidni.test')

    def _assert_page_propre(self, user, url_name):
        self.client.force_login(user)
        html = self.client.get(reverse(url_name)).content.decode('utf-8')
        for marqueur in self.MARQUEURS:
            self.assertNotIn(
                marqueur, html,
                f"Le marqueur de commentaire '{marqueur}' fuit dans le HTML rendu "
                f"pour {url_name} (rôle {user.role}) — commentaire Django mal formé."
            )

    def test_base_admin_ne_fuit_aucun_commentaire(self):
        self._assert_page_propre(self.admin, 'dashboard_admin')

    def test_base_mshrif_ne_fuit_aucun_commentaire(self):
        self._assert_page_propre(self.mshrif, 'dashboard_mshrif')

    def test_base_prof_ne_fuit_aucun_commentaire(self):
        self._assert_page_propre(self.prof.user, 'dashboard_prof')

    def test_base_eleve_ne_fuit_aucun_commentaire(self):
        self._assert_page_propre(self.eleve.user, 'dashboard_eleve')

    def test_base_superviseur_ne_fuit_aucun_commentaire(self):
        self._assert_page_propre(self.superviseur.user, 'dashboard_superviseur')


@override_settings(STORAGES=_STORAGES_TEST)
class RechercheGlobalePresenteSurToutesLesPagesTests(TestCase):
    """Régression du 2026-08-14 — la barre de recherche globale est incluse
    dans base_admin.html/base_mshrif.html eux-mêmes (avant {% block content
    %}), pas dans une page précise : elle doit donc apparaître sur TOUTE page
    مدير/مشرف, pas seulement l'accueil. Couvre 3+ pages par rôle, au-delà de
    RechercheGlobaleTests qui ne teste que l'endpoint API lui-même."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _verifier_presente_avant_le_contenu(self, url_name):
        html = self.client.get(reverse(url_name)).content.decode('utf-8')
        idx_recherche = html.find('rechercheGlobaleInput')
        idx_contenu = html.find('class="page-title"')
        self.assertNotEqual(idx_recherche, -1, f"Barre de recherche absente sur {url_name}.")
        self.assertNotEqual(idx_contenu, -1, f"Repère de contenu introuvable sur {url_name}.")
        self.assertLess(
            idx_recherche, idx_contenu,
            f"La barre de recherche doit apparaître AVANT le contenu propre à la "
            f"page {url_name} (donc faire partie du layout commun, pas du contenu)."
        )

    def test_admin_recherche_presente_sur_3_pages_differentes(self):
        self.client.force_login(self.admin)
        for url_name in ['dashboard_admin', 'admin_eleves', 'admin_profs']:
            self._verifier_presente_avant_le_contenu(url_name)

    def test_mshrif_recherche_presente_sur_3_pages_differentes(self):
        self.client.force_login(self.mshrif)
        for url_name in ['dashboard_mshrif', 'admin_eleves', 'admin_profs']:
            self._verifier_presente_avant_le_contenu(url_name)

    # --- Correction du 2026-08-14 (test manuel) : EXCLUSION explicite sur les
    # écrans d'action focalisée à une seule tâche (formulaire d'action, écran
    # de confirmation) — la recherche globale y distrait de l'action en
    # cours. base_admin.html/base_mshrif.html exposent {% block
    # recherche_globale %} pour que ces écrans puissent l'écraser à vide,
    # plutôt que de casser silencieusement le test ci-dessus si un écran
    # de ce type était un jour ajouté à la liste testée plus haut. ---

    def _assert_recherche_absente(self, url):
        html = self.client.get(url).content.decode('utf-8')
        self.assertNotIn(
            'rechercheGlobaleInput', html,
            f"La recherche globale ne doit PAS apparaître sur un écran d'action "
            f"focalisée ({url}) — elle distrait de l'action en cours."
        )

    def test_recherche_absente_sur_ecran_de_refus(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='scope_refus@zidni.test')
        self._assert_recherche_absente(reverse('admin_rejeter_eleve', args=[inscription.id]))

    def test_recherche_absente_sur_ecran_de_suppression_definitive(self):
        self.client.force_login(self.admin)
        eleve = _creer_eleve('scope_suppr_def@zidni.test')
        self._assert_recherche_absente(reverse('eleve_supprimer_definitivement', args=[eleve.id]))

    def test_recherche_absente_sur_ecran_de_confirmation_creation_compte(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session['confirmation_creation_compte'] = {
            'type_compte': 'eleve', 'nom': 'Scope Confirmation',
            'email': 'scope_confirmation@zidni.test', 'password': 'xxxxxxxx',
            'telephone': '', 'redirect_url_name': 'admin_inscriptions',
        }
        session.save()
        self._assert_recherche_absente(reverse('confirmation_creation_compte'))
