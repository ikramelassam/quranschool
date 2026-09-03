import datetime
import time

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import (
    User, Eleve, Prof, Superviseur, DocumentEleve, ElementHakiba, DerniereVisiteNotification,
)
from courses.models import (
    Groupe, Creneau, Seance, Presence, BilanMensuel, HistoriqueGroupeEleve,
    DisponibiliteEleve, DisponibiliteProf, DemandeModificationDisponibilite, DemandeChangementHalaka,
    CritereEleve, NotePresence,
)
from courses.utils import remplacer_slots_creneau
from courses.views import _ajouter_eleve_au_groupe
from registration.models import (
    ChampInscription, ConfigurationChampStructurel, Critere as CritereInscription, CritereOption,
    EtapeInscription, GroupeCritereValeur,
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


def _creer_document_cartable(eleve, **kwargs):
    """Équivalent, pour les tests, de l'ancien DocumentEleve.objects.create(
    eleve=...) — refonte du 2026-08-30 : DocumentEleve cible désormais un ou
    plusieurs élèves via cible_type + eleves_cibles (M2M), plus une simple FK
    (voir accounts.models.DocumentEleve.__doc__). Crée un document en mode
    'specifique' ciblant UN SEUL élève, comportement équivalent à l'ancien FK
    pour les tests qui n'ont pas besoin de tester les modes 'tous'/'categorie'
    eux-mêmes."""
    doc = DocumentEleve.objects.create(cible_type=DocumentEleve.CIBLE_SPECIFIQUE, **kwargs)
    doc.eleves_cibles.add(eleve)
    return doc


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


class EleveArchiverPermissionsTests(TestCase):
    """Tâche du 2026-09-02 : أرشفة + إعادة تفعيل d'un élève ouvertes au مشرف
    en plus du مدير. L'arrêt (admin_eleve_suspendre) reste مدير seul, et un
    rôle sans droit (prof) ne peut toujours rien changer."""

    def test_mshrif_peut_archiver_un_eleve(self):
        self.client.force_login(_creer_mshrif())
        eleve = _creer_eleve()
        response = self.client.get(reverse('admin_eleve_archiver', args=[eleve.id]))
        self.assertRedirects(response, reverse('admin_eleve_detail', args=[eleve.id]))
        eleve.refresh_from_db()
        self.assertEqual(eleve.statut, 'archive')

    def test_mshrif_peut_reactiver_un_eleve_archive(self):
        self.client.force_login(_creer_mshrif())
        eleve = _creer_eleve()
        eleve.statut = 'archive'
        eleve.save(update_fields=['statut'])
        response = self.client.get(reverse('admin_eleve_reactiver', args=[eleve.id]))
        self.assertRedirects(response, reverse('admin_eleve_detail', args=[eleve.id]))
        eleve.refresh_from_db()
        self.assertEqual(eleve.statut, 'actif')

    def test_mshrif_ne_peut_toujours_pas_suspendre(self):
        self.client.force_login(_creer_mshrif())
        eleve = _creer_eleve()
        self.client.get(reverse('admin_eleve_suspendre', args=[eleve.id]))
        eleve.refresh_from_db()
        self.assertEqual(eleve.statut, 'actif')

    def test_prof_ne_peut_pas_archiver(self):
        self.client.force_login(_creer_prof().user)
        eleve = _creer_eleve()
        self.client.get(reverse('admin_eleve_archiver', args=[eleve.id]))
        eleve.refresh_from_db()
        self.assertEqual(eleve.statut, 'actif')

    def test_bouton_archiver_visible_pour_mshrif_sur_la_fiche(self):
        self.client.force_login(_creer_mshrif())
        eleve = _creer_eleve()
        html = self.client.get(reverse('admin_eleve_detail', args=[eleve.id])).content.decode('utf-8')
        self.assertIn(reverse('admin_eleve_archiver', args=[eleve.id]), html)
        # L'arrêt (إيقاف) reste réservé au مدير — absent pour le مشرف.
        self.assertNotIn(reverse('admin_eleve_suspendre', args=[eleve.id]), html)


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
class BilansMensuelsPerfRefactorTests(TestCase):
    """Correctif perf du 2026-08-30 (voir AUDIT_PERFORMANCE_2026-08-30.md,
    point 2.4) : moyennes/bilan de dashboard.views.bilans_mensuels sont
    passés de 2 requêtes PAR ÉLÈVE affiché à 2 requêtes groupées, indexées
    par (eleve_id, groupe_id)/(eleve_id, prof_id). Ces tests vérifient
    précisément le cas qui rendait ce refactor délicat : un même élève dans
    2 groupes (donc 2 profs différents) doit continuer à afficher des
    moyennes/bilans DIFFÉRENTS sur chacune de ses 2 lignes — jamais l'un
    écrasant l'autre par erreur de clé de regroupement."""

    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)
        self.critere = CritereEleve.objects.create(nom_ar='الحفظ', ordre=1, est_actif=True)

    def test_meme_eleve_dans_2_groupes_affiche_moyenne_et_bilan_distincts_par_groupe(self):
        eleve = _creer_eleve('eleve_bilans_perf@zidni.test')
        prof_a = _creer_prof('prof_bilans_perf_a@zidni.test')
        prof_b = _creer_prof('prof_bilans_perf_b@zidni.test')
        groupe_a = Groupe.objects.create(nom='مجموعة أ', prof=prof_a)
        groupe_b = Groupe.objects.create(nom='مجموعة ب', prof=prof_b)
        groupe_a.eleves.add(eleve)
        groupe_b.eleves.add(eleve)

        seance_a = Seance.objects.create(groupe=groupe_a, date=datetime.date(2026, 8, 5), heure='14:00', type='normal')
        presence_a = Presence.objects.create(seance=seance_a, eleve=eleve, statut='present')
        NotePresence.objects.create(presence=presence_a, critere=self.critere, note=10)

        seance_b = Seance.objects.create(groupe=groupe_b, date=datetime.date(2026, 8, 6), heure='16:00', type='normal')
        presence_b = Presence.objects.create(seance=seance_b, eleve=eleve, statut='present')
        NotePresence.objects.create(presence=presence_b, critere=self.critere, note=18)

        BilanMensuel.objects.create(
            eleve=eleve, prof=prof_a, mois_reference=datetime.date(2026, 8, 1),
            memorisation='بيان المجموعة أ',
        )
        BilanMensuel.objects.create(
            eleve=eleve, prof=prof_b, mois_reference=datetime.date(2026, 8, 1),
            memorisation='بيان المجموعة ب',
        )

        response = self.client.get(reverse('bilans_mensuels'))
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')

        # Chaque groupe doit afficher SA PROPRE moyenne pour ce même élève —
        # jamais la moyenne de l'autre groupe (bug qu'une clé de regroupement
        # par seul eleve_id, sans le groupe_id, aurait introduit).
        # Virgule (pas point) : {{ m.moyenne }} passe par le formatage de
        # nombre localisé de Django, actif par défaut — LANGUAGE_CODE='ar'
        # (la langue par défaut de ce test, aucun ?language= choisi) utilise
        # la virgule comme séparateur décimal, pas le point.
        self.assertIn('الحفظ: 10,0/20', contenu)
        self.assertIn('الحفظ: 18,0/20', contenu)
        # Idem pour le bilan textuel, scopé par prof.
        self.assertIn('بيان المجموعة أ', contenu)
        self.assertIn('بيان المجموعة ب', contenu)

    def test_groupe_sans_prof_affiche_quand_meme_un_bilan_dont_lauteur_a_ete_supprime(self):
        """prof=None sur le bilan (SET_NULL après suppression définitive du
        prof, voir AffichageDonneesDetacheesTests) ET sur le groupe lui-même
        (prof réassigné à None) — cas à part car `prof_id__in=[...]` ne
        matche jamais NULL en SQL, contrairement à l'ancien `prof=groupe.prof`
        (qui devenait `prof_id IS NULL` quand groupe.prof valait None)."""
        eleve = _creer_eleve('eleve_bilans_perf_sansprof@zidni.test')
        groupe = Groupe.objects.create(nom='مجموعة بدون أستاذ', prof=None)
        groupe.eleves.add(eleve)
        BilanMensuel.objects.create(
            eleve=eleve, prof=None, mois_reference=datetime.date(2026, 8, 1),
            memorisation='بيان بدون أستاذ',
        )

        response = self.client.get(reverse('bilans_mensuels'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('بيان بدون أستاذ', response.content.decode('utf-8'))


class CritereEleveLocaliseTests(TestCase):
    """Chantier i18n contenu-DB (2026-08-31) : courses.CritereEleve.nom_ar
    gagne nom_fr/nom_en. Vu par le prof (feuille de présence), l'élève et le
    مؤطر — repli automatique sur l'arabe via nom_localise."""

    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)

    def test_nom_localise_repli(self):
        from django.utils import translation
        c = CritereEleve.objects.create(nom_ar='الحفظ', nom_fr='Mémorisation', ordre=1)
        with translation.override('fr'):
            self.assertEqual(c.nom_localise, 'Mémorisation')
        with translation.override('en'):
            self.assertEqual(c.nom_localise, 'الحفظ')  # repli arabe (nom_en vide)
        with translation.override('ar'):
            self.assertEqual(c.nom_localise, 'الحفظ')

    def test_bilans_mensuels_affiche_le_critere_traduit_en_fr(self):
        critere = CritereEleve.objects.create(
            nom_ar='الحفظ', nom_fr='Mémorisation', nom_en='Memorization', ordre=1, est_actif=True,
        )
        eleve = _creer_eleve('eleve_crit_loc@zidni.test')
        prof = _creer_prof('prof_crit_loc@zidni.test')
        groupe = Groupe.objects.create(nom='مجموعة', prof=prof)
        groupe.eleves.add(eleve)
        seance = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 5), heure='14:00', type='normal')
        presence = Presence.objects.create(seance=seance, eleve=eleve, statut='present')
        NotePresence.objects.create(presence=presence, critere=critere, note=15)

        response = self.client.get(reverse('bilans_mensuels'), HTTP_ACCEPT_LANGUAGE='fr')
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('Mémorisation', contenu)
        self.assertNotIn('الحفظ', contenu)

    def test_admin_enregistre_nom_fr_nom_en(self):
        self.client.post(reverse('admin_critere_eleve_ajouter'), {
            'nom_ar': 'معيار تجريبي للترجمة', 'nom_fr': 'Récitation', 'nom_en': 'Recitation', 'ordre': 3,
        })
        cree = CritereEleve.objects.get(nom_ar='معيار تجريبي للترجمة')
        self.assertEqual(cree.nom_fr, 'Récitation')
        self.assertEqual(cree.nom_en, 'Recitation')


@override_settings(STORAGES=_STORAGES_TEST)
class ExtensionSeancesThrottleTests(TestCase):
    """Correctif perf du 2026-08-30 (voir AUDIT_PERFORMANCE_2026-08-30.md) :
    admin_seances/admin_calendrier appelaient etendre_toutes_les_seances()
    (balayage — 1 à plusieurs requêtes SQL PAR groupe actif) SANS AUCUN
    throttle, à CHAQUE requête — signalé lent par le client précisément en
    appliquant un filtre/une recherche sur /dashboard/admin/seances/ (qui
    recharge entièrement la page, donc rejoue tout depuis le début). Vérifie
    que la version throttlée (courses.utils.
    etendre_toutes_les_seances_opportuniste) n'exécute réellement le balayage
    qu'une seule fois, même après plusieurs requêtes/filtres successifs."""

    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)
        # La clé de throttle vit dans le cache global (LocMemCache en test,
        # comme en dev) — partagé entre tests si on ne la nettoie pas.
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_filtrer_plusieurs_fois_de_suite_n_appelle_le_balayage_qu_une_fois(self):
        from unittest.mock import patch

        with patch('courses.utils.etendre_toutes_les_seances') as balayage:
            self.assertEqual(self.client.get(reverse('admin_seances')).status_code, 200)
            self.assertEqual(
                self.client.get(reverse('admin_seances'), {'statut': 'planifiee'}).status_code, 200
            )
            self.assertEqual(
                self.client.get(reverse('admin_seances'), {'groupe': '999999'}).status_code, 200
            )
            self.assertEqual(balayage.call_count, 1)

    def test_admin_calendrier_partage_le_meme_throttle_que_admin_seances(self):
        from unittest.mock import patch

        with patch('courses.utils.etendre_toutes_les_seances') as balayage:
            self.assertEqual(self.client.get(reverse('admin_seances')).status_code, 200)
            self.assertEqual(self.client.get(reverse('admin_calendrier')).status_code, 200)
            self.assertEqual(balayage.call_count, 1)


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
        self.assertTrue(DocumentEleve.objects.filter(eleves_cibles=self.eleve, titre='تقرير').exists())

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
        self.assertFalse(DocumentEleve.objects.filter(eleves_cibles=self.eleve).exists())

    def test_ajout_sans_eleve_choisi_est_refuse(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {'fichier': fichier})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DocumentEleve.objects.exists())

    def test_cible_tous_est_visible_par_tous_les_eleves(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        autre_eleve = _creer_eleve('autre_cible_tous@zidni.test')
        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('rapport.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        r = self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'tous', 'titre': 'تعميم', 'fichier': fichier,
        })
        self.assertEqual(r.status_code, 302)
        # Un SEUL enregistrement créé (plus une copie par élève, refonte du
        # 2026-08-30), visible dynamiquement par les deux élèves.
        self.assertEqual(DocumentEleve.objects.filter(titre='تعميم').count(), 1)
        self.assertTrue(DocumentEleve.pour_eleve(self.eleve).filter(titre='تعميم').exists())
        self.assertTrue(DocumentEleve.pour_eleve(autre_eleve).filter(titre='تعميم').exists())

    def test_eleve_inscrit_apres_coup_voit_quand_meme_le_fichier_tous(self):
        """Cœur de la demande client du 2026-08-30 : un fichier ajouté en
        'كل الطلاب' AVANT l'inscription d'un élève doit quand même apparaître
        dans son cartable dès sa première connexion — pas besoin que
        مدير/مشرف le redépose pour lui."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import DocumentEleve

        self.client.force_login(self.admin)
        fichier = SimpleUploadedFile('reglement.pdf', b'contenu-pdf-factice', content_type='application/pdf')
        self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'tous', 'titre': 'نظام داخلي', 'fichier': fichier,
        })
        # Élève inscrit APRÈS l'ajout du fichier.
        nouvel_eleve = _creer_eleve('nouvel_inscrit_apres_upload@zidni.test')
        self.client.force_login(nouvel_eleve.user)
        html = self.client.get(reverse('eleve_cartable')).content.decode('utf-8')
        self.assertIn('نظام داخلي', html)

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
        self.assertTrue(DocumentEleve.pour_eleve(eleve_femmes).filter(titre='خاص بالنساء').exists())
        # self.eleve (setUp) n'appartient à aucun groupe -> jamais inclus
        # dans un ciblage par catégorie précise.
        self.assertFalse(DocumentEleve.pour_eleve(self.eleve).filter(titre='خاص بالنساء').exists())

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
        self.assertFalse(DocumentEleve.pour_eleve(eleve).exists())

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
        self.assertFalse(DocumentEleve.pour_eleve(eleve).exists())

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
        self.assertTrue(DocumentEleve.pour_eleve(eleve).exists())

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

        _creer_document_cartable(
            self.eleve, titre='ملف الطالب',
            fichier=SimpleUploadedFile('doc.pdf', b'contenu-pdf-factice'), ajoute_par=self.admin,
        )
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('eleve_cartable')).content.decode('utf-8')
        self.assertIn('ملف الطالب', html)

    def test_eleve_ne_voit_pas_le_cartable_dun_autre_eleve(self):
        from accounts.models import DocumentEleve
        from django.core.files.uploadedfile import SimpleUploadedFile

        autre_eleve = _creer_eleve('autre_eleve_cartable@zidni.test')
        _creer_document_cartable(
            autre_eleve, titre='ملف الآخر',
            fichier=SimpleUploadedFile('doc2.pdf', b'contenu-pdf-factice'), ajoute_par=self.admin,
        )
        self.client.force_login(self.eleve.user)
        html = self.client.get(reverse('eleve_cartable')).content.decode('utf-8')
        self.assertNotIn('ملف الآخر', html)

    def test_admin_peut_supprimer_un_fichier(self):
        from accounts.models import DocumentEleve
        from django.core.files.uploadedfile import SimpleUploadedFile

        doc = _creer_document_cartable(
            self.eleve, titre='ملف للحذف',
            fichier=SimpleUploadedFile('doc3.pdf', b'contenu-pdf-factice'), ajoute_par=self.admin,
        )
        self.client.force_login(self.admin)
        r = self.client.post(reverse('admin_eleve_cartable_supprimer', args=[doc.id]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(DocumentEleve.objects.filter(id=doc.id).exists())


@override_settings(STORAGES={**_STORAGES_TEST, 'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'}})
class HakibaCartableLocaliseTests(TestCase):
    """Chantier i18n contenu-DB (2026-08-31), lot 5 : ElementHakiba
    (titre/contenu_texte) et DocumentEleve (titre) — ajoutés par le مدير/مشرف,
    vus par le prof (حقيبة الأستاذ) et l'élève (حقيبتي) — gagnent _fr/_en +
    <champ>_localise avec repli arabe."""

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.admin = _creer_admin()
        self.client.force_login(self.admin)
        self._pdf = lambda: SimpleUploadedFile('f.pdf', b'x', content_type='application/pdf')

    def test_element_hakiba_localise(self):
        from django.utils import translation
        from accounts.models import ElementHakiba
        e = ElementHakiba.objects.create(
            titre='ميثاق', titre_fr='Charte', contenu_texte='نص عربي', contenu_texte_en='English text',
        )
        with translation.override('fr'):
            self.assertEqual(e.titre_localise, 'Charte')
            self.assertEqual(e.contenu_texte_localise, 'نص عربي')  # _fr vide -> repli
        with translation.override('en'):
            self.assertEqual(e.contenu_texte_localise, 'English text')

    def test_admin_hakiba_ajouter_enregistre_les_traductions(self):
        from accounts.models import ElementHakiba
        self.client.post(reverse('admin_hakiba_ajouter'), {
            'cible': 'tous', 'titre': 'ملاحظة', 'titre_fr': 'Note', 'titre_en': 'Note EN',
            'contenu_texte': 'محتوى', 'contenu_texte_fr': 'Contenu FR', 'contenu_texte_en': '',
        })
        e = ElementHakiba.objects.get(titre='ملاحظة')
        self.assertEqual(e.titre_fr, 'Note')
        self.assertEqual(e.contenu_texte_fr, 'Contenu FR')

    def test_document_eleve_localise_et_ajout(self):
        from django.utils import translation
        from accounts.models import DocumentEleve
        eleve = _creer_eleve('eleve_doc_loc@zidni.test')
        self.client.post(reverse('admin_eleve_cartable_ajouter'), {
            'cible': 'specifique', 'eleves_cibles': [eleve.id],
            'titre': 'وثيقة', 'titre_fr': 'Document', 'fichier': self._pdf(),
        })
        d = DocumentEleve.objects.get(titre='وثيقة')
        self.assertEqual(d.titre_fr, 'Document')
        with translation.override('fr'):
            self.assertEqual(d.titre_localise, 'Document')
        with translation.override('en'):
            self.assertEqual(d.titre_localise, 'وثيقة')
        d.fichier.delete(save=False)


# ============================================================================
# Besoin du 2026-08-31 — les fichiers (cartable élève + حقيبة الأستاذ) s'ouvrent
# DEPUIS le site, plus par une redirection vers l'URL Cloudinary directe.
# Vues proxy : dashboard.views.eleve_cartable_fichier / hakiba_fichier.
# Stockage local en mémoire ici : ces tests ne dépendent pas de Cloudinary
# (contrairement aux CartableEleveTests ci-dessus qui testent l'upload réel).
# ============================================================================
_STORAGES_TEST_MEMOIRE = {
    **_STORAGES_TEST,
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
}


@override_settings(STORAGES=_STORAGES_TEST_MEMOIRE)
class FichiersServisDepuisLeSiteTests(TestCase):
    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.admin = _creer_admin()
        self.eleve = _creer_eleve('eleve_proxy_fichier@zidni.test')
        self.autre_eleve = _creer_eleve('autre_eleve_proxy_fichier@zidni.test')
        self.prof = _creer_prof('prof_proxy_fichier@zidni.test')
        self.autre_prof = _creer_prof('autre_prof_proxy_fichier@zidni.test')
        self.superviseur = _creer_superviseur('superviseur_proxy_fichier@zidni.test')

        self.doc_pdf = _creer_document_cartable(
            self.eleve, titre='الحصة الأولى',
            fichier=SimpleUploadedFile('cours.pdf', b'%PDF-1.4 factice'),
            ajoute_par=self.admin,
        )
        self.doc_pptx = _creer_document_cartable(
            self.eleve, titre='عرض',
            fichier=SimpleUploadedFile('slides.pptx', b'PK\x03\x04 factice'),
            ajoute_par=self.admin,
        )
        self.element_tous = ElementHakiba.objects.create(
            titre='ميثاق', tous_les_profs=True,
            fichier=SimpleUploadedFile('charte.pdf', b'%PDF-1.4 charte'),
        )
        self.element_autre_prof = ElementHakiba.objects.create(
            titre='خاص', tous_les_profs=False,
            fichier=SimpleUploadedFile('prive.pdf', b'%PDF-1.4 prive'),
        )
        self.element_autre_prof.profs_cibles.add(self.autre_prof)

    # ---------- Cartable élève ----------
    def test_eleve_ouvre_son_pdf_dans_longlet(self):
        self.client.force_login(self.eleve.user)
        r = self.client.get(reverse('eleve_cartable_fichier', args=[self.doc_pdf.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('inline', r['Content-Disposition'])
        self.assertEqual(b''.join(r.streaming_content), b'%PDF-1.4 factice')

    def test_parametre_dl_force_le_telechargement(self):
        self.client.force_login(self.eleve.user)
        r = self.client.get(reverse('eleve_cartable_fichier', args=[self.doc_pdf.id]) + '?dl=1')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])
        # Le titre sans extension récupère celle du fichier réel.
        self.assertIn('.pdf', r['Content-Disposition'])

    def test_office_toujours_en_telechargement_meme_sans_dl(self):
        self.client.force_login(self.eleve.user)
        r = self.client.get(reverse('eleve_cartable_fichier', args=[self.doc_pptx.id]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])

    def test_eleve_ne_peut_pas_ouvrir_le_fichier_dun_autre_eleve(self):
        self.client.force_login(self.autre_eleve.user)
        r = self.client.get(reverse('eleve_cartable_fichier', args=[self.doc_pdf.id]))
        self.assertEqual(r.status_code, 404)

    def test_admin_peut_ouvrir_nimporte_quel_fichier_du_cartable(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse('eleve_cartable_fichier', args=[self.doc_pdf.id]))
        self.assertEqual(r.status_code, 200)

    # ---------- حقيبة الأستاذ ----------
    def test_prof_ouvre_un_element_qui_le_concerne(self):
        self.client.force_login(self.prof.user)
        r = self.client.get(reverse('hakiba_fichier', args=[self.element_tous.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_prof_ne_peut_pas_ouvrir_un_element_ciblant_un_autre_prof(self):
        self.client.force_login(self.prof.user)
        r = self.client.get(reverse('hakiba_fichier', args=[self.element_autre_prof.id]))
        self.assertEqual(r.status_code, 404)

    def test_superviseur_ouvre_nimporte_quel_element(self):
        self.client.force_login(self.superviseur.user)
        r = self.client.get(reverse('hakiba_fichier', args=[self.element_autre_prof.id]))
        self.assertEqual(r.status_code, 200)

    def test_element_sans_fichier_renvoie_404(self):
        element_texte = ElementHakiba.objects.create(titre='note', contenu_texte='bonjour', tous_les_profs=True)
        self.client.force_login(self.prof.user)
        r = self.client.get(reverse('hakiba_fichier', args=[element_texte.id]))
        self.assertEqual(r.status_code, 404)


class MediaProxyHelpersTests(TestCase):
    """core.media_proxy — briques pures (sans HTTP ni stockage)."""

    def test_extensions_affichables_vs_telechargement(self):
        from core.media_proxy import est_affichable_navigateur

        for ok in ('a.pdf', 'b.PNG', 'c.mp3', 'd.mp4', 'e.txt'):
            self.assertTrue(est_affichable_navigateur(ok), ok)
        for ko in ('a.docx', 'b.xlsx', 'c.pptx', 'd.zip', 'e.inconnu'):
            self.assertFalse(est_affichable_navigateur(ko), ko)

    def test_content_type_connu_et_repli(self):
        from core.media_proxy import content_type_pour

        self.assertEqual(content_type_pour('x.pdf'), 'application/pdf')
        self.assertEqual(content_type_pour('x.png'), 'image/png')
        self.assertEqual(content_type_pour('x.bizarre'), 'application/octet-stream')

    def test_type_apercu(self):
        from core.media_proxy import type_apercu

        self.assertEqual(type_apercu('a.png'), 'image')
        self.assertEqual(type_apercu('a.MP4'), 'video')
        self.assertEqual(type_apercu('a.mp3'), 'audio')
        self.assertEqual(type_apercu('a.pdf'), 'embed')
        self.assertEqual(type_apercu('a.txt'), 'embed')
        self.assertEqual(type_apercu('a.docx'), '')
        self.assertEqual(type_apercu('a.zip'), '')

    def test_nom_telechargement_recolle_lextension_manquante(self):
        from core.media_proxy import _nom_telechargement

        self.assertEqual(_nom_telechargement('الحصة الأولى', 'media/x/abc_qtyuf6.pptx'), 'الحصة الأولى.pptx')
        self.assertEqual(_nom_telechargement('rapport.pdf', 'media/x/abc.pdf'), 'rapport.pdf')
        self.assertEqual(_nom_telechargement('', 'media/x/abc.pdf'), 'abc.pdf')


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
        _creer_document_cartable(self.eleve, titre='جدول التسميع', fichier='cartable_eleve/test.pdf')
        self._connecter_eleve()
        response = self.client.get(reverse('dashboard_eleve'))
        self.assertEqual(response.context['notif_total'], 1)
        self.assertContains(response, 'جدول التسميع')

    def test_document_dun_autre_eleve_ne_declenche_pas(self):
        autre_eleve = _creer_eleve(email='notif_autre_eleve@zidni.test')
        _creer_document_cartable(autre_eleve, titre='ملف غير معني', fichier='cartable_eleve/x.pdf')
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
        _creer_document_cartable(self.eleve, titre='ملف', fichier='cartable_eleve/a.pdf')
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
        _creer_document_cartable(self.eleve, titre='fichier', fichier='cartable_eleve/a.pdf')
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
        _creer_document_cartable(self.eleve, titre='ancien fichier', fichier='cartable_eleve/old.pdf')
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

    # ---------- 5c. Hakiba côté مؤطر (Chantier du 2026-08-31) ----------
    def _connecter_superviseur(self):
        self.client.force_login(self.superviseur.user)

    def test_hakiba_declenche_le_badge_superviseur(self):
        ElementHakiba.objects.create(titre='ميثاق التدريس', contenu_texte='...', tous_les_profs=True)
        self._connecter_superviseur()
        response = self.client.get(reverse('dashboard_superviseur'))
        self.assertEqual(response.context['notif_total'], 1)
        self.assertContains(response, 'ميثاق التدريس')

    def test_hakiba_ciblant_un_prof_precis_declenche_quand_meme_le_superviseur(self):
        """Contrairement au prof, le مؤطر voit TOUS les éléments de la حقيبة
        sans distinction de ciblage (voir dashboard.views.superviseur_hakiba)
        — un élément ciblé sur un seul prof lève donc quand même son badge."""
        autre_prof = _creer_prof(email='notif_hakiba_autre_prof@zidni.test')
        element = ElementHakiba.objects.create(titre='خاص بأستاذ واحد', tous_les_profs=False)
        element.profs_cibles.add(autre_prof)
        self._connecter_superviseur()
        response = self.client.get(reverse('dashboard_superviseur'))
        self.assertEqual(response.context['notif_total'], 1)

    def test_visiter_hakiba_marque_le_type_comme_lu_pour_le_superviseur(self):
        ElementHakiba.objects.create(titre='ميثاق', contenu_texte='...', tous_les_profs=True)
        self._connecter_superviseur()
        self.assertEqual(self.client.get(reverse('dashboard_superviseur')).context['notif_total'], 1)
        self.client.get(reverse('superviseur_hakiba'))
        self.assertEqual(self.client.get(reverse('dashboard_superviseur')).context['notif_total'], 0)

    def test_visite_prof_ne_marque_pas_lu_pour_le_superviseur(self):
        """DerniereVisiteNotification est keyée par (user, cle) : la visite de
        prof_hakiba par le prof ne fait jamais retomber le badge du مؤطر."""
        ElementHakiba.objects.create(titre='ميثاق', contenu_texte='...', tous_les_profs=True)
        self._connecter_prof()
        self.client.get(reverse('prof_hakiba'))  # le prof marque SON 'hakiba' lu
        self._connecter_superviseur()
        response = self.client.get(reverse('dashboard_superviseur'))
        self.assertEqual(response.context['notif_total'], 1)

    # ---------- Page "عرض الكل" ----------
    def test_mes_notifications_accessible_eleve_prof_superviseur(self):
        self._connecter_eleve()
        self.assertEqual(self.client.get(reverse('mes_notifications')).status_code, 200)
        self._connecter_prof()
        self.assertEqual(self.client.get(reverse('mes_notifications')).status_code, 200)
        self._connecter_superviseur()
        self.assertEqual(self.client.get(reverse('mes_notifications')).status_code, 200)

    def test_mes_notifications_refuse_visiteur_anonyme(self):
        self.client.logout()
        response = self.client.get(reverse('mes_notifications'))
        self.assertNotEqual(response.status_code, 200)


# ---------- Chantier du 2026-08-24 : panneau 🔔 étendu au مدير/مشرف ----------
class NotificationsDirectionTests(TestCase):
    """Voir dashboard.notifications.notifications_direction — un seul
    événement : nouvelle demande d'inscription élève (wizard public OU ajout
    manuel, inscrire_eleve() étant le point de création unique des deux)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def test_nouvelle_inscription_eleve_declenche_le_badge_admin_et_mshrif(self):
        InscriptionEleve.objects.create(
            nom='مرشح جديد', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000001', email='notif_demande@zidni.test',
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='en_attente',
        )
        self.client.force_login(self.admin)
        reponse_admin = self.client.get(reverse('dashboard_admin'))
        self.assertEqual(reponse_admin.context['notif_total'], 1)
        self.assertContains(reponse_admin, 'طلب تسجيل جديد: مرشح جديد')

        self.client.force_login(self.mshrif)
        reponse_mshrif = self.client.get(reverse('dashboard_mshrif'))
        self.assertEqual(reponse_mshrif.context['notif_total'], 1)

    def test_inscription_deja_validee_ne_declenche_pas(self):
        """Une candidature déjà traitée (valide/rejetée) ne concerne plus une
        NOUVELLE demande — jamais une fausse notification."""
        InscriptionEleve.objects.create(
            nom='مرشح مقبول مسبقاً', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000002', email='notif_deja_valide@zidni.test',
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='valide',
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard_admin'))
        self.assertEqual(response.context['notif_total'], 0)

    def test_visiter_admin_inscriptions_marque_le_type_comme_lu_independamment_par_compte(self):
        InscriptionEleve.objects.create(
            nom='مرشح آخر', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000003', email='notif_lu@zidni.test',
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='en_attente',
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 1)
        self.client.get(reverse('admin_inscriptions'))  # marque 'demandes_inscription' comme lu POUR l'admin
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 0)

        # مشرف garde SON PROPRE repère de lecture (pas encore visité) — même
        # cle partagée, mais DerniereVisiteNotification est keyée par (user, cle).
        self.client.force_login(self.mshrif)
        self.assertEqual(self.client.get(reverse('dashboard_mshrif')).context['notif_total'], 1)

    def test_visiter_la_fiche_dune_candidature_marque_aussi_le_type_comme_lu(self):
        """Correctif du 2026-08-25 : chaque lien de notification pointe vers
        admin_inscription_eleve_detail (la fiche), PAS vers admin_inscriptions
        (la liste) — avant ce correctif, cliquer une notification puis lire la
        fiche ne faisait JAMAIS baisser le badge."""
        inscription = InscriptionEleve.objects.create(
            nom='مرشح ثالث', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000004', email='notif_fiche@zidni.test',
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='en_attente',
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 1)
        self.client.get(reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 0)

    def test_admin_et_mshrif_voient_le_panneau_et_la_page_voir_tout(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('dashboard_admin')), 'id="notifWrap"')
        self.assertEqual(self.client.get(reverse('mes_notifications')).status_code, 200)

        self.client.force_login(self.mshrif)
        self.assertContains(self.client.get(reverse('dashboard_mshrif')), 'id="notifWrap"')
        self.assertEqual(self.client.get(reverse('mes_notifications')).status_code, 200)


# ---------- Fonctionnalité 3 (2026-08-27) : notification مشرف — prof en attente ----------
class NotificationsProfEnAttenteDirectionTests(TestCase):
    """Voir dashboard.notifications.notifications_direction — 2e événement :
    InscriptionProf passée en 'validee_directeur', réutilisant le même
    panneau 🔔 que NotificationsDirectionTests, مشرف UNIQUEMENT (jamais مدير,
    qui déclenche lui-même cette transition)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _inscription_en_attente(self, nom='مرشح أستاذ'):
        from inscriptions.models import InscriptionProf
        return InscriptionProf.objects.create(
            nom=nom, prenom='تجريبي', telephone='0600000010', email=f'{nom}_prof@zidni.test',
            statut='en_attente',
        )

    def _donnees_ajout_manuel(self, email):
        # Même format que AjoutManuelProfTests._donnees ci-dessus —
        # indicatif_pays/telephone_confirmation exigés par
        # inscriptions.views._construire_et_valider_telephone.
        return {
            'nom': 'أستاذ', 'prenom': 'تجريبي', 'indicatif_pays': '212',
            'telephone': '0611002244', 'telephone_confirmation': '0611002244', 'email': email,
        }

    def test_admin_valider_prof_declenche_le_badge_mshrif_pas_admin(self):
        inscription = self._inscription_en_attente()
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))

        # مدير lui-même n'est PAS notifié — c'est lui qui a déclenché la transition.
        reponse_admin = self.client.get(reverse('dashboard_admin'))
        self.assertEqual(reponse_admin.context['notif_total'], 0)

        self.client.force_login(self.mshrif)
        reponse_mshrif = self.client.get(reverse('dashboard_mshrif'))
        self.assertEqual(reponse_mshrif.context['notif_total'], 1)
        self.assertContains(reponse_mshrif, 'طلب تسجيل أستاذ جديد')

    def test_ajout_manuel_admin_declenche_aussi_le_badge_mshrif(self):
        """Fonctionnalité 3 : les 2 chemins vers 'validee_directeur' (flux
        classique admin_valider_prof ET ajout manuel admin_prof_ajouter_
        manuel) déclenchent la même notification."""
        self.client.force_login(self.admin)
        self.client.post(reverse('admin_prof_ajouter_manuel'), self._donnees_ajout_manuel('notif_ajout_manuel_prof@zidni.test'))
        self.client.force_login(self.mshrif)
        reponse_mshrif = self.client.get(reverse('dashboard_mshrif'))
        self.assertEqual(reponse_mshrif.context['notif_total'], 1)

    def test_ajout_manuel_mshrif_ne_declenche_pas(self):
        """Un ajout manuel par le مشرف lui-même saute 'validee_directeur'
        (statut='valide' directement, compte créé tout de suite) — aucune
        notification ne doit lui être adressée à lui-même."""
        self.client.force_login(self.mshrif)
        self.client.post(reverse('admin_prof_ajouter_manuel'), self._donnees_ajout_manuel('notif_ajout_manuel_mshrif@zidni.test'))
        reponse_mshrif = self.client.get(reverse('dashboard_mshrif'))
        self.assertEqual(reponse_mshrif.context['notif_total'], 0)

    def test_lien_notification_pointe_vers_la_fiche_du_candidat(self):
        """Révision du 2026-09-02 : chaque ligne du panneau mène désormais à
        la FICHE du candidat concerné (mshrif_inscription_prof_detail), plus
        vers la liste."""
        inscription = self._inscription_en_attente()
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))

        self.client.force_login(self.mshrif)
        reponse = self.client.get(reverse('dashboard_mshrif'))
        self.assertContains(
            reponse, reverse('mshrif_inscription_prof_detail', args=[inscription.id])
        )

    def test_visiter_mshrif_inscriptions_profs_marque_comme_lu(self):
        inscription = self._inscription_en_attente()
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))

        self.client.force_login(self.mshrif)
        self.assertEqual(self.client.get(reverse('dashboard_mshrif')).context['notif_total'], 1)
        self.client.get(reverse('mshrif_inscriptions_profs'))
        self.assertEqual(self.client.get(reverse('dashboard_mshrif')).context['notif_total'], 0)

    def test_visiter_la_fiche_candidat_marque_comme_lu(self):
        """La fiche détail étant la nouvelle cible du lien (voir
        test_lien_notification_pointe_vers_la_fiche_du_candidat), la consulter
        doit vider le badge exactement comme la liste."""
        inscription = self._inscription_en_attente()
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_valider_prof', args=[inscription.id]))

        self.client.force_login(self.mshrif)
        self.assertEqual(self.client.get(reverse('dashboard_mshrif')).context['notif_total'], 1)
        self.client.get(reverse('mshrif_inscription_prof_detail', args=[inscription.id]))
        self.assertEqual(self.client.get(reverse('dashboard_mshrif')).context['notif_total'], 0)

    def test_prof_deja_valide_ne_declenche_pas(self):
        """Un dossier déjà passé au statut final 'valide' ne concerne plus
        une candidature EN ATTENTE de تصديق مشرف — jamais une fausse notif."""
        from inscriptions.models import InscriptionProf
        InscriptionProf.objects.create(
            nom='أستاذ مقبول نهائياً', prenom='تجريبي', telephone='0600000013',
            email='notif_prof_deja_valide@zidni.test', statut='valide',
        )
        self.client.force_login(self.mshrif)
        self.assertEqual(self.client.get(reverse('dashboard_mshrif')).context['notif_total'], 0)


class NotificationsNouvelleCandidatureProfDirectionTests(TestCase):
    """Voir dashboard.notifications.notifications_direction — groupe "1bis" :
    InscriptionProf.statut='en_attente' (candidature prof pas encore
    pré-validée). مدير UNIQUEMENT (le مشرف n'agit qu'à l'étape 2), `cle`
    dédiée 'demandes_inscription_prof' distincte de celle des élèves."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _candidature(self, nom='مرشح أستاذ جديد', statut='en_attente'):
        from inscriptions.models import InscriptionProf
        return InscriptionProf.objects.create(
            nom=nom, prenom='تجريبي', telephone='0600000020',
            email=f'{nom}_prof_nouveau@zidni.test'.replace(' ', '_'), statut=statut,
        )

    def test_nouvelle_candidature_prof_declenche_le_badge_du_directeur_pas_du_mshrif(self):
        self._candidature()
        self.client.force_login(self.admin)
        reponse_admin = self.client.get(reverse('dashboard_admin'))
        self.assertEqual(reponse_admin.context['notif_total'], 1)
        self.assertContains(reponse_admin, 'طلب تسجيل أستاذ جديد')

        # مشرف : l'étape 1 n'est pas la sienne, rien pour lui ici.
        self.client.force_login(self.mshrif)
        self.assertEqual(self.client.get(reverse('dashboard_mshrif')).context['notif_total'], 0)

    def test_candidature_prof_deja_pre_validee_ne_declenche_pas_ce_groupe(self):
        self._candidature(statut='validee_directeur')
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 0)

    def test_visiter_la_liste_des_inscriptions_marque_comme_lu(self):
        self._candidature()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 1)
        self.client.get(reverse('admin_inscriptions'))
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 0)

    def test_visiter_la_fiche_de_la_candidature_marque_comme_lu(self):
        inscription = self._candidature()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 1)
        self.client.get(reverse('admin_inscription_prof_detail', args=[inscription.id]))
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 0)

    def test_repere_de_lecture_independant_de_celui_des_eleves(self):
        """`cle` dédiée : lire une fiche élève ne doit pas faire disparaître
        la notification d'une candidature prof (et inversement)."""
        self._candidature()
        eleve_ins = InscriptionEleve.objects.create(
            nom='مرشح تلميذ', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000021', email='notif_mix_eleve@zidni.test',
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='en_attente',
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 2)
        # Lire uniquement la fiche élève.
        self.client.get(reverse('admin_inscription_eleve_detail', args=[eleve_ins.id]))
        reponse = self.client.get(reverse('dashboard_admin'))
        self.assertEqual(reponse.context['notif_total'], 1)
        self.assertContains(reponse, 'طلب تسجيل أستاذ جديد')


class NotificationsOrdreGroupesTests(TestCase):
    """Ordre du panneau 🔔, de la notification la PLUS RÉCENTE à la plus
    ancienne : panneaux élève/prof/مؤطر = groupes triés entre eux
    (_trier_groupes_par_recence) ; panneau direction = liste plate triée
    strictement par date (option iii du 2026-09-02)."""

    def setUp(self):
        from django.utils import timezone
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        # Recule le seuil d'amorçage des notifications (dashboard.notifications.
        # _seuils amorce toute cle jamais visitée à user.date_joined) bien dans
        # le passé, pour que des évènements datés « il y a 10 jours » restent
        # au-dessus du seuil et apparaissent donc dans le panneau.
        User.objects.filter(pk__in=[self.admin.pk, self.mshrif.pk]).update(
            date_joined=timezone.now() - datetime.timedelta(days=90)
        )

    def test_trier_groupes_par_recence_ordonne_du_plus_recent_au_plus_ancien(self):
        from django.utils import timezone
        from dashboard.notifications import _trier_groupes_par_recence

        t0 = timezone.now()
        ancien = {'label': 'ancien', 'evenements': [{'date': t0 - datetime.timedelta(days=10)}]}
        recent = {'label': 'recent', 'evenements': [{'date': t0 - datetime.timedelta(hours=1)}]}
        milieu = {'label': 'milieu', 'evenements': [{'date': t0 - datetime.timedelta(days=2)}]}
        ordre = [g['label'] for g in _trier_groupes_par_recence([ancien, recent, milieu])]
        self.assertEqual(ordre, ['recent', 'milieu', 'ancien'])

    def test_panneau_direction_est_une_liste_plate_triee_par_date(self):
        """Panneau direction = liste plate (option iii du 2026-09-02) : un
        seul pseudo-groupe sans label, évènements de tous types fusionnés et
        triés strictement du plus récent au plus ancien."""
        from django.utils import timezone

        # Demande d'inscription élève plus ANCIENNE que la candidature prof
        # ci-dessous (date_soumission = auto_now_add, réécrite via .update()
        # qui bypasse auto_now_add) mais postérieure au seuil (date_joined
        # reculé de 90 j dans setUp).
        ins_eleve = InscriptionEleve.objects.create(
            nom='مرشح قديم', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000030', email='notif_ordre_eleve@zidni.test',
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='en_attente',
        )
        InscriptionEleve.objects.filter(pk=ins_eleve.pk).update(
            date_soumission=timezone.now() - datetime.timedelta(days=10)
        )

        # Candidature prof pré-validée à l'instant -> notification RÉCENTE pour le مشرف.
        from inscriptions.models import InscriptionProf
        ins_prof = InscriptionProf.objects.create(
            nom='مرشح حديث', prenom='تجريبي', telephone='0600000031',
            email='notif_ordre_prof@zidni.test', statut='en_attente',
        )
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_valider_prof', args=[ins_prof.id]))

        self.client.force_login(self.mshrif)
        groupes = self.client.get(reverse('dashboard_mshrif')).context['notif_groupes']
        # Un seul pseudo-groupe, sans label.
        self.assertEqual(len(groupes), 1)
        self.assertFalse(groupes[0]['label'])
        evts = groupes[0]['evenements']
        self.assertEqual(len(evts), 2)
        # Tri strictement décroissant par date : prof (à l'instant) avant élève (il y a 10 j).
        self.assertGreater(evts[0]['date'], evts[1]['date'])
        self.assertTrue(evts[0]['texte'].startswith('طلب تسجيل أستاذ جديد'))
        self.assertTrue(evts[1]['texte'].startswith('طلب تسجيل جديد'))
        # Chaque ligne porte son icône de type.
        self.assertEqual(evts[0]['icone'], '👨‍🏫')
        self.assertEqual(evts[1]['icone'], '📝')


class NotificationsDirectionBadgeVsPanneauTests(TestCase):
    """Cloche direction = centre de notifications (révision 2026-09-02) :
    le BADGE (notif_total) ne compte que les non-lus et se vide à la visite
    de la page cible ; le PANNEAU (notif_groupes) liste TOUTE demande encore
    en attente, lue ou non, et ne se vide jamais tant qu'il reste à traiter."""

    def setUp(self):
        self.admin = _creer_admin()

    def _inscription_eleve(self, email, nom='مرشح'):
        return InscriptionEleve.objects.create(
            nom=nom, date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000050', email=email,
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut='en_attente',
        )

    def test_visite_vide_le_badge_mais_pas_le_panneau(self):
        self._inscription_eleve('badge_panneau_1@zidni.test', nom='بشير')
        self.client.force_login(self.admin)

        r1 = self.client.get(reverse('dashboard_admin'))
        self.assertEqual(r1.context['notif_total'], 1)
        self.assertEqual(len(r1.context['notif_groupes'][0]['evenements']), 1)
        self.assertTrue(r1.context['notif_groupes'][0]['evenements'][0]['non_lu'])

        # Visite de la page cible.
        self.client.get(reverse('admin_inscriptions'))

        r2 = self.client.get(reverse('dashboard_admin'))
        # Badge éteint...
        self.assertEqual(r2.context['notif_total'], 0)
        # ...mais la demande, toujours en attente, reste dans le panneau.
        evts = r2.context['notif_groupes'][0]['evenements']
        self.assertEqual(len(evts), 1)
        self.assertIn('بشير', evts[0]['texte'])
        self.assertFalse(evts[0]['non_lu'])

    def test_badge_ne_compte_que_les_non_lus_dans_une_liste_mixte(self):
        from django.utils import timezone
        # 1 ancienne demande (sera « lue » après visite)...
        vieille = self._inscription_eleve('badge_mixte_vieux@zidni.test', nom='قديم')
        InscriptionEleve.objects.filter(pk=vieille.pk).update(
            date_soumission=timezone.now() - datetime.timedelta(days=5)
        )
        self.client.force_login(self.admin)
        self.client.get(reverse('admin_inscriptions'))  # marque tout lu

        # ...puis 2 nouvelles demandes arrivées APRÈS la visite.
        self._inscription_eleve('badge_mixte_neuf1@zidni.test', nom='جديد١')
        self._inscription_eleve('badge_mixte_neuf2@zidni.test', nom='جديد٢')

        r = self.client.get(reverse('dashboard_admin'))
        # Panneau : les 3 demandes en attente.
        self.assertEqual(len(r.context['notif_groupes'][0]['evenements']), 3)
        # Badge : seulement les 2 non lues.
        self.assertEqual(r.context['notif_total'], 2)

    def test_panneau_montre_aussi_l_historique_des_demandes_traitees(self):
        """Une demande acceptée/refusée reste visible dans le panneau (avec sa
        pastille de statut), même si elle ne compte plus dans le badge."""
        from inscriptions.models import InscriptionProf
        acceptee = self._inscription_eleve('histo_ok@zidni.test', nom='مقبول')
        InscriptionEleve.objects.filter(pk=acceptee.pk).update(statut='valide')
        refusee = self._inscription_eleve('histo_ko@zidni.test', nom='مرفوض')
        InscriptionEleve.objects.filter(pk=refusee.pk).update(statut='rejete')
        prof_valide = InscriptionProf.objects.create(
            nom='أستاذ', prenom='مقبول', telephone='0600000055',
            email='histo_prof@zidni.test', statut='valide',
        )

        self.client.force_login(self.admin)
        r = self.client.get(reverse('dashboard_admin'))
        evts = r.context['notif_groupes'][0]['evenements']
        textes = ' '.join(e['texte'] for e in evts)
        self.assertIn('مقبول', textes)
        self.assertIn('مرفوض', textes)
        self.assertEqual(len(evts), 3)
        # Aucune n'est « non lue » -> badge à zéro.
        self.assertEqual(r.context['notif_total'], 0)
        self.assertTrue(all(e['non_lu'] is False for e in evts))
        # Chaque ligne d'inscription porte une pastille de statut.
        tons = {e['statut_ton'] for e in evts}
        self.assertTrue({'ok', 'ko'} <= tons)


class BadgeSidebarGestionUtilisateursTests(TestCase):
    """Badges du groupe « إدارة المستخدمين » (voir dashboard.context_processors.
    badges_sidebar_direction) : item PARENT = somme, + un badge propre sur
    chaque sous-item (« طلبات التسجيل » = inscriptions en_attente élèves+profs,
    « طلبات الأساتذة » مشرف = profs validee_directeur)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _inscription_eleve(self, email, statut='en_attente'):
        return InscriptionEleve.objects.create(
            nom='مرشح', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
            telephone='0600000040', email=email,
            programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
            statut=statut,
        )

    def _inscription_prof(self, email, statut='en_attente'):
        from inscriptions.models import InscriptionProf
        return InscriptionProf.objects.create(
            nom='أستاذ', prenom='تجريبي', telephone='0600000041', email=email, statut=statut,
        )

    def test_directeur_parent_et_sous_item_egaux_aux_inscriptions_en_attente(self):
        self._inscription_eleve('badge_dir_eleve@zidni.test')
        self._inscription_prof('badge_dir_prof@zidni.test')  # en_attente
        self.client.force_login(self.admin)
        reponse = self.client.get(reverse('dashboard_admin'))
        # مدير : parent == sous-item « طلبات التسجيل » (pas d'autre sous-item).
        self.assertEqual(reponse.context['nb_inscriptions_attente'], 2)
        self.assertEqual(reponse.context['badge_gestion_utilisateurs'], 2)
        self.assertContains(reponse, 'menu-cat-titre')

    def test_mshrif_parent_est_la_somme_inscriptions_plus_profs_a_valider(self):
        self._inscription_eleve('badge_mshrif_eleve@zidni.test')                       # +1 inscription
        self._inscription_prof('badge_mshrif_prof_att@zidni.test')                     # +1 inscription (prof en_attente)
        self._inscription_prof('badge_mshrif_prof_dir@zidni.test', statut='validee_directeur')  # +1 à valider
        self.client.force_login(self.mshrif)
        reponse = self.client.get(reverse('dashboard_mshrif'))
        self.assertEqual(reponse.context['nb_inscriptions_attente'], 2)
        self.assertEqual(reponse.context['nb_profs_a_valider'], 1)
        # Parent = somme des 2 sous-badges visibles une fois déplié.
        self.assertEqual(reponse.context['badge_gestion_utilisateurs'], 3)

    def test_mshrif_badge_sous_item_profs_inchange(self):
        """« طلبات الأساتذة » garde son badge historique nb_demandes_en_attente
        (profs validee_directeur) — non touché par ce chantier."""
        self._inscription_prof('badge_mshrif_hist@zidni.test', statut='validee_directeur')
        self.client.force_login(self.mshrif)
        reponse = self.client.get(reverse('dashboard_mshrif'))
        self.assertEqual(reponse.context['nb_demandes_en_attente'], 1)

    def test_pas_de_badge_pour_les_autres_roles(self):
        eleve = _creer_eleve(email='badge_neutre_eleve@zidni.test')
        self.client.force_login(eleve.user)
        reponse = self.client.get(reverse('dashboard_eleve'))
        self.assertNotIn('badge_gestion_utilisateurs', reponse.context)
        self.assertNotIn('nb_inscriptions_attente', reponse.context)


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


class LibellesArabesListeFiltreTests(TestCase):
    """Filtre dashboard.templatetags.libelles_arabes.libelles_arabes_liste —
    les valeurs de LIBELLES sont des gettext_lazy (__proxy__) depuis le
    chantier i18n : str.join() lève 'expected str instance, __proxy__ found'
    si on ne force pas str() sur chaque élément (bug fiche prof, 2026-08-31)."""

    def test_liste_de_codes_traduits_est_jointe_sans_typeerror(self):
        from dashboard.templatetags.libelles_arabes import libelles_arabes_liste
        self.assertEqual(
            libelles_arabes_liste(['arabe', 'francais'], 'langues'),
            'العربية، الفرنسية',
        )

    def test_code_inconnu_retombe_sur_le_code_brut(self):
        from dashboard.templatetags.libelles_arabes import libelles_arabes_liste
        self.assertEqual(libelles_arabes_liste(['xyz'], 'langues'), 'xyz')

    def test_fiche_prof_avec_champs_json_non_vides_rend_200(self):
        prof = _creer_prof('prof_libelles_json@zidni.test')
        prof.langues = ['arabe', 'francais']
        prof.outils_maitrises = ['whatsapp', 'meet']
        prof.type_eleve_preference = ['enfants']
        prof.contrainte_genre = ['mixte']
        prof.save()
        self.client.force_login(_creer_admin())
        r = self.client.get(reverse('admin_prof_detail', args=[prof.id]))
        self.assertEqual(r.status_code, 200)


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
# Chantier découvrabilité مؤطر du 2026-08-30 — superviseur_emploi (nouvelle
# vue, jusqu'ici la sidebar مؤطر n'exposait ni grille horaire ni lien clair
# vers les séances/l'évaluation). Mirroir de ProfEmploiGeneralisationSlotsTests
# mais scopé sur superviseur.profs_assignes (plusieurs profs possibles).
# ============================================================================
class SuperviseurEmploiTests(TestCase):
    def setUp(self):
        self.superviseur = _creer_superviseur('superviseur_emploi@zidni.test')
        self.prof = _creer_prof('prof_emploi_superviseur@zidni.test')
        self.superviseur.profs_assignes.add(self.prof)
        self.client.force_login(self.superviseur.user)

    def _creneau_lundi_16h(self):
        creneau = Creneau.objects.create(
            sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=12,
        )
        remplacer_slots_creneau(creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        return creneau

    def test_affiche_le_groupe_dun_prof_assigne(self):
        creneau = self._creneau_lundi_16h()
        Groupe.objects.create(nom='مجموعة المؤطر', creneau=creneau, prof=self.prof, statut='actif')

        reponse = self.client.get(reverse('superviseur_emploi'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('مجموعة المؤطر', html)
        self.assertIn(self.prof.user.get_full_name(), html)

    def test_groupe_dun_prof_non_assigne_est_absent(self):
        """Isolation : un prof non assigné à ce مؤطر ne doit jamais apparaître
        sur sa grille, même si son groupe a un créneau actif."""
        creneau = self._creneau_lundi_16h()
        autre_prof = _creer_prof('prof_hors_perimetre@zidni.test')
        Groupe.objects.create(nom='مجموعة أستاذ آخر', creneau=creneau, prof=autre_prof, statut='actif')

        reponse = self.client.get(reverse('superviseur_emploi'))
        self.assertNotIn('مجموعة أستاذ آخر', reponse.content.decode('utf-8'))

    def test_sans_groupe_actif_affiche_letat_vide(self):
        reponse = self.client.get(reverse('superviseur_emploi'))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('لا توجد مجموعات نشطة', reponse.content.decode('utf-8'))

    def test_lien_accessible_uniquement_au_role_superviseur(self):
        """@role_required('superviseur') — un prof connecté ne doit pas
        pouvoir accéder à la grille d'un مؤطر."""
        self.client.force_login(self.prof.user)
        reponse = self.client.get(reverse('superviseur_emploi'))
        self.assertNotEqual(reponse.status_code, 200)

    def test_traduit_reellement_en_fr_et_en(self):
        """Même piège que RenduReelFrEnTemplatesAdminTests (chantier i18n du
        2026-08-29) : un {% trans %} syntaxiquement correct peut rester
        affiché en arabe si locale/*.po/.mo n'a pas été recompilé avec ce
        msgid — cette page ajoute justement 2 nouveaux msgids au catalogue,
        donc test de rendu réel plutôt qu'un simple assertIn sur le tag."""
        self.client.post(reverse('set_language'), {'language': 'fr', 'next': reverse('superviseur_emploi')})
        html_fr = self.client.get(reverse('superviseur_emploi')).content.decode('utf-8')
        self.assertIn('Mon emploi du temps', html_fr)
        self.assertIn('Aucun groupe actif chez les enseignants qui vous sont assignés', html_fr)
        self.assertNotIn('لا توجد مجموعات نشطة', html_fr)

        self.client.post(reverse('set_language'), {'language': 'en', 'next': reverse('superviseur_emploi')})
        html_en = self.client.get(reverse('superviseur_emploi')).content.decode('utf-8')
        self.assertIn('My schedule', html_en)
        self.assertIn('No active groups among the teachers assigned to you', html_en)
        self.assertNotIn('لا توجد مجموعات نشطة', html_en)


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

    def test_detacher_groupe_permet_ensuite_la_suppression(self):
        """Chantier du 2026-08-25 : détacher un critère de TOUS ses groupes
        depuis sa propre fiche (nouveau bouton "فك الارتباط") lève le PROTECT
        vérifié ci-dessus — la suppression réussit ensuite normalement,
        aucune donnée candidat perdue (aucune ReponseInscription ici)."""
        from courses.models import Creneau, Groupe
        from courses.utils import remplacer_slots_creneau as _slots

        client = self._connecte_admin()
        critere = CritereInscription.objects.create(code='niveau_test', label='المستوى', filtrable=True)
        option = CritereOption.objects.create(critere=critere, code='inter', label='متوسط')
        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(creneau, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
        groupe1 = Groupe.objects.create(nom='مجموعة أولى', creneau=creneau, statut='actif')
        groupe2 = Groupe.objects.create(nom='مجموعة ثانية', creneau=creneau, statut='actif')
        GroupeCritereValeur.objects.create(groupe=groupe1, critere=critere, option=option)
        GroupeCritereValeur.objects.create(groupe=groupe2, critere=critere, option=option)

        # Suppression refusée tant que les 2 liens existent.
        client.get(reverse('admin_critere_inscription_supprimer', args=[critere.id]))
        self.assertTrue(CritereInscription.objects.filter(id=critere.id).exists())

        # La fiche liste bien les 2 groupes configurés.
        html = client.get(reverse('admin_critere_inscription_detail', args=[critere.id])).content.decode('utf-8')
        self.assertIn('مجموعة أولى', html)
        self.assertIn('مجموعة ثانية', html)

        # Détache le 1er groupe uniquement — le 2e lien bloque encore.
        client.post(reverse('admin_critere_inscription_detacher_groupe', args=[critere.id, groupe1.id]))
        self.assertFalse(GroupeCritereValeur.objects.filter(groupe=groupe1, critere=critere).exists())
        self.assertTrue(GroupeCritereValeur.objects.filter(groupe=groupe2, critere=critere).exists())
        client.get(reverse('admin_critere_inscription_supprimer', args=[critere.id]))
        self.assertTrue(CritereInscription.objects.filter(id=critere.id).exists())  # encore bloqué

        # Détache le 2e groupe — plus aucun lien, la suppression réussit désormais.
        client.post(reverse('admin_critere_inscription_detacher_groupe', args=[critere.id, groupe2.id]))
        self.assertFalse(GroupeCritereValeur.objects.filter(critere=critere).exists())
        client.get(reverse('admin_critere_inscription_supprimer', args=[critere.id]))
        self.assertFalse(CritereInscription.objects.filter(id=critere.id).exists())  # supprimé cette fois

    def test_detacher_groupe_refuse_get(self):
        from courses.models import Creneau, Groupe
        from courses.utils import remplacer_slots_creneau as _slots

        client = self._connecte_admin()
        critere = CritereInscription.objects.create(code='niveau_test_get', label='المستوى', filtrable=True)
        option = CritereOption.objects.create(critere=critere, code='inter', label='متوسط')
        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        _slots(creneau, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
        groupe = Groupe.objects.create(nom='مجموعة GET', creneau=creneau, statut='actif')
        GroupeCritereValeur.objects.create(groupe=groupe, critere=critere, option=option)

        reponse = client.get(reverse('admin_critere_inscription_detacher_groupe', args=[critere.id, groupe.id]))
        self.assertEqual(reponse.status_code, 405)
        self.assertTrue(GroupeCritereValeur.objects.filter(groupe=groupe, critere=critere).exists())

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
# EtapeInscription / ChampInscription. Même exigence de
# parité stricte Directeur/مشرف que 5A.
# ============================================================================
class EtapeChampInscriptionCRUDTests(TestCase):
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

    def test_liste_affiche_les_7_vraies_etapes_du_parcours(self):
        """Correction 8 (2026-08-22) : bug signalé — seules 2 étapes sur 7
        s'affichaient (identite/programme, seules seedées avant la migration
        0007). Vérifie que TOUTES les vraies étapes du parcours public sont
        désormais listées."""
        client = self._connecte_admin()
        html = client.get(reverse('admin_etapes_inscription')).content.decode('utf-8')
        for code in ('categorie_age', 'identite', 'programme', 'groupe', 'abonnement', 'paiement', 'confirmation'):
            self.assertIn(code, html, f'{code} devrait apparaître dans la liste')

    def test_etapes_verrouillees_affichent_le_cadenas_et_pas_de_bouton_toggle(self):
        client = self._connecte_admin()
        for code in EtapeInscription.CODES_VERROUILLES:
            etape = EtapeInscription.objects.get(code=code)
            html = client.get(reverse('admin_etape_inscription_detail', args=[etape.id])).content.decode('utf-8')
            self.assertIn('🔒', html)
            self.assertNotIn(reverse('admin_etape_inscription_toggle', args=[etape.id]), html)
            self.assertNotIn(reverse('admin_etape_inscription_supprimer', args=[etape.id]), html)

    def test_toggle_refuse_pour_une_etape_verrouillee(self):
        client = self._connecte_admin()
        etape = EtapeInscription.objects.get(code='abonnement')
        client.get(reverse('admin_etape_inscription_toggle', args=[etape.id]))
        etape.refresh_from_db()
        self.assertTrue(etape.est_actif)

    def test_toggle_fonctionne_pour_une_etape_non_verrouillee(self):
        client = self._connecte_admin()
        etape = EtapeInscription.objects.get(code='groupe')
        client.get(reverse('admin_etape_inscription_toggle', args=[etape.id]))
        etape.refresh_from_db()
        self.assertFalse(etape.est_actif)
        etape.est_actif = True  # remis en état
        etape.save()

    def test_suppression_refusee_pour_une_etape_verrouillee_meme_sans_champs(self):
        """Ces étapes n'ont souvent AUCUN ChampInscription (groupe/abonnement/
        paiement/confirmation/categorie_age ne rendent jamais de champ
        générique) — le garde-fou ProtectedError (déjà testé ailleurs pour
        une étape avec champs) ne se déclencherait donc JAMAIS pour elles ;
        ce test vérifie le garde-fou explicite dédié aux étapes verrouillées."""
        client = self._connecte_admin()
        etape = EtapeInscription.objects.get(code='confirmation')
        self.assertEqual(etape.champs.count(), 0)
        client.get(reverse('admin_etape_inscription_supprimer', args=[etape.id]))
        self.assertTrue(EtapeInscription.objects.filter(id=etape.id).exists())

    def test_modifier_ignore_est_actif_poste_pour_une_etape_verrouillee(self):
        client = self._connecte_admin()
        etape = EtapeInscription.objects.get(code='paiement')
        client.post(reverse('admin_etape_inscription_modifier', args=[etape.id]), {
            'titre': etape.titre, 'ordre': etape.ordre,  # 'est_actif' volontairement absent (décoché)
        })
        etape.refresh_from_db()
        self.assertTrue(etape.est_actif)

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

    def test_menu_systeme_a_exclut_les_criteres_qui_ne_filtrent_jamais(self):
        """Chantier du 2026-08-23 (Partie 2, séparation Système A/B) : un
        critère de type texte/nombre/date/... ne filtre RÉELLEMENT jamais
        (registration.utils.groupes_compatibles ne compare que des
        CritereOption) — même coché 'filtrable', c'est un piège pour le
        مدير. Le menu "المعيار" du bloc Système A ("سؤال يُستخدم لتصفية
        المجموعات") ne doit donc plus jamais le proposer, contrairement au
        critère choix_unique/choix_multiple qui, lui, reste proposé."""
        etape = EtapeInscription.objects.create(code='test_identite_systeme_a', titre='المعلومات الشخصية')
        critere_texte = CritereInscription.objects.create(
            code='test_critere_texte_piege', label='معيار نصي لا يُصفّي أبداً', type_champ='texte', filtrable=True,
        )
        critere_choix = CritereInscription.objects.create(
            code='test_critere_choix_valide', label='معيار اختيار يُصفّي فعلاً', type_champ='choix_unique',
        )
        client = self._connecte_admin()
        html = client.get(reverse('admin_etape_inscription_detail', args=[etape.id])).content.decode('utf-8')
        self.assertNotIn('معيار نصي لا يُصفّي أبداً', html)
        self.assertIn('معيار اختيار يُصفّي فعلاً', html)

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

    def test_etape_identite_naffiche_plus_aucun_champ_bidon_grace_aux_champs_structurels(self):
        """Bug signalé le 2026-08-22 : l'étape "المعلومات الشخصية" affichait
        "لا توجد حقول بعد" alors que nom/sexe/telephone/... existent et sont
        utilisés — corrigé par ConfigurationChampStructurel, affiché dans la
        MÊME liste que les ChampInscription."""
        etape_identite = EtapeInscription.objects.get(code='identite')
        client = self._connecte_admin()
        html = client.get(reverse('admin_etape_inscription_detail', args=[etape_identite.id])).content.decode('utf-8')
        self.assertNotIn('لا توجد حقول بعد', html)
        self.assertIn('الاسم الكامل', html)
        self.assertIn('المستوى الدراسي', html)  # niveau_scolaire, nouveau champ

    def test_modifier_champ_structurel_non_verrouille_reussit(self):
        config = ConfigurationChampStructurel.objects.get(champ_cle='job_actuel')
        client = self._connecte_admin()
        reponse = client.post(reverse('admin_champ_structurel_modifier', args=[config.id]), {
            'label': 'مهنتك الحالية', 'ordre': 5, 'etape_id': config.etape_id,
            'obligatoire': 'on', 'est_actif': 'on', 'type_champ': 'texte',
            'placeholder': 'مثال: مهندس', 'texte_aide': 'اختياري',
        })
        self.assertEqual(reponse.status_code, 302)
        config.refresh_from_db()
        self.assertEqual(config.label, 'مهنتك الحالية')
        self.assertTrue(config.obligatoire)
        self.assertEqual(config.placeholder, 'مثال: مهندس')

    def test_modifier_champ_verrouille_ignore_toute_tentative_hors_label_ordre(self):
        """Défense en profondeur écran + modèle (déjà testée côté modèle) :
        même en POSTant obligatoire/est_actif/etape_id pour 'sexe', seuls
        label et ordre sont réellement pris en compte."""
        autre_etape = EtapeInscription.objects.create(code='test_autre_etape_ecran', titre='أخرى', ordre=88)
        config = ConfigurationChampStructurel.objects.get(champ_cle='sexe')
        etape_originale_id = config.etape_id

        client = self._connecte_admin()
        reponse = client.post(reverse('admin_champ_structurel_modifier', args=[config.id]), {
            'label': 'جنس المسجَّل', 'ordre': 1,
            'obligatoire': '', 'est_actif': '', 'etape_id': autre_etape.id,
        })
        self.assertEqual(reponse.status_code, 302)
        config.refresh_from_db()
        self.assertEqual(config.label, 'جنس المسجَّل')  # label : bien pris en compte
        self.assertTrue(config.obligatoire)  # jamais relâché
        self.assertTrue(config.est_actif)  # jamais relâché
        self.assertEqual(config.etape_id, etape_originale_id)  # jamais déplacé


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

    def test_moyen_autre_modifiable_a_parite_stricte_comme_cih_barid(self):
        """Chantier du 2026-08-27 ("طريقة أخرى" pour les élèves sans compte
        bancaire) — MÊME structure que CIH/Barid Bank ci-dessus : aucune vue
        ni logique dédiée, une ligne MoyenPaiement de plus, éditable par
        مدير ET مشرف à travers le MÊME formulaire (voir
        dashboard.views.admin_moyen_paiement_modifier, qui ne connaît aucun
        code particulier)."""
        from payments.models import MoyenPaiement

        moyen = MoyenPaiement.objects.create(code='autre_parite_test', label='طريقة أخرى', coordonnees='نص أولي')
        for client in (self._connecte_admin(), self._connecte_mshrif()):
            reponse = client.post(reverse('admin_moyen_paiement_modifier', args=[moyen.id]), {
                'label': 'طريقة أخرى', 'coordonnees': 'يرجى التواصل مع الإدارة', 'ordre': 999,
            })
            self.assertEqual(reponse.status_code, 302)
            moyen.refresh_from_db()
            self.assertEqual(moyen.coordonnees, 'يرجى التواصل مع الإدارة')

        client = self._connecte_admin()
        client.get(reverse('admin_moyen_paiement_toggle', args=[moyen.id]))
        moyen.refresh_from_db()
        self.assertFalse(moyen.est_actif)

    # test_liste_ajout_toggle_suppression_option_nb_seances_a_parite_stricte
    # retiré (2026-08-29) : doublon de couverture avec les tests déjà
    # existants pour admin_options_nb_seances/ajouter/toggle plus haut dans
    # ce fichier (catalogue partagé courses.OptionNbSeances, chantier du
    # 2026-08-27) — ce catalogue n'a volontairement aucune suppression
    # définitive (toggle actif/inactif seulement, voir son __doc__), la
    # version testée ici en avait une, incompatible avec cette politique.

    def test_presentation_inscription_editable_par_les_deux_roles(self):
        for client in (self._connecte_admin(), self._connecte_mshrif()):
            reponse = client.post(reverse('admin_presentation_inscription'), {
                'titre': 'أهلاً بك', 'intro': 'نص الميثاق', 'bouton_texte': 'متابعة',
                'message_bienvenue': 'مرحباً بك في زدني علماً',
                'texte_attente_groupe': 'نص بطاقة الانتظار المعدّل',
                'afficher_disponibilites_si_attente': '1',
            })
            self.assertEqual(reponse.status_code, 302)

        from registration.models import get_presentation_inscription
        presentation = get_presentation_inscription()
        self.assertEqual(presentation.titre, 'أهلاً بك')
        # Chantier du 2026-08-25 : même formulaire, même permissions مدير/مشرف
        # (voir registration.models.PresentationInscription.texte_attente_groupe).
        self.assertEqual(presentation.texte_attente_groupe, 'نص بطاقة الانتظار المعدّل')
        # Chantier du 2026-08-27 : coché dans les 2 POST ci-dessus -> reste True.
        self.assertTrue(presentation.afficher_disponibilites_si_attente)

    def test_toggle_disponibilites_si_attente_se_desactive_quand_decoche(self):
        """Une case à cocher absente du POST (décochée côté navigateur) doit
        bien repasser le réglage à False — pas de valeur fantôme conservée."""
        from registration.models import get_presentation_inscription

        presentation = get_presentation_inscription()
        presentation.afficher_disponibilites_si_attente = True
        presentation.save()

        client = self._connecte_admin()
        client.post(reverse('admin_presentation_inscription'), {
            'titre': 'أهلاً بك', 'intro': 'نص الميثاق', 'bouton_texte': 'متابعة',
            'message_bienvenue': 'مرحباً بك', 'texte_attente_groupe': 'انتظر',
            # 'afficher_disponibilites_si_attente' volontairement absent.
        })
        presentation.refresh_from_db()
        self.assertFalse(presentation.afficher_disponibilites_si_attente)

    def test_traductions_fr_en_optionnelles_avec_repli_arabe(self):
        """Chantier i18n du 2026-08-28 ("Problème B") : les 6 champs de
        PresentationInscription existent désormais aussi en _fr/_en, saisis à la
        main par le مدير/مشرف (PAS de traduction automatique — voir
        PresentationInscription._localise) — le champ arabe reste seul
        obligatoire ; FR/EN restent optionnels et servent de repli sur l'arabe
        tant qu'ils ne sont pas remplis."""
        from django.utils import translation
        from registration.models import get_presentation_inscription

        client = self._connecte_admin()
        client.post(reverse('admin_presentation_inscription'), {
            'titre': 'أهلاً بك', 'intro': 'نص الميثاق', 'bouton_texte': 'متابعة',
            'message_bienvenue': 'مرحباً', 'message_aucun_groupe_exact': 'لا توجد مجموعة',
            'texte_attente_groupe': 'انتظر',
            'titre_fr': 'Bienvenue', 'titre_en': '',  # EN volontairement laissé vide
        })
        presentation = get_presentation_inscription()
        self.assertEqual(presentation.titre_fr, 'Bienvenue')
        self.assertEqual(presentation.titre_en, '')
        with translation.override('fr'):
            self.assertEqual(presentation.titre_localise, 'Bienvenue')
        with translation.override('en'):
            # EN vide -> repli automatique sur l'arabe, jamais un texte manquant.
            self.assertEqual(presentation.titre_localise, 'أهلاً بك')
        with translation.override('ar'):
            self.assertEqual(presentation.titre_localise, 'أهلاً بك')

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

    # --- Écran de confirmation post-acceptation : bloc « المجموعة » + bouton
    #     « إضافة الطالب إلى مجموعة » (Chantier du 2026-09-03) ---

    def test_confirmation_sans_halaka_propose_un_bouton_vers_la_fiche_eleve(self):
        """Élève inscrit « بدون مجموعة » : l'écran de confirmation affiche un
        bouton d'ajout menant directement à la section « مجموعات مقترحة » de la
        fiche élève (ancre #groupes-suggeres)."""
        inscription = _creer_inscription_eleve(
            email='confirm_sans_halaka@zidni.test', date_naissance=datetime.date(2000, 1, 1),
        )
        reponse = self.client.get(reverse('admin_valider_eleve', args=[inscription.id]), follow=True)
        self.assertEqual(reponse.status_code, 200)

        eleve = Eleve.objects.get(user__email='confirm_sans_halaka@zidni.test')
        contenu = reponse.content.decode()
        self.assertIn('إضافة الطالب إلى مجموعة', contenu)
        self.assertIn(
            reverse('admin_eleve_detail', args=[eleve.id]) + '#groupes-suggeres', contenu
        )

    def test_confirmation_rattachement_auto_propose_de_changer_de_groupe(self):
        inscription = _creer_inscription_eleve(
            email='confirm_halaka_ok@zidni.test', date_naissance=datetime.date(2000, 1, 1),
            groupe_choisi=self.groupe,
        )
        reponse = self.client.get(reverse('admin_valider_eleve', args=[inscription.id]), follow=True)
        contenu = reponse.content.decode()
        self.assertIn('تغيير المجموعة', contenu)
        # « تغيير المجموعة » mène à la fiche de la halaka où l'élève vient
        # d'être rattaché, pas à la fiche élève.
        self.assertIn(reverse('admin_groupe_detail', args=[self.groupe.id]), contenu)
        self.assertNotIn('إضافة الطالب إلى مجموعة', contenu)

    def test_confirmation_choix_invalide_propose_un_bouton_vers_la_fiche_eleve(self):
        self.groupe.capacite_max = 0
        self.groupe.save()
        inscription = _creer_inscription_eleve(
            email='confirm_halaka_ko@zidni.test', date_naissance=datetime.date(2000, 1, 1),
            groupe_choisi=self.groupe,
        )
        reponse = self.client.get(reverse('admin_valider_eleve', args=[inscription.id]), follow=True)
        eleve = Eleve.objects.get(user__email='confirm_halaka_ko@zidni.test')
        contenu = reponse.content.decode()
        self.assertIn('إضافة الطالب إلى مجموعة', contenu)
        self.assertIn(
            reverse('admin_eleve_detail', args=[eleve.id]) + '#groupes-suggeres', contenu
        )

    def test_confirmation_bloc_groupe_traduit_reellement_en_fr_et_en(self):
        """Même piège que RenduReelFrEnTemplatesAdminTests : les nouveaux msgids
        du bloc « المجموعة » doivent être dans locale/*.mo, pas seulement
        balisés {% trans %}/{% blocktrans %}."""
        for langue, attendu in (('fr', "Ajouter l'élève à un groupe"),
                                ('en', 'Add the student to a group')):
            inscription = _creer_inscription_eleve(
                email=f'confirm_i18n_{langue}@zidni.test', date_naissance=datetime.date(2000, 1, 1),
            )
            self.client.post(reverse('set_language'), {'language': langue, 'next': '/'})
            contenu = self.client.get(
                reverse('admin_valider_eleve', args=[inscription.id]), follow=True
            ).content.decode()
            self.assertIn(attendu, contenu)
            self.assertNotIn('إضافة الطالب إلى مجموعة', contenu)


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
            # nom_parent devenu obligatoire pour un mineur depuis le partage de
            # la règle wizard_identite/inscrire_eleve (commit du 2026-08-28,
            # appliquer_regle_nom_parent) — cette fixture représente une
            # candidate mineure (2010), jamais fourni avant ce correctif car
            # inscrire_eleve() ne l'exigeait pas encore réellement à l'époque.
            'nom_parent': 'فاطمة الإدريسي',
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

    def test_prix_individuel_configure_sur_la_page_fusionnee_saffiche_cote_ajout_manuel(self):
        """Correction du 2026-08-22 (grille de prix incohérente/incomplète,
        étape D) : reproduit le scénario signalé (Individuel + 4 séances/
        semaine) en passant RÉELLEMENT par la page fusionnée admin_
        abonnement_modifier (jamais un objects.create() direct sur
        GrillePrixAbonnement ici) — preuve bout en bout que le مدير peut
        désormais configurer un nombre de séances jamais présent dans un
        vrai groupe, et que admin_eleve_ajouter_manuel le reflète aussitôt
        via la même abonnements_avec_prix_effectif() que le wizard public."""
        from courses.models import OptionNbSeances
        from inscriptions.models import TypeAbonnement

        # Chantier "cases nb_slots configurables" du 2026-08-27 (Besoin 1.5) :
        # admin_abonnement_modifier ne lit/n'enregistre plus prix_4/actif_4 que
        # si "4" existe dans le catalogue OptionNbSeances actif (plage_nb_
        # slots_grille_prix, plus une plage fixe 1..10) — jamais seedé par
        # défaut (seed migration = 1/2/3 seulement), donc créé ici explicitement.
        OptionNbSeances.objects.get_or_create(valeur=4)

        abo_individuel = TypeAbonnement.objects.create(
            code='test_ajout_manuel_abo_indiv', label='فردي شهري', prix=400,
            type_offre='individuel', cible_age='les_deux', ordre=2,
        )
        client = self._connecte_admin()
        client.post(reverse('admin_abonnement_modifier', args=[abo_individuel.id]), {
            'label': abo_individuel.label, 'prix': str(abo_individuel.prix), 'cible_age': 'les_deux', 'ordre': '2',
            'prix_4': '777', 'actif_4': 'on',
        })

        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), {
            **self._round1_donnees('prix_individuel_4_ajout_manuel@zidni.test'),
            f'champ_{self.champ_type_offre.id}': 'individuel',
            f'champ_{self.champ_nb_seances.id}': '4',
        })
        abonnements = {a.code: a for a in reponse.context['abonnements']}
        self.assertEqual(abonnements[abo_individuel.code].prix_affiche, 777)

    def test_affichage_abonnement_montre_uniquement_la_duree(self):
        """Correction 5 (2026-08-22) : même simplification que le wizard
        public (type d'offre déjà choisi 2 étapes plus tôt) — vérifie que la
        duplication n'existe plus ici non plus."""
        self.abo_groupe.duree = 'شهر'
        self.abo_groupe.save()
        client = self._connecte_admin()
        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees('duree_ajout_manuel@zidni.test'))
        html = reponse.content.decode('utf-8')
        self.assertIn('شهر', html)
        self.assertNotIn('جماعي شهري', html)

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

    def test_continuer_sans_groupe_reussit_et_enregistre_une_demande(self):
        """Chantier du 2026-08-22 : nombre de séances libre (77, jamais réel)
        -> aucune des 2 groupes seedées (self.groupe_hafs/warsh, nb_slots=2)
        ne correspond exactement -> l'admin doit pouvoir continuer sans
        groupe, avec traçabilité (DemandeNonSatisfaite)."""
        from registration.models import DemandeNonSatisfaite

        client = self._connecte_admin()
        donnees_round1 = {
            'round_form': 'identite',
            'nom': 'سلمى الإدريسي', 'sexe': 'femme', 'email': 'sans_groupe_manuel@zidni.test',
            'date_naissance': '2010-01-01', 'nom_parent': 'فاطمة الإدريسي',
            'indicatif_pays': '212', 'telephone': '0611229900', 'telephone_confirmation': '0611229900',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '77',
        }
        reponse_round2 = client.post(reverse('admin_eleve_ajouter_manuel'), donnees_round1)
        html = reponse_round2.content.decode('utf-8')
        self.assertIn('لا توجد حالياً أي مجموعة تتوافق تماماً', html)

        reponse_finale = client.post(reverse('admin_eleve_ajouter_manuel'), {
            **donnees_round1, 'round_form': 'confirmation',
            'continuer_sans_groupe': '1', 'abonnement_code': self.abo_groupe.code,
        })
        inscription = InscriptionEleve.objects.get(email='sans_groupe_manuel@zidni.test')
        self.assertRedirects(reponse_finale, reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        self.assertIsNone(inscription.groupe_choisi)
        demande = DemandeNonSatisfaite.objects.get()
        self.assertEqual(demande.inscription_id, inscription.id)
        self.assertEqual(demande.nb_slots, 77)

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
        client_wizard.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})  # Étape -1, restaurée le 2026-08-22
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


class AjoutManuelProfTests(TestCase):
    """Chantier du 2026-08-27 — admin_prof_ajouter_manuel : ajout manuel d'une
    InscriptionProf par مدير/مشرف, statut initial selon le rôle du créateur
    (seule différence avec une candidature publique — voir docstring de la vue)."""

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

    def _donnees(self, email):
        return {
            'nom': 'أستاذ', 'prenom': 'يدوي', 'date_naissance': '1990-05-05',
            'indicatif_pays': '212', 'telephone': '0611002233', 'telephone_confirmation': '0611002233',
            'email': email, 'ville': 'فاس', 'statut_familial': 'celibataire',
            'job_actuel': 'مهندس', 'niveau_memorisation': 'كامل',
            'parcours_scolaire': 'باكالوريا علوم', 'parcours_enseignant': '5 سنوات تدريس',
            'compte_bancaire': '1234567890', 'rib': 'RIB123', 'agence_bancaire': 'الوكالة المركزية',
        }

    def test_admin_cree_candidature_avec_statut_validee_directeur_sans_creer_de_compte(self):
        client = self._connecte_admin()
        response = client.post(reverse('admin_prof_ajouter_manuel'), self._donnees('prof_manuel_admin@zidni.test'))
        inscription = InscriptionProf.objects.get(email='prof_manuel_admin@zidni.test')
        self.assertEqual(inscription.statut, 'validee_directeur')
        self.assertFalse(User.objects.filter(email='prof_manuel_admin@zidni.test').exists())
        self.assertRedirects(response, reverse('admin_inscription_prof_detail', args=[inscription.id]))

        # Visible pour مشرف comme n'importe quelle candidature classique — même
        # liste que celle alimentée par admin_valider_prof (workflow public).
        client_mshrif = self._connecte_mshrif()
        html = client_mshrif.get(reverse('mshrif_inscriptions_profs')).content.decode('utf-8')
        self.assertIn('أستاذ يدوي', html)

    def test_mshrif_cree_le_compte_immediatement_sans_attente(self):
        client = self._connecte_mshrif()
        client.post(reverse('admin_prof_ajouter_manuel'), self._donnees('prof_manuel_mshrif@zidni.test'))
        inscription = InscriptionProf.objects.get(email='prof_manuel_mshrif@zidni.test')
        self.assertEqual(inscription.statut, 'valide')

        prof = Prof.objects.get(user__email='prof_manuel_mshrif@zidni.test')
        self.assertEqual(prof.ville, 'فاس')
        self.assertTrue(User.objects.filter(email='prof_manuel_mshrif@zidni.test', role='prof').exists())
        # Présentation publique générée automatiquement — même point de
        # création que mshrif_valider_prof_final (_creer_compte_prof, partagée).
        self.assertIn('كامل', prof.presentation_publique)

    def test_eleve_ne_peut_pas_acceder_a_la_page(self):
        eleve = _creer_eleve('eleve_ajout_manuel_prof@zidni.test')
        client = Client()
        client.force_login(eleve.user)
        response = client.get(reverse('admin_prof_ajouter_manuel'))
        self.assertNotEqual(response.status_code, 200)

    def test_email_deja_utilise_est_refuse(self):
        _creer_inscription_prof(email='prof_manuel_conflit@zidni.test')
        client = self._connecte_admin()
        client.post(reverse('admin_prof_ajouter_manuel'), self._donnees('prof_manuel_conflit@zidni.test'))
        self.assertEqual(InscriptionProf.objects.filter(email='prof_manuel_conflit@zidni.test').count(), 1)

    # ========================================================================
    # Chantier du 2026-08-27 ("tout optionnel sauf le strict indispensable") —
    # seuls nom/prenom/email/telephone restent obligatoires ici.
    # ========================================================================
    def _donnees_minimales(self, email):
        """Uniquement nom/prenom/email/telephone — AUCUN autre champ, preuve
        que le formulaire accepte désormais un dossier volontairement
        incomplet plutôt que de forcer sa saisie intégrale au premier passage."""
        return {
            'nom': 'أستاذ', 'prenom': 'ناقص',
            'indicatif_pays': '212', 'telephone': '0611002244', 'telephone_confirmation': '0611002244',
            'email': email,
        }

    def test_creation_reussit_avec_uniquement_les_champs_indispensables(self):
        client = self._connecte_admin()
        response = client.post(reverse('admin_prof_ajouter_manuel'), self._donnees_minimales('prof_manuel_minimal@zidni.test'))
        inscription = InscriptionProf.objects.get(email='prof_manuel_minimal@zidni.test')
        self.assertEqual(inscription.statut, 'validee_directeur')
        self.assertIsNone(inscription.date_naissance)
        self.assertEqual(inscription.ville, '')
        self.assertEqual(inscription.job_actuel, '')
        self.assertEqual(inscription.niveau_memorisation, '')
        self.assertEqual(inscription.parcours_scolaire, '')
        self.assertEqual(inscription.parcours_enseignant, '')
        self.assertEqual(inscription.compte_bancaire, '')
        self.assertEqual(inscription.rib, '')
        self.assertEqual(inscription.agence_bancaire, '')
        self.assertRedirects(response, reverse('admin_inscription_prof_detail', args=[inscription.id]))

    def test_mshrif_cree_le_compte_meme_avec_dossier_minimal(self):
        """Preuve bout en bout : _creer_compte_prof (User+Prof) ne plante
        jamais sur des champs optionnels vides, y compris la génération de
        presentation_publique (accounts.services.generer_presentation_publique,
        déjà conçue pour ignorer les champs vides)."""
        client = self._connecte_mshrif()
        client.post(reverse('admin_prof_ajouter_manuel'), self._donnees_minimales('prof_manuel_minimal_mshrif@zidni.test'))
        prof = Prof.objects.get(user__email='prof_manuel_minimal_mshrif@zidni.test')
        self.assertEqual(prof.ville, '')
        self.assertEqual(prof.presentation_publique, '')
        self.assertTrue(User.objects.filter(email='prof_manuel_minimal_mshrif@zidni.test', role='prof').exists())

    def test_nom_manquant_toujours_refuse(self):
        client = self._connecte_admin()
        donnees = self._donnees_minimales('prof_manuel_sans_nom@zidni.test')
        donnees['nom'] = ''
        client.post(reverse('admin_prof_ajouter_manuel'), donnees)
        self.assertFalse(InscriptionProf.objects.filter(email='prof_manuel_sans_nom@zidni.test').exists())

    def test_email_manquant_toujours_refuse(self):
        client = self._connecte_admin()
        donnees = self._donnees_minimales('prof_manuel_sans_email@zidni.test')
        donnees['email'] = ''
        reponse = client.post(reverse('admin_prof_ajouter_manuel'), donnees)
        self.assertEqual(reponse.status_code, 200)  # réaffiche le formulaire, ne redirige jamais
        self.assertFalse(InscriptionProf.objects.filter(nom='أستاذ', prenom='ناقص').exists())

    def test_telephone_manquant_toujours_refuse(self):
        client = self._connecte_admin()
        donnees = self._donnees_minimales('prof_manuel_sans_tel@zidni.test')
        donnees['telephone'] = ''
        donnees['telephone_confirmation'] = ''
        client.post(reverse('admin_prof_ajouter_manuel'), donnees)
        self.assertFalse(InscriptionProf.objects.filter(email='prof_manuel_sans_tel@zidni.test').exists())

    def test_date_naissance_saisie_mais_invalide_refusee(self):
        """Contrairement à une date LAISSÉE VIDE (acceptée), une date SAISIE
        mais mal formée reste une vraie erreur — jamais enregistrée comme si
        de rien n'était."""
        client = self._connecte_admin()
        donnees = self._donnees_minimales('prof_manuel_date_invalide@zidni.test')
        donnees['date_naissance'] = 'pas-une-date'
        client.post(reverse('admin_prof_ajouter_manuel'), donnees)
        self.assertFalse(InscriptionProf.objects.filter(email='prof_manuel_date_invalide@zidni.test').exists())


class PresentationPubliqueProfTests(TestCase):
    """Chantier du 2026-08-27 — génération automatique + édition manuelle de
    Prof.presentation_publique (accounts.services.generer_presentation_publique)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def test_generee_automatiquement_a_la_validation_finale_classique(self):
        client_admin = Client()
        client_admin.force_login(self.admin)
        inscription = _creer_inscription_prof(
            email='prof_presentation_auto@zidni.test', niveau_memorisation='حفظ كامل مجود',
        )
        client_admin.get(reverse('admin_valider_prof', args=[inscription.id]))

        client_mshrif = Client()
        client_mshrif.force_login(self.mshrif)
        client_mshrif.get(reverse('mshrif_valider_prof_final', args=[inscription.id]))

        prof = Prof.objects.get(user__email='prof_presentation_auto@zidni.test')
        self.assertIn('حفظ كامل مجود', prof.presentation_publique)

    def test_modifiable_ensuite_par_admin_et_jamais_ecrasee_automatiquement(self):
        prof = _creer_prof('prof_presentation_modif@zidni.test')
        prof.presentation_publique = 'نبذة أصلية مولدة'
        prof.save(update_fields=['presentation_publique'])

        client = Client()
        client.force_login(self.admin)
        response = client.post(
            reverse('admin_prof_presentation_modifier', args=[prof.id]),
            {'presentation_publique': 'نبذة معدَّلة يدوياً من طرف المدير'},
        )
        self.assertRedirects(response, reverse('admin_prof_detail', args=[prof.id]))
        prof.refresh_from_db()
        self.assertEqual(prof.presentation_publique, 'نبذة معدَّلة يدوياً من طرف المدير')

    def test_mshrif_peut_aussi_modifier(self):
        prof = _creer_prof('prof_presentation_mshrif@zidni.test')
        client = Client()
        client.force_login(self.mshrif)
        response = client.post(
            reverse('admin_prof_presentation_modifier', args=[prof.id]),
            {'presentation_publique': 'نبذة معدَّلة من المشرف'},
        )
        self.assertRedirects(response, reverse('admin_prof_detail', args=[prof.id]))
        prof.refresh_from_db()
        self.assertEqual(prof.presentation_publique, 'نبذة معدَّلة من المشرف')

    def test_reglage_ajoute_sur_la_page_admin_visibilite_prof(self):
        client = Client()
        client.force_login(self.admin)
        html = client.get(reverse('admin_visibilite_prof')).content.decode('utf-8')
        self.assertIn('afficher_presentation_wizard', html)


class GroupeCacheDuWizardPublicCoteAdminTests(TestCase):
    """Chantier du 2026-08-23 ("exclusion manuelle d'un groupe") — côté
    admin_eleve_ajouter_manuel UNIQUEMENT : un groupe cache_du_wizard_
    public=True doit rester normalement affiché et sélectionnable ici,
    jamais affecté par ce masquage (réservé au formulaire public, voir
    registration.tests.GroupeCacheDuWizardPublicTests pour le pendant
    public)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.critere_programme = CritereInscription.objects.get(code='programme')
        self.critere_riwaya = CritereInscription.objects.get(code='riwaya')
        self.critere_type_offre = CritereInscription.objects.get(code='type_offre')
        self.critere_nb_seances = CritereInscription.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        self.creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(self.creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe_cache = Groupe.objects.create(
            nom='مجموعة مخفية عن الاستمارة العامة', creneau=self.creneau, statut='actif',
            type_capacite='groupe', capacite_max=10, cache_du_wizard_public=True,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe_cache, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe_cache, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        from inscriptions.models import TypeAbonnement
        self.abonnement = TypeAbonnement.objects.create(
            code='test_cache_wizard_abo', label='جماعي شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1,
        )

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _round1_donnees(self, email):
        return {
            'round_form': 'identite',
            'nom': 'تلميذ اختبار الإخفاء', 'sexe': 'homme', 'email': email,
            # nom_parent obligatoire pour un mineur depuis appliquer_regle_nom_parent
            # (commit du 2026-08-28) -- cette fixture représente un candidat
            # mineur (2010), voir le même correctif dans AjoutManuelEleveTests.
            'date_naissance': '2010-01-01', 'nom_parent': 'ولي أمر اختبار الإخفاء',
            'indicatif_pays': '212', 'telephone': '0611223344', 'telephone_confirmation': '0611223344',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        }

    def test_groupe_cache_apparait_dans_la_liste_de_selection_admin(self):
        client = self._connecte_admin()
        reponse = client.post(
            reverse('admin_eleve_ajouter_manuel'),
            self._round1_donnees('cache_visible_admin@zidni.test'),
        )
        self.assertEqual(reponse.status_code, 200)
        ids_proposes = set(reponse.context['groupes'].values_list('id', flat=True))
        self.assertIn(self.groupe_cache.id, ids_proposes)
        self.assertIn('مجموعة مخفية عن الاستمارة العامة', reponse.content.decode('utf-8'))

    def test_groupe_cache_reste_choisissable_pour_creer_reellement_linscription(self):
        client = self._connecte_admin()
        client.post(reverse('admin_eleve_ajouter_manuel'), self._round1_donnees('cache_choisi_admin@zidni.test'))
        reponse = client.post(reverse('admin_eleve_ajouter_manuel'), {
            'round_form': 'confirmation',
            'nom': 'تلميذ اختبار الإخفاء', 'sexe': 'homme', 'email': 'cache_choisi_admin@zidni.test',
            'date_naissance': '2010-01-01', 'nom_parent': 'ولي أمر اختبار الإخفاء',
            'indicatif_pays': '212', 'telephone': '0611223344', 'telephone_confirmation': '0611223344',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
            'groupe_id': str(self.groupe_cache.id),
            'abonnement_code': self.abonnement.code,
        })
        self.assertRedirects(
            reponse, reverse('admin_inscription_eleve_detail', args=[InscriptionEleve.objects.get(email='cache_choisi_admin@zidni.test').id]),
        )
        inscription = InscriptionEleve.objects.get(email='cache_choisi_admin@zidni.test')
        self.assertEqual(inscription.groupe_choisi_id, self.groupe_cache.id)


class AdminParametresAbonnementsTests(TestCase):
    """Correction 5 (2026-08-22, suite au test local) : la liste sépare
    désormais Groupe/Individuel en 2 sections claires, au lieu d'une seule
    liste plate mélangeant les deux."""

    def setUp(self):
        from inscriptions.models import TypeAbonnement

        self.admin = _creer_admin()
        self.prof = _creer_prof()
        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_section_groupe', label='شهر تجريبي', prix=80, type_offre='groupe',
        )
        self.abo_individuel = TypeAbonnement.objects.create(
            code='test_section_individuel', label='شهر تجريبي فردي', prix=400, type_offre='individuel',
        )

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_role_required_refuse_un_prof(self):
        client = Client()
        client.force_login(self.prof.user)
        reponse = client.get(reverse('admin_parametres_abonnements'))
        self.assertEqual(reponse.status_code, 302)

    def test_2_sections_separent_groupe_et_individuel(self):
        client = self._connecte_admin()
        html = client.get(reverse('admin_parametres_abonnements')).content.decode('utf-8')
        self.assertIn('اشتراكات جماعية', html)
        self.assertIn('اشتراكات فردية', html)
        # Chaque abonnement apparaît, et une SEULE fois (pas dans les 2 sections).
        self.assertEqual(html.count('شهر تجريبي فردي'), 1)
        # L'abonnement groupe apparaît dans la section جماعية AVANT فردية.
        position_section_groupe = html.index('اشتراكات جماعية')
        position_section_individuelle = html.index('اشتراكات فردية')
        position_abo_groupe = html.index('test_section_groupe')
        position_abo_individuel = html.index('test_section_individuel')
        self.assertTrue(position_section_groupe < position_abo_groupe < position_section_individuelle)
        self.assertTrue(position_section_individuelle < position_abo_individuel)

    def test_section_vide_affiche_message_dedie(self):
        from inscriptions.models import TypeAbonnement
        TypeAbonnement.objects.filter(type_offre='individuel').delete()

        client = self._connecte_admin()
        html = client.get(reverse('admin_parametres_abonnements')).content.decode('utf-8')
        self.assertIn('لا توجد أنواع اشتراك من هذا النوع بعد', html)


class AdminParametresAbonnementsArchivageTests(TestCase):
    """Fonctionnalité 1 (2026-08-27) : les abonnements archivés
    (TypeAbonnement.est_actif=False) sont séparés visuellement des actifs,
    dans une section repliée par défaut — jamais mélangés à la liste active,
    jamais non plus supprimés/masqués (consultables pour l'historique)."""

    def setUp(self):
        from inscriptions.models import TypeAbonnement

        self.admin = _creer_admin()
        self.abo_actif = TypeAbonnement.objects.create(
            code='test_archivage_actif', label='مشترك نشط', prix=80, type_offre='groupe', est_actif=True,
        )
        self.abo_archive = TypeAbonnement.objects.create(
            code='test_archivage_archive', label='مشترك مؤرشف', prix=80, type_offre='groupe', est_actif=False,
        )

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_archive_apparait_dans_section_dediee_avec_badge(self):
        client = self._connecte_admin()
        html = client.get(reverse('admin_parametres_abonnements')).content.decode('utf-8')
        self.assertIn('مشترك نشط', html)
        self.assertIn('مشترك مؤرشف', html)
        self.assertIn('مؤرشف 🗄', html)
        # La section archives (repliée par JS, display:none par défaut) contient
        # bien l'abonnement archivé — pas juste un badge affiché ailleurs.
        self.assertIn('archives_extra_groupe', html)
        position_archives_extra = html.index('id="archives_extra_groupe"')
        position_abo_archive = html.index('مشترك مؤرشف')
        self.assertTrue(position_archives_extra < position_abo_archive)

    def test_actif_naffiche_pas_le_badge_archive(self):
        client = self._connecte_admin()
        html = client.get(reverse('admin_parametres_abonnements')).content.decode('utf-8')
        # Le bloc de la ligne active de l'abonnement actif ne doit pas contenir
        # le badge "مؤرشف" (mais bien "نشط").
        bloc_actif = html[html.index('مشترك نشط'):html.index('مشترك نشط') + 800]
        self.assertIn('نشط ✅', bloc_actif)
        self.assertNotIn('مؤرشف', bloc_actif)

    def test_toggle_archive_un_abonnement_actif(self):
        from inscriptions.models import TypeAbonnement

        client = self._connecte_admin()
        reponse = client.get(reverse('admin_abonnement_toggle', args=[self.abo_actif.id]), follow=True)
        self.abo_actif.refresh_from_db()
        self.assertFalse(self.abo_actif.est_actif)
        self.assertContains(reponse, 'تم أرشفة نوع الاشتراك')

    def test_toggle_reactive_un_abonnement_archive(self):
        client = self._connecte_admin()
        reponse = client.get(reverse('admin_abonnement_toggle', args=[self.abo_archive.id]), follow=True)
        self.abo_archive.refresh_from_db()
        self.assertTrue(self.abo_archive.est_actif)
        self.assertContains(reponse, 'تم إعادة تفعيل نوع الاشتراك')


# ============================================================================
# Correction du 2026-08-22 (chantier grille de prix incohérente/incomplète) :
# admin_abonnement_modifier fusionne désormais les infos générales du
# TypeAbonnement ET sa grille de prix (auparavant 2 pages séparées :
# admin_abonnement_modifier + admin_abonnement_grille_prix). La grille
# propose systématiquement 1..10 séances/semaine, plus jamais limitée aux
# nb_slots de vrais groupes existants (bug corrigé : impossible auparavant
# de tarifer un nombre de séances jamais demandé par un vrai groupe, alors
# que l'Individuel n'a besoin d'AUCUN groupe réel, chantier "liberté totale
# du nombre de séances").
# ============================================================================
class AdminAbonnementModifierTests(TestCase):
    def setUp(self):
        from courses.models import OptionNbSeances
        from inscriptions.models import TypeAbonnement

        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.prof = _creer_prof()
        self.abonnement = TypeAbonnement.objects.create(
            code='test_grille_prix_abo', label='شهري تجريبي', prix=80, type_offre='groupe', cible_age='les_deux',
        )
        # Chantier "cases nb_slots configurables" du 2026-08-27 (Besoin 1.5) :
        # plage_nb_slots_grille_prix() lit désormais courses.models.
        # OptionNbSeances (catalogue configurable) au lieu d'une plage fixe
        # 1..10 codée en dur — cases 1..10 recréées explicitement ici pour
        # que les assertions historiques de cette classe (écrites pour
        # l'ancienne plage fixe) restent valables telles quelles. Repart
        # d'une table vide (la migration 0040_seed_nb_seances_et_tarifs_
        # remuneration seed déjà 1/2/3, sinon IntegrityError sur `valeur`).
        OptionNbSeances.objects.all().delete()
        OptionNbSeances.objects.bulk_create([OptionNbSeances(valeur=n) for n in range(1, 11)])
        # AUCUN vrai groupe créé ici, volontairement — preuve que la grille
        # (1..10) ne dépend plus d'aucun groupe réellement existant.
        self.nb_slots = 4

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_role_required_refuse_un_prof(self):
        client = Client()
        client.force_login(self.prof.user)
        reponse = client.get(reverse('admin_abonnement_modifier', args=[self.abonnement.id]))
        self.assertEqual(reponse.status_code, 302)

    def test_mshrif_peut_acceder(self):
        client = Client()
        client.force_login(self.mshrif)
        reponse = client.get(reverse('admin_abonnement_modifier', args=[self.abonnement.id]))
        self.assertEqual(reponse.status_code, 200)

    def test_get_affiche_les_infos_generales_et_aucune_ligne_vide(self):
        """Refonte du 2026-08-22 (correction 6) : plus de 10 lignes fixes à
        cases vides ambiguës — SEULES les lignes déjà configurées
        s'affichent (ici aucune), "+ إضافة" propose les 10 nombres de
        séances possibles, aucun n'étant encore configuré."""
        client = self._connecte_admin()
        html = client.get(reverse('admin_abonnement_modifier', args=[self.abonnement.id])).content.decode('utf-8')
        self.assertIn('name="label"', html)
        self.assertIn('name="duree"', html)
        self.assertIn('name="cible_age"', html)
        for n in range(1, 11):
            self.assertNotIn(f'name="prix_{n}"', html)
        self.assertIn('لا يوجد أي سعر خاص محدد بعد', html)
        self.assertIn('+ إضافة سعر لعدد حصص', html)
        for n in range(1, 11):
            self.assertIn(f'<option value="{n}">', html)

    def test_get_affiche_uniquement_les_lignes_deja_configurees(self):
        """Preuve du bug corrigé à l'origine (4 séances/semaine tarifable
        sans qu'aucun groupe réel n'ait jamais eu 4 créneaux) : cette ligne
        s'affiche bien, éditable — mais les 9 autres nombres, non
        configurés, ne créent AUCUNE case vide, seulement une option
        disponible dans "+ إضافة"."""
        from inscriptions.models import GrillePrixAbonnement

        GrillePrixAbonnement.objects.create(type_abonnement=self.abonnement, nb_slots=self.nb_slots, prix=300)
        client = self._connecte_admin()
        html = client.get(reverse('admin_abonnement_modifier', args=[self.abonnement.id])).content.decode('utf-8')
        self.assertIn(f'name="prix_{self.nb_slots}"', html)
        self.assertNotIn('لا يوجد أي سعر خاص محدد بعد', html)
        for n in range(1, 11):
            if n == self.nb_slots:
                continue
            self.assertNotIn(f'name="prix_{n}"', html)
            self.assertIn(f'<option value="{n}">', html)
        self.assertNotIn(f'<option value="{self.nb_slots}">', html)  # déjà configuré -> plus proposé à l'ajout

    def test_post_met_a_jour_les_infos_generales_et_cree_une_ligne_de_grille(self):
        from inscriptions.models import GrillePrixAbonnement, TypeAbonnement

        client = self._connecte_admin()
        client.post(reverse('admin_abonnement_modifier', args=[self.abonnement.id]), {
            'label': 'شهري معدّل', 'duree': 'شهر', 'prix': '90', 'cible_age': 'adulte', 'ordre': '2',
            f'prix_{self.nb_slots}': '999', f'actif_{self.nb_slots}': 'on',
        })
        self.abonnement.refresh_from_db()
        self.assertEqual(self.abonnement.label, 'شهري معدّل')
        self.assertEqual(self.abonnement.duree, 'شهر')
        self.assertEqual(self.abonnement.prix, 90)
        self.assertEqual(self.abonnement.cible_age, 'adulte')

        ligne = GrillePrixAbonnement.objects.get(type_abonnement=self.abonnement, nb_slots=self.nb_slots)
        self.assertEqual(ligne.prix, 999)
        self.assertTrue(ligne.est_actif)

        # Re-soumission SANS la case "نشط" cochée (jamais envoyée par un
        # navigateur pour une checkbox décochée) -> désactive la ligne sans
        # la supprimer, prix mis à jour dans le même passage.
        client.post(reverse('admin_abonnement_modifier', args=[self.abonnement.id]), {
            'label': 'شهري معدّل', 'prix': '90', 'cible_age': 'adulte', 'ordre': '2',
            f'prix_{self.nb_slots}': '500',
        })
        ligne.refresh_from_db()
        self.assertEqual(ligne.prix, 500)
        self.assertFalse(ligne.est_actif)

    def test_post_champ_vide_supprime_la_ligne_existante(self):
        from inscriptions.models import GrillePrixAbonnement

        GrillePrixAbonnement.objects.create(type_abonnement=self.abonnement, nb_slots=self.nb_slots, prix=200)
        client = self._connecte_admin()
        client.post(reverse('admin_abonnement_modifier', args=[self.abonnement.id]), {
            'label': self.abonnement.label, 'prix': str(self.abonnement.prix), 'cible_age': 'les_deux', 'ordre': '0',
            f'prix_{self.nb_slots}': '',
        })
        self.assertFalse(
            GrillePrixAbonnement.objects.filter(type_abonnement=self.abonnement, nb_slots=self.nb_slots).exists()
        )

    def test_warning_configures_zero_puis_partiellement_couvert_apres_ajout(self):
        client = self._connecte_admin()
        html_avant = client.get(reverse('admin_abonnement_modifier', args=[self.abonnement.id])).content.decode('utf-8')
        self.assertIn('لم يُحدد أي سعر خاص بعد', html_avant)

        client.post(reverse('admin_abonnement_modifier', args=[self.abonnement.id]), {
            'label': self.abonnement.label, 'prix': str(self.abonnement.prix), 'cible_age': 'les_deux', 'ordre': '0',
            f'prix_{self.nb_slots}': '999', f'actif_{self.nb_slots}': 'on',
        })
        html_apres = client.get(reverse('admin_abonnement_modifier', args=[self.abonnement.id])).content.decode('utf-8')
        # 1 seule ligne configurée sur 10 -> "partiellement couvert", jamais
        # "entièrement couvert" ni "aucun sécifié" (les 2 autres messages).
        self.assertNotIn('لم يُحدد أي سعر خاص بعد', html_apres)
        self.assertIn('1 من أصل 10', html_apres)

    def test_ancienne_route_grille_prix_redirige_vers_la_page_fusionnee(self):
        """La route dédiée n'existe plus mais reste en redirection simple
        (jamais un 404) pour tout ancien favori/lien déjà enregistré."""
        client = self._connecte_admin()
        reponse = client.get(reverse('admin_abonnement_grille_prix', args=[self.abonnement.id]))
        self.assertRedirects(reponse, reverse('admin_abonnement_modifier', args=[self.abonnement.id]))


# ============================================================================
# Chantier "cases nb_slots configurables" du 2026-08-27 (Besoin 1.5) —
# catalogue partagé courses.models.OptionNbSeances.
# ============================================================================
class AdminOptionsNbSeancesTests(TestCase):
    def setUp(self):
        from courses.models import OptionNbSeances

        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.prof = _creer_prof()
        OptionNbSeances.objects.all().delete()
        self.option_1 = OptionNbSeances.objects.create(valeur=1)

    def test_role_required_refuse_un_prof(self):
        client = Client()
        client.force_login(self.prof.user)
        reponse = client.get(reverse('admin_options_nb_seances'))
        self.assertEqual(reponse.status_code, 302)

    def test_mshrif_peut_ajouter_une_case(self):
        """Besoin 1.5 explicite : "le directeur OU le مشرف" peut ajouter
        une case — pas réservé au مدير seul, contrairement aux tarifs."""
        from courses.models import OptionNbSeances

        client = Client()
        client.force_login(self.mshrif)
        client.post(reverse('admin_option_nb_seances_ajouter'), {'valeur': '4'})
        self.assertTrue(OptionNbSeances.objects.filter(valeur=4).exists())

    def test_ajout_valeur_dupliquee_refuse(self):
        from courses.models import OptionNbSeances

        client = Client()
        client.force_login(self.admin)
        client.post(reverse('admin_option_nb_seances_ajouter'), {'valeur': '1'})
        self.assertEqual(OptionNbSeances.objects.filter(valeur=1).count(), 1)

    def test_ajout_valeur_non_numerique_refuse(self):
        client = Client()
        client.force_login(self.admin)
        reponse = client.post(reverse('admin_option_nb_seances_ajouter'), {'valeur': 'abc'}, follow=True)
        self.assertContains(reponse, 'رقماً صحيحاً')

    def test_toggle_desactive_puis_reactive(self):
        client = Client()
        client.force_login(self.admin)
        client.get(reverse('admin_option_nb_seances_toggle', args=[self.option_1.id]))
        self.option_1.refresh_from_db()
        self.assertFalse(self.option_1.est_actif)
        client.get(reverse('admin_option_nb_seances_toggle', args=[self.option_1.id]))
        self.option_1.refresh_from_db()
        self.assertTrue(self.option_1.est_actif)

    def test_case_desactivee_disparait_de_la_plage_grille_prix(self):
        """Preuve d'intégration avec registration.utils.plage_nb_slots_grille_prix
        (source désormais dynamique, voir son docstring) — pas juste un
        test isolé du modèle."""
        from registration.utils import plage_nb_slots_grille_prix

        self.assertIn(1, plage_nb_slots_grille_prix())
        self.option_1.est_actif = False
        self.option_1.save()
        self.assertNotIn(1, plage_nb_slots_grille_prix())


class AdminTarifsRemunerationRefonteTests(TestCase):
    """Refonte du 2026-08-27 (Besoin 3) — remplace l'ancienne page 4-lignes
    (courses.models.TarifRemuneration, dépréciée) par 2 grilles distinctes."""

    def setUp(self):
        from courses.models import OptionNbSeances, TarifRemunerationGroupe, TarifRemunerationIndividuel

        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.prof = _creer_prof()
        OptionNbSeances.objects.all().delete()
        TarifRemunerationGroupe.objects.all().delete()
        self.option_2 = OptionNbSeances.objects.create(valeur=2)
        self.tarif_groupe = TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=2, montant=60)
        self.tarif_individuel = TarifRemunerationIndividuel.objects.filter(tranche_age='adulte').first()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_role_required_refuse_un_prof(self):
        client = Client()
        client.force_login(self.prof.user)
        reponse = client.get(reverse('admin_tarifs_remuneration'))
        self.assertEqual(reponse.status_code, 302)

    def test_mshrif_redirige_vers_mshrif_remuneration(self):
        client = Client()
        client.force_login(self.mshrif)
        reponse = client.get(reverse('admin_tarifs_remuneration'))
        self.assertRedirects(reponse, reverse('mshrif_remuneration'))

    def test_get_affiche_les_2_grilles(self):
        html = self._connecte_admin().get(reverse('admin_tarifs_remuneration')).content.decode('utf-8')
        self.assertIn('2 حصص/أسبوع', html)
        self.assertIn('60', html)
        self.assertIn('35', html)  # tarif individuel seedé

    def test_bandeau_combinaisons_manquantes_affiche(self):
        """Seule (adulte, 2) est configurée — (enfant, 2) doit apparaître
        dans le bandeau d'alerte persistant."""
        html = self._connecte_admin().get(reverse('admin_tarifs_remuneration')).content.decode('utf-8')
        self.assertIn('طفل', html)

    def test_ajouter_tarif_groupe_valide(self):
        from courses.models import TarifRemunerationGroupe

        self._connecte_admin().post(reverse('admin_tarif_remuneration_groupe_ajouter'), {
            'tranche_age': 'enfant', 'nb_slots': '2', 'montant': '90',
        })
        self.assertTrue(TarifRemunerationGroupe.objects.filter(tranche_age='enfant', nb_slots=2, montant=90).exists())

    def test_ajouter_tarif_groupe_nb_slots_hors_catalogue_refuse(self):
        """nb_slots=5 n'est PAS dans le catalogue OptionNbSeances actif
        (seul 2 existe ici) — revalidation serveur, jamais une confiance
        aveugle dans le POST."""
        from courses.models import TarifRemunerationGroupe

        self._connecte_admin().post(reverse('admin_tarif_remuneration_groupe_ajouter'), {
            'tranche_age': 'enfant', 'nb_slots': '5', 'montant': '90',
        })
        self.assertFalse(TarifRemunerationGroupe.objects.filter(nb_slots=5).exists())

    def test_modifier_tarif_groupe_montant_et_desactivation(self):
        client = self._connecte_admin()
        client.post(reverse('admin_tarif_remuneration_groupe_modifier', args=[self.tarif_groupe.id]), {
            'montant': '65',
        })
        self.tarif_groupe.refresh_from_db()
        self.assertEqual(self.tarif_groupe.montant, 65)
        self.assertFalse(self.tarif_groupe.est_actif)  # checkbox non cochée = décochée

    def test_modifier_tarif_individuel(self):
        client = self._connecte_admin()
        client.post(reverse('admin_tarif_remuneration_individuel_modifier', args=[self.tarif_individuel.id]), {
            'montant': '40',
        })
        self.tarif_individuel.refresh_from_db()
        self.assertEqual(self.tarif_individuel.montant, 40)

    def test_seules_admin_role_peut_modifier_pas_mshrif(self):
        client = Client()
        client.force_login(self.mshrif)
        reponse = client.get(reverse('admin_tarif_remuneration_groupe_modifier', args=[self.tarif_groupe.id]))
        self.assertEqual(reponse.status_code, 302)


class AdminAbonnementAjouterWizardTests(TestCase):
    """Flux multi-étapes (Besoin 1, Chantier du 2026-08-27)."""

    def setUp(self):
        from courses.models import OptionNbSeances

        self.admin = _creer_admin()
        self.prof = _creer_prof()
        OptionNbSeances.objects.all().delete()
        OptionNbSeances.objects.create(valeur=1)
        OptionNbSeances.objects.create(valeur=2)

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_get_affiche_les_5_etapes_avec_label_masque(self):
        """Besoin 1.3 : "الاسم المعروض" masqué (display:none) tant que le
        type n'est pas choisi — vérifiable server-side sur le HTML initial."""
        html = self._connecte_admin().get(reverse('admin_abonnement_ajouter')).content.decode('utf-8')
        self.assertIn('name="code"', html)
        self.assertIn('name="type_offre"', html)
        self.assertIn('id="step-label" style="display:none;"', html)
        self.assertIn('name="duree"', html)
        self.assertIn('1 حصص/أسبوع', html)
        self.assertIn('2 حصص/أسبوع', html)

    def test_post_cree_abonnement_et_grille_prix_en_une_transaction(self):
        from inscriptions.models import GrillePrixAbonnement, TypeAbonnement

        self._connecte_admin().post(reverse('admin_abonnement_ajouter'), {
            'code': 'test_wizard_abo', 'type_offre': 'groupe', 'label': 'اشتراك تجريبي',
            'duree': '1mois', 'prix_1': '70', 'prix_2': '100',
        })
        abonnement = TypeAbonnement.objects.get(code='test_wizard_abo')
        self.assertEqual(abonnement.label, 'اشتراك تجريبي')
        self.assertEqual(abonnement.duree, '1mois')
        self.assertEqual(abonnement.prix, 70)  # plus petit nb_slots reçu
        self.assertEqual(
            set(GrillePrixAbonnement.objects.filter(type_abonnement=abonnement).values_list('nb_slots', 'prix')),
            {(1, 70), (2, 100)},
        )

    def test_post_code_duplique_refuse(self):
        from inscriptions.models import TypeAbonnement

        TypeAbonnement.objects.create(code='test_wizard_doublon', label='x', prix=10, type_offre='groupe')
        reponse = self._connecte_admin().post(reverse('admin_abonnement_ajouter'), {
            'code': 'test_wizard_doublon', 'type_offre': 'groupe', 'label': 'y',
            'duree': '1mois', 'prix_1': '70',
        }, follow=True)
        self.assertContains(reponse, 'مستخدم مسبقاً')
        self.assertEqual(TypeAbonnement.objects.filter(code='test_wizard_doublon').count(), 1)

    def test_post_sans_aucun_prix_refuse(self):
        """Besoin 1.5 : "bloquant" — un abonnement ne peut pas être créé
        sans AU MOINS un prix pour un nombre de séances."""
        from inscriptions.models import TypeAbonnement

        self._connecte_admin().post(reverse('admin_abonnement_ajouter'), {
            'code': 'test_wizard_sans_prix', 'type_offre': 'groupe', 'label': 'y', 'duree': '1mois',
        })
        self.assertFalse(TypeAbonnement.objects.filter(code='test_wizard_sans_prix').exists())

    def test_post_type_offre_manquant_refuse(self):
        from inscriptions.models import TypeAbonnement

        self._connecte_admin().post(reverse('admin_abonnement_ajouter'), {
            'code': 'test_wizard_sans_type', 'label': 'y', 'duree': '1mois', 'prix_1': '70',
        })
        self.assertFalse(TypeAbonnement.objects.filter(code='test_wizard_sans_type').exists())

    def test_post_duree_invalide_refuse(self):
        from inscriptions.models import TypeAbonnement

        self._connecte_admin().post(reverse('admin_abonnement_ajouter'), {
            'code': 'test_wizard_duree_invalide', 'type_offre': 'groupe', 'label': 'y',
            'duree': 'texte_libre_non_autorise', 'prix_1': '70',
        })
        self.assertFalse(TypeAbonnement.objects.filter(code='test_wizard_duree_invalide').exists())


class AdminAbonnementAjouterCibleAgeEtOrdreTests(TestCase):
    """Fonctionnalité 2 (2026-08-27, cohérence formulaire ajout/modification) —
    bug constaté : la vue admin_abonnement_ajouter lisait déjà cible_age/ordre
    depuis le POST (donc admin_abonnement_modifier les gérait sans problème),
    mais le TEMPLATE de création n'avait jamais les champs correspondants —
    cible_age retombait donc TOUJOURS sur 'les_deux', ordre toujours sur 0,
    quoi que le مدير fasse à l'écran."""

    def setUp(self):
        from courses.models import OptionNbSeances

        self.admin = _creer_admin()
        OptionNbSeances.objects.all().delete()
        OptionNbSeances.objects.create(valeur=1)

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_formulaire_affiche_le_champ_cible_age_et_ordre(self):
        html = self._connecte_admin().get(reverse('admin_abonnement_ajouter')).content.decode('utf-8')
        self.assertIn('name="cible_age"', html)
        self.assertIn('name="ordre"', html)
        # Mêmes 3 choix que le formulaire de modification.
        self.assertIn('أطفال فقط', html)
        self.assertIn('بالغون فقط', html)
        self.assertIn('الجميع (أطفال وبالغون)', html)

    def test_post_cible_age_enfant_est_respectee(self):
        from inscriptions.models import TypeAbonnement

        self._connecte_admin().post(reverse('admin_abonnement_ajouter'), {
            'code': 'test_cible_age_creation', 'type_offre': 'groupe', 'label': 'y',
            'duree': '1mois', 'prix_1': '70', 'cible_age': 'enfant', 'ordre': '5',
        })
        abonnement = TypeAbonnement.objects.get(code='test_cible_age_creation')
        self.assertEqual(abonnement.cible_age, 'enfant')
        self.assertEqual(abonnement.ordre, 5)

    def test_post_sans_cible_age_repli_sur_les_deux(self):
        """Comportement de repli inchangé (cible_age absent du POST) —
        toujours 'les_deux', jamais un crash."""
        from inscriptions.models import TypeAbonnement

        self._connecte_admin().post(reverse('admin_abonnement_ajouter'), {
            'code': 'test_cible_age_repli', 'type_offre': 'groupe', 'label': 'y',
            'duree': '1mois', 'prix_1': '70',
        })
        abonnement = TypeAbonnement.objects.get(code='test_cible_age_repli')
        self.assertEqual(abonnement.cible_age, 'les_deux')
        self.assertEqual(abonnement.ordre, 0)


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
        # de couverture (même flux que EtapeChampInscriptionCRUDTests.
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
        client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})  # Étape -1, restaurée le 2026-08-22
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


# ============================================================================
# Audit du 2026-08-22 : la page détail candidature (admin_inscription_
# eleve_detail) n'était pas à jour avec le nouveau moteur d'inscription
# configurable — corrigée pour afficher نوع الحصة, عدد الحصص الأسبوعية,
# المستوى الدراسي, le prix effectif, et distinguer groupe choisi/attente/
# individuel au lieu de l'ancien moteur de suggestion (courses.utils.
# groupes_compatibles_pour_inscription, basé sur des données que le nouveau
# wizard ne collecte plus).
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class AdminInscriptionDetailAuditTests(TestCase):
    def setUp(self):
        from registration.models import ChampInscription

        self.admin = _creer_admin()
        self.champs = {
            code: ChampInscription.objects.get(etape__code='programme', critere__code=code)
            for code in ('programme', 'riwaya', 'type_offre', 'nb_seances_hebdo')
        }

        self.creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(self.creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe = Groupe.objects.create(
            nom='مجموعة اختبار تدقيق الصفحة', creneau=self.creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        from registration.models import Critere as CritereInscription, GroupeCritereValeur
        critere_programme = CritereInscription.objects.get(code='programme')
        critere_riwaya = CritereInscription.objects.get(code='riwaya')
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=critere_programme, option=critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=critere_riwaya, option=critere_riwaya.options.get(code='hafs'))

        from inscriptions.models import TypeAbonnement
        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_audit_abo_groupe', label='جماعي شهري', prix=80,
            type_offre='groupe', cible_age='les_deux', ordre=1,
        )
        self.abo_individuel = TypeAbonnement.objects.create(
            code='test_audit_abo_indiv', label='فردي شهري', prix=400,
            type_offre='individuel', cible_age='les_deux', ordre=2,
        )
        from payments.models import MoyenPaiement
        self.moyen = MoyenPaiement.objects.create(code='test_audit_cih', label='CIH بنك', est_actif=True)

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _avancer_wizard(self, client, email, type_offre='groupe', nb_seances='2', niveau_scolaire=''):
        client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})
        client.post(reverse('wizard_identite'), {
            'nom': 'مترشح تدقيق الصفحة', 'sexe': 'homme', 'email': email,
            'date_naissance': '2000-01-01', 'niveau_scolaire': niveau_scolaire,
            'indicatif_pays': '212', 'telephone': '0600110022', 'telephone_confirmation': '0600110022',
        })
        client.post(reverse('wizard_programme'), {
            f"champ_{self.champs['programme'].id}": 'hifz',
            f"champ_{self.champs['riwaya'].id}": 'hafs',
            f"champ_{self.champs['type_offre'].id}": type_offre,
            f"champ_{self.champs['nb_seances_hebdo'].id}": nb_seances,
        })

    def _terminer_wizard_groupe(self, client, abonnement):
        client.post(reverse('wizard_abonnement'), {'abonnement_code': abonnement.code})
        client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})

    def test_type_offre_affiche_et_wisilat_hudur_masquee(self):
        """Points 2 : نوع الحصة remplace/complète l'ancien "وسيلة الحضور",
        toujours vide (inscription.outil) pour une candidature du nouveau
        wizard — masqué plutôt qu'affiché vide."""
        client = Client()
        self._avancer_wizard(client, 'audit_type_offre@zidni.test', type_offre='groupe', nb_seances='2')
        client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        self._terminer_wizard_groupe(client, self.abo_groupe)

        inscription = InscriptionEleve.objects.get(email='audit_type_offre@zidni.test')
        html = self._connecte_admin().get(reverse('admin_inscription_eleve_detail', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('نوع الحصة', html)
        self.assertIn('جماعي', html)
        self.assertNotIn('وسيلة الحضور', html)

    def test_nb_slots_et_niveau_scolaire_affiches(self):
        """Points 3 et 4."""
        client = Client()
        self._avancer_wizard(client, 'audit_nb_slots@zidni.test', type_offre='individuel', nb_seances='4', niveau_scolaire='الثانية باكالوريا')
        self._terminer_wizard_groupe(client, self.abo_individuel)

        inscription = InscriptionEleve.objects.get(email='audit_nb_slots@zidni.test')
        html = self._connecte_admin().get(reverse('admin_inscription_eleve_detail', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('عدد الحصص الأسبوعية', html)
        self.assertIn('4', html)
        self.assertIn('المستوى الدراسي', html)
        self.assertIn('الثانية باكالوريا', html)

    def test_groupe_choisi_affiche_comme_choisi_pas_comme_suggestion(self):
        """Point 5 (groupe) : le groupe RÉELLEMENT choisi par le wizard est
        montré directement, jamais recalculé via l'ancien moteur de
        suggestion (qui afficherait à tort "aucune مجموعة متوافقة", voir
        docstring de la vue)."""
        client = Client()
        self._avancer_wizard(client, 'audit_groupe_choisi@zidni.test', type_offre='groupe', nb_seances='2')
        client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        self._terminer_wizard_groupe(client, self.abo_groupe)

        inscription = InscriptionEleve.objects.get(email='audit_groupe_choisi@zidni.test')
        html = self._connecte_admin().get(reverse('admin_inscription_eleve_detail', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('المجموعة المختارة', html)
        self.assertIn('مجموعة اختبار تدقيق الصفحة', html)
        self.assertNotIn('لا توجد حلقة/مجموعة متوافقة حالياً', html)

    def test_individuel_naffiche_aucun_avertissement_de_groupe(self):
        """Point 5 (individuel) : un abonnement فردي n'a structurellement
        besoin d'aucun groupe — l'ancienne page affichait quand même
        l'avertissement "aucune مجموعة متوافقة", trompeur."""
        client = Client()
        self._avancer_wizard(client, 'audit_individuel@zidni.test', type_offre='individuel', nb_seances='2')
        self._terminer_wizard_groupe(client, self.abo_individuel)

        inscription = InscriptionEleve.objects.get(email='audit_individuel@zidni.test')
        html = self._connecte_admin().get(reverse('admin_inscription_eleve_detail', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('لا حاجة إلى مجموعة', html)
        self.assertNotIn('لا توجد حلقة/مجموعة متوافقة حالياً', html)

    def test_attente_affiche_message_configurable_et_lien_vers_demandes(self):
        """Point 5 (attente) : le choix "لا، أنتظر حتى يتم إنشاء الحلقة"
        (chantier "liberté totale du nombre de séances") doit être visible
        ici, avec le message CONFIGURABLE (message_aucun_groupe_exact),
        jamais l'ancien texte codé en dur."""
        from registration.models import get_presentation_inscription

        presentation = get_presentation_inscription()
        presentation.message_aucun_groupe_exact = 'رسالة اختبار قابلة للتخصيص'
        presentation.save()

        client = Client()
        # nb_seances=55, jamais réel -> aucun groupe exact, écran d'attente.
        self._avancer_wizard(client, 'audit_attente@zidni.test', type_offre='groupe', nb_seances='55')
        client.post(reverse('wizard_groupe'), {'continuer_sans_groupe': '1'})
        self._terminer_wizard_groupe(client, self.abo_groupe)

        inscription = InscriptionEleve.objects.get(email='audit_attente@zidni.test')
        self.assertIsNone(inscription.groupe_choisi)
        html = self._connecte_admin().get(reverse('admin_inscription_eleve_detail', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('رسالة اختبار قابلة للتخصيص', html)
        self.assertIn(reverse('admin_demandes_non_satisfaites'), html)

    def test_prix_grille_affiche_badge_seulement_si_different_du_defaut(self):
        """Point 6 : le badge "سعر خاص بـ N حصص" n'apparaît QUE si une ligne
        de grille s'applique réellement — jamais 2 lignes redondantes quand
        le prix effectif == le prix par défaut."""
        from inscriptions.models import GrillePrixAbonnement

        GrillePrixAbonnement.objects.create(type_abonnement=self.abo_groupe, nb_slots=2, prix=999)

        client = Client()
        self._avancer_wizard(client, 'audit_prix_grille@zidni.test', type_offre='groupe', nb_seances='2')
        client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        self._terminer_wizard_groupe(client, self.abo_groupe)

        inscription = InscriptionEleve.objects.get(email='audit_prix_grille@zidni.test')
        html = self._connecte_admin().get(reverse('admin_inscription_eleve_detail', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('999', html)
        self.assertIn('سعر خاص بـ 2 حصص/أسبوع', html)
        self.assertIn('80', html)  # السعر الافتراضي rappelé dans le badge

    def test_candidature_ancien_formulaire_garde_son_comportement_historique(self):
        """Non-régression : une candidature de l'ANCIEN formulaire (aucune
        ReponseInscription) garde exactement l'ancien titre pluriel et
        l'ancien moteur de suggestion, jamais le nouveau vocabulaire
        "المجموعة المختارة"."""
        inscription = _creer_inscription_eleve(email='audit_ancien_formulaire@zidni.test')
        html = self._connecte_admin().get(reverse('admin_inscription_eleve_detail', args=[inscription.id])).content.decode('utf-8')
        self.assertIn('المجموعات المتوافقة', html)
        self.assertNotIn('المجموعة المختارة', html)


class AdminDemandesNonSatisfaitesTests(TestCase):
    """Page dashboard listant les DemandeNonSatisfaite (chantier du
    2026-08-22) — comptage par combinaison pour identifier les tendances."""

    def setUp(self):
        self.admin = _creer_admin()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_page_vide_sans_erreur(self):
        client = self._connecte_admin()
        reponse = client.get(reverse('admin_demandes_non_satisfaites'))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('لا توجد أي طلبات غير ملبّاة بعد', reponse.content.decode('utf-8'))

    def test_regroupe_et_compte_les_demandes_identiques(self):
        from registration.models import DemandeNonSatisfaite

        for _ in range(3):
            DemandeNonSatisfaite.objects.create(
                criteres_json={'riwaya': 'hafs'}, type_offre='groupe', nb_slots=6, age=10, sexe='homme',
            )
        DemandeNonSatisfaite.objects.create(
            criteres_json={'riwaya': 'warsh'}, type_offre='groupe', nb_slots=4, age=12, sexe='femme',
        )

        client = self._connecte_admin()
        reponse = client.get(reverse('admin_demandes_non_satisfaites'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('4', html)  # total
        self.assertIn('3 طلب', html)  # la combinaison répétée 3 fois
        self.assertIn('عدد الحصص: 6', html)
        self.assertIn('عدد الحصص: 4', html)

    def test_prof_na_pas_acces(self):
        client = Client()
        client.force_login(_creer_prof('prof_demandes_non_satisfaites@zidni.test').user)
        reponse = client.get(reverse('admin_demandes_non_satisfaites'))
        self.assertNotEqual(reponse.status_code, 200)

    def test_criteres_json_avec_une_liste_ne_plante_pas(self):
        """Bug du 2026-08-22 : un critère choix_multiple stocke sa valeur
        sous forme de LISTE dans criteres_json (voir snapshot_criteres_pour_
        demande) — reproduit exactement le scénario signalé (élève ayant
        cliqué "لا، أنتظر حتى يتم إنشاء الحلقة" à l'étape Groupe avec un
        critère choix_multiple répondu). Avant fix : TypeError: unhashable
        type: 'list' (une liste utilisée telle quelle dans une clé de dict/
        Counter pour le regroupement par combinaison)."""
        from registration.models import Critere, CritereOption, DemandeNonSatisfaite

        langue = Critere.objects.create(code='test_langue_dns', label='اللغة', type_champ='choix_multiple')
        CritereOption.objects.create(critere=langue, code='ar', label='العربية', ordre=0)
        CritereOption.objects.create(critere=langue, code='fr', label='الفرنسية', ordre=1)

        DemandeNonSatisfaite.objects.create(
            criteres_json={'test_langue_dns': ['ar', 'fr']}, type_offre='groupe', nb_slots=5, age=9, sexe='homme',
        )

        client = self._connecte_admin()
        reponse = client.get(reverse('admin_demandes_non_satisfaites'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('اللغة:', html)
        self.assertIn('العربية', html)
        self.assertIn('الفرنسية', html)

    def test_filtre_statut_ne_garde_que_les_demandes_correspondantes(self):
        """Chantier du 2026-08-27 : filtre ?statut=complete/incomplete sur la
        liste détaillée ET sur "أكثر التركيبات طلباً" (les tendances ne sont
        qu'un regroupement des mêmes demandes, doivent rester cohérentes avec
        la liste une fois le filtre actif). Le critère complet/incomplet est
        celui déjà utilisé pour le badge de chaque carte — d.inscription (voir
        _carte_demande_non_satisfaite.html). Seuls les compteurs du haut
        (total, nb_liees_a_une_inscription) restent globaux, non affectés par
        le filtre — vérifié séparément ci-dessous."""
        from registration.models import DemandeNonSatisfaite

        inscription = _creer_inscription_eleve(email='filtre_complet@zidni.test')
        complete = DemandeNonSatisfaite.objects.create(
            criteres_json={'riwaya': 'hafs'}, type_offre='groupe', nb_slots=6, age=10, sexe='homme',
            nom='مكتمل', inscription=inscription,
        )
        incomplete = DemandeNonSatisfaite.objects.create(
            criteres_json={'riwaya': 'warsh'}, type_offre='groupe', nb_slots=4, age=12, sexe='femme',
            nom='غير مكتمل',
        )

        client = self._connecte_admin()

        reponse = client.get(reverse('admin_demandes_non_satisfaites'), {'statut': 'complete'})
        demandes = list(reponse.context['demandes'])
        self.assertEqual([d.id for d in demandes], [complete.id])
        self.assertEqual(reponse.context['total'], 2)  # compteur global, pas filtré
        self.assertEqual(reponse.context['nb_liees_a_une_inscription'], 1)
        tendances = reponse.context['tendances']
        self.assertEqual([t['nb_slots'] for t in tendances], [6])

        reponse = client.get(reverse('admin_demandes_non_satisfaites'), {'statut': 'incomplete'})
        demandes = list(reponse.context['demandes'])
        self.assertEqual([d.id for d in demandes], [incomplete.id])
        self.assertEqual(reponse.context['total'], 2)  # compteur global, pas filtré
        tendances = reponse.context['tendances']
        self.assertEqual([t['nb_slots'] for t in tendances], [4])

        reponse = client.get(reverse('admin_demandes_non_satisfaites'))
        demandes = list(reponse.context['demandes'])
        self.assertEqual({d.id for d in demandes}, {complete.id, incomplete.id})
        tendances = reponse.context['tendances']
        self.assertEqual({t['nb_slots'] for t in tendances}, {4, 6})


class AdminDemandeNonSatisfaiteDetailEtSuppressionTests(TestCase):
    """Chantier du 2026-08-25 (point 4a/4c) : fiche détail cliquable depuis
    chaque carte de admin_demandes_non_satisfaites, pagination "عرض المزيد"
    au-delà de 15, et suppression définitive par carte. Point 4b (logique du
    statut "لم يتم إكمال التسجيل") laissé inchangé — confirmé avec
    l'utilisateur que le comportement existant (d.inscription is None)
    correspond déjà exactement à la définition attendue, aucun bug trouvé."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def test_carte_est_cliquable_vers_la_fiche_detail(self):
        from registration.models import DemandeNonSatisfaite

        demande = DemandeNonSatisfaite.objects.create(
            criteres_json={'riwaya': 'hafs'}, type_offre='groupe', nb_slots=6, age=10, sexe='homme',
            nom='مرشح تفاصيل', telephone='0600000010', email='detail_carte@zidni.test',
        )
        client = self._connecte_admin()
        html = client.get(reverse('admin_demandes_non_satisfaites')).content.decode('utf-8')
        self.assertIn(reverse('admin_demande_non_satisfaite_detail', args=[demande.id]), html)

    def test_fiche_detail_affiche_toutes_les_infos(self):
        from registration.models import DemandeNonSatisfaite

        demande = DemandeNonSatisfaite.objects.create(
            criteres_json={'riwaya': 'hafs'}, type_offre='groupe', nb_slots=6, age=10, sexe='homme',
            nom='مرشح تفاصيل كاملة', telephone='0600000011', email='detail_complet@zidni.test',
        )
        client = self._connecte_admin()
        reponse = client.get(reverse('admin_demande_non_satisfaite_detail', args=[demande.id]))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('مرشح تفاصيل كاملة', html)
        self.assertIn('0600000011', html)
        self.assertIn('detail_complet@zidni.test', html)
        self.assertIn('لم يتم إكمال التسجيل', html)

    def test_fiche_detail_liee_a_une_inscription_affiche_le_lien(self):
        from registration.models import DemandeNonSatisfaite

        inscription = _creer_inscription_eleve(email='detail_lie@zidni.test')
        demande = DemandeNonSatisfaite.objects.create(
            criteres_json={'riwaya': 'hafs'}, type_offre='groupe', nb_slots=6, age=10, sexe='homme',
            inscription=inscription,
        )
        client = self._connecte_admin()
        html = client.get(reverse('admin_demande_non_satisfaite_detail', args=[demande.id])).content.decode('utf-8')
        self.assertIn(reverse('admin_inscription_eleve_detail', args=[inscription.id]), html)
        self.assertNotIn('لم يتم إكمال التسجيل', html)

    def test_fiche_detail_404_si_id_inexistant(self):
        client = self._connecte_admin()
        reponse = client.get(reverse('admin_demande_non_satisfaite_detail', args=[999999]))
        self.assertEqual(reponse.status_code, 404)

    def test_prof_na_pas_acces_a_la_fiche_detail(self):
        from registration.models import DemandeNonSatisfaite

        demande = DemandeNonSatisfaite.objects.create(criteres_json={}, type_offre='groupe')
        client = Client()
        client.force_login(_creer_prof('prof_detail_dns@zidni.test').user)
        reponse = client.get(reverse('admin_demande_non_satisfaite_detail', args=[demande.id]))
        self.assertNotEqual(reponse.status_code, 200)

    def test_suppression_retire_la_demande_et_le_comptage(self):
        from registration.models import DemandeNonSatisfaite

        demande = DemandeNonSatisfaite.objects.create(criteres_json={'riwaya': 'hafs'}, type_offre='groupe', nb_slots=2)
        client = self._connecte_admin()
        self.assertEqual(client.get(reverse('admin_demandes_non_satisfaites')).context['total'], 1)

        reponse = client.post(reverse('admin_demande_non_satisfaite_supprimer', args=[demande.id]))
        self.assertRedirects(reponse, reverse('admin_demandes_non_satisfaites'))
        self.assertFalse(DemandeNonSatisfaite.objects.filter(id=demande.id).exists())
        self.assertEqual(client.get(reverse('admin_demandes_non_satisfaites')).context['total'], 0)

    def test_suppression_refuse_get(self):
        from registration.models import DemandeNonSatisfaite

        demande = DemandeNonSatisfaite.objects.create(criteres_json={}, type_offre='groupe')
        client = self._connecte_admin()
        reponse = client.get(reverse('admin_demande_non_satisfaite_supprimer', args=[demande.id]))
        self.assertEqual(reponse.status_code, 405)
        self.assertTrue(DemandeNonSatisfaite.objects.filter(id=demande.id).exists())

    def test_prof_ne_peut_pas_supprimer(self):
        from registration.models import DemandeNonSatisfaite

        demande = DemandeNonSatisfaite.objects.create(criteres_json={}, type_offre='groupe')
        client = Client()
        client.force_login(_creer_prof('prof_suppr_dns@zidni.test').user)
        reponse = client.post(reverse('admin_demande_non_satisfaite_supprimer', args=[demande.id]))
        self.assertNotEqual(reponse.status_code, 200)
        self.assertTrue(DemandeNonSatisfaite.objects.filter(id=demande.id).exists())

    def test_pagination_affiche_15_puis_le_reste_cache(self):
        from registration.models import DemandeNonSatisfaite

        for i in range(18):
            DemandeNonSatisfaite.objects.create(
                criteres_json={}, type_offre='groupe', nom=f'مرشح رقم {i}', email=f'pagination_{i}@zidni.test',
            )
        client = self._connecte_admin()
        html = client.get(reverse('admin_demandes_non_satisfaites')).content.decode('utf-8')
        self.assertIn('id="demandes_extra"', html)
        self.assertIn('عرض كل الطلبات (18)', html)
        # Les 18 sont bien présentes dans la page (15 visibles + 3 dans le
        # bloc caché), seul l'AFFICHAGE initial est limité côté JS.
        for i in range(18):
            self.assertIn(f'pagination_{i}@zidni.test', html)

    def test_pas_de_pagination_sous_15(self):
        from registration.models import DemandeNonSatisfaite

        DemandeNonSatisfaite.objects.create(criteres_json={}, type_offre='groupe')
        client = self._connecte_admin()
        html = client.get(reverse('admin_demandes_non_satisfaites')).content.decode('utf-8')
        self.assertNotIn('id="demandes_extra"', html)

    def test_mshrif_a_aussi_acces(self):
        from registration.models import DemandeNonSatisfaite

        demande = DemandeNonSatisfaite.objects.create(criteres_json={}, type_offre='groupe')
        client = Client()
        client.force_login(self.mshrif)
        self.assertEqual(client.get(reverse('admin_demande_non_satisfaite_detail', args=[demande.id])).status_code, 200)


# ============================================================================
# Fonctionnalité 4 (2026-08-27) : demande de changement de halaka (élève)
# ============================================================================
def _creer_creneau_dashboard(sexe_cible='mixte', age_min=6, age_max=60):
    creneau = Creneau.objects.create(sexe_cible=sexe_cible, type_seance='hifz', riwaya='hafs', age_min=age_min, age_max=age_max)
    remplacer_slots_creneau(creneau, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
    return creneau


def _creer_eleve_avec_inscription(email, age=20, sexe='homme'):
    aujourdhui = datetime.date.today()
    inscription = InscriptionEleve.objects.create(
        nom='طالب تجريبي', date_naissance=aujourdhui.replace(year=aujourdhui.year - age), sexe=sexe,
        telephone='0600000000', email=email,
        programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois', statut='valide',
    )
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe=sexe, statut='actif', inscription=inscription)


class EleveDemandeChangementHalakaTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve_avec_inscription('eleve_demande_halaka@zidni.test', age=20, sexe='homme')
        self.creneau_actuel = _creer_creneau_dashboard(sexe_cible='mixte', age_min=18, age_max=60)
        self.groupe_actuel = Groupe.objects.create(nom='حلقته الحالية', creneau=self.creneau_actuel)
        # _ajouter_eleve_au_groupe (pas .eleves.add() brut) — ouvre aussi la
        # ligne HistoriqueGroupeEleve correspondante, nécessaire pour que le
        # transfert testé plus bas puisse la fermer (date_fin) comme en
        # conditions réelles (voir courses.views._ajouter_eleve_au_groupe).
        _ajouter_eleve_au_groupe(self.eleve, self.groupe_actuel)

        self.creneau_cible = _creer_creneau_dashboard(sexe_cible='mixte', age_min=18, age_max=60)
        self.groupe_cible = Groupe.objects.create(nom='الحلقة المطلوبة', creneau=self.creneau_cible)

    def _connecte_eleve(self):
        client = Client()
        client.force_login(self.eleve.user)
        return client

    def test_get_affiche_les_halakat_compatibles(self):
        html = self._connecte_eleve().get(reverse('eleve_demande_changement_halaka')).content.decode('utf-8')
        self.assertIn('الحلقة المطلوبة', html)
        # La halaka ACTUELLE de l'élève n'est jamais proposée comme destination.
        self.assertNotIn('حلقته الحالية', html)

    def test_post_cree_la_demande(self):
        client = self._connecte_eleve()
        client.post(reverse('eleve_demande_changement_halaka'), {'groupe_demande': self.groupe_cible.id})
        demande = DemandeChangementHalaka.objects.get(eleve=self.eleve)
        self.assertEqual(demande.statut, 'en_attente')
        self.assertEqual(demande.groupe_demande, self.groupe_cible)
        self.assertEqual(demande.groupe_actuel, self.groupe_actuel)

    def test_post_groupe_hors_liste_refuse(self):
        """Revalidation serveur — un groupe_demande posté qui n'est PAS dans
        la liste compatible (ex: incompatible d'âge/sexe, ou id inexistant)
        ne doit jamais créer de demande."""
        creneau_incompatible = _creer_creneau_dashboard(sexe_cible='femme', age_min=18, age_max=60)
        groupe_incompatible = Groupe.objects.create(nom='غير متوافقة', creneau=creneau_incompatible)
        client = self._connecte_eleve()
        client.post(reverse('eleve_demande_changement_halaka'), {'groupe_demande': groupe_incompatible.id})
        self.assertFalse(DemandeChangementHalaka.objects.filter(eleve=self.eleve).exists())

    def test_une_seule_demande_en_attente_a_la_fois(self):
        DemandeChangementHalaka.objects.create(eleve=self.eleve, groupe_actuel=self.groupe_actuel, groupe_demande=self.groupe_cible)
        autre_creneau = _creer_creneau_dashboard(sexe_cible='mixte', age_min=18, age_max=60)
        autre_groupe = Groupe.objects.create(nom='حلقة أخرى', creneau=autre_creneau)

        client = self._connecte_eleve()
        client.post(reverse('eleve_demande_changement_halaka'), {'groupe_demande': autre_groupe.id})
        self.assertEqual(DemandeChangementHalaka.objects.filter(eleve=self.eleve).count(), 1)

    def test_get_avec_demande_en_attente_naffiche_pas_le_formulaire(self):
        DemandeChangementHalaka.objects.create(eleve=self.eleve, groupe_actuel=self.groupe_actuel, groupe_demande=self.groupe_cible)
        html = self._connecte_eleve().get(reverse('eleve_demande_changement_halaka')).content.decode('utf-8')
        self.assertNotIn('name="groupe_demande"', html)

    def test_profil_affiche_le_bouton_normalement(self):
        html = self._connecte_eleve().get(reverse('eleve_profil')).content.decode('utf-8')
        self.assertIn('طلب تغيير الحلقة', html)

    def test_profil_affiche_le_statut_si_demande_en_attente(self):
        DemandeChangementHalaka.objects.create(eleve=self.eleve, groupe_actuel=self.groupe_actuel, groupe_demande=self.groupe_cible)
        html = self._connecte_eleve().get(reverse('eleve_profil')).content.decode('utf-8')
        self.assertIn('طلب تغيير الحلقة قيد الانتظار', html)


class AdminDemandesChangementHalakaTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.eleve = _creer_eleve_avec_inscription('eleve_admin_demande_halaka@zidni.test', age=20, sexe='homme')
        self.creneau_actuel = _creer_creneau_dashboard(sexe_cible='mixte', age_min=18, age_max=60)
        self.groupe_actuel = Groupe.objects.create(nom='حلقته الحالية', creneau=self.creneau_actuel)
        # _ajouter_eleve_au_groupe (pas .eleves.add() brut) — ouvre aussi la
        # ligne HistoriqueGroupeEleve correspondante, nécessaire pour que le
        # transfert testé plus bas puisse la fermer (date_fin) comme en
        # conditions réelles (voir courses.views._ajouter_eleve_au_groupe).
        _ajouter_eleve_au_groupe(self.eleve, self.groupe_actuel)
        self.creneau_cible = _creer_creneau_dashboard(sexe_cible='mixte', age_min=18, age_max=60)
        self.groupe_cible = Groupe.objects.create(nom='الحلقة المطلوبة', creneau=self.creneau_cible)
        self.demande = DemandeChangementHalaka.objects.create(
            eleve=self.eleve, groupe_actuel=self.groupe_actuel, groupe_demande=self.groupe_cible,
        )

    def _connecte(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_liste_affiche_la_demande_en_attente(self):
        html = self._connecte(self.admin).get(reverse('admin_demandes_changement_halaka')).content.decode('utf-8')
        self.assertIn('حلقته الحالية', html)
        self.assertIn('الحلقة المطلوبة', html)

    def test_valider_transfere_leleve_automatiquement(self):
        client = self._connecte(self.admin)
        client.get(reverse('admin_demande_changement_halaka_valider', args=[self.demande.id]))

        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, 'validee')
        self.assertEqual(self.demande.traite_par, self.admin)
        self.assertIsNotNone(self.demande.date_traitement)

        self.assertFalse(self.groupe_actuel.eleves.filter(id=self.eleve.id).exists())
        self.assertTrue(self.groupe_cible.eleves.filter(id=self.eleve.id).exists())

        # Historique cohérent (même mécanisme que groupe_transferer_eleve).
        self.assertTrue(
            HistoriqueGroupeEleve.objects.filter(eleve=self.eleve, groupe=self.groupe_actuel, date_fin__isnull=False).exists()
        )
        self.assertTrue(
            HistoriqueGroupeEleve.objects.filter(eleve=self.eleve, groupe=self.groupe_cible, date_fin__isnull=True).exists()
        )

    def test_mshrif_peut_aussi_valider(self):
        """Décision explicite du client : un SEUL des 2 rôles suffit."""
        client = self._connecte(self.mshrif)
        client.get(reverse('admin_demande_changement_halaka_valider', args=[self.demande.id]))
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, 'validee')
        self.assertEqual(self.demande.traite_par, self.mshrif)

    def test_refuser_ne_transfere_pas(self):
        client = self._connecte(self.admin)
        client.get(reverse('admin_demande_changement_halaka_refuser', args=[self.demande.id]))

        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, 'refusee')
        self.assertTrue(self.groupe_actuel.eleves.filter(id=self.eleve.id).exists())
        self.assertFalse(self.groupe_cible.eleves.filter(id=self.eleve.id).exists())

    def test_valider_groupe_devenu_complet_bloque(self):
        """Revalidation serveur au moment de la validation — même garde que
        n'importe quel autre transfert (raison_incompatibilite_groupe)."""
        self.groupe_cible.capacite_max = 1
        self.groupe_cible.save()
        autre_eleve = _creer_eleve_avec_inscription('autre_eleve_capacite@zidni.test', age=20, sexe='homme')
        self.groupe_cible.eleves.add(autre_eleve)

        client = self._connecte(self.admin)
        client.get(reverse('admin_demande_changement_halaka_valider', args=[self.demande.id]))

        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, 'en_attente')  # pas transformée
        self.assertFalse(self.groupe_cible.eleves.filter(id=self.eleve.id).exists())

    def test_deja_traitee_refuse_un_2e_traitement(self):
        self.demande.statut = 'validee'
        self.demande.save()
        client = self._connecte(self.admin)
        reponse = client.get(reverse('admin_demande_changement_halaka_refuser', args=[self.demande.id]), follow=True)
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.statut, 'validee')  # inchangée
        self.assertContains(reponse, 'لم يعد قيد الانتظار')


# ---------- Fonctionnalité 4 : notification مدير/مشرف partagée ----------
class NotificationsChangementHalakaDirectionTests(TestCase):
    """Même panneau 🔔 que NotificationsDirectionTests/
    NotificationsProfEnAttenteDirectionTests — 3e événement, visible par les
    2 rôles cette fois (contrairement au 2e, مشرف seul)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.eleve = _creer_eleve_avec_inscription('eleve_notif_halaka@zidni.test', age=20, sexe='homme')
        creneau = _creer_creneau_dashboard(sexe_cible='mixte', age_min=18, age_max=60)
        self.groupe_cible = Groupe.objects.create(nom='حلقة الإشعار', creneau=creneau)

    def test_demande_declenche_le_badge_admin_et_mshrif(self):
        DemandeChangementHalaka.objects.create(eleve=self.eleve, groupe_demande=self.groupe_cible)

        self.client.force_login(self.admin)
        reponse_admin = self.client.get(reverse('dashboard_admin'))
        self.assertEqual(reponse_admin.context['notif_total'], 1)
        self.assertContains(reponse_admin, 'طلب تغيير حلقة')

        self.client.force_login(self.mshrif)
        reponse_mshrif = self.client.get(reverse('dashboard_mshrif'))
        self.assertEqual(reponse_mshrif.context['notif_total'], 1)

    def test_visiter_la_liste_marque_comme_lu(self):
        DemandeChangementHalaka.objects.create(eleve=self.eleve, groupe_demande=self.groupe_cible)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 1)
        self.client.get(reverse('admin_demandes_changement_halaka'))
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 0)

    def test_demande_traitee_ne_declenche_plus(self):
        demande = DemandeChangementHalaka.objects.create(
            eleve=self.eleve, groupe_demande=self.groupe_cible, statut='validee',
        )
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard_admin')).context['notif_total'], 0)


class CharteEnseignementLocaliseeTests(TestCase):
    """Chantier i18n du 2026-08-28 — même patron que PresentationInscription
    (registration/tests.py), mais CharteEnseignement stocke ses traductions
    dans un JSONField (traductions) plutôt que des colonnes _fr/_en par champ
    (27 champs, voir accounts.models.CharteEnseignement.__doc__ juste avant
    _CHAMPS_LOCALISABLES pour le pourquoi)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

    def _connecte_admin(self):
        client = Client()
        client.force_login(self.admin)
        return client

    def _poster_charte_minimale(self, client, **supplement):
        from accounts.models import CharteEnseignement

        donnees = {champ: f'نص {champ}' for champ in CharteEnseignement._CHAMPS_LOCALISABLES}
        donnees.update(supplement)
        return client.post(reverse('mshrif_charte'), donnees)

    def test_traductions_fr_en_sauvegardees_avec_repli_arabe(self):
        from django.utils import translation
        from accounts.models import get_charte

        client = self._connecte_admin()
        self._poster_charte_minimale(
            client,
            section1_titre_fr='Titre section 1', section1_titre_en='',  # EN volontairement vide
        )
        charte = get_charte()
        self.assertEqual(charte.traductions['fr']['section1_titre'], 'Titre section 1')
        self.assertEqual(charte.traductions['en']['section1_titre'], '')
        with translation.override('fr'):
            self.assertEqual(charte._localise('section1_titre'), 'Titre section 1')
        with translation.override('en'):
            # EN vide -> repli automatique sur l'arabe.
            self.assertEqual(charte._localise('section1_titre'), 'نص section1_titre')
        with translation.override('ar'):
            self.assertEqual(charte._localise('section1_titre'), 'نص section1_titre')

    def test_page_mshrif_charte_affiche_la_traduction_selon_la_langue(self):
        client = self._connecte_admin()
        self._poster_charte_minimale(client, intro_fr='Introduction en français')
        client.post(reverse('set_language'), {'language': 'fr', 'next': reverse('mshrif_charte')})
        html = client.get(reverse('mshrif_charte')).content.decode('utf-8')
        self.assertIn('Introduction en français', html)

    def test_ligne_sanction_fr_en_avec_repli_arabe(self):
        from django.utils import translation
        from accounts.models import get_charte

        client = self._connecte_admin()
        self._poster_charte_minimale(
            client,
            sanction_violation=['التأخر عن الحصة'], sanction_violation_fr=['Retard au cours'],
            sanction_violation_en=[''], sanction_severite=['progressive'],
        )
        ligne = get_charte().sanctions.get()
        self.assertEqual(ligne.violation_fr, 'Retard au cours')
        with translation.override('fr'):
            self.assertEqual(ligne._localise('violation'), 'Retard au cours')
        with translation.override('en'):
            self.assertEqual(ligne._localise('violation'), 'التأخر عن الحصة')


class ProgrammeGeneralLocaliseTests(TestCase):
    """Chantier i18n contenu-DB (2026-08-31), lot 4 : accounts.ProgrammeGeneral
    gagne 6 paires _fr/_en (titre/intro/items × enfants/adultes), lues via
    <champ>_localise avec repli arabe — même patron que PresentationInscription."""

    def setUp(self):
        self.admin = _creer_admin()
        self.client.force_login(self.admin)

    def test_localise_repli(self):
        from django.utils import translation
        from accounts.models import get_programme_general
        p = get_programme_general()
        p.titre_enfants = 'برنامج الأطفال'
        p.titre_enfants_fr = 'Programme enfants'
        p.save()
        with translation.override('fr'):
            self.assertEqual(p.titre_enfants_localise, 'Programme enfants')
        with translation.override('en'):
            self.assertEqual(p.titre_enfants_localise, 'برنامج الأطفال')  # _en vide -> repli

    def test_admin_enregistre_les_traductions_et_page_detail_les_affiche(self):
        self.client.post(reverse('admin_programme_general'), {
            'titre_enfants': 'برنامج الأطفال', 'titre_enfants_fr': 'Programme enfants', 'titre_enfants_en': '',
            'intro_enfants': 'مقدمة', 'intro_enfants_fr': 'Intro FR', 'intro_enfants_en': '',
            'items_enfants': 'نقطة 1', 'items_enfants_fr': '', 'items_enfants_en': '',
            'titre_adultes': '', 'titre_adultes_fr': '', 'titre_adultes_en': '',
            'intro_adultes': '', 'intro_adultes_fr': '', 'intro_adultes_en': '',
            'items_adultes': '', 'items_adultes_fr': '', 'items_adultes_en': '',
        })
        from accounts.models import get_programme_general
        p = get_programme_general()
        self.assertEqual(p.titre_enfants_fr, 'Programme enfants')
        self.assertEqual(p.intro_enfants_fr, 'Intro FR')

        eleve = _creer_eleve('eleve_prog_gen@zidni.test')
        eleve.user.date_naissance = datetime.date(2015, 1, 1)  # enfant
        eleve.user.save()
        self.client.force_login(eleve.user)
        r = self.client.get(reverse('programme_general_detail'), HTTP_ACCEPT_LANGUAGE='fr')
        self.assertEqual(r.status_code, 200)
        contenu = r.content.decode('utf-8')
        self.assertIn('Programme enfants', contenu)
        self.assertIn('Intro FR', contenu)


class RenduReelFrEnTemplatesAdminTests(TestCase):
    """Chantier i18n du 2026-08-29 (audit مدير/مشرف, fin de chantier) —
    contrairement aux tests {% trans %}/gettext_lazy déjà présents ailleurs
    (qui vérifient que le TAG est bien posé), celui-ci vérifie le rendu RÉEL
    d'une page après bascule de langue via /i18n/setlang/ : un texte {% trans %}
    peut être syntaxiquement correct mais rester affiché en arabe si
    locale/*.po/.mo n'a jamais été recompilé avec ce msgid — c'est exactement
    ce qui s'est produit une bonne partie de ce chantier (plusieurs centaines
    de nouvelles chaînes ajoutées aux templates sans mise à jour du catalogue,
    découvert et corrigé en toute fin de session). Ce test couvre 2 pages
    représentatives de lots distincts (créneaux/courses et élèves/dashboard)
    pour détecter une régression similaire à l'avenir."""

    def setUp(self):
        self.admin = _creer_admin()

    def test_admin_eleves_traduit_reellement_en_fr_et_en(self):
        client = Client()
        client.force_login(self.admin)
        client.post(reverse('set_language'), {'language': 'fr', 'next': reverse('admin_eleves')})
        html_fr = client.get(reverse('admin_eleves')).content.decode('utf-8')
        self.assertIn('Gestion des élèves', html_fr)
        self.assertNotIn('إدارة الطلاب', html_fr)

        client.post(reverse('set_language'), {'language': 'en', 'next': reverse('admin_eleves')})
        html_en = client.get(reverse('admin_eleves')).content.decode('utf-8')
        self.assertIn('Student management', html_en)
        self.assertNotIn('إدارة الطلاب', html_en)

    def test_admin_creneaux_traduit_reellement_en_fr_et_en(self):
        client = Client()
        client.force_login(self.admin)
        client.post(reverse('set_language'), {'language': 'fr', 'next': reverse('admin_creneaux')})
        html_fr = client.get(reverse('admin_creneaux')).content.decode('utf-8')
        self.assertIn('Gestion des halqas', html_fr)

        client.post(reverse('set_language'), {'language': 'en', 'next': reverse('admin_creneaux')})
        html_en = client.get(reverse('admin_creneaux')).content.decode('utf-8')
        self.assertIn('Halaka management', html_en)
