from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404

from accounts.decorators import role_required
from .models import Annonce
from .services import annonces_visibles_pour_eleve, marquer_annonces_lues, effectif_par_cible

CIBLES_VALIDES = {code for code, _ in Annonce.CIBLE_CHOICES}


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
    """Page centrale "الإعلانات" (مدير/مشرف) — formulaire de création +
    historique complet, même patron que dashboard.views.admin_hakiba_gestion
    (liste + formulaire sur UNE page, création traitée par une vue POST
    séparée ci-dessous)."""
    context = {
        'annonces': Annonce.objects.select_related('cree_par').all(),
        'cible_choices': Annonce.CIBLE_CHOICES,
        'effectifs': effectif_par_cible(),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'annonces/admin_annonces.html', context)


@role_required('admin', 'mshrif')
def annonce_ajouter(request):
    if request.method != 'POST':
        return redirect('annonces_gestion')

    titre = request.POST.get('titre', '').strip()
    contenu = request.POST.get('contenu', '').strip()
    cible = request.POST.get('cible', '')

    if not titre or not contenu:
        messages.error(request, 'يجب إدخال عنوان ونص الإعلان.')
        return redirect('annonces_gestion')
    if cible not in CIBLES_VALIDES:
        messages.error(request, 'يجب اختيار الفئة المستهدفة بالإعلان.')
        return redirect('annonces_gestion')

    Annonce.objects.create(titre=titre, contenu=contenu, cible=cible, cree_par=request.user)
    messages.success(request, 'تم نشر الإعلان بنجاح.')
    return redirect('annonces_gestion')


@role_required('admin', 'mshrif')
def annonce_toggle(request, annonce_id):
    """Active/désactive une annonce (POST only) — réversible, ne supprime
    jamais (voir Annonce.active). Une annonce désactivée reste dans
    l'historique مدير/مشرف mais disparaît immédiatement de annonces_visibles_pour_eleve."""
    if request.method != 'POST':
        return redirect('annonces_gestion')

    annonce = get_object_or_404(Annonce, id=annonce_id)
    annonce.active = not annonce.active
    annonce.save(update_fields=['active'])
    if annonce.active:
        messages.success(request, 'تم إعادة تفعيل الإعلان.')
    else:
        messages.success(request, 'تم إخفاء الإعلان عن الطلاب.')
    return redirect('annonces_gestion')


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
        'age_inconnu': eleve.inscription is None or eleve.inscription.date_naissance is None,
    })
