"""Sitio personal de Sebastián Ferrada (Hugo/Wowchemy) y su CV en PDF.

Fuentes:
- Home: persona, perfiles, afiliaciones actuales (prosa de la biografía), intereses y formación.
- Listados `/publication/` y `/event/` (talks): no traen venue ni evento, así que se sigue cada página de detalle
  (`Publication`, `Event`, `Location`). Los demás listados (`/project/`, `/promotion/`, `/news/`, `/press/`) traen
  todo en el listado. Las noticias sobre papers aceptados se omiten (las publicaciones ya vienen del listado).
- `uploads/resume.pdf`: cargos con fechas, proyectos con código, premios, servicio, tesis guiadas y docencia.
  Sus publicaciones no se leen (el sitio y DBLP/ORCID las cubren).
"""

import io
import re
import unicodedata
from collections.abc import Iterator
from urllib.parse import urlparse

from pypdf import PdfReader
from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, texts

PERSONA = "sebastian-ferrada"
SITIO = "https://sferrada.com/"
CV = SITIO + "uploads/resume.pdf"
ANIO = re.compile(r"\b(?:19|20)\d{2}\b")
# "an Assistant Professor at the X and the Y at Universidad de Chile, where ..." / "a Junior Researcher at the Z (IMFD)"
CARGO = re.compile(r"\ban? ((?:[A-Z][\w-]* )+)at the (.+?)(?=, where| and a |\.\s|\.$)")
PLATAFORMAS = {
    "twitter.com": "twitter",
    "scholar.google.com": "scholar",
    "github.com": "github",
    "ingenieria.uchile.cl": "fcfm",
    "portafolio-academico.uchile.cl": "portafolio",
}
# CV: rótulos de sección y subsección (líneas completas).
SECCIONES = {
    "Education and Academic Degrees": "formacion",
    "Academic Positions": "afiliacion",
    "Research Projects": "proyecto",
    "Publications": None,
    "Honours and Awards": "distincion",
    "Community Service": "servicio",
    "Student Supervision": "tesis",
    "Teaching": "dictacion",
}
SUBSECCIONES = {
    "As Principal Investigator",
    "As Researcher",
    "Scientific Journal Duties",
    "Conference Programme Committees",
    "Scientific Event Organization",
    "Tutorials",
    "Graduate Students",
    "Undergraduate Students",
}
ENTRADA = re.compile(r"^(\d{4}(?:–(?:\d{4}|Now))?|Since \d{4}|[A-Z][a-z]{2}\. \d{4}) (.+)$")  # "2024–Now Assistant..."
COMA = re.compile(r",\s+(?![^()]*\))")  # coma fuera de paréntesis


def plain(sel) -> str | None:
    """Texto de un nodo sin insertar espacios entre hijos ("(<a>IMFD</a>)" → "(IMFD)")."""
    return clean("".join(sel.css("::text").getall()))


def anio(text: str | None) -> str | None:
    return (ANIO.findall(text or "") or [None])[-1]


def filas(response: Response) -> dict[str, str | None]:
    """Filas "Type / Publication / Event / Location" de una página de detalle Wowchemy."""
    return {texts(h) or "": texts(h.xpath("following-sibling::div[1]")) for h in response.css(".pub-row-heading")}


def cv_texto(body: bytes) -> str:
    t = unicodedata.normalize("NFKC", "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(body)).pages))
    return re.sub(r"(\w)-\n(\w)", r"\1\2", t)  # deshace el guionado de LaTeX ("CE-\nNIA")


def cv_secciones(text: str) -> dict[str, list[tuple[str, str, str]]]:
    """Entradas del CV por sección: (subsección, fecha, texto). Una entrada empieza con fecha o con "◦"."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    actual, sub, fecha, lineas = None, "", "", []

    def cerrar():
        if actual and lineas:
            out.setdefault(actual, []).append((sub, fecha, clean(" ".join(lineas)) or ""))

    for line in (x.strip() for x in text.splitlines()):
        if line in SECCIONES or line in SUBSECCIONES:
            cerrar()
            if line in SECCIONES:
                actual = SECCIONES[line]
            sub, fecha, lineas = (line if line in SUBSECCIONES else ""), "", []
        elif m := ENTRADA.match(line):
            cerrar()
            fecha, lineas = m.group(1), [m.group(2)]
        elif line.startswith("◦"):
            cerrar()
            fecha, lineas = "", [line.lstrip("◦ ")]
        elif lineas:
            lineas.append(line)
    cerrar()
    return out


class SebastianFerradaSpider(AcademicSpider):
    name = "sitio_sebastian_ferrada"
    expect = {
        "persona": 1,
        "perfil": 3,
        "afiliacion": 5,
        "area": 2,
        "formacion": 3,
        "publicacion": 12,
        "proyecto": 4,
        "distincion": 5,
        "tesis": 7,
        "dictacion": 10,
        "actividad": 25,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(SITIO, self.parse_home, PERSONA)
        yield self.page(SITIO + "publication/", self.parse_publicaciones, PERSONA)
        yield self.page(SITIO + "event/", self.parse_charlas, PERSONA)
        yield self.page(SITIO + "project/", self.parse_proyectos, PERSONA)
        yield self.page(SITIO + "promotion/", self.parse_premios, PERSONA)
        yield self.page(SITIO + "news/", self.parse_noticias, PERSONA)
        yield self.page(SITIO + "press/", self.parse_noticias, PERSONA)
        yield self.page(CV, self.parse_cv, PERSONA)

    def detalle(self, response: Response, href: str, callback):
        # dont_filter: si related() de otra página ya pidió este detalle como `pagina`, igual se parsea aquí.
        return self.page(response.urljoin(href), callback, PERSONA).replace(dont_filter=True)

    def parse_home(self, response: Response) -> Iterator:
        about = response.css("#about")
        bio = about.css(".article-style > p")
        yield self.item(
            "persona",
            response,
            nombre=texts(about.css(".portrait-title h2")),
            cargo=texts(about.css(".portrait-title h3:not(:has(a))")),
            foto_url=response.urljoin(about.css("img.avatar::attr(src)").get("")),
            bio=clean(" ".join(plain(p) or "" for p in bio)),
        )
        for href in about.css(".network-icon a::attr(href)").getall():
            netloc = urlparse(href).netloc.removeprefix("www.")
            if netloc in PLATAFORMAS:
                yield self.item("perfil", response, plataforma=PLATAFORMAS[netloc], url_destino=href)

        # Cargos actuales en la prosa de la biografía; la url sale del link cuyo texto está en la organización.
        links = [(texts(a) or "", a.attrib["href"]) for a in bio.css("a")]
        for cargo, orgs in CARGO.findall(plain(bio[0]) or "" if bio else ""):
            for org in orgs.split(" and the "):
                yield self.item(
                    "afiliacion",
                    response,
                    rol=cargo.strip(),
                    organizacion=org,
                    url_organizacion=next((h for t, h in links if t and t in org), None),
                )
        for li in about.css(".ul-interests li"):
            yield self.item("area", response, nombre=texts(li))
        for li in about.css(".ul-edu li"):
            grado, _, year = (texts(li.css(".course")) or "").rpartition(", ")  # "PhD in Computer Science, 2021"
            yield self.item(
                "formacion", response, grado=grado or year, anio=year if grado else None,
                institucion=texts(li.css(".institution")),
            )  # fmt: skip
        yield from self.related(response, region="#about")

    def parse_publicaciones(self, response: Response) -> Iterator:
        for href in response.css("#container-publications .view-list-item > a::attr(href)").getall():
            yield self.detalle(response, href, self.parse_publicacion)
        yield from self.related(response, region="#container-publications")

    def parse_publicacion(self, response: Response) -> Iterator:
        pub = response.css(".pub")
        f = filas(response)
        doi = next((h for h in pub.css("a::attr(href)").getall() if "doi.org/" in h), None)
        pdf = pub.xpath(".//a[normalize-space(.)='PDF']/@href").get()
        yield self.item(
            "publicacion",
            response,
            titulo=texts(pub.css("h1")),
            anio=anio(texts(pub.css(".article-date"))),
            tipo_publicacion=f.get("Type"),
            venue=f.get("Publication"),
            autores=[a for s in pub.css(".article-metadata > div > span") if (a := texts(s))],
            doi=doi.split("doi.org/", 1)[1] if doi else None,
            url_destino=response.urljoin(pdf) if pdf else None,
        )

    def parse_charlas(self, response: Response) -> Iterator:
        for href in response.css("#talk_list .article-title a::attr(href)").getall():
            yield self.detalle(response, href, self.parse_charla)
        yield from self.related(response, region="#talk_list")

    def parse_charla(self, response: Response) -> Iterator:
        f = filas(response)
        slides = response.xpath("//a[normalize-space(.)='Slides']/@href").get()
        yield self.item(
            "actividad",
            response,
            tipo_actividad="charla",
            titulo=texts(response.css(".article-container h1")),
            evento=f.get("Event"),
            fecha=f.get("Date"),
            descripcion=f.get("Location"),
            url_destino=response.urljoin(slides) if slides else None,
        )

    def parse_proyectos(self, response: Response) -> Iterator:
        for card in response.css(".universal-wrapper .card-simple"):
            yield self.item(
                "proyecto",
                response,
                titulo=texts(card.css(".article-title a")),
                fuente=texts(card.css(".article-style")),  # "Fondecyt Iniciación 2025, financiado por ANID."
                anio_inicio=anio(texts(card.css(".article-date"))),
            )
        yield from self.related(response, region=".universal-wrapper")

    def parse_premios(self, response: Response) -> Iterator:
        for card in response.css(".universal-wrapper .card-simple"):
            desc = texts(card.css(".article-style")) or ""
            at = re.search(r"\bat (?:the )?(.+?)\.?$", desc)  # "For the paper ..., at the 29th International ..."
            yield self.item(
                "distincion",
                response,
                nombre=texts(card.css(".article-title a")),
                otorgante=at.group(1) if at else None,
                anio=anio(texts(card.css(".article-date"))),
            )
        yield from self.related(response, region=".universal-wrapper")

    def parse_noticias(self, response: Response) -> Iterator:
        """`/news/` y `/press/`: "<strong>Título</strong> — <em>Medio</em>, resto. <a>Read</a>"."""
        for it in response.css(".news-item"):
            titulo = texts(it.css("strong")) or ""
            if "paper" in titulo.lower():
                continue
            cuerpo = "./text()|./em//text()|./a[not(@class)]//text()"  # sin el botón "Read/Watch"
            cuerpo = clean("".join(it.css(".news-text").xpath(cuerpo).getall()))
            yield self.item(
                "actividad",
                response,
                tipo_actividad="prensa",
                titulo=titulo,
                evento=texts(it.css(".news-text > em")[:1]) if "press-item" in it.attrib.get("class", "") else None,
                descripcion=(cuerpo or "").lstrip("— ") or None,
                fecha=texts(it.css(".news-date")),
                url_destino=it.css("a::attr(href)").get(),
            )
        yield from self.related(response, region=".page-body")

    def parse_cv(self, response: Response) -> Iterator:
        s = cv_secciones(cv_texto(response.body))
        for _, fecha, t in s.get("formacion", []):
            m = re.match(r"(.+?), ((?:Universidad|University)[^,.]*)", t)
            tesis = re.search(r"Thesis: (.+?)\.(?: Supervisors|$)", t)
            yield self.item(
                "formacion",
                response,
                grado=m.group(1) if m else t.split(", ")[0],
                institucion=m.group(2) if m else None,
                anio=fecha,
                titulo_tesis=tesis.group(1) if tesis else None,
            )
        for _, fecha, t in s.get("afiliacion", []):
            rol, _, org = t.partition(", ")  # "Assistant Professor, Data & ... (IDIA). Universidad de Chile, ..."
            desde, _, hasta = fecha.partition("–")
            yield self.item(
                "afiliacion", response, rol=rol, organizacion=org.rstrip("."), desde=desde,
                hasta=None if hasta == "Now" else hasta or desde,
            )  # fmt: skip
        for sub, fecha, t in s.get("proyecto", []):
            # "Título, Fuente, Proyecto Nr. 11251322." / "..., Role: X. Principal Investigator: Y."
            partes = COMA.split(t)
            codigo = re.search(r"\bNr\. ([\w-]+)", t)
            rol = re.search(r"Role: (.+?)\.(?:\s+Principal|$)", t)
            ir = re.search(r"Principal Investigator: (.+?)\.?$", t)
            desde, _, hasta = fecha.partition("–")
            yield self.item(
                "proyecto",
                response,
                titulo=partes[0],
                fuente=re.sub(r"\s*(?:Project|Research Project)? Nr\..*$", "", partes[1]).rstrip(".") or None
                if len(partes) > 1
                else None,
                codigo=codigo.group(1) if codigo else None,
                rol=rol.group(1) if rol else sub.removeprefix("As ") or None,
                anio_inicio=desde,
                anio_fin=hasta or desde,
                investigador_responsable=ir.group(1) if ir else None,
            )
        for _, fecha, t in s.get("distincion", []):
            por = re.search(r"\b(?:at|by) (?:the )?([^,.]+)", t)
            yield self.item(
                "distincion",
                response,
                nombre=COMA.split(t)[0],
                otorgante=por.group(1) if por else None,
                anio=anio(fecha),
            )
        yield from self.cv_servicio(response, s.get("servicio", []))
        for sub, _, t in s.get("tesis", []):
            # "Benito Fuentes, Thesis: “Título”. M.Sc. in Data Science, Universidad de Chile. Ongoing. Role: Supervisor"
            m = re.match(r"(.+?), Thesis: “(.+?)”\.\s*(.+?), (.+?)\. (Ongoing|Graduated[^.]*)\. Role: (.+)$", t)
            if not m:
                continue
            yield self.item(
                "tesis",
                response,
                estudiante=m.group(1),
                titulo=m.group(2),
                programa=f"{m.group(3)}, {m.group(4)}",
                nivel=sub or None,
                estado=m.group(5),
                anio=anio(m.group(5)),
                rol=m.group(6),
            )
        for _, _, t in s.get("dictacion", []):
            # "Databases, MDS, U. de Chile, Spring 2024, Autumn 2025. Course level: undergraduate Role: Lecturer (...)"
            curso, _, rol = t.partition(" Role: ")
            curso = curso.split(" Course level:")[0].rstrip(".")
            inst = re.search(r"U\. de Chile|Linköping University", curso)
            yield self.item(
                "dictacion",
                response,
                nombre_curso=curso.split(", ")[0],
                institucion=inst.group(0) if inst else None,
                semestre=curso[inst.end() :].strip(" ,") or None if inst else None,  # "Spring 2024, Autumn 2025"
                rol=rol or None,
            )

    def cv_servicio(self, response: Response, entradas: list[tuple[str, str, str]]) -> Iterator[dict]:
        for sub, fecha, t in entradas:
            partes = COMA.split(t.rstrip("."))
            if sub == "Scientific Journal Duties":  # "Transactions on ... (TGDK), Editorial Board Member."
                tipo = "editorial" if "Editor" in t else "revisor"
                rol = partes[-1]
            elif sub == "Conference Programme Committees":  # "ISWC, Programme Committee Member, Research Track."
                tipo, rol = "comite_programa", partes[1] if len(partes) > 1 else None
            elif sub == "Tutorials":  # "SICSS-Chile, “An Introduction to Knowledge Graphs”, Santiago, Chile."
                tipo, rol = "tutorial", None
            else:  # "13th International Conference on Knowledge Capture, Dec 10–12, Dayton, OH, USA, Program Co-Chair."
                tipo, rol = "organizacion_evento", partes[-1]
            cita = re.search(r"“(.+?)”", t)
            yield self.item(
                "actividad",
                response,
                tipo_actividad=tipo,
                titulo=cita.group(1) if cita else partes[0],
                evento=partes[0],
                rol=rol,
                fecha=fecha,
                descripcion=t,
            )
