"""CV de Patricio Felmer. La reseña de uchile.cl devuelve HTTP 403."""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, anio, anios, autores, clean, latex_acentos, pdf_texto

PERSONA = 'patricio-felmer'
CV = 'https://intranet.ciae.cl/uploads/cv/CV_Patricio_Felmer.pdf'
FORMACION = re.compile(r'^(.+)\. ([^\n.]+), ((?:19|20)\d{2})\.$', re.M)
DISTINCION = re.compile(r'^(?=Premio |Medalla |Hijo Ilustre |Miembro |Herramientas )', re.M)
PUBLICACION = re.compile(r'^\d+\.[ \t]+', re.M)
REFERENCIA = re.compile(r'^([^“”‘"]+?)(?:[“”"](.+?)[”"]|‘(.+?)’)\.?\s+(.*)$')
ANIO_FINAL = re.compile(r', ((?:19|20)\d{2})\.?$')


class PatricioFelmerSpider(AcademicSpider):
    name = 'sitio_patricio_felmer'
    expect = {'formacion': 3, 'distincion': 7, 'publicacion': 12}

    async def start(self):
        if not self.only or self.only == PERSONA:
            yield self.page(CV, self.parse_cv, PERSONA, guardar=False)

    def parse_cv(self, response: Response) -> Iterator:
        texto = '\n' + latex_acentos(pdf_texto(response))
        # La cabecera contiene datos personales y queda fuera de las secciones parseadas.
        formacion = texto.partition('\nEDUCACIÓN\n')[2].partition('\nPOSICIÓN ACADEMICA\n')[0]
        for grado, institucion, fecha in FORMACION.findall(formacion):
            yield self.item('formacion', response, grado=grado, institucion=institucion, anio=int(fecha))

        premios = texto.partition('\nPREMIOS Y DISTINCIONES\n')[2].partition('\nPUBLICACIONES\n')[0]
        for entrada in DISTINCION.split(premios):
            if nombre := clean(entrada):
                fechas = anios(nombre)
                yield self.item('distincion', response, nombre=nombre, anio=fechas[-1] if fechas else None)

        # shortcut: títulos entre comillas en matemática, ampliar al cubrir el resto de las referencias.
        publicaciones = texto.partition('\nPUBLICACIONES\n')[2].partition('\nLIBROS Y APUNTES DE CLASES\n')[0]
        for entrada in PUBLICACION.split(publicaciones):
            cita = clean(re.sub(r'(?<=\w)-\n(?=\w)', '-', entrada))
            if cita and (m := REFERENCIA.match(cita)):
                firma, titulo_doble, titulo_simple, referencia = m.groups()
                fecha_final = ANIO_FINAL.search(referencia)
                yield self.item(
                    'publicacion',
                    response,
                    titulo=(titulo_doble or titulo_simple).strip(),
                    autores=autores(re.sub(r' (?:&|y) ', ' and ', firma)),
                    anio=int(fecha_final[1]) if fecha_final else anio(referencia),
                )

        yield from self.related(response)
