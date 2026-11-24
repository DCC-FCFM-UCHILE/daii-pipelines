"""Fichas de investigadores del Centro de Modelamiento Matemático (cmm.uchile.cl/?persona=<slug>, WordPress + Impreza).

Una ficha trae: categoría CMM, nombre, cargo, títulos, universidad, jerarquía académica, áreas de investigación
fundamental/aplicada, intereses, biografía (con premios) y contacto.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, email, texts

YEAR_END = re.compile(r'\s*\((\d{4})\)\s*$')  # "Doctor en Matemáticas, ..., Francia (1994)"
AWARD_YEAR = re.compile(r'\s+[-–]\s+(\d{4})$')  # "CNRS Fellow-Ambassadeur - 2023"


class CmmSpider(AcademicSpider):
    name = 'cmm'
    expect = {'persona': 1, 'formacion': 1, 'afiliacion': 2, 'area': 1}

    def parse(self, response: Response) -> Iterator:
        main = response.css('main')
        contacto = main.css('.info')
        tel = contacto.css("a[href^='tel:']")
        bio = [texts(p) or '' for p in main.css('.cmm-bio p')]
        yield self.item(
            'persona',
            response,
            nombre=texts(main.css('h1.post_title')),
            cargo=texts(main.css('.cargo')),
            email=email(contacto.css("a[href^='mailto:']::attr(href)").get()),
            telefono=texts(tel[-1]) if tel else None,
            oficina=next(  # el iconbox sin link es la oficina ("724")
                (t for b in contacto.css('.w-iconbox') if not b.css('a') and (t := texts(b.css('.w-iconbox-title')))),
                None,
            ),
            foto_url=main.css('.w-image img::attr(src)').get(),
            bio=clean(' '.join(p for p in bio if not p.startswith('Awards'))),
        )

        for li in main.css('.cmm-titulos li'):
            t = texts(li) or ''
            m = YEAR_END.search(t)
            grado, _, inst = (t[: m.start()] if m else t).partition(', ')
            yield self.item('formacion', response, grado=grado, institucion=clean(inst), anio=m.group(1) if m else None)

        # Cargo en el CMM: "Investigador Principal | Director de Relaciones Internacionales"
        cmm = response.css("meta[property='og:site_name']::attr(content)").get() or 'CMM'
        for rol in (texts(main.css('.cargo')) or '').split('|'):
            if clean(rol):
                yield self.item(
                    'afiliacion', response, organizacion=cmm, rol=clean(rol), url_organizacion=response.urljoin('/')
                )

        # Bloque "datos académicos" (University / Academic Hierarchy / Fundamental Research / Applied Research).
        # Se identifica por clases y taxonomías, no por las etiquetas, que cambian con el idioma del sitio.
        datos = main.css('.datos-academicos')
        jerarquia = texts(datos.css('.jerarquia_academica'))
        for a in datos.css("a[href*='/universidad/']"):
            yield self.item(
                'afiliacion', response, organizacion=texts(a), rol=jerarquia, url_organizacion=a.attrib['href']
            )
        for el in datos.css("a[href*='/area-de-investigacion/'], .trabaja_en"):
            yield self.item('area', response, nombre=texts(el))

        # "Awards and recognitions:<br>- National Prize for Exact Sciences – 2025<br>- ..."
        for p in main.css('.cmm-bio p'):
            lines = [clean(t) or '' for t in p.css('::text').getall()]
            if not lines or not lines[0].startswith('Awards'):
                continue
            for line in lines[1:]:
                nombre = line.removeprefix('-').strip()
                m = AWARD_YEAR.search(nombre)
                if nombre:
                    yield self.item(
                        'distincion',
                        response,
                        nombre=nombre[: m.start()] if m else nombre,
                        anio=m.group(1) if m else None,
                    )

        # Solo bio y contacto: los demás links de la ficha son taxonomías del CMM (listados de otras personas).
        yield from self.related(response, region='main section:last-of-type')
