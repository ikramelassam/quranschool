from django.core.paginator import Paginator


def paginer(request, queryset, par_page=10):
    """Découpe une longue liste en pages de par_page éléments.
    Retourne un objet Page, itérable comme la queryset d'origine dans les templates."""
    paginator = Paginator(queryset, par_page)
    return paginator.get_page(request.GET.get('page'))
