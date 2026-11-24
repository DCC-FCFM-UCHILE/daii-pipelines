"""Portafolio Académico U. de Chile (portafolio-academico.uchile.cl/perfil/<id>-<nombre>).

Fuente oficial: nombramientos, grados, cargos, docencia (U-Campus), publicaciones con indexación, proyectos,
tesis (biblioteca), libros y vinculación con el medio. Es una SPA: se renderiza con Playwright y se pagina
haciendo clic en cada tabla, como un visitante. Su API interna exige una credencial y responde ofuscada:
no se usa directamente.
"""

import re
from collections.abc import AsyncIterator, Iterator

from parsel import Selector  # base de scrapy.Selector; response.css() devuelve estos
from scrapy import Request
from scrapy.http import Response
from scrapy_playwright.page import PageMethod

from daii.bronze.middlewares import archive_observation
from daii.bronze.spiders.base import AcademicSpider, anio, clean, redact, texts
from daii.log import logger

PANES = [
    "informacion-personal",
    "docencia",
    "publicaciones",
    "proyectos-investigacion",
    "memorias-tesis",
    "libros-capitulos",
    "extensiones",
]
PAGINA = re.compile(r"Página (\d+) de (\d+)")
# Tipos de "Vinculación con el medio" del portafolio → vocabulario de items.TipoActividad.
TIPO_EXTENSION = {
    "Divulgaciones": "divulgacion",
    "Noticias": "prensa",
    "Prestaciones": "asesoria",
    "Proyectos": "vinculacion",
}
MAX_PAGES = 60  # tope de seguridad por tabla
WAIT_MS = 120_000  # las esperas de página usan 30 s por defecto; perfiles grandes con carga paralela tardan más


def _rows(table: Selector) -> Iterator[tuple[dict[str, str | None], Selector]]:
    heads = [texts(th) or "" for th in table.css("thead th")]
    for tr in table.css("tbody tr"):
        tds = tr.css("td")
        yield {h: texts(td) for h, td in zip(heads, tds, strict=False)}, tr


class PortafolioSpider(AcademicSpider):
    name = "portafolio"
    expect = {"persona": 1, "formacion": 1, "dictacion": 5}
    # Perfiles grandes (cientos de cursos) tardan en quedar sin actividad de red.
    custom_settings = {"DOWNLOAD_TIMEOUT": 180, "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 120_000}

    async def start(self):
        for p in self.personas("portafolio"):
            yield self.page(
                p["perfiles"]["portafolio"],
                self.parse,
                p["slug"],
                playwright=True,
                playwright_include_page=True,
                playwright_page_methods=[
                    # "attached", no "visible": si la pestaña activa es la bio, las tablas existen pero ocultas
                    PageMethod("wait_for_selector", "div[role=tabpanel] table", state="attached", timeout=WAIT_MS),
                    # las secciones cargan por separado
                    PageMethod("wait_for_load_state", "networkidle", timeout=WAIT_MS),
                ],
            )

    async def parse(self, response: Response) -> AsyncIterator[dict | Request]:
        """Recorre todas las páginas de cada tabla (clic en '>') y luego parsea cada fragmento."""
        page = response.meta["playwright_page"]
        fragments: list[tuple[str, Selector, str]] = []
        try:
            for pane in PANES:
                coverage = f"daii/coverage/{response.meta['persona']}/{pane}"
                try:
                    if not await page.locator(f"#justify-tab-example-tab-{pane}").count():
                        self.crawler.stats.set_value(coverage, "sin_pestania")
                        continue
                    await self._paginar(page, pane, response, fragments)
                    self.crawler.stats.set_value(coverage, "completa")
                except Exception:  # conserva las páginas ya capturadas para diagnóstico
                    logger.bind(evento="pestania_incompleta", persona=response.meta["persona"], url=response.url).opt(
                        exception=True
                    ).error(f"falló la paginación de {pane}")
                    self.crawler.stats.inc_value("daii/page_error")
                    self.crawler.stats.set_value(coverage, "incompleta")
        finally:
            await page.close()

        for item in self.parse_static(response, extra=fragments):
            yield item

    async def _paginar(self, page, pane: str, response: Response, fragments: list[tuple[str, Selector, str]]) -> None:
        """Páginas 2..n de cada tabla de una pestaña (clic en '>')."""
        root = f"#justify-tab-example-tabpane-{pane}"
        await page.click(f"#justify-tab-example-tab-{pane}")
        panel_count = await page.locator(root).count()
        table_count = await page.locator(f"{root} table").count()
        paginator_count = await page.locator(f"{root} [class*=paginadorTexto]").count()
        if panel_count != 1 or table_count != paginator_count:
            raise ValueError(f"{pane}: panel o paginadores irreconocibles")
        for i in range(paginator_count):
            pag = page.locator(f"{root} [class*=paginadorTexto]").nth(i)
            for _ in range(MAX_PAGES):
                m = PAGINA.search(await pag.inner_text())
                if not m:
                    raise ValueError(f"{pane}: contador de páginas irreconocible")
                if int(m.group(1)) >= int(m.group(2)):
                    break
                rows = page.locator(f"{root} table").nth(i).locator("tbody")
                before = await rows.inner_text()
                await pag.locator("label", has_text=re.compile(r"^\s*>\s*$")).click()
                # el contador "Página n" cambia antes que las filas: esperar a que cambien las filas
                for _ in range(50):
                    await page.wait_for_timeout(200)
                    if await rows.inner_text() != before:
                        break
                else:
                    raise TimeoutError(f"{pane}: la tabla {i} no cambió tras pasar de página")
                await page.wait_for_timeout(300)  # amabilidad con el servidor
                html = await page.inner_html(root)
                # solo la tabla i-ésima de esta página nueva (las demás tablas del panel no cambiaron)
                table = Selector(text=html).css("table")[i]
                observation = self._archive_table(response, pane, i, int(m.group(1)) + 1, table)
                fragments.append((pane, table, observation))
            else:
                m = PAGINA.search(await pag.inner_text())
                if not m or int(m.group(1)) < int(m.group(2)):
                    raise ValueError(f"{pane}: quedaron páginas sin leer")

    def _archive_table(self, response: Response, pane: str, table_index: int, page_number: int, table: Selector) -> str:
        return archive_observation(
            self,
            {
                "url": redact(response.url),
                "persona": response.meta["persona"],
                "modo": "playwright_fragmento",
                "status": response.status,
                "content_type": "text/html; charset=utf-8",
                "pestania": pane,
                "tabla": table_index,
                "pagina": page_number,
                "observacion_padre": response.meta.get("observacion_id"),
            },
            table.get().encode(),
        )

    def parse_static(
        self, response: Response, extra: list[tuple[str, Selector, str]] | None = None
    ) -> Iterator[dict | Request]:
        """Parsea la página inicial (página 1 de cada tabla) + fragmentos de páginas siguientes."""
        yield self.item(
            "persona",
            response,
            nombre=clean(response.css("img[class*=academicImag]::attr(alt)").get()) or "",
            email=next((t for t in response.css("[class*=email]::text").getall() if "@" in t), None),
            telefono=clean(response.css("[class*=email][href^='tel:']::attr(href)").get("").removeprefix("tel:"))
            or None,
            bio=texts(response.css("#justify-tab-example-tabpane-perfil-academico")),  # pestaña opcional
        )
        for nb in response.css("[class*=nombramientoCont]"):
            d = [texts(x) for x in nb.css("[class*=nombramientoDetail]")]
            if d:
                yield self.item(
                    "afiliacion",
                    response,
                    organizacion=d[2] if len(d) > 2 else (d[-1] or ""),
                    rol=" · ".join(x for x in [d[0], *d[1:2], *d[4:]] if x),
                )

        tables = [
            (p.attrib["id"].rsplit("-tabpane-", 1)[1], t)
            for p in response.css("div[role=tabpanel]")
            for t in p.css("table")
        ]
        for pane, table in tables:
            yield from self._table(pane, table, response)
        for pane, table, observation in extra or []:
            for item in self._table(pane, table, response):
                yield item | {"observacion_id": observation}

        yield from self.related(response, region=".tab-content")

    def _table(self, pane: str, table: Selector, response: Response) -> Iterator[dict]:
        heads = " ".join(texts(th) or "" for th in table.css("thead th"))
        for r, tr in _rows(table):
            href = next((h for h in tr.css("a::attr(href)").getall() if h != "#"), None)
            if pane == "informacion-personal" and "Grado" in heads:
                yield self.item(
                    "formacion",
                    response,
                    grado=r.get("Grado / Título") or "",
                    institucion=r.get("Institución"),
                    anio=anio(r.get("Fecha")),
                )
            elif pane == "informacion-personal" and "Cargo" in heads:
                yield self.item(
                    "afiliacion",
                    response,
                    organizacion=" / ".join(x for x in [r.get("Organismo"), r.get("Departamento")] if x),
                    rol=r.get("Cargo"),
                    desde=r.get("Inicio"),
                    hasta=None if r.get("Término") in (None, "-") else r.get("Término"),
                )
            elif pane == "docencia":
                yield self.item(
                    "dictacion",
                    response,
                    nombre_curso=r.get("Nombre de asignatura") or "",
                    codigo_curso=r.get("Código"),
                    anio=r.get("Año"),
                    semestre=r.get("Periodo"),
                    rol=" · ".join(x for x in [r.get("Rol"), r.get("Nivel")] if x),
                    institucion=r.get("Unidad Académica"),
                )
            elif pane == "publicaciones":
                yield self.item(
                    "publicacion",
                    response,
                    titulo=r.get("Publicación") or "",
                    anio=r.get("Año"),
                    venue=r.get("Título revista"),
                    tipo_publicacion="revista",
                    doi=href if href and "doi.org" in href else None,  # crudo: silver normaliza
                    url_destino=href,
                    ids={"indexacion": r.get("Indexación")} if r.get("Indexación") else {},
                )
            elif pane == "libros-capitulos":
                yield self.item(
                    "publicacion",
                    response,
                    titulo=r.get("Título") or "",
                    anio=r.get("Año"),
                    venue=r.get("Editorial"),
                    tipo_publicacion="libro o capítulo",
                    doi=href if href and "doi.org" in href else None,  # crudo: silver normaliza
                    url_destino=href,
                )
            elif pane == "proyectos-investigacion":
                yield self.item(
                    "proyecto",
                    response,
                    titulo=r.get("Título") or "",
                    codigo=r.get("Código"),
                    fuente=" · ".join(x for x in [r.get("Fuente"), r.get("Programa")] if x),
                    anio_inicio=anio(r.get("Inicio")),
                    anio_fin=anio(r.get("Fin")),
                    investigador_responsable=r.get("Investigador/a principal | Coinvestigadores/as"),
                )
            elif pane == "memorias-tesis":
                yield self.item(
                    "tesis",
                    response,
                    titulo=r.get("Titulo"),
                    anio=r.get("Año"),
                    estudiante=r.get("Autores/as"),
                    rol="guía",
                    programa=r.get("Unidad Académica"),
                    url_destino=href,
                )
            elif pane == "extensiones":
                yield self.item(
                    "actividad",
                    response,
                    tipo_actividad=TIPO_EXTENSION.get(r.get("Tipo") or "", "extension"),
                    titulo=r.get("Iniciativa") or "",
                    descripcion=" · ".join(x for x in [r.get("Tipo"), r.get("Subtipo")] if x) or None,
                    fecha=" - ".join(x for x in [r.get("Fecha inicio"), r.get("Fecha fin")] if x and "9999" not in x),
                    rol=r.get("Rol"),
                    url_destino=href,
                )
