"""Ficha histórica de proyectos adjudicados de Claudio Pérez en FONDEF."""

from daii.bronze.spiders.base import AcademicSpider, texts

PERSONA = 'claudio-perez'


class ClaudioPerezSpider(AcademicSpider):
    name = 'sitio_claudio_perez'
    expect = {'persona': 1, 'proyecto': 4}

    async def start(self):
        for p in self.personas('sitio'):
            if p['slug'] == PERSONA:
                yield self.page(p['perfiles']['sitio'], self.parse, PERSONA)

    def parse(self, response):
        yield self.item('persona', response, nombre=texts(response.css('title')))
        tabla = response.xpath(
            "//span[@class='textoblanco' and normalize-space()='Proyectos Adjudicados FONDEF']/ancestor::table[1]"
        )
        for fila in tabla.xpath('.//tr[td[1]//a and count(td)=3]'):
            codigo, titulo, rol = map(texts, fila.css('td'))
            yield self.item('proyecto', response, codigo=codigo, titulo=titulo, rol=rol, fuente='FONDEF')
        yield from self.related(response, region='td.texto')
