from daii.bronze.spiders.base import DieSpider


class RodrigoPalmaSpider(DieSpider):
    name = 'sitio_rodrigo_palma'
    slug = 'rodrigo-palma'
    expect = {'persona': 1, 'formacion': 1, 'publicacion': 21, 'proyecto': 15, 'tesis': 15}
