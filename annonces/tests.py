import datetime

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Eleve
from inscriptions.models import InscriptionEleve
from courses.utils import cible_annonce_pour_eleve
from .models import Annonce, LectureAnnonce
from .services import annonces_visibles_pour_eleve, annonces_non_lues_pour_eleve, marquer_annonces_lues

MOT_DE_PASSE = 'xX!test12345'


def _date_naissance_pour_age(age):
    """Date de naissance donnant exactement `age` ans aujourd'hui (même jour
    du mois, pour éviter tout effet de bord février/29)."""
    aujourdhui = timezone.localdate()
    return aujourdhui.replace(year=aujourdhui.year - age)


def _creer_admin(email='admin_annonces@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مدير', last_name='تجريبي', role='admin', doit_changer_mot_de_passe=False,
    )


def _creer_mshrif(email='mshrif_annonces@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مشرف', last_name='تجريبي', role='mshrif', doit_changer_mot_de_passe=False,
    )


def _creer_inscription(email, sexe, age):
    return InscriptionEleve.objects.create(
        nom='طالب تجريبي', date_naissance=_date_naissance_pour_age(age), sexe=sexe,
        telephone='0600000000', email=email, programme='hifz', riwaya='hafs',
        outil='whatsapp', abonnement='groupe_1mois',
    )


def _creer_eleve(email, sexe, age, statut='actif'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    inscription = _creer_inscription(email, sexe, age)
    return Eleve.objects.create(user=u, sexe=sexe, statut=statut, inscription=inscription)


def _creer_eleve_sans_naissance(email):
    """Élève sans inscription liée — âge inconnu (cas limite explicitement
    couvert par cible_annonce_pour_eleve : None, jamais une supposition)."""
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme', statut='actif')


class CibleAnnoncePourEleveTests(TestCase):
    """courses.utils.cible_annonce_pour_eleve — les 6 cas demandés par le client."""

    def test_femme_18_ans_ou_plus_femmes_adultes(self):
        eleve = _creer_eleve('f18@zidni.test', 'femme', 20)
        self.assertEqual(cible_annonce_pour_eleve(eleve), 'femmes_adultes')

    def test_homme_18_ans_ou_plus_hommes_adultes(self):
        eleve = _creer_eleve('h18@zidni.test', 'homme', 25)
        self.assertEqual(cible_annonce_pour_eleve(eleve), 'hommes_adultes')

    def test_femme_moins_18_ans_mineurs(self):
        eleve = _creer_eleve('f10@zidni.test', 'femme', 10)
        self.assertEqual(cible_annonce_pour_eleve(eleve), 'mineurs')

    def test_homme_moins_18_ans_mineurs(self):
        eleve = _creer_eleve('h10@zidni.test', 'homme', 10)
        self.assertEqual(cible_annonce_pour_eleve(eleve), 'mineurs')

    def test_exactement_18_ans_est_adulte(self):
        eleve_f = _creer_eleve('f18exact@zidni.test', 'femme', 18)
        eleve_h = _creer_eleve('h18exact@zidni.test', 'homme', 18)
        self.assertEqual(cible_annonce_pour_eleve(eleve_f), 'femmes_adultes')
        self.assertEqual(cible_annonce_pour_eleve(eleve_h), 'hommes_adultes')

    def test_17_ans_et_364_jours_reste_mineur(self):
        # Un jour avant le 18e anniversaire : toujours mineur.
        u = User.objects.create_user(
            username='veille18@zidni.test', email='veille18@zidni.test', password=MOT_DE_PASSE,
            role='eleve', doit_changer_mot_de_passe=False,
        )
        aujourdhui = timezone.localdate()
        naissance = aujourdhui.replace(year=aujourdhui.year - 18) + datetime.timedelta(days=1)
        inscription = InscriptionEleve.objects.create(
            nom='طالب', date_naissance=naissance, sexe='homme', telephone='0600000000',
            email='veille18@zidni.test', programme='hifz', riwaya='hafs', outil='whatsapp',
            abonnement='groupe_1mois',
        )
        eleve = Eleve.objects.create(user=u, sexe='homme', statut='actif', inscription=inscription)
        self.assertEqual(cible_annonce_pour_eleve(eleve), 'mineurs')

    def test_age_inconnu_retourne_none(self):
        eleve = _creer_eleve_sans_naissance('sansnaissance@zidni.test')
        self.assertIsNone(cible_annonce_pour_eleve(eleve))


class AnnoncesVisibilitePourEleveTests(TestCase):
    """Une annonce n'atteint QUE sa catégorie exacte — jamais les 2 autres."""

    def setUp(self):
        self.annonce_femmes = Annonce.objects.create(titre='F', contenu='...', cible='femmes_adultes')
        self.annonce_hommes = Annonce.objects.create(titre='H', contenu='...', cible='hommes_adultes')
        self.annonce_mineurs = Annonce.objects.create(titre='M', contenu='...', cible='mineurs')

        self.femme_adulte = _creer_eleve('vf@zidni.test', 'femme', 22)
        self.homme_adulte = _creer_eleve('vh@zidni.test', 'homme', 22)
        self.fille_mineure = _creer_eleve('vfm@zidni.test', 'femme', 10)
        self.garcon_mineur = _creer_eleve('vhm@zidni.test', 'homme', 10)

    def test_femme_adulte_ne_voit_que_lannonce_femmes(self):
        visibles = set(annonces_visibles_pour_eleve(self.femme_adulte).values_list('titre', flat=True))
        self.assertEqual(visibles, {'F'})

    def test_homme_adulte_ne_voit_que_lannonce_hommes(self):
        visibles = set(annonces_visibles_pour_eleve(self.homme_adulte).values_list('titre', flat=True))
        self.assertEqual(visibles, {'H'})

    def test_fille_mineure_voit_lannonce_mineurs_pas_femmes(self):
        visibles = set(annonces_visibles_pour_eleve(self.fille_mineure).values_list('titre', flat=True))
        self.assertEqual(visibles, {'M'})

    def test_garcon_mineur_voit_la_meme_annonce_mineurs_que_la_fille(self):
        # Règle explicite du client : PAS de séparation garçons/filles mineurs.
        visibles_fille = set(annonces_visibles_pour_eleve(self.fille_mineure).values_list('id', flat=True))
        visibles_garcon = set(annonces_visibles_pour_eleve(self.garcon_mineur).values_list('id', flat=True))
        self.assertEqual(visibles_fille, visibles_garcon)
        self.assertEqual(visibles_garcon, {self.annonce_mineurs.id})

    def test_annonce_inactive_najamais_visible(self):
        self.annonce_femmes.active = False
        self.annonce_femmes.save(update_fields=['active'])
        visibles = set(annonces_visibles_pour_eleve(self.femme_adulte).values_list('titre', flat=True))
        self.assertEqual(visibles, set())

    def test_age_inconnu_najamais_aucune_annonce(self):
        eleve = _creer_eleve_sans_naissance('inconnu2@zidni.test')
        self.assertEqual(annonces_visibles_pour_eleve(eleve).count(), 0)


class MarquerLuTests(TestCase):
    def test_marquer_lu_puis_non_lues_diminue(self):
        annonce = Annonce.objects.create(titre='A', contenu='...', cible='hommes_adultes')
        eleve = _creer_eleve('lu1@zidni.test', 'homme', 22)
        self.assertEqual(annonces_non_lues_pour_eleve(eleve, eleve.user), 1)
        marquer_annonces_lues([annonce], eleve.user)
        self.assertEqual(annonces_non_lues_pour_eleve(eleve, eleve.user), 0)
        self.assertEqual(LectureAnnonce.objects.filter(annonce=annonce, user=eleve.user).count(), 1)

    def test_marquer_lu_est_idempotent(self):
        annonce = Annonce.objects.create(titre='A', contenu='...', cible='hommes_adultes')
        eleve = _creer_eleve('lu2@zidni.test', 'homme', 22)
        marquer_annonces_lues([annonce], eleve.user)
        marquer_annonces_lues([annonce], eleve.user)
        self.assertEqual(LectureAnnonce.objects.filter(annonce=annonce, user=eleve.user).count(), 1)


class VuesAnnoncesTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.eleve = _creer_eleve('vue1@zidni.test', 'femme', 22)

    def _client_connecte(self, user):
        client = Client(SERVER_NAME='localhost')
        client.force_login(user)
        return client

    def test_admin_peut_creer_une_annonce(self):
        client = self._client_connecte(self.admin)
        reponse = client.post(reverse('annonce_ajouter'), {
            'titre': 'إعلان تجريبي', 'contenu': 'محتوى', 'cible': 'femmes_adultes',
        })
        self.assertEqual(reponse.status_code, 302)
        annonce = Annonce.objects.get(titre='إعلان تجريبي')
        self.assertEqual(annonce.cree_par, self.admin)
        self.assertEqual(annonce.cible, 'femmes_adultes')

    def test_mshrif_peut_aussi_creer_une_annonce(self):
        client = self._client_connecte(self.mshrif)
        reponse = client.post(reverse('annonce_ajouter'), {
            'titre': 'إعلان مشرف', 'contenu': 'محتوى', 'cible': 'mineurs',
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Annonce.objects.filter(titre='إعلان مشرف', cree_par=self.mshrif).exists())

    def test_eleve_ne_peut_pas_creer_une_annonce(self):
        client = self._client_connecte(self.eleve.user)
        reponse = client.post(reverse('annonce_ajouter'), {
            'titre': 'محاولة تسلل', 'contenu': 'محتوى', 'cible': 'femmes_adultes',
        })
        self.assertFalse(Annonce.objects.filter(titre='محاولة تسلل').exists())
        self.assertNotEqual(reponse.status_code, 200)

    def test_creation_sans_cible_valide_refusee(self):
        client = self._client_connecte(self.admin)
        client.post(reverse('annonce_ajouter'), {
            'titre': 'بدون فئة', 'contenu': 'محتوى', 'cible': 'nimporte_quoi',
        })
        self.assertFalse(Annonce.objects.filter(titre='بدون فئة').exists())

    def test_toggle_desactive_puis_reactive(self):
        annonce = Annonce.objects.create(titre='X', contenu='...', cible='femmes_adultes')
        client = self._client_connecte(self.admin)
        client.post(reverse('annonce_toggle', args=[annonce.id]))
        annonce.refresh_from_db()
        self.assertFalse(annonce.active)
        client.post(reverse('annonce_toggle', args=[annonce.id]))
        annonce.refresh_from_db()
        self.assertTrue(annonce.active)

    def test_eleve_annonces_marque_comme_lu_a_la_visite(self):
        annonce = Annonce.objects.create(titre='Y', contenu='...', cible='femmes_adultes')
        client = self._client_connecte(self.eleve.user)
        self.assertFalse(LectureAnnonce.objects.filter(annonce=annonce, user=self.eleve.user).exists())
        reponse = client.get(reverse('eleve_annonces'))
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(LectureAnnonce.objects.filter(annonce=annonce, user=self.eleve.user).exists())

    def test_eleve_ne_voit_pas_les_annonces_dune_autre_categorie_sur_sa_page(self):
        Annonce.objects.create(titre='Pour hommes', contenu='...', cible='hommes_adultes')
        annonce_femmes = Annonce.objects.create(titre='Pour femmes', contenu='...', cible='femmes_adultes')
        client = self._client_connecte(self.eleve.user)
        reponse = client.get(reverse('eleve_annonces'))
        titres = {a.titre for a in reponse.context['annonces']}
        self.assertEqual(titres, {'Pour femmes'})

    def test_badge_non_lu_dans_le_context_processor(self):
        Annonce.objects.create(titre='Badge', contenu='...', cible='femmes_adultes')
        client = self._client_connecte(self.eleve.user)
        reponse = client.get(reverse('dashboard_eleve'))
        self.assertEqual(reponse.context['annonces_non_lues_total'], 1)


class CanauxTests(TestCase):
    """Chantier "canaux de diffusion" (2026-08-16) — annonces_gestion devient
    la page de sélection des 3 canaux, annonces_canal_detail le fil de
    publications d'UN canal."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.eleve = _creer_eleve('canaux1@zidni.test', 'femme', 22)

    def _client_connecte(self, user):
        client = Client(SERVER_NAME='localhost')
        client.force_login(user)
        return client

    def test_annonces_gestion_expose_les_3_canaux(self):
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonces_gestion'))
        codes = {c['code'] for c in reponse.context['canaux']}
        self.assertEqual(codes, {'femmes_adultes', 'hommes_adultes', 'mineurs'})

    def test_canal_detail_ne_liste_que_ses_propres_publications(self):
        Annonce.objects.create(titre='F', contenu='...', cible='femmes_adultes')
        Annonce.objects.create(titre='H', contenu='...', cible='hommes_adultes')
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonces_canal_detail', args=['femmes_adultes']))
        titres = {a.titre for a in reponse.context['annonces']}
        self.assertEqual(titres, {'F'})

    def test_canal_detail_code_invalide_404(self):
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonces_canal_detail', args=['nimporte_quoi']))
        self.assertEqual(reponse.status_code, 404)

    def test_eleve_ne_peut_pas_acceder_a_annonces_canal_detail(self):
        client = self._client_connecte(self.eleve.user)
        reponse = client.get(reverse('annonces_canal_detail', args=['femmes_adultes']))
        self.assertNotEqual(reponse.status_code, 200)

    def test_annonce_ajouter_depuis_un_canal_y_retourne(self):
        client = self._client_connecte(self.admin)
        reponse = client.post(reverse('annonce_ajouter'), {
            'titre': 'من داخل القناة', 'contenu': 'محتوى', 'cible': 'mineurs',
        })
        self.assertRedirects(reponse, reverse('annonces_canal_detail', args=['mineurs']))

    def test_toggle_redirige_vers_le_canal_de_lannonce(self):
        annonce = Annonce.objects.create(titre='X', contenu='...', cible='hommes_adultes')
        client = self._client_connecte(self.admin)
        reponse = client.post(reverse('annonce_toggle', args=[annonce.id]))
        self.assertRedirects(reponse, reverse('annonces_canal_detail', args=['hommes_adultes']))

    def test_eleve_annonces_expose_le_canal_de_lelevel(self):
        client = self._client_connecte(self.eleve.user)
        reponse = client.get(reverse('eleve_annonces'))
        self.assertEqual(reponse.context['canal']['code'], 'femmes_adultes')

    def test_aucun_abonne_expose_dans_le_html(self):
        """Point C5 : jamais de liste d'abonnés/membres dans un canal —
        contrairement au chat, la page canal_detail ne doit fournir aucun nom
        d'élève ni aucune coordonnée."""
        Annonce.objects.create(titre='F', contenu='...', cible='femmes_adultes')
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonces_canal_detail', args=['femmes_adultes']))
        contenu = reponse.content.decode('utf-8')
        self.assertNotIn(self.eleve.user.email, contenu)
        self.assertNotIn('members', contenu.lower())

    def test_flux_recent_absent_si_aucune_publication_nulle_part(self):
        """Redesign du 2026-08-16 : sans AUCUNE publication (dans aucun des 3
        canaux), le bloc "آخر النشاط عبر القنوات" ne doit pas s'afficher du
        tout (pas de bloc vide sous les cards)."""
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonces_gestion'))
        self.assertEqual(list(reponse.context['dernieres_publications']), [])
        self.assertNotIn('آخر النشاط عبر القنوات', reponse.content.decode('utf-8'))

    def test_flux_recent_liste_les_publications_de_tous_les_canaux(self):
        Annonce.objects.create(titre='F', contenu='...', cible='femmes_adultes')
        Annonce.objects.create(titre='H', contenu='...', cible='hommes_adultes')
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonces_gestion'))
        titres = {a.titre for a in reponse.context['dernieres_publications']}
        self.assertEqual(titres, {'F', 'H'})

    def test_etat_vide_dun_canal_affiche_le_cta_de_publication(self):
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonces_canal_detail', args=['mineurs']))
        self.assertContains(reponse, 'نشر إعلان جديد')
        self.assertNotContains(reponse, '0 منشور')


class PiecesJointesAnnoncesTests(TestCase):
    """Médias d'une publication (image/vidéo/audio/document) — Point C9."""

    def setUp(self):
        self.admin = _creer_admin()
        self.client = Client(SERVER_NAME='localhost')
        self.client.force_login(self.admin)

    def test_publication_avec_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('photo.jpg', b'\xff\xd8\xff\xe0contenu-image-factice', content_type='image/jpeg')
        reponse = self.client.post(reverse('annonce_ajouter'), {
            'titre': 'مع صورة', 'contenu': '...', 'cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        annonce = Annonce.objects.get(titre='مع صورة')
        self.assertEqual(annonce.type_fichier, 'image')
        annonce.fichier.delete(save=False)

    def test_publication_avec_video(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('clip.mp4', b'contenu-video-factice', content_type='video/mp4')
        reponse = self.client.post(reverse('annonce_ajouter'), {
            'titre': 'مع فيديو', 'contenu': '...', 'cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        annonce = Annonce.objects.get(titre='مع فيديو')
        self.assertEqual(annonce.type_fichier, 'video')
        annonce.fichier.delete(save=False)

    def test_publication_avec_audio(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('note.mp3', b'contenu-audio-factice', content_type='audio/mpeg')
        reponse = self.client.post(reverse('annonce_ajouter'), {
            'titre': 'مع صوت', 'contenu': '...', 'cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        annonce = Annonce.objects.get(titre='مع صوت')
        self.assertEqual(annonce.type_fichier, 'audio')
        annonce.fichier.delete(save=False)

    def test_publication_avec_audio_enregistre_en_direct(self):
        """Régression (2026-08-16) : le bouton "صوت" de canal_detail.html
        enregistre désormais en direct (MediaRecorder, comme le chat) et
        produit un blob .webm — l'extension doit être acceptée côté serveur,
        pas seulement les fichiers audio pré-existants (.mp3 etc.)."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('voice-123.webm', b'\x1a\x45\xdf\xa3contenu-audio-factice', content_type='audio/webm')
        reponse = self.client.post(reverse('annonce_ajouter'), {
            'titre': 'تسجيل صوتي مباشر', 'contenu': '...', 'cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        annonce = Annonce.objects.get(titre='تسجيل صوتي مباشر')
        self.assertEqual(annonce.type_fichier, 'audio')
        annonce.fichier.delete(save=False)

    def test_video_webm_reste_video_malgre_lambiguite_avec_laudio(self):
        """.webm est la SEULE extension partagée entre 'video' et 'audio'
        (voir annonces.services.deduire_type_fichier) — un vrai fichier
        vidéo .webm (content-type 'video/webm', pas 'audio/webm') doit
        rester classé 'video', pas être aspiré vers 'audio' par erreur."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('clip.webm', b'\x1a\x45\xdf\xa3contenu-video-factice', content_type='video/webm')
        reponse = self.client.post(reverse('annonce_ajouter'), {
            'titre': 'فيديو webm', 'contenu': '...', 'cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        annonce = Annonce.objects.get(titre='فيديو webm')
        self.assertEqual(annonce.type_fichier, 'video')
        annonce.fichier.delete(save=False)

    def test_publication_avec_pdf(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 contenu factice', content_type='application/pdf')
        reponse = self.client.post(reverse('annonce_ajouter'), {
            'titre': 'مع مستند', 'contenu': '...', 'cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertEqual(reponse.status_code, 302)
        annonce = Annonce.objects.get(titre='مع مستند')
        self.assertEqual(annonce.type_fichier, 'document')
        annonce.fichier.delete(save=False)

    def test_extension_non_autorisee_refusee(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('script.exe', b'MZ', content_type='application/octet-stream')
        self.client.post(reverse('annonce_ajouter'), {
            'titre': 'محاولة رفع خبيث', 'contenu': '...', 'cible': 'femmes_adultes', 'fichier': fichier,
        })
        self.assertFalse(Annonce.objects.filter(titre='محاولة رفع خبيث').exists())


class SecuritePieceJointeAnnoncesTests(TestCase):
    """Point C14 : le fichier d'une publication n'est accessible qu'aux
    utilisateurs autorisés à voir CETTE publication — même patron IDOR que
    chat_fichier."""

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.admin = _creer_admin()
        self.femme = _creer_eleve('secu_f@zidni.test', 'femme', 22)
        self.homme = _creer_eleve('secu_h@zidni.test', 'homme', 22)
        self.annonce_femmes = Annonce.objects.create(
            titre='F', contenu='...', cible='femmes_adultes',
            fichier=SimpleUploadedFile('photo.jpg', b'\xff\xd8\xff\xe0img', content_type='image/jpeg'),
            type_fichier='image',
        )

    def tearDown(self):
        self.annonce_femmes.fichier.delete(save=False)

    def _client_connecte(self, user):
        client = Client(SERVER_NAME='localhost')
        client.force_login(user)
        return client

    def test_eleve_du_meme_canal_peut_acceder_au_fichier(self):
        client = self._client_connecte(self.femme.user)
        reponse = client.get(reverse('annonce_fichier', args=[self.annonce_femmes.id]))
        self.assertEqual(reponse.status_code, 302)  # redirige vers l'URL réelle du storage

    def test_eleve_dun_autre_canal_ne_peut_pas_acceder_au_fichier(self):
        client = self._client_connecte(self.homme.user)
        reponse = client.get(reverse('annonce_fichier', args=[self.annonce_femmes.id]))
        self.assertEqual(reponse.status_code, 403)

    def test_admin_peut_toujours_acceder_au_fichier(self):
        client = self._client_connecte(self.admin)
        reponse = client.get(reverse('annonce_fichier', args=[self.annonce_femmes.id]))
        self.assertEqual(reponse.status_code, 302)

    def test_annonce_masquee_inaccessible_meme_pour_son_canal(self):
        self.annonce_femmes.active = False
        self.annonce_femmes.save(update_fields=['active'])
        client = self._client_connecte(self.femme.user)
        reponse = client.get(reverse('annonce_fichier', args=[self.annonce_femmes.id]))
        self.assertEqual(reponse.status_code, 403)
