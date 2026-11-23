"""Sitio personal de Doris Sáez Hueichapan (WordPress, inglés): home, Publications, Research Projects, Students,
Teaching y su CV en PDF.

Se parsea el HTML y no `?rest_route=/wp/v2/pages`: la API trae el mismo `content.rendered` que `.entry-content`
(Gutenberg sin shortcodes), pero no la barra lateral "Links of interest" (Mapuche Communities, Indigenous People
Program, Kimeltuwe Lof Tech...), que es justo donde aparece su trabajo con comunidades indígenas; además con HTML
`related()` registra los links y `pages/` guarda lo mismo que ve una persona.

Del CV (URL en `config/academicos.yaml`, `perfiles.cv`) se leen solo las secciones previas a PUBLICATIONS que el
sitio no tiene: formación, cargos (incluida la Subdirección de Pueblos Indígenas), editoriales, premios y sociedades.
Publicaciones, proyectos, estudiantes y cursos del CV repiten lo del sitio. La cabecera del CV trae RUT, fecha de
nacimiento y dirección: no se lee.
"""

import io
import re
from collections.abc import Iterator

from pypdf import PdfReader
from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, autores, clean, texts
from daii.config import academico

PERSONA = "doris-saez"
BASE = "https://www.cec.uchile.cl/~dsaez/"
PUBLICATIONS = BASE + "?page_id=16"
STUDENTS = BASE + "?page_id=615"
PROJECTS = BASE + "?page_id=619"
TEACHING = BASE + "?page_id=633"
MAIN = ".entry-content"
SIDEBAR = "#primary"

ANIO = re.compile(r"\b(?:19|20)\d{2}\b")
DOI = re.compile(r"\b10\.\d{4,9}/[^\s,]+")
APA = re.compile(r"(?<=\(\d{4}\)\.\s)(.+?)\.\s")  # "Autores (2022). Título. Revista, ..." (OTHER JOURNALS)
TITULO = re.compile(r"«\s*(.+?)[,.]?\s*»")
# "2024-2026 FONDEF IDeA project ID24I10010 «Título», Director." / "2020-2021. FONDEF ID19I10363 «...», Co-Inv."
PROYECTO = re.compile(r"^(\d{4})(?:\s*-\s*(\d{4}))?\.?\s+(.*?),?\s*«(.+?)»,?\s*(.*?)\.?$")
INDIGENA = re.compile(r"Mapuche|Indigenous|Kimeltuwe", re.IGNORECASE)
# CV: rótulo de sección → clave (None = se ignora). Se corta en PUBLICATIONS.
SECCIONES = {
    "EDUCATION": "formacion",
    "POSITIONS": "cargo",
    "JOURNAL ASSOCIATE EDITOR": "editorial",
    "AWARDS": "distincion",
    "PARTICIPATION IN SCIENTIFIC SOCIETIES": "sociedad",
    "PUBLICATIONS": None,
}
ENTRADA_CV = re.compile(r"^(\d{4})(?:\s*-\s*(\d{4}|Date))?\s+(.*)$")  # "2019 - Date Founding Member, ..."


def secciones_cv(texto: str) -> dict[str, list[tuple[str | None, str | None, str]]]:
    """Entradas (desde, hasta, texto) por sección. Una línea sin año tras una entrada terminada en "." abre la
    siguiente (en AWARDS el año queda en la línea del medio)."""
    out: dict[str, list[tuple[str | None, str | None, str]]] = {}
    seccion = None
    pendiente = ""
    for raw in texto.splitlines():
        line = clean(raw.replace("▪", ""))
        if not line or re.fullmatch(
            r"(January|February|March|April|May|June|July|August|September|October|"
            r"November|December) \d{4}",
            line,
        ):  # pie de página "May 2025"
            continue
        if line in SECCIONES:
            if (seccion := SECCIONES[line]) is None:
                break
            out[seccion], pendiente = [], ""
            continue
        if seccion is None:
            continue
        entries = out[seccion]
        m = ENTRADA_CV.match(line)
        if seccion != "formacion" and m:
            entries.append((m.group(1), m.group(2), clean(f"{pendiente} {m.group(3)}") or ""))
            pendiente = ""
        elif raw.lstrip().startswith("▪") or (seccion == "formacion" and not entries):
            entries.append((None, None, line))
        elif entries and not entries[-1][2].endswith("."):
            d, h, t = entries[-1]
            entries[-1] = (d, h, f"{t} {line}")
        else:
            pendiente = clean(f"{pendiente} {line}") or ""
    return out


class DorisSaezSpider(AcademicSpider):
    name = "sitio_doris_saez"
    expect = {
        "persona": 1,
        "afiliacion": 5,
        "formacion": 2,
        "distincion": 3,
        "actividad": 4,
        "proyecto": 20,
        "publicacion": 80,
        "tesis": 35,
        "dictacion": 3,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(BASE, self.parse, PERSONA)
        yield self.page(PUBLICATIONS, self.parse_publications, PERSONA)
        yield self.page(PROJECTS, self.parse_projects, PERSONA)
        yield self.page(STUDENTS, self.parse_students, PERSONA)
        yield self.page(TEACHING, self.parse_teaching, PERSONA)
        yield self.page(academico(PERSONA)["perfiles"]["cv"], self.parse_cv, PERSONA)

    def parse(self, response: Response) -> Iterator:
        main = response.css(MAIN)
        # "Full Professor<br>Department of Electrical Engineering<br>Sub-directorate of Indigenous People<br>..."
        head = [t for x in main.css("p.has-text-align-right::text").getall() if (t := clean(x))]
        campo = {k: v.strip() for k, _, v in (h.partition(":") for h in head if ":" in h)}
        yield self.item(
            "persona",
            response,
            nombre=(clean(response.css("#site-info a::text").get()) or "").removeprefix("Prof. "),
            cargo=head[0],
            email=campo.get("E-mail"),
            telefono=campo.get("Phones"),
            foto_url=main.css("figure img::attr(src)").get(),
        )
        univ = next((h for h in head if h.startswith("Universidad")), None)
        for org in head[1:]:
            if ":" in org or org == univ or org.startswith(("Av.", "Faculty")):
                continue
            yield self.item(
                "afiliacion",
                response,
                organizacion=org,
                rol=head[0] if org.startswith("Department") else None,
            )
        # "Collaborative work with Indigenous communities" (video) y los links laterales de ese trabajo
        for h2 in main.css("h2"):
            if INDIGENA.search(texts(h2) or ""):
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="vinculacion",
                    titulo=texts(h2),
                    url_destino=h2.xpath("following-sibling::div[1]//iframe/@src").get(),
                )
        for a in response.css(f"{SIDEBAR} a"):
            if INDIGENA.search(texts(a) or ""):
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="vinculacion",
                    titulo=texts(a),
                    url_destino=a.attrib["href"],
                )
        yield from self.related(response, region=MAIN)
        yield from self.related(response, region=SIDEBAR)

    def parse_publications(self, response: Response) -> Iterator:
        tipo = None
        for el in response.css(f"{MAIN} > p, {MAIN} li"):
            t = texts(el) or ""
            if el.root.tag == "p":
                tipo = t or tipo  # "BOOKS & BOOKS CHAPTERS", "ISI JOURNAL ARTICLES", "OTHER JOURNALS", "CONFERENCES"
                continue
            q = TITULO.search(t) or APA.search(t)
            if not q:
                continue
            resto = t[q.end() :].strip(" ,.")
            venue = re.split(r",|\.\s", resto.removeprefix("in "))[0].strip() or None
            pre = t[: q.start()]
            years = ANIO.findall(DOI.sub("", resto)) or ANIO.findall(pre)
            doi = DOI.search(t)
            yield self.item(
                "publicacion",
                response,
                titulo=q.group(1),
                autores=autores(re.sub(r"\(\d{4}\)\.?", "", pre).replace(" & ", ", ")),
                venue=venue,
                anio=years[-1] if years else None,
                tipo_publicacion=tipo,
                doi=doi.group(0).rstrip(".") if doi else None,
                url_destino=el.css("a::attr(href)").get(),
            )
        yield from self.related(response, region=MAIN)

    def parse_projects(self, response: Response) -> Iterator:
        for li in response.css(f"{MAIN} li"):
            t = texts(li) or ""
            m = PROYECTO.match(t)
            if not m:
                continue
            # "FONDEF IDeA project ID24I10010" → fuente "FONDEF IDeA project", código "ID24I10010"
            fuente, _, ultimo = m.group(3).strip(" ,.").rpartition(" ")
            codigo = ultimo if re.search(r"\d", ultimo) else None
            fuente = fuente if codigo else m.group(3).strip(" ,.")
            rol = m.group(5).rpartition(", ")[2] if m.group(5) else None
            yield self.item(
                "proyecto",
                response,
                titulo=m.group(4).strip(),
                codigo=codigo,
                fuente=fuente or None,
                rol=rol,
                anio_inicio=m.group(1),
                anio_fin=m.group(2) or m.group(1),
            )
        yield from self.related(response, region=MAIN)

    def parse_students(self, response: Response) -> Iterator:
        estado = None
        for el in response.css(f"{MAIN} > p, {MAIN} li"):
            t = texts(el) or ""
            if el.root.tag == "p":
                estado = t or estado  # "Current Students" / "Former Students"
                continue
            q = TITULO.search(t)
            if not q:
                continue
            # ", Master in Electrical Engineering, U. Chile. Graduated 2024." / "... 2025 – date."
            resto = t[q.end() :].strip(" ,.")
            years = ANIO.findall(resto)
            programa = re.split(r"\.\s*(?:Graduated|Tesis|\d{4}|[A-Z][a-z]+ \d{4})|,?\s*\d{4}\s*–", resto)[0]
            yield self.item(
                "tesis",
                response,
                titulo=q.group(1),
                estudiante=t[: q.start()].strip(" ,"),
                programa=clean(programa.strip(" ,.")) or None,
                anio=years[-1] if years else None,
                rol="guía",  # página "Students" de la profesora guía
                estado=estado,
                url_destino=el.css("a::attr(href)").get(),
            )
        yield from self.related(response, region=MAIN)

    def parse_teaching(self, response: Response) -> Iterator:
        for li in response.css(f"{MAIN} li"):
            codigo, _, nombre = (texts(li) or "").partition(" – ")  # "EL4004 – Principles of System Control"
            if nombre:
                yield self.item(
                    "dictacion",
                    response,
                    codigo_curso=codigo,
                    nombre_curso=nombre,
                    url_curso=li.css("a::attr(href)").get(),
                )
        yield from self.related(response, region=MAIN)

    def parse_cv(self, response: Response) -> Iterator:
        texto = "\n".join(p.extract_text(extraction_mode="layout") for p in PdfReader(io.BytesIO(response.body)).pages)
        s = secciones_cv(texto)
        for _, _, t in s.get("formacion", []):
            # "Doctor in Engineering Sciences, Pontificia Universidad Católica de Chile, December 2000."
            partes = [p.strip() for p in t.rstrip(".").split(",")]
            i = next((i for i, p in enumerate(partes) if "Universi" in p), len(partes))
            anio = ANIO.search(partes[-1])
            yield self.item(
                "formacion",
                response,
                grado=", ".join(partes[:i]),
                institucion=partes[i] if i < len(partes) else None,
                anio=anio.group(0) if anio else None,
            )
        for desde, hasta, t in s.get("cargo", []):
            rol, _, org = t.rstrip(".").partition(", ")
            yield self.item("afiliacion", response, rol=rol, organizacion=org or rol, desde=desde, hasta=hasta)
        for desde, hasta, t in s.get("sociedad", []):
            # "Chair of IEEE Chile Section." / "Senior Member IEEE."
            rol, sep, org = t.rstrip(".").partition(" of ")
            yield self.item(
                "afiliacion", response, rol=rol, organizacion=org if sep else rol, desde=desde, hasta=hasta or desde
            )
        for desde, hasta, t in s.get("editorial", []):
            yield self.item(
                "actividad",
                response,
                tipo_actividad="editorial",
                rol="Associate Editor" if t.startswith("Associate Editor") else None,
                titulo=t.removeprefix("Associate Editor").strip(),
                fecha=f"{desde} - {hasta}" if hasta else desde,
            )
        for desde, _, t in s.get("distincion", []):
            # "Outstanding Woman in Energy, Ministry of Energy, March 2018." → nombre, otorgante
            partes = t.rstrip(".").split(", ")
            yield self.item(
                "distincion",
                response,
                nombre=partes[0].split(". ")[0],
                otorgante=partes[1] if len(partes) > 2 and not ANIO.search(partes[1]) else None,
                anio=desde,
            )
