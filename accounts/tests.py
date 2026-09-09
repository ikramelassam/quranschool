from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import Prof
from accounts.services import generer_presentation_publique

User = get_user_model()

_STORAGES_TEST = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class ModifierTelephoneTests(TestCase):
    """accounts.views.modifier_telephone — audit du 2026-09-05 : le `next`
    n'était pas validé (open-redirect faible) ; aucun test ne couvrait la vue."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='tel@zidni.test', email='tel@zidni.test', password='xX!test12345',
            role='eleve', doit_changer_mot_de_passe=False,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_next_interne_est_respecte(self):
        reponse = self.client.post(reverse('modifier_telephone'), {
            'telephone': '0611223344', 'next': reverse('eleve_profil'),
        })
        self.assertRedirects(reponse, reverse('eleve_profil'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertEqual(self.user.telephone, '0611223344')

    def test_next_externe_est_ignore(self):
        reponse = self.client.post(reverse('modifier_telephone'), {
            'telephone': '0611223344', 'next': 'https://evil.example.com/phish',
        })
        self.assertNotIn('evil.example.com', reponse['Location'])
        # Retombe sur le dashboard du rôle, jamais sur l'URL externe.
        self.assertEqual(reponse['Location'], reverse('dashboard_eleve'))

    def test_next_protocol_relative_est_ignore(self):
        reponse = self.client.post(reverse('modifier_telephone'), {
            'telephone': '0611223344', 'next': '//evil.example.com',
        })
        self.assertEqual(reponse['Location'], reverse('dashboard_eleve'))


@override_settings(STORAGES=_STORAGES_TEST)
class PasswordChangeValidatorsTests(TestCase):
    """accounts.views.password_change_view — audit du 2026-09-05 : seul
    `len >= 8` était vérifié, les AUTH_PASSWORD_VALIDATORS de settings.py
    n'étaient invoqués nulle part. `validate_password` les applique désormais."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='pwd@zidni.test', email='pwd@zidni.test', password='AncienMdp!2026',
            first_name='مدير', role='admin', doit_changer_mot_de_passe=False,
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_mot_de_passe_trop_courant_refuse(self):
        reponse = self.client.post(reverse('password_change'), {
            'ancien_mot_de_passe': 'AncienMdp!2026',
            'nouveau_mot_de_passe': 'password',  # >= 8 mais CommonPasswordValidator le rejette
            'confirmation': 'password',
        })
        self.assertEqual(reponse.status_code, 200)  # formulaire ré-affiché
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('AncienMdp!2026'))  # inchangé

    def test_mot_de_passe_purement_numerique_refuse(self):
        reponse = self.client.post(reverse('password_change'), {
            'ancien_mot_de_passe': 'AncienMdp!2026',
            'nouveau_mot_de_passe': '48291736',
            'confirmation': '48291736',
        })
        self.assertEqual(reponse.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('AncienMdp!2026'))

    def test_mot_de_passe_valide_accepte(self):
        reponse = self.client.post(reverse('password_change'), {
            'ancien_mot_de_passe': 'AncienMdp!2026',
            'nouveau_mot_de_passe': 'Kachida-9271-Tarwiya',
            'confirmation': 'Kachida-9271-Tarwiya',
        })
        self.assertEqual(reponse.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Kachida-9271-Tarwiya'))


def _creer_prof(email, **extra):
    user = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='أستاذ', last_name='تجريبي', role='prof', doit_changer_mot_de_passe=False,
    )
    valeurs = {'user': user, 'ville': 'الرباط'}
    valeurs.update(extra)
    return Prof.objects.create(**valeurs)


class BackfillPresentationPubliqueProfsTests(TestCase):
    """Chantier du 2026-08-27 — voir accounts.services.generer_presentation_publique
    et accounts.management.commands.backfill_presentation_publique_profs : les profs
    créés avant ce chantier ont presentation_publique vide, cette commande doit le
    régénérer sans jamais toucher un texte déjà présent."""

    def test_remplit_un_prof_vide_avec_donnees_exploitables(self):
        prof = _creer_prof(
            'prof_vide_avec_donnees@zidni.test',
            niveau_memorisation='كامل',
            parcours_scolaire='بكالوريا علوم',
            langues=['arabe', 'francais'],
        )
        self.assertEqual(prof.presentation_publique, '')

        call_command('backfill_presentation_publique_profs')

        prof.refresh_from_db()
        self.assertNotEqual(prof.presentation_publique, '')
        self.assertIn('كامل', prof.presentation_publique)

    def test_ne_touche_pas_un_texte_deja_genere_ou_modifie_a_la_main(self):
        prof = _creer_prof(
            'prof_deja_rempli@zidni.test',
            niveau_memorisation='كامل',
            presentation_publique='نص كتبه المشرف يدويا.',
        )

        call_command('backfill_presentation_publique_profs')

        prof.refresh_from_db()
        self.assertEqual(prof.presentation_publique, 'نص كتبه المشرف يدويا.')

    def test_prof_sans_donnees_exploitables_reste_vide(self):
        prof = _creer_prof('prof_sans_donnees@zidni.test')
        self.assertEqual(prof.presentation_publique, '')

        call_command('backfill_presentation_publique_profs')

        prof.refresh_from_db()
        self.assertEqual(prof.presentation_publique, '')


class GenererPresentationPubliqueTests(TestCase):
    """'les_deux' (يدرّس الأطفال والبالغين) n'est pas une vraie préférence —
    ne doit jamais apparaître dans le paragraphe généré, pour aucun prof,
    alors qu'une vraie préférence (enfants seuls, ou adultes seuls) doit
    rester affichée."""

    def test_les_deux_napparait_jamais(self):
        prof = _creer_prof('prof_les_deux@zidni.test', type_eleve_preference=['les_deux'])
        self.assertNotIn('يفضل التدريس لـ', generer_presentation_publique(prof))

    def test_preference_enfants_seuls_reste_affichee(self):
        prof = _creer_prof('prof_enfants_seuls@zidni.test', type_eleve_preference=['enfants'])
        texte = generer_presentation_publique(prof)
        self.assertIn('يفضل التدريس لـ', texte)
        self.assertIn('أطفال', texte)

    def test_preference_adultes_seuls_reste_affichee(self):
        prof = _creer_prof('prof_adultes_seuls@zidni.test', type_eleve_preference=['adultes'])
        texte = generer_presentation_publique(prof)
        self.assertIn('يفضل التدريس لـ', texte)
        self.assertIn('بالغون', texte)


class ConnexionEmailMobileRTLTests(TestCase):
    """« Beaucoup de profs bloqués à la connexion » (2026-09-09) : sur mobile RTL,
    le clavier arabe colle des marques directionnelles / espaces invisibles à
    l'e-mail, et iOS met une majuscule à la 1re lettre. La candidature s'était
    faite proprement (chantier 569113f), mais la connexion lisait l'e-mail brut
    → « البريد الإلكتروني أو كلمة المرور غير صحيحة »."""

    def setUp(self):
        self.client = Client(SERVER_NAME='localhost')
        self.user = User.objects.create_user(
            username='prof.mobile@zidni.test', email='prof.mobile@zidni.test',
            password='MotDePasse123', first_name='Prof Mobile', role='prof',
        )
        self.url = reverse('login')

    def _login(self, email):
        return self.client.post(self.url, {'email': email, 'password': 'MotDePasse123'})

    def test_email_propre_fonctionne_toujours(self):
        self.assertEqual(self._login('prof.mobile@zidni.test').status_code, 302)

    def test_marques_directionnelles_invisibles_sont_ignorees(self):
        self.assertEqual(self._login('‏prof.mobile@zidni.test‏').status_code, 302)

    def test_espaces_parasites_sont_ignores(self):
        self.assertEqual(self._login('  prof.mobile@zidni.test﻿ ').status_code, 302)

    def test_casse_differente_est_toleree(self):
        self.assertEqual(self._login('Prof.Mobile@Zidni.test').status_code, 302)

    def test_mauvais_mot_de_passe_refuse_toujours(self):
        reponse = self.client.post(self.url, {'email': 'prof.mobile@zidni.test', 'password': 'faux'})
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, 'غير صحيحة')

    def test_backend_direct_normalise_aussi(self):
        from django.contrib.auth import authenticate
        self.assertEqual(
            authenticate(username='‏ PROF.MOBILE@zidni.test ', password='MotDePasse123'),
            self.user,
        )
