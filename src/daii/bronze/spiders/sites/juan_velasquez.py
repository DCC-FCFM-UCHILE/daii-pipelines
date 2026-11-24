"""Ficha académica del DII y perfil de Juan Velásquez en el equipo del WIC."""

from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, plain, texts

PERSONA = 'juan-velasquez'
DII = 'https://www.dii.uchile.cl/quien/juan-valasquez/'
WIC = 'https://wic.uchile.cl/'
NOMBRE = 'Juan Velásquez'


class JuanVelasquezSpider(AcademicSpider):
    name = 'sitio_juan_velasquez'
    expect = {'persona': 1, 'formacion': 3, 'area': 4, 'dictacion': 4, 'afiliacion': 2}

    async def start(self):
        if self.only in (None, PERSONA):
            # La ficha del DII enlaza la portada del WIC mediante HTTP.
            self.handled.add('http://wic.uchile.cl/')
            # La portada también contiene las fichas del resto del equipo.
            yield self.page(WIC, self.parse_wic, PERSONA, guardar=False)
            yield self.page(DII, self.parse_dii, PERSONA)

    def parse_dii(self, response: Response) -> Iterator:
        ficha = response.css('.listado-academicos')
        nombre = plain(ficha.css('h1.post_title'))
        if nombre != NOMBRE:
            return

        bloques = {plain(b.css('h4')): b for b in ficha.css('.bloq_pers')}
        cargo = plain(ficha.css('.bloq_pers > b'))
        foto = ficha.css('.persona a.circ::attr(style)').re_first(r"background:\s*url\('([^']+)'\)")
        yield self.item(
            'persona',
            response,
            nombre=nombre,
            cargo=cargo,
            foto_url=foto,
            email=ficha.css('.cont_pers a[href^="mailto:"]::text').get(),
            telefono=ficha.css('.cont_pers a[href^="tel:"]::text').get(),
            bio=texts(ficha.css('#pers_bio p')),
        )
        yield self.item(
            'afiliacion',
            response,
            organizacion='Departamento de Ingeniería Industrial de la Universidad de Chile',
            rol=cargo,
        )
        if (area := bloques.get('Área')) is not None and (nombre_area := plain(area.css('span'))):
            yield self.item('area', response, nombre=nombre_area)
        for etiqueta, tipo, campo in (
            ('Grados Académicos', 'formacion', 'grado'),
            ('Áreas de Especialización', 'area', 'nombre'),
            ('Actividades Docentes', 'dictacion', 'nombre_curso'),
        ):
            bloque = bloques.get(etiqueta)
            if bloque is None:
                continue
            for linea in bloque.css('p::text').getall():
                if not (valor := clean(linea)):
                    continue
                if tipo == 'formacion':
                    grado, _, institucion = valor.partition(', ')
                    yield self.item(tipo, response, grado=grado, institucion=institucion or None)
                else:
                    yield self.item(tipo, response, **{campo: valor})
        yield from self.related(response, region='.listado-academicos')

    def parse_wic(self, response: Response) -> Iterator:
        for modal in response.css('.modal[id]'):
            if plain(modal.css('.modal-title')) != NOMBRE:
                continue
            rol = plain(modal.css('.modal-title + p'))
            organizacion = plain(response.css('h1'))
            if organizacion and rol:
                yield self.item('afiliacion', response, organizacion=organizacion, rol=rol, url_organizacion=WIC)
            intereses = modal.xpath(".//p[normalize-space(.)='Temas de interés']/following-sibling::p[1]")
            for area in (plain(intereses) or '').split(','):
                if nombre_area := clean(area):
                    yield self.item('area', response, nombre=nombre_area)
            yield from self.related(response, region=f'.modal[id="{modal.attrib["id"]}"]')
            return
