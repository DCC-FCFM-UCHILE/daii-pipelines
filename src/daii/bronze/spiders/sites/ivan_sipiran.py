"""Sitio personal de Iván Sipirán (HTML estático, inglés): home, research, publications, links y su CV en PDF.

- `index` (home): cargos actuales y previos (PUCP, postdoc en Konstanz), formación, áreas y notas de prensa (News).
- `research.html`: proyectos (los que dicen "funded by ... under contract ..." o "Project") y software
  propio (Harris 3D, que tiene "Project Page" con el código fuente).
- `publications.html`: publicaciones agrupadas por año (`<h1>2025</h1>`) más "Preprints".
- `links.html` ("Software and Links") lista datasets y herramientas de terceros (Princeton Shape Benchmark, MeshLab...):
  no son productos suyos, así que solo se registran como `link`.
- `fullcv.pdf`: experiencia, formación, proyectos (con montos), premios, cursos (PUCP, U. Nacional de Trujillo, DCC),
  tesis guiadas y servicio (comités de programa, revisor). Sus publicaciones son las mismas del sitio (más antiguas) y
  la sección "Personal" no se lee. Su ficha DCC la cubre `ucurriculum`.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import ANIO, AcademicSpider, autores, clean, pdf_texto, texts
from daii.config import academico

PERSONA = "ivan-sipiran"
BASE = "https://www.ivan-sipiran.com/"
RESEARCH = BASE + "research.html"
PUBLICATIONS = BASE + "publications.html"
LINKS = BASE + "links.html"
MAIN = "#page"

# home: "I am Assistant Professor in the Department ..." / "I held a Post-doc position at the University of Konstanz"
CARGO = re.compile(r"\bI (?:am|was|held|spent [\w ]+? as) (?:an? )?(.+?)(?: position)? (?:in|at) (?:the )?(.+)$")
GRADO = re.compile(
    r"\bI (?:got|received) (?:an? |the )?(.+?) (?:from|in(?!.* from )) (?:the )?(.+?)"
    r"(?: under the advice of .+?)?(?: in (\d{4}))?$"
)
FONDO = re.compile(r"funded by (.+?) under contract (\S+?)\.?$")
# CV
SECCIONES = {
    "Personal": None,
    "Experience": "experiencia",
    "Education": "formacion",
    "Research Projects": "proyecto",
    "Grants / Awards": "distincion",
    "Research Stays": None,
    "Research Interests": None,
    "Teaching Experience": "dictacion",
    "Publications": None,
    "Supervision of Students": "tesis",
    "Scientiﬁc Community Service": "servicio",
}
FECHA = re.compile(r"((?:[A-Z][a-z]{2,8}\.? )?\d{4}\s*-\s*(?:[A-Z][a-z]{2,8}\.?\s*)?(?:\d{4}|Current))")
PROYECTO_CV = re.compile(r"^(.+?) in the (.*?)Project\s*(.*?)(?::\s*(.+?))?\s*\(([^()]*\d{4}[^()]*)\)\.?(.*)$")
SEMESTRE = re.compile(r"^(Spring|Fall|Summer|Winter) (\d{4}) - (.+)$")  # "Spring 2020 - DCC, UChile"


def secciones_cv(texto: str) -> dict[str, list[str]]:
    """Líneas por sección del CV; une palabras cortadas ("Detec-\\ntion") y bota el pie de página."""
    texto = re.sub(r"-\n(?=[a-z])", "", texto)
    out: dict[str, list[str]] = {}
    seccion = None
    for line in texto.splitlines():
        line = clean(line) or ""
        if not line or line.startswith("B isipiran@") or re.fullmatch(r"\d+/\d+", line):
            continue
        if line in SECCIONES:
            seccion = SECCIONES[line]
            if seccion:
                out[seccion] = []
        elif seccion:
            out[seccion].append(line)
    return out


def bullets(lines: list[str]) -> list[str]:
    """Une las líneas de cada viñeta ("{ ..."); las líneas sin viñeta quedan solas (rótulos)."""
    out: list[str] = []
    abierta = False
    for line in lines:
        if line.startswith("{"):
            out.append(line.lstrip("{ "))
            abierta = True
        elif (
            abierta and not line.endswith(":") and not SEMESTRE.match(line) and line not in ("Master", "Undergraduate")
        ):
            out[-1] += " " + line
        else:
            out.append(line)
            abierta = False
    return out


class IvanSipiranSpider(AcademicSpider):
    name = "sitio_ivan_sipiran"
    expect = {
        "persona": 1,
        "afiliacion": 4,
        "formacion": 3,
        "area": 2,
        "actividad": 7,
        "proyecto": 4,
        "producto": 1,
        "publicacion": 30,
        "distincion": 5,
        "dictacion": 20,
        "tesis": 2,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(BASE, self.parse, PERSONA)
        yield self.page(RESEARCH, self.parse_research, PERSONA)
        yield self.page(PUBLICATIONS, self.parse_publications, PERSONA)
        yield self.page(LINKS, self.parse_links, PERSONA)
        # sección "Personal" del CV (nombre completo, dirección): no se guarda el PDF en pages/
        yield self.page(academico(PERSONA)["perfiles"]["cv"], self.parse_cv, PERSONA, guardar=False)

    def parse(self, response: Response) -> Iterator:
        intro, news = response.css(f"{MAIN} #latest-post")[:2]
        yield self.item(
            "persona",
            response,
            nombre=clean(response.css("#logo h1 ::text").get()),
            foto_url=intro.css("img::attr(src)").get(),
        )
        for p in intro.css("p"):
            # "... University of Chile . I was ..." → frases; "Dr. Benjamin Bustos" no corta
            t = re.sub(r"\s+([.,])", r"\1", texts(p) or "")
            for frase in re.split(r"(?<!Dr)\.\s+", t.rstrip(".")):
                frase = re.sub(r"^(?:Also|Previously),\s*", "", frase)
                if g := GRADO.search(frase):
                    yield self.item("formacion", response, grado=g.group(1), institucion=g.group(2), anio=g.group(3))
                elif c := CARGO.search(frase):
                    org = re.sub(r" in [A-Z][\w]+, [\wú]+$", "", c.group(2))  # "... - PUCP in Lima, Perú"
                    yield self.item("afiliacion", response, rol=c.group(1), organizacion=org)
        for li in intro.css("li"):
            yield self.item("area", response, nombre=texts(li))
        for li in news.css("li"):  # notas de prensa sobre su investigación (arqueología 3D)
            yield self.item(
                "actividad",
                response,
                tipo_actividad="prensa",
                titulo=re.sub(r"\s+([.,])", r"\1", texts(li) or ""),
                url_destino=li.css("a::attr(href)").get(),
            )
        yield from self.related(response, region=MAIN)

    def parse_research(self, response: Response) -> Iterator:
        for post in response.css(f"{MAIN} .post"):
            titulo = texts(post.css("h2"))
            if not titulo:
                continue
            cuerpo = texts(post.css(".entry")) or ""
            fondo = next((m for f in re.split(r"(?<=\.)\s+", cuerpo) if (m := FONDO.search(f))), None)
            if fondo or "Project" in titulo:
                codigo = fondo.group(2) if fondo else None
                yield self.item(
                    "proyecto",
                    response,
                    titulo=titulo,
                    fuente=fondo.group(1) if fondo else None,
                    codigo=codigo,
                    anio_inicio=a.group(0) if codigo and (a := ANIO.search(codigo)) else None,
                )
            if page := post.css("p.byline a::attr(href)").get():  # "Project Page" con el código fuente
                yield self.item(
                    "producto",
                    response,
                    tipo_producto="software",
                    nombre=titulo,
                    url_destino=page,
                    descripcion=clean(cuerpo.split(". ")[0]),
                )
        yield from self.related(response, region=MAIN)

    def parse_publications(self, response: Response) -> Iterator:
        for h1 in response.css(f"{MAIN} h1"):
            grupo = texts(h1)
            if not grupo:
                continue
            for li in h1.xpath("following-sibling::ul[1]/li"):
                titulo = texts(li.css("strong"))
                if not titulo:
                    continue
                t = texts(li) or ""
                pre, _, resto = t.partition(titulo)
                resto = resto.strip(" .")
                venue = re.split(r"\.\s|\[|\. ?(?=Vol)|,\s*(?:Vol|\d)", resto)[0].strip(" .") or None
                arxiv = re.search(r"Arxiv:\s*(\S+?)\.?(?:\s|$)", resto, re.IGNORECASE)
                yield self.item(
                    "publicacion",
                    response,
                    titulo=titulo.rstrip("."),
                    autores=autores(re.sub(r"(\w{2,})\.$", r"\1", pre.strip(" :"))),  # "Bustos." sí, "G." no
                    anio=grupo if grupo.isdigit() else None,
                    tipo_publicacion="preprint" if grupo == "Preprints" else None,
                    venue=None if arxiv else venue,
                    estado="To appear" if re.search(r"to appear", t, re.IGNORECASE) else None,
                    url_destino=li.css("a::attr(href)").get(),
                    ids={"arxiv": arxiv.group(1)} if arxiv else {},
                )
        yield from self.related(response, region=MAIN)

    def parse_links(self, response: Response) -> Iterator:
        # datasets y software de terceros: solo links
        yield from self.related(response, region=MAIN)

    def parse_cv(self, response: Response) -> Iterator:
        s = secciones_cv(pdf_texto(response))

        partes = FECHA.split(" ".join(s.get("experiencia", [])))
        for fecha, texto in zip(partes[1::2], partes[2::2], strict=True):
            # "Post-doctoral researcher, Department of Computing ... - University of Konstanz, Konstanz - Germany."
            rol, _, org = texto.strip(" .").partition(", ")
            desde, _, hasta = fecha.partition("-")
            yield self.item("afiliacion", response, rol=rol, organizacion=org, desde=desde.strip(), hasta=hasta.strip())

        for line in s.get("formacion", []):  # "2014 Ph.D., Department of Computer Science - University of Chile, ..."
            m = re.match(r"^(\d{4})(?:[–-](\d{4}))? (.+?), (.+?)\.?$", line)
            if m:
                yield self.item(
                    "formacion", response, anio=m.group(2) or m.group(1), grado=m.group(3), institucion=m.group(4)
                )

        for b in bullets(s.get("proyecto", [])):
            m = PROYECTO_CV.match(b)
            if not m:
                continue
            rol, pre, ref, titulo, fechas, resto = (x.strip(" .") if x else x for x in m.groups())
            fuente_ref, _, codigo = (ref or "").rpartition(" ")
            monto = re.search(r"Grant:\s*([^)]+)\)", resto or "")
            years = ANIO.findall(fechas)
            yield self.item(
                "proyecto",
                response,
                titulo=titulo or ref,
                codigo=codigo if titulo and re.search(r"\d", codigo) else None,
                fuente=fuente_ref or pre or clean(re.split(r"\(Grant", resto or "")[0].strip(" .")) or None,
                rol=rol,
                anio_inicio=years[0] if years else None,
                anio_fin=years[-1] if years else None,
                monto=monto.group(1).strip() if monto else None,
            )

        for b in bullets(s.get("distincion", [])):
            # "Best Paper Award - Big Data Visual Analytics (2015)." / "Outstanding ... student. Department ..., 2013."
            anio = ANIO.search(b)
            base = re.sub(r"\.?\s*\(?\d{4}(?:-\d{4})?\)?\.?$", "", b).strip()
            nombre = re.split(r" - |\. ", base, maxsplit=1)[0]
            resto = base[len(nombre) :].lstrip(" -.")
            yield self.item(
                "distincion", response, nombre=nombre, otorgante=resto or None, anio=anio.group(0) if anio else None
            )

        semestre = anio = institucion = None
        for line in s.get("dictacion", []):
            if m := SEMESTRE.match(line):
                semestre, anio, institucion = m.groups()
            elif line.startswith("{"):
                curso = line.lstrip("{ ")
                rol, sep, nombre = curso.partition(" - ") if curso.startswith("Adjoint") else (None, "", curso)
                yield self.item(
                    "dictacion",
                    response,
                    nombre_curso=nombre,
                    rol=rol,
                    semestre=semestre,
                    anio=anio,
                    institucion=institucion,
                )

        nivel = None
        for b in bullets(s.get("tesis", [])):
            if b in ("Master", "Undergraduate"):
                nivel = b
            elif m := re.match(r"^(.+?): (.+?)\.?\s*(\d{4})\.$", b):  # "Miguel Retamozo: Automatic ... 2019."
                yield self.item(
                    "tesis",
                    response,
                    estudiante=m.group(1),
                    titulo=m.group(2).rstrip("."),
                    anio=m.group(3),
                    nivel=nivel,
                    rol="guía",  # sección "Supervision of Students"
                )

        tipo = None
        for b in bullets(s.get("servicio", [])):
            if b.endswith(":"):
                tipo = {"Program Committee:": "comite_programa", "Peer-reviewer for journals:": "revisor"}.get(b)
                rol = b.rstrip(":")
            elif tipo:
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad=tipo,
                    rol=rol,
                    titulo=b.rstrip("."),
                    fecha=a.group(0) if (a := ANIO.search(b)) else None,
                )
