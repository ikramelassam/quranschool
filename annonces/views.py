import datetime

from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.decorators import role_required
from .models import Annonce
from .services import (
    annonces_visibles_pour_eleve, marquer_annonces_lues, effectif_par_cible,
    canal_pour_code, canal_pour_eleve, canaux_avec_apercu, dernieres_publications,
    peut_voir_annonce, valider_piece_jointe,
)

CIBLES_VALIDES = {code for code, _ in Annonce.CIBLE_CHOICES}

# Anti-double-soumission (chantier du 2026-08-16, séparé du fix de
# duplication des messages) : un même contenu (titre+contenu+cible) publié
# par le même utilisateur il y a moins de ce délai est traité comme un rejeu
# du même clic (double clic, onglet dupliqué, re-soumission réseau) plutôt
# que comme une 2e publication distincte. Volontairement court — ne bloque
# jamais une vraie republication délibérée du même texte quelques minutes
# plus tard.
FENETRE_ANTI_DOUBLON_SECONDES = 5


def _base_template_admin_ou_mshrif(request):
    """Même patron que courses.views._base_template_admin_ou_mshrif /
    dashboard.views._base_template_admin_ou_mshrif : pages de gestion
    partagées مدير (édition) / مشرف (édition aussi, ici — les deux créent des
    annonces, contrairement aux pages purement en lecture seule pour مشرف)."""
    return 'dashboard/base_mshrif.html' if request.user.role == 'mshrif' else 'dashboard/base_admin.html'


def _contexte_base_mshrif(request):
    """Badge sidebar des candidatures en attente — nécessaire uniquement pour
    que base_mshrif.html s'affiche correctement (même contenu que la
    fonction homonyme de courses.views/dashboard.views, dupliquée à
    l'identique plutôt que factorisée dans un 4e endroit pour un si petit
    bloc — voir ces deux autres fonctions pour le même choix)."""
    if request.user.role != 'mshrif':
        return {}
    from inscriptions.models import InscriptionProf
    return {'nb_demandes_en_attente': InscriptionProf.objects.filter(statut='validee_directeur').count()}


@role_required('admin', 'mshrif')
def annonces_gestion(request):
    """Page "📢 الإعلانات" (مدير/مشرف) — Chantier "canaux de diffusion" du
    2026-08-16 : ce n'est plus un formulaire+liste unique, mais la page de
    SÉLECTION des 3 canaux (Femmes/Hommes/Mineurs), chacun ouvrant sur son
    propre fil de publications (annonces_canal_detail ci-dessous). Mental
    model WhatsApp/Telegram Channels — jamais un select générique."""
    context = {
        'canaux': canaux_avec_apercu(),
        'dernieres_publications': dernieres_publications(),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'annonces/admin_annonces.html', context)


@role_required('admin', 'mshrif')
def annonces_canal_detail(request, cible):
    """Fil de publications d'UN canal + formulaire "نشر جديد" qui publie
    directement dans CE canal (cible déjà fixée, pas de sélecteur à
    re-choisir — Point C7 du chantier canaux). 404 si `cible` n'est pas
    l'une des 3 valeurs réelles (Annonce.CIBLE_CHOICES) : jamais une 4e
    catégorie inventée via l'URL."""
    canal = canal_pour_code(cible)
    if canal is None:
        raise Http404("قناة غير موجودة.")

    context = {
        'canal': canal,
        'annonces': Annonce.objects.filter(cible=cible).select_related('cree_par'),
        'effectif': effectif_par_cible().get(cible, 0),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'annonces/canal_detail.html', context)


@role_required('admin', 'mshrif')
def annonce_ajouter(request):
    if request.method != 'POST':
        return redirect('annonces_gestion')

    titre = request.POST.get('titre', '').strip()
    contenu = request.POST.get('contenu', '').strip()
    cible = request.POST.get('cible', '')
    fichier = request.FILES.get('fichier')
    # Redirection : reste dans le canal d'où le formulaire a été soumis
    # (Point C7 : "+ Nouvelle publication" publie dans le canal courant,
    # sans renvoyer l'utilisateur à la liste des 3 canaux) — retombe sur
    # annonces_gestion seulement si `cible` est absent/invalide (garde-fou,
    # ne devrait pas arriver depuis canal_detail.html).
    destination = 'annonces_canal_detail' if cible in CIBLES_VALIDES else 'annonces_gestion'
    destination_args = [cible] if destination == 'annonces_canal_detail' else []

    if not titre or not contenu:
        messages.error(request, 'يجب إدخال عنوان ونص الإعلان.')
        return redirect(destination, *destination_args)
    if cible not in CIBLES_VALIDES:
        messages.error(request, 'يجب اختيار الفئة المستهدفة بالإعلان.')
        return redirect('annonces_gestion')

    type_fichier = ''
    if fichier:
        type_fichier, erreur = valider_piece_jointe(fichier)
        if erreur:
            messages.error(request, erreur)
            return redirect(destination, *destination_args)

    # Garde anti-double-soumission : si CE même utilisateur vient de publier
    # EXACTEMENT le même contenu dans le même canal il y a quelques secondes,
    # on ne recrée pas une 2e Annonce — on se comporte comme si la publication
    # avait réussi (même message, même redirection) sans rien insérer de plus.
    recente = Annonce.objects.filter(
        cree_par=request.user, titre=titre, contenu=contenu, cible=cible,
        date_creation__gte=timezone.now() - datetime.timedelta(seconds=FENETRE_ANTI_DOUBLON_SECONDES),
    ).exists()
    if recente:
        messages.success(request, 'تم نشر الإعلان بنجاح.')
        return redirect(destination, *destination_args)

    Annonce.objects.create(
        titre=titre, contenu=contenu, cible=cible, cree_par=request.user,
        fichier=fichier or None, type_fichier=type_fichier,
        nom_fichier_original=fichier.name if fichier else '',
        taille_fichier_octets=fichier.size if fichier else None,
    )
    messages.success(request, 'تم نشر الإعلان بنجاح.')
    return redirect(destination, *destination_args)


@role_required('admin', 'mshrif')
def annonce_toggle(request, annonce_id):
    """Active/désactive une annonce (POST only) — réversible, ne supprime
    jamais (voir Annonce.active). Une annonce désactivée reste dans
    l'historique مدير/مشرف mais disparaît immédiatement de annonces_visibles_pour_eleve."""
    annonce = get_object_or_404(Annonce, id=annonce_id)
    if request.method != 'POST':
        return redirect('annonces_canal_detail', annonce.cible)

    annonce.active = not annonce.active
    annonce.save(update_fields=['active'])
    if annonce.active:
        messages.success(request, 'تم إعادة تفعيل الإعلان.')
    else:
        messages.success(request, 'تم إخفاء الإعلان عن الطلاب.')
    return redirect('annonces_canal_detail', annonce.cible)


@role_required('eleve')
def eleve_annonces(request):
    """Liste des annonces ciblant CET élève (voir courses.utils.cible_annonce_pour_eleve)
    — jamais les 3 catégories mélangées. Visiter cette page marque les
    annonces affichées comme lues (retire le badge sidebar/bannière)."""
    from accounts.models import Eleve

    try:
        eleve = Eleve.objects.select_related('inscription').get(user=request.user)
    except Eleve.DoesNotExist:
        return redirect('login')

    annonces = list(annonces_visibles_pour_eleve(eleve))
    marquer_annonces_lues(annonces, request.user)

    return render(request, 'annonces/eleve_annonces.html', {
        'annonces': annonces,
        'canal': canal_pour_eleve(eleve),
        'age_inconnu': eleve.inscription is None or eleve.inscription.date_naissance is None,
    })


@role_required('admin', 'mshrif', 'eleve')
def annonce_fichier(request, annonce_id):
    """Accès sécurisé à la pièce jointe d'une publication (Point C14) —
    même patron que chat.views.chat_fichier : l'URL réelle du fichier
    (Cloudinary en prod, /media/ en dev) n'est JAMAIS imprimée directement
    dans un template annonces, seule cette vue, après vérification
    peut_voir_annonce, redirige vers le fichier. Un élève d'un AUTRE canal ne
    peut donc pas récupérer le fichier même en devinant/rejouant cette URL."""
    annonce = get_object_or_404(Annonce, id=annonce_id)
    if not annonce.fichier or not peut_voir_annonce(request.user, annonce):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذا الملف.')
    return redirect(annonce.fichier.url)
