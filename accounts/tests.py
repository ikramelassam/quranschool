from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from accounts.models import Prof
from accounts.services import generer_presentation_publique

User = get_user_model()


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
