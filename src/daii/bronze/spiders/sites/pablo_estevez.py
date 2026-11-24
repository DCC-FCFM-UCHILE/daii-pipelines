"""Sitio histórico de Pablo Estévez en el CEC."""

import re

from scrapy.http import HtmlResponse

from daii.bronze.spiders.base import AcademicSpider, anio, anios, autores, clean, email, texts

PERSONA = "pablo-estevez"
CITA = re.compile(r'^\[\w+\]\s*(.+?)\s*"([^"]+)"\s*,?\s*(.*)')
PROYECTO = re.compile(r"^(.+?) of (\w+) project (\w+): (.+?) \((\d{4}-\d{4})\)")


class PabloEstevezSpider(AcademicSpider):
    name = "sitio_pablo_estevez"
    expect = {"persona": 1, "formacion": 4, "publicacion": 25, "proyecto": 4}

    async def start(self):
        for p in self.personas("sitio"):
            if p["slug"] == PERSONA:
                url = p["perfiles"]["sitio"]
                yield self.page(url, self.parse, PERSONA)
                yield self.page(url + "info.html", self.parse_info, PERSONA)
                yield self.page(url + "public.html", self.parse_publicaciones, PERSONA)
                yield self.page(url + "projects.html", self.parse_proyectos, PERSONA)

    def parse(self, response):
        yield self.item(
            "persona",
            response,
            nombre=texts(response.css("h1:nth-of-type(2)")),
            cargo=texts(response.css("body > font > b:first-of-type")),
            foto_url=response.css("img::attr(src)").get(),
            email=email(response.css("a[href^='mailto:']::attr(href)").get()),
        )
        yield from self.related(response)

    def parse_info(self, response):
        educacion = response.xpath("//p[normalize-space(.)='Education']/following-sibling::p[1]/b")
        grados = educacion.xpath("text()[following-sibling::a]").getall()
        for grado, inst in zip(grados, educacion.css("a"), strict=False):
            fecha = inst.xpath("following-sibling::text()[1]").get()
            yield self.item(
                "formacion", response, grado=clean(grado.strip().rstrip(",")), institucion=texts(inst), anio=anio(fecha)
            )
        yield from self.related(response)

    def parse_publicaciones(self, response):
        # Página antigua en ISO-8859-1, sin declaración en el HTML.
        response = HtmlResponse(url=response.url, body=response.body, encoding="latin-1", request=response.request)
        for tabla in response.css("table"):
            tipo = texts(tabla.css("td > p:first-of-type"))
            for p in tabla.css("p"):
                if m := CITA.match(texts(p) or ""):
                    yield self.item(
                        "publicacion",
                        response,
                        autores=autores(m[1]),
                        titulo=m[2],
                        anio=anio(m[3]),
                        tipo_publicacion=tipo,
                        url_destino=p.css("a::attr(href)").get(),
                    )
        yield from self.related(response)

    def parse_proyectos(self, response):
        for p in response.css("td > p"):
            if m := PROYECTO.match(texts(p) or ""):
                inicio, fin = anios(m[5])
                yield self.item(
                    "proyecto",
                    response,
                    rol=m[1],
                    fuente=m[2],
                    codigo=m[3],
                    titulo=m[4],
                    anio_inicio=inicio,
                    anio_fin=fin,
                )
        yield from self.related(response)
