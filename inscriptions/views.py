import datetime
import re

from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from .models import InscriptionEleve, InscriptionProf, TypeAbonnement, get_parametres_inscriptions
from core.utils import envoyer_notification_telegram
from courses.utils import AGE_SEUIL_ADULTE, tranche_age_depuis_naissance
import json

# Anti-double-soumission (chantier du 2026-08-16, séparé du fix de
# duplication des messages) : une candidature avec les mêmes champs-clés
# soumise il y a moins de ce délai par la même personne est traitée comme un
# rejeu du même clic (double clic, onglet dupliqué, re-soumission réseau),
# jamais comme une 2e candidature distincte. Volontairement court et étroit —
# ne touche PAS à _email_bloque_pour_candidature_eleve/_email_deja_utilise
# (règles métier de blocage/partage d'email, inchangées).
FENETRE_ANTI_DOUBLON_SECONDES = 5

CATEGORIE_LABEL = {
    'adulte': 'الطلاب البالغون',
    'enfant': 'الطلاب الأطفال',
    'prof': 'الأساتذة',
}


def _reponse_categorie_fermee(request, categorie):
    """Écran public partagé affiché quand une catégorie d'inscription est
    fermée (chantier du 2026-08-04) — mêmes coordonnées admin que
    dashboard/_contact_administration.html (déjà réutilisé ailleurs), pour
    ne pas inventer un nouveau mécanisme de contact."""
    User = get_user_model()
    return render(request, 'inscriptions/inscription_fermee.html', {
        'categorie_label': CATEGORIE_LABEL[categorie],
        'admins': User.objects.filter(role='admin'),
    })

MESSAGE_EMAIL_DEJA_UTILISE = (
    'هذا البريد الإلكتروني مستخدم بالفعل من طرف حساب آخر أو طلب تسجيل قيد '
    'الدراسة. يرجى استخدام بريد إلكتروني آخر أو التواصل مع المدرسة.'
)

MESSAGE_AGE_NE_CORRESPOND_PAS = {
    'adulte': 'يبدو أنك بالغ (18 سنة فما فوق) — يرجى استخدام نموذج التسجيل الخاص بالبالغين.',
    'enfant': 'يبدو أنك طفل (أقل من 18 سنة) — يرجى استخدام نموذج التسجيل الخاص بالأطفال.',
}

MESSAGE_DATE_NAISSANCE_INVALIDE = 'يرجى إدخال تاريخ ميلاد صحيح.'
# Corrige un 500 en production (Chantier du 2026-08-15) : date_naissance était
# lu deux fois — une fois parsé/validé (date_naissance ci-dessous, utilisé
# uniquement pour la vérification d'âge côté élève) puis, à la création de
# l'objet, RE-LU brut depuis request.POST.get('date_naissance') sans passer
# par cette validation. Un champ vide ou un format non-ISO (navigateur/
# webview sans support natif de <input type="date">, ou le JS existant qui
# laisse volontairement passer un champ vide — voir verifierAgeCategorie()
# dans eleve_formulaire.html) atteignait donc directement
# InscriptionEleve/InscriptionProf.objects.create(), où date_naissance est un
# DateField non-nullable : Django lève une ValidationError non rattrapée en
# tentant d'adapter la valeur pour l'INSERT SQL, jamais interceptée par cette
# vue -> 500 pour l'utilisateur. Reproduit et confirmé (traceback identique)
# avant correctif, pour les 2 formulaires (élève ET prof).


# Longueurs plausibles (min, max) du numéro LOCAL (indicatif exclu, zéro
# initial déjà retiré) par indicatif — couvre la liste déroulante de
# _verification_whatsapp.html. Indicatif absent de cette table (option
# "دولة أخرى" ou saisie libre) : on retombe sur une fourchette générique
# E.164 large plutôt que de bloquer un pays non prévu (Tâche du 2026-08-04,
# Point 3 — "pas une règle fixe marocaine").
INDICATIFS_LONGUEUR_LOCALE = {
    '212': (9, 9),   # Maroc
    '33': (9, 9),    # France
    '34': (9, 9),    # Espagne
    '32': (8, 9),    # Belgique
    '31': (9, 9),    # Pays-Bas
    '39': (9, 10),   # Italie
    '49': (10, 11),  # Allemagne
    '1': (10, 10),   # USA/Canada
    '971': (8, 9),   # Émirats
    '966': (8, 9),   # Arabie Saoudite
}
LONGUEUR_LOCALE_GENERIQUE = (6, 12)

MESSAGE_TELEPHONE_MISMATCH = 'رقم الهاتف وتأكيده غير متطابقين.'
MESSAGE_TELEPHONE_INVALIDE = 'رقم الهاتف غير صحيح — يرجى التحقق من رمز الدولة والرقم المدخل.'


def _chiffres_significatifs(valeur, indicatif=''):
    """Réduit un numéro de téléphone à ses chiffres significatifs SEULS, quel
    que soit le format saisi — c'est la vraie "normalisation" (avant, cette
    fonction ne retirait que les espaces/tirets/parenthèses, ce qui laissait
    "0663394165" et "+212663394165" considérés comme différents alors que
    c'est le même numéro ; corrigé suite au signalement du 2026-08-05).
    Étapes : (1) ne garde que les chiffres (retire +, espaces, tirets,
    parenthèses...), (2) si le résultat commence par l'indicatif du pays
    actuellement sélectionné dans le formulaire, le retire (cas d'un candidat
    qui colle son numéro déjà au format international dans le champ local),
    (3) retire ensuite un éventuel zéro initial (préfixe national marocain
    et autres). indicatif: code pays sans "+" (ex: '212'), optionnel — sans
    lui, seules les étapes (1) et (3) s'appliquent."""
    chiffres = re.sub(r'[^0-9]', '', valeur or '')
    if indicatif and chiffres.startswith(indicatif):
        chiffres = chiffres[len(indicatif):]
    if chiffres.startswith('0'):
        chiffres = chiffres[1:]
    return chiffres


def _construire_et_valider_telephone(request):
    """Combine indicatif_pays(+indicatif_pays_autre)/telephone soumis par
    _verification_whatsapp.html en un numéro complet au format "+<indicatif><local>"
    (compatible tel quel avec le filtre wa_number existant, voir
    dashboard.templatetags.libelles_arabes), revalide la double saisie et le
    format selon le pays choisi — jamais confiance au JS seul (Tâche du
    2026-08-04, Point 3). Renvoie (numero_complet, None) si valide, ou
    (None, message_erreur) sinon."""
    indicatif_choisi = request.POST.get('indicatif_pays', '').strip()
    if indicatif_choisi == 'autre':
        indicatif = re.sub(r'[^0-9]', '', request.POST.get('indicatif_pays_autre', ''))
    else:
        indicatif = re.sub(r'[^0-9]', '', indicatif_choisi)

    telephone_brut = request.POST.get('telephone', '')
    confirmation_brut = request.POST.get('telephone_confirmation', '')

    numero_local = _chiffres_significatifs(telephone_brut, indicatif)
    numero_local_confirmation = _chiffres_significatifs(confirmation_brut, indicatif)

    if numero_local != numero_local_confirmation:
        return None, MESSAGE_TELEPHONE_MISMATCH

    if not indicatif or not numero_local:
        return None, MESSAGE_TELEPHONE_INVALIDE

    longueur_min, longueur_max = INDICATIFS_LONGUEUR_LOCALE.get(indicatif, LONGUEUR_LOCALE_GENERIQUE)
    if not (longueur_min <= len(numero_local) <= longueur_max):
        return None, MESSAGE_TELEPHONE_INVALIDE

    # Garde-fou universel (norme E.164 : 15 chiffres max, indicatif inclus) —
    # couvre aussi le cas "دولة أخرى" où indicatif_pays_autre est une saisie
    # libre non bornée par INDICATIFS_LONGUEUR_LOCALE, pour ne jamais tenter
    # d'insérer une valeur trop longue pour la colonne telephone (varchar(20)).
    if len(indicatif) + len(numero_local) > 15:
        return None, MESSAGE_TELEPHONE_INVALIDE

    return f'+{indicatif}{numero_local}', None


def _email_deja_utilise(email, exclure_user_id=None):
    """Vérifie si cet email est déjà pris par un compte User existant, ou par
    une InscriptionEleve/InscriptionProf encore en attente de validation.
    Empêche les doublons de candidature avant même la création d'un User
    (voir bug connu #5 du CLAUDE.md, corrigé au niveau de la validation admin,
    mais qu'il vaut mieux éviter dès la soumission du formulaire).
    exclure_user_id: permet de vérifier un changement d'email sur un compte
    existant sans que ce compte se bloque lui-même (même email, même user)."""
    User = get_user_model()
    users_qs = User.objects.filter(email=email)
    if exclure_user_id is not None:
        users_qs = users_qs.exclude(id=exclure_user_id)
    if users_qs.exists():
        return True
    if InscriptionEleve.objects.filter(email=email, statut='en_attente').exists():
        return True
    if InscriptionProf.objects.filter(email=email, statut='en_attente').exists():
        return True
    return False


def _email_bloque_pour_candidature_eleve(email):
    """Variante de _email_deja_utilise strictement scopée à la soumission du
    formulaire élève (inscription_eleve_formulaire) — chantier du 2026-08-10
    (partage d'email parent/enfant).

    Pourquoi une fonction séparée plutôt que modifier _email_deja_utilise :
    celle-ci reste utilisée TELLE QUELLE par les 3 autres sites d'appel
    (candidature prof, modification email par مدير, changement d'email
    self-service) — aucun ne doit être affecté par ce chantier.

    Sans ce correctif, le partage d'email serait structurellement
    inatteignable : _email_deja_utilise bloque la soumission d'une 2e
    InscriptionEleve dès qu'une autre existe déjà avec le même email (encore
    en_attente, ou déjà validée en User) — la 2e personne d'une même famille
    ne pourrait jamais soumettre sa candidature, même si admin_valider_eleve
    autoriserait ensuite la validation. Reprend donc EXACTEMENT la même règle
    que le bypass déjà en place à la validation (dashboard.views.
    admin_valider_eleve, via _verifier_conflit_email) : autorise dès qu'AU
    MOINS UN compte élève actif partage déjà cet email (peu importe l'état
    des AUTRES comptes du même groupe — voir `partage_eleve_possible`) —
    bloque toujours pour un conflit prof, admin/مشرف, ou un groupe sans aucun
    élève actif, exactement comme avant ce chantier."""
    from dashboard.views import _verifier_conflit_email

    conflit = _verifier_conflit_email(email)
    if conflit['conflit']:
        if not conflit['partage_eleve_possible']:
            return True

    # Une autre candidature PROF encore en attente avec cet email : hors scope
    # (le partage reste réservé aux paires élève/élève), toujours bloqué.
    if InscriptionProf.objects.filter(email=email, statut='en_attente').exists():
        return True

    # Une autre InscriptionEleve encore en attente avec cet email : c'est
    # justement le cas qu'on autorise (2e candidature élève, même famille).
    return False


def inscription_eleve_choix(request):
    return render(request, 'inscriptions/eleve_choix.html')


def inscription_eleve_formulaire(request, type_age):
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    # Garde AVANT tout traitement GET/POST — une requête directe (bouton
    # normal, POST manipulé, script) sur une catégorie fermée ne doit jamais
    # atteindre la logique de création, pas seulement voir le bouton caché
    # côté affichage (chantier du 2026-08-04).
    parametres = get_parametres_inscriptions()
    if type_age == 'adulte' and not parametres.ouverte_eleve_adulte:
        return _reponse_categorie_fermee(request, 'adulte')
    if type_age == 'enfant' and not parametres.ouverte_eleve_enfant:
        return _reponse_categorie_fermee(request, 'enfant')

    types_abonnement_json = json.dumps([{
        'code': t.code,
        'label': t.label,
        'prix': str(t.prix),
    } for t in TypeAbonnement.objects.filter(est_actif=True, cible_age__in=[type_age, 'les_deux']).order_by('ordre')])

    contexte_grille = {
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'age_seuil_adulte': AGE_SEUIL_ADULTE,
    }

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        disponibilites = request.POST.getlist('dispo')
        date_naissance_str = request.POST.get('date_naissance', '')

        # _email_bloque_pour_candidature_eleve (pas _email_deja_utilise) : seul
        # ce formulaire autorise un email déjà pris par un AUTRE compte/une
        # autre candidature élève (chantier du 2026-08-10, partage parent/
        # enfant) — voir sa docstring dans ce fichier. Bloque toujours pour
        # prof/admin/مشرف/orphelin/archivé, exactement comme avant.
        if _email_bloque_pour_candidature_eleve(email):
            return render(request, 'inscriptions/eleve_formulaire.html', {
                'type_age': type_age,
                'types_abonnement_json': types_abonnement_json,
                'erreur_email': MESSAGE_EMAIL_DEJA_UTILISE,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        telephone_complet, erreur_telephone = _construire_et_valider_telephone(request)
        if erreur_telephone:
            return render(request, 'inscriptions/eleve_formulaire.html', {
                'type_age': type_age,
                'types_abonnement_json': types_abonnement_json,
                'erreur_telephone': erreur_telephone,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        # Garde-fou serveur, indépendant du JS de eleve_formulaire.html: même
        # une requête POST directe (JS désactivé, script, curl) ne peut pas
        # créer une InscriptionEleve dont la catégorie choisie (type_age, le
        # paramètre d'URL) contredit l'âge réel calculé depuis date_naissance.
        try:
            date_naissance = datetime.date.fromisoformat(date_naissance_str)
        except ValueError:
            date_naissance = None

        # Corrige le 500 de production (voir MESSAGE_DATE_NAISSANCE_INVALIDE
        # ci-dessus) : un champ vide/invalide était auparavant silencieusement
        # toléré ICI (date_naissance=None ne faisait que sauter la
        # vérification d'âge juste en dessous) puis provoquait un crash plus
        # loin, à la création de l'objet. Bloqué explicitement maintenant,
        # même pattern que erreur_email/erreur_telephone/erreur_age juste
        # au-dessus/en-dessous.
        if date_naissance is None:
            return render(request, 'inscriptions/eleve_formulaire.html', {
                'type_age': type_age,
                'types_abonnement_json': types_abonnement_json,
                'erreur_date_naissance': MESSAGE_DATE_NAISSANCE_INVALIDE,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        categorie_reelle = tranche_age_depuis_naissance(date_naissance)
        if categorie_reelle != type_age:
            return render(request, 'inscriptions/eleve_formulaire.html', {
                'type_age': type_age,
                'types_abonnement_json': types_abonnement_json,
                'erreur_age': MESSAGE_AGE_NE_CORRESPOND_PAS[categorie_reelle],
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        # Garde anti-double-soumission : une InscriptionEleve avec les mêmes
        # email+nom+date_naissance vient d'être créée il y a quelques
        # secondes -> on renvoie directement vers la confirmation sans
        # insérer un doublon ni renvoyer une 2e notification Telegram.
        seuil_anti_doublon = timezone.now() - datetime.timedelta(seconds=FENETRE_ANTI_DOUBLON_SECONDES)
        if InscriptionEleve.objects.filter(
            email=email, nom=request.POST.get('nom'), date_naissance=date_naissance,
            date_soumission__gte=seuil_anti_doublon,
        ).exists():
            return redirect('inscription_confirmation')

        inscription = InscriptionEleve.objects.create(
            nom=request.POST.get('nom'),
            nom_parent=request.POST.get('nom_parent', ''),
            date_naissance=date_naissance,
            sexe=request.POST.get('sexe'),
            telephone=telephone_complet,
            email=email,
            job_actuel=request.POST.get('job_actuel', '').strip(),
            programme=request.POST.get('programme'),
            riwaya=request.POST.get('riwaya'),
            outil=request.POST.get('outil'),
            abonnement=request.POST.get('abonnement'),
            accepte_conditions=request.POST.get('accepte_conditions') == 'oui',
            remarques=request.POST.get('remarques', ''),
            disponibilites_libres=request.POST.get('disponibilites_libres', ''),
            disponibilites=disponibilites,
        )
        lien_fiche = request.build_absolute_uri(
            reverse('admin_inscription_eleve_detail', args=[inscription.id])
        )
        if date_naissance is not None:
            categorie_label = 'بالغ' if tranche_age_depuis_naissance(date_naissance) == 'adulte' else 'طفل'
        else:
            categorie_label = 'غير محدد'
        envoyer_notification_telegram(
            f'📥 طلب تسجيل جديد — طالب ({categorie_label})\n'
            f'الاسم: {inscription}\n'
            f'تاريخ التقديم: {inscription.date_soumission.strftime("%Y-%m-%d %H:%M")}\n'
            f'رابط الملف: {lien_fiche}'
        )
        return redirect('inscription_confirmation')

    return render(request, 'inscriptions/eleve_formulaire.html', {
        'type_age': type_age,
        'types_abonnement_json': types_abonnement_json,
        'valeurs_form': set(),
        **contexte_grille,
    })


def inscription_confirmation(request):
    return render(request, 'inscriptions/confirmation.html')

def inscription_prof(request):
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    # Même garde que inscription_eleve_formulaire — voir son commentaire.
    if not get_parametres_inscriptions().ouverte_prof:
        return _reponse_categorie_fermee(request, 'prof')

    contexte_grille = {
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
    }

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        disponibilites = request.POST.getlist('dispo')
        compte_bancaire = request.POST.get('compte_bancaire', '').strip()
        rib = request.POST.get('rib', '').strip()
        agence_bancaire = request.POST.get('agence_bancaire', '').strip()
        job_actuel = request.POST.get('job_actuel', '').strip()
        audio_enregistrement = request.FILES.get('audio_enregistrement')

        # Corrige un 500 en production — voir MESSAGE_DATE_NAISSANCE_INVALIDE
        # (même bug qu'inscription_eleve_formulaire, jamais de garde ici
        # avant ce correctif) : un champ vide/invalide était envoyé tel quel
        # à InscriptionProf.objects.create() (DateField non-nullable) et
        # provoquait une ValidationError non rattrapée -> 500.
        try:
            date_naissance = datetime.date.fromisoformat(request.POST.get('date_naissance', ''))
        except ValueError:
            date_naissance = None

        if _email_deja_utilise(email):
            return render(request, 'inscriptions/prof_formulaire.html', {
                'erreur_email': MESSAGE_EMAIL_DEJA_UTILISE,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        telephone_complet, erreur_telephone = _construire_et_valider_telephone(request)
        if erreur_telephone:
            return render(request, 'inscriptions/prof_formulaire.html', {
                'erreur_telephone': erreur_telephone,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        # Pas de Django Forms dans ce projet (request.POST.get() brut) — le HTML5
        # required peut être contourné, donc on revalide ces champs côté serveur
        # avant toute création (voir bug RIB/compte bancaire vides malgré le
        # champ obligatoire en apparence, et l'audio qui doit devenir obligatoire).
        champs_manquants = []
        if not compte_bancaire:
            champs_manquants.append('رقم الحساب البنكي')
        if not rib:
            champs_manquants.append('RIB')
        if not agence_bancaire:
            champs_manquants.append('اسم الوكالة البنكية')
        if not job_actuel:
            champs_manquants.append('العمل الحالي')
        if not audio_enregistrement:
            champs_manquants.append('التسجيل الصوتي')
        if date_naissance is None:
            champs_manquants.append('تاريخ الميلاد')

        if champs_manquants:
            return render(request, 'inscriptions/prof_formulaire.html', {
                'erreur_champs': 'الحقول التالية إلزامية ولم يتم تعبئتها: ' + '، '.join(champs_manquants),
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        # Garde anti-double-soumission — même principe que
        # inscription_eleve_formulaire ci-dessus, clé email+nom+prenom.
        seuil_anti_doublon = timezone.now() - datetime.timedelta(seconds=FENETRE_ANTI_DOUBLON_SECONDES)
        if InscriptionProf.objects.filter(
            email=email, nom=request.POST.get('nom'), prenom=request.POST.get('prenom'),
            date_soumission__gte=seuil_anti_doublon,
        ).exists():
            return redirect('inscription_confirmation')

        inscription = InscriptionProf.objects.create(
            nom=request.POST.get('nom'),
            prenom=request.POST.get('prenom'),
            date_naissance=date_naissance,
            telephone=telephone_complet,
            ville=request.POST.get('ville'),
            statut_familial=request.POST.get('statut_familial'),
            job_actuel=job_actuel,
            certifications=request.POST.get('certifications'),
            niveau_memorisation=request.POST.get('niveau_memorisation'),
            parcours_scolaire=request.POST.get('parcours_scolaire'),
            parcours_enseignant=request.POST.get('parcours_enseignant'),
            gestion_eleve_faible=request.POST.get('gestion_eleve_faible'),
            gestion_eleve_absent=request.POST.get('gestion_eleve_absent'),
            email=email,
            langues=request.POST.getlist('langues'),
            outils_maitrises=request.POST.getlist('outils'),
            type_eleve_preference=request.POST.getlist('type_eleve'),
            contrainte_genre=request.POST.getlist('contrainte_genre'),
            compte_bancaire=compte_bancaire,
            rib=rib,
            agence_bancaire=agence_bancaire,
            audio_enregistrement=audio_enregistrement,
            disponibilites=disponibilites,
        )
        lien_fiche = request.build_absolute_uri(
            reverse('admin_inscription_prof_detail', args=[inscription.id])
        )
        envoyer_notification_telegram(
            f'📥 طلب تسجيل جديد — أستاذ\n'
            f'الاسم: {inscription}\n'
            f'تاريخ التقديم: {inscription.date_soumission.strftime("%Y-%m-%d %H:%M")}\n'
            f'رابط الملف: {lien_fiche}'
        )
        return redirect('inscription_confirmation')

    return render(request, 'inscriptions/prof_formulaire.html', {
        'valeurs_form': set(),
        **contexte_grille,
    })