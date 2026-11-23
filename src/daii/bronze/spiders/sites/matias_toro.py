"""Sitio personal de Matías Toro (una sola página): investigación, formación, publicaciones, estudiantes,
proyectos, centros y docencia (tabla de semestres dictados)."""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider, clean, texts

SITIO = "https://matiastoro.github.io/"
PERSONA = "matias-toro"
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


class MatiasToroSpider(AcademicSpider):
    name = "sitio_matias_toro"
    expect = {
        "persona": 1,
        "perfil": 3,
        "afiliacion": 2,
        "area": 2,
        "formacion": 2,
        "publicacion": 13,
        "tesis": 30,
        "proyecto": 3,
        "dictacion": 8,
    }

    async def start(self):
        if self.only in (None, PERSONA):
            yield self.page(SITIO, self.parse_home, PERSONA)

    def parse_home(self, response: Response) -> Iterator:
        intro = response.css(".masthead .intro")
        cargo = texts(intro.css(".post"))
        yield self.item(
            "persona",
            response,
            nombre=clean(" ".join(intro.css("h1.name span::text").getall())),
            cargo=cargo,
            email=(intro.css("a[href^='mailto:']::attr(href)").get() or "").removeprefix("mailto:") or None,
            oficina=texts(response.css("footer .contact > p:not([class])")),
            foto_url=response.css(".portrait img::attr(src)").get(),
            bio=texts(response.css("#research p.lead")),
        )
        for a in intro.css("ul.links a:not([href^='mailto:'])"):
            yield self.item("perfil", response, plataforma=(texts(a) or "").lower(), url_destino=a.attrib["href"])

        # "Department of Computer Science<br>Universidad de Chile · PLEIAD"
        aff = [t for t in (clean(x.strip(" ·")) for x in intro.css(".aff ::text").getall()) if t]
        if len(aff) >= 2:
            yield self.item("afiliacion", response, organizacion=", ".join(aff[:2]), rol=cargo)
        for a in intro.css(".aff a"):
            yield self.item("afiliacion", response, organizacion=texts(a), url_organizacion=a.attrib["href"])
        # Centros: "Instituto Milenio ... (IMFD)" · "2022–2025" · "Collaborating researcher"
        for li in response.xpath("//h3[@class='rail-label'][.='Centres']/../following-sibling::ul[1]/li"):
            years = YEAR.findall(texts(li.css(".side")) or "")
            hasta = years[1] if len(years) > 1 else None
            yield self.item(
                "afiliacion",
                response,
                organizacion=texts(li.css(".what")),
                rol=texts(li.css(".detail")),
                desde=years[0] if years else None,
                hasta=hasta,
            )

        for h3 in response.css("#research .tracks h3"):
            yield self.item("area", response, nombre=texts(h3))

        for li in response.css("#research .edu li"):
            # "Universidad de Chile, 2019. Thesis: <título>, advised by Éric Tanter"
            det = texts(li.css(".detail")) or ""
            m = re.match(r"(.+?),\s*(\d{4})\.\s*(?:Thesis:\s*(.+?)(?:, advised by .*)?)?$", det)
            yield self.item(
                "formacion",
                response,
                grado=texts(li.css(".what")) or texts(li.css(".code")),
                institucion=m.group(1) if m else clean(det),
                anio=m.group(2) if m else None,
                titulo_tesis=m.group(3) if m else None,
            )

        for year in response.css("#publications .year"):
            rail = texts(year.css(".rail-label")) or ""
            for pub in year.css("article.pub"):
                info = texts(pub.css(".info"))
                doi = pub.xpath(".//a[.='doi']/@href").get()
                pdf = pub.xpath(".//a[.='pdf']/@href").get()
                anio = rail if rail.isdigit() else next(iter(YEAR.findall(info or "")[-1:]), None)
                yield self.item(
                    "publicacion",
                    response,
                    titulo=texts(pub.css("h4")),
                    autores=[a.strip() for a in (texts(pub.css(".authors")) or "").split(",") if a.strip()],
                    venue=info,
                    anio=anio,
                    tipo_publicacion=None if rail.isdigit() or rail == "To appear" else rail,
                    estado=texts(pub.css(".soon")),
                    doi=doi[doi.index("10.") :] if doi and "10." in doi else None,
                    url_destino=pdf or doi,
                )

        for li in response.css("#students ul.roster li"):
            when = texts(li.css(".when")) or ""
            yield self.item(
                "tesis",
                response,
                titulo=texts(li.css(".what")),
                estudiante=texts(li.css(".who")),
                nivel=texts(li.css(".code")),
                rol=texts(li.css(".with")),
                anio=None if when.startswith("since") else (YEAR.findall(when) or [None])[0],
            )

        for li in response.xpath("//h3[@class='rail-label'][.='Grants']/../following-sibling::ul[1]/li"):
            # "Fondecyt Regular 2026, led by Eduardo Graells-Garrido"
            fuente, _, ir = (texts(li.css(".detail")) or "").partition(", led by ")
            years = YEAR.findall(fuente)
            yield self.item(
                "proyecto",
                response,
                titulo=texts(li.css(".what")),
                rol=texts(li.css(".side")),
                fuente=clean(fuente),
                investigador_responsable=clean(ir),
                anio_inicio=years[0] if years else None,
            )

        nombres = {
            texts(li.css(".code")): clean("".join(li.css(".what::text").getall()))
            for li in response.css("#teaching ul.items li")
        }
        anios = response.css("table.timetable thead th::text").getall()
        for tr in response.css("table.timetable tbody tr"):
            codigo = texts(tr.css("th"))
            for anio, td in zip(anios, tr.css("td"), strict=False):
                for i, term in enumerate(td.css(".term"), 1):
                    if "on" in term.attrib.get("class", "").split():
                        yield self.item(
                            "dictacion",
                            response,
                            codigo_curso=codigo,
                            nombre_curso=nombres.get(codigo) or codigo,
                            anio=anio,
                            semestre=f"semester {i}",  # la tabla marca semestre 1/2 de cada año
                        )
        yield from self.related(response)
