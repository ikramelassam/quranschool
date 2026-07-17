from django.core.paginator import Paginator


def paginer(request, queryset, par_page=10, param='page'):
    """Découpe une longue liste en pages de par_page éléments.
    Retourne un objet Page, itérable comme la queryset d'origine dans les templates.
    param: nom du paramètre GET à utiliser — permet de paginer indépendamment
    deux listes différentes sur une même page (ex: candidatures élèves et
    profs sur la même vue d'ensemble)."""
    paginator = Paginator(queryset, par_page)
    return paginator.get_page(request.GET.get(param))
