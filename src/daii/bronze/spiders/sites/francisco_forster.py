"""Sitio personal de Francisco Förster (Jekyll, una sola página) y su CV en PDF (LaTeX, una columna)."""

import re
from collections.abc import Iterator
from urllib.parse import urlparse

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, anios, clean, latex_acentos, pdf_texto, texts

PERSONA = "francisco-forster"
HOME = "https://fforster.github.io/"
CV = HOME + "assets/CV.pdf"

PLATAFORMAS = {
    "scholar.google": "scholar",
    "orcid": "orcid",
    "adsabs": "ads",
    "linkedin": "linkedin",
    "github": "github",
}

# About Me: "<rol> at/of the <Organización> (<SIGLA>[, años])". El rol se hereda si la frase lo comparte
# ("principal investigator of the ... (ALeRCE) ... and the ... (HiTS, 2012-2018)").
ORG = re.compile(r"the (?:The )?(?P<org>[A-Z][^()]*?) \((?P<sigla>[A-Za-z]+)(?:, (?P<desde>\d{4})-(?P<hasta>\d{4}))?\)")
ROL = re.compile(
    r"Full Professor|director|Research Scientist|Associate Researcher|principal investigator|academic coordinator"
)
ANIOS = re.compile(r"^[^()]*?\((\d{4})-(\d{4})\)|^\s*since (\d{4})")
PRODUCTO = re.compile(r"broker|Survey")
TELESCOPIO = re.compile(
    r"(?P<rol>led the installation) of the (?P<nombre>\S+) (?P<desc>[^.()]*telescope[^.()]*\([^)]*\))"
)
PHD = re.compile(r"I did my (?P<grado>Ph\.D\.) thesis on .+? at the (?P<inst>[^(]+?) \((?P<anio>\d{4})\)")

SECCIONES = {
    "Profile",
    "Education",
    "Research",
    "Grants and Awards:",
    "Invitations to speak at international conferences:",
    "Teaching Experience",
    "Students / Engineers Supervising Experience",
    "ALeRCE project engineers (as P.I.)",
    "Organization of conferences:",
    "Other recognitions/contributions:",
    "Other",
}
FRASE = re.compile(r"(?<!Prof)(?<!\b[A-Z])\.\s+(?=[A-Z])")  # fin de oración, sin cortar "Prof. X" ni "P.I."


def unir(lines: list[str]) -> str:
    t = re.sub(r"(\w)(?<!\bco)-\n([a-z])", r"\1\2", "\n".join(lines))  # deshace guionado de LaTeX
    return clean(t) or ""


def secciones(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    actual = None
    for line in latex_acentos(text).splitlines():
        if line.strip() in SECCIONES:
            actual = line.strip().rstrip(":")
        elif actual:
            out.setdefault(actual, []).append(line)
    return out


def entradas(lines: list[str], inicio: str) -> list[str]:
    """Agrupa líneas en entradas: una nueva entrada empieza en cada línea que calza `inicio`."""
    out: list[list[str]] = []
    for line in lines:
        if re.match(inicio, line) or not out:
            out.append([])
        out[-1].append(line)
    return [unir(e) for e in out]


class FranciscoForsterSpider(AcademicSpider):
    name = "sitio_francisco_forster"
    expect = {
        "persona": 1,
        "afiliacion": 8,
        "producto": 2,
        "formacion": 2,
        "area": 2,
        "perfil": 3,
        "proyecto": 5,
        "actividad": 12,
        "dictacion": 15,
        "tesis": 30,
        "distincion": 2,
    }

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(HOME, self.parse, PERSONA)
            yield self.page(CV, self.parse_cv, PERSONA)

    def parse(self, response: Response) -> Iterator:
        sec = response.css("section")
        about = sec.xpath(
            ".//h1[@id='-about-me']/following-sibling::p[following-sibling::h1[@id='-research-interests']]"
        )
        texto = clean("".join(about.css("::text").getall())) or ""
        email = next((t for t in sec.css("li::text").getall() if t.strip().startswith("Email:")), "")
        yield self.item(
            "persona",
            response,
            nombre=texts(sec.css("h1[id^='--francisco']")),
            cargo=clean(response.css("header p::text").get()),
            email=clean(email.split(":", 1)[-1]),
            foto_url=about.css("img::attr(src)").get(),
            bio=texto,
        )

        links = {texts(a): a.attrib["href"] for a in about.css("a")}
        matches = list(ORG.finditer(texto))
        rol = None
        for i, m in enumerate(matches):
            antes = texto[matches[i - 1].end() if i else 0 : m.start()]
            despues = texto[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(texto)]
            rol = (ROL.findall(antes) or [rol])[-1]
            a = ANIOS.match(despues)
            desde = m["desde"] or (a and (a[1] or a[3]))
            hasta = m["hasta"] or (a and a[2])
            org = f"{m['org']} ({m['sigla']})"
            yield self.item(
                "afiliacion",
                response,
                organizacion=org,
                rol=rol,
                desde=desde or None,
                hasta=hasta or None,
                url_organizacion=links.get(m["sigla"]),
            )
            frase = re.split(r"\.\s+(?=I\b)|, and ", despues)[0]  # resto de la cláusula de esta organización
            if tipo := PRODUCTO.search(m["org"] + frase):
                yield self.item(
                    "producto",
                    response,
                    tipo_producto=tipo.group(0),
                    nombre=m["sigla"],
                    descripcion=clean(m["org"] + frase),
                    url_destino=links.get(m["sigla"]),
                    rol=rol,
                )
        if t := TELESCOPIO.search(texto):
            yield self.item(
                "producto", response, tipo_producto="telescope", nombre=t["nombre"], descripcion=t["desc"], rol=t["rol"]
            )
        if p := PHD.search(texto):
            yield self.item("formacion", response, grado=p["grado"], institucion=p["inst"], anio=p["anio"])

        research = sec.xpath(".//h1[@id='-research-interests']/following-sibling::ul[1]/li")
        for li in research:
            yield self.item("area", response, nombre=texts(li))

        for href in sec.css("a::attr(href)").getall():
            netloc = urlparse(href).netloc
            if plat := next((v for k, v in PLATAFORMAS.items() if k in netloc), None):
                orcid = re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", href) if plat == "orcid" else None
                yield self.item(
                    "perfil",
                    response,
                    plataforma=plat,
                    url_destino=href,
                    identificador=orcid.group(0) if orcid else None,
                )

        yield from self.related(response, region="section")

    def parse_cv(self, response: Response) -> Iterator:
        s = secciones(pdf_texto(response))
        for parser in (
            cv_formacion,
            cv_afiliaciones,
            cv_fondos,
            cv_charlas,
            cv_cursos,
            cv_tesis,
            cv_organizacion,
            cv_otros,
        ):
            for tipo, campos in parser(s):
                yield self.item(tipo, response, **campos)


# Cada parser de sección del CV recibe `secciones(...)` y emite (tipo, campos).
type Items = Iterator[tuple[str, dict]]


def cv_formacion(s: dict[str, list[str]]) -> Items:
    # "D.Phil. in Physics, University of Oxford, 2004 – 2009. Thesis title: ... Supervised by Prof. ..."
    for e in entradas(s.get("Education", []), r"(?:D\.Phil|B\.Sc|M\.Sc|Ph\.D)\.|.*Summer School"):
        m = re.match(r"((?:D\.Phil|B\.Sc|M\.Sc|Ph\.D)\.?[^,]*), ([^,]+), (\d{4})(?:\s*–\s*(\d{4}))?", e)
        if m:
            tesis = re.search(r"Thesis title: (.+?)\.", e)
            yield (
                "formacion",
                {
                    "grado": m[1],
                    "institucion": m[2],
                    "anio": int(m[4] or m[3]),
                    "titulo_tesis": tesis[1] if tesis else None,
                },
            )


def cv_afiliaciones(s: dict[str, list[str]]) -> Items:
    # "2024 – present, Millennium Institute for Astrophysics: Director."
    fecha = r"(?:[A-Z][a-z]{2} )?\d{4}"
    for e in entradas(s.get("Research", []), rf"{fecha} – "):
        m = re.match(rf"({fecha}) – ({fecha}|present), (.+)", e)
        if not m:
            continue
        org, sep, rol = m[3].partition(": ")
        if not sep:  # "Center for ... (CATA) Associate Researcher."
            org, _, rol = m[3].rpartition(") ")
            org += ")"
        yield (
            "afiliacion",
            {
                "organizacion": org,
                "rol": FRASE.split(rol, maxsplit=1)[0].rstrip("."),
                "desde": m[1],
                "hasta": m[2],
            },
        )


def cv_fondos(s: dict[str, list[str]]) -> Items:
    """Grants and Awards: proyectos ("<rol> of <fuente> project <título>, 2024 (awarded 206 kUSD).") y becas."""
    entradas_ = re.split(r"(?<=\)\.)\s+", unir(s.get("Grants and Awards", [])))
    for e in entradas_:
        monto = re.search(r"\((?:awarded|budget of) ([^)]*)\)", e)
        campos = {"monto": monto[1] if monto else None}
        if m := re.match(r"(.+?) of (?:the )?(.+?) project (.+?), (\d{4})", e):
            campos |= {"rol": m[1], "fuente": m[2], "titulo": m[3], "anio_inicio": int(m[4]), "anio_fin": int(m[4])}
        elif m := re.match(r"((Fondecyt) .+? Fellow), (\d{4})\s*–?\s*(\d{4})?\. (.+?)\s?\.\s", e):
            fin = int(m[4]) if m[4] else None
            campos |= {"rol": m[1], "fuente": m[2], "titulo": m[5], "anio_inicio": int(m[3]), "anio_fin": fin}
        elif m := re.match(r"(.+?) of (?:the )?(.+?), (\d{4})(?:–(\d{4}))? \(", e):
            fin = int(m[4]) if m[4] else int(m[3])
            campos |= {"rol": m[1], "titulo": m[2], "anio_inicio": int(m[3]), "anio_fin": fin}
        elif m := re.match(r"(.+?) \((\d{4})\)", e):  # "PPARC - GEMINI studentship (2003), ..."
            yield "distincion", {"nombre": m[1], "anio": int(m[2])}
            continue
        else:
            continue
        yield "proyecto", campos


def cv_charlas(s: dict[str, list[str]]) -> Items:
    for e in re.split(r"(?<=\(\d{4}\))\.?\s+", unir(s.get("Invitations to speak at international conferences", []))):
        if m := re.match(r"(.+?)\s*\((\d{4})\)", e):
            yield "actividad", {"tipo_actividad": "charla", "titulo": m[1], "evento": m[1], "fecha": m[2]}


def cv_cursos(s: dict[str, list[str]]) -> Items:
    # "Astroinformatics, U. Chile: Lecturer of this course ... (2011B, 2012B, ...)."
    for e in entradas(s.get("Teaching Experience", []), r"[^:]+: (?:Lecturer)"):
        m = re.match(r"([^:]+): (Lecturer(?: and organizer)?).*\(([^()]*)\)\.?$", e)
        if not m:
            continue
        for anio, sem in re.findall(r"(\d{4})([AB])?", m[3]):
            yield "dictacion", {"nombre_curso": m[1], "rol": m[2], "anio": int(anio), "semestre": sem or None}


def cv_tesis(s: dict[str, list[str]]) -> Items:
    """Students: "Astronomy: Isidora Mancilla, 2024 (B.Sc.); ..." (el CV no trae títulos de tesis)."""
    for e in entradas(s.get("Students / Engineers Supervising Experience", []), r"[A-Z][\w ]+: "):
        programa, _, lista = e.partition(": ")
        if programa.startswith("Visiting students"):
            continue
        for est in filter(None, (x.strip(" .") for x in lista.split(";"))):
            m = re.match(r"(.+?), ?(\d{4})(?:-(\d{4}|present))?,? \(([^)]*)\)", est)
            if not m:
                continue
            nivel = m[4]
            yield (
                "tesis",
                {
                    "estudiante": m[1],
                    "anio": int(m[3]) if m[3] and m[3].isdigit() else int(m[2]) if not m[3] else None,
                    "nivel": re.split(r",? co-?supervisor", nivel)[0].strip(", ") or None,
                    "rol": "co-supervisor" if re.search(r"co-?supervisor", nivel) else None,
                    "programa": programa,
                },
            )


def cv_organizacion(s: dict[str, list[str]]) -> Items:
    for e in entradas(s.get("Organization of conferences", []), r"(?:LOC|SOC) "):
        if m := re.match(r"(.+? member(?: and invited speaker)?) (?:in|at) (?:the )?(?:conference )?(.+)", e):
            ys = anios(m[2])
            yield (
                "actividad",
                {
                    "tipo_actividad": "organizacion_evento",
                    "titulo": m[2].rstrip("."),
                    "rol": m[1],
                    "fecha": ", ".join(map(str, ys)) or None,
                },
            )


def cv_otros(s: dict[str, list[str]]) -> Items:
    lineas = s.get("Other recognitions/contributions", [])
    for e in entradas(lineas, r"(?:Founder|Member|Scientific|Head|1st|Beca)\b"):
        for parte in re.split(r",?\s+and\s+(?=Beca)", e):
            parte = parte.rstrip(".,")
            if m := re.match(r"Founder of the startup (\w+), (\S+), (.+)", parte):
                yield (
                    "producto",
                    {
                        "tipo_producto": "startup",
                        "nombre": m[1],
                        "url_destino": m[2],
                        "descripcion": m[3],
                        "rol": "Founder",
                    },
                )
            elif parte.startswith(("1st", "Beca")):
                ys = anios(parte)
                yield "distincion", {"nombre": re.sub(r"\s*\([^)]*\)$", "", parte), "anio": ys[-1] if ys else None}
            elif m := re.match(
                r"(Member|Scientific advisor|Head) (?:of|for) (?:the )?(.+?)(?:,? \(?(\d{4})–(\d{4})\)?)?$", parte
            ):
                yield (
                    "actividad",
                    {
                        "tipo_actividad": "asesoria" if m[1] == "Scientific advisor" else "comite",
                        "titulo": parte,
                        "rol": m[1],
                        "evento": m[2],
                        "fecha": f"{m[3]}–{m[4]}" if m[3] else None,
                    },
                )
