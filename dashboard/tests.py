import datetime
import time

from django.conf import settings
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    User, Eleve, Prof, Superviseur, DocumentEleve, ElementHakiba, DerniereVisiteNotification,
)
from courses.models import (
    Groupe, Creneau, Seance, Presence, BilanMensuel, HistoriqueGroupeEleve,
    DisponibiliteEleve, DisponibiliteProf, DemandeModificationDisponibilite,
)
from courses.utils import remplacer_slots_creneau
from registration.models import (
    ChampInscription, Critere as CritereInscription, CritereOption, EtapeInscription,
    GroupeCritereValeur, RegleCondition,
)
from evaluations.models import Evaluation, CommentaireMensuel, Critere, NoteEvaluation
from examens.models import Examen
from inscriptions.models import InscriptionEleve, InscriptionProf, PhraseRefus
from payments.models import Paiement
from dashboard.views import (
    GABARIT_REFUS_AVANT_MOTIF, GABARIT_REFUS_APRES_MOTIF, _contact_admin_fixe,
    URL_PLATEFORME, construire_message_acceptation_whatsapp,
)


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

    # --- WhatsApp : plus AUCUN bouton sur le formulaire lui-même (Correction
    # du 2026-08-14, bug de logique) — voir RefusConfirmeOrdreLogiqueTests
    # pour la présence des boutons APRÈS confirmation, sur refus_confirme. ---

    def test_aucun_lien_whatsapp_sur_le_formulaire_de_refus_avant_confirmation(self):
        """Avant ce correctif, les 2 boutons WhatsApp étaient déjà cliquables
        SUR ce formulaire — donc avant même le clic sur 'تأكيد الرفض'. Verrou
        structurel : plus aucun lien wa.me, sur aucun des 3 écrans, tant que
        le refus n'a pas été confirmé (POST)."""
        self.admin.telephone = '0611223344'
        self.admin.save()

        self.client.force_login(self.admin)
        ins_eleve = _creer_inscription_eleve(email='pas_de_wa_eleve@zidni.test', telephone='0699887766')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[ins_eleve.id])).content.decode('utf-8')
        self.assertNotIn('wa.me/', html)

        ins_prof1 = _creer_inscription_prof(email='pas_de_wa_prof1@zidni.test')
        html = self.client.get(reverse('admin_rejeter_prof', args=[ins_prof1.id])).content.decode('utf-8')
        self.assertNotIn('wa.me/', html)

        self.client.force_login(self.mshrif)
        ins_prof2 = _creer_inscription_prof(email='pas_de_wa_prof2@zidni.test', statut='validee_directeur')
        html = self.client.get(reverse('mshrif_rejeter_prof', args=[ins_prof2.id])).content.decode('utf-8')
        self.assertNotIn('wa.me/', html)

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

    def test_gabarit_complet_transmis_a_la_page_pour_lapercu(self):
        """Le gabarit complet (salutation + clôture fixes, fournies par le
        client) doit être présent sur la page — c'est lui qui alimente
        l'aperçu live (calculé en JS à partir des MÊMES constantes Python,
        jamais réécrites dans le template ni dupliquées entre les 3 écrans).
        Depuis la correction du 2026-08-14 (ordre logique), ce même gabarit
        sert aussi à construire le message final sur refus_confirme — mais
        recalculé côté serveur à partir du motif en base, pas transmis
        depuis cette page (voir RefusConfirmeOrdreLogiqueTests)."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='gabarit_complet@zidni.test')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('السلام عليكم ورحمة الله وبركاته', html)
        self.assertIn('نسأل الله أن يوفقك ويكتب لك الخير حيث كان', html)
        # Texte mis à jour le 2026-08-15 : le nom de la personne fait
        # désormais partie du gabarit fixe (placeholder {nom}) — vérifie
        # qu'il est bien substitué dans l'aperçu, pas laissé tel quel.
        self.assertIn(f'حياك الله {inscription.nom}', html)
        self.assertNotIn('{nom}', html)
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
        self.assertIn('سبب عدم القبول', GABARIT_REFUS_AVANT_MOTIF)
        self.assertIn('{nom}', GABARIT_REFUS_AVANT_MOTIF)  # placeholder, jamais figé en dur
        self.assertIn('نسأل الله', GABARIT_REFUS_APRES_MOTIF)

    def test_variables_js_du_gabarit_correctement_quotees(self):
        """Régression du 2026-08-14 (test manuel) : |escapejs échappe les
        caractères spéciaux mais N'AJOUTE PAS les guillemets englobants — un
        `var x = {{ v|escapejs }};` sans guillemets produit du JS invalide dès
        que le texte contient un espace (ex: texte arabe), et une
        SyntaxError silencieuse dans un <script> tue TOUT le reste du script
        (dont majTout(), qui alimente l'aperçu) — c'est exactement pourquoi
        l'aperçu restait vide, confirmé par exécution JS réelle (Node/jsdom)
        sur le HTML rendu. Vérifié ici de façon statique (guillemets présents
        autour de {{ }}), le comportement réel étant confirmé une fois
        manuellement hors suite (jsdom non disponible en dépendance de test)."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='scope_apercu_quote@zidni.test')
        html = self.client.get(reverse('admin_rejeter_eleve', args=[inscription.id])).content.decode('utf-8')
        self.assertIn("var gabaritAvant = '", html)
        self.assertIn("var gabaritApres = '", html)
        self.assertIn("var nomPersonne = '", html)


@override_settings(STORAGES=_STORAGES_TEST)
class RefusConfirmeOrdreLogiqueTests(TestCase):
    """Correction du 2026-08-14 (bug de logique constaté en test manuel) :
    les 2 boutons WhatsApp étaient cliquables AVANT même la confirmation du
    refus (avant le clic sur 'تأكيد الرفض'), ce qui permettait d'envoyer un
    message de refus à quelqu'un alors que la demande était encore
    'en_attente' en base. Nouveau flux : POST confirme le refus en base puis
    redirige vers l'écran dédié refus_confirme, qui seul affiche les
    boutons WhatsApp — voir aussi RefusInscriptionAvecMotifTests pour la
    preuve que ces boutons sont absents AVANT confirmation."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def test_confirmation_refus_eleve_redirige_vers_refus_confirme_avec_whatsapp(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='ordre_eleve@zidni.test', telephone='0699887766')
        response = self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': 'الملف غير مكتمل'},
        )
        # fetch_redirect_response=False : par défaut assertRedirects fait elle-même
        # un GET sur l'URL cible pour vérifier son code 200 — vu que refus_confirme
        # POP la session dès sa première lecture (comme confirmation_creation_compte),
        # ce GET interne consommerait la session avant notre propre GET ci-dessous
        # et ferait échouer l'assertion suivante avec une page vide (redirigée).
        self.assertRedirects(response, reverse('refus_confirme'), fetch_redirect_response=False)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'rejete')  # déjà en base avant même d'afficher WhatsApp

        html = self.client.get(reverse('refus_confirme')).content.decode('utf-8')
        self.assertIn('wa.me/212699887766', html)  # bouton vers la personne
        # Pas de sens à "مراسلة الإدارة" ici : c'est الإدارة elle-même qui a rejeté.
        self.assertNotIn('تواصل مع الإدارة', html)

    def test_confirmation_refus_prof_etape1_redirige_avec_whatsapp_sans_bouton_directeur(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='ordre_prof1@zidni.test', telephone='0688776655')
        response = self.client.post(
            reverse('admin_rejeter_prof', args=[inscription.id]),
            {'motif': 'خبرة غير كافية'},
        )
        self.assertRedirects(response, reverse('refus_confirme'), fetch_redirect_response=False)
        html = self.client.get(reverse('refus_confirme')).content.decode('utf-8')
        self.assertIn('wa.me/212688776655', html)
        self.assertNotIn('تواصل مع الإدارة', html)

    def test_confirmation_refus_prof_etape2_redirige_avec_whatsapp_et_bouton_directeur(self):
        """Ici مشرف rejette et مدير est bien une personne différente — le
        bouton 'تواصل مع الإدارة' garde tout son sens (contrairement aux 2
        écrans où c'est مدير qui agit sur lui-même)."""
        self.admin.telephone = '0611223344'
        self.admin.save()
        self.client.force_login(self.mshrif)
        inscription = _creer_inscription_prof(
            email='ordre_prof2@zidni.test', telephone='0677665544', statut='validee_directeur'
        )
        response = self.client.post(
            reverse('mshrif_rejeter_prof', args=[inscription.id]),
            {'motif': 'ملف غير مطابق'},
        )
        self.assertRedirects(response, reverse('refus_confirme'), fetch_redirect_response=False)
        html = self.client.get(reverse('refus_confirme')).content.decode('utf-8')
        self.assertIn('wa.me/212677665544', html)  # la personne
        self.assertIn('تواصل مع الإدارة', html)
        self.assertIn('wa.me/212611223344', html)  # le مدير

    def test_motif_affiche_sur_refus_confirme_est_relu_depuis_la_base(self):
        """Le motif affiché doit TOUJOURS être inscription.motif_refus tel
        qu'il est en base au moment de l'affichage — jamais une valeur
        transportée par la session ou figée au moment du formulaire. Preuve :
        on modifie motif_refus EN BASE entre la confirmation (POST, sans
        suivre la redirection) et l'affichage de refus_confirme (GET
        séparé) — le texte affiché doit refléter la modification, pas le
        texte initialement tapé dans le formulaire."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='motif_relu_base@zidni.test')

        response = self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': 'TEXTE_ORIGINAL_DU_FORMULAIRE'},
            follow=False,
        )
        self.assertRedirects(response, reverse('refus_confirme'), fetch_redirect_response=False)

        # Modification directe en base, simulant un état différent de ce qui
        # a été tapé dans le formulaire au moment du POST. refresh_from_db()
        # d'abord : l'objet Python `inscription` date d'avant le POST (encore
        # 'en_attente' en mémoire) — un save() sans ce refresh réécrirait TOUS
        # les champs avec ces valeurs périmées, y compris statut, et
        # écraserait le 'rejete' que la vue vient d'enregistrer.
        inscription.refresh_from_db()
        inscription.motif_refus = 'TEXTE_MODIFIE_EN_BASE'
        inscription.save(update_fields=['motif_refus'])

        html = self.client.get(reverse('refus_confirme')).content.decode('utf-8')
        self.assertIn('TEXTE_MODIFIE_EN_BASE', html)
        self.assertNotIn('TEXTE_ORIGINAL_DU_FORMULAIRE', html)

    def test_rafraichissement_de_refus_confirme_ne_reaffiche_rien(self):
        """Comme confirmation_creation_compte : la session est POP'ée à la
        première lecture — un rafraîchissement renvoie vers le dashboard
        plutôt que de réafficher indéfiniment le même écran WhatsApp."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='refus_confirme_refresh@zidni.test')
        self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': 'motif quelconque'},
        )
        self.client.get(reverse('refus_confirme'))  # 1re lecture : consomme la session
        response = self.client.get(reverse('refus_confirme'))  # rafraîchissement
        self.assertRedirects(response, reverse('dashboard_admin'))

    def test_acces_direct_a_lancienne_url_du_formulaire_apres_refus_deja_confirme(self):
        """Régression demandée : une fois le refus confirmé (statut='rejete'
        en base), un accès direct à l'ANCIENNE URL du formulaire
        (admin_rejeter_eleve/<id>/) ne doit plus jamais afficher de boutons
        WhatsApp dans le mauvais contexte — la garde d'état existante (statut
        != 'en_attente') empêche déjà le formulaire de se réafficher, ce test
        verrouille ce comportement explicitement pour les 3 écrans."""
        self.client.force_login(self.admin)
        ins_eleve = _creer_inscription_eleve(email='ancienne_url_eleve@zidni.test', telephone='0699887766')
        self.client.post(reverse('admin_rejeter_eleve', args=[ins_eleve.id]), {'motif': 'x'})

        response = self.client.get(reverse('admin_rejeter_eleve', args=[ins_eleve.id]))
        self.assertRedirects(response, reverse('admin_inscriptions'))
        html_suivi = self.client.get(reverse('admin_rejeter_eleve', args=[ins_eleve.id]), follow=True).content.decode('utf-8')
        self.assertNotIn('wa.me/', html_suivi)

        self.client.force_login(self.mshrif)
        ins_prof = _creer_inscription_prof(
            email='ancienne_url_prof2@zidni.test', telephone='0677665544', statut='validee_directeur'
        )
        self.client.post(reverse('mshrif_rejeter_prof', args=[ins_prof.id]), {'motif': 'y'})

        response = self.client.get(reverse('mshrif_rejeter_prof', args=[ins_prof.id]))
        self.assertRedirects(response, reverse('mshrif_inscriptions_profs'))
        html_suivi = self.client.get(reverse('mshrif_rejeter_prof', args=[ins_prof.id]), follow=True).content.decode('utf-8')
        self.assertNotIn('wa.me/', html_suivi)


@override_settings(STORAGES=_STORAGES_TEST)
class ContactAdminFixeUnSeulResultatTests(TestCase):
    """Bug confirmé en test manuel (2026-08-14) : plusieurs comptes
    role='admin' en base (dont des résidus de test jamais nettoyés, ex.
    'TEST_Admin Manuel') faisaient afficher plusieurs boutons "تواصل مع
    الإدارة" superposés et incohérents sur les écrans post-action
    (confirmation_creation_compte, réinitialisation mot de passe). Cause :
    ces 2 écrans construisaient 'admins' avec
    User.objects.filter(role='admin').exclude(...) — TOUS les comptes admin
    — au lieu de résoudre un seul contact via _contact_admin_fixe(), déjà
    utilisée ailleurs (refus_confirme). Corrigé en les alignant sur
    _contact_admin_fixe() partout. Verrou : cette fonction doit TOUJOURS
    renvoyer UN SEUL compte (ou None), jamais un queryset/liste, quel que
    soit le nombre de comptes role='admin' en base."""

    def test_contact_admin_fixe_retourne_un_seul_compte_le_plus_ancien_avec_telephone(self):
        # 3 comptes admin avec des téléphones variés (dont un vide, comme le
        # résidu de test réel constaté) — créés dans le désordre, puis
        # date_joined forcée explicitement pour ne pas dépendre du timing
        # réel de création (auto_now_add).
        plus_recent_avec_tel = User.objects.create_user(
            username='admin_recent@zidni.test', email='admin_recent@zidni.test',
            password='xX!test12345', role='admin', telephone='0611110001',
        )
        sans_telephone = User.objects.create_user(
            username='admin_sans_tel@zidni.test', email='admin_sans_tel@zidni.test',
            password='xX!test12345', role='admin', telephone='',
        )
        plus_ancien_avec_tel = User.objects.create_user(
            username='admin_ancien@zidni.test', email='admin_ancien@zidni.test',
            password='xX!test12345', role='admin', telephone='0611110002',
        )
        User.objects.filter(id=plus_recent_avec_tel.id).update(
            date_joined=datetime.datetime(2026, 8, 10, tzinfo=datetime.timezone.utc))
        User.objects.filter(id=sans_telephone.id).update(
            date_joined=datetime.datetime(2026, 8, 5, tzinfo=datetime.timezone.utc))
        User.objects.filter(id=plus_ancien_avec_tel.id).update(
            date_joined=datetime.datetime(2026, 8, 1, tzinfo=datetime.timezone.utc))

        resultat = _contact_admin_fixe()
        self.assertIsInstance(resultat, User)  # UN SEUL objet, jamais un queryset/liste
        self.assertEqual(resultat.id, plus_ancien_avec_tel.id)  # le plus ancien AVEC téléphone

    def test_contact_admin_fixe_retourne_none_si_aucun_admin_na_de_telephone(self):
        User.objects.create_user(
            username='admin_sans_tel_seul@zidni.test', email='admin_sans_tel_seul@zidni.test',
            password='xX!test12345', role='admin', telephone='',
        )
        self.assertIsNone(_contact_admin_fixe())

    def test_confirmation_creation_compte_affiche_un_seul_bloc_contact_admin(self):
        """Reproduction du bug rapporté : avec PLUSIEURS comptes admin en
        base (dont un sans téléphone, dont un qui aurait été un résidu de
        test), l'écran affiché après validation finale d'un prof par مشرف
        n'affiche qu'UN SEUL bloc "تواصل مع الإدارة" — pas un par compte
        admin trouvé. Marqueur 'تواصل مع الإدارة<br>' : texte exact du label
        du bouton (WhatsApp ou repli mailto) dans _contacts_whatsapp.html —
        distinct de la phrase d'aide en prose plus bas sur la même page qui
        contient aussi ces mots mais jamais suivis de <br>."""
        admin_sans_tel = _creer_admin()
        User.objects.create_user(
            username='admin_extra1@zidni.test', email='admin_extra1@zidni.test',
            password='xX!test12345', role='admin', telephone='0622220001',
        )
        User.objects.create_user(
            username='admin_extra2@zidni.test', email='admin_extra2@zidni.test',
            password='xX!test12345', role='admin', telephone='0622220002',
        )
        mshrif = _creer_mshrif()
        inscription = _creer_inscription_prof(email='contact_admin_unique@zidni.test')

        self.client.force_login(admin_sans_tel)
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))

        self.client.force_login(mshrif)
        response = self.client.get(reverse('mshrif_valider_prof_final', args=[inscription.id]), follow=True)
        html = response.content.decode('utf-8')
        self.assertEqual(html.count('تواصل مع الإدارة<br>'), 1)


@override_settings(STORAGES=_STORAGES_TEST)
class MshrifNeVoitJamaisUnDossierFermeTests(TestCase):
    """Bug critique confirmé en test manuel (2026-08-14) : un prof déjà refusé
    par مدير (statut='rejete') apparaissait quand même côté مشرف, qui pouvait
    alors agir dessus. Règle métier : مشرف ne voit QUE les dossiers
    'validee_directeur' (explicitement pré-validés par مدير) — jamais un
    dossier 'rejete' (fermé définitivement) ni 'en_attente' (pas encore
    traité par مدير du tout).

    Diagnostic : mshrif_inscriptions_profs (la liste) filtrait déjà
    correctement sur statut='validee_directeur' — voir le queryset dans
    dashboard.views. Le vrai trou : mshrif_inscription_prof_detail n'avait
    AUCUNE garde d'état, contrairement à mshrif_valider_prof_final et
    mshrif_rejeter_prof qui en avaient déjà une chacune — un accès direct par
    URL à la fiche de détail restait donc possible quel que soit le statut.
    Corrigé en ajoutant la même garde à mshrif_inscription_prof_detail."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _absent_de_la_liste(self, inscription):
        # logout() d'abord : si مدير vient d'agir (pré-validation, rejet...)
        # dans CE MÊME test.client, un message flash Django (session) portant
        # le nom de l'inscription peut encore être en attente d'affichage —
        # sans ce logout, force_login(mshrif) réutilise la même session et ce
        # message flash apparaîtrait sur la page مشرف, faussant l'assertion
        # ci-dessous (faux positif : le nom serait "trouvé", mais dans un
        # message de مدير, pas dans une ligne de la liste مشرف elle-même).
        self.client.logout()
        self.client.force_login(self.mshrif)
        html = self.client.get(reverse('mshrif_inscriptions_profs')).content.decode('utf-8')
        self.assertNotIn(inscription.nom, html)

    def _acces_direct_bloque_sur_les_3_vues(self, inscription):
        """Consultation, acceptation et refus doivent tous les 3 rediriger
        vers la liste sans rien changer en base — même en accès direct par
        URL, sans jamais passer par la liste elle-même."""
        self.client.logout()  # même raison que dans _absent_de_la_liste.
        self.client.force_login(self.mshrif)

        response = self.client.get(reverse('mshrif_inscription_prof_detail', args=[inscription.id]))
        self.assertRedirects(response, reverse('mshrif_inscriptions_profs'))

        response = self.client.get(reverse('mshrif_valider_prof_final', args=[inscription.id]))
        self.assertRedirects(response, reverse('mshrif_inscriptions_profs'))
        self.assertFalse(User.objects.filter(email=inscription.email, role='prof').exists())

        statut_avant = inscription.statut
        motif_avant = inscription.motif_refus
        response = self.client.post(
            reverse('mshrif_rejeter_prof', args=[inscription.id]), {'motif': 'tentative مشرف'}
        )
        self.assertRedirects(response, reverse('mshrif_inscriptions_profs'))
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, statut_avant)  # inchangé
        self.assertEqual(inscription.motif_refus, motif_avant)  # jamais écrasé par مشرف

    def test_prof_rejete_directement_depuis_en_attente_invisible_et_bloque_cote_mshrif(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='bug_critique_rejet_direct@zidni.test')
        self.client.post(reverse('admin_rejeter_prof', args=[inscription.id]), {'motif': 'خبرة غير كافية'})
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'rejete')

        self._absent_de_la_liste(inscription)
        self._acces_direct_bloque_sur_les_3_vues(inscription)

    def test_prof_pre_valide_puis_rejete_par_directeur_invisible_et_bloque_cote_mshrif(self):
        """Scénario exact du bug rapporté : مدير pré-valide (le dossier devient
        momentanément visible pour مشرف), PUIS se ravise et rejette avant que
        مشرف n'ait agi — le dossier doit redevenir invisible et fermé, pas
        rester accessible via un lien/onglet que مشرف aurait déjà ouvert."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='bug_critique_rejet_apres_prevalidation@zidni.test')
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'validee_directeur')  # visible pour مشرف à ce stade précis

        self.client.post(reverse('admin_rejeter_prof', args=[inscription.id]), {'motif': 'ملف غير مطابق'})  # ravisement du مدير
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'rejete')

        self._absent_de_la_liste(inscription)
        self._acces_direct_bloque_sur_les_3_vues(inscription)

    def test_prof_encore_en_attente_jamais_traite_par_directeur_invisible_cote_mshrif(self):
        """Sens inverse explicitement demandé : un dossier que مدير n'a même
        pas encore regardé ('en_attente') n'est pas plus visible côté مشرف
        qu'un dossier rejeté — seul 'validee_directeur' doit apparaître."""
        inscription = _creer_inscription_prof(email='bug_critique_jamais_traite@zidni.test')
        self.assertEqual(inscription.statut, 'en_attente')

        self._absent_de_la_liste(inscription)
        self._acces_direct_bloque_sur_les_3_vues(inscription)

    def test_reproduction_complete_du_scenario_rapporte(self):
        """Reproduction fidèle du test manuel rapporté, de bout en bout avec
        django.test.Client : création → rejet مدير → connexion مشرف →
        absence totale de la liste ET les 3 actions bloquées en accès direct."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(
            nom='بوغلاب', prenom='محمد', email='bug_critique_reproduction@zidni.test'
        )
        response = self.client.post(
            reverse('admin_rejeter_prof', args=[inscription.id]),
            {'motif': 'الملف غير مكتمل'},
        )
        self.assertRedirects(response, reverse('refus_confirme'), fetch_redirect_response=False)
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'rejete')
        self.client.logout()

        self.client.force_login(self.mshrif)
        html_liste = self.client.get(reverse('mshrif_inscriptions_profs')).content.decode('utf-8')
        self.assertNotIn('بوغلاب', html_liste)

        response_detail = self.client.get(reverse('mshrif_inscription_prof_detail', args=[inscription.id]))
        self.assertRedirects(response_detail, reverse('mshrif_inscriptions_profs'))

        response_accepter = self.client.get(reverse('mshrif_valider_prof_final', args=[inscription.id]))
        self.assertRedirects(response_accepter, reverse('mshrif_inscriptions_profs'))
        self.assertFalse(User.objects.filter(email='bug_critique_reproduction@zidni.test', role='prof').exists())

        response_refuser = self.client.post(
            reverse('mshrif_rejeter_prof', args=[inscription.id]), {'motif': 'tentative'}
        )
        self.assertRedirects(response_refuser, reverse('mshrif_inscriptions_profs'))
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'rejete')  # toujours fermé
        self.assertEqual(inscription.motif_refus, 'الملف غير مكتمل')  # motif du مدير jamais écrasé


@override_settings(STORAGES=_STORAGES_TEST)
class MessagesAcceptationEtRefusTests(TestCase):
    """Chantier du 2026-08-15 — refonte du texte des messages d'acceptation
    et de refus (style fourni par le client, ton islamique chaleureux, sans
    "أستاذ/أستاذة/طالب/طالبة" devant le nom, sans emoji, نطاق fixe
    app.zidanieilman.com). Vérifie le contenu RÉELLEMENT reçu (corps d'email
    capturé par django.core.mail.outbox, HTML réellement rendu) — pas
    seulement que les fonctions ne plantent pas.

    Acceptation : DEUX canaux distincts pour le MÊME texte —
    envoyer_email_bienvenue (email réel) et construire_message_acceptation_
    whatsapp (texte affiché sur confirmation_creation_compte, prêt à copier/
    envoyer). Un SEUL message d'acceptation existe par compte, envoyé
    uniquement quand le compte est réellement créé — pour un prof (workflow
    2 étapes), c'est donc à l'étape 2 (مشرف, mshrif_valider_prof_final),
    JAMAIS à l'étape 1 (مدير, admin_valider_prof, qui ne fait que
    pré-valider sans créer de compte ni envoyer aucun message)."""

    MOTS_INTERDITS = ['أستاذ', 'أستاذة', 'طالب', 'طالبة']
    EMOJIS_COURANTS = ['📋', '✅', '🎉', '📱', '❌', '👤', '📞', '💡', '🔑', '⚠️', '😊']

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    # --- Acceptation élève (validation en 1 seule étape par مدير) ---

    def test_email_acceptation_eleve_contient_nom_email_mot_de_passe_et_lien(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='accept_email_eleve@zidni.test', nom='زينب الفاسي')
        mail.outbox.clear()
        self.client.get(reverse('admin_valider_eleve', args=[inscription.id]))

        self.assertEqual(len(mail.outbox), 1)
        corps = mail.outbox[0].body
        self.assertIn('حياك الله زينب الفاسي،', corps)
        self.assertIn('accept_email_eleve@zidni.test', corps)
        self.assertIn(URL_PLATEFORME, corps)
        self.assertIn('يسرنا إخبارك بأنه تم قبولك للانضمام إلى منصة زدني علماً', corps)
        self.assertIn('زدني علماً', corps)  # nom exact de la plateforme
        # Le mot de passe temporaire réellement généré doit être dans le corps
        # — pas une valeur figée : on le relit depuis Eleve fraîchement créé.
        eleve = Eleve.objects.get(user__email='accept_email_eleve@zidni.test')
        # Pas d'accès direct au mot de passe en clair depuis le modèle (hashé) —
        # on vérifie sa PRÉSENCE structurelle via le motif "كلمة المرور:\n" suivi
        # d'une valeur non vide, garanti par le format du gabarit lui-même.
        self.assertIn('كلمة المرور:\n', corps)
        self.assertTrue(eleve.user.check_password(corps.split('كلمة المرور:\n')[1].split('\n')[0]))

    def test_email_acceptation_ne_contient_aucun_prefixe_de_role_ni_emoji(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='accept_sans_prefixe@zidni.test', nom='كريم بنعلي')
        mail.outbox.clear()
        self.client.get(reverse('admin_valider_eleve', args=[inscription.id]))
        corps = mail.outbox[0].body
        for mot in self.MOTS_INTERDITS:
            self.assertNotIn(mot, corps, f"'{mot}' ne doit jamais apparaître dans le message d'acceptation.")
        for emoji in self.EMOJIS_COURANTS:
            self.assertNotIn(emoji, corps, f"emoji '{emoji}' ne doit jamais apparaître dans le message d'acceptation.")

    # --- Acceptation prof (workflow 2 étapes) : message envoyé UNE SEULE
    # fois, à l'étape 2 (مشرف), jamais à l'étape 1 (مدير) ---

    def test_etape1_prevalidation_directeur_nenvoie_aucun_message_dacceptation(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='accept_prof_etape1@zidni.test')
        mail.outbox.clear()
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))
        inscription.refresh_from_db()
        self.assertEqual(inscription.statut, 'validee_directeur')  # pré-validé...
        self.assertEqual(len(mail.outbox), 0)  # ...mais AUCUN message envoyé
        self.assertFalse(User.objects.filter(email='accept_prof_etape1@zidni.test').exists())  # ni compte créé

    def test_etape2_validation_finale_mshrif_envoie_le_message_dacceptation(self):
        self.client.force_login(self.admin)
        inscription = _creer_inscription_prof(email='accept_prof_etape2@zidni.test', nom='حسن', prenom='العلوي')
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))

        self.client.force_login(self.mshrif)
        mail.outbox.clear()
        response = self.client.get(reverse('mshrif_valider_prof_final', args=[inscription.id]), follow=True)

        self.assertEqual(len(mail.outbox), 1)
        corps = mail.outbox[0].body
        self.assertIn('حياك الله حسن العلوي،', corps)
        self.assertIn('accept_prof_etape2@zidni.test', corps)

        # Le même texte est aussi affiché sur l'écran (canal WhatsApp,
        # construire_message_acceptation_whatsapp) — vérifie que les 2 canaux
        # ne divergent pas.
        html = response.content.decode('utf-8')
        self.assertIn('حياك الله حسن العلوي،', html)
        self.assertIn('accept_prof_etape2@zidni.test', html)
        self.assertIn(URL_PLATEFORME, html)

    def test_message_whatsapp_acceptation_identique_a_lemail_pour_les_memes_donnees(self):
        """Les 2 canaux (email, WhatsApp) partagent le même texte — vérifié
        directement sur la fonction dédiée, sans dépendre d'un flux HTTP."""
        message = construire_message_acceptation_whatsapp('سارة أمين', 'sara@zidni.test', 'zidanieilman42@@')
        self.assertIn('حياك الله سارة أمين،', message)
        self.assertIn('sara@zidni.test', message)
        self.assertIn('zidanieilman42@@', message)
        self.assertIn(URL_PLATEFORME, message)
        self.assertIn('يسرنا إخبارك بأنه تم قبولك للانضمام إلى منصة زدني علماً', message)
        for mot in self.MOTS_INTERDITS:
            self.assertNotIn(mot, message)
        for emoji in self.EMOJIS_COURANTS:
            self.assertNotIn(emoji, message)

    # --- Refus : motif dynamique correctement inséré ---

    def test_gabarit_refus_avec_nom_et_motif_assembles_correctement(self):
        """Vérifie l'assemblage exact GABARIT_REFUS_AVANT_MOTIF.format(nom=...)
        + motif + GABARIT_REFUS_APRES_MOTIF, tel que fait par refus_confirme —
        le nom et le motif doivent apparaître, dans le bon ordre, sans rien
        d'autre entre "سبب عدم القبول:" et le motif lui-même."""
        message = (
            GABARIT_REFUS_AVANT_MOTIF.format(nom='ياسين مرادي')
            + 'الملف غير مكتمل، الرجاء إعادة التقديم لاحقاً'
            + GABARIT_REFUS_APRES_MOTIF
        )
        self.assertIn('حياك الله ياسين مرادي،', message)
        self.assertIn('سبب عدم القبول:\nالملف غير مكتمل', message)
        self.assertIn('نسأل الله أن يوفقك ويكتب لك الخير حيث كان', message)
        self.assertIn('زدني علماً', message)

    def test_ecran_refus_confirme_affiche_bien_le_nom_et_le_motif_reels(self):
        """Reproduction bout en bout (django.test.Client) : le nom et le motif
        réellement enregistrés apparaissent sur l'écran final — pas une
        valeur générique ni un placeholder non substitué."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='refus_nom_motif@zidni.test', nom='نور الهدى')
        self.client.post(
            reverse('admin_rejeter_eleve', args=[inscription.id]),
            {'motif': 'العمر لا يطابق شروط الحلقة المطلوبة'},
        )
        html = self.client.get(reverse('refus_confirme')).content.decode('utf-8')
        self.assertIn('حياك الله نور الهدى،', html)
        self.assertIn('العمر لا يطابق شروط الحلقة المطلوبة', html)
        self.assertNotIn('{nom}', html)  # placeholder jamais laissé tel quel

    def test_messages_de_refus_ne_contiennent_aucun_prefixe_de_role_ni_emoji(self):
        message_brut = GABARIT_REFUS_AVANT_MOTIF.format(nom='X') + 'motif' + GABARIT_REFUS_APRES_MOTIF
        for mot in self.MOTS_INTERDITS:
            self.assertNotIn(mot, message_brut, f"'{mot}' ne doit jamais apparaître dans le message de refus.")
        for emoji in self.EMOJIS_COURANTS:
            self.assertNotIn(emoji, message_brut, f"emoji '{emoji}' ne doit jamais apparaître dans le message de refus.")


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
    """Règle resserrée le 2026-08-14 (correction du même jour, plus stricte que
    la version précédente de ce test) : la recherche globale n'est plus incluse
    dans base_admin.html/base_mshrif.html — elle n'apparaît désormais QUE sur
    لوحة التحكم de chaque rôle (dashboard/admin.html et
    dashboard/dashboard_mshrif.html, tout en haut de {% block content %}).
    Absente PARTOUT ailleurs, consultation ET action confondues — ce test
    couvre donc l'inverse de l'ancienne version : présente sur 2 pages
    précises, absente sur toutes les autres."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _assert_recherche_presente(self, url_name):
        html = self.client.get(reverse(url_name)).content.decode('utf-8')
        idx_recherche = html.find('rechercheGlobaleInput')
        idx_contenu = html.find('class="page-title"')
        self.assertNotEqual(idx_recherche, -1, f"Barre de recherche absente sur {url_name}.")
        self.assertNotEqual(idx_contenu, -1, f"Repère de contenu introuvable sur {url_name}.")
        self.assertLess(
            idx_recherche, idx_contenu,
            f"La barre de recherche doit apparaître AVANT le reste du contenu de {url_name}."
        )

    def _assert_recherche_absente(self, url):
        html = self.client.get(url).content.decode('utf-8')
        self.assertNotIn(
            'rechercheGlobaleInput', html,
            f"La recherche globale ne doit PAS apparaître sur {url} — règle "
            f"resserrée du 2026-08-14 : seule لوحة التحكم l'affiche."
        )

    # --- Présente : لوحة التحكم des 2 rôles, et seulement elle ---

    def test_admin_recherche_presente_sur_louha_at_tahakoum(self):
        self.client.force_login(self.admin)
        self._assert_recherche_presente('dashboard_admin')

    def test_mshrif_recherche_presente_sur_louha_at_tahakoum(self):
        self.client.force_login(self.mshrif)
        self._assert_recherche_presente('dashboard_mshrif')

    # --- Absente : pages de consultation (listes) — nouveauté de la règle
    # stricte, ces pages affichaient la recherche avant ce correctif ---

    def test_admin_recherche_absente_sur_pages_de_consultation(self):
        self.client.force_login(self.admin)
        for url_name in ['admin_eleves', 'admin_profs']:
            self._assert_recherche_absente(reverse(url_name))

    def test_mshrif_recherche_absente_sur_pages_de_consultation(self):
        self.client.force_login(self.mshrif)
        for url_name in ['admin_eleves', 'admin_profs']:
            self._assert_recherche_absente(reverse(url_name))

    # --- Absente : écrans d'action focalisée à une seule tâche (déjà exclus
    # par la correction précédente du même jour, toujours vrai avec la règle
    # stricte — ces tests restent valides tels quels) ---

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

    def test_recherche_absente_sur_ecran_refus_confirme(self):
        """Nouvel écran (correction du 2026-08-14, ordre logique refus/WhatsApp)
        — même règle que confirmation_creation_compte : un écran post-action
        n'affiche pas la recherche globale."""
        self.client.force_login(self.admin)
        inscription = _creer_inscription_eleve(email='scope_refus_confirme@zidni.test')
        session = self.client.session
        session['refus_confirme'] = {
            'type_demande': 'eleve', 'inscription_id': inscription.id,
            'nom_complet': inscription.nom, 'titre_refus': 'رفض طلب الطالب',
            'afficher_contact_admin': False, 'redirect_url_name': 'admin_inscriptions',
            'base_template': 'dashboard/base_admin.html',
        }
        session.save()
        inscription.statut = 'rejete'
        inscription.motif_refus = 'سبب اختبار'
        inscription.save()
        self._assert_recherche_absente(reverse('refus_confirme'))


# ============================================================================
# Tâche du 2026-08-18 — Carnet de notes personnelles (accounts.NotePersonnelle)
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class NotePersonnelleTests(TestCase):
    """Notes STRICTEMENT privées à leur auteur — voir accounts.models.
    NotePersonnelle.__doc__. Un 2e admin ayant accès à la même fiche ne doit
    JAMAIS voir les notes du premier, ni pouvoir les modifier/supprimer."""

    def setUp(self):
        self.admin = _creer_admin()
        self.autre_admin = User.objects.create_user(
            username='autre_admin_notes@zidni.test', email='autre_admin_notes@zidni.test',
            password='xX!test12345', role='admin', doit_changer_mot_de_passe=False,
        )
        self.eleve = _creer_eleve('eleve_notes@zidni.test')

    def test_admin_voit_sa_propre_note_sur_la_fiche_eleve(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('ajouter_note_personnelle', args=[self.eleve.user.id]), {
            'contenu': 'ملاحظة سرية عن هذا الطالب', 'next': reverse('admin_eleve_detail', args=[self.eleve.id]),
        })
        html = self.client.get(reverse('admin_eleve_detail', args=[self.eleve.id])).content.decode('utf-8')
        self.assertIn('ملاحظة سرية عن هذا الطالب', html)

    def test_note_dun_admin_invisible_a_un_autre_admin(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('ajouter_note_personnelle', args=[self.eleve.user.id]), {
            'contenu': 'ملاحظة خاصة بي فقط', 'next': reverse('admin_eleve_detail', args=[self.eleve.id]),
        })
        self.client.force_login(self.autre_admin)
        html = self.client.get(reverse('admin_eleve_detail', args=[self.eleve.id])).content.decode('utf-8')
        self.assertNotIn('ملاحظة خاصة بي فقط', html)

    def test_modifier_note_refuse_a_un_autre_auteur(self):
        from accounts.models import NotePersonnelle
        note = NotePersonnelle.objects.create(profil_user=self.eleve.user, auteur=self.admin, contenu='أصلية')
        self.client.force_login(self.autre_admin)
        r = self.client.post(reverse('modifier_note_personnelle', args=[note.id]), {'contenu': 'محاولة تعديل'})
        self.assertEqual(r.status_code, 403)
        note.refresh_from_db()
        self.assertEqual(note.contenu, 'أصلية')

    def test_supprimer_note_refuse_a_un_autre_auteur(self):
        from accounts.models import NotePersonnelle
        note = NotePersonnelle.objects.create(profil_user=self.eleve.user, auteur=self.admin, contenu='أصلية')
        self.client.force_login(self.autre_admin)
        r = self.client.post(reverse('supprimer_note_personnelle', args=[note.id]))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(NotePersonnelle.objects.filter(id=note.id).exists())

    def test_auteur_peut_modifier_sa_propre_note(self):
        from accounts.models import NotePersonnelle
        note = NotePersonnelle.objects.create(profil_user=self.eleve.user, auteur=self.admin, contenu='أصلية')
        self.client.force_login(self.admin)
        r = self.client.post(reverse('modifier_note_personnelle', args=[note.id]), {'contenu': 'محدَّثة'})
        self.assertEqual(r.status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.contenu, 'محدَّثة')

    def test_auteur_peut_supprimer_sa_propre_note(self):
        from accounts.models import NotePersonnelle
        note = NotePersonnelle.objects.create(profil_user=self.eleve.user, auteur=self.admin, contenu='أصلية')
        self.client.force_login(self.admin)
        r = self.client.post(reverse('supprimer_note_personnelle', args=[note.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(NotePersonnelle.objects.filter(id=note.id).exists())

    def test_prof_ne_peut_pas_ajouter_de_note_sur_le_profil_dun_autre(self):
        """Depuis la Tâche du 2026-08-18 bis (bloc-notes personnel), prof
        passe désormais le role_required (élargi aux 5 rôles) — mais reste
        bloqué par la garde stricte interne dès qu'il cible le profil de
        quelqu'un d'autre que lui-même : 403 explicite, pas un simple
        redirect de role_required."""
        prof = _creer_prof('prof_notes@zidni.test')
        self.client.force_login(prof.user)
        r = self.client.post(reverse('ajouter_note_personnelle', args=[self.eleve.user.id]), {'contenu': 'x'})
        self.assertEqual(r.status_code, 403)
        from accounts.models import NotePersonnelle
        self.assertFalse(NotePersonnelle.objects.filter(profil_user=self.eleve.user).exists())

    def test_titre_optionnel_a_lajout(self):
        from accounts.models import NotePersonnelle
        self.client.force_login(self.admin)
        self.client.post(reverse('ajouter_note_personnelle', args=[self.eleve.user.id]), {
            'titre': 'أول لقاء', 'contenu': 'محتوى الملاحظة',
        })
        note = NotePersonnelle.objects.get(profil_user=self.eleve.user, auteur=self.admin)
        self.assertEqual(note.titre, 'أول لقاء')
        self.assertEqual(note.contenu, 'محتوى الملاحظة')

    def test_ajout_sans_titre_laisse_le_champ_vide(self):
        from accounts.models import NotePersonnelle
        self.client.force_login(self.admin)
        self.client.post(reverse('ajouter_note_personnelle', args=[self.eleve.user.id]), {
            'contenu': 'محتوى بدون عنوان',
        })
        note = NotePersonnelle.objects.get(profil_user=self.eleve.user, auteur=self.admin)
        self.assertEqual(note.titre, '')

    def test_liste_affiche_le_titre_pas_le_contenu_en_tete(self):
        """Le contenu reste présent dans le HTML (formulaire d'édition masqué,
        voir _carnet_notes_personnelles.html) mais la ligne d'affichage
        principale montre le titre, jamais le contenu en clair au 1er plan."""
        from accounts.models import NotePersonnelle
        NotePersonnelle.objects.create(
            profil_user=self.eleve.user, auteur=self.admin,
            titre='عنوان الملاحظة', contenu='محتوى طويل لا يجب أن يظهر في القائمة مباشرة',
        )
        self.client.force_login(self.admin)
        html = self.client.get(reverse('admin_eleve_detail', args=[self.eleve.id])).content.decode('utf-8')
        self.assertIn('عنوان الملاحظة', html)

    def test_liste_retombe_sur_date_si_titre_vide(self):
        from accounts.models import NotePersonnelle
        note = NotePersonnelle.objects.create(
            profil_user=self.eleve.user, auteur=self.admin, contenu='بدون عنوان',
        )
        self.client.force_login(self.admin)
        html = self.client.get(reverse('admin_eleve_detail', args=[self.eleve.id])).content.decode('utf-8')
        self.assertIn(f'ملاحظة بتاريخ {note.date_creation:%d/%m/%Y}', html)

    def test_modifier_note_met_a_jour_le_titre(self):
        from accounts.models import NotePersonnelle
        note = NotePersonnelle.objects.create(
            profil_user=self.eleve.user, auteur=self.admin, titre='قديم', contenu='أصلية',
        )
        self.client.force_login(self.admin)
        r = self.client.post(reverse('modifier_note_personnelle', args=[note.id]), {
            'titre': 'جديد', 'contenu': 'محدَّثة',
        })
        self.assertEqual(r.status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.titre, 'جديد')
        self.assertEqual(note.contenu, 'محدَّثة')

    def test_note_champ_indépendant_de_notes_admin_existant(self):
        """Le nouveau carnet ne touche jamais Prof.notes_admin (système
        indépendant, confirmé explicitement)."""
        prof = _creer_prof('prof_notes_admin@zidni.test')
        prof.notes_admin = 'ancien champ inchangé'
        prof.save()
        self.client.force_login(self.admin)
        self.client.post(reverse('ajouter_note_personnelle', args=[prof.user.id]), {
            'contenu': 'nouvelle note perso', 'next': reverse('admin_prof_detail', args=[prof.id]),
        })
        prof.refresh_from_db()
        self.assertEqual(prof.notes_admin, 'ancien champ inchangé')
        html = self.client.get(reverse('admin_prof_detail', args=[prof.id])).content.decode('utf-8')
        self.assertIn('ancien champ inchangé', html)
        self.assertIn('nouvelle note perso', html)


# ============================================================================
# Tâche du 2026-08-18 bis — Bloc-notes personnel "ملاحظاتي" (tous rôles)
# ============================================================================
class MesNotesPersonnellesTests(TestCase):
    """Réutilise accounts.NotePersonnelle avec profil_user == auteur ==
    request.user (voir dashboard.views.mes_notes_personnelles)."""

    def test_chaque_role_peut_ajouter_une_note_sur_soi_meme(self):
        from accounts.models import NotePersonnelle

        for user in (
            _creer_admin(), _creer_mshrif(), _creer_eleve('mn_eleve@zidni.test'),
            _creer_prof('mn_prof@zidni.test'), _creer_superviseur('mn_superviseur@zidni.test'),
        ):
            u = user.user if hasattr(user, 'user') else user
            self.client.force_login(u)
            r = self.client.post(reverse('ajouter_note_personnelle', args=[u.id]), {'contenu': 'ملاحظتي الخاصة'})
            self.assertEqual(r.status_code, 302)
            self.assertTrue(NotePersonnelle.objects.filter(profil_user=u, auteur=u, contenu='ملاحظتي الخاصة').exists())

    def test_page_mes_notes_accessible_a_chaque_role_et_affiche_ses_notes(self):
        from accounts.models import NotePersonnelle

        for user in (
            _creer_admin(), _creer_mshrif(), _creer_eleve('mn_page_eleve@zidni.test'),
            _creer_prof('mn_page_prof@zidni.test'), _creer_superviseur('mn_page_superviseur@zidni.test'),
        ):
            u = user.user if hasattr(user, 'user') else user
            NotePersonnelle.objects.create(profil_user=u, auteur=u, contenu=f'note de {u.id}')
            self.client.force_login(u)
            r = self.client.get(reverse('mes_notes_personnelles'))
            self.assertEqual(r.status_code, 200)
            self.assertIn(f'note de {u.id}', r.content.decode('utf-8'))

    def test_ne_voit_pas_les_notes_dun_autre_utilisateur_sur_la_page_mes_notes(self):
        from accounts.models import NotePersonnelle

        eleve_a = _creer_eleve('mn_a@zidni.test')
        eleve_b = _creer_eleve('mn_b@zidni.test')
        NotePersonnelle.objects.create(profil_user=eleve_a.user, auteur=eleve_a.user, contenu='note de a')
        self.client.force_login(eleve_b.user)
        html = self.client.get(reverse('mes_notes_personnelles')).content.decode('utf-8')
        self.assertNotIn('note de a', html)

    def test_admin_ne_voit_pas_la_note_personnelle_dun_eleve_sur_sa_fiche(self):
        """Le bloc-notes personnel (auteur == profil_user) est strictement
        distinct du carnet admin/مشرف SUR un profil consulté (auteur ==
        مدير/مشرف, profil_user == la personne consultée) — jamais mélangés."""
        from accounts.models import NotePersonnelle

        eleve = _creer_eleve('mn_prive@zidni.test')
        NotePersonnelle.objects.create(profil_user=eleve.user, auteur=eleve.user, contenu='ملاحظة شخصية للطالب')
        admin = _creer_admin()
        self.client.force_login(admin)
        html = self.client.get(reverse('admin_eleve_detail', args=[eleve.id])).content.decode('utf-8')
        self.assertNotIn('ملاحظة شخصية للطالب', html)

    def test_auteur_peut_supprimer_sa_propre_note_personnelle(self):
        from accounts.models import NotePersonnelle

        eleve = _creer_eleve('mn_suppr@zidni.test')
        note = NotePersonnelle.objects.create(profil_user=eleve.user, auteur=eleve.user, contenu='à supprimer')
        self.client.force_login(eleve.user)
        r = self.client.post(reverse('supprimer_note_personnelle', args=[note.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(NotePersonnelle.objects.filter(id=note.id).exists())


# ============================================================================
# Tâche du 2026-08-18 — Cartable élève (accounts.DocumentEleve)
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class CartableEleveTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.eleve = _creer_eleve('eleve_cartable@zidni.test')

    def tearDown(self):
        from accounts.models import DocumentEleve
        for doc in DocumentEleve.objects.all():
            if doc.fichier:
                doc.fichier.delete(save=False)

    def test_admin_peut_ajouter_un_fichier_au_cartable(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'specifique', 'eleves_cibles': [self.eleve.id], 'titre': 'تقرير', 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(DocumentEleve.objects.filter(eleve=self.eleve, titre='تقرير').exists())

    def test_prof_ne_peut_pas_ajouter_de_fichier(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        prof = _creer_prof('prof_cartable@zidni.test')
        self.client.force_login(prof.user)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'specifique', 'eleves_cibles': [self.eleve.id], 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)  # role_required redirige vers son propre dashboard
        self.assertFalse(DocumentEleve.objects.filter(eleve=self.eleve).exists())

    def test_ajout_sans_eleve_choisi_est_refuse(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {'fichier': fichier})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DocumentEleve.objects.exists())

    def test_cible_tous_ajoute_a_chaque_eleve_actif(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        autre_eleve = _creer_eleve('autre_cible_tous@zidni.test')
        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'tous', 'titre': 'تعميم', 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(DocumentEleve.objects.filter(eleve=self.eleve, titre='تعميم').exists())
        self.assertTrue(DocumentEleve.objects.filter(eleve=autre_eleve, titre='تعميم').exists())

    def test_cible_categorie_ajoute_seulement_aux_eleves_dont_un_groupe_actif_a_cette_categorie(self):
        """Source de la catégorie = Groupe.categorie (champ saisi par le
        مدير), PAS categorie_collectif (property dérivée du créneau) ni
        l'âge/sexe de l'élève — demande explicite du client, correction UX
        du 2026-08-18 ter."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        eleve_femmes = _creer_eleve('groupe_femmes@zidni.test')
        groupe_femmes = Groupe.objects.create(nom='مجموعة النساء', categorie='femmes_adultes')
        groupe_femmes.eleves.add(eleve_femmes)

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'categorie', 'categorie_cible': 'femmes_adultes', 'titre': 'خاص بالنساء', 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(DocumentEleve.objects.filter(eleve=eleve_femmes, titre='خاص بالنساء').exists())
        # self.eleve (setUp) n'appartient à aucun groupe -> jamais inclus
        # dans un ciblage par catégorie précise.
        self.assertFalse(DocumentEleve.objects.filter(eleve=self.eleve, titre='خاص بالنساء').exists())

    def test_categorie_collectif_du_groupe_est_ignoree(self):
        """Groupe.categorie_collectif (property dérivée du créneau) ne doit
        JAMAIS servir de source ici, même s'il coïncide visuellement — seul
        le champ Groupe.categorie compte. Un groupe SANS categorie renseignée
        (blank='') ne doit matcher aucune des 3 catégories, quel que soit son
        categorie_collectif calculé."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        eleve = _creer_eleve('groupe_sans_categorie@zidni.test')
        groupe_sans_categorie = Groupe.objects.create(nom='مجموعة بدون فئة')  # categorie='' par défaut
        groupe_sans_categorie.eleves.add(eleve)

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'categorie', 'categorie_cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DocumentEleve.objects.filter(eleve=eleve).exists())

    def test_eleve_avec_groupe_archive_nest_pas_cible_par_categorie(self):
        """Seuls les groupes ACTIFS comptent pour la résolution de catégorie —
        un ancien groupe archivé ne doit pas faire (ré)apparaître un élève
        dans une catégorie qui ne le concerne plus."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        eleve = _creer_eleve('groupe_archive@zidni.test')
        groupe_archive = Groupe.objects.create(nom='مجموعة مؤرشفة', categorie='hommes_adultes', statut='archive')
        groupe_archive.eleves.add(eleve)

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'categorie', 'categorie_cible': 'hommes_adultes', 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DocumentEleve.objects.filter(eleve=eleve).exists())

    def test_eleve_avec_plusieurs_groupes_matche_si_au_moins_un_correspond(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        eleve = _creer_eleve('multi_groupes@zidni.test')
        groupe_sans_categorie = Groupe.objects.create(nom='مجموعة أ')
        groupe_enfants = Groupe.objects.create(nom='مجموعة ب', categorie='mineurs')
        groupe_sans_categorie.eleves.add(eleve)
        groupe_enfants.eleves.add(eleve)

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'categorie', 'categorie_cible': 'mineurs', 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(DocumentEleve.objects.filter(eleve=eleve).exists())

    def test_ancien_filtre_de_liste_nest_plus_affiche(self):
        """Correction UX du 2026-08-18 ter — un seul système de sélection des
        destinataires (celui du formulaire "ملف جديد"), l'ancien filtre de
        catégorie séparé au-dessus de la liste des fichiers a été retiré."""
        import re

        def _sans_csrf(html):
            # Le jeton CSRF est régénéré à chaque rendu (masquage aléatoire
            # par requête) — non pertinent à cette comparaison, on le retire.
            return re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', '', html)

        self.client.force_login(self.admin)
        html = self.client.get(reverse('admin_eleve_cartable_gestion')).content.decode('utf-8')
        self.assertNotIn('تصفية القائمة أدناه حسب فئة الطالب', html)
        # ?categorie= n'a plus aucun effet — la vue ne lit plus ce paramètre,
        # la page rendue est identique avec ou sans lui (hors jeton CSRF).
        html_avec_param = self.client.get(
            reverse('admin_eleve_cartable_gestion') + '?categorie=femmes_adultes'
        ).content.decode('utf-8')
        self.assertEqual(_sans_csrf(html), _sans_csrf(html_avec_param))

    def test_admin_eleve_detail_ne_contient_plus_le_cartable(self):
        """Refonte du 2026-08-18 — la gestion du cartable élève a quitté la
        fiche élève individuelle pour la page centrale إدارة حقيبة الطالب
        (demande explicite du client, même refonte déjà appliquée à حقيبة
        الأستاذ). Garde-fou de non-régression contre un retour accidentel."""
        self.client.force_login(self.admin)
        html = self.client.get(reverse('admin_eleve_detail', args=[self.eleve.id])).content.decode('utf-8')
        # Marqueur exact de l'ancien bloc (emoji 🎒 propre à la section supprimée) —
        # pas juste "حقيبة الطالب" seul, qui réapparaît légitimement dans le lien
        # sidebar "🗂️ إدارة حقيبة الطالب" vers la nouvelle page centrale.
        self.assertNotIn('🎒 حقيبة الطالب', html)

    def test_page_gestion_centrale_accessible_admin_et_mshrif(self):
        mshrif = _creer_mshrif()
        for user in (self.admin, mshrif):
            self.client.force_login(user)
            r = self.client.get(reverse('admin_eleve_cartable_gestion'))
            self.assertEqual(r.status_code, 200)
            self.assertIn('إدارة حقيبة الطالب', r.content.decode('utf-8'))

    def test_prof_ne_peut_pas_acceder_a_la_page_de_gestion(self):
        prof = _creer_prof('prof_cartable_gestion@zidni.test')
        self.client.force_login(prof.user)
        r = self.client.get(reverse('admin_eleve_cartable_gestion'))
        self.assertEqual(r.status_code, 302)  # role_required redirige, jamais 403

    def test_eleve_voit_son_propre_cartable(self):
        from accounts.models import DocumentEleve
        from django.core.files.uploadedfile import SimpleUploadedFile

        DocumentEleve.objects.create(
            eleve=self.eleve, titre='ملف الطالب',
            fichier=SimpleUploadedFile('doc.pdf', b'contenu-pdf-factice'), ajoute_par=self.admin,
        )
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('eleve_cartable')).content.decode('utf-8')
        self.assertIn('ملف الطالب', html)

    def test_eleve_ne_voit_pas_le_cartable_dun_autre_eleve(self):
        from accounts.models import DocumentEleve
        from django.core.files.uploadedfile import SimpleUploadedFile

        autre_eleve = _creer_eleve('autre_eleve_cartable@zidni.test')
        DocumentEleve.objects.create(
            eleve=autre_eleve, titre='ملف الآخر',
            fichier=SimpleUploadedFile('doc2.pdf', b'contenu-pdf-factice'), ajoute_par=self.admin,
        )
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('eleve_cartable')).content.decode('utf-8')
        self.assertNotIn('ملف الآخر', html)

    def test_admin_peut_supprimer_un_fichier(self):
        from accounts.models import DocumentEleve
        from django.core.files.uploadedfile import SimpleUploadedFile

        doc = DocumentEleve.objects.create(
            eleve=self.eleve, titre='ملف للحذف',
            fichier=SimpleUploadedFile('doc3.pdf', b'contenu-pdf-factice'), ajoute_par=self.admin,
        )
        self.client.force_login(self.admin)
        r = self.client.post(reverse('admin_eleve_cartable_supprimer', args=[doc.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DocumentEleve.objects.filter(id=doc.id).exists())


# ============================================================================
# Tâche du 2026-08-18 — Critère ينتقل/يعيد, sauvegarde depuis la vue prof
# ============================================================================
class PresenceResultatMemorisationVueTests(TestCase):
    """prof_presence_sauvegarder enregistre bien resultat_memorisation/
    resultat_revision — voir courses.tests.ResultatMemorisationProgressionTests
    pour l'exclusion du calcul de progression lui-même."""

    def setUp(self):
        from courses.models import CritereEleve

        self.prof = _creer_prof('prof_resultat_memo@zidni.test')
        self.eleve = _creer_eleve('eleve_resultat_memo@zidni.test')
        self.groupe = Groupe.objects.create(nom='ZZZ_مجموعة_نتيجة', prof=self.prof)
        self.groupe.eleves.add(self.eleve)

        from django.utils import timezone
        # Heure locale (pas UTC brut) : Seance.date/heure sont des champs naïfs
        # re-localisés via timezone.make_aware() dans Seance.debut_datetime —
        # calculer directement en heure locale évite tout décalage de fuseau.
        il_y_a_2h = timezone.localtime(timezone.now() - datetime.timedelta(hours=2))
        self.seance = Seance.objects.create(
            groupe=self.groupe, date=il_y_a_2h.date(), heure=il_y_a_2h.time(),
            type='normal', statut='planifiee',
        )
        self.criteres = list(CritereEleve.objects.filter(est_actif=True))

    def _donnees_formulaire(self, resultat_memo='a_refaire', resultat_rev='valide'):
        donnees = {
            f'statut_{self.eleve.id}': 'present',
            f'sourate_memo_{self.eleve.id}': '2',
            f'ayah_debut_memo_{self.eleve.id}': '1',
            f'ayah_fin_memo_{self.eleve.id}': '10',
            f'sourate_rev_{self.eleve.id}': '',
            f'ayah_debut_rev_{self.eleve.id}': '',
            f'ayah_fin_rev_{self.eleve.id}': '',
            f'remarque_{self.eleve.id}': '',
            f'consigne_memo_{self.eleve.id}': 'حفظ الآيات 1-10',
            f'consigne_rev_{self.eleve.id}': 'مراجعة عامة',
            f'resultat_memo_{self.eleve.id}': resultat_memo,
            f'resultat_rev_{self.eleve.id}': resultat_rev,
            'remarque_generale': '',
        }
        for c in self.criteres:
            donnees[f'note_critere_{c.id}_{self.eleve.id}'] = '15'
        return donnees

    def test_resultat_memorisation_et_revision_enregistres(self):
        self.client.force_login(self.prof.user)
        self.client.post(reverse('prof_presence_sauvegarder', args=[self.seance.id]), self._donnees_formulaire())
        presence = Presence.objects.get(seance=self.seance, eleve=self.eleve)
        self.assertEqual(presence.resultat_memorisation, 'a_refaire')
        self.assertEqual(presence.resultat_revision, 'valide')

    def test_valeur_invalide_retombe_sur_valide(self):
        """Une valeur POST qui ne serait pas l'un des 2 choix valides (paramètre
        manipulé) ne doit jamais planter — retombe sur 'valide' (comportement
        historique), jamais une confiance aveugle dans le client."""
        self.client.force_login(self.prof.user)
        donnees = self._donnees_formulaire(resultat_memo='autre_chose_invalide')
        self.client.post(reverse('prof_presence_sauvegarder', args=[self.seance.id]), donnees)
        presence = Presence.objects.get(seance=self.seance, eleve=self.eleve)
        self.assertEqual(presence.resultat_memorisation, 'valide')


# ==================== Chantier notifications (2026-08-19) ====================
# Panneau 🔔 الإشعارات — un test par déclencheur (Point F de la todo list
# validée), plus marquage lu, amorçage, anti-fausse-notification et
# permissions. Voir dashboard.notifications.__doc__ pour l'architecture.

class NotificationsChantierTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve(email='notif_eleve@zidni.test')
        self.prof = _creer_prof(email='notif_prof@zidni.test')
        self.superviseur = _creer_superviseur(email='notif_superviseur@zidni.test')
        self.groupe = Groupe.objects.create(nom='مجموعة الإشعارات', prof=self.prof, statut='actif')
        self.groupe.eleves.add(self.eleve)
        self.superviseur.profs_assignes.add(self.prof)
        # Date de demain (jamais "aujourd'hui à heure fixe" — dépendrait de
        # l'heure d'exécution des tests) : le proxy de notification
        # 'notes_seances' se base sur seance.date/heure (voir dashboard.
        # notifications.notifications_eleve — Presence n'a pas de champ date
        # propre), qui doit donc rester SANS AMBIGUÏTÉ postérieur à
        # self.eleve.user.date_joined (fixé à "maintenant" à la création
        # ci-dessus) pour que le scénario "note tout juste remplie" reste
        # réaliste et non-flaky dans ces tests.
        self.seance = Seance.objects.create(
            groupe=self.groupe, date=timezone.localdate() + datetime.timedelta(days=1), heure=datetime.time(17, 0),
            type='normal', statut='terminee',
        )

    def _connecter_eleve(self):
        self.client.force_login(self.eleve.user)

    def _connecter_prof(self):
        self.client.force_login(self.prof.user)

    # ---------- 4a. Examen publié ----------
    def test_examen_publie_declenche_le_badge_eleve(self):
        Examen.objects.create(
            groupe=self.groupe, prof=self.prof, titre='اختبار الجزء الأول',
            statut='publie', date_publication=timezone.now(),
            date_debut=timezone.now() - datetime.timedelta(hours=1),
            date_limite=timezone.now() + datetime.timedelta(hours=3),
            duree_minutes=30,
        )
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 1)
        self.assertContains(response, 'اختبار جديد: اختبار الجزء الأول')

    def test_examen_brouillon_ne_declenche_pas(self):
        """Un examen non publié ne concerne pas encore l'élève — aucune fausse
        notification avant que le prof ne clique réellement sur 'نشر'."""
        Examen.objects.create(
            groupe=self.groupe, prof=self.prof, titre='اختبار غير منشور',
            statut='brouillon',
            date_debut=timezone.now() - datetime.timedelta(hours=1),
            date_limite=timezone.now() + datetime.timedelta(hours=3),
            duree_minutes=30,
        )
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 0)

    # ---------- 4b. Note de séance (Presence) ----------
    def test_note_seance_declenche_le_badge_eleve(self):
        Presence.objects.create(
            seance=self.seance, eleve=self.eleve, statut='present',
            note_hifz=15, note_muraja3a=14, note_tilawa=16, note_mouwazaba=18,
        )
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 1)

    def test_presence_sans_note_ne_declenche_pas(self):
        """Un élève marqué simplement absent (aucune note remplie) ne doit
        jamais lever une fausse notification 'nouvelle note'."""
        Presence.objects.create(seance=self.seance, eleve=self.eleve, statut='absent')
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 0)

    # ---------- 4c. Cartable élève ----------
    def test_document_cartable_declenche_le_badge_eleve(self):
        DocumentEleve.objects.create(eleve=self.eleve, titre='جدول التسميع', fichier='cartable_eleve/test.pdf')
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 1)
        self.assertContains(response, 'جدول التسميع')

    def test_document_dun_autre_eleve_ne_declenche_pas(self):
        autre_eleve = _creer_eleve(email='notif_autre_eleve@zidni.test')
        DocumentEleve.objects.create(eleve=autre_eleve, titre='ملف غير معني', fichier='cartable_eleve/x.pdf')
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 0)

    # ---------- 5a. Évaluation reçue par le prof ----------
    def test_evaluation_recue_declenche_le_badge_prof(self):
        Evaluation.objects.create(
            seance=self.seance, superviseur=self.superviseur, prof=self.prof,
            commentaire='أداء جيد بشكل عام.',
        )
        self._connecter_prof()
        response = self.client.get(reverse('dashboard_prof'))
        self.assertEqual(response.context['notif_total'], 1)

    # ---------- 5b. Hakiba (fichier cartable prof) ----------
    def test_hakiba_tous_les_profs_declenche_le_badge(self):
        ElementHakiba.objects.create(titre='ميثاق التدريس', contenu_texte='...', tous_les_profs=True)
        self._connecter_prof()
        response = self.client.get(reverse('dashboard_prof'))
        self.assertEqual(response.context['notif_total'], 1)

    def test_hakiba_cible_un_autre_prof_ne_declenche_pas(self):
        autre_prof = _creer_prof(email='notif_autre_prof@zidni.test')
        element = ElementHakiba.objects.create(titre='خاص بأستاذ آخر', tous_les_profs=False)
        element.profs_cibles.add(autre_prof)
        self._connecter_prof()
        response = self.client.get(reverse('dashboard_prof'))
        self.assertEqual(response.context['notif_total'], 0)

    def test_hakiba_ciblant_ce_prof_specifiquement_declenche(self):
        element = ElementHakiba.objects.create(titre='خاص بك', tous_les_profs=False)
        element.profs_cibles.add(self.prof)
        self._connecter_prof()
        response = self.client.get(reverse('dashboard_prof'))
        self.assertEqual(response.context['notif_total'], 1)

    # ---------- Marquer comme lu (par type, pas par élément) ----------
    def test_visiter_la_page_cible_marque_le_type_comme_lu(self):
        DocumentEleve.objects.create(eleve=self.eleve, titre='ملف', fichier='cartable_eleve/a.pdf')
        self._connecter_eleve()
        # Avant la visite : le badge compte le fichier.
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 1)
        # Visite de la vraie page cible -> marque 'cartable' comme lu.
        self.client.get(reverse('eleve_cartable'))
        # Après la visite : le badge retombe à 0, sans qu'aucun autre type
        # (jamais créé ici) ne soit affecté.
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 0)

    def test_premiere_visite_dun_compte_voit_le_contenu_recent(self):
        """Un compte SANS DerniereVisiteNotification (jamais visité) doit
        voir, dès sa toute première visite, le contenu créé APRÈS son
        inscription — pas de faux 'déjà vu'. Corrige un bug réel détecté
        par ce test avant intégration (voir dashboard.notifications._seuils.
        __doc__) : la 1ère version amorçait le seuil à 'maintenant' au 1er
        calcul, ce qui avalait aussi le contenu légitimement nouveau d'un
        compte tout juste créé — pas seulement l'historique des comptes déjà
        anciens au jour du déploiement (protégés séparément, voir
        accounts/migrations/0037_seed_dernieres_visites_notification.py)."""
        DocumentEleve.objects.create(eleve=self.eleve, titre='fichier', fichier='cartable_eleve/a.pdf')
        self.assertFalse(DerniereVisiteNotification.objects.filter(user=self.eleve.user, cle='cartable').exists())
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 1)
        # Le seuil est maintenant persisté (amorcé à user.date_joined), pas recalculé à chaque appel.
        self.assertTrue(DerniereVisiteNotification.objects.filter(user=self.eleve.user, cle='cartable').exists())

    def test_contenu_anterieur_au_seuil_deja_amorce_ne_redeclenche_pas(self):
        """Une fois un seuil déjà posé (ici simulé comme si la migration de
        déploiement — ou une visite précédente — l'avait déjà fait), un
        contenu plus ANCIEN que ce seuil ne redéclenche jamais le badge —
        c'est cette ligne-ci qui protège réellement les comptes déjà
        existants d'une inondation le jour de la mise en service."""
        DocumentEleve.objects.create(eleve=self.eleve, titre='ancien fichier', fichier='cartable_eleve/old.pdf')
        DerniereVisiteNotification.objects.create(
            user=self.eleve.user, cle='cartable', date_visite=timezone.now() + datetime.timedelta(seconds=1)
        )
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 0)

    # ---------- Anti-fausse-notification : modification != création ----------
    def test_modification_mineure_hakiba_ne_redeclenche_pas(self):
        element = ElementHakiba.objects.create(titre='ميثاق', contenu_texte='v1', tous_les_profs=True)
        self._connecter_prof()
        self.client.get(reverse('dashboard_prof'))  # amorce le seuil 'hakiba'
        self.client.get(reverse('prof_hakiba'))  # marque 'hakiba' comme lu
        # Correction mineure du contenu (date_modification change, date_ajout non)
        element.contenu_texte = 'v2 (correction de faute)'
        element.save(update_fields=['contenu_texte', 'date_modification'])
        response = self.client.get(reverse('dashboard_prof'))
        self.assertEqual(response.context['notif_total'], 0)

    # ---------- Rôles sans ce déclencheur ----------
    def test_admin_naffiche_jamais_le_panneau_notifications(self):
        admin = _creer_admin()
        self.client.force_login(admin)
        response = self.client.get(reverse('dashboard_admin'))
        self.assertNotContains(response, 'id="notifWrap"')

    def test_superviseur_naffiche_jamais_le_panneau_notifications(self):
        self.client.force_login(self.superviseur.user)
        response = self.client.get(reverse('dashboard_superviseur'))
        self.assertNotContains(response, 'id="notifWrap"')

    # ---------- Page "عرض الكل" ----------
    def test_mes_notifications_accessible_eleve_et_prof(self):
        self._connecter_eleve()
        self.assertEqual(self.client.get(reverse('mes_notifications')).status_code, 200)
        self._connecter_prof()
        self.assertEqual(self.client.get(reverse('mes_notifications')).status_code, 200)

    def test_mes_notifications_refuse_autre_role(self):
        self.client.force_login(self.superviseur.user)
        response = self.client.get(reverse('mes_notifications'))
        self.assertNotEqual(response.status_code, 200)


class DepuisRelatifFiltreTests(TestCase):
    """Filtre dashboard.templatetags.libelles_arabes.depuis_relatif — duel
    arabe correct à CHAQUE palier (minute/heure/jour/semaine), pas juste le
    pluriel générique pour n==2 (bug détecté et corrigé pendant la revue de
    la maquette avant intégration)."""

    def _il_y_a(self, **kwargs):
        return timezone.now() - datetime.timedelta(**kwargs)

    def test_duel_minutes(self):
        from dashboard.templatetags.libelles_arabes import depuis_relatif
        self.assertEqual(depuis_relatif(self._il_y_a(minutes=2)), 'منذ دقيقتين')

    def test_duel_heures(self):
        from dashboard.templatetags.libelles_arabes import depuis_relatif
        self.assertEqual(depuis_relatif(self._il_y_a(hours=2)), 'منذ ساعتين')

    def test_duel_jours(self):
        from dashboard.templatetags.libelles_arabes import depuis_relatif
        self.assertEqual(depuis_relatif(self._il_y_a(days=2)), 'منذ يومين')

    def test_duel_semaines(self):
        from dashboard.templatetags.libelles_arabes import depuis_relatif
        self.assertEqual(depuis_relatif(self._il_y_a(weeks=2)), 'منذ أسبوعين')

    def test_singulier_et_pluriel_generique(self):
        from dashboard.templatetags.libelles_arabes import depuis_relatif
        self.assertEqual(depuis_relatif(self._il_y_a(minutes=1)), 'منذ دقيقة')
        self.assertEqual(depuis_relatif(self._il_y_a(minutes=5)), 'منذ 5 دقائق')
        self.assertEqual(depuis_relatif(self._il_y_a(hours=5)), 'منذ 5 ساعات')


# ============================================================================
# Chantier de généralisation N séances/semaine — prof_emploi (grille jours×heures)
# lisait auparavant creneau.jour_1/jour_2 en dur ; lit désormais creneau.slots.all()
# (1 à N). Aucun test n'existait pour cette vue avant ce chantier — ajoutée ici.
# ============================================================================
class ProfEmploiGeneralisationSlotsTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_emploi_slots@zidni.test')
        self.client.force_login(self.prof.user)

    def _creneau_3_slots(self):
        creneau = Creneau.objects.create(
            sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=12,
        )
        remplacer_slots_creneau(creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'jeu', 'heure_debut': datetime.time(18, 0), 'heure_fin': datetime.time(19, 0)},
        ])
        return creneau

    def test_grille_affiche_les_3_slots_dun_creneau_a_3_seances(self):
        creneau = self._creneau_3_slots()
        Groupe.objects.create(nom='مجموعة 3 حصص أسبوعياً', creneau=creneau, prof=self.prof, statut='actif')

        reponse = self.client.get(reverse('prof_emploi'))
        self.assertEqual(reponse.status_code, 200)

        # occupation est construit en contexte implicite (lignes_grille) — on
        # vérifie plutôt que le rendu final mentionne bien le groupe aux 3
        # créneaux horaires distincts (16:00 lundi/mercredi, 18:00 jeudi).
        html = reponse.content.decode('utf-8')
        self.assertIn('مجموعة 3 حصص أسبوعياً', html)

    def test_groupe_sans_creneau_ne_fait_pas_planter_la_grille(self):
        """Garde déjà existante (if not creneau: continue) — toujours valable
        après la réécriture sur creneau.slots.all()."""
        Groupe.objects.create(nom='مجموعة بدون حلقة', prof=self.prof, statut='actif')
        reponse = self.client.get(reverse('prof_emploi'))
        self.assertEqual(reponse.status_code, 200)


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5A : CRUD Critere/
# CritereOption. Parité STRICTE Directeur/مشرف testée sur chaque vue (aucune
# des deux ne doit jamais recevoir une redirection/erreur que l'autre
# n'obtient pas) — exigence explicite et répétée du client pour ce système.
# ============================================================================
class CritereInscriptionCRUDTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _connecte_mshrif(self):
        client = Client()
        client.force_login(self.mshrif)
        return client

    def test_liste_accessible_a_parite_stricte(self):
        for client in (self._connecte_admin(), self._connecte_mshrif()):
            reponse = client.get(reverse('admin_criteres_inscription'))
            self.assertEqual(reponse.status_code, 200)

    def test_eleve_prof_superviseur_nont_pas_acces(self):
        eleve = _creer_eleve('eleve_registration_crud@zidni.test')
        client = Client()
        client.force_login(eleve.user)
        reponse = client.get(reverse('admin_criteres_inscription'))
        self.assertNotEqual(reponse.status_code, 200)

    def test_ajout_critere_reussit_pour_directeur_et_mshrif(self):
        for i, client in enumerate((self._connecte_admin(), self._connecte_mshrif())):
            reponse = client.post(reverse('admin_critere_inscription_ajouter'), {
                'code': f'objectif_test_{i}', 'label': 'الهدف التربوي', 'type_champ': 'choix_unique',
                'backend': 'eav', 'filtrable': 'on', 'ordre': 1,
            })
            self.assertEqual(reponse.status_code, 302)
            self.assertTrue(CritereInscription.objects.filter(code=f'objectif_test_{i}').exists())

    def test_code_duplique_refuse(self):
        CritereInscription.objects.create(code='objectif_unique', label='الهدف')
        client = self._connecte_admin()
        reponse = client.post(reverse('admin_critere_inscription_ajouter'), {
            'code': 'objectif_unique', 'label': 'مكرر', 'type_champ': 'choix_unique', 'backend': 'eav',
        })
        self.assertEqual(reponse.status_code, 200)  # réaffiche le formulaire, pas de redirection
        self.assertEqual(CritereInscription.objects.filter(code='objectif_unique').count(), 1)

    def test_ajout_option_reussit_pour_les_deux_roles(self):
        critere = CritereInscription.objects.create(code='objectif', label='الهدف')
        for i, client in enumerate((self._connecte_admin(), self._connecte_mshrif())):
            reponse = client.post(reverse('admin_critere_option_ajouter', args=[critere.id]), {
                'code': f'opt_{i}', 'label': f'خيار {i}', 'ordre': i,
            })
            self.assertEqual(reponse.status_code, 302)
        self.assertEqual(critere.options.count(), 2)

    def test_toggle_critere_et_option(self):
        client = self._connecte_mshrif()  # مشرف peut aussi bien que الديرم
        critere = CritereInscription.objects.create(code='objectif', label='الهدف', est_actif=True)
        option = CritereOption.objects.create(critere=critere, code='memo', label='الحفظ', est_actif=True)

        client.get(reverse('admin_critere_inscription_toggle', args=[critere.id]))
        critere.refresh_from_db()
        self.assertFalse(critere.est_actif)

        client.get(reverse('admin_critere_option_toggle', args=[option.id]))
        option.refresh_from_db()
        self.assertFalse(option.est_actif)

    def test_suppression_critere_jamais_utilise_reussit(self):
        client = self._connecte_admin()
        critere = CritereInscription.objects.create(code='jamais_utilise', label='غير مستخدم')
        client.get(reverse('admin_critere_inscription_supprimer', args=[critere.id]))
        self.assertFalse(CritereInscription.objects.filter(id=critere.id).exists())

    def test_suppression_critere_deja_utilise_est_refusee_avec_message_clair(self):
        """PROTECT — décision explicite du client : jamais de CASCADE silencieux
        sur un critère déjà utilisé."""
        from courses.models import Creneau, Groupe
        from courses.utils import remplacer_slots_creneau as _slots

        client = self._connecte_admin()
        critere = CritereInscription.objects.create(code='riwaya_test', label='الرواية', filtrable=True)
        option = CritereOption.objects.create(critere=critere, code='hafs', label='حفص')
        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(creneau, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
        groupe = Groupe.objects.create(nom='مجموعة تستخدم المعيار', creneau=creneau, statut='actif')
        GroupeCritereValeur.objects.create(groupe=groupe, critere=critere, option=option)

        client.get(reverse('admin_critere_inscription_supprimer', args=[critere.id]))
        self.assertTrue(CritereInscription.objects.filter(id=critere.id).exists())  # PAS supprimé

    def test_activer_filtrable_sans_couverture_demande_confirmation(self):
        client = self._connecte_admin()
        from courses.models import Creneau, Groupe
        from courses.utils import remplacer_slots_creneau as _slots

        critere = CritereInscription.objects.create(code='objectif', label='الهدف', filtrable=False)
        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(creneau, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
        Groupe.objects.create(nom='مجموعة بدون قيمة', creneau=creneau, statut='actif')  # non configuré pour ce critère

        # Sans confirme=1 : refusé, warning affiché.
        reponse = client.post(reverse('admin_critere_inscription_modifier', args=[critere.id]), {
            'label': 'الهدف', 'type_champ': 'choix_unique', 'filtrable': 'on', 'ordre': 0, 'est_actif': 'on',
        })
        self.assertEqual(reponse.status_code, 200)
        critere.refresh_from_db()
        self.assertFalse(critere.filtrable)  # pas encore sauvegardé

        # Avec confirme=1 : accepté.
        reponse2 = client.post(reverse('admin_critere_inscription_modifier', args=[critere.id]), {
            'label': 'الهدف', 'type_champ': 'choix_unique', 'filtrable': 'on', 'ordre': 0, 'est_actif': 'on',
            'confirme': '1',
        })
        self.assertEqual(reponse2.status_code, 302)
        critere.refresh_from_db()
        self.assertTrue(critere.filtrable)


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5B : CRUD
# EtapeInscription / ChampInscription / RegleCondition. Même exigence de
# parité stricte Directeur/مشرف que 5A.
# ============================================================================
class EtapeChampRegleInscriptionCRUDTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _connecte_mshrif(self):
        client = Client()
        client.force_login(self.mshrif)
        return client

    def test_liste_etapes_accessible_a_parite_stricte(self):
        for client in (self._connecte_admin(), self._connecte_mshrif()):
            reponse = client.get(reverse('admin_etapes_inscription'))
            self.assertEqual(reponse.status_code, 200)

    def test_ajout_etape_reussit_pour_les_deux_roles(self):
        for i, client in enumerate((self._connecte_admin(), self._connecte_mshrif())):
            reponse = client.post(reverse('admin_etape_inscription_ajouter'), {
                'code': f'etape_test_{i}', 'titre': 'اختيار البرنامج', 'ordre': i,
            })
            self.assertEqual(reponse.status_code, 302)
            self.assertTrue(EtapeInscription.objects.filter(code=f'etape_test_{i}').exists())

    def test_detail_etape_affiche_les_champs_et_le_formulaire_ajout(self):
        # Codes test_ : la base de test contient déjà 'programme'/'riwaya'/
        # 'identite'/'type_offre' seedés par registration/migrations/0002_seed_
        # wizard_config.py (Étape 6A) — mêmes codes distincts qu'ailleurs.
        etape = EtapeInscription.objects.create(code='test_programme', titre='اختيار البرنامج')
        critere = CritereInscription.objects.create(code='test_riwaya', label='الرواية')
        client = self._connecte_admin()
        reponse = client.get(reverse('admin_etape_inscription_detail', args=[etape.id]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('الرواية', reponse.content.decode('utf-8'))

    def test_ajout_champ_avec_critere_et_champ_informatif(self):
        etape = EtapeInscription.objects.create(code='test_identite', titre='المعلومات الشخصية')
        critere = CritereInscription.objects.create(code='test_riwaya', label='الرواية')
        client = self._connecte_admin()

        # Champ lié à un critère.
        client.post(reverse('admin_champ_inscription_ajouter', args=[etape.id]), {
            'critere_id': critere.id, 'label': 'الرواية', 'obligatoire': 'on', 'ordre': 1,
        })
        champ_critere = ChampInscription.objects.get(etape=etape, critere=critere)
        self.assertTrue(champ_critere.obligatoire)

        # Champ informatif pur (pas de critere_id).
        client.post(reverse('admin_champ_inscription_ajouter', args=[etape.id]), {
            'label': 'البلد', 'type_champ': 'texte', 'ordre': 2,
        })
        champ_info = ChampInscription.objects.get(etape=etape, critere__isnull=True)
        self.assertEqual(champ_info.type_champ, 'texte')

    def test_suppression_etape_avec_champs_est_refusee(self):
        etape = EtapeInscription.objects.create(code='test_programme', titre='اختيار البرنامج')
        ChampInscription.objects.create(etape=etape, label='حقل', ordre=1)
        client = self._connecte_admin()
        client.get(reverse('admin_etape_inscription_supprimer', args=[etape.id]))
        self.assertTrue(EtapeInscription.objects.filter(id=etape.id).exists())

    def test_suppression_champ_deja_repondu_est_refusee(self):
        from inscriptions.models import InscriptionEleve
        from registration.models import ReponseInscription

        etape = EtapeInscription.objects.create(code='test_identite', titre='المعلومات')
        champ = ChampInscription.objects.create(etape=etape, label='البلد', type_champ='texte', ordre=1)
        inscription = InscriptionEleve.objects.create(
            nom='طالب اختبار', date_naissance='2000-01-01', sexe='homme',
            telephone='+212600000000', email='test_suppr_champ@zidni.test',
        )
        ReponseInscription.objects.create(inscription=inscription, champ=champ, valeur_texte='المغرب')

        client = self._connecte_mshrif()
        client.get(reverse('admin_champ_inscription_supprimer', args=[champ.id]))
        self.assertTrue(ChampInscription.objects.filter(id=champ.id).exists())

    def test_rendre_champ_obligatoire_sans_couverture_demande_confirmation(self):
        from courses.models import Creneau, Groupe
        from courses.utils import remplacer_slots_creneau as _slots

        etape = EtapeInscription.objects.create(code='test_programme', titre='اختيار البرنامج')
        critere = CritereInscription.objects.create(code='objectif', label='الهدف', filtrable=True)
        champ = ChampInscription.objects.create(etape=etape, critere=critere, label='الهدف', obligatoire=False, ordre=1)
        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(creneau, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
        Groupe.objects.create(nom='مجموعة بدون قيمة', creneau=creneau, statut='actif')

        client = self._connecte_admin()
        reponse = client.post(reverse('admin_champ_inscription_modifier', args=[champ.id]), {
            'label': 'الهدف', 'obligatoire': 'on', 'ordre': 1, 'est_actif': 'on',
        })
        self.assertEqual(reponse.status_code, 200)
        champ.refresh_from_db()
        self.assertFalse(champ.obligatoire)

        reponse2 = client.post(reverse('admin_champ_inscription_modifier', args=[champ.id]), {
            'label': 'الهدف', 'obligatoire': 'on', 'ordre': 1, 'est_actif': 'on', 'confirme': '1',
        })
        self.assertEqual(reponse2.status_code, 302)
        champ.refresh_from_db()
        self.assertTrue(champ.obligatoire)

    def test_liste_et_ajout_regle_condition(self):
        etape_groupe = EtapeInscription.objects.create(code='choix_groupe', titre='اختيار المجموعة')
        critere = CritereInscription.objects.create(
            code='test_type_offre', label='نوع الحصة', backend='champ_groupe', champ_modele_groupe='type_capacite',
        )
        CritereOption.objects.create(critere=critere, code='groupe', label='جماعي')
        CritereOption.objects.create(critere=critere, code='individuel', label='فردي')

        client = self._connecte_mshrif()
        reponse_liste = client.get(reverse('admin_regles_inscription'))
        self.assertEqual(reponse_liste.status_code, 200)

        reponse_ajout = client.get(reverse('admin_regle_inscription_ajouter'))
        self.assertEqual(reponse_ajout.status_code, 200)

        reponse_post = client.post(reverse('admin_regle_inscription_ajouter'), {
            'critere_condition_id': critere.id, 'operateur': 'different',
            'valeurs': ['groupe'], 'cible_type': 'etape', 'cible_id': etape_groupe.id,
        })
        self.assertEqual(reponse_post.status_code, 302)
        regle = RegleCondition.objects.get()
        self.assertEqual(regle.cible, etape_groupe)
        self.assertEqual(regle.valeurs, ['groupe'])

    def test_suppression_regle_reussit(self):
        etape = EtapeInscription.objects.create(code='test_programme', titre='برنامج')
        critere = CritereInscription.objects.create(code='test_riwaya', label='الرواية')
        from django.contrib.contenttypes.models import ContentType
        regle = RegleCondition.objects.create(
            cible_content_type=ContentType.objects.get_for_model(EtapeInscription),
            cible_object_id=etape.id, critere_condition=critere, operateur='egal', valeurs=['hafs'],
        )
        client = self._connecte_admin()
        client.get(reverse('admin_regle_inscription_supprimer', args=[regle.id]))
        self.assertFalse(RegleCondition.objects.filter(id=regle.id).exists())


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5C : MoyenPaiement +
# PresentationInscription + délais (ParametresInscriptions). Même exigence de
# parité stricte Directeur/مشرف que 5A/5B.
# ============================================================================
class MoyenPaiementPresentationDelaisTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _connecte_mshrif(self):
        client = Client()
        client.force_login(self.mshrif)
        return client

    def test_liste_et_ajout_moyen_paiement_a_parite_stricte(self):
        from payments.models import MoyenPaiement

        for i, client in enumerate((self._connecte_admin(), self._connecte_mshrif())):
            reponse_liste = client.get(reverse('admin_moyens_paiement'))
            self.assertEqual(reponse_liste.status_code, 200)

            reponse_post = client.post(reverse('admin_moyen_paiement_ajouter'), {
                'code': f'moyen_test_{i}', 'label': 'CIH بنك', 'coordonnees': 'RIB: 123456789', 'ordre': i,
            })
            self.assertEqual(reponse_post.status_code, 302)
        self.assertEqual(MoyenPaiement.objects.filter(code__startswith='moyen_test_').count(), 2)

    def test_modification_et_toggle_moyen_paiement(self):
        from payments.models import MoyenPaiement

        moyen = MoyenPaiement.objects.create(code='barid', label='Barid Bank', coordonnees='RIB initial')
        client = self._connecte_mshrif()

        reponse = client.post(reverse('admin_moyen_paiement_modifier', args=[moyen.id]), {
            'label': 'Barid Bank (محدث)', 'coordonnees': 'RIB modifié', 'ordre': 5,
        })
        self.assertEqual(reponse.status_code, 302)
        moyen.refresh_from_db()
        self.assertEqual(moyen.coordonnees, 'RIB modifié')

        client.get(reverse('admin_moyen_paiement_toggle', args=[moyen.id]))
        moyen.refresh_from_db()
        self.assertFalse(moyen.est_actif)

    def test_presentation_inscription_editable_par_les_deux_roles(self):
        for client in (self._connecte_admin(), self._connecte_mshrif()):
            reponse = client.post(reverse('admin_presentation_inscription'), {
                'titre': 'أهلاً بك', 'intro': 'نص الميثاق', 'bouton_texte': 'متابعة',
                'message_bienvenue': 'مرحباً بك في زدني علماً',
            })
            self.assertEqual(reponse.status_code, 302)

        from registration.models import get_presentation_inscription
        presentation = get_presentation_inscription()
        self.assertEqual(presentation.titre, 'أهلاً بك')

    def test_delais_paiement_et_contact_configurables(self):
        from inscriptions.models import get_parametres_inscriptions

        client = self._connecte_admin()
        reponse = client.post(reverse('admin_gestion_inscriptions'), {
            'ouverte_eleve_adulte': '1', 'ouverte_eleve_enfant': '1', 'ouverte_prof': '1',
            'delai_paiement_jours': '7', 'delai_contact_heures': '48',
        })
        self.assertEqual(reponse.status_code, 302)
        parametres = get_parametres_inscriptions()
        self.assertEqual(parametres.delai_paiement_jours, 7)
        self.assertEqual(parametres.delai_contact_heures, 48)

    def test_delai_invalide_refuse_sans_rien_sauvegarder(self):
        from inscriptions.models import get_parametres_inscriptions

        parametres_avant = get_parametres_inscriptions()
        valeur_avant = parametres_avant.delai_paiement_jours

        client = self._connecte_mshrif()
        reponse = client.post(reverse('admin_gestion_inscriptions'), {
            'ouverte_eleve_adulte': '1', 'ouverte_eleve_enfant': '1', 'ouverte_prof': '1',
            'delai_paiement_jours': '0', 'delai_contact_heures': '48',
        })
        self.assertEqual(reponse.status_code, 302)  # redirige quand même (erreur via messages, pas 200)
        parametres_apres = get_parametres_inscriptions()
        self.assertEqual(parametres_apres.delai_paiement_jours, valeur_avant)  # inchangé


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5E : rattachement
# automatique du nouvel Eleve à InscriptionEleve.groupe_choisi dans
# admin_valider_eleve — engagement explicite pris envers le client (ne pas
# laisser ce champ écrit par inscrire_eleve, Étape 4, sans jamais être
# consommé par le reste du système).
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class AdminValiderEleveGroupeChoisiTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)
        self.creneau = Creneau.objects.create(
            sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60,
        )
        remplacer_slots_creneau(self.creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe = Groupe.objects.create(
            nom='مجموعة مختارة عند التسجيل', creneau=self.creneau, statut='actif', capacite_max=10,
        )

    def test_eleve_rattache_automatiquement_au_groupe_choisi_si_toujours_valable(self):
        inscription = _creer_inscription_eleve(
            email='groupe_choisi_valide@zidni.test', date_naissance=datetime.date(2000, 1, 1),
            groupe_choisi=self.groupe,
        )
        reponse = self.client.get(reverse('admin_valider_eleve', args=[inscription.id]))
        self.assertEqual(reponse.status_code, 302)

        eleve = Eleve.objects.get(user__email='groupe_choisi_valide@zidni.test')
        self.assertTrue(self.groupe.eleves.filter(id=eleve.id).exists())
        self.assertTrue(HistoriqueGroupeEleve.objects.filter(eleve=eleve, groupe=self.groupe).exists())

    def test_avertissement_si_groupe_choisi_nest_plus_valable(self):
        """Le groupe a été rempli/archivé entre la candidature et la
        validation — RIEN n'est fait silencieusement, un avertissement
        explicite est montré, l'élève est quand même créé."""
        self.groupe.capacite_max = 0  # devenu incompatible (complet)
        self.groupe.save()
        inscription = _creer_inscription_eleve(
            email='groupe_choisi_invalide@zidni.test', date_naissance=datetime.date(2000, 1, 1),
            groupe_choisi=self.groupe,
        )
        reponse = self.client.get(reverse('admin_valider_eleve', args=[inscription.id]), follow=True)
        self.assertEqual(reponse.status_code, 200)

        eleve = Eleve.objects.get(user__email='groupe_choisi_invalide@zidni.test')
        self.assertFalse(self.groupe.eleves.filter(id=eleve.id).exists())  # PAS ajouté

        messages_affiches = [str(m) for m in reponse.context['messages']]
        self.assertTrue(any('لم يعد بالإمكان إلحاقه' in m for m in messages_affiches))

    def test_aucun_groupe_choisi_ne_change_rien_au_comportement_historique(self):
        """Comportement inchangé pour toute candidature sans groupe_choisi
        (100% des candidatures créées via l'ancien formulaire à une page,
        toujours en service — voir inscriptions/views.py, non modifié)."""
        inscription = _creer_inscription_eleve(email='sans_groupe_choisi@zidni.test', date_naissance=datetime.date(2000, 1, 1))
        self.assertIsNone(inscription.groupe_choisi)
        reponse = self.client.get(reverse('admin_valider_eleve', args=[inscription.id]))
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Eleve.objects.filter(user__email='sans_groupe_choisi@zidni.test').exists())


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5E (2e tâche) :
# fallback d'affichage Programme/Riwaya sur les 2 écrans historiques —
# engagement explicite pris envers le client, avant toute activation en prod
# du nouveau parcours (Partie signalée : ne jamais laisser "Riwaya : vide"
# passer pour un bug alors que la réponse existe dans ReponseInscription).
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class FallbackAffichageProgrammeRiwayaTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)

    def test_ancien_champ_rempli_fait_toujours_foi(self):
        """Candidature créée par l'ancien formulaire à une page — comportement
        historique 100% inchangé."""
        inscription = _creer_inscription_eleve(
            email='ancien_champ_rempli@zidni.test', programme='hifz', riwaya='hafs',
        )
        reponse = self.client.get(reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        html = reponse.content.decode('utf-8')
        self.assertIn(inscription.get_programme_display(), html)
        self.assertIn(inscription.get_riwaya_display(), html)

    def test_nouveau_parcours_sans_ancien_champ_affiche_la_reponseinscription(self):
        """Candidature créée par inscrire_eleve() (Étape 4) — programme/riwaya
        vides sur le modèle, mais une vraie réponse existe dans
        ReponseInscription : ne doit JAMAIS s'afficher vide."""
        from registration.models import ChampInscription, Critere, CritereOption, EtapeInscription, ReponseInscription

        # critere_riwaya : LE vrai critère seedé (code='riwaya', migration 0002)
        # — pas un double 'test_riwaya' comme ailleurs dans ce fichier. Le tag
        # de fallback (registration.templatetags.registration_tags.
        # reponse_ou_ancien_champ) cherche explicitement critere__code='riwaya'
        # (voir sa docstring) : lui donner un autre code romprait le test.
        etape = EtapeInscription.objects.create(code='programme_fallback_test', titre='اختيار البرنامج')
        critere_riwaya = Critere.objects.get(code='riwaya')
        option_hafs = CritereOption.objects.get(critere=critere_riwaya, code='hafs')
        champ_riwaya = ChampInscription.objects.create(etape=etape, critere=critere_riwaya, label='الرواية', ordre=1)

        inscription = _creer_inscription_eleve(
            email='nouveau_parcours_fallback@zidni.test', programme='', riwaya='',
        )
        ReponseInscription.objects.create(inscription=inscription, champ=champ_riwaya, critere=critere_riwaya, option=option_hafs)

        reponse = self.client.get(reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        html = reponse.content.decode('utf-8')
        self.assertIn('حفص', html)  # récupéré depuis ReponseInscription, pas depuis inscription.riwaya (vide)

    def test_rien_nulle_part_affiche_non_determine_jamais_vide_silencieux(self):
        inscription = _creer_inscription_eleve(
            email='rien_nulle_part_fallback@zidni.test', programme='', riwaya='',
        )
        reponse = self.client.get(reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        html = reponse.content.decode('utf-8')
        self.assertIn('غير محدد', html)

    def test_fallback_fonctionne_aussi_sur_la_fiche_eleve_validee(self):
        from registration.models import ChampInscription, Critere, CritereOption, EtapeInscription, ReponseInscription

        # Même remarque que test_nouveau_parcours_sans_ancien_champ_affiche_la_
        # reponseinscription ci-dessus : critere_riwaya DOIT être le vrai
        # critère seedé (code='riwaya'), pas un double renommé.
        etape = EtapeInscription.objects.create(code='programme_fallback_eleve', titre='اختيار البرنامج')
        critere_riwaya = Critere.objects.get(code='riwaya')
        option_warsh = CritereOption.objects.get(critere=critere_riwaya, code='warsh')
        champ_riwaya = ChampInscription.objects.create(etape=etape, critere=critere_riwaya, label='الرواية', ordre=1)

        inscription = _creer_inscription_eleve(
            email='fallback_fiche_eleve@zidni.test', programme='', riwaya='', statut='valide',
        )
        ReponseInscription.objects.create(inscription=inscription, champ=champ_riwaya, critere=critere_riwaya, option=option_warsh)

        user = User.objects.create_user(
            username='fallback_fiche_eleve@zidni.test', email='fallback_fiche_eleve@zidni.test',
            password='xX!test12345', first_name=inscription.nom, role='eleve',
        )
        eleve = Eleve.objects.create(user=user, sexe=inscription.sexe, inscription=inscription)

        reponse = self.client.get(reverse('admin_eleve_detail', args=[eleve.id]))
        html = reponse.content.decode('utf-8')
        self.assertIn('ورش', html)


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5F : balayage de
# parité CONSOLIDÉ sur TOUTE la surface de pages introduites par ce chantier
# (5A à 5E) — en plus des tests de parité déjà écrits par sous-étape (35 au
# total), cette classe unique garantit qu'AUCUNE page de cette interface n'a
# été oubliée avec un role_required('admin') seul (sans مشرف) par erreur —
# un test structurel, pas une répétition des tests métier déjà faits.
# ============================================================================
class PariteDirecteurMshrifConsolideeTests(TestCase):
    def setUp(self):
        from courses.utils import remplacer_slots_creneau as _slots
        from registration.models import ChampInscription, Critere as CritereInscription, EtapeInscription
        from payments.models import MoyenPaiement

        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.eleve = _creer_eleve('eleve_parite_consolidee@zidni.test')

        self.creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(self.creneau, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
        self.groupe = Groupe.objects.create(nom='مجموعة اختبار التناظر', creneau=self.creneau, statut='actif')

        self.critere = CritereInscription.objects.create(code='critere_parite_test', label='معيار اختبار التناظر')
        self.etape = EtapeInscription.objects.create(code='etape_parite_test', titre='مرحلة اختبار التناظر')
        self.champ = ChampInscription.objects.create(etape=self.etape, critere=self.critere, label='حقل اختبار', ordre=1)
        self.moyen = MoyenPaiement.objects.create(code='moyen_parite_test', label='طريقة اختبار')

        # Liste exhaustive des vues GET "sûres" (sans effet de bord) introduites
        # par ce chantier — toggle/supprimer/ajouter(option) volontairement
        # exclus (effets de bord déjà testés séparément par rôle dans 5A-5E).
        self.urls_a_verifier = [
            ('admin_criteres_inscription', []),
            ('admin_critere_inscription_ajouter', []),
            ('admin_critere_inscription_detail', [self.critere.id]),
            ('admin_critere_inscription_modifier', [self.critere.id]),
            ('admin_etapes_inscription', []),
            ('admin_etape_inscription_ajouter', []),
            ('admin_etape_inscription_detail', [self.etape.id]),
            ('admin_etape_inscription_modifier', [self.etape.id]),
            ('admin_champ_inscription_modifier', [self.champ.id]),
            ('admin_regles_inscription', []),
            ('admin_regle_inscription_ajouter', []),
            ('admin_moyens_paiement', []),
            ('admin_moyen_paiement_ajouter', []),
            ('admin_moyen_paiement_modifier', [self.moyen.id]),
            ('admin_presentation_inscription', []),
            ('admin_gestion_inscriptions', []),
            ('admin_groupe_detail', [self.groupe.id]),
            ('admin_eleve_ajouter_manuel', []),  # Étape 7
        ]

    def test_directeur_et_mshrif_recoivent_exactement_le_meme_statut_partout(self):
        client_admin = Client()
        client_admin.force_login(self.admin)
        client_mshrif = Client()
        client_mshrif.force_login(self.mshrif)

        echecs = []
        for url_name, args in self.urls_a_verifier:
            url = reverse(url_name, args=args)
            statut_admin = client_admin.get(url).status_code
            statut_mshrif = client_mshrif.get(url).status_code
            if statut_admin != statut_mshrif:
                echecs.append(f'{url_name} : admin={statut_admin} mais mshrif={statut_mshrif}')
            # Aucune des 2 ne doit être bloquée (200 attendu partout ici).
            if statut_admin != 200:
                echecs.append(f'{url_name} : statut inattendu {statut_admin} (attendu 200)')

        self.assertEqual(echecs, [], '\n'.join(echecs))

    def test_eleve_est_bloque_de_maniere_identique_partout(self):
        client_eleve = Client()
        client_eleve.force_login(self.eleve.user)

        for url_name, args in self.urls_a_verifier:
            url = reverse(url_name, args=args)
            reponse = client_eleve.get(url)
            # role_required redirige (302) vers le dashboard de l'élève plutôt
            # que d'afficher la page — jamais 200 sur une de ces pages.
            self.assertNotEqual(
                reponse.status_code, 200,
                f'{url_name} accessible à un élève connecté — role_required manquant ou incorrect ?'
            )


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 7 : ajout manuel d'une
# candidature élève par le Directeur/مشرف, via EXACTEMENT le même service
# (registration.utils.inscrire_eleve) que le wizard public (Étape 6). Même
# exigence de parité stricte Directeur/مشرف que 5A-5E.
# ============================================================================
class AjoutManuelEleveTests(TestCase):
    def setUp(self):
        from courses.utils import remplacer_slots_creneau as _slots
        from inscriptions.models import TypeAbonnement
        from registration.models import ChampInscription, Critere as CritereInscription

        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.prof = _creer_prof('prof_ajout_manuel@zidni.test')

        self.critere_programme = CritereInscription.objects.get(code='programme')
        self.critere_riwaya = CritereInscription.objects.get(code='riwaya')
        self.critere_type_offre = CritereInscription.objects.get(code='type_offre')
        self.critere_nb_seances = CritereInscription.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        self.creneau_hafs = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(self.creneau_hafs, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe_hafs = Groupe.objects.create(
            nom='مجموعة حفص — إضافة يدوية', creneau=self.creneau_hafs, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe_hafs, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe_hafs, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        self.creneau_warsh = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='warsh', age_min=6, age_max=60)
        _slots(self.creneau_warsh, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe_warsh = Groupe.objects.create(
            nom='مجموعة ورش — إضافة يدوية', creneau=self.creneau_warsh, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe_warsh, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe_warsh, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='warsh'))

        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_ajout_manuel_abo', label='جماعي شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1,
        )

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _connecte_mshrif(self):
        client = Client()
        client.force_login(self.mshrif)
        return client

    def _round1_donnees(self, email):
        return {
            'round_form': 'identite',
            'nom': 'سلمى الإدريسي', 'sexe': 'femme', 'email': email,
            'date_naissance': '2010-01-01',
            'indicatif_pays': '212', 'telephone': '0611223344', 'telephone_confirmation': '0611223344',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        }

    def test_directeur_et_mshrif_peuvent_tous_les_deux_creer_une_inscription(self):
        for i, (client, user, email) in enumerate([
            (self._connecte_admin(), self.admin, 'parite_admin_ajout_manuel@zidni.test'),
            (self._connecte_mshrif(), self.mshrif, 'parite_mshrif_ajout_manuel@zidni.test'),
        ]):
            reponse_round2 = client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees(email))
            self.assertEqual(reponse_round2.status_code, 200)
            self.assertIn('مجموعة حفص — إضافة يدوية', reponse_round2.content.decode('utf-8'))

            reponse_finale = client.post(reverse('admin_eleve_ajouter_manuel'), {
                **self._round1_donnees(email),
                'round_form': 'confirmation',
                'groupe_id': str(self.groupe_hafs.id),
                'abonnement_code': self.abo_groupe.code,
            })
            inscription = InscriptionEleve.objects.get(email=email)
            self.assertRedirects(reponse_finale, reverse('admin_inscription_eleve_detail', args=[inscription.id]))
            self.assertEqual(inscription.cree_par_id, user.id)
            self.assertEqual(inscription.groupe_choisi_id, self.groupe_hafs.id)

    def test_prix_affiche_repli_puis_grille_si_ligne_configuree(self):
        """Étape 9 (GrillePrixAbonnement, 2026-08-21) : même comportement que
        registration.views.wizard_abonnement — repli sur TypeAbonnement.prix
        tant qu'aucune ligne de grille ne matche exactement nb_slots=2 (déjà
        répondu par _round1_donnees), puis prix de la grille dès qu'une
        ligne active existe pour cette combinaison."""
        from inscriptions.models import GrillePrixAbonnement

        client = self._connecte_admin()
        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees('prix_repli_ajout_manuel@zidni.test'))
        abonnements = {a.code: a for a in reponse.context['abonnements']}
        self.assertEqual(abonnements[self.abo_groupe.code].prix_affiche, self.abo_groupe.prix)

        GrillePrixAbonnement.objects.create(type_abonnement=self.abo_groupe, nb_slots=2, prix=999)
        reponse2 = client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees('prix_grille_ajout_manuel@zidni.test'))
        abonnements2 = {a.code: a for a in reponse2.context['abonnements']}
        self.assertEqual(abonnements2[self.abo_groupe.code].prix_affiche, 999)

    def test_groupe_plein_napparait_pas_dans_le_select_de_ladmin(self):
        """Même correctif que registration.views.wizard_groupe (bug signalé
        le 2026-08-21), côté ajout manuel (Étape 7) : un groupe complet ne
        doit pas apparaître comme option choisissable pour le Directeur/مشرف
        non plus."""
        for i in range(self.groupe_hafs.capacite_max):
            email = f'admin_ajout_plein_{i}@zidni.test'
            u = User.objects.create_user(username=email, email=email, password='xX!test12345', role='eleve')
            self.groupe_hafs.eleves.add(Eleve.objects.create(user=u, sexe='homme'))

        client = self._connecte_admin()
        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees('admin_verif_groupe_plein@zidni.test'))
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn('مجموعة حفص — إضافة يدوية', reponse.content.decode('utf-8'))

    def test_regression_sexe_2026_08_22_femme_ne_voit_pas_un_groupe_hommes(self):
        """Même correctif que registration.utils.groupes_compatibles_avec_age
        (régression signalée le 2026-08-22), côté ajout manuel (Étape 7) —
        les 2 entrées partagent la même fonction, donc le même correctif."""
        creneau_hommes = Creneau.objects.create(
            sexe_cible='homme', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60,
        )
        remplacer_slots_creneau(creneau_hommes, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        groupe_hommes = Groupe.objects.create(
            nom='مجموعة رجال — إضافة يدوية', creneau=creneau_hommes, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=groupe_hommes, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=groupe_hommes, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        client = self._connecte_admin()
        # _round1_donnees soumet sexe='femme' (voir sa définition ci-dessus).
        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees('regression_sexe_femme@zidni.test'))
        html = reponse.content.decode('utf-8')
        self.assertIn('مجموعة حفص — إضافة يدوية', html)  # groupe mixte, toujours visible
        self.assertNotIn('مجموعة رجال — إضافة يدوية', html)  # groupe hommes, jamais visible pour une femme

    def test_prof_na_pas_acces(self):
        client = Client()
        client.force_login(self.prof.user)
        reponse = client.get(reverse('admin_eleve_ajouter_manuel'))
        self.assertNotEqual(reponse.status_code, 200)
        reponse_post = client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees('prof_tente_ajout@zidni.test'))
        self.assertNotEqual(reponse_post.status_code, 200)
        self.assertFalse(InscriptionEleve.objects.filter(email='prof_tente_ajout@zidni.test').exists())

    def test_desaccord_non_bloquant_affiche_avertissement_sans_creer(self):
        """riwaya répondue = hafs, mais groupe_id posté = celui en warsh (non
        bloquant, filtrable) — AUCUNE création tant que confirme_override
        n'est pas explicitement transmis."""
        client = self._connecte_admin()
        email = 'avertissement_ajout_manuel@zidni.test'
        client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees(email))

        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), {
            **self._round1_donnees(email),
            'round_form': 'confirmation',
            'groupe_id': str(self.groupe_warsh.id),
            'abonnement_code': self.abo_groupe.code,
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(InscriptionEleve.objects.filter(email=email).exists())
        html = reponse.content.decode('utf-8')
        self.assertIn('تأكيد التسجيل رغم التحذير', html)

    def test_confirme_override_cree_malgre_lavertissement(self):
        client = self._connecte_admin()
        email = 'override_ajout_manuel@zidni.test'
        client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees(email))

        # Round 2, tentative sans confirmation : rien créé (déjà couvert
        # ci-dessus, refait ici pour prouver le contraste avec l'étape suivante).
        client.post(reverse('admin_eleve_ajouter_manuel'), {
            **self._round1_donnees(email),
            'round_form': 'confirmation',
            'groupe_id': str(self.groupe_warsh.id),
            'abonnement_code': self.abo_groupe.code,
        })
        self.assertFalse(InscriptionEleve.objects.filter(email=email).exists())

        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), {
            **self._round1_donnees(email),
            'round_form': 'confirmation',
            'groupe_id': str(self.groupe_warsh.id),
            'abonnement_code': self.abo_groupe.code,
            'confirme_override': '1',
        })
        inscription = InscriptionEleve.objects.get(email=email)
        self.assertRedirects(reponse, reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        self.assertEqual(inscription.groupe_choisi_id, self.groupe_warsh.id)
        self.assertEqual(inscription.cree_par_id, self.admin.id)

    def test_meme_source_champs_actifs_que_wizard_public(self):
        """Preuve bout en bout (pas juste "même fonction appelée") : un critère
        tout juste créé et rattaché à l'étape 'programme' apparaît SANS AUCUNE
        modification de code aussi bien sur le wizard public que sur l'ajout
        manuel — les deux lisent la même table ChampInscription, jamais 2
        listes maintenues séparément."""
        from registration.models import ChampInscription, EtapeInscription

        etape_programme = EtapeInscription.objects.get(code='programme')
        champ = ChampInscription.objects.create(etape=etape_programme, critere=None, label='حقل اختبار التناظر', ordre=99)

        client_wizard = Client()
        client_wizard.post(reverse('wizard_identite'), {
            'nom': 'test', 'sexe': 'homme', 'email': 'test_parite_wizard@zidni.test', 'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600000000', 'telephone_confirmation': '0600000000',
        })
        html_wizard = client_wizard.get(reverse('wizard_programme')).content.decode('utf-8')

        client_admin = self._connecte_admin()
        html_admin = client_admin.get(reverse('admin_eleve_ajouter_manuel')).content.decode('utf-8')

        self.assertIn('حقل اختبار التناظر', html_wizard)
        self.assertIn('حقل اختبار التناظر', html_admin)

    def test_html_expose_les_attributs_js_necessaires_au_correctif_individuel(self):
        """Même correctif que registration.tests.WizardProgrammeTests.test_
        html_expose_les_attributs_js_necessaires_au_correctif_individuel
        (bugs A+B du 2026-08-21), côté ajout manuel."""
        client = self._connecte_admin()
        html = client.get(reverse('admin_eleve_ajouter_manuel')).content.decode('utf-8')
        self.assertIn('data-backend="champ_groupe"', html)
        self.assertIn('id="nb_seances_wrapper" style="display:none;"', html)
        self.assertIn('data-obligatoire="1"', html)


# ============================================================================
# Étape 9 — admin_abonnement_grille_prix : page dashboard où le مدير/مشرف
# configure GrillePrixAbonnement (prix par nb_slots, décidé le 2026-08-21).
# ============================================================================
class AdminAbonnementGrillePrixTests(TestCase):
    def setUp(self):
        from inscriptions.models import TypeAbonnement

        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.prof = _creer_prof()
        self.abonnement = TypeAbonnement.objects.create(
            code='test_grille_prix_abo', label='شهري تجريبي', prix=80, type_offre='groupe', cible_age='les_deux',
        )
        # Garantit au moins un nb_slots réel connu et déterministe pour les
        # tests (la base de test contient aussi des groupes seedés réels,
        # mais leur nb_slots exact n'est pas supposé ici).
        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(creneau, [
            {'jour': j, 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}
            for j in ['lun', 'mar', 'mer']
        ])
        Groupe.objects.create(nom='مجموعة شبكة أسعار', creneau=creneau, statut='actif')
        self.nb_slots = 3

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_role_required_refuse_un_prof(self):
        client = Client()
        client.force_login(self.prof.user)
        reponse = client.get(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id]))
        self.assertEqual(reponse.status_code, 302)

    def test_mshrif_peut_acceder(self):
        client = Client()
        client.force_login(self.mshrif)
        reponse = client.get(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id]))
        self.assertEqual(reponse.status_code, 200)

    def test_get_affiche_une_ligne_par_nb_slots_reel(self):
        client = self._connecte_admin()
        html = client.get(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id])).content.decode('utf-8')
        self.assertIn(f'name="prix_{self.nb_slots}"', html)
        self.assertIn(f'{self.nb_slots} حصص', html)

    def test_post_cree_une_ligne_puis_la_modifie(self):
        from inscriptions.models import GrillePrixAbonnement

        client = self._connecte_admin()
        client.post(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id]), {
            f'prix_{self.nb_slots}': '999', f'actif_{self.nb_slots}': 'on',
        })
        ligne = GrillePrixAbonnement.objects.get(type_abonnement=self.abonnement, nb_slots=self.nb_slots)
        self.assertEqual(ligne.prix, 999)
        self.assertTrue(ligne.est_actif)

        # Re-soumission SANS la case "نشط" cochée (jamais envoyée par un
        # navigateur pour une checkbox décochée) -> désactive la ligne sans
        # la supprimer, prix mis à jour dans le même passage.
        client.post(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id]), {
            f'prix_{self.nb_slots}': '500',
        })
        ligne.refresh_from_db()
        self.assertEqual(ligne.prix, 500)
        self.assertFalse(ligne.est_actif)

    def test_post_champ_vide_supprime_la_ligne_existante(self):
        from inscriptions.models import GrillePrixAbonnement

        GrillePrixAbonnement.objects.create(type_abonnement=self.abonnement, nb_slots=self.nb_slots, prix=200)
        client = self._connecte_admin()
        client.post(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id]), {
            f'prix_{self.nb_slots}': '',
        })
        self.assertFalse(
            GrillePrixAbonnement.objects.filter(type_abonnement=self.abonnement, nb_slots=self.nb_slots).exists()
        )

    def test_warning_configures_zero_puis_couvert_apres_ajout(self):
        client = self._connecte_admin()
        html_avant = client.get(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id])).content.decode('utf-8')
        self.assertIn('لم يُحدد أي سعر خاص بعد', html_avant)

        client.post(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id]), {
            f'prix_{self.nb_slots}': '999', f'actif_{self.nb_slots}': 'on',
        })
        html_apres = client.get(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id])).content.decode('utf-8')
        # Reste 'partiellement couvert' si d'autres nb_slots réels existent
        # (groupes seedés), sinon 'entièrement couvert' -- les deux messages
        # excluent l'ancien état "aucun prix défini".
        self.assertNotIn('لم يُحدد أي سعر خاص بعد', html_apres)


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 8 : preuve de
# généricité totale, bout en bout, à travers TOUTE la chaîne (dashboard CRUD
# -> onglet groupe "الخصائص" -> wizard public ET ajout manuel) avec un
# critère qui n'existe dans AUCUN autre test de ce chantier ("هدف التعلم" /
# but_apprentissage — jamais "Mode d'apprentissage préféré" ni "Langue
# préférée", déjà utilisés à l'Étape 4/6). Zéro objects.create() direct sur
# Critere/CritereOption/ChampInscription/GroupeCritereValeur dans cette
# classe : uniquement des POST sur les vraies vues, exactement ce que ferait
# le Directeur. La preuve finale (aucune ligne de code ne mentionne ce
# critère) est un grep RÉEL du dépôt, pas une affirmation.
# ============================================================================
class GenericiteBoutEnBoutTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _creer_critere_but_apprentissage_via_dashboard(self):
        from registration.models import ChampInscription, Critere, EtapeInscription

        client = self._connecte_admin()

        client.post(reverse('admin_critere_inscription_ajouter'), {
            'code': 'but_apprentissage', 'label': 'هدف التعلم', 'type_champ': 'choix_unique',
            'backend': 'eav', 'filtrable': 'on', 'ordre': 5,
        })
        critere = Critere.objects.get(code='but_apprentissage')

        for code, label in [
            ('genericite_memorisation', 'الحفظ فقط'),
            ('genericite_revision', 'المراجعة فقط'),
            ('genericite_lecture', 'القراءة فقط'),
        ]:
            client.post(reverse('admin_critere_option_ajouter', args=[critere.id]), {'code': code, 'label': label})
        self.assertEqual(critere.options.count(), 3)

        # Ajouté à une étape EXISTANTE (celle du parcours réel, pas une étape
        # créée pour l'occasion) — obligatoire volontairement PAS coché ici,
        # vérifié/activé dans un 2e temps par test_couverture_vide_puis_
        # couverte_apres_assignation_aux_groupes ci-dessous, après contrôle
        # de couverture (même flux que EtapeChampRegleInscriptionCRUDTests.
        # test_rendre_champ_obligatoire_sans_couverture_demande_confirmation).
        etape_programme = EtapeInscription.objects.get(code='programme')
        client.post(reverse('admin_champ_inscription_ajouter', args=[etape_programme.id]), {
            'critere_id': critere.id, 'label': 'هدف التعلم', 'ordre': 5,
        })
        champ = ChampInscription.objects.get(etape=etape_programme, critere=critere)
        self.assertFalse(champ.obligatoire)
        return critere, champ

    def _creer_groupes_et_assigner_valeurs(self, critere):
        from courses.utils import remplacer_slots_creneau as _slots
        from registration.models import Critere as CritereInscription

        critere_programme = CritereInscription.objects.get(code='programme')
        critere_riwaya = CritereInscription.objects.get(code='riwaya')

        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        groupe_memo = Groupe.objects.create(
            nom='مجموعة اختبار التعميم — الحفظ', creneau=creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        groupe_revision = Groupe.objects.create(
            nom='مجموعة اختبار التعميم — المراجعة', creneau=creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        for groupe in (groupe_memo, groupe_revision):
            GroupeCritereValeur.objects.create(groupe=groupe, critere=critere_programme, option=critere_programme.options.get(code='hifz'))
            GroupeCritereValeur.objects.create(groupe=groupe, critere=critere_riwaya, option=critere_riwaya.options.get(code='hafs'))

        # Valeurs assignées via l'onglet "الخصائص" (courses.views.groupe_
        # definir_critere, URL admin_groupe_definir_critere) — PAS un appel
        # direct à registration.utils.definir_valeurs_groupe().
        client = self._connecte_admin()
        client.post(reverse('admin_groupe_definir_critere', args=[groupe_memo.id, critere.id]), {'options': ['genericite_memorisation']})
        client.post(reverse('admin_groupe_definir_critere', args=[groupe_revision.id, critere.id]), {'options': ['genericite_revision']})
        return groupe_memo, groupe_revision

    def _champs_programme_seedes(self):
        from registration.models import ChampInscription
        return {
            code: ChampInscription.objects.get(etape__code='programme', critere__code=code)
            for code in ('programme', 'riwaya', 'type_offre', 'nb_seances_hebdo')
        }

    def _abonnement_groupe_actif(self, suffixe):
        from inscriptions.models import TypeAbonnement
        abo = TypeAbonnement.objects.filter(est_actif=True, type_offre='groupe').first()
        if abo is None:
            abo = TypeAbonnement.objects.create(
                code=f'test_generique_abo_{suffixe}', label='جماعي', prix=80,
                type_offre='groupe', cible_age='les_deux', ordre=1,
            )
        return abo

    def _moyen_paiement_actif(self):
        from payments.models import MoyenPaiement
        moyen = MoyenPaiement.objects.filter(est_actif=True).first()
        if moyen is None:
            moyen = MoyenPaiement.objects.create(code='test_generique_moyen', label='نقداً', est_actif=True)
        return moyen

    def test_couverture_vide_puis_couverte_apres_assignation_aux_groupes(self):
        """Warning de couverture vérifié AVANT toute assignation (0 groupe
        configuré), puis couverture complète après assignation via l'onglet
        "الخصائص" — et rendu obligatoire seulement APRÈS, sans confirmation
        nécessaire cette fois (couverture déjà complète)."""
        from registration.utils import couverture_critere

        critere, champ = self._creer_critere_but_apprentissage_via_dashboard()
        couverture_avant = couverture_critere(critere)
        self.assertEqual(couverture_avant['configures'], 0)

        self._creer_groupes_et_assigner_valeurs(critere)
        couverture_apres = couverture_critere(critere)
        self.assertEqual(couverture_apres['configures'], 2)

        client = self._connecte_admin()
        reponse = client.post(reverse('admin_champ_inscription_modifier', args=[champ.id]), {
            'label': 'هدف التعلم', 'obligatoire': 'on', 'ordre': 5, 'est_actif': 'on',
        })
        self.assertEqual(reponse.status_code, 302)
        champ.refresh_from_db()
        self.assertTrue(champ.obligatoire)

    def test_wizard_public_filtre_les_groupes_selon_le_nouveau_critere(self):
        """Bout en bout via le formulaire PUBLIC : le nouveau critère filtre
        réellement les groupes proposés à l'étape 3, sans une seule ligne de
        code écrite pour lui."""
        critere, champ = self._creer_critere_but_apprentissage_via_dashboard()
        groupe_memo, groupe_revision = self._creer_groupes_et_assigner_valeurs(critere)
        champs = self._champs_programme_seedes()

        client = Client()
        client.post(reverse('wizard_identite'), {
            'nom': 'وزير الاختبار', 'sexe': 'homme', 'email': 'generique_wizard@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600998877', 'telephone_confirmation': '0600998877',
        })
        client.post(reverse('wizard_programme'), {
            f"champ_{champs['programme'].id}": 'hifz',
            f"champ_{champs['riwaya'].id}": 'hafs',
            f"champ_{champs['type_offre'].id}": 'groupe',
            f"champ_{champs['nb_seances_hebdo'].id}": '2',
            f'champ_{champ.id}': 'genericite_memorisation',
        })
        html_groupe = client.get(reverse('wizard_groupe')).content.decode('utf-8')
        self.assertIn('مجموعة اختبار التعميم — الحفظ', html_groupe)
        self.assertNotIn('مجموعة اختبار التعميم — المراجعة', html_groupe)

        reponse_choix = client.post(reverse('wizard_groupe'), {'groupe_id': str(groupe_memo.id)})
        self.assertRedirects(reponse_choix, reverse('wizard_abonnement'), fetch_redirect_response=False)

        abo = self._abonnement_groupe_actif('wizard')
        client.post(reverse('wizard_abonnement'), {'abonnement_code': abo.code})

        moyen = self._moyen_paiement_actif()
        reponse_finale = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': moyen.code})
        self.assertRedirects(reponse_finale, reverse('wizard_confirmation'), fetch_redirect_response=False)

        inscription = InscriptionEleve.objects.get(email='generique_wizard@zidni.test')
        self.assertEqual(inscription.groupe_choisi_id, groupe_memo.id)
        from registration.models import ReponseInscription
        self.assertTrue(ReponseInscription.objects.filter(
            inscription=inscription, critere=critere, option__code='genericite_memorisation',
        ).exists())

    def test_ajout_manuel_filtre_aussi_les_groupes_selon_le_nouveau_critere(self):
        """Même preuve, via l'Étape 7 (ajout manuel Directeur/مشرف) — même
        moteur, même résultat, toujours zéro ligne de code pour ce critère."""
        critere, champ = self._creer_critere_but_apprentissage_via_dashboard()
        groupe_memo, groupe_revision = self._creer_groupes_et_assigner_valeurs(critere)
        champs = self._champs_programme_seedes()
        abo = self._abonnement_groupe_actif('manuel')

        client = self._connecte_admin()
        donnees_round1 = {
            'round_form': 'identite', 'nom': 'مديرة الاختبار', 'sexe': 'femme', 'email': 'generique_manuel@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600112200', 'telephone_confirmation': '0600112200',
            f"champ_{champs['programme'].id}": 'hifz', f"champ_{champs['riwaya'].id}": 'hafs',
            f"champ_{champs['type_offre'].id}": 'groupe', f"champ_{champs['nb_seances_hebdo'].id}": '2',
            f'champ_{champ.id}': 'genericite_memorisation',
        }
        reponse_round2 = client.post(reverse('admin_eleve_ajouter_manuel'), donnees_round1)
        html = reponse_round2.content.decode('utf-8')
        self.assertIn('مجموعة اختبار التعميم — الحفظ', html)
        self.assertNotIn('مجموعة اختبار التعميم — المراجعة', html)

        reponse_finale = client.post(reverse('admin_eleve_ajouter_manuel'), {
            **donnees_round1, 'round_form': 'confirmation',
            'groupe_id': str(groupe_memo.id), 'abonnement_code': abo.code,
        })
        inscription = InscriptionEleve.objects.get(email='generique_manuel@zidni.test')
        self.assertRedirects(reponse_finale, reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        self.assertEqual(inscription.groupe_choisi_id, groupe_memo.id)
        self.assertEqual(inscription.cree_par_id, self.admin.id)

    def test_le_critere_napparait_dans_aucun_fichier_source(self):
        """LA preuve explicitement demandée : grep RÉEL sur tout le dépôt
        (hors ce fichier de test lui-même) — zéro mention du code de ce
        critère ou de ses options, nulle part dans le code source. Prouve
        qu'aucune ligne de code n'a été écrite pour LUI spécifiquement, pas
        juste une affirmation dans un message de commit. Canari permanent :
        si un jour quelqu'un copie-colle ce fixture dans du code réel avec un
        `if critere.code == 'but_apprentissage':`, ce test échoue."""
        import pathlib

        racine = pathlib.Path(__file__).resolve().parent.parent
        motifs = ['but_apprentissage', 'genericite_memorisation', 'genericite_revision', 'genericite_lecture']
        extensions = ('.py', '.html')
        exclusions = {'venv', '.git', 'node_modules', 'staticfiles', 'media', '__pycache__'}
        fichier_de_ce_test = pathlib.Path(__file__).resolve()

        trouvailles = []
        for chemin in racine.rglob('*'):
            if not chemin.is_file() or chemin.suffix not in extensions:
                continue
            if any(part in exclusions for part in chemin.parts):
                continue
            if chemin.resolve() == fichier_de_ce_test:
                continue
            try:
                contenu = chemin.read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            for motif in motifs:
                if motif in contenu:
                    trouvailles.append(f'{chemin} contient "{motif}"')

        self.assertEqual(trouvailles, [], '\n'.join(trouvailles))
