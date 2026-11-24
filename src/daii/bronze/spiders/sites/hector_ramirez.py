"""Sitio personal de Héctor Ramírez (Google Sites, inglés): home, servicio académico, proyectos, publicaciones y
estudiantes.

Google Sites entrega el texto en el HTML del servidor (no hace falta Playwright). El contenido está en `<section>`;
cada párrafo es un `<p>` cuyo texto viene partido en `<span>` (a veces a mitad de palabra: "b</span>ioprocesses"),
por eso se une sin espacios. Su ficha CMM la cubre el spider `cmm`.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import ANIO, AcademicSpider, anio, clean, plain

PERSONA = "hector-ramirez"
BASE = "https://sites.google.com/site/hectorramirezhomepage/"
HOME = BASE + "home"
SERVICE = BASE + "academic-service"
PROJECTS = BASE + "projects"
PUBLICATIONS = BASE + "publications"
STUDENTS = BASE + "student-s-formation"
REGION = "section"

DOI = re.compile(r"\b10\.\d{4,9}/[^\s;,]+")
QUOTED = re.compile(r"[“\"](.+?)[”\"]")
# "2016-2019: FONDECYT 1160204: ..." / "2014- 2016: ..." / "2022: ..."
PERIODO = re.compile(r"^(\d{4})(?:\s*-\s*(\d{4}))?:?\s*(.*)$")
FUENTE_CODIGO = re.compile(r"^([A-Za-zÀ-ÿ -]+?)\s+([A-Z-]*\d[\w-]*):\s*(.*)$")  # "FONDECYT 1160204: ..."
ROL_PROYECTO = re.compile(
    r"\(([^()]*(?:respons[ai]ble|researcher|director|coordinator|investigator|IP)[^()]*)\)", re.IGNORECASE
)
LED_BY = re.compile(r"led (?:in Chile )?by ([^(;,]+?)\s*(?:\(|,|;|\.$|$)")
PROGRAMA = re.compile(r"(?:Program|Programa|Monograph)\s*\w*\s*$")
MINUSCULAS = {"and", "de", "da", "del", "van", "von", "le", "II"}


def lineas(response: Response) -> list[str]:
    """Párrafos y títulos del contenido en orden (los <li> envuelven un <p>, así que basta con los <p>)."""
    return [t for el in response.css(f"{REGION} p, {REGION} h1, {REGION} h2, {REGION} h3") if (t := plain(el))]


def es_autor(chunk: str) -> bool:
    """Trozo de la lista de autores ("J.", "Báez,", "and H. Ramírez C."): pocas palabras, todas capitalizadas."""
    words = chunk.strip(" .,;").split()
    return 0 < len(words) <= 4 and all(w[0].isupper() or w in MINUSCULAS for w in words)


def separar_cita(t: str) -> tuple[list[str], str, str]:
    """ "A. B, C. D. Título. Resto" → (autores, título, resto). Funciona con "Autor, Título." y "Autor. Título.\""""
    chunks = re.split(r"(?<=[.,;])\s+", t)
    i = 0
    while i < len(chunks) - 1 and es_autor(chunks[i]):
        i += 1
    autores = [a for a in re.split(r"\s*(?:[,;]|\band\b)\s*", " ".join(chunks[:i]).strip(" .,;")) if a]
    titulo, _, resto = " ".join(chunks[i:]).partition(". ")
    return autores, titulo.strip(" ."), resto.strip()


class HectorRamirezSpider(AcademicSpider):
    name = "sitio_hector_ramirez"
    expect = {
        "persona": 1,
        "afiliacion": 1,
        "area": 3,
        "dictacion": 5,
        "actividad": 15,
        "proyecto": 20,
        "publicacion": 30,
        "tesis": 10,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(HOME, self.parse, PERSONA)
        yield self.page(SERVICE, self.parse_service, PERSONA)
        yield self.page(PROJECTS, self.parse_projects, PERSONA)
        yield self.page(PUBLICATIONS, self.parse_publications, PERSONA)
        yield self.page(STUDENTS, self.parse_students, PERSONA)

    def parse(self, response: Response) -> Iterator:
        ls = lineas(response)
        campo = {k: v.strip() for k, _, v in (x.partition(":") for x in ls if ":" in x)}
        yield self.item(
            "persona",
            response,
            nombre=ls[0],
            cargo=ls[1],
            email=campo["E-mail"].replace("(a)", "@") if "E-mail" in campo else None,
            telefono=campo.get("Phone"),
            oficina=campo.get("Address"),  # dirección de la oficina (Beauchef), no personal
            foto_url=response.css(f"{REGION} img::attr(src)").get(),
        )
        # "Full Professor" / "Mathematical Engineering Department, ..." / "Director of" / "Center for ... (CMM), ..."
        contacto = ls.index("Contact information:") if "Contact information:" in ls else 5
        for rol, org in zip(ls[1:contacto:2], ls[2:contacto:2], strict=False):
            yield self.item("afiliacion", response, organizacion=org, rol=rol.removesuffix(" of"))

        seccion = None
        for t in ls:
            if t.endswith(":") and len(t) < 30:
                seccion = t
            elif seccion == "Research Interests:":
                # "Continuous Optimization: Conic programming (SDP, SOCP), stability analysis, ..."
                for a in re.split(r",\s*(?![^()]*\))", t.partition(":")[2].rstrip(".")):
                    if clean(a):
                        yield self.item("area", response, nombre=clean(a))
            elif seccion == "Teaching:" and t.startswith("This year"):
                for nombre, codigo in re.findall(r"([A-Z][\w &]+?) \(([A-Z]{2}\d{4})\)", t):
                    yield self.item(
                        "dictacion",
                        response,
                        nombre_curso=nombre.removeprefix("and ").strip(),
                        codigo_curso=codigo,
                        anio=anio(t),
                    )
            elif seccion == "Teaching:" and t.startswith("Former lectures:"):
                cursos = t.removeprefix("Former lectures:").removesuffix("among others.")
                for c in re.split(r",\s*(?![^()]*\))", cursos):
                    if clean(c):
                        yield self.item("dictacion", response, nombre_curso=clean(c))
        yield from self.related(response, region=REGION)

    def parse_service(self, response: Response) -> Iterator:
        seccion = None
        for t in lineas(response)[1:]:
            years = re.search(r"\s*\((\d{4}\s*-\s*(?:\d{4}|now))\)\.?$", t)
            sin_anios = t[: years.start()] if years else t
            fecha = years.group(1) if years else None
            if t.startswith("I have been part"):
                continue
            if t.endswith(":"):
                seccion = t.rstrip(":")
            elif "Evaluator" in t:  # "Member of Mathematics Evaluator Group of FONDECYT program from ANID-Chile (...)"
                yield self.item("actividad", response, tipo_actividad="revisor", titulo=sin_anios, fecha=fecha)
            elif seccion is None and " Editor of " in t:  # "Chief Editor of Continuous Optimization Area of ORL (...)"
                rol, _, revista = sin_anios.rpartition(" of ")
                yield self.item("actividad", response, tipo_actividad="editorial", rol=rol, titulo=revista, fecha=fecha)
            elif seccion == "Associate Editor":
                yield self.item(
                    "actividad", response, tipo_actividad="editorial", rol=seccion, titulo=sin_anios, fecha=fecha
                )
            elif t.startswith("("):  # "(July 8-11, 2025) 10th French-Chilean Journeys on Optimization. Rouen, France."
                cuando, _, rest = t[1:].partition(")")
                evento, _, desc = rest.strip().partition(". ")
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="organizacion_evento",
                    titulo=evento.strip(" ."),
                    fecha=cuando.strip(),
                    descripcion=clean(desc.rstrip(".")),
                )
        yield from self.related(response, region=REGION)

    def parse_projects(self, response: Response) -> Iterator:
        for t in lineas(response)[1:]:
            m = PERIODO.match(t)
            if not m:
                continue
            rest = m.group(3).strip()
            fc = FUENTE_CODIGO.match(rest)
            fuente, codigo, cuerpo = (fc.group(1), fc.group(2), fc.group(3)) if fc else (None, None, rest)
            # el primer texto entre comillas que no sea el nombre de un programa ('Programa INRIA “Equipe Associé”')
            q = next((q for q in QUOTED.finditer(cuerpo) if not PROGRAMA.search(cuerpo[: q.start()])), None)
            if q:
                titulo = q.group(1)
            else:  # "Qualification Constraints ... algorithms (responsible)." → hasta el rol o "; led by"
                titulo = re.split(
                    r"\s*\((?=[^()]*(?:respons|researcher|director|coordinator|investigator|IP\b))|[;,]\s*led\b", cuerpo
                )[0]
            rol = ROL_PROYECTO.search(cuerpo)
            led = LED_BY.search(cuerpo)
            yield self.item(
                "proyecto",
                response,
                titulo=titulo.strip(" ."),
                fuente=fuente,
                codigo=codigo,
                rol=rol.group(1).strip() if rol else None,
                investigador_responsable=led.group(1).strip() if led else None,
                anio_inicio=m.group(1),
                anio_fin=m.group(2) or m.group(1),
            )
        yield from self.related(response, region=REGION)

    def parse_publications(self, response: Response) -> Iterator:
        tipo = None
        for t in lineas(response)[1:]:
            num = re.match(r"^(\d+)\.\s+(.*)$", t)
            if not num and not QUOTED.search(t):
                tipo = t  # "Journal articles", "Conference proceedings (peer reviewed)", "Books"...
                continue
            if num:
                autores, titulo, resto = separar_cita(num.group(2))
            else:  # libros: 'H. Ramírez and E. Moreno. “Grafos: Fundamentos and Algoritmos” (in Spanish). JC ...'
                q = QUOTED.search(t)
                assert q
                autores = [a for a in re.split(r"\s*(?:,|\band\b)\s*", t[: q.start()].strip(" .")) if a]
                autores = autores if all(es_autor(a) for a in autores) else []
                titulo, resto = q.group(1), t[q.end() :].strip(" .")
            estado = re.match(r"^(Submitted|Accepted)\b(?: in)?\s*", resto)
            venue = resto[estado.end() :] if estado else resto
            venue = re.split(r"(?i),|\(|\. (?=DOI|http|vol)|\bDOI\b|https?://|arxiv", venue)[0].strip(" .") or None
            pre = re.split(r"\bDOI\b|https?://|arxiv", resto, flags=re.IGNORECASE)[0]
            years = ANIO.findall(pre)
            doi = DOI.search(t)
            url = re.search(r"https?://\S+", t)
            yield self.item(
                "publicacion",
                response,
                titulo=titulo,
                autores=autores,
                venue=venue,
                anio=years[-1] if years else None,
                tipo_publicacion=tipo,
                estado=estado.group(1) if estado else None,
                doi=doi.group(0).rstrip(".") if doi else None,
                url_destino=url.group(0).rstrip(".)") if url else None,
            )
        yield from self.related(response, region=REGION)

    def parse_students(self, response: Response) -> Iterator:
        nivel = None
        for t in lineas(response)[1:]:
            if t.endswith(":"):
                nivel = t.rstrip(":")
                continue
            if nivel == "Internship":  # estadías de investigación, no tesis
                continue
            # "2024-…: Lucas Motta. Ph.D. Mathematics, ... (UCH). “Title”. Co-advisored with ..."
            # "2025-… : Tiare Letelier. Mathematical Engineering & ..., Universidad de Chile: “To be confirmed”"
            m = re.match(r"^(\d{4})(-\s*…)?\s*:\s*(.*)$", t)
            if not m:
                continue
            rest = m.group(3)
            q = QUOTED.search(rest)
            estudiante, _, programa = rest[: q.start() if q else len(rest)].partition(". ")
            yield self.item(
                "tesis",
                response,
                titulo=q.group(1).strip(' ."“”') if q else None,
                estudiante=estudiante.strip(),
                programa=clean(re.sub(r"\(jointly advisored with [^)]*\)", "", programa).strip(" .:")) or None,
                anio=m.group(1),
                nivel=nivel,
                rol="co-guía" if re.search(r"Co-advis|jointly", rest, re.IGNORECASE) else "guía",
                estado="en curso" if m.group(2) else None,
            )
        yield from self.related(response, region=REGION)
