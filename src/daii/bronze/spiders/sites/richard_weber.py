"""Sitio personal de Richard Weber (Wix): home (bio), cv, publications y projects.

Wix renderiza el texto en el HTML del servidor, así que no hace falta Playwright. El contenido útil vive en
`#PAGES_CONTAINER` (header y footer repiten menú, redes sociales y formulario de contacto). Las listas (cargos,
publicaciones, proyectos) son repeaters `[id^=NewsPostsView]` con una fila `div.flex_display` por entrada y una
celda de texto (`richTextContainer`) por campo.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, anios, autores, clean, texts

SITIO = 'https://richardweber.wixsite.com/home'
PERSONA = 'richard-weber'
MAIN = '#PAGES_CONTAINER'
# shortcut: el DOM de Wix no deja asociar cada repeater a su título; se asume el orden visual de la página.
TIPOS_PUB = ['JOURNAL ARTICLES', 'BOOKS', 'BOOK CHAPTERS', 'CONFERENCE PROCEEDINGS']
# "Associate Professor at the Department ..." / "Associate Editor of the journal ..." (frases de la bio)
ROLE = re.compile(
    r'\b(Associate Professor|Director|Associate Editor|member of the Editorial Board|head|'
    r'Chairman of the Program Committee) (?:at|of) the '
    r'(.+?)(?= and (?:Director|member|Chairman)| as well as|\.(?:\s|$))'
)
PERFILES = {
    'orcid.org': 'orcid',
    'dblp': 'dblp',
    'scholar.google': 'scholar',
    'researchgate.net': 'researchgate',
    'researcherid.com': 'researcherid',
    'linkedin.com': 'linkedin',
    'twitter.com': 'twitter',
}


def rows(response: Response) -> list[list[list[str]]]:
    """Por repeater: sus filas como lista de párrafos de texto (uno por campo)."""
    out = []
    for rep in response.css(f"{MAIN} [id^='NewsPostsView']"):
        filas = []
        for row in rep.css("div[class='flex_display']"):
            ps = row.css("[class*='richTextContainer']").css('p, h1, h2, h3, h4, h5, h6')
            filas.append([t for p in ps if (t := clean(' '.join(p.css('::text').getall()).replace('\u200b', '')))])
        out.append(filas)
    return out


class RichardWeberSpider(AcademicSpider):
    name = 'sitio_richard_weber'
    expect = {
        'persona': 1,
        'perfil': 3,
        'afiliacion': 3,
        'formacion': 2,
        'area': 2,
        'actividad': 4,
        'publicacion': 60,
        'proyecto': 18,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(SITIO, self.parse, PERSONA)
        yield self.page(f'{SITIO}/cv', self.parse_cv, PERSONA)
        yield self.page(f'{SITIO}/publications', self.parse_publications, PERSONA)
        yield self.page(f'{SITIO}/projects', self.parse_projects, PERSONA)

    def parse(self, response: Response) -> Iterator:
        header = [
            texts(h) for h in response.css("#SITE_HEADER [data-testid='richTextElement'] h1")
        ]  # Professor / NOMBRE
        main = response.css(MAIN)
        # La bio es el bloque de texto más largo de la página.
        bio_el = max(main.css("[data-testid='richTextElement']"), key=lambda el: len(texts(el) or ''))
        bio = [t for p in bio_el.css('p') if (t := texts(p))]
        yield self.item(
            'persona',
            response,
            nombre=header[-1],
            cargo=header[0] if len(header) > 1 else None,
            foto_url=main.css('img::attr(src)').get(),
            bio=' '.join(bio),
        )
        for a in response.css('#SITE_HEADER a[href]'):
            url = a.attrib['href'].strip()
            plataforma = next((v for k, v in PERFILES.items() if k in url), None)
            if plataforma:
                ident = url.rstrip('/').rsplit('/', 1)[-1] if plataforma in ('orcid', 'researcherid') else None
                yield self.item('perfil', response, plataforma=plataforma, url_destino=url, identificador=ident)

        for m in ROLE.finditer(' '.join(bio)):
            rol, org = m.group(1), m.group(2)
            if 'Editor' in rol:
                yield self.item('actividad', response, tipo_actividad='editorial', titulo=org, rol=rol)
            elif 'Program Committee' in rol:
                yield self.item('actividad', response, tipo_actividad='comite_programa', titulo=org, rol=rol)
            else:
                yield self.item('afiliacion', response, organizacion=org, rol=rol)

        for t in (texts(el) or '' for el in main.css("[data-testid='richTextElement']")):
            # "My research interests are data mining , dynamic data mining , ... with applications to ..."
            if t.startswith('My research interests are'):
                temas = t.removeprefix('My research interests are').split(' with applications')[0]
                for nombre in re.split(r'\s*,\s*(?:and\s+)?', temas.strip(' .')):
                    yield self.item('area', response, nombre=nombre)
        yield from self.related(response, region=MAIN)

    def parse_cv(self, response: Response) -> Iterator:
        # "1992: PhD Operations Research, RWTH Aachen University, Aachen, Germany"
        for p in response.css(f"{MAIN} [data-testid='richTextElement'] p"):
            m = re.match(r'^((?:19|20)\d{2}):\s*([^,]+),\s*(.+)$', texts(p) or '')
            if m:
                yield self.item('formacion', response, anio=m.group(1), grado=m.group(2), institucion=m.group(3))

        # ACADEMIC APPOINTMENTS: [fechas, "Professor; Universidad de Chile, Department of Industrial Engineering."]
        for rep in rows(response):
            for fila in rep:
                if len(fila) < 2:
                    continue
                fechas, texto = fila[0], fila[1].rstrip(' .')
                partes = re.split(r'\s+[–-]\s+', fechas, maxsplit=1)
                desde, hasta = partes[0], partes[1] if len(partes) > 1 else None
                if texto.startswith('Visiting'):  # "Visiting Professor KU Leuven, Belgium (invited by ...)"
                    rol = ' '.join(texto.split()[:2])
                    yield self.item('actividad', response, tipo_actividad='visita', titulo=texto, rol=rol, fecha=fechas)
                    continue
                sep = next((s for s in (';', ' at ', ', ') if s in texto), None)
                rol, _, org = texto.partition(sep) if sep else (None, None, texto)
                yield self.item(
                    'afiliacion', response, organizacion=org.strip(), rol=rol and rol.strip(), desde=desde, hasta=hasta
                )
        yield from self.related(response, region=MAIN)

    def parse_publications(self, response: Response) -> Iterator:
        reps = rows(response)
        for i, rep in enumerate(reps):
            tipo = TIPOS_PUB[i] if len(reps) == len(TIPOS_PUB) else None
            for fila in rep:
                # celdas: "Autores (año)", "Título. Venue", "DOI: ..." en cualquier orden
                aut = next((c for c in fila if re.search(r'\((?:19|20)\d{2}\)$', c)), None)
                doi = next((c for c in fila if c.startswith(('DOI', 'http'))), None)
                cuerpo = next((c for c in fila if c not in (aut, doi)), None)
                if not cuerpo:
                    continue
                titulo, *venue = re.split(r'(?<=[.?!])\s+', cuerpo, maxsplit=1)
                anio = anios(aut)
                doi_url = doi.removeprefix('DOI:').strip() if doi else None
                yield self.item(
                    'publicacion',
                    response,
                    titulo=titulo.rstrip('.'),
                    venue=venue[0].strip(' .') if venue else None,
                    anio=anio[-1] if anio else None,
                    autores=autores(re.sub(r'\s*\(Eds?\.\)|\s*\((?:19|20)\d{2}\)$', '', aut)) if aut else [],
                    tipo_publicacion=tipo,
                    doi=re.sub(r'^https?://(dx\.)?doi\.org/', '', doi_url)
                    if doi_url and 'doi.org/' in doi_url
                    else None,
                    url_destino=doi_url,
                )
        yield from self.related(response, region=MAIN)

    def parse_projects(self, response: Response) -> Iterator:
        # RESEARCH PROJECTS e INDUSTRIAL EXPERIENCE: [años, "“Título”", "(Fondecyt project 1181036); Principal
        # Investigator; Total project amount: USD125,000 approx."] / [años, "“Título”", "Chilecompra. Director."]
        for rep in rows(response):
            for fila in rep:
                if len(fila) < 2:
                    continue
                years = anios(fila[0])
                fuente = rol = monto = None
                for parte in (p.strip() for p in ' '.join(fila[2:]).split(';')):
                    if 'amount:' in parte:
                        monto = parte.split('amount:', 1)[1].strip()
                    elif 'Investigator' in parte:
                        rol = parte.rstrip('.')
                    elif parte and fuente is None:
                        fuente = parte[1:-1] if parte.startswith('(') and parte.endswith(')') else parte
                codigo = re.search(r'[Pp]roject\s+([A-Z]*\d[\w-]*)', fuente or '')
                yield self.item(
                    'proyecto',
                    response,
                    titulo=fila[1].strip(' “”"\''),
                    fuente=fuente,
                    codigo=codigo.group(1) if codigo else None,
                    rol=rol,
                    monto=monto,
                    anio_inicio=years[0] if years else None,
                    anio_fin=years[-1] if years else None,
                )
        yield from self.related(response, region=MAIN)
