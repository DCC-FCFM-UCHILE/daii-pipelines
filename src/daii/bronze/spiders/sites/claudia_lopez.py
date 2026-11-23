"""Sitio personal de Claudia López Moncada (WordPress.com): home, bio, publicaciones, estudiantes, docencia,
divulgación e investigación.

WordPress.com responde 429 si se piden páginas seguidas: delay alto y una conexión. `news/` es prosa libre por fecha
(redundante con bio/outreach); no tiene parser, queda como `pagina` vía `related()`.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, anio, anios, clean, plain

SITIO = "https://claudialopezmoncada.com/"
PERSONA = "claudia-lopez"
CONTENT = ".entry-content"  # excluye header/footer/menús de wordpress.com
FECHA = re.compile(r"^((?:\w+\.? )?\d{4}(?:\s*[-–]\s*(?:\d{2,4}|ongoing))?)[:.]\s*(.*)$")  # "Mar. 2024: ..."
ANIO_PAREN = re.compile(r"\((\d{4})[a-z]?(?:, \w+)?\)\.?")  # APA: "López, C. (2017). Título. Venue"
LINK_LABEL = re.compile(r"\s*\(\s*[a-z]{2,5}\s*\)")  # "(acm)", "(pdf)": etiquetas de links
INICIALES = re.compile(r"^(?:[A-ZÁÉÍÓÚÑ]\.?\s?-?)+$")
# Sección (bio/outreach) → tipo_actividad; el encabezado original queda en `descripcion`
ACTIVIDADES = {
    "Outreach appointments": "asesoria",
    "Podcasts / TV": "prensa",
    "Interviews and quotes in national press": "prensa",
    "Invited outreach presentations and panels": "divulgacion",
    "Invited academic talks": "charla",
    "Invited academic panels": "charla",
    "Guest lectures": "charla",
    "Invited event participation": "charla",
    "Written documents": "divulgacion",
    "Community outreach": "divulgacion",
    "Opportunities to inform public policy on AI": "politica_publica",
}


def secciones(response: Response) -> Iterator[tuple[str, list]]:
    """(encabezado, elementos) por cada h4/p-título seguido de una lista en el contenido WordPress."""
    for lista in response.css(f"{CONTENT} > ol, {CONTENT} > ul"):
        yield plain(lista.xpath("preceding-sibling::*[self::h4 or self::p][1]")) or "", lista.xpath("./li")


def rango_anios(texto: str) -> list[int]:
    """ "(2016-17, 22-23)" → [2016, 2017, 2022, 2023]; "(2026, Spring)" → [2026]."""
    out: list[int] = []
    for a, b in re.findall(r"(\d{4}|\d{2})(?:\s*-\s*(\d{4}|\d{2}))?", texto):
        ini = int(a) if len(a) == 4 else 2000 + int(a)
        fin = (int(b) if len(b) == 4 else ini // 100 * 100 + int(b)) if b else ini
        out += range(ini, fin + 1)
    return out


def autores(texto: str) -> list[str]:
    """APA ("López, C., Farzan, R., & Lin, Y. R.") o "C. López, P. Brusilovsky" → lista de nombres."""
    texto = re.sub(r"(?<=\w{3})[.:]\s*$", "", texto.strip(" ,"))  # punto final tras un apellido, no tras inicial
    tokens = [t for t in re.split(r",\s*|\s*&\s*", texto) if t and t != "…"]
    out: list[str] = []
    for t in tokens:
        if out and INICIALES.match(t) and "," not in out[-1]:
            out[-1] += ", " + t
        else:
            out.append(t)
    return out


def periodo(texto: str) -> tuple[str | None, str | None]:
    """ "2022-2024" → ("2022", "2024"); "Mar. 2024" → ("Mar. 2024", None)."""
    m = re.fullmatch(r"(\d{4})\s*[-–]\s*(\d{2,4}|ongoing)", texto)
    if not m:
        return texto, None
    fin = m.group(2)
    return m.group(1), m.group(1)[:2] + fin if len(fin) == 2 else fin


class ClaudiaLopezSpider(AcademicSpider):
    name = "sitio_claudia_lopez"
    custom_settings = {"DOWNLOAD_DELAY": 5, "CONCURRENT_REQUESTS_PER_DOMAIN": 1}
    expect = {
        "persona": 1,
        "afiliacion": 6,
        "formacion": 2,
        "publicacion": 35,
        "tesis": 45,
        "dictacion": 15,
        "actividad": 80,
        "area": 3,
        "proyecto": 8,
        "producto": 1,
        "distincion": 3,
    }

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(SITIO, self.parse_home, PERSONA)
            for path, cb in [
                ("bio/", self.parse_bio),
                ("publications/", self.parse_publications),
                ("students/", self.parse_students),
                ("teaching/", self.parse_teaching),
                ("outreach/", self.parse_outreach),
                ("research/", self.parse_research),
            ]:
                yield self.page(SITIO + path, cb, PERSONA)

    def parse_home(self, response: Response) -> Iterator:
        main = response.css("main")
        cargo = main.xpath(".//h1/following-sibling::p[1]")
        intro = main.xpath(".//p[contains(., 'my research')]")
        yield self.item(
            "persona",
            response,
            nombre=plain(main.css("h1")),
            cargo=plain(cargo),
            foto_url=main.css("figure img::attr(src)").get(),
            bio=plain(intro),
        )
        # "Associate Professor, <a>Department of Computer Science</a> & <a>IDIA</a>, <a>University of Chile</a>"
        rol = (cargo.xpath("text()").get() or "").strip(" ,") or None
        for a in cargo.css("a"):
            yield self.item("afiliacion", response, organizacion=plain(a), rol=rol, url_organizacion=a.attrib["href"])

        texto = plain(intro) or ""
        for frase in re.split(r"(?<=[a-z)])\.\s+", texto):
            # "From 2015 to early 2026, I was a faculty member in the Department of Informatics at UTFSM"
            desde = hasta = None
            if m := re.match(r"From (\d{4}) to ([^,]+), ", frase):
                desde, hasta = m.group(1), m.group(2)
            for parte in re.split(r",? and (?=an? )|, I am ", frase):
                m = re.search(
                    r"\ban? ((?:principal|associate) investigator|faculty member) (?:at|in) (?:the )?(.+)", parte
                )
                if m and "University of Chile" not in m.group(2):  # la U. de Chile ya viene en el cargo
                    org = re.sub(r",\s*I am.*$", "", m.group(2)).strip(" .")
                    yield self.item("afiliacion", response, organizacion=org, rol=m.group(1), desde=desde, hasta=hasta)
        # "I currently serve on the Senior Program Committee for <a>ACM CSCW 2026</a> and on the Steering Committee ..."
        for rol, evento in re.findall(
            r"on the ((?:Senior )?Program Committee|Steering Committee) for ([^,.]+?)(?:,| and |\.)", texto
        ):
            yield self.item(
                "actividad",
                response,
                tipo_actividad="comite_programa" if "Program" in rol else "comite",
                titulo=f"{rol} for {evento}",
                evento=evento,
                rol=rol,
                url_destino=intro.xpath(f".//a[normalize-space(.)='{evento}']/@href").get(),
            )
        # "I am also the deputy director of <a>dashAI</a>, a no-code, open-source machine learning platform."
        if m := re.search(r"the ([\w ]+?) of (\w+), (an? [^.]+)", texto):
            yield self.item(
                "producto",
                response,
                tipo_producto="plataforma",
                nombre=m.group(2),
                descripcion=m.group(3),
                rol=m.group(1),
                url_destino=intro.xpath(f".//a[normalize-space(.)='{m.group(2)}']/@href").get(),
            )
        yield from self.related(response, region="main")

    def parse_bio(self, response: Response) -> Iterator:
        for seccion, items in secciones(response):
            for li in items:
                m = FECHA.match(plain(li) or "")
                if not m:
                    continue
                fecha, texto = m.group(1), m.group(2).strip()
                url = li.css("a::attr(href)").get()
                if seccion.startswith("Major events"):
                    yield from self._evento_bio(response, fecha, texto, url)
                elif seccion.startswith("Fellowships"):
                    nombre, _, otorgante = texto.partition(", ")
                    yield self.item(
                        "distincion", response, nombre=nombre, otorgante=otorgante or None, anio=anio(fecha)
                    )
                else:  # política pública / servicio / participación en eventos
                    tipo = ACTIVIDADES.get(seccion)
                    if not tipo:
                        tipo = (
                            "revisor"
                            if texto.startswith("Reviewer")
                            else "comite_programa"
                            if "Program" in texto
                            else "organizacion_evento"
                            if "chair" in texto
                            else "servicio"
                        )
                    yield self.item(
                        "actividad",
                        response,
                        tipo_actividad=tipo,
                        titulo=texto,
                        descripcion=seccion,
                        fecha=fecha,
                        url_destino=url,
                    )
        yield from self.related(response, region=CONTENT)

    def _evento_bio(self, response: Response, fecha: str, texto: str, url: str | None) -> Iterator[dict]:
        """Hitos de "Major events": grados → formación; cargos con organización → afiliación."""
        if m := re.match(r"(?:Earned|Got|Obtained|Started) an? (.+?)(?:, (.+))?$", texto):
            grado, inst = m.group(1), m.group(2)
            if texto.startswith("Started"):  # "Started a Ph.D. in ..., U. of Pittsburgh": año de inicio, no de grado
                yield self.item("formacion", response, grado=grado, institucion=inst)
            else:
                yield self.item("formacion", response, grado=grado, institucion=inst, anio=(anios(fecha) or [None])[-1])
            return
        m = re.search(
            r"(?:I am|I was promoted to|I joined as|Joined, as) (?:an? )?([\w ]+?),? (?:at|of|the) "
            r"(?:the |a )?(?:new )?([^.]+)",
            texto,
        )
        if m:
            desde, hasta = periodo(fecha)
            yield self.item(
                "afiliacion", response, organizacion=m.group(2).strip(), rol=m.group(1), desde=desde, hasta=hasta
            )

    def parse_publications(self, response: Response) -> Iterator:
        for h4 in response.css(f"{CONTENT} > h4"):
            seccion = plain(h4)
            sig = h4.xpath("following-sibling::*[1]")
            for el in sig.xpath("./li") or sig:
                t = plain(el)
                if not t:
                    continue
                hrefs = el.css("a::attr(href)").getall()
                doi = next((re.split(r"doi\.org/", h)[1] for h in hrefs if "doi.org/" in h), None)
                # sin formato reconocible: la cita completa (sin URL) queda como título
                pub = {"titulo": re.split(r"\s*\(?https?://", t)[0], "anio": None, "venue": None, "autores": []}
                if "“" in t:  # C. López, P. Brusilovsky. “Título.” Venue, 2012.
                    antes, _, resto = t.partition("“")
                    titulo, _, venue = resto.partition("”")
                    ys = anios(venue)
                    if m := ANIO_PAREN.search(antes):  # López, C. (2014). “Título.” Venue
                        antes, ys = antes[: m.start()], [int(m.group(1))]
                    pub = {
                        "titulo": titulo.strip(" .,"),
                        "anio": ys[-1] if ys else None,
                        "venue": clean(LINK_LABEL.sub("", venue).strip(" .,")),
                        "autores": autores(antes),
                    }
                elif (m := ANIO_PAREN.search(t)) and re.search(
                    r"[A-Z]\.?,?\s*$", t[: m.start()]
                ):  # López, C., Farzan, R. (2017). Título. Venue, 18(1).
                    resto = t[m.end() :].strip()
                    partes = re.match(r"(.+?\.)\s+(.*)$", resto)
                    titulo, venue = (partes.group(1), partes.group(2)) if partes else (resto, "")
                    pub = {
                        "titulo": titulo.strip(" ."),
                        "anio": m.group(1),
                        "venue": clean(LINK_LABEL.sub("", re.split(r"\s*\(?https?://", venue)[0]).strip(" .(")),
                        "autores": autores(t[: m.start()]),
                    }
                yield self.item(
                    "publicacion",
                    response,
                    **pub,
                    tipo_publicacion=seccion,
                    doi=doi,
                    url_destino=hrefs[0] if hrefs else None,
                )
        yield from self.related(response, region=CONTENT)

    def parse_students(self, response: Response) -> Iterator:
        for seccion, items in secciones(response):
            for li in items:
                t = plain(li) or ""
                if "“" not in t and not li.css("em"):
                    continue  # estudiantes en curso: sin título de tesis
                antes, _, resto = t.partition("“")
                if not resto:  # título solo en <em>
                    em = plain(li.css("em")) or ""
                    antes, resto = t.split(em)[0], em
                cierre = resto.rfind("”")
                titulo = resto[:cierre] if cierre > 0 else resto.rsplit("(", 1)[0]
                ys = re.findall(r"\([^()]*?(\d{4})\)", t)
                estudiante = re.split(r"\s+[–-]\s+|,\s*", antes.strip(" ,"), maxsplit=1)[0]
                programa = clean(antes.strip(" ,").removeprefix(estudiante).strip(" ,–-"))
                yield self.item(
                    "tesis",
                    response,
                    titulo=titulo.strip(" “”\"'.,"),
                    anio=ys[-1] if ys else None,
                    estudiante=estudiante,
                    rol=seccion,
                    programa=programa,
                    url_destino=li.css("a::attr(href)").get(),
                )
        yield from self.related(response, region=CONTENT)

    def parse_teaching(self, response: Response) -> Iterator:
        # "<em>Human-centered AI</em>, DCC & IDIA, U. de Chile (2026, Spring)"
        for seccion, items in secciones(response):
            for li in items:
                t = plain(li) or ""
                nombre = plain(li.css("em")) or t.split(",")[0]
                paren = re.findall(r"\(([^()]*)\)\s*$", t)
                sem = re.search(r"(Spring|Fall|Summer|Winter)", paren[0]) if paren else None
                for y in rango_anios(paren[0]) if paren else [None]:
                    yield self.item(
                        "dictacion",
                        response,
                        nombre_curso=nombre,
                        anio=y,
                        semestre=sem.group(1) if sem else None,
                        rol=seccion or None,
                    )
        yield from self.related(response, region=CONTENT)

    def parse_outreach(self, response: Response) -> Iterator:
        for seccion, items in secciones(response):
            for li in items:
                m = FECHA.match(plain(li) or "")
                if not m:
                    continue
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad=ACTIVIDADES.get(seccion, "otro"),
                    descripcion=seccion,
                    titulo=m.group(2).strip(),
                    fecha=m.group(1),
                    url_destino=li.css("a::attr(href)").get(),
                )
        yield from self.related(response, region=CONTENT)

    def parse_research(self, response: Response) -> Iterator:
        for h4 in response.css(f"{CONTENT} > h4"):
            yield self.item("area", response, nombre=plain(h4))
        for li in response.css(f"{CONTENT} > ul > li"):
            yield self._proyecto(response, plain(li) or "")
        yield from self.related(response, region=CONTENT)

    def _proyecto(self, response: Response, t: str) -> dict:
        """Dos formatos: "Fuente. Título (2026-2030). My role: X." y "“Título” Fuente 2016, cód. US$X. PI: ..."."""
        rol = re.search(r"My role: ([^.]+)", t)
        resp = re.search(r"(?:Director|Responsible|PI|PO)\s*:\s*((?:Dr\. )?[^.(]+?)(?:\s*\(|\.\s|\.$|,?\s*Co-PI)", t)
        monto = re.search(r"US\$\d[\d,]*", t)
        codigo = re.search(r",\s*(\d[\d.]{5,}\d)\b", t)
        if "“" in t:
            _, _, resto = t.partition("“")
            cierre = resto.rfind("”")
            titulo, despues = resto[:cierre], resto[cierre + 1 :]
            fuente = re.split(r"\s*(?:\d{4}|US\$)", despues.strip(" ,."), maxsplit=1)[0].strip(" ,") or None
            años = re.search(r"\b(\d{4})(?:-(\d{2,4}))?\b", despues)
            if rol is None:  # "PI: López, C." / "Co-PI: López , C."
                for etiqueta, nombres in re.findall(
                    r"((?:Co-)?P\s?[IO])\s*:\s*(.*?)(?=(?:,\s*)?(?:Co-)?P\s?[IO]\s*:|$)", despues
                ):
                    if "López" in nombres:
                        rol = etiqueta.replace(" ", "")
                        break
            else:
                rol = rol.group(1)
        else:
            primera, _, resto = t.partition(". ")
            if resto.startswith(("Director", "Responsible")) or "Director:" in primera:
                titulo, _, fuente = primera.partition("), ")
                titulo += ")" if fuente else ""
                fuente = fuente.split(", Director")[0] or None
            else:
                fuente, titulo = primera, re.split(r"\s*\(\d{4}", resto)[0]
            años = re.search(r"\((\d{4})(?:-(\d{2,4}))?", t)
            rol = rol.group(1) if rol else None
        ini, fin = (años.group(1), años.group(2) or años.group(1)) if años else (None, None)
        if ini and fin and len(fin) == 2:  # "2019-20"
            fin = ini[:2] + fin
        return self.item(
            "proyecto",
            response,
            titulo=titulo.strip(" “”.,"),
            fuente=fuente,
            codigo=codigo.group(1) if codigo else None,
            rol=rol,
            anio_inicio=ini,
            anio_fin=fin,
            monto=monto.group(0) if monto else None,
            investigador_responsable=resp.group(1).strip(" ,") if resp and "López" not in resp.group(1) else None,
        )
