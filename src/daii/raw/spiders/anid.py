"""Portal del Investigador de ANID (investigadores.anid.cl/es/public_search/researcher?id=<n>): registro nacional.

HTML renderizado en servidor. La ficha trae tres pestañas en el mismo HTML:
- Currículo (#home): nombre/cargo/institución, Líneas de Investigación, Educación, Experiencia Académica y
  Profesional, Premios y Distinciones. "Formación de Capital Humano" y "Difusión y Transferencia" son texto libre
  sin estructura: no se parsean (quedan en el HTML guardado).
- Producción (#messages): lista agrupada por tipo (Article, ConferencePaper, Proyecto...) con link a cada obra
  `/es/public_search/work?id=<n>`. Se sigue cada obra porque solo ahí está el DOI (publicaciones) y el año de
  inicio/término y financiamiento (proyectos). Los proyectos no traen código ni rol.
- Colaboraciones (#colab): fichas de otros investigadores ANID; se registran como `link` sin seguirlas.

robots.txt: `User-agent: *` con `Allow: /` y Content-Signal `ai-train=no`. Este spider extrae de forma
determinista para un dashboard interno (no entrena ni alimenta modelos), así que cumple la señal.
"""

import re
from collections.abc import Iterator

from scrapy.http import Response

from daii.raw.spiders.base import AcademicSpider, clean, texts

ANIO = re.compile(r"\b(\d{4})\b")
DESDE_HASTA = re.compile(r"(\d{4})\s*-\s*(.+)")


def _anio(text: str | None) -> int | None:
    return int(m.group(1)) if text and (m := ANIO.search(text)) else None


class AnidSpider(AcademicSpider):
    name = "anid"
    expect = {"persona": 1, "formacion": 1, "afiliacion": 6, "publicacion": 20, "proyecto": 1, "link": 5}

    async def start(self):
        for p in self.personas("anid"):
            yield self.page(p["perfiles"]["anid"], self.parse, p["slug"])

    def parse(self, response: Response) -> Iterator:
        foto = response.css(".profile-picture img::attr(src)").get()
        cargo = texts(response.css(".col-sm-6 h3 + p strong"))
        institucion = clean(response.css(".col-sm-6 h3 ~ p:nth-of-type(2)::text").get())
        yield self.item(
            "persona",
            response,
            nombre=texts(response.css(".col-sm-6 h3 strong")),
            cargo=cargo,
            # man.jpg/woman.jpg son el avatar genérico del portal
            foto_url=None if not foto or "/images/" in foto else response.urljoin(foto),
        )
        if institucion:
            yield self.item("afiliacion", response, organizacion=institucion, rol=cargo)

        for head in response.css("#home .widget-header"):
            seccion = texts(head.css("h4"))
            body = head.xpath("following-sibling::*[not(self::br)][1]")
            if seccion == "Líneas de Investigación":
                for nombre in (texts(body) or "").split(","):
                    if nombre := clean(nombre):
                        yield self.item("area", response, nombre=nombre)
            elif seccion == "Educación":
                for h5 in body.css("li h5"):
                    pais = clean((h5.css("small::text").get() or "").rsplit(",", 1)[0])
                    inst = texts(h5.css("span"))
                    yield self.item(
                        "formacion",
                        response,
                        grado=texts(h5.css("strong")),
                        institucion=", ".join(x for x in (inst, pais) if x) or None,
                        anio=_anio(h5.css("small::text").get()),
                    )
            elif seccion in ("Experiencia Académica", "Experiencia Profesional"):
                for li in body.css("li"):
                    ps = [texts(p) for p in li.css("div > p")]
                    fechas = texts(li.css("div p strong")) or ""
                    m = DESDE_HASTA.match(fechas)
                    hasta = m and m.group(2).strip()
                    # [institución, facultad?, ciudad, fechas]: la facultad solo viene en Experiencia Académica
                    org = ", ".join(x for x in [texts(li.css("span.text-warning")), *ps[1:-2]] if x)
                    jornada = texts(li.css("h5 small"))
                    yield self.item(
                        "afiliacion",
                        response,
                        organizacion=org,
                        rol=", ".join(x for x in (texts(li.css("h5 strong")), jornada) if x),
                        desde=m and m.group(1),
                        hasta=None if hasta == "A la fecha" else hasta,
                    )
            elif seccion == "Premios y Distinciones":
                for li in body.css("li"):
                    yield self.item(
                        "distincion",
                        response,
                        nombre=texts(li.css("h5 strong")),
                        otorgante=texts(li.css("span.text-warning")),
                        anio=_anio(texts(li.css("small"))),
                    )

        for href in response.css("#messages a::attr(href)").getall():
            yield self.page(response.urljoin(href), self.parse_work, response.meta["persona"])

        # Colaboradores: otras fichas del mismo portal; se registran pero no se siguen.
        for a in response.css("#colab h5 a[href]"):
            url = response.urljoin(a.attrib["href"])
            if url != response.url:
                yield self.item("link", response, url_destino=url, texto=texts(a), seguido=False)

        # Solo la pestaña Currículo: fuera de ella hay menú, obras (ya pedidas) y colaboradores (arriba).
        yield from self.related(response, region="#home")

    def parse_work(self, response: Response) -> Iterator:
        art = response.css(".article")
        meta = {texts(tr.css("td:first-child")): texts(tr.css("td:nth-child(2)")) for tr in art.css("#metadata tr")}
        tipo = texts(art.css(".metadata .label-info"))
        titulo = texts(art.css(".article > h3"))
        anio = _anio(texts(art.css(".metadata")))
        ident = response.url.rsplit("id=", 1)[-1]
        if tipo == "Proyecto":
            inicio, _, fin = (meta.get("Año de Inicio/Término:") or "").partition("-")
            yield self.item(
                "proyecto",
                response,
                titulo=titulo,
                fuente=meta.get("Financiamiento/Sponsor:"),
                anio_inicio=_anio(inicio) or anio,
                anio_fin=_anio(fin),
            )
        else:
            indexacion = ", ".join(texts(s) or "" for s in art.css(".metadata .label:not(.label-info)"))
            autores_txt = texts(art.css(".author")) or ""
            partes = [a for x in autores_txt.split(";") if (a := clean(x))]
            # "Fontbona, Joaquin; Rios, Gonzalo" se separa; "Fontbona; J.; Rios; G." usa ";" también entre
            # apellido e inicial: ambiguo, se deja el texto entero.
            autores = partes if all(" " in a or "," in a for a in partes) else [autores_txt] if autores_txt else []
            yield self.item(
                "publicacion",
                response,
                titulo=titulo,
                anio=anio,
                tipo_publicacion=tipo,
                venue=meta.get("Título de la Revista:"),
                autores=autores,
                doi=meta.get("DOI:"),
                ids={"anid": ident} | ({"indexacion": indexacion} if indexacion else {}),
            )
        yield from self.related(response, region=".article")
