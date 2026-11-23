"""Sitio personal de Jorge F. Silva (Hugo Academic) y su CV en PDF (LaTeX, dos columnas: sección | contenido)."""

import io
import re
import unicodedata
from collections.abc import Iterator
from urllib.parse import urlparse

from pypdf import PdfReader
from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, texts

PERSONA = "jorge-silva"
HOME = "https://jorgesil77.github.io/"
PUBLICACIONES = HOME + "publication/"
CV = HOME + "files/cv.pdf"

PLATAFORMAS = {"scholar.google": "scholar", "researchgate": "researchgate", "linkedin": "linkedin", "github": "github"}

# Columna izquierda del CV: nombre de sección (algunos en dos líneas: "Professional / Experience").
SECCION = re.compile(
    r"^(Education|Professional|Experience|Activities|Distinctions|Research Projects"
    r"|Publications|Patents|Teaching|Talks)\b"
)
NUMERO = re.compile(r"^\s*\d{1,2}\.\s+(?=\S)", re.M)
ANIO = re.compile(r"\b(?:19|20)\d{2}\b")
# Fin de la primera oración (evita cortar "E. Orchard", "Dept. of").
FRASE = re.compile(r"(?<=[a-z0-9)])\.\s+(?=[A-Z“])")
CODIGO = re.compile(r"\b(\d{7}|\d{2}IDL\d-\d{5}|ACT\d+)\b")
FUENTE = re.compile(r"Fondecyt Regular Grant|Conicyt PIA|CORFO|Proyecto Basal \w+")
FIN_TITULO = re.compile(r",\s*(?:Fondecyt|CORFO|Proyecto Basal|Programa de|\d{2}IDL)")
ROL_PROYECTO = re.compile(
    r"Principal [Ii]nvestigator(?: \(PI\))?|Co-investigator(?: \(Co-PI\))?"
    r"|Associate (?:investigator|Researcher)|Co-director"
)
RESPONSABLE = re.compile(r"(?:\bPI|\bPi\.|Director:)\s+((?:[A-Z]\.\s|[A-Z][\w-]+\s?)+)")
FIN_VENUE = re.compile(
    r",\s*(?=(?:vol|Vol|pp|no|issue|accepted)\b|\d|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b)"
)


def unir(lines: list[str]) -> str:
    """Une líneas del PDF: deshace el guionado de LaTeX ("De-\\npartment") y normaliza ligaduras (ﬁ → fi)."""
    t = unicodedata.normalize("NFKC", "\n".join(line.strip() for line in lines))
    t = re.sub(r"(\w)-\n+([a-z])", r"\1\2", t)  # shortcut: también une guiones reales ("Multiple-imputation")
    return clean(re.sub(r"-\n+(?=\S)", "-", t)) or ""


def anios(text: str) -> list[int]:
    return [int(y) for y in ANIO.findall(text)]


def primera_frase(text: str) -> str:
    return FRASE.split(text, maxsplit=1)[0].rstrip(".")


def secciones(text: str) -> dict[str, list[str]]:
    """Agrupa las líneas (modo layout) por sección; el rótulo se reemplaza por espacios para conservar columnas."""
    text = re.sub(r"\n\s*1http\S*\n\s*\S+\n", "\n", text)  # nota al pie de "Distinctions" (cae en Research Projects)
    out: dict[str, list[str]] = {}
    actual = None
    for line in text.splitlines():
        if m := SECCION.match(line):
            nombre = m.group(1)
            if nombre == "Professional":  # 1ª vez "Experience", 2ª "Activities"
                nombre = "Activities" if "Experience" in out else "Experience"
            actual = nombre
            line = " " * m.end() + line[m.end() :]
        if actual:
            out.setdefault(actual, []).append(line)
    return out


def bloques(lines: list[str]) -> Iterator[tuple[str, str, list[str]]]:
    """Entradas que empiezan con una fecha alineada a la derecha: (encabezado, fecha, líneas del cuerpo)."""
    actual: tuple[str, str, list[str]] | None = None
    for line in lines:
        m = re.match(r"^\s*(\S.*?)\s{6,}(\S.*?)\s*$", line)
        sangria = len(line) - len(line.lstrip())
        if m or (line.strip() and sangria >= 45):
            if actual:
                yield actual
            head, fecha = (m.group(1), m.group(2)) if m else ("", line.strip())
            actual = (head.strip(), fecha, [])
        elif actual:
            actual[2].append(line)
    if actual:
        yield actual


def entradas(lines: list[str]) -> list[str]:
    """Ítems numerados ("1.  Autor, “Título,” Venue, 2018.")."""
    partes = NUMERO.split("\n".join(lines))
    return [t for p in partes[1:] if (t := unir(p.splitlines()))]


def cita(text: str) -> tuple[list[str], str, str]:
    """Separa autores, título (entre comillas, a veces sin cerrar) y el resto."""
    i = min((i for c in '“‘”"' if (i := text.find(c)) >= 0), default=-1)
    if i < 0:
        return [], text, ""
    autores = [a for a in re.split(r",\s*(?:and\s+)?|\s+and\s+", text[:i].strip(" ,.")) if a]
    resto = text[i + 1 :]
    j = min((j for c in '”“"' if (j := resto.find(c)) >= 0), default=-1)
    titulo, resto = (resto[:j], resto[j + 1 :]) if j >= 0 else resto.partition(", ")[::2]
    return autores, titulo.strip(" ,."), resto.strip(" ,.")


class JorgeSilvaSpider(AcademicSpider):
    name = "sitio_jorge_silva"
    expect = {
        "persona": 1,
        "formacion": 3,
        "afiliacion": 4,
        "distincion": 6,
        "proyecto": 6,
        "actividad": 10,
        "publicacion": 50,
        "dictacion": 8,
    }

    async def start(self):
        if not self.only or self.only == PERSONA:
            yield self.page(HOME, self.parse, PERSONA)
            yield self.page(PUBLICACIONES, self.parse_publicaciones, PERSONA)
            yield self.page(CV, self.parse_cv, PERSONA)

    def parse(self, response: Response) -> Iterator:
        perfil = response.css("#profile")
        yield self.item(
            "persona",
            response,
            nombre=texts(perfil.css("h2[itemprop=name]")),
            cargo=texts(perfil.css("[itemprop=jobTitle]")),
            foto_url=response.urljoin(perfil.css("img.portrait::attr(src)").get("")),
            bio=texts(response.css("#about [itemprop=description] p")),
        )
        for href in perfil.css(".network-icon a::attr(href)").getall():
            netloc = urlparse(href).netloc
            if netloc:
                plat = next((v for k, v in PLATAFORMAS.items() if k in netloc), netloc)
                yield self.item("perfil", response, plataforma=plat, url_destino=href)

        for li in response.css(".ul-interests li"):
            yield self.item("area", response, nombre=texts(li))

        for li in response.css(".ul-edu li"):
            grado, _, anio = (texts(li.css(".course")) or "").rpartition(", ")
            yield self.item("formacion", response, grado=grado, institucion=texts(li.css(".institution")), anio=anio)

        for card in response.css("#experience .card-body"):
            desde, _, hasta = (clean(" ".join(card.css(".exp-meta").xpath("text()").getall())) or "").partition("–")
            yield self.item(
                "afiliacion",
                response,
                organizacion=texts(card.css(".exp-company")),
                rol=texts(card.css(".exp-title")),
                desde=clean(desde),
                hasta=clean(hasta),
                url_organizacion=card.css(".exp-company a::attr(href)").get(),
            )

        for card in response.css("#accomplishments .card-body"):
            sub = texts(card.css(".card-subtitle")) or ""
            yield self.item(
                "distincion",
                response,
                nombre=texts(card.css(".card-title")),
                otorgante=texts(card.css(".card-subtitle a")),
                anio=(anios(sub) or [None])[0],
            )

        for card in response.css("#talks .card-simple"):
            a = card.css(".article-title a")
            yield self.item(
                "actividad",
                response,
                tipo_actividad="charla",
                titulo=texts(a),
                descripcion=texts(card.css("[itemprop=articleBody]")),
                fecha=texts(card.css("[itemprop=startDate]")),
                url_destino=response.urljoin(a.attrib.get("href", "")),
            )

        yield from self.related(response)

    def parse_publicaciones(self, response: Response) -> Iterator:
        tipos = {o.attrib["value"].lstrip("."): texts(o) for o in response.css(".pubtype-select option")}
        for item in response.css(".isotope-item"):
            pub = item.css(".pub-list-item")
            if not pub:
                continue
            a = pub.css("a[itemprop=name]")
            doi = next(
                (m.group(0) for h in pub.css("a::attr(href)").getall() if (m := re.search(r"10\.\d{4,}/\S+", h))), None
            )
            yield self.item(
                "publicacion",
                response,
                titulo=texts(a),
                autores=pub.css("[itemprop='author name'] ::text").getall(),
                anio=(anios(" ".join(pub.xpath("text()").getall())) or [None])[0],
                tipo_publicacion=next((t for c, t in tipos.items() if c in item.attrib.get("class", "").split()), None),
                doi=doi,
                url_destino=response.urljoin(a.attrib.get("href", "")),
            )
        yield from self.related(response)

    def parse_cv(self, response: Response) -> Iterator:
        reader = PdfReader(io.BytesIO(response.body))
        text = "\n".join(p.extract_text(extraction_mode="layout") for p in reader.pages)
        s = secciones(text)
        cabecera = [c for line in text.split("Education", 1)[0].splitlines() if (c := clean(line))]
        email = next((c for c in cabecera if "@" in c), None)
        if cabecera:
            yield self.item("persona", response, nombre=cabecera[0], cargo=cabecera[1], email=email)
        for parser in (
            cv_formacion,
            cv_afiliaciones,
            cv_distinciones,
            cv_proyectos,
            cv_actividades,
            cv_publicaciones,
            cv_cursos_y_charlas,
        ):
            for tipo, campos in parser(s):
                yield self.item(tipo, response, **campos)


# Cada parser de sección del CV recibe `secciones(...)` y emite (tipo, campos).
type Items = Iterator[tuple[str, dict]]


def cv_formacion(s: dict[str, list[str]]) -> Items:
    for inst, fecha, body in bloques(s.get("Education", [])):
        t = unir(body)
        tesis = re.search(r"Title:\s*[“\"](.+?)[”\"]", t)
        yield (
            "formacion",
            {
                "grado": primera_frase(t),
                "institucion": inst,
                "anio": (anios(fecha) or [None])[-1],
                "titulo_tesis": tesis.group(1).strip(" ,.") if tesis else None,
            },
        )


def cv_afiliaciones(s: dict[str, list[str]]) -> Items:
    for org, fecha, body in bloques(s.get("Experience", [])):
        desde, _, hasta = fecha.partition("—")
        yield (
            "afiliacion",
            {
                "organizacion": org,
                "rol": primera_frase(unir(body)),
                "desde": clean(desde),
                "hasta": clean(hasta.rstrip(".")),
            },
        )


def cv_distinciones(s: dict[str, list[str]]) -> Items:
    for _, fecha, body in bloques(s.get("Distinctions", [])):
        t = unir(body)
        por = re.search(r"(?:[Gg]iven|Recognized) by (?:the )?(.+?)\.(?:\s|$)", t)
        yield (
            "distincion",
            {"nombre": primera_frase(t), "otorgante": por.group(1) if por else None, "anio": anios(fecha)[0]},
        )


def cv_proyectos(s: dict[str, list[str]]) -> Items:
    for _, fecha, body in bloques(s.get("Research Projects", [])):
        t = unir(body)
        fuente = FUENTE.search(t)
        codigo = CODIGO.search(t)
        rol = ROL_PROYECTO.search(t)
        resp = RESPONSABLE.search(t)
        titulo = re.sub(r"^Conicyt PIA \w+,\s*", "", t)  # el único proyecto que parte por la fuente
        titulo = FIN_TITULO.split(titulo, maxsplit=1)[0]
        ys = anios(fecha)
        yield (
            "proyecto",
            {
                "titulo": titulo,
                "codigo": codigo.group(1) if codigo else None,
                "fuente": fuente.group(0) if fuente else None,
                "rol": rol.group(0) if rol else None,
                "anio_inicio": ys[0] if ys else None,
                "anio_fin": ys[-1] if ys else None,
                "investigador_responsable": resp.group(1).strip() if resp else None,
            },
        )


def cv_actividades(s: dict[str, list[str]]) -> Items:
    t = unir(s.get("Activities", []))
    if m := re.search(r"Member of (.+?)\.", t):
        yield "afiliacion", {"organizacion": m.group(1), "rol": "Member"}
    for m in re.finditer(r"(Associate Editor \(AE\)) of the (.+?):\s*(.+?\d{4})\.", t):
        yield (
            "actividad",
            {
                "tipo_actividad": "editorial",
                "titulo": f"{m.group(1)} of the {m.group(2)}",
                "rol": m.group(1),
                "evento": m.group(2),
                "fecha": m.group(3),
            },
        )
    if m := re.search(r"Reviewer for:\s*(.+?)\.?$", t):
        for revista in re.split(r";\s*(?:and\s+)?|,\s*(?=IEEE|ELSEVIER)", m.group(1)):
            yield "actividad", {"tipo_actividad": "revisor", "titulo": revista, "evento": revista, "rol": "Reviewer"}


def cv_publicaciones(s: dict[str, list[str]]) -> Items:
    for _, seccion, body in bloques(s.get("Publications", [])):
        for e in entradas(body):
            autores, titulo, resto = cita(e)
            estado = "under review" if "under review" in resto else "accepted" if "accepted" in resto else None
            venue = FIN_VENUE.split(re.sub(r"^(?:in\s+(?:the\s+)?|under review:\s*)", "", resto), maxsplit=1)[0]
            doi = re.search(r"10\.\d{4,}/\S+", resto)
            ys = anios(re.sub(r"\S+/\S+", "", resto))  # sin URLs/DOIs
            yield (
                "publicacion",
                {
                    "titulo": titulo,
                    "autores": autores,
                    "anio": ys[-1] if ys else None,
                    "tipo_publicacion": None if seccion == "Under review" else seccion,
                    "venue": venue.strip(" ,.") or None,
                    "doi": doi.group(0).rstrip(".") if doi else None,
                    "estado": estado,
                },
            )
    for e in entradas(s.get("Patents", [])):
        _, titulo, resto = cita(e)
        yield "producto", {"tipo_producto": "patente", "nombre": titulo, "descripcion": resto or None}


def cv_cursos_y_charlas(s: dict[str, list[str]]) -> Items:
    t = unir(s.get("Teaching", []))
    for m in re.finditer(r"([A-Z][^:]*?):\s*(Lecturer|Teaching Assistant),[^()]*\(([^)]*)\)", t):
        for sem, anio in re.findall(r"(Spring|Fall)\s+(\d{4})", m.group(3)):
            yield "dictacion", {"nombre_curso": m.group(1), "rol": m.group(2), "anio": int(anio), "semestre": sem}
    for e in re.split(r"(?=“)", unir(s.get("Talks", []))):
        if not e.startswith("“"):
            continue
        titulo, _, resto = e[1:].partition("”")
        resto = resto.strip(" ,.")
        ys = anios(resto)
        yield (
            "actividad",
            {
                "tipo_actividad": "charla",
                "titulo": titulo.strip(" ,."),
                "evento": re.sub(r"^at (?:the )?", "", resto) or None,
                "fecha": str(ys[-1]) if ys else None,
            },
        )
