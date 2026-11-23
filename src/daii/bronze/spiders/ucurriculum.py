"""Fichas institucionales FCFM con el template `fcfm_ucurriculum` (p. ej. dcc.uchile.cl/nosotros/academico/<slug>/).

Una ficha trae: cargo, grados, cursos por semestre (7 años), memorias/tesis guiadas, publicaciones y proyectos.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, texts

YEAR_END = re.compile(r",\s*(\d{4})\s*$")
SEMESTRE = re.compile(r"(\d{4})\s+(Otoño|Primavera|Verano|Invierno|Anual)")


class UcurriculumSpider(AcademicSpider):
    name = "ucurriculum"
    expect = {"persona": 1, "formacion": 1, "dictacion": 1}

    async def start(self):
        for p in self.personas("ucurriculum"):
            yield self.page(p["perfiles"]["ucurriculum"], self.parse, p["slug"])

    def parse(self, response: Response) -> Iterator:
        box = response.css(".academico")
        yield self.item(
            "persona",
            response,
            nombre=texts(box.css(".nombre")) or texts(response.css(".quien h2")),
            cargo=texts(box.css(".cargo")),
            email=(box.css(".email a::attr(href)").get() or "").removeprefix("mailto:") or None,
            telefono=box.css(".anexo a::text").get(),
            oficina=box.css(".oficina::attr(title)").get(),
            foto_url=box.css("img.img-fluid::attr(src)").get(),
        )
        for a in box.css(".social a"):
            yield self.item(
                "perfil", response, plataforma=a.css("img::attr(alt)").get("").lower(), url_destino=a.attrib["href"]
            )

        cv = response.css(".fcfm_ucurriculum")
        for li in cv.css("#cronologia li"):
            # "Académico - Profesor Asociado (DCC/IDIA)"
            m = re.search(r"-\s*(.+?)\s*\((.+)\)", texts(li) or "")
            if m:
                for unidad in m.group(2).split("/"):
                    yield self.item("afiliacion", response, organizacion=unidad, rol=m.group(1))

        for li in cv.css("#estudios li"):
            grado, _, inst = (clean(li.xpath("text()").get()) or "").partition(" - ")
            anio = li.css("em::text").get()
            yield self.item("formacion", response, grado=grado, institucion=clean(inst), anio=anio)

        for li in cv.css("#cursos_dictados li"):
            nombre = clean(li.css("a::text").get()) or clean(li.xpath("text()").get()) or ""
            codigo, _, nombre_curso = nombre.partition(" ")
            for anio, sem in SEMESTRE.findall(li.css("em::text").get("")):
                yield self.item(
                    "dictacion",
                    response,
                    codigo_curso=codigo,
                    nombre_curso=nombre_curso,
                    anio=anio,
                    semestre=sem,
                    url_curso=li.css("a::attr(href)").get(),
                )

        rol = None
        for el in cv.css("#memorias > *"):
            if el.root.tag == "p":
                rol = texts(el)  # "Participación como Profesor Guía"
            for li in el.css("li"):
                t = texts(li) or ""
                m = YEAR_END.search(t)
                yield self.item(
                    "tesis",
                    response,
                    titulo=(t[: m.start()] if m else t).strip(" “”\"'"),
                    anio=m.group(1) if m else None,
                    rol=rol,
                )

        for h4 in cv.css("#investigacion h4"):
            seccion = texts(h4) or ""
            for li in h4.xpath("following-sibling::ul[1]/li"):
                titulo = clean(li.xpath("text()").get())
                meta = [p.strip() for p in (texts(li.css("em")) or "").split(",")]
                if not titulo:
                    continue
                if seccion.startswith("Publicaciones"):
                    m = YEAR_END.search(", ".join(meta))
                    yield self.item(
                        "publicacion",
                        response,
                        titulo=titulo,
                        venue=", ".join(meta[:-1]) if m else ", ".join(meta) or None,
                        anio=m.group(1) if m else None,
                    )
                elif seccion.startswith("Proyectos"):
                    # "Fondecyt_Anid, 1240954, 2024 - 2028"  (la fuente puede traer comas; se parsea desde la derecha)
                    years = re.findall(r"\d{4}", meta[-1]) if meta else []
                    rest = meta[:-1] if years else meta
                    yield self.item(
                        "proyecto",
                        response,
                        titulo=titulo.strip(" “”\"'"),
                        fuente=", ".join(rest[:-1]) if len(rest) > 1 else (rest[0] if rest else None),
                        codigo=rest[-1] if len(rest) > 1 else None,
                        anio_inicio=years[0] if years else None,
                        anio_fin=years[-1] if years else None,
                    )

        yield from self.related(response, region=".fcfm_ucurriculum")
