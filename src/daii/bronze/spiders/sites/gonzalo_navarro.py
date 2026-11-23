"""Sitio personal de Gonzalo Navarro (HTML estático de los 90, en castellano) y su CV largo en PDF.

Fuentes:
- `sindex.html`: áreas, cargos actuales, libros, Pizza&Chili, charlas invitadas recientes, comités, cursos, perfiles.
  La versión en inglés (`index.html`) trae lo mismo y menos (sin cursos), así que no se pide.
- `curric/curric.pdf` (CV largo, castellano, LaTeX): formación con tesis, proyectos con código Fondecyt,
  distinciones, charlas plenarias desde 2001, comités editoriales y chairs. Se leen solo las secciones previas a
  "Publicaciones" (las publicaciones llegan por DBLP/ORCID). El CV corto en inglés tiene menos proyectos y no
  trae códigos ni tesis.
- `mem/realizadas.html` y `mem/encurso.html`: tesis guiadas (más completas y estructuradas que el CV).
- `software/sindex.html`: software publicado.
"""

import io
import re
import unicodedata
from collections.abc import Iterator

from pypdf import PdfReader
from scrapy.http import Response

from daii.bronze.spiders.base import ANIO, AcademicSpider, anio, anios, clean, latex_acentos, texts
from daii.config import academico

PERSONA = "gonzalo-navarro"
BASE = "https://users.dcc.uchile.cl/~gnavarro/"
HOME = BASE + "sindex.html"
REALIZADAS = BASE + "mem/realizadas.html"
EN_CURSO = BASE + "mem/encurso.html"
SOFTWARE = BASE + "software/sindex.html"

ENTRADA = re.compile(r"^\((\d{4}[^)]*)\)\s+(.*)$")  # "(2016-2017, 2019-2022) Profesor guía en ..."
# Rótulos de sección del CV → clave del parser (None = se ignora, pero corta la sección anterior).
SECCIONES = {
    "Datos Personales": None,
    "Formación": None,
    "Estudios Cursados": "formacion",
    "Becas": None,
    "Distinciones": "distincion",
    "Investigación": None,
    "Estadías de Investigación": None,
    "Proyectos de Investigación": "proyecto",
    "Charlas Invitadas y Tutoriales": "charla",
    "Comités Editoriales y Steering Committees": "comite",
    "Chair de Comité de Programa y Editor Invitado": "comite",
    "Organización de y Participación en Seminarios Internacionales": "seminario",
    "Referatos y Comités de Programa": None,
}
ROL_PROYECTO = re.compile(
    r"^(Investigador (?:principal|asociado|[Cc]lave|Residente)|Coinvestigador|Coordinador|Director"
    r"|Responsable(?: chileno| por la Universidad de Chile)?|Profesor guía|Alumno tesista)"
)
CODIGO = re.compile(r"\b(?:Fondecyt|Fondef|CYTED|ECOS/Conicyt) ([\w./-]*\d[\w./-]*)")
FUENTE = re.compile(
    r"\b(Fondecyt|Fondef|CYTED|ECOS/Conicyt|CICYT|Iniciativa Científica Milenio|Mideplan|Conicyt"
    r"|Yahoo! Research|Google Research Awards|Unión Europea)"
)
FRASE = re.compile(r"\.\s+(?=[A-ZÁÉÍÓÚ])|\.$")
ROL_CHAIR = re.compile(r"^(associate chair|special session chair|cochair|chair|coorganizador)\s+(?:de un a|del|de)\s+")


def unir(lines: list[str]) -> str:
    """Une líneas del PDF: arregla acentos y ligaduras de LaTeX y deshace el guionado ("Struc-\\ntures")."""
    t = unicodedata.normalize("NFKC", latex_acentos("\n".join(line.strip() for line in lines)))
    t = re.sub(r"(\w)-\n([a-zà-ÿ])", r"\1\2", t)
    return clean(re.sub(r"-\n", "-", t)) or ""


def primera_frase(text: str) -> str:
    return FRASE.split(text, maxsplit=1)[0].strip(" .")


def primera_clausula(text: str) -> str:
    """Hasta la primera coma fuera de paréntesis, o hasta " por el/la/los"."""
    m = re.match(r"(?:\([^)]*\)|[^,(])+", text)
    return re.split(r"\s+por (?:el|la|los) ", m.group(0) if m else text)[0].strip(" .")


def secciones(text: str) -> dict[str, list[tuple[str, str]]]:
    """Agrupa las entradas "(fecha) texto" del CV por sección. Cada entrada: (fecha, texto)."""
    out: dict[str, list[tuple[str, str]]] = {}
    actual: str | None = None
    fecha, lineas = "", []

    def cerrar():
        if actual and lineas:
            out.setdefault(actual, []).append((fecha, unir(lineas)))

    for line in text.splitlines():
        cabeza = unir([line])
        if re.fullmatch(r"\d{1,3}", cabeza):  # número de página
            continue
        if cabeza in SECCIONES:
            cerrar()
            actual, fecha, lineas = SECCIONES[cabeza], "", []
        elif m := ENTRADA.match(line.strip()):
            cerrar()
            fecha, lineas = m.group(1), [m.group(2)]
        elif lineas:
            lineas.append(line)
    cerrar()
    return out


class GonzaloNavarroSpider(AcademicSpider):
    name = "sitio_gonzalo_navarro"
    expect = {
        "persona": 1,
        "afiliacion": 2,
        "area": 3,
        "perfil": 1,
        "publicacion": 1,
        "producto": 4,
        "dictacion": 3,
        "formacion": 2,
        "proyecto": 17,
        "distincion": 14,
        "tesis": 40,
        "actividad": 60,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(HOME, self.parse, PERSONA)
        # el CV trae año de nacimiento y estado civil: no se guarda el PDF en pages/
        yield self.page(academico(PERSONA)["perfiles"]["cv"], self.parse_cv, PERSONA, guardar=False)
        yield self.page(REALIZADAS, self.parse_tesis, PERSONA)
        yield self.page(EN_CURSO, self.parse_tesis, PERSONA)
        yield self.page(SOFTWARE, self.parse_software, PERSONA)

    def parse(self, response: Response) -> Iterator:
        def lista(h2: str):
            return response.xpath(f"//h2[contains(., '{h2}')]/following-sibling::ul[1]/li")

        presentacion = texts(response.xpath("//h2[contains(., 'Presentaci')]/following-sibling::text()[1]/..")) or ""
        cargo = re.search(r"Soy (Profesor \w+)", presentacion)
        contacto = [c for t in response.css("address ::text").getall() if (c := clean(t))]
        tel = next((c.split(":", 1)[1].strip() for c in contacto if c.startswith("Teléfono")), None)
        yield self.item(
            "persona",
            response,
            nombre=contacto[0],
            cargo=cargo.group(1) if cargo else None,
            email=response.css("address a[href^=mailto]::text").get(),
            telefono=tel,
            foto_url=response.css("img::attr(src)").get(),
        )
        if cargo:
            # "Soy Profesor Titular del <a>DCC</a>, <a>FCFM</a>, <a>Universidad de Chile</a>."
            orgs = response.xpath("//h2[contains(., 'Presentaci')]/following-sibling::a[position() <= 3]")
            yield self.item(
                "afiliacion",
                response,
                rol=cargo.group(1),
                organizacion=", ".join(texts(a) or "" for a in orgs),
                url_organizacion=orgs[0].attrib.get("href") if orgs else None,
            )
        for li in lista("Cargos"):  # "Coordinador del Programa de Doctorado (DCC)"
            t = texts(li) or ""
            org = re.search(r"\(([^)]+)\)$", t)
            yield self.item("afiliacion", response, rol=t, organizacion=org.group(1) if org else t)

        for li in response.xpath("//text()[contains(., 'reas de inter')]/following::ul[1]/li"):
            yield self.item("area", response, nombre=texts(li))

        for a in response.css("a[href*='scholar.google'], a[href*='dblp.org']"):
            href = a.attrib["href"]
            yield self.item("perfil", response, plataforma="scholar" if "scholar" in href else "dblp", url_destino=href)

        for li in lista("Charlas"):
            t = texts(li) or ""
            a = li.css("a")
            if t.startswith("Libro") and a:
                yield self.item(
                    "publicacion",
                    response,
                    titulo=texts(a[0]),
                    tipo_publicacion="libro",
                    url_destino=a[0].attrib["href"],
                )
            elif "pizzachili" in li.get():
                yield self.item(
                    "producto",
                    response,
                    tipo_producto="software",
                    nombre=texts(a[0]),
                    descripcion=t,
                    url_destino=a[0].attrib["href"],
                )
            elif t.startswith("Charlista invitado"):
                for x in a:  # "<a>ACDA 2025</a> (Montreal, Canadá, 30 de Julio al 1 de Agosto),"
                    evento = texts(x) or ""
                    lugar = re.match(r"\s*\(([^)]*)\)", " ".join(x.xpath("following-sibling::text()[1]").getall()))
                    yield self.item(
                        "actividad",
                        response,
                        tipo_actividad="charla",
                        titulo=evento,
                        evento=evento,
                        fecha=(ANIO.findall(evento) or [None])[-1],
                        descripcion=clean(lugar.group(1)) if lugar else None,
                        url_destino=x.attrib.get("href"),
                    )

        for li in lista("Comit"):
            t = re.sub(r'href="[^"]*">', "", texts(li) or "")  # HTML roto en la fuente
            if t.startswith("Miembro del Comité Editorial de"):
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="editorial",
                    rol="Miembro del Comité Editorial",
                    titulo=t.removeprefix("Miembro del Comité Editorial de").strip(),
                    url_destino=li.css("a::attr(href)").get(),
                )
                continue
            cabeza, _, resto = t.partition(":")  # "Chair de conferencias 2015-: cochair de ACDA 2027, ..."
            rol = "PC Member" if cabeza.startswith("PC Member") else None
            for pieza in re.split(r"\s*,\s+(?!\d)", resto.strip(" ,.")):
                pieza = clean(pieza.strip(" ,.")) or ""
                if m := ROL_CHAIR.match(pieza):
                    rol, pieza = m.group(1), pieza[m.end() :]
                if not pieza or not rol:
                    continue
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="organizacion_evento" if rol == "coorganizador" else "comite_programa",
                    rol=rol,
                    titulo=pieza,
                    evento=pieza,
                    fecha=(ANIO.findall(pieza) or [None])[0],
                )

        for li in response.xpath("//li[contains(., 'Cursos que usualmente dicto')]//ul/li"):
            codigo = texts(li.css("b")) or ""
            yield self.item(
                "dictacion",
                response,
                codigo_curso=codigo.rstrip(":"),
                nombre_curso=(texts(li) or "").removeprefix(codigo).strip(),
            )
        yield from self.related(response)

    def parse_tesis(self, response: Response) -> Iterator:
        en_curso = "encurso" in response.url
        if en_curso:
            # <li><b>Estudiante</b>, Universidad.<br><a>Título</a>.<br>Memoria de Ingeniería, 2026-. Co-guía con ...
            grupos = [(None, response.xpath("//ol[1]/li"))]
        else:
            # <h3>Doctorado</h3><ol><li><i><a>Título</a></i>.<br><b>Estudiante</b>, Universidad, 2025.<br>Co-guía...
            grupos = [(texts(h3), h3.xpath("following::ol[1]/li")) for h3 in response.css("h3")]
        for nivel, lis in grupos:
            for li in lis:
                t = texts(li) or ""
                titulo = texts(li.css("a")) if en_curso else texts(li.css("i"))
                if not titulo:
                    continue
                if en_curso:  # "Memoria de Ingeniería, 2026-." / "Tesis de Doctorado, 2018-."
                    m = re.search(r"((?:Memoria|Tesis) de [^,]+), ((?:19|20)\d{2})", t)
                    nivel_li, anio_li = (m.group(1), m.group(2)) if m else (None, None)
                else:
                    nivel_li, anio_li = nivel, anio(t.split(titulo, 1)[-1])
                yield self.item(
                    "tesis",
                    response,
                    titulo=titulo.rstrip("."),
                    estudiante=texts(li.css("b")),
                    nivel=nivel_li,
                    anio=anio_li,
                    rol="Co-guía" if "Co-guía" in t else "guía",
                    estado="en curso" if en_curso else "terminada",
                    url_destino=li.css("a::attr(href)").get(),
                )
        yield from self.related(response)

    def parse_software(self, response: Response) -> Iterator:
        for h3 in response.css("h3"):  # sin url: el primer link de cada bloque suele ser el paper, no el código
            yield self.item("producto", response, tipo_producto="software", nombre=texts(h3))
        yield from self.related(response)

    def parse_cv(self, response: Response) -> Iterator:
        reader = PdfReader(io.BytesIO(response.body))
        paginas = []
        for p in reader.pages:  # las secciones útiles están antes de "Publicaciones" (~13 de 70 páginas)
            t = p.extract_text()
            corte = re.search(r"^Publicaciones\s*$", t, re.M)
            paginas.append(t[: corte.start()] if corte else t)
            if corte:
                break
        s = secciones("\n".join(paginas))
        for parser in (cv_formacion, cv_distinciones, cv_proyectos, cv_actividades):
            for tipo, campos in parser(s):
                yield self.item(tipo, response, **campos)


type Items = Iterator[tuple[str, dict]]


def cv_formacion(s: dict[str, list[tuple[str, str]]]) -> Items:
    for fecha, t in s.get("formacion", []):
        # "Doctorado en Ciencias, Mención Computación, Facultad de ..., Universidad de Chile Promedio: ... Tesis: “...”"
        grado, _, inst = re.sub(r", (?=Facultad|Escuela)", "|", t.split(" Promedio:")[0], count=1).partition("|")
        tesis = re.search(r"Tesis(?: de grado)?: “(.+?)”", t)
        yield (
            "formacion",
            {
                "grado": grado,
                "institucion": inst or None,
                "anio": anios(fecha)[-1],
                "titulo_tesis": tesis.group(1) if tesis else None,
            },
        )


def cv_distinciones(s: dict[str, list[tuple[str, str]]]) -> Items:
    for fecha, t in s.get("distincion", []):
        por = re.search(r"entregad[oa] por (?:la |el )?(?:Editorial )?(.+?)(?:,| a | como |$)", t)
        yield (
            "distincion",
            {"nombre": primera_clausula(t), "otorgante": por.group(1) if por else None, "anio": anios(fecha)[0]},
        )


def cv_proyectos(s: dict[str, list[tuple[str, str]]]) -> Items:
    for fecha, t in s.get("proyecto", []):
        rol = ROL_PROYECTO.match(t)
        codigo = CODIGO.search(t)
        fuente = FUENTE.search(t)
        resp = re.search(r"\(a cargo de ([^)]+)\)", t)
        cita = re.search(r"“(.+?)”", t)
        if (
            codigo
        ):  # "... Fondecyt 1-260080, Space/Time Efficient Solutions ..." / "... 1-090037 (a cargo de X), Título"
            titulo = primera_frase(re.sub(r"^(?:\s*\([^)]*\))*\s*,?\s*", "", t[codigo.end() :]))
        elif cita:
            titulo = cita.group(1)
        else:  # "Investigador asociado en el Instituto Milenio ..." → "Instituto Milenio ..."
            resto = re.sub(r"^\s*\([^)]*\)", "", t[rol.end() :] if rol else t)
            titulo = primera_frase(re.sub(r"^\s*(?:en|del?|de la)\s+(?:el |la )?", "", resto))
        ys = anios(fecha)
        yield (
            "proyecto",
            {
                "titulo": titulo.strip('“”" ') or t,
                "codigo": codigo.group(1) if codigo else None,
                "fuente": fuente.group(1) if fuente else None,
                "rol": rol.group(1) if rol else None,
                "anio_inicio": ys[0] if ys else None,
                "anio_fin": None if fecha.rstrip().endswith("-") else (ys[-1] if ys else None),
                "investigador_responsable": resp.group(1) if resp else None,
            },
        )


def cv_actividades(s: dict[str, list[tuple[str, str]]]) -> Items:
    for fecha, t in s.get("charla", []):
        titulo = re.search(r"Título: “(.+?)”", t) or re.search(r"“(.+?)”", t)
        evento = re.search(r"\ben (?:el |la |las |los )?(.+?)(?:\.\s+(?=[A-Z])|\.?$)", t)
        tipo = "tutorial" if t.startswith("Tutorial") else "charla"
        yield (
            "actividad",
            {
                "tipo_actividad": "keynote" if "plenaria" in t else tipo,
                "titulo": titulo.group(1).strip(" .,") if titulo else primera_frase(t),
                "evento": evento.group(1) if evento else None,
                "fecha": fecha,
                "descripcion": t,
            },
        )
    for clave in ("comite", "seminario"):
        for fecha, t in s.get(clave, []):
            if t.startswith("Participación"):
                continue
            if clave == "seminario":
                tipo = "organizacion_evento"
            else:
                tipo = "editorial" if re.search(r"Editor", t) else "comite_programa"
            rol = re.match(r"^(.+?) (?:del?|de la|en el) ", t)
            yield (
                "actividad",
                {"tipo_actividad": tipo, "titulo": t.rstrip("."), "rol": rol.group(1) if rol else None, "fecha": fecha},
            )
