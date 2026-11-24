"""Ficha del Departamento de Astronomía de Leonardo Bronfman."""

import re

from daii.bronze.spiders.base import AcademicSpider, anio, clean, email, texts

PERSONA = "leonardo-bronfman"
CITAS = re.compile(r"(\d{4})\.?\s*(?:«([^»]+)»|»([^«]+)«|“([^”]+)”|([^;]+?)\s+ApJ\s+\d+,\s*\d+;)")


class LeonardoBronfmanSpider(AcademicSpider):
    name = "sitio_leonardo_bronfman"
    expect = {"persona": 1, "formacion": 2, "area": 2, "distincion": 2, "publicacion": 3}

    async def start(self):
        for p in self.personas("sitio"):
            if p["slug"] == PERSONA:
                yield self.page(p["perfiles"]["sitio"], self.parse, PERSONA)

    def parse(self, response):
        bio = response.xpath("//h2[normalize-space()='Biografía']/following-sibling::div[1]")
        cuerpo, _, premios = (texts(bio) or "").partition("Premios y distinciones:")
        yield self.item(
            "persona",
            response,
            nombre=texts(response.css(".nombre-persona")),
            cargo=texts(response.css(".cargo-persona")),
            email=email(response.css(".carg-persona a[href^='mailto:']::attr(href)").get()),
            foto_url=response.css(".foto-persona img::attr(src)").get(),
            bio=clean(cuerpo),
        )

        for grado, year, inst in re.findall(
            r"([^,]+),\s*(\d{4}),\s*([^.]+)\.", texts(response.css(".universidad")) or ""
        ):
            yield self.item("formacion", response, grado=grado.strip(), anio=int(year), institucion=inst.strip())

        areas = (texts(response.css(".interses")) or "").partition(":")[2]
        for area in areas.rstrip(".").split(","):
            if nombre := clean(area):
                yield self.item("area", response, nombre=nombre)

        if premios:
            for linea in bio.xpath("text()").getall():
                if re.match(r"\s*(Premio |Cátedra |Medalla )", linea) and (year := anio(linea)):
                    nombre = re.sub(r"[,\s]+\d{4}\.?\s*$", "", linea)
                    yield self.item("distincion", response, nombre=clean(nombre), anio=year)

        for entrada in response.css(".cuadro-b1 .contenido-seccion li"):
            cita = texts(entrada) or ""
            for year, *titulos in CITAS.findall(cita):
                titulo = next(t for t in titulos if t)
                yield self.item("publicacion", response, titulo=clean(titulo), anio=int(year))

        yield from self.related(response, region=".contenedor-biografia")
