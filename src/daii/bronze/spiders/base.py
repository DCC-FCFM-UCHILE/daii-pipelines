"""Clase base de todos los spiders: semillas por persona, ítems con metadatos y links relacionados."""

import io
import re
import unicodedata
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urlparse

import scrapy
from pypdf import PdfReader
from scrapy.http import Response, TextResponse

from daii.config import academicos, con_perfil, whitelist

SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".css", ".js", ".mp4", ".pptx", ".docx", ".xml")


def clean(text: str | None) -> str | None:
    """Colapsa espacios; devuelve None si queda vacío."""
    text = " ".join((text or "").split())
    return text or None


ANIO = re.compile(r"\b(?:19|20)\d{2}\b")
URL_FIELDS = ("url_destino", "url_organizacion", "url_curso", "foto_url")
LATEX_ACENTO = re.compile(r"([´˜¨`ˆ¸])\s?([A-Za-zı])")
LATEX_COMB = {"´": "\u0301", "˜": "\u0303", "¨": "\u0308", "`": "\u0300", "ˆ": "\u0302", "¸": "\u0327"}


def anios(text: str | None) -> list[int]:
    """Todos los años (19xx/20xx) como palabra completa; no confunde años con trozos de códigos como 1240954."""
    return [int(a) for a in ANIO.findall(text or "")]


def anio(text: str | None) -> int | None:
    """Primer año del texto (usar `anios(t)[-1]` para el último)."""
    return (anios(text) or [None])[0]


def plain(sel) -> str | None:
    """Texto de un nodo SIN insertar espacios entre hijos (para editores que parten palabras en <span>)."""
    return clean("".join(sel.css("::text").getall()))


def abs_url(response: Response, href: str | None) -> str | None:
    """URL absoluta o None (ojo: response.urljoin("") devuelve la URL de la página, no vacío)."""
    return response.urljoin(href) if href else None


def pdf_texto(response: Response, **kw: Any) -> str:
    """Texto de un PDF (kw → PageObject.extract_text, p. ej. extraction_mode="layout")."""
    return "\n".join(p.extract_text(**kw) or "" for p in PdfReader(io.BytesIO(response.body)).pages)


def latex_acentos(text: str) -> str:
    """pypdf deja el acento LaTeX antes de la letra ("F¨orster", "Rodr´ıguez"): recomponer."""
    text = LATEX_ACENTO.sub(lambda m: m[2].replace("ı", "i") + LATEX_COMB[m[1]], text)
    return unicodedata.normalize("NFC", text.replace("ı", "i"))


def email(href: str | None) -> str | None:
    """ "mailto:x@y.cl" → "x@y.cl"."""
    return (href or "").removeprefix("mailto:").strip() or None


def redact(url: str) -> str:
    """Quita credenciales de query strings antes de persistir una URL (p. ej. api_key de OpenAlex)."""
    return re.sub(r"([?&])api_key=[^&]*&?", r"\1", url).rstrip("?&")


def texts(sel) -> str | None:
    """Texto visible de un selector (incluye hijos), limpio."""
    return clean(" ".join(sel.css("::text").getall()))


# Iniciales con o sin punto ("F.", "Ch.", "R", "J.-L."); la forma alternada evita fusionar "F. Bravo, J. Li".
INITIALS = re.compile(r"^(?:[A-ZÁÉÍÓÚÑ](?:[a-z]\.|\.?)\s?-?)+$")


def autores(s: str) -> list[str]:
    """ "Zhang, B., Orchard, M., and Liang, S." o "Baldo, L.; Orchard, M." → ["Zhang, B.", ...]."""
    out: list[str] = []
    for tok in re.split(r"\s*[;,]\s*(?:and\s+)?|\s+and\s+", s.strip(" ,;")):
        if INITIALS.match(tok) and out and "," not in out[-1]:
            out[-1] += ", " + tok
        elif tok:
            out.append(tok)
    return out


class AcademicSpider(scrapy.Spider):
    """Base para spiders de académicos.

    - `expect`: mínimo de ítems por tipo en un run completo; quality falla si no se alcanza.
    - `-a persona=<slug>` restringe el run a una persona (útil para depurar).
    - Usar `self.page(...)` para pedir páginas propias y `self.related(response)` para registrar
      links y seguir (profundidad 1) los que están en la lista blanca.
    """

    expect: ClassVar[dict[str, int]] = {}

    def __init__(self, *args: Any, persona: str | None = None, run_id: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.run_id = run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.only = persona
        self.handled: set[str] = set()

    async def start(self):
        """Por defecto (spiders de plataforma): una página por persona con `perfiles[<name>]` en config."""
        for p in self.personas(self.name):
            yield self.page(p["perfiles"][self.name], self.parse, p["slug"])

    def personas(self, plataforma: str | None = None) -> list[dict]:
        ps = con_perfil(plataforma) if plataforma else academicos()
        return [p for p in ps if not self.only or p["slug"] == self.only]

    def page(self, url: str, callback, persona: str, **meta: Any) -> scrapy.Request:
        self.handled.add(url)
        # dont_filter: si related() de otra página ya pidió esta URL como `pagina`, igual se parsea aquí.
        return scrapy.Request(
            url, callback=callback, errback=self._page_failed, dont_filter=True, meta={"persona": persona, **meta}
        )

    async def _page_failed(self, failure) -> None:
        """Una página propia no se pudo bajar: quality lo reporta como warn."""
        if page := failure.request.meta.get("playwright_page"):  # con playwright_include_page la cierra el spider
            await page.close()
        self.crawler.stats.inc_value("daii/page_error")
        self.logger.error("página propia falló: %s (%s)", failure.request.url, failure.value)

    def _related_failed(self, failure) -> None:
        """Links externos caídos son normales en sitios académicos: se cuentan, no se alertan."""
        self.crawler.stats.inc_value("daii/related_error")
        self.logger.info("link relacionado falló: %s (%s)", failure.request.url, failure.value)

    def item(self, tipo: str, response: Response, **fields: Any) -> dict:
        for k in URL_FIELDS:  # hrefs relativos → absolutos, en un solo lugar
            if fields.get(k):
                fields[k] = response.urljoin(fields[k])
        return {
            "tipo": tipo,
            "persona": response.meta["persona"],
            "url": redact(response.url),
            "spider": self.name,
            "run_id": self.run_id,
            "scraped_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **fields,
        }

    def related(self, response: Response, region: str = "body") -> Iterator[dict | scrapy.Request]:
        """Emite un ítem `link` por cada link saliente de `region` y sigue los de la lista blanca."""
        if not isinstance(response, TextResponse):
            return
        here = urlparse(response.url)
        seen: set[str] = set()
        for a in response.css(f"{region} a[href]"):
            url = response.urljoin(a.attrib["href"]).split("#")[0]
            u = urlparse(url)
            if u.scheme not in ("http", "https") or url in seen or u._replace(scheme="") == here._replace(scheme=""):
                continue
            seen.add(url)
            follow = (
                not response.meta.get("related")
                and url not in self.handled
                and not u.path.lower().endswith(SKIP_EXT)
                and (host := u.hostname or "")
                and (host == here.hostname or any(host == d or host.endswith("." + d) for d in whitelist()))
            )
            yield self.item("link", response, url_destino=url, texto=texts(a), seguido=follow)
            if follow:
                yield scrapy.Request(
                    url,
                    callback=self.parse_related,
                    errback=self._related_failed,
                    meta={"persona": response.meta["persona"], "related": True},
                )

    def parse_related(self, response: Response) -> Iterator[dict]:
        if isinstance(response, TextResponse):
            body = " ".join(response.css("body :not(script):not(style)::text").getall())
            yield self.item("pagina", response, titulo=clean(response.css("title::text").get()), texto=clean(body))
