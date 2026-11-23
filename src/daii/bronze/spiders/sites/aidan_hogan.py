"""Sitio personal de Aidan Hogan: una sola página larga (XHTML plano, secciones h2/h3 hermanas en <body>).

Las subpáginas enlazadas (tesis doctoral en docs/thesis/, páginas de cursos en teaching/) no traen datos
estructurados nuevos: quedan como `pagina` vía `related()`. Los bloques "Projects", "Past Teaching" y el
detalle de PC por año están comentados en el HTML, así que no se emiten (bronze no inventa).
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, texts

SITIO = "https://aidanhogan.com/"
PERSONA = "aidan-hogan"
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
QUOTED = re.compile(r'"(.+?)"')
ORCID = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
# "I'm a Professor in the Department ... at the Universidad de Chile, and an Associate Researcher of the ..."
ROL_ORG = re.compile(r"(?:I'm|and) an? ([A-Z][\w ]+?) (?:in|of) the (.+?)(?:,|\.$)")
# Sección h2 → (tipo_actividad, rol) para listas de servicio
SERVICIO = {
    "PC Memberships": "comite_programa",
    "SPC Memberships / Sub-Track Chair / Area Chair": "comite_programa",
    "Editor-in-Chief": "editorial",
    "Editorial Board": "editorial",
}
CHARLAS = {"Keynote Speaker": "keynote", "Invited Lectures": "charla", "Invited Talks": "charla"}


def plain(sel) -> str:
    """Texto sin separadores extra entre hijos ("<span>Aidan Hogan</span>, Eva" → "Aidan Hogan, Eva")."""
    return clean("".join(sel.css("::text").getall())) or ""


def after_at_the(a) -> bool:
    """El <a> del evento es el que sigue a "at the" (antes puede haber coautores enlazados)."""
    return (clean(a.xpath("preceding-sibling::text()[1]").get()) or "").endswith("at the")


def autores(s: str) -> list[str]:
    return [a for a in re.split(r",\s*(?:and\s+)?|\s+and\s+", s.strip(" .,")) if a]


class AidanHoganSpider(AcademicSpider):
    name = "sitio_aidan_hogan"
    expect = {
        "persona": 1,
        "perfil": 3,
        "afiliacion": 2,
        "formacion": 1,
        "publicacion": 150,
        "actividad": 60,
        "dictacion": 2,
        "tesis": 30,
        "distincion": 15,
    }

    async def start(self):
        if self.only and self.only != PERSONA:
            return
        yield self.page(SITIO, self.parse, PERSONA)

    def parse(self, response: Response) -> Iterator:
        h2 = h3 = None
        intro: list = []
        for el in response.xpath("/html/body/*"):
            tag = el.root.tag
            if tag == "h2":
                h2, h3 = texts(el), None
            elif tag == "h3":
                h3 = texts(el)
            elif h2 is None and tag == "p":
                intro.append(el)
            elif h2 == "Publications" and h3 and tag == "p":
                yield from self._publicacion(response, el, h3)
            elif h2 == "Ph.D. Thesis" and tag == "p":
                yield from self._formacion(response, intro, plain(el))
            elif h2 == "Organisation and Chairing" and tag == "p":
                t = plain(el)
                rol = t.split(" of the ")[0]
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="comite_programa" if rol.startswith("PC ") else "organizacion_evento",
                    rol=rol,
                    titulo=plain(el.css("a")) or t,
                    fecha=h3,
                    descripcion=t,
                    url_destino=el.css("a::attr(href)").get(),
                )
            elif h2 in SERVICIO and tag == "ul":
                for li in el.css("li"):
                    t = plain(li)
                    yield self.item(
                        "actividad",
                        response,
                        tipo_actividad=SERVICIO[h2],
                        rol=h2,
                        # "AAAI: 2013, 2015, 2021" / "<a>Journal of Web Semantics (JWS)</a> [Resigned 2023]"
                        titulo=plain(li.css("a")) or t.split(":")[0],
                        fecha=t.partition(": ")[2] or None,
                        descripcion=t,
                        url_destino=li.css("a::attr(href)").get(),
                    )
            elif h2 == "Other Reviewing" and tag == "p":
                yield self.item("actividad", response, tipo_actividad="revision", rol=h2, titulo=plain(el))
            elif h2 in CHARLAS and tag == "p":
                yield self._charla(response, el, h2, h3)
            elif h2 == "Tutorials" and tag == "p":
                t = plain(el)
                links = el.css("a")
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad="tutorial",
                    titulo=plain(links[0]),
                    evento=plain(links[1]) if len(links) > 1 else None,
                    fecha=h3,
                    descripcion=t,
                    url_destino=links[0].attrib["href"],
                )
            elif h2 == "Teaching" and tag == "ul":
                for li in el.css("li"):
                    # "La Web de Datos (Web of Data), English, Postgraduate, 2015–2023 (see 2023 content)"
                    url = li.css("a::attr(href)").get()
                    yield self.item(
                        "dictacion",
                        response,
                        nombre_curso=plain(li).split(", ")[0],
                        url_curso=response.urljoin(url) if url else None,
                    )
            elif h2 == "Supervision" and tag == "ul":
                for li in el.css("li"):
                    # "Sebastián Ferrada: PhD in Computer Science (co-supervised with Benjamín Bustos)"
                    estudiante, _, rest = plain(li).partition(": ")
                    nivel, _, co = rest.partition(" (")
                    yield self.item(
                        "tesis",
                        response,
                        titulo=nivel,  # la fuente no da título de tesis, solo el programa
                        nivel=nivel,
                        estudiante=estudiante,
                        rol=co.rstrip(")") or None,
                        estado=h3,
                    )
            elif h3 == "Awards, distinctions, etc." and tag == "ul":
                for li in el.css("li"):
                    nombre = plain(li)
                    anio = YEAR.search(nombre)
                    yield self.item("distincion", response, nombre=nombre, anio=anio.group(0) if anio else None)

        yield from self._persona(response, intro)
        yield from self.related(response)

    def _persona(self, response: Response, intro: list) -> Iterator:
        roles = ROL_ORG.findall(plain(intro[1])) if len(intro) > 1 else []
        email = response.css("a[href^='mailto:']::attr(href)").get()
        yield self.item(
            "persona",
            response,
            nombre=texts(response.css("h1")),
            cargo=roles[0][0] if roles else None,
            email=email.removeprefix("mailto:") if email else None,
            foto_url=response.urljoin(response.css(".portrait img::attr(src)").get() or "") or None,
            bio=clean(" ".join(plain(p) for p in intro)),
        )
        for rol, org in roles:
            url = next((a.attrib["href"] for a in intro[1].css("a") if plain(a) in org), None)
            yield self.item("afiliacion", response, organizacion=org, rol=rol, url_organizacion=url)
        if len(intro) > 2:  # DERI/INSIGHT, Galway
            p = intro[2]
            t = plain(p)
            desde, hasta = re.search(r"started there in (\w+ \d{4})", t), re.search(r"left .*? in (\w+ \d{4})", t)
            deri = p.css("a")[0]
            for rol in [None, *re.findall(r"did a (PostDoc)", t)]:
                yield self.item(
                    "afiliacion",
                    response,
                    organizacion=plain(deri),
                    rol=rol,
                    desde=desde.group(1) if desde and not rol else None,
                    hasta=hasta.group(1) if hasta else None,
                    url_organizacion=deri.attrib["href"],
                )
        for a in response.xpath("//h2[.='Publications']/following-sibling::p[1]//a"):
            href = a.attrib["href"]
            rid = ORCID.search(href) or re.search(r"/rid/(\S+)$", href)
            yield self.item(
                "perfil",
                response,
                plataforma=(a.css("img::attr(alt)").get() or "").removeprefix("Aidan on ") or href,
                url_destino=href,
                identificador=rid.group(rid.lastindex or 0) if rid else None,
            )

    def _formacion(self, response: Response, intro: list, tesis: str) -> Iterator:
        # "... including a PhD which I defended in February 2011" (párrafo DERI, NUI Galway)
        t = plain(intro[2]) if len(intro) > 2 else ""
        phd = re.search(r"\b(PhD) which I defended in \w+ (\d{4})", t)
        links = intro[2].css("a") if len(intro) > 2 else []
        yield self.item(
            "formacion",
            response,
            grado=phd.group(1) if phd else "Ph.D.",
            anio=phd.group(2) if phd else None,
            institucion=plain(links[1]) if len(links) > 1 else None,
            titulo_tesis=tesis,
        )

    def _publicacion(self, response: Response, p, seccion: str) -> Iterator:
        a = p.css("a")
        t = plain(p)
        if not a or '"' not in t:
            return
        pre = t.split('"')[0]
        spans = p.xpath("./span[not(@class='me') and not(@class='sc') and not(@class='hl')]")
        venue = plain(spans[0]) if spans else None
        years = YEAR.findall(venue or "") or YEAR.findall(t)
        url = response.urljoin(a[0].attrib["href"])
        if re.search(r"\(inte?r?view\)", pre):  # "Various (inteview)": nota de prensa, no publicación
            yield self.item(
                "actividad",
                response,
                tipo_actividad="prensa",
                titulo=plain(a[0]),
                evento=venue,
                fecha=venue.split(", ")[-1] if venue else None,
                url_destino=url,
            )
            return
        yield self.item(
            "publicacion",
            response,
            titulo=plain(a[0]),
            autores=autores(pre),
            venue=venue,
            anio=years[-1] if years else None,
            tipo_publicacion=seccion,
            url_destino=url,
        )

    def _charla(self, response: Response, p, seccion: str, anio: str | None) -> dict:
        # 'Keynote "Título" at the <a>Evento</a>, fecha, lugar.' / 'Invited Talk on "Título", Lugar, fecha.'
        t = plain(p)
        q = QUOTED.search(t)
        ev = next((a for a in p.css("a") if after_at_the(a)), None)
        return self.item(
            "actividad",
            response,
            tipo_actividad=CHARLAS[seccion],
            rol=t.split(' "')[0].removesuffix(" on"),  # "Keynote" / "Invited Lecture" / "Invited Talk"
            titulo=q.group(1) if q else t,
            evento=plain(ev) if ev else None,
            fecha=anio,
            descripcion=t,
            url_destino=ev.attrib["href"] if ev else None,
        )
