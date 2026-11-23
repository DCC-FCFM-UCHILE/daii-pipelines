"""Sitio personal de Felipe Bravo-Marquez (MkDocs Material): home, CV web y publicaciones.

Los cursos del menú Teaching apuntan a repos de GitHub (no se siguen); se registran como dictación con `url_curso`.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.raw.spiders.base import AcademicSpider, clean, texts

SITIO = "https://felipebravom.com/"
PERSONA = "felipe-bravo"
BRACKET = re.compile(r"^\[([^\]]*)\]\s*(.*)$")  # "[2024 - present] resto"
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
TERM = re.compile(r"(\w+)\s+(\d{4})")  # "fall 2026"
DOI = re.compile(r"DOI:\s*(10\.\d+/\S+)")
AUTHOR_SEP = re.compile(r",\s*(?:and\s+)?|\s+and\s+")
# Sección del CV → tipo_actividad (vocabulario de docs/modelo_datos.md cuando calza; si no, la sección)
ACTIVIDADES = {
    "Service": "servicio",
    "University Administration": "gestion",
    "Technology transfer": "transferencia",
    "Academic Visits": "visita",
    "Seminars and Talks": "charla",
    "Shared Task Organisation": "organizacion_evento",
    "Media Outreach": "prensa",
}


def plain(sel) -> str:
    """Texto de un nodo sin insertar espacios entre hijos (evita "AffectiveTweets , a ...")."""
    return clean("".join(sel.css("::text").getall())) or ""


def bracket(li) -> tuple[str | None, str]:
    """Separa "[fecha] resto" de un <li>; sin corchete devuelve (None, texto)."""
    t = plain(li)
    m = BRACKET.match(t)
    return (clean(m.group(1)), m.group(2)) if m else (None, t)


def section(article, h2_id: str, tag: str = "h2"):
    """Los <li> de la primera lista después del encabezado con ese id."""
    return article.xpath(f"./{tag}[@id='{h2_id}']/following-sibling::*[self::ul or self::ol][1]/li")


class FelipeBravoSpider(AcademicSpider):
    name = "sitio_felipe_bravo"
    expect = {
        "persona": 1,
        "afiliacion": 8,
        "area": 4,
        "perfil": 8,
        "formacion": 3,
        "dictacion": 20,
        "proyecto": 3,
        "distincion": 3,
        "tesis": 25,
        "actividad": 60,
        "producto": 2,
        "publicacion": 35,
    }

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(SITIO, self.parse_home, PERSONA)
            yield self.page(SITIO + "cv/", self.parse_cv, PERSONA)
            yield self.page(SITIO + "publications/", self.parse_publicaciones, PERSONA)

    def parse_home(self, response: Response) -> Iterator:
        art = response.css("article.md-content__inner")
        contacto = [texts(li) or "" for li in section(art, "contact")]
        tel = next((c for c in contacto if c.startswith("Phone")), "")
        email = next((c for c in contacto if c.startswith("Email")), "")
        yield self.item(
            "persona",
            response,
            nombre=clean(response.css("title::text").get()),
            telefono=clean(tel.partition(":")[2]),
            email=clean(email.partition(":")[2]),  # "fbravo at dcc.uchile.cl", tal como aparece
            oficina=contacto[0] if contacto else None,
            foto_url=response.urljoin(art.css("img::attr(src)").get("")) if art.css("img") else None,
        )
        for li in section(art, "affiliations"):
            links = li.css("a")
            yield self.item(
                "afiliacion",
                response,
                rol=texts(li.css("em")),
                organizacion=", ".join(filter(None, (texts(a) for a in links))) or texts(li),
                url_organizacion=links[0].attrib["href"] if links else None,
            )
        for li in section(art, "research-areas"):
            yield self.item("area", response, nombre=texts(li))
        for a in section(art, "other-profiles").css("a"):
            yield self.item("perfil", response, plataforma=(texts(a) or "").lower(), url_destino=a.attrib["href"])

        # Menú Teaching: links a los repos de los cursos
        for a in response.css("nav.md-nav--primary a.md-nav__link[href^='https://github.com']"):
            href = a.attrib["href"]
            codigo = re.search(r"/(CC\d+\w*)", href)
            yield self.item(
                "dictacion",
                response,
                nombre_curso=texts(a),
                codigo_curso=codigo.group(1) if codigo else None,
                url_curso=href,
            )
        yield from self.related(response)

    def parse_cv(self, response: Response) -> Iterator:
        art = response.css("article.md-content__inner")

        for li in section(art, "academic-positions-and-work-experience"):
            fecha, resto = bracket(li)
            rol, _, org = resto.partition(",")
            years = re.findall(r"\d{4}|present", fecha or "")
            yield self.item(
                "afiliacion",
                response,
                rol=clean(rol),
                organizacion=clean(org.strip(" .")) or clean(rol),
                desde=years[0] if years else None,
                hasta=years[-1] if len(years) > 1 else None,
                url_organizacion=li.css("a::attr(href)").get(),
            )

        for li in section(art, "qualifications"):
            # "PhD. Computer Science, University of Waikato (Jul. 2017)"
            m = re.match(r"(.+?),\s*(.+?)\s*\(([^)]*)\)", texts(li) or "")
            if m:
                anio = YEAR.search(m.group(3))
                yield self.item(
                    "formacion",
                    response,
                    grado=m.group(1),
                    institucion=m.group(2),
                    anio=anio.group() if anio else None,
                )

        for li in section(art, "teaching"):
            # "[CC6104] (Lecturer) Statistical Thinking (spring 2025, spring 2024), Computer Science Department, ..."
            codigo, resto = bracket(li)
            m = re.match(r"\(([^)]*)\)\s*(.+?)\s*\(([^)]*)\)", resto)
            if not m:
                continue
            for sem, anio in TERM.findall(m.group(3)):
                yield self.item(
                    "dictacion",
                    response,
                    codigo_curso=codigo,
                    rol=m.group(1),
                    nombre_curso=m.group(2),
                    semestre=sem,
                    anio=anio,
                    url_curso=li.css("a::attr(href)").get(),
                )

        for h3 in art.xpath("./h2[@id='grants']/following-sibling::h3[following-sibling::h2[1][@id='service']]"):
            for li in h3.xpath("following-sibling::ul[1]/li"):
                fecha, resto = bracket(li)
                years = YEAR.findall(fecha or "")
                fuente, sep, despues = resto.partition(". Proyect Title")
                titulo, codigo = despues.partition(":")[2], None
                if m := re.search(r"\.?\s*Code:\s*(.+)$", titulo):
                    titulo, codigo = titulo[: m.start()], m.group(1).strip(" .")
                titulo = re.split(r"\.\s+(?:PI:|In this project)", titulo)[0]
                yield self.item(
                    "proyecto",
                    response,
                    titulo=clean(titulo.strip(' ."“”')) if sep else clean(resto.strip(" .")),
                    fuente=clean(fuente) if sep else None,
                    codigo=clean(codigo),
                    rol=texts(h3),
                    anio_inicio=years[0] if years else None,
                    anio_fin=years[1] if len(years) > 1 else None,
                )

        for li in section(art, "scholarships-and-awards"):
            fecha, resto = bracket(li)
            anio = YEAR.search(fecha or "")
            nombre = clean(resto.strip(" ."))
            yield self.item("distincion", response, nombre=nombre, anio=anio.group() if anio else None)

        estudiantes = "./h2[@id='students']/following-sibling::h3[following-sibling::h2[1][@id='short-courses']]"
        for h3 in art.xpath(estudiantes):
            for li in h3.xpath("following-sibling::ul[1]/li"):
                # "[2022 - 2026] Fabián Villena, Co-supervised with Jocelyn Dunstan, PhD, University of Chile."
                fecha, resto = bracket(li)
                quoted = re.search(r"\"([^\"]+)\"", resto)
                partes = [p.strip(" .") for p in re.sub(r"\"[^\"]+\"", "", resto).split(",") if p.strip(" .")]
                rol = next((p for p in partes[1:] if p.startswith("Co-")), None)
                years = YEAR.findall(fecha or "")
                yield self.item(
                    "tesis",
                    response,
                    titulo=quoted.group(1) if quoted else clean(resto),  # sin título en la fuente: la entrada completa
                    estudiante=partes[0] if partes else None,
                    nivel=texts(h3),
                    rol=rol,
                    programa=", ".join(p for p in partes[1:] if p != rol) or None,
                    anio=years[-1] if years and "ongoing" not in (fecha or "") else None,
                )

        for h2 in art.css("h2"):
            tipo = ACTIVIDADES.get(texts(h2) or "")
            if not tipo:
                continue
            for li in h2.xpath("following-sibling::*[self::ul or self::ol][1]/li"):
                fecha, resto = bracket(li)
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad=tipo,
                    titulo=clean(resto),
                    fecha=fecha,
                    url_destino=li.css("a::attr(href)").get(),
                )

        for li in section(art, "software"):
            yield self.item(
                "producto",
                response,
                tipo_producto="software",
                nombre=clean(plain(li).strip(" .")),
                url_destino=li.css("a::attr(href)").get(),
            )
        yield from self.related(response, region="article")

    def parse_publicaciones(self, response: Response) -> Iterator:
        art = response.css("article.md-content__inner")
        for h3 in art.css("h3"):
            seccion = texts(h3)
            for li in h3.xpath("following-sibling::*[self::ul or self::ol][1]/li"):
                full = plain(li)
                a = next((x for x in li.css("a") if (texts(x) or "").lower() not in ("pdf", "codalab")), None)
                if a is None:
                    continue
                titulo = plain(a)
                antes, _, despues = full.partition(titulo)
                if seccion == "Theses":
                    # "PhD Thesis: <título> (pdf)"
                    yield self.item(
                        "publicacion",
                        response,
                        titulo=titulo,
                        tipo_publicacion=clean(antes.split(":")[0]),
                        url_destino=a.attrib["href"],
                        autores=[],
                    )
                    continue
                years = YEAR.findall(despues.split("DOI")[0])
                doi = DOI.search(despues)
                estado = re.search(r"\((to appear|under review|accepted)\)", despues, re.I)
                yield self.item(
                    "publicacion",
                    response,
                    titulo=titulo,
                    autores=[x for x in AUTHOR_SEP.split(antes.strip(" ,.")) if x],
                    venue=texts(li.css("em")),
                    anio=years[-1] if years else None,
                    doi=doi.group(1).rstrip(".,") if doi else None,
                    url_destino=a.attrib["href"],
                    tipo_publicacion=seccion,
                    estado=estado.group(1) if estado else None,
                )
        yield from self.related(response, region="article")
