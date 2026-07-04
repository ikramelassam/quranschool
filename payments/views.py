from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import role_required
from accounts.models import Eleve
from .models import Paiement


@role_required('eleve')
def eleve_paiements(request):
    eleve = get_object_or_404(Eleve, user=request.user)

    if request.method == 'POST':
        Paiement.objects.create(
            eleve=eleve,
            montant=request.POST.get('montant'),
            mois_reference=request.POST.get('mois_reference'),
            screenshot=request.FILES.get('screenshot'),
        )
        messages.success(request, 'تم إرسال إثبات الدفع بنجاح، سيتم مراجعته من طرف الإدارة.')
        return redirect('eleve_paiements')

    paiements = Paiement.objects.filter(eleve=eleve).order_by('-mois_reference')
    return render(request, 'dashboard/eleve_paiements.html', {
        'eleve': eleve,
        'paiements': paiements,
    })


@role_required('admin')
def admin_paiements(request):
    paiements = Paiement.objects.select_related('eleve__user').order_by('-date')
    return render(request, 'dashboard/admin_paiements.html', {
        'paiements': paiements,
    })


@role_required('admin')
def admin_paiement_detail(request, paiement_id):
    paiement = get_object_or_404(Paiement, id=paiement_id)
    return render(request, 'dashboard/admin_paiement_detail.html', {
        'paiement': paiement,
    })


@role_required('admin')
def admin_paiement_valider(request, paiement_id):
    paiement = get_object_or_404(Paiement, id=paiement_id)
    paiement.statut = 'valide'
    paiement.valide_par = request.user
    paiement.save()
    messages.success(request, 'تم قبول الدفعة.')
    return redirect('admin_paiement_detail', paiement_id=paiement.id)


@role_required('admin')
def admin_paiement_rejeter(request, paiement_id):
    paiement = get_object_or_404(Paiement, id=paiement_id)
    paiement.statut = 'rejete'
    paiement.valide_par = request.user
    paiement.save()
    messages.info(request, 'تم رفض الدفعة.')
    return redirect('admin_paiement_detail', paiement_id=paiement.id)
