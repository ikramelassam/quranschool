import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from django.utils import translation

from accounts.models import User, Eleve, Prof, Superviseur, DerniereVisiteNotification
from courses.models import Groupe, Seance
from .models import Evaluation, Critere, NoteEvaluation


def _creer_eleve(email='eleve_eval_test@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme')


def _creer_prof(email='prof_eval_test@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='أستاذ', last_name='تجريبي', role='prof', doit_changer_mot_de_passe=False,
    )
    return Prof.objects.create(user=u, ville='الرباط', niveau_memorisation='كامل')


def _creer_superviseur(email='superviseur_eval_test@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='مؤطر', last_name='تجريبي', role='superviseur', doit_changer_mot_de_passe=False,
    )
    return Superviseur.objects.create(user=u)


class ProfEvaluationsRecuesTests(TestCase):
    """"تقييمات المؤطر لي" (Chantier notifications du 2026-08-19) — manque
    fonctionnel comblé par ce chantier : jusqu'ici aucune vue ne permettait
    au prof de consulter les évaluations écrites sur lui par son مؤطر."""

    def setUp(self):
        self.prof = _creer_prof()
        self.autre_prof = _creer_prof(email='autre_prof_eval_test@zidni.test')
        self.superviseur = _creer_superviseur()
        self.groupe = Groupe.objects.create(nom='مجموعة', prof=self.prof, statut='actif')
        self.seance = Seance.objects.create(
            groupe=self.groupe, date=datetime.date(2026, 8, 10), heure=datetime.time(17, 0),
            type='normal', statut='terminee',
        )
        self.evaluation = Evaluation.objects.create(
            seance=self.seance, superviseur=self.superviseur, prof=self.prof,
            commentaire='أداء جيد.',
        )

    def test_prof_voit_sa_propre_evaluation(self):
        self.client.force_login(self.prof.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'أداء جيد')

    def test_prof_ne_voit_jamais_les_evaluations_dun_autre_prof(self):
        """Le queryset est scopé à prof=request.user.prof — pas de fuite
        même si un autre prof partage un groupe/مؤطر."""
        self.client.force_login(self.autre_prof.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'أداء جيد')

    def test_role_eleve_refuse(self):
        eleve = _creer_eleve()
        self.client.force_login(eleve.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertNotEqual(response.status_code, 200)

    def test_role_superviseur_refuse(self):
        self.client.force_login(self.superviseur.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertNotEqual(response.status_code, 200)

    def test_affiche_le_nom_et_les_coordonnees_du_mouatir_auteur(self):
        """Point 6 (chantier catégorisation par âge du 2026-08-28) : le prof
        voit désormais QUI a écrit l'évaluation (nom) et peut le contacter
        (icônes email/WhatsApp), pas seulement le texte "المؤطر" générique."""
        self.superviseur.user.telephone = '0612345678'
        self.superviseur.user.save()
        self.client.force_login(self.prof.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertContains(response, self.superviseur.user.get_full_name())
        self.assertContains(response, f'mailto:{self.superviseur.user.email}')

    def test_evaluation_dont_le_mouatir_a_ete_supprime_ne_plante_pas(self):
        """Evaluation.superviseur est SET_NULL (voir son docstring) — la page
        doit rester utilisable même sans auteur retrouvable."""
        self.evaluation.superviseur = None
        self.evaluation.save()
        self.client.force_login(self.prof.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertEqual(response.status_code, 200)

    def test_visiter_la_page_marque_evaluations_recues_comme_lu(self):
        self.client.force_login(self.prof.user)
        self.assertFalse(
            DerniereVisiteNotification.objects.filter(user=self.prof.user, cle='evaluations_recues').exists()
        )
        self.client.get(reverse('evaluations_prof_recues'))
        self.assertTrue(
            DerniereVisiteNotification.objects.filter(user=self.prof.user, cle='evaluations_recues').exists()
        )


class CritereLocaliseTests(TestCase):
    """Chantier i18n contenu-DB (2026-08-31) : evaluations.Critere.nom_ar
    gagne nom_fr/nom_en (saisis à la main par le مدير), lus via nom_localise
    avec repli automatique sur l'arabe. Vus par le مؤطر (formulaire
    d'évaluation du prof) ET par le prof (ses propres évaluations) — les 2
    peuvent être en session FR/EN."""

    def setUp(self):
        self.prof = _creer_prof()
        self.superviseur = _creer_superviseur()
        self.groupe = Groupe.objects.create(nom='مجموعة', prof=self.prof, statut='actif')
        self.seance = Seance.objects.create(
            groupe=self.groupe, date=datetime.date(2026, 8, 10), heure=datetime.time(17, 0),
            type='normal', statut='terminee',
        )
        self.critere_traduit = Critere.objects.create(
            nom_ar='المواظبة', nom_fr='Assiduité', nom_en='Attendance', ordre=1,
        )
        self.critere_sans_trad = Critere.objects.create(nom_ar='التلاوة', ordre=2)

    def test_nom_localise_repli(self):
        with translation.override('fr'):
            self.assertEqual(self.critere_traduit.nom_localise, 'Assiduité')
            self.assertEqual(self.critere_sans_trad.nom_localise, 'التلاوة')  # repli arabe
        with translation.override('en'):
            self.assertEqual(self.critere_traduit.nom_localise, 'Attendance')
        with translation.override('ar'):
            self.assertEqual(self.critere_traduit.nom_localise, 'المواظبة')

    def test_prof_voit_le_critere_traduit_dans_ses_evaluations(self):
        evaluation = Evaluation.objects.create(
            seance=self.seance, superviseur=self.superviseur, prof=self.prof,
            commentaire='أداء جيد.',
        )
        NoteEvaluation.objects.create(evaluation=evaluation, critere=self.critere_traduit, note=3)
        NoteEvaluation.objects.create(evaluation=evaluation, critere=self.critere_sans_trad, note=4)
        self.client.force_login(self.prof.user)
        response = self.client.get(
            reverse('evaluations_prof_recues'), HTTP_ACCEPT_LANGUAGE='fr',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Assiduité')
        self.assertNotContains(response, 'المواظبة')
        self.assertContains(response, 'التلاوة')  # non traduit -> repli arabe visible

    def test_admin_enregistre_nom_fr_nom_en(self):
        admin = User.objects.create_user(
            username='admin_crit_test@zidni.test', email='admin_crit_test@zidni.test',
            password='xX!test12345', role='admin', doit_changer_mot_de_passe=False,
        )
        self.client.force_login(admin)
        self.client.post(reverse('admin_critere_ajouter'), {
            'nom_ar': 'معيار تجريبي للترجمة', 'nom_fr': 'Préparation', 'nom_en': 'Preparation', 'ordre': 5,
        })
        cree = Critere.objects.get(nom_ar='معيار تجريبي للترجمة')
        self.assertEqual(cree.nom_fr, 'Préparation')
        self.assertEqual(cree.nom_en, 'Preparation')
