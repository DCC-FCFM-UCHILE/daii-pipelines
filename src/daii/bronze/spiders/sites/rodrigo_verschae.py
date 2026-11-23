"""Sitio personal de Rodrigo Verschae (Jekyll academicpages): home, publicaciones, líneas de investigación y noticias.

La trayectoria (afiliaciones con fechas) y la formación vienen en prosa en "About Me"; se separan con regex sobre
frases y se guardan tal como aparecen. Los estudiantes no traen título de tesis, así que no se emiten como `tesis`.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, anio, anios, clean, email, plain

SITIO = "https://rodrigo.verschae.org/"
PERSONA = "rodrigo-verschae"
# Fechas de un tramo de trayectoria: "(2018-2026)", "Since August 2026", "From 2020 to 2023"
PERIODO = re.compile(r"\((\d{4})(?:-(\d{4}))?\),?|Since (\w+ \d{4}),?|From (\d{4}) to (\d{4}),?")
GRADO = re.compile(r"an? ([^()]+?) \(((?:[^()]|\([^()]*\))+), (\d{4})\)")  # "a M.Sc. in X (ENS (..), France, 2006)"
TAG = re.compile(r"^\[([^\]]+)\],?\s*(.*)$")  # "[New Paper] resto"
QUOTE = re.compile(r"[“\"]")
# Etiqueta de noticia "[New Visit]" → tipo_actividad; sin palabra clave clara es "noticia"
NOTICIAS = {
    "visit": "visita",
    "tutorial": "tutorial",
    "speaker": "charla",
    "editor": "editorial",
    "organizing": "organizacion_evento",
}


def tramos(texto: str) -> Iterator[tuple[str, str | None, str | None]]:
    """Parte la prosa de trayectoria en (cargo en org, desde, hasta)."""
    for frase in re.split(r"(?<=[a-z)])\.\s+(?=[A-Z])", texto):
        if frase.startswith("I received"):
            continue
        for tramo in re.split(r"\s*(?:and )?[Bb]efore that\s*|,\s+(?:and\s+)?(?=an? [a-z])", frase):
            m = PERIODO.search(tramo)
            if not m:
                continue
            desde = m.group(1) or m.group(3) or m.group(4)
            hasta = m.group(2) or m.group(5) or (m.group(1) if m.group(1) else None)
            resto = (tramo[: m.start()] + tramo[m.end() :]).strip(" ,.")
            resto = re.sub(r"^I (?:was|am|have been)\s+|^an?\s+", "", resto)
            yield re.sub(r"^an?\s+", "", resto), desde, hasta


def cargo_org(texto: str) -> tuple[str | None, str]:
    """ "associate professor at the X" → ("associate professor", "X"). Sin separador: (None, texto)."""
    sin_parentesis = re.sub(r"\([^()]*\)", lambda m: "_" * len(m.group()), texto)  # "(... of the FONDECYT ...)"
    cortes = [(i, sep) for sep in (" at ", " of ", " the ") if (i := sin_parentesis.find(sep)) >= 0]
    if not cortes:
        return None, texto
    i, sep = min(cortes)
    return texto[:i].strip(" ,"), re.sub(r"^the ", "", texto[i + len(sep) :]).strip(" ,")


class RodrigoVerschaeSpider(AcademicSpider):
    name = "sitio_rodrigo_verschae"
    expect = {
        "persona": 1,
        "perfil": 4,
        "afiliacion": 5,
        "formacion": 2,
        "publicacion": 30,
        "area": 5,
        "proyecto": 2,
        "actividad": 10,
    }

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(SITIO, self.parse_home, PERSONA)
            yield self.page(SITIO + "publications/", self.parse_publications, PERSONA)
            yield self.page(SITIO + "research/", self.parse_research, PERSONA)
            yield self.page(SITIO + "news/", self.parse_news, PERSONA)

    def parse_home(self, response: Response) -> Iterator:
        content = response.css(".page__content")
        about = " ".join(plain(p) or "" for p in content.xpath("./h1[@id='about-me']/following-sibling::p"))
        yield self.item(
            "persona",
            response,
            nombre=plain(response.css(".author__name")),
            cargo=plain(response.css(".author__bio")),
            email=email(response.css(".author__urls a[href^=mailto]::attr(href)").get()),
            foto_url=response.css(".author__avatar img::attr(src)").get(),
            bio=clean(about),
        )
        for a in response.css(".author__urls a"):
            href = a.attrib["href"]
            if href.startswith("mailto:") or href.rstrip("/") == SITIO.rstrip("/"):
                continue
            orcid = re.search(r"orcid\.org/([\d-]+X?)", href)
            yield self.item(
                "perfil",
                response,
                plataforma=(plain(a) or "").lower(),
                url_destino=href,
                identificador=orcid.group(1) if orcid else None,
            )

        # "Faculty at <a>IDIA</a>, the Data and IA Initiative ..." / "<a>Robotics and Intelligent Systems Lab</a>"
        for li in content.xpath("./h2[@id='affiliations']/following-sibling::ul[1]/li"):
            rol, sep, _ = (plain(li) or "").partition(" at ")
            yield self.item(
                "afiliacion",
                response,
                organizacion=plain(li.css("a")),
                rol=rol if sep else None,
                url_organizacion=li.css("a::attr(href)").get(),
            )
        vistos = set()
        logros = content.xpath("./h1[@id='accomplishments']/following-sibling::ul[1]/li")
        for texto in [about, *(plain(li) or "" for li in logros)]:
            for tramo, desde, hasta in tramos(texto):
                rol, org = cargo_org(tramo)
                if (org, desde) not in vistos:
                    vistos.add((org, desde))
                    yield self.item("afiliacion", response, organizacion=org, rol=rol, desde=desde, hasta=hasta)

        # "I received a Doctoral degree in Electrical Engineering (Universidad de Chile, 2010), a M.Sc. ..."
        recibidos = next((f for f in re.split(r"(?<=\))\.\s+", about) if "I received" in f), "")
        for grado, inst, egreso in GRADO.findall(recibidos):
            yield self.item("formacion", response, grado=grado, institucion=inst, anio=egreso)

        for li in logros:
            t = plain(li) or ""
            # "... received the <strong>2025 ... Award</strong> from the Institute of Engineers of Chile for ..."
            if premio := plain(li.css("strong")):
                m = re.search(r"from (?:the )?(.+?)(?: for |\.|$)", t)
                yield self.item(
                    "distincion",
                    response,
                    nombre=premio,
                    otorgante=m.group(1) if m else None,
                    anio=anio(t),
                )
            elif "Editor" in t:
                fecha = anio(t)
                yield self.item(
                    "actividad", response, tipo_actividad="editorial", titulo=t, fecha=str(fecha) if fecha else None
                )
        yield from self.related(response, region="#main")

    def parse_publications(self, response: Response) -> Iterator:
        for art in response.css(".list__item article"):
            seccion = plain(art.xpath("ancestor::div[@class='list__item'][1]/preceding-sibling::h2[1]")) or ""
            titulo = plain(art.css(".archive__item-title"))
            if seccion.startswith("Talks"):
                desc = plain(art.css(".archive__item-excerpt")) or ""
                partes = desc.split(", ")  # "Tutorial, FG2026, Kyoto, Japan" / "Talk, London School of Testing, ..."
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="tutorial" if partes[0] == "Tutorial" else "charla",
                    titulo=titulo,
                    descripcion=desc or None,
                    evento=partes[1] if len(partes) > 1 else None,
                    fecha=plain(art.css(".page__meta")),
                    url_destino=art.css(".archive__item-title a::attr(href)").get(),
                )
                continue
            publicado = plain(art.xpath("./p[starts-with(normalize-space(.), 'Published in')]"))
            cita = plain(art.xpath("./p[starts-with(normalize-space(.), 'Recommended citation')]")) or ""
            cita = cita.removeprefix("Recommended citation:").strip()
            autores = QUOTE.split(cita, maxsplit=1)[0].strip(" ,") if QUOTE.search(cita) else ""
            ys = anios(publicado)
            yield self.item(
                "publicacion",
                response,
                titulo=titulo,
                anio=ys[-1] if ys else None,
                tipo_publicacion=seccion or None,
                venue=plain(art.xpath("./p[starts-with(normalize-space(.), 'Published in')]/i")),
                autores=[a.strip() for a in autores.split(",") if a.strip()],
                url_destino=art.xpath(".//a[contains(., 'Download Paper')]/@href").get()
                or art.css(".archive__item-title a::attr(href)").get(),
            )
        yield from self.related(response, region="#main")

    def parse_research(self, response: Response) -> Iterator:
        content = response.css(".page__content")
        for h2 in content.xpath("./h2"):
            yield self.item("area", response, nombre=plain(h2))
            for li in h2.xpath("following-sibling::ul[1]/li"):
                yield self.item("area", response, nombre=plain(li))
        # "Director, FOVI Project “Artificial ...”, Universidad de O’Higgins, Chile"
        for li in content.xpath("./h1[@id='current-main-research-projects']/following-sibling::ul[1]/li"):
            t = plain(li) or ""
            rol, _, resto = t.partition(", ")
            fuente, _, resto = resto.partition("“")
            titulo, _, _ = resto.partition("”")
            codigo = re.search(r"\b([A-Z]{2}\d{2}[A-Z]\d{4,})\b", fuente)
            yield self.item(
                "proyecto",
                response,
                titulo=titulo or t,
                fuente=clean(fuente.strip(" ,-")) or None,
                codigo=codigo.group(1) if codigo else None,
                rol=rol,
            )
        yield from self.related(response, region=".page__content")

    def parse_news(self, response: Response) -> Iterator:
        for li in response.css(".page__content li"):
            m = TAG.match(plain(li) or "")
            if not m or "paper" in m.group(1).lower():  # los papers ya vienen de /publications/
                continue
            etiqueta = m.group(1)
            h2 = li.xpath("ancestor::ul[1]/preceding-sibling::h2[1]/text()").get()
            yield self.item(
                "actividad",
                response,
                tipo_actividad=next((v for k, v in NOTICIAS.items() if k in etiqueta.lower()), "noticia"),
                titulo=m.group(2).strip(" ,") or etiqueta,
                descripcion=etiqueta,
                fecha=clean(h2),
                url_destino=li.css("a::attr(href)").get(),
            )
        yield from self.related(response, region=".page__content")
