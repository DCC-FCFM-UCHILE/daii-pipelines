from daii.bronze.spiders.base import DieSpider


class RobertoCardenasSpider(DieSpider):
    name = 'sitio_roberto_cardenas'
    slug = 'roberto-cardenas'
    expect = {'persona': 1, 'formacion': 1, 'publicacion': 30, 'proyecto': 10, 'tesis': 3}
