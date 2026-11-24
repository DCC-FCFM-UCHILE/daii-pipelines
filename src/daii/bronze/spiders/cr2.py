"""Fichas de investigadores del Centro de Ciencia del Clima y la Resiliencia (cr2.cl/<slug>/, WordPress + tagDiv).

Una ficha trae: foto, nombre y cargo en el CR2 (h2), bio (con afiliación académica y doctorado), contacto con
perfiles y la tabla TablePress "Papers del investigador". La tabla viene completa en el HTML: la paginación es
DataTables en el navegador.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, email, texts

# "Profesor asociado del Departamento de Geofísica de la Universidad de Chile."
CARGO = re.compile(r'^(Profesor[a]?(?: \w+)?) del? (.+?)\.')
# "Obtuvo su doctorado en el Massachusetts Institute of Technology (MIT), Estados Unidos."
DOCTORADO = re.compile(r'Obtuvo su (doctorado|magíster|maestría) en (?:el |la )?(.+?)\.')
PERFILES = {'orcid.org': 'orcid', 'researchgate.net': 'researchgate', 'scholar.google': 'scholar'}
IDS = {'Línea de Investigación': 'linea_cr2', 'Index': 'indexacion', 'Acceso': 'acceso', 'ISSN': 'issn'}


class Cr2Spider(AcademicSpider):
    name = 'cr2'
    expect = {'persona': 1, 'afiliacion': 1, 'perfil': 1, 'publicacion': 25}

    def parse(self, response: Response) -> Iterator:
        content = response.css('.td_block_text_with_title')
        h2 = content.css('h2')
        nombre = texts(h2.css('strong'))
        cargo = clean(' '.join(h2.xpath('text()').getall()))
        bio = texts(h2.xpath('following-sibling::p[1]'))
        yield self.item(
            'persona',
            response,
            nombre=nombre,
            cargo=cargo,
            email=email(content.css("a[href^='mailto:']::attr(href)").get()),
            foto_url=content.css('img::attr(src)').get(),
            bio=bio,
        )
        if cargo:
            yield self.item(
                'afiliacion', response, organizacion='CR2', rol=cargo, url_organizacion=response.urljoin('/')
            )
        if bio and (m := CARGO.match(bio)):
            yield self.item('afiliacion', response, organizacion=m.group(2), rol=m.group(1))
        if bio and (m := DOCTORADO.search(bio)):
            yield self.item('formacion', response, grado=m.group(1), institucion=m.group(2))

        for a in content.css('a[href]'):
            href = a.attrib['href']
            if plat := next((v for k, v in PERFILES.items() if k in href), None):
                ident = href.rstrip('/').rsplit('/', 1)[-1] if plat == 'orcid' else None
                yield self.item('perfil', response, plataforma=plat, url_destino=href, identificador=ident)

        for table in content.css('table.tablepress'):
            cols = [texts(th) for th in table.css('thead th')]
            for tr in table.css('tbody tr'):
                row = dict(zip(cols, [texts(td) for td in tr.css('td')], strict=False))
                if not row.get('Título'):
                    continue
                anio = row.get('Año') or ''
                yield self.item(
                    'publicacion',
                    response,
                    titulo=row['Título'],
                    venue=row.get('Revista'),
                    autores=[a for x in (row.get('Autores') or '').split(';') if (a := clean(x))],
                    anio=int(anio) if anio.isdigit() else None,
                    doi=row.get('DOI'),
                    url_destino=tr.css('td.column-7 a::attr(href)').get() or tr.css('a::attr(href)').get(),
                    tipo_publicacion='revista',
                    ids={k: row[c] for c, k in IDS.items() if row.get(c)},
                )

        # Solo bio, contacto y tabla de papers: el resto es menú/pie del sitio CR2.
        yield from self.related(response, region='.td_block_text_with_title')
