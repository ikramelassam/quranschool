from django import template

register = template.Library()


@register.filter
def get_item(dictionnaire, cle):
    """Lookup par clé dynamique dans un dict — la syntaxe {{ dict.cle }} de
    Django ne résout que des clés LITTÉRALES, jamais la valeur d'une variable
    de boucle (ex: {% for valeur, libelle in cible_choices %}), d'où ce
    filtre pour afficher effectifs[valeur] dans admin_annonces.html."""
    if dictionnaire is None:
        return None
    return dictionnaire.get(cle)
