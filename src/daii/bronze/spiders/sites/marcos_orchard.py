"""Sitio personal de Marcos E. Orchard (WordPress + Divi): home, about, proyectos, premios, publicaciones,
docencia y difusión.

Se parsea el HTML y no `wp-json/wp/v2/pages`: la API devuelve los shortcodes de Divi sin renderizar
(`[et_pb_text ...]`) con comillas pasadas por wptexturize, o sea más ruido y sin la estructura de módulos
que sí trae el HTML (`.et_pb_text_inner`, `.et_pb_blurb_description`).
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, anio, anios, autores, clean, plain

SITIO = "https://www.morchard.cl/"
PERSONA = "marcos-orchard"
MAIN = "#main-content"
YEARS_END = re.compile(
    r"\((?:[^()]*?,\s*)?(\d{4})(?:\s*[-–]\s*(\d{4}))?\)\.?$"
)  # "(2025-2028)." / "(U.Ch., 2012-2015)."
QUOTED = re.compile(r"[“”\"]\s*(.+?)\s*[,.]?\s*[”“\"]")
ROLE = re.compile(
    r"(Deputy Director|Alternate Director|Director Alterno|Director|Principal Investigator|Co-PIs?|PIs?)\s*:"
)
VENUE_END = re.compile(
    r",\s*(?=(?i:vol)\.?|Volume|No\.|Issue|pp\.|Early Access|Art|\d|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s)"
)
CURSO = re.compile(r"([A-Z]{2,3} ?\d{2,4}[A-Z]?)\s*“")  # "EL5205 “Laboratorio..." / "ECE 4562 “..."
NAME = re.compile(r"(?:(?!\.\s)[^,;(])*(?:\([^)]*\))?")  # "Jorge Silva (U.Ch)" hasta la coma / punto
# Prefijo de cada ítem de "Dissemination and Transfer" → tipo_actividad (vocabulario de docs/modelo_datos.md)
ACTIVIDADES = {
    "Keynote Speaker": "keynote",
    "Plenary Speaker": "keynote",
    "Guest Editor": "editorial",
    "Program Chair": "comite_programa",
    "Conference Chair": "organizacion_evento",
}


class MarcosOrchardSpider(AcademicSpider):
    name = "sitio_marcos_orchard"
    expect = {
        "persona": 1,
        "afiliacion": 3,
        "formacion": 2,
        "area": 2,
        "proyecto": 20,
        "distincion": 7,
        "publicacion": 100,
        "dictacion": 5,
        "actividad": 5,
    }

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(SITIO, self.parse, PERSONA)
            for slug, cb in [
                ("about-me", self.parse_about),
                ("research-experience", self.parse_research),
                ("awards-distinctions", self.parse_awards),
                ("journal-publications", self.parse_publications),
                ("conference-articles", self.parse_publications),
                ("books-books-chapters", self.parse_publications),
                ("teaching", self.parse_teaching),
                ("dissemination-and-transfer", self.parse_dissemination),
            ]:
                yield self.page(f"{SITIO}{slug}/", cb, PERSONA)

    def parse(self, response: Response) -> Iterator:
        main = response.css(MAIN)
        head = [plain(p) or "" for p in main.css(".et_pb_text_0 p")]
        email = next((h.removeprefix("Email:").strip() for h in head if h.startswith("Email:")), None)
        yield self.item(
            "persona",
            response,
            nombre=head[0],
            cargo=head[1] if len(head) > 1 else None,
            email=email.replace(" [@] ", "@") if email else None,
            foto_url=main.css(".et_pb_image img::attr(src)").get(),
            bio=clean(" ".join(plain(p) or "" for p in main.css(".et_pb_text_1 p"))),
        )
        if len(head) > 2:  # "Professor" / "Department of Electrical Engineering, ..., University of Chile"
            yield self.item("afiliacion", response, organizacion=head[2], rol=head[1])
        for a in main.css(".et_pb_text_0 a"):
            rid = re.search(r"ResearcherID:\s*(\S+)", plain(a) or "")
            yield self.item(
                "perfil",
                response,
                plataforma="publons",
                url_destino=a.attrib["href"],
                identificador=rid.group(1) if rid else None,
            )

        # Bloques "rol / organización / lugar"
        for blurb in main.css(".et_pb_blurb_description"):
            ps = [plain(p) or "" for p in blurb.css("p")]
            if len(ps) < 2:
                continue
            url = blurb.css("a::attr(href)").get()
            yield self.item("afiliacion", response, organizacion=ps[1], rol=ps[0], url_organizacion=url)
            if "Editor" in ps[0]:
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="editorial",
                    titulo=ps[1],
                    rol=ps[0],
                    descripcion=", ".join(ps[2:]) or None,
                    url_destino=url,
                )
        yield from self.related(response, region=MAIN)

    def parse_about(self, response: Response) -> Iterator:
        for block in response.css(f"{MAIN} .et_pb_text_inner"):
            title = plain(block.css("p:first-child"))
            if title == "RESEARCH INTERESTS":
                for li in block.css("li"):
                    yield self.item("area", response, nombre=plain(li))
            elif title == "EDUCATION":
                # <ul><li>2003 – 2007</li></ul> <p>institución</p> <p>grado</p> [<p>grado</p>]
                egreso = inst = None
                for el in block.xpath("./*[position() > 1]"):
                    t = plain(el)
                    if el.root.tag == "ul":
                        egreso, inst = (anios(t) or [None])[-1], None
                    elif t and inst is None:
                        inst = t
                    elif t:
                        yield self.item("formacion", response, grado=t, institucion=inst, anio=egreso)
        yield from self.related(response, region=MAIN)

    def parse_research(self, response: Response) -> Iterator:
        for li in response.css(f"{MAIN} .et_pb_text_inner li"):
            t = plain(li) or ""
            years = YEARS_END.search(t)
            if not years:  # líneas de investigación (repetidas en about-me)
                continue
            q = QUOTED.search(t)
            if q:
                titulo, prefix, rest = q.group(1), t[: q.start()], t[q.end() :]
            else:  # "Conicyt REDES-170031: Prognostics and ..., PI: ..." / "CORFO: Atacama ... (AtaMoS-TeC). Work..."
                prefix, _, rest = t.partition(":")
                titulo, *tail = re.split(r"\.\s|,\s", rest.strip(), maxsplit=1)
                rest = tail[0] if tail else ""
            prefix = prefix.strip(" :,;")
            # "FONDECYT Project 1250036" → fuente "FONDECYT Project", código "1250036"
            m = re.match(r"^(.*?)\s+(\S*\d.*)$", prefix)
            fuente, codigo = (m.group(1), m.group(2)) if m else (prefix or None, None)
            rol = responsable = None
            roles = list(ROLE.finditer(rest))
            for i, r in enumerate(roles):
                seg = rest[r.end() : roles[i + 1].start() if i + 1 < len(roles) else len(rest)]
                if responsable is None and r.group(1) in ("PI", "Director"):
                    responsable = clean(NAME.findall(seg.strip())[0])
                if rol is None and "Orchard" in seg:
                    rol = r.group(1)
            if rol is None and re.search(r"\bResearcher\b", rest):
                rol = "Researcher"
            yield self.item(
                "proyecto",
                response,
                titulo=titulo or t,
                codigo=codigo,
                fuente=fuente,
                rol=rol,
                investigador_responsable=responsable,
                anio_inicio=years.group(1),
                anio_fin=years.group(2) or years.group(1),
            )
        yield from self.related(response, region=MAIN)

    def parse_awards(self, response: Response) -> Iterator:
        for li in response.css(f"{MAIN} .et_pb_text_inner li"):
            body = (plain(li) or "").split(" DOI:")[0].strip()
            years = re.search(r"\(([^()]*\d{4}[^()]*)\)$", body)
            if years:
                body = body[: years.start()].strip()
            # "“Best Paper Award”: Annual Conference ..." / "Fulbright Grant. Graduate Studies. Fulbright-Chile, ..."
            nombre, *otorgante = re.split(r"(?:[.:]”|”[.:]|[.:])\s+", body, maxsplit=1)
            yield self.item(
                "distincion",
                response,
                nombre=nombre.strip("“”") if "”" not in nombre[1:-1] else nombre,
                otorgante=clean(otorgante[0].strip(" .")) if otorgante else None,
                anio=anio(years.group(1)) if years else None,
            )
        yield from self.related(response, region=MAIN)

    def parse_publications(self, response: Response) -> Iterator:
        tipo = (plain(response.css(f"{MAIN} .et_pb_text_inner").css("p:first-child")[0]) or "").rstrip(":")
        for el in response.css(f"{MAIN} .et_pb_text_inner p, {MAIN} .et_pb_text_inner li"):
            if el.root.tag == "p" and el.xpath("ancestor::li"):
                continue
            t = plain(el) or ""
            q = QUOTED.search(t)
            if not q:
                continue
            rest = t[q.end() :].strip(" ,.")
            pre_doi = re.split(r"\bDOI\b", rest)[0].strip(" ,.;:")
            chapter = re.search(r"Chapter Title:\s*[“\"](.+?)[”\"]", rest)
            if chapter:
                titulo, venue = chapter.group(1).strip(" ,."), q.group(1)
            else:
                titulo = q.group(1)
                venue = VENUE_END.split(pre_doi)[0].removeprefix("Publisher:").strip(" ,.") or None
            years = anios(pre_doi)
            doi = el.css("a[href*='doi.org']::attr(href)").get()
            yield self.item(
                "publicacion",
                response,
                titulo=titulo,
                autores=autores(t[: q.start()]),
                venue=venue,
                anio=years[-1] if years else None,
                tipo_publicacion=tipo,
                doi=re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip()).split("#")[0] if doi else None,
                url_destino=el.css("a::attr(href)").get(),
                estado="Early Access" if "Early Access" in rest else None,
            )
        yield from self.related(response, region=MAIN)

    def parse_teaching(self, response: Response) -> Iterator:
        for block in response.css(f"{MAIN} .et_pb_text_inner"):
            t = plain(block) or ""
            codes = list(CURSO.finditer(t))
            for i, m in enumerate(codes):
                seg = t[m.end() : codes[i + 1].start() if i + 1 < len(codes) else len(t)]
                yield self.item(
                    "dictacion",
                    response,
                    codigo_curso=m.group(1),
                    nombre_curso=re.split(r"”", seg)[0].strip(),  # "Laboratorio de Control Avanzado” (Advanced ...)"
                )
        yield from self.related(response, region=MAIN)

    def parse_dissemination(self, response: Response) -> Iterator:
        for li in response.css(f"{MAIN} .et_pb_text_inner li"):
            t = (plain(li) or "").rstrip(".")
            prefix, _, rest = t.partition(", ")
            if prefix in ACTIVIDADES:
                yield self.item("actividad", response, tipo_actividad=ACTIVIDADES[prefix], rol=prefix, titulo=rest)
                continue
            # 'Orchard. M., “Charla”. Evento, lugar, fecha.' / 'Orchard, M., “Evento” (...). Keynote Speaker “Charla”.'
            keynote = re.search(r"Keynote Speaker\s*“(.+?)”", t)
            q = QUOTED.search(t)
            yield self.item(
                "actividad",
                response,
                tipo_actividad="keynote" if keynote else "charla",
                rol="Keynote Speaker" if keynote else None,
                titulo=keynote.group(1).strip(" .") if keynote else (q.group(1) if q else t),
                evento=(q.group(1) if keynote else clean(t[q.end() :].strip(" .,"))) if q else None,
                descripcion=t,
            )
        yield from self.related(response, region=MAIN)
