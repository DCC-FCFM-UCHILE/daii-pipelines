"""Sitio personal de Susana Mondschein (DII), su CV en PDF y su sitio de candidatura a decana.

- `dii.uchile.cl/~smondsch/`: HTML estático (FrontPage). Bio en prosa → formación, afiliaciones y áreas;
  publicaciones con DOI. El servidor dice UTF-8 pero los bytes son windows-1252 (lo declara el <meta>).
- `cvsusanamondschein.pdf`: CV en inglés con secciones en MAYÚSCULAS y viñetas "- ".
- `susanamondschein.cl`: SPA (Lovable + Supabase) que sin JS es un <div id="root"> vacío; se renderiza con
  Playwright. Solo se toman hechos (trayectoria, gestión, prensa); el programa y los testimonios no.
"""

import io
import re
from collections.abc import Iterator

from pypdf import PdfReader
from scrapy.http import Response
from scrapy_playwright.page import PageMethod

from daii.raw.spiders.base import AcademicSpider, clean, texts

PERSONA = "susana-mondschein"
SITIO = "https://www.dii.uchile.cl/~smondsch/"
CV = SITIO + "cvsusanamondschein.pdf"
CAMPANIA = "https://susanamondschein.cl/"

ANIO = re.compile(r"\b(?:19|20)\d{2}\b")
# "Associate Professor, University of Chile, August 2020 – present." → fechas al final
FECHAS = re.compile(r",?\s*((?:[A-Za-zé]+\.? )?\d{4}\s*[-–]+\s*(?:[A-Za-zé]+ )?(?:\d{4}|present|presente)|\d{4})\.?$")
GRADO = re.compile(r"(Industrial Engineer|master’s degree in [^,.]+?|Ph\.D\. in [^,.]+?)(?= and | from |\.)")
ROL_BIO = re.compile(r"\b(associate professor|researcher|taught|advisors|president)\b")
ORG_BIO = re.compile(r"\b(?:at|of) (?:the )?([A-Z][^,.]*?(?:\([A-Z]+\))?)(?= from |,|\.|$)")
SECCIONES_CV = (
    "ACADEMIC POSITIONS",
    "ACADEMIC DEGREES",
    "RESEARCH FIELDS",
    "TEACHING",
    "HONORS, AWARDS AND GRANTS",
    "ACADEMIC ADMINISTRATION",
    "PUBLICATIONS",
    "RESEARCH AND DEVELOPMENT PROJECTS",
    "PROFESSIONAL SERVICES",
)


def anios(text: str) -> list[int]:
    return [int(y) for y in ANIO.findall(text)]


def fechas(text: str) -> tuple[str, str | None, str | None]:
    """Separa "texto, desde – hasta" en (texto, desde, hasta)."""
    m = FECHAS.search(text)
    if not m:
        return text.strip(" ."), None, None
    desde, _, hasta = re.sub(r"\s*[-–]+\s*", "|", m.group(1), count=1).partition("|")
    return text[: m.start()].strip(" ,."), clean(desde), clean(hasta)


def cv_secciones(text: str) -> dict[str, list[str]]:
    """Entradas por sección: viñetas "- " (con sus líneas de continuación) o, si no hay viñetas, una por línea."""
    out: dict[str, list[list[str]]] = {}
    actual = None
    for line in text.splitlines():
        t = clean(line)
        if not t:
            continue
        if t in SECCIONES_CV:
            actual = t
            out[actual] = []
        elif actual:
            bloques = out[actual]
            if t.startswith("-") or not bloques or actual in SECCIONES_CV[:3] or t.endswith(":"):
                bloques.append([t.lstrip("- ")])
            else:
                bloques[-1].append(t)
    return {k: [e for b in v if (e := clean(" ".join(b))) and not e.endswith(":")] for k, v in out.items()}


class SusanaMondscheinSpider(AcademicSpider):
    name = "sitio_susana_mondschein"
    expect = {
        "persona": 1,
        "formacion": 4,
        "afiliacion": 19,
        "area": 3,
        "publicacion": 17,
        "dictacion": 6,
        "distincion": 4,
        "proyecto": 6,
        "actividad": 28,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(SITIO, self.parse, PERSONA)
        yield self.page(CV, self.parse_cv, PERSONA)
        yield self.page(
            CAMPANIA,
            self.parse_campania,
            PERSONA,
            playwright=True,
            playwright_page_methods=[PageMethod("wait_for_load_state", "networkidle")],
        )

    def parse(self, response: Response) -> Iterator:
        try:
            response.body.decode("utf-8")
        except UnicodeDecodeError:  # header UTF-8, bytes windows-1252
            response = response.replace(encoding="cp1252")
        bio = [
            t
            for p in response.xpath("//h1[contains(normalize-space(.), 'ABOUT ME')]/following::p[position() < 5]")
            if (t := texts(p))
        ]
        yield self.item(
            "persona", response, nombre=texts(response.css("h1.header")) or "Susana Mondschein", bio=" ".join(bio)
        )
        if bio:
            for m in GRADO.finditer(bio[0]):
                inst = re.search(r"from (?:the )?(.+?)(?: and |\.$|$)", bio[0][m.end() :])
                yield self.item("formacion", response, grado=m.group(1), institucion=inst.group(1) if inst else None)
        if len(bio) > 1:
            yield from self.afiliaciones_bio(response, bio[1])
        if len(bio) > 2:
            # "...specialization lies in applied stochastic models, with her main research focus being on X and Y."
            esp = re.search(r"specialization lies in (.+?),", bio[2])
            foco = re.search(r"focus being on (.+?)\.", bio[2])
            for a in ([esp.group(1)] if esp else []) + (re.split(r" and ", foco.group(1)) if foco else []):
                yield self.item("area", response, nombre=a)

        for h2 in response.css("h2[id]"):
            tipo = texts(h2)
            for p in h2.xpath("following-sibling::p[preceding-sibling::h2[1][@id=$id]]", id=h2.attrib["id"]):
                t = texts(p) or ""
                q = re.match(r"[“\"](.+?)[”\"]\s*(.*)$", t)
                if not q:
                    continue
                resto = q.group(2)
                con = re.match(r"\((?:with )?([^)]*)\)\s*,?\s*", resto)
                if con:
                    resto = resto[con.end() :]
                ys = anios(resto)
                venue = clean(re.split(r",\s*(?:\d|vol|Vol|ABSTRACTS)|\.\s*Link$", resto)[0].strip(" ,."))
                href = p.css("a::attr(href)").get()
                doi = re.search(r"10\.\d{4,}/\S+", href or "")
                yield self.item(
                    "publicacion",
                    response,
                    titulo=q.group(1).strip(" ,."),
                    autores=re.split(r",\s*(?:and\s+)?|\s+and\s+", con.group(1).strip(" ,")) if con else [],
                    venue=None if not venue or venue.isdigit() else venue,
                    anio=ys[0] if ys else None,
                    tipo_publicacion=tipo,
                    doi=doi.group(0) if doi else None,
                    url_destino=href,
                )
        yield from self.related(response)

    def afiliaciones_bio(self, response: Response, texto: str) -> Iterator:
        """Afiliaciones de la prosa de la bio, cláusula por cláusula ("... and at the Center for ... (CECAN)")."""
        rol = None
        for frase in re.split(r"(?<=\.)\s+", texto):
            frase = frase.split(", where ")[0]  # "..., where she served as the director of the ... program"
            for clausula in re.split(r",? and (?=a |at |an )", frase):
                if r := ROL_BIO.search(clausula):
                    rol = r.group(1)
                org = ORG_BIO.findall(clausula[r.end() :] if r else clausula)
                if not org or not rol:
                    continue
                rango = re.search(r"from (\d{4}) to (\d{4})", clausula)
                desde = (
                    rango.group(1) if rango else (m.group(1) if (m := re.search(r"\bin (\d{4})", clausula)) else None)
                )
                yield self.item(
                    "afiliacion",
                    response,
                    organizacion=org[-1],
                    rol=rol,
                    desde=desde,
                    hasta=rango.group(2) if rango else None,
                )

    def parse_cv(self, response: Response) -> Iterator:
        reader = PdfReader(io.BytesIO(response.body))
        s = cv_secciones("\n".join(p.extract_text() for p in reader.pages))
        for t in s.get("ACADEMIC POSITIONS", []):  # "Associate Professor, University of Chile, August 2020 – present."
            cuerpo, desde, hasta = fechas(t)
            rol, _, org = cuerpo.partition(", ")
            if not org:  # "Lecturer Yale School of Management"
                rol, _, org = cuerpo.partition(" ")
            yield self.item("afiliacion", response, rol=rol, organizacion=org, desde=desde, hasta=hasta)
        for t in s.get(
            "ACADEMIC DEGREES", []
        ):  # "Ph.D. in Operations Research, Massachusetts Institute ... (MIT), 1993."
            cuerpo, _, anio = t.rstrip(".").rpartition(", ")
            grado, _, inst = cuerpo.partition(", ")
            yield self.item("formacion", response, grado=grado, institucion=inst or None, anio=anio)
        for t in s.get("RESEARCH FIELDS", []):
            yield self.item("area", response, nombre=t.rstrip("."))
        for t in s.get("TEACHING", []):  # "Stochastic Processes, University of Chile and Adolfo Ibañez University."
            curso, _, inst = t.rstrip(".").rpartition(", ")
            yield self.item("dictacion", response, nombre_curso=curso or inst, institucion=inst if curso else None)
        for t in s.get("HONORS, AWARDS AND GRANTS", []):
            yield self.item(
                "distincion", response, nombre=re.split(r"\.\s|,\s", t, maxsplit=1)[0], anio=(anios(t) or [None])[0]
            )
        for t in s.get("ACADEMIC ADMINISTRATION", []):
            cuerpo, desde, hasta = fechas(t)
            rol, _, org = cuerpo.partition(", ")
            yield self.item("afiliacion", response, rol=rol, organizacion=org or rol, desde=desde, hasta=hasta)
        for t in s.get("RESEARCH AND DEVELOPMENT PROJECTS", []) + s.get("PROFESSIONAL SERVICES", []):
            if t.startswith("Advisor of the Council"):  # "Advisor of the Council of the National Commission ..."
                yield self.item(
                    "afiliacion",
                    response,
                    rol="Advisor of the Council",
                    organizacion=t.split(", ")[0].removeprefix("Advisor of the Council of the "),
                )
                continue
            q = re.search(r"[“\"](.+?)[”\"]", t)
            rol = re.search(r"\b(Co-researcher|Principal researcher|Director|Project director)\b", t)
            codigo = re.search(r"\b(AFB\d+|FONDAP \d+|\d{7})\b", t)
            ys = anios(re.sub(r"\b\d{7,}\b|AFB\d+", "", t[q.end() :] if q else t))
            yield self.item(
                "proyecto",
                response,
                titulo=q.group(1) if q else re.split(r"[.:(]\s", t, maxsplit=1)[0],
                codigo=codigo.group(1) if codigo else None,
                fuente=re.split(r"[:,(]", t, maxsplit=1)[0].strip() if q else None,
                rol=rol.group(1) if rol else None,
                anio_inicio=ys[0] if ys else None,
                anio_fin=ys[-1] if ys and "present" not in t else None,
            )

    def parse_campania(self, response: Response) -> Iterator:
        # Trayectoria Académica: <span class="font-mono">2023-Act</span><p>Profesora Titular, Depto. ..., FCFM</p>
        for span in response.css("section#sobre span.font-mono"):
            desde, _, hasta = (texts(span) or "").partition("-")
            t = texts(span.xpath("following-sibling::p[1]")) or ""
            if re.match(r"(PhD|Mag[ií]ster|Ingenier[ií]a|Doctor|Licenciatura)", t):
                grado, _, inst = t.partition(",")
                yield self.item(
                    "formacion",
                    response,
                    grado=grado.strip(),
                    institucion=clean(inst),
                    anio=(anios(hasta) or [None])[0],
                )
            else:
                rol, _, org = re.split(r"(, | de la )", t, maxsplit=1) if re.search(r", | de la ", t) else (t, "", t)
                yield self.item("afiliacion", response, rol=rol, organizacion=org, desde=desde, hasta=hasta or None)

        for li in response.css("section#gestion li"):
            t = texts(li) or ""
            # "Directora del Departamento de ingeniería Industrial, FCFM, Universidad de Chile, octubre 2023-presente"
            cuerpo, desde, hasta = fechas(re.split(r"\.\s", t, maxsplit=1)[0])
            if not hasta:  # logros sueltos ("Otorgamiento de la acreditación ... ABET ... en 2016")
                continue
            rol, _, org = cuerpo.partition(", ")
            yield self.item("afiliacion", response, rol=rol, organizacion=org or rol, desde=desde, hasta=hasta)

        for li in response.css("section#prensa li"):
            t = texts(li)
            if not t:
                continue
            q = re.search(r"[“\"](.+)[”\"]", t)  # greedy: hay comillas anidadas ("tiene “impacto marginal” y ...")
            fecha = re.search(r"\d{1,2} (?:de )?[A-Za-zúé]+ (?:de )?\d{3,4}", t)
            yield self.item(
                "actividad",
                response,
                tipo_actividad="prensa",
                titulo=q.group(1).strip(" .") if q else t,
                descripcion=t,
                fecha=fecha.group(0) if fecha else None,
                url_destino=clean(li.css("a::attr(href)").get()),
            )
        yield from self.related(response)
