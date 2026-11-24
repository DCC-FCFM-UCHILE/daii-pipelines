"""Perfil y publicaciones del sitio personal de Marcel Clerc."""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, anios, autores, clean, plain, texts

PERSONA = "marcel-clerc"
SITIO = "https://www.cec.uchile.cl/~mclerc/"
PERFIL = SITIO + "DatosPersonales.html"
PUBLICACIONES = SITIO + "Publicaciones.html"

CITA = re.compile(r"""^\d+\s*\.\s*(.*?)["“](.+?)(?:["”]|'')""", re.S)
DOI = re.compile(r"10\.\d{4,}/[^?#\s]+")
COAUTORES = re.compile(r"^\(with\s+([^)]*)\)\s*[,.; ]*", re.I)
VOLUMEN = re.compile(r"\s*,?\s*\d+(?=\s*[,.(])")


class MarcelClercSpider(AcademicSpider):
    name = "sitio_marcel_clerc"
    expect = {"persona": 1, "perfil": 3, "publicacion": 100}

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(PERFIL, self.parse, PERSONA, guardar=False)
            yield self.page(PUBLICACIONES, self.parse_publicaciones, PERSONA)

    def parse(self, response: Response) -> Iterator:
        nombre = response.xpath('//td[b][starts-with(normalize-space(.), "Dr. Marcel")][1]')
        cargo = response.xpath('//p[starts-with(normalize-space(.), "Full Professor of")][1]')
        if nombre:
            yield self.item(
                "persona",
                response,
                nombre=texts(nombre),
                cargo=plain(cargo),
                foto_url=response.css('img[src="images/marcel_professional.jpg"]::attr(src)').get(),
            )
        for plataforma, dominio in (
            ("scholar", "scholar.google.com"),
            ("wos", "webofscience.com"),
            ("scopus", "scopus.com"),
        ):
            if href := response.css(f'a[href*="{dominio}"]::attr(href)').get():
                yield self.item("perfil", response, plataforma=plataforma, url_destino=href)
        yield from self.related(response)

    def parse_publicaciones(self, response: Response) -> Iterator:
        tipo = texts(response.css("p.centrado b")[:1])
        for p in response.css('td[width="87%"] div[align="left"] p'):
            cita = "\n".join(
                clean(parte) or ""
                for parte in "".join(
                    x.get() if isinstance(x.root, str) else "\x1f" for x in p.xpath(".//text()|.//br")
                ).split("\x1f")
            )
            if not (m := CITA.match(cita)):
                continue
            prefijo, titulo = m.groups()
            resto = cita[m.end() :].strip(" ,\n")
            primera_linea, _, revista = resto.partition("\n")
            coautores = COAUTORES.match(primera_linea)
            if coautores:
                nombres, revista = coautores[1], resto[coautores.end() :]
            else:
                nombres = primera_linea.removeprefix("(with ") if revista else ""
                # shortcut: sin salto ni enlace de revista, dejar autores y revista vacíos.
                if not revista and (enlace := plain(p.css("a[href]")[:1])) and enlace in resto:
                    nombres, _, sufijo = resto.partition(enlace)
                    revista = enlace + sufijo
            ys = anios(DOI.sub("", resto))
            links = p.css("a[href]::attr(href)").getall()
            doi = next((d[0].rstrip(".,;") for fuente in (*links, resto) if (d := DOI.search(fuente))), None)
            revista = re.split(r",?\s+DOI:", revista, maxsplit=1, flags=re.I)[0]
            pdf = p.xpath("ancestor::td[1]/following-sibling::td[1]//a[img]/@href").get()
            yield self.item(
                "publicacion",
                response,
                titulo=clean(f"{prefijo}{titulo}".strip(" ,")),
                tipo_publicacion=tipo,
                anio=ys[-1] if ys else None,
                autores=[a for a in autores(nombres.strip().replace(" & ", " and ")) if a.strip(" .")],
                venue=clean(VOLUMEN.split(revista, maxsplit=1)[0].rstrip(" ,")) if revista else None,
                doi=doi,
                url_destino=next(iter(links), pdf),
            )
        yield from self.related(response)
