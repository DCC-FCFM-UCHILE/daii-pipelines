"""Sitio personal de Francielle Vargas (Jekyll en GitHub Pages) y su CV en PDF.

El menú carga fragmentos HTML (`pages/<seccion>.html`) dentro del home con JS (`loadPage`), así que cada sección se
pide como página propia. Sus links relativos (`doc/...`, `pages/bib/...`) son relativos a la raíz del sitio, no al
fragmento: se inyecta `<base href>` antes de parsear para que `urljoin` y `related()` los resuelvan bien.

Del CV (`doc/cv.pdf`) se leen formación, trayectoria con fechas y proyectos con código y monto; el resto (charlas,
servicio, premios, publicaciones) ya está estructurado en el sitio. Las referencias del CV (con emails de terceros)
no se leen. Los estudiantes de "Teaching & Students" no traen título de tesis, así que no se emiten como `tesis`.
"""

import io
import re
import unicodedata
from collections.abc import Iterator

from pypdf import PdfReader
from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, texts

PERSONA = "francielle-vargas"
SITIO = "https://franciellevargas.github.io/"
SECCIONES = ("teaching", "publications", "resources", "service", "talks", "press", "awards")
CV = SITIO + "doc/cv.pdf"
ANIO = re.compile(r"\b(?:19|20)\d{2}\b")
PLATAFORMAS = {
    "Google Scholar": "scholar",
    "Semantic Scholar": "semanticscholar",
    "ORCID": "orcid",
    "LinkedIn": "linkedin",
    "GitHub": "github",
}
# Rótulos de la columna izquierda del CV (pueden compartir línea con la primera entrada).
CV_SECCIONES = re.compile(
    r"^(Education|Funded Research|Awards & Honors|Academic Experience|Teaching Experience|Publications)\b ?", re.M
)
# Acentos que pypdf deja separados en el CV LaTeX: "S˜ao", "T¨ubingen", "Fabr´ıcio".
ACENTO = re.compile(r"([´˜¨`ˆ¸])\s?([A-Za-zı])")
ACENTOS = {"´": "́", "˜": "̃", "¨": "̈", "`": "̀", "ˆ": "̂", "¸": "̧"}
PERIODO = re.compile(r"^(\d{2}/\d{4})(?:–(\d{2}/\d{4}|Present))? (.+)$")  # "05/2026–Present Assistant Professor"


def anio(text: str | None) -> str | None:
    return (ANIO.findall(text or "") or [None])[0]


def con_base(response: Response) -> Response:
    return response.replace(body=f'<base href="{SITIO}">'.encode() + response.body)


def cv_texto(body: bytes) -> str:
    t = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(body)).pages)
    t = ACENTO.sub(lambda m: m[2].replace("ı", "i") + ACENTOS[m[1]], t)
    return unicodedata.normalize("NFKC", t)


def cv_secciones(text: str) -> dict[str, str]:
    cortes = list(CV_SECCIONES.finditer(text))
    fines = [m.start() for m in cortes[1:]] + [len(text)]
    return {m.group(1): text[m.end() : fin] for m, fin in zip(cortes, fines, strict=True)}


def unir(lineas: str) -> str:
    """Une líneas del PDF deshaciendo el guionado ("Trust-\\nworthy")."""
    return clean(re.sub(r"(\w)-\n(\w)", r"\1\2", lineas)) or ""


class FrancielleVargasSpider(AcademicSpider):
    name = "sitio_francielle_vargas"
    expect = {
        "persona": 1,
        "perfil": 3,
        "afiliacion": 6,
        "area": 2,
        "formacion": 2,
        "proyecto": 7,
        "publicacion": 14,
        "producto": 7,
        "dictacion": 2,
        "distincion": 6,
        "actividad": 27,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(SITIO, self.parse_home, PERSONA)
        for seccion in SECCIONES:
            yield self.page(f"{SITIO}pages/{seccion}.html", getattr(self, f"parse_{seccion}"), PERSONA)
        yield self.page(CV, self.parse_cv, PERSONA)

    def parse_home(self, response: Response) -> Iterator:
        header = response.css("header.post-header")
        # Un solo <p>: antes del primer <br> los cargos, separados por ";"; después la biografía.
        # "Assistant Professor at X, <a>University of Chile</a>; Co-Lead PI in ... at Y, <a>U. of Tübingen</a>; and ..."
        p = header.css("p")[:1]
        antes = "./br[1]/preceding-sibling::text()|./br[1]/preceding-sibling::*//text()"
        cargos = clean("".join(p.xpath(antes).getall())) or ""
        tramos = [t for x in cargos.split(";") if (t := clean(x.strip(" .")))]
        links = p.xpath("./br[1]/preceding-sibling::a/@href").getall()
        despues = "./br[1]/following-sibling::text()|./br[1]/following-sibling::*//text()"
        bio = clean(" ".join(p.xpath(despues).getall()))
        yield self.item(
            "persona",
            response,
            nombre=texts(header.xpath("./div[1]/div[1]")),
            cargo=tramos[0].split(" at ")[0] if tramos else None,
            foto_url=response.urljoin(header.css("img::attr(src)").get("")),
            bio=bio,
        )
        for a in header.css("a[title]"):
            if a.attrib["title"] in PLATAFORMAS:
                orcid = re.search(r"orcid\.org/([\d-]+X?)", a.attrib["href"])
                yield self.item(
                    "perfil",
                    response,
                    plataforma=PLATAFORMAS[a.attrib["title"]],
                    url_destino=a.attrib["href"],
                    identificador=orcid.group(1) if orcid else None,
                )
        for i, tramo in enumerate(tramos):
            rol, _, org = re.sub(r"^and ", "", tramo).partition(" at ")
            yield self.item(
                "afiliacion",
                response,
                rol=rol,
                organizacion=re.sub(r"^the ", "", org) or rol,
                url_organizacion=links[i] if i < len(links) else None,
            )
        for li in response.xpath("//h6[a[normalize-space()='Research Projects']]/following-sibling::ul[1]/li"):
            href = li.css("a::attr(href)").get("")
            anio_inicio, _, fuente = (clean(" ".join(li.xpath("./text()").getall())) or "").partition(": ")
            snf = re.search(r"data\.snf\.ch/grants/grant/(\d+)", href)
            yield self.item(
                "proyecto",
                response,
                titulo=texts(li.css("a")),
                anio_inicio=anio(anio_inicio),
                fuente=fuente or None,  # "University of Tübingen", "Google LARA"
                codigo=snf.group(1) if snf else None,
            )
        for b in response.xpath("//h6[a[normalize-space()='Research Agenda']]/following-sibling::ul[1]/li/b"):
            yield self.item("area", response, nombre=texts(b))
        yield from self.related(response, region=".container")

    def parse_teaching(self, response: Response) -> Iterator:
        response = con_base(response)
        for it in response.css(".teaching-item"):
            yield self.item(
                "dictacion",
                response,
                nombre_curso=texts(it.css(".role")),
                anio=anio(texts(it.css(".year"))),  # "2026 – Present · Undergraduate Course"
                institucion=texts(it.css(".institution")),
            )
        yield from self.related(response)

    def parse_publications(self, response: Response) -> Iterator:
        response = con_base(response)
        for li in response.css("li.pub-item"):
            seccion = texts(li.xpath("preceding::h3[@class='pub-type'][1]")) or ""  # "2026" / "Preprints"
            venue = texts(li.css(".pub-details b i"))
            antes_br = "./br/preceding-sibling::text()|./br/preceding-sibling::*//text()"  # autores, antes del <br>
            autores = clean(" ".join(li.css(".pub-details").xpath(antes_br).getall()))
            pdf = li.css(".pub-buttons a::attr(href)").get()
            ids = {}
            if pdf and (m := re.search(r"aclanthology\.org/([\w.-]+?)/?$", pdf)):
                ids["acl"] = m.group(1)
            if pdf and (m := re.search(r"arxiv\.org/(?:abs|pdf)/([\d.]+)", pdf)):
                ids["arxiv"] = m.group(1)
            yield self.item(
                "publicacion",
                response,
                titulo=texts(li.css(".pub-title")),
                anio=seccion if seccion.isdigit() else anio(venue),
                tipo_publicacion=None if seccion.isdigit() else seccion,
                venue=venue,
                autores=[a.strip(" *") for a in (autores or "").split(",") if a.strip(" *")],
                url_destino=response.urljoin(pdf) if pdf else None,
                ids=ids,
            )
        yield from self.related(response)

    def parse_resources(self, response: Response) -> Iterator:
        response = con_base(response)
        for li in response.css(".resource-section li"):
            a = li.css("a")
            yield self.item(
                "producto",
                response,
                tipo_producto=texts(li.xpath("ancestor::div[@class='resource-section'][1]/h3")),  # "Benchmark Datasets"
                nombre=texts(a[:1]),
                descripcion=clean((texts(li) or "").removeprefix(texts(a[:1]) or "").lstrip(" :")) or None,
                url_destino=response.urljoin(a[0].attrib["href"]) if a else None,
            )
        yield from self.related(response)

    def parse_service(self, response: Response) -> Iterator:
        response = con_base(response)
        for li in response.css(".service-category li"):
            categoria = texts(li.xpath("ancestor::div[@class='service-category'][1]/h6")) or ""
            sub = texts(li.xpath("parent::ol/preceding-sibling::h9[1]")) or ""
            if categoria.startswith("Scientific"):
                tipo = "asesoria"
            elif categoria == "Organizing Committee":
                tipo = "comite_programa" if sub == "Area Chairing" else "organizacion_evento"
            else:
                tipo = "revisor" if sub == "Journals" else "comite_programa"
            # "<h8>NeurIPS: ...</h8> <a>(2026)</a> <a>(2023)</a>" → fecha "2026, 2023"
            fechas = [t.strip("() ") for a in li.css("a") if (t := texts(a))]
            yield self.item(
                "actividad",
                response,
                tipo_actividad=tipo,
                titulo=clean(" ".join(li.css("h8").xpath("./text()|./*[not(self::a)]//text()").getall())) or texts(li),
                rol=sub or categoria,
                fecha=", ".join(fechas) or anio(texts(li)),
                url_destino=li.css("a::attr(href)").get(),
            )
        yield from self.related(response)

    def parse_talks(self, response: Response) -> Iterator:
        response = con_base(response)
        for it in response.css(".talk-item"):
            linea = it.css(".talk-line span")
            rol = (texts(linea.css("b")) or "").split(":")[0]  # "Invited Talk", "Keynote Speaker", "Presentation"
            slides = it.xpath(".//a[normalize-space()='[slides]']/@href").get()
            yield self.item(
                "actividad",
                response,
                tipo_actividad="keynote" if "Keynote" in rol else "charla",
                titulo=next((t for i in linea.css("i") if (t := texts(i))), None) or texts(linea) or "",
                rol=rol or None,
                evento=texts(it.css("p a")),
                descripcion=clean("".join(it.css("p").xpath("./b//text()|./text()").getall())),  # "Leiden U., NL"
                fecha=texts(it.xpath("ancestor::div[@class='year-card'][1]/div[@class='year-title']")),
                url_destino=response.urljoin(slides) if slides else None,
            )
        yield from self.related(response)

    def parse_press(self, response: Response) -> Iterator:
        response = con_base(response)
        for li in response.css(".news-item"):
            medio, _, fecha = (texts(li.css(".news-meta")) or "").rpartition(" · ")
            yield self.item(
                "actividad",
                response,
                tipo_actividad="prensa",
                titulo=texts(li.css(".news-title")),
                evento=medio or None,
                fecha=fecha or None,
                url_destino=li.css("a::attr(href)").get(),
            )
        yield from self.related(response)

    def parse_awards(self, response: Response) -> Iterator:
        response = con_base(response)
        for div in response.css(".award"):
            yield self.item(
                "distincion",
                response,
                nombre=texts(div.css(".award-title")),
                otorgante=texts(div.css(".award-institution")),
                anio=anio(texts(div.xpath("preceding-sibling::div[@class='award-year'][1]"))),
            )
        yield from self.related(response)

    def parse_cv(self, response: Response) -> Iterator:
        s = cv_secciones(cv_texto(response.body))
        # "PhD in Computer Science and Computational Mathematics 2024\nUniversity of São Paulo (USP)"
        for grado, year, inst in re.findall(r"^(.+?) ((?:19|20)\d{2})\n(.+)$", s.get("Education", ""), re.M):
            yield self.item("formacion", response, grado=grado, anio=year, institucion=inst.strip())

        exp = s.get("Academic Experience", "").splitlines()
        for i, line in enumerate(exp):
            if (m := PERIODO.match(line.strip())) and i + 1 < len(exp):
                yield self.item(
                    "afiliacion",
                    response,
                    rol=m.group(3),
                    organizacion=exp[i + 1].strip(),
                    desde=m.group(1),
                    hasta=None if m.group(2) == "Present" else m.group(2) or m.group(1),
                )

        # "• 2026–Present. University of Chile. Principal Investigator. Título. Detalle... (USD 12.000,00)."
        for item in re.split(r"^• ", s.get("Funded Research", ""), flags=re.M)[1:]:
            t = unir(item)
            partes = re.split(r"\.\s+(?=[A-Z])", t, maxsplit=4)
            if len(partes) < 4:
                continue
            desde, _, hasta = partes[0].partition("–")
            codigo = re.search(r"Grant number: (?:No\. )?([\w/-]+)", t)
            monto = re.search(r"\((USD [\d.,]+)\)", t)
            yield self.item(
                "proyecto",
                response,
                anio_inicio=desde,
                anio_fin=None if hasta == "Present" else hasta or desde,
                fuente=partes[1],
                rol=partes[2],
                titulo=partes[3],
                codigo=codigo.group(1) if codigo else None,
                monto=monto.group(1) if monto else None,
            )
