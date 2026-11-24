"""Sitio personal (antiguo, ~2012) de Javier Ruiz del Solar en cec.uchile.cl/~jruizd/.

Home de una página (contacto, formación, cargos, áreas, "other activities") y subpáginas del mismo sitio:
CV (curriculum.html), publicaciones, tesis guiadas, líneas de investigación y cursos.
El servidor declara UTF-8, pero las páginas son windows-1252 o macintosh (según su <meta charset>): se
re-decodifican con el charset del <meta>.
No se extraen fecha de nacimiento ni RUT del CV, y esa página no se guarda en disco (`guardar=False`).
"""

import re
from collections.abc import Iterator

from scrapy.http import Response, TextResponse

from daii.bronze.spiders.base import AcademicSpider, anio, anios, autores, clean, email, plain

SITIO = 'https://www.cec.uchile.cl/~jruizd/'
PERSONA = 'javier-ruiz-del-solar'
CARGO = re.compile(
    r'^(.*?)\s+(?:at|of) the\s+(.+)$'
)  # "Professor of Electrical Engineering at the Universidad de Chile"
PUB = re.compile(r'^\d+\.\s*(?P<autores>.+?)\s*(?:\(Eds?\.\)\s*)?\((?P<anio>\d{4})[a-z]?\)\.?\s*(?P<resto>.+)$')
QUOTED = re.compile(r'[“\"”](.+?)[,.]?[”\"]')
DOI = re.compile(r'\b10\.\d{4,}/[^\s,;()]+')
ESTADO = re.compile(r'\((in press|accepted|submitted|to appear)\)', re.I)
# Sección del CV → tipo_actividad (vocabulario de docs/modelo_datos.md); el rol queda con el texto de la sección
ACTIVIDADES = {
    'Technical Committees': 'comite',
    'Journal Editor': 'editorial',
    'Journal Reviewer': 'revisor',
    'Proposal Reviewer': 'revisor',
    'Chairman / Organizing Chair': 'organizacion_evento',
    'Session Chair': 'organizacion_evento',
    'Organizing Committee': 'organizacion_evento',
    'Program Committee': 'comite_programa',
    'Invited speaker': 'charla',
    'Tutorial Courses': 'tutorial',
}
CV_SECCIONES = {
    'Appointments',
    'Education',
    'Awards',
    'Selected Grants and Scholarships',
    'Research interests',
    'Professional and Research Activities',
    'Workshops & Conferences',
    'Research visits',
    'Languages',
    'Societies',
    *ACTIVIDADES,
}


def decoded(response: Response) -> Response:
    m = re.search(rb'charset=([\w-]+)', response.body[:3000])
    return response.replace(encoding=m.group(1).decode()) if m and isinstance(response, TextResponse) else response


def lines(sel) -> list[str]:
    return [t for t in (clean(x) for x in sel.xpath('.//text()').getall()) if t]


def fechas(t: str) -> tuple[str, str | None, str | None]:
    """ "Cargo ... (May 2005 – present)." / "Cargo ... since 2011." → (texto sin fechas, desde, hasta)."""
    if m := re.search(r'\s*\(([^()]*\d{4}[^()]*)\)\.?$', t):
        desde, *hasta = re.split(r'\s+[–-]\s+', m.group(1), maxsplit=1)
        return t[: m.start()], clean(desde), clean(hasta[0]) if hasta else None
    if m := re.search(r'\s+since\s+(\d{4})\.?$', t):
        return t[: m.start()], m.group(1), None
    return t.rstrip('.'), None, None


def italica(el, t: str, desde: int) -> tuple[int, int]:
    """Posición en `t` del venue: primer bloque de <i> contiguos desde `desde` (Word parte "<i>Proc. of</i> <i>...")."""
    ini = fin = 0
    for s in filter(None, (plain(i) for i in el.css('i'))):
        k = t.find(s, fin or desde)
        if k < 0 or (fin and t[fin:k].strip()):
            break
        ini, fin = (ini, k + len(s)) if fin else (k, k + len(s))
    return ini, fin


class JavierRuizDelSolarSpider(AcademicSpider):
    name = 'sitio_javier_ruiz_del_solar'
    expect = {
        'persona': 1,
        'formacion': 3,
        'afiliacion': 8,
        'area': 3,
        'distincion': 10,
        'actividad': 90,
        'publicacion': 120,
        'tesis': 15,
        'dictacion': 2,
    }

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(SITIO, self.parse, PERSONA)
            yield self.page(SITIO + 'curriculum.html', self.parse_cv, PERSONA, guardar=False)  # trae RUT y nacimiento
            yield self.page(SITIO + 'publications.html', self.parse_publications, PERSONA)
            yield self.page(SITIO + 'thesis.html', self.parse_thesis, PERSONA)
            yield self.page(SITIO + 'research.html', self.parse_research, PERSONA)
            yield self.page(SITIO + 'courses.htm', self.parse_courses, PERSONA)

    def parse(self, response: Response) -> Iterator:
        response = decoded(response)
        contacto = lines(response.xpath("//p[contains(., 'e-mail')]"))
        phone = next((x.removeprefix('Phone:').strip() for x in contacto if x.startswith('Phone:')), None)
        yield self.item(
            'persona',
            response,
            nombre=contacto[0],
            email=email(response.css("a[href^='mailto:']::attr(href)").get()),
            telefono=phone,
        )

        # Celdas de contenido (colspan=6) con texto, en orden: formación, cargo, áreas, otras actividades
        cells = [td for td in response.css("td[colspan='6']") if clean(' '.join(td.css('::text').getall()))]
        formacion, cargos, areas, otras = (cells + [None] * 4)[:4]
        for t in lines(formacion) if formacion else []:
            grado, _, inst = t.partition(', ')
            yield self.item('formacion', response, grado=grado, institucion=clean(inst))
        for t in lines(cargos) if cargos else []:
            m = CARGO.match(t)
            yield self.item('afiliacion', response, rol=m.group(1) if m else None, organizacion=m.group(2) if m else t)
        for t in lines(areas) if areas else []:
            for nombre in t.rstrip('.').split(', '):
                yield self.item('area', response, nombre=nombre.strip())
        for a in otras.css('a') if otras else []:
            nombre = plain(a)
            if not nombre:
                continue
            if 'Children' in nombre:  # robótica con niños: divulgación
                yield self.item(
                    'actividad', response, tipo_actividad='divulgacion', titulo=nombre, url_destino=a.attrib['href']
                )
            else:  # centros, laboratorios, equipos RoboCup y consejo IEEE a los que pertenece
                yield self.item('afiliacion', response, organizacion=nombre, url_organizacion=a.attrib['href'])
        yield from self.related(response)

    def parse_cv(self, response: Response) -> Iterator:
        response = decoded(response)
        seccion = None
        for el in response.css('body p, body h1, body h3'):
            t = plain(el) or ''
            if t.rstrip(': ') in CV_SECCIONES:
                seccion = t.rstrip(': ')
                continue
            if not t or seccion is None:
                continue
            t = t.removeprefix('-').strip()
            if seccion == 'Appointments':
                texto, desde, hasta = fechas(t)
                m = CARGO.match(texto)
                if not m:  # "Graduate Studies Chairman, Dept. of Electrical Engineering, Universidad de Chile"
                    rol, _, org = texto.partition(', ')
                else:
                    rol, org = m.groups()
                yield self.item('afiliacion', response, rol=rol, organizacion=org or texto, desde=desde, hasta=hasta)
            elif seccion == 'Education':
                # "Doctor-Engineer (1997). Technical University Berlin, Germany. Examination Grade: ..."
                m = re.match(r'(.+?)\s*\((\d{4})\)\.\s*(.+?)(?:\.\s|\.?$)', t)
                if m:
                    yield self.item('formacion', response, grado=m.group(1), anio=m.group(2), institucion=m.group(3))
                else:
                    yield self.item('formacion', response, grado=t.rstrip('.'))
            elif seccion in ('Awards', 'Selected Grants and Scholarships'):
                nombre = t.rstrip('. ') if seccion == 'Awards' else re.split(r'\s*\(', t)[0]
                yield self.item('distincion', response, nombre=nombre, anio=anio(t))
            elif seccion == 'Research interests':
                for nombre in t.rstrip('.').split(', '):
                    yield self.item('area', response, nombre=nombre)
            elif seccion in ACTIVIDADES:
                fecha = re.search(r'\(([^()]*\d{4}[^()]*)\)', t)
                yield self.item(
                    'actividad',
                    response,
                    tipo_actividad=ACTIVIDADES[seccion],
                    rol=seccion,
                    titulo=t.rstrip('.'),
                    fecha=fecha.group(1).split(';')[-1].strip() if fecha else None,
                )
            # Research visits, Languages, Societies: no tienen tipo en el contrato bronze
        yield from self.related(response)

    def parse_publications(self, response: Response) -> Iterator:
        response = decoded(response)
        tipo = None
        for el in response.css('body p, body h4'):
            t = plain(el) or ''
            if re.match(r'^[A-E]\.(\d\.)?\s+\D', t):  # "A. International Journal Papers" / "D.2. Book Chapters"
                tipo = re.sub(r'^[A-E]\.(\d\.)?\s+', '', t)
                continue
            m = PUB.match(t)
            q = QUOTED.search(t)
            if m:
                aut, anio, resto = m.group('autores'), m.group('anio'), m.group('resto')
                ini, fin = italica(el, t, m.start('resto'))
                venue = t[ini:fin] if fin else None
                titulo = t[m.start('resto') : ini] if fin else re.split(r'\.\s', resto)[0]
                titulo = re.split(r'[.,]\s+In\s', titulo)[0].strip(' .,')  # capítulos: "Título. In X (Ed.), Libro"
                if fin and not titulo:  # libros editados: la itálica ES el título, no hay venue
                    titulo, venue = venue or '', None
            elif q and re.match(r'^\d+\.', t):  # 'Ruiz-del-Solar, J., ..., “Advances in Robotics ...,” Journal ...'
                aut, titulo = re.sub(r'^\d+\.\s*', '', t[: q.start()]), q.group(1)
                ini, fin = italica(el, t, q.end())
                anio, venue = None, t[ini:fin] if fin else None
            else:
                continue
            doi = DOI.search(t)
            estado = ESTADO.search(t)
            yield self.item(
                'publicacion',
                response,
                titulo=titulo.strip('“”" ') if titulo[:1] in '“"' else titulo,
                autores=autores(aut),
                anio=anio,
                venue=venue.strip(' ,.') if venue else None,
                tipo_publicacion=tipo,
                doi=doi.group(0).rstrip('.') if doi else None,
                estado=estado.group(1) if estado else None,
                url_destino=el.css('a::attr(href)').get(),
            )
        yield from self.related(response)

    def parse_thesis(self, response: Response) -> Iterator:
        response = decoded(response)
        nivel = rol = None
        for el in response.css('body p, body h1'):
            t = plain(el) or ''
            m = re.match(r'^(.+?),?\s*[“\"](.+?)[”\"]\s*,?\s*(.*)$', t)
            if not m:
                if t:  # encabezado: "Tesis de Magister", "Memorias de Ingeniero Civil", "... como profesor de comisión"
                    nivel, rol = (None, t) if 'comisi' in t else (t, None)
                continue
            resto = m.group(3)
            y = anios(resto)
            co = re.search(r'\((profesor [^)]+)\)', resto)
            yield self.item(
                'tesis',
                response,
                estudiante=m.group(1).strip(' ,'),
                titulo=m.group(2).strip(' ,'),
                programa=clean(resto.split(', ')[0]),
                anio=y[-1] if y else None,
                nivel=nivel,
                rol=co.group(1) if co else rol,
            )
        yield from self.related(response)

    def parse_research(self, response: Response) -> Iterator:
        response = decoded(response)
        for h in response.css('h5'):
            if nombre := plain(h):
                yield self.item('area', response, nombre=nombre)
        yield from self.related(response)

    def parse_courses(self, response: Response) -> Iterator:
        response = decoded(response)
        for td in response.css("td[width='98%']"):
            codigo, _, nombre = (plain(td) or '').partition(' ')  # "EL708 Procesamiento Avanzado de Imágenes (...)"
            yield self.item('dictacion', response, codigo_curso=codigo, nombre_curso=nombre)
        yield from self.related(response, region='table')  # excluye el botón "main" → index.html
