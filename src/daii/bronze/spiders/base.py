"""Clase base de todos los spiders: semillas por persona, ítems con metadatos y links relacionados."""

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urlparse

import scrapy
from scrapy.http import Response, TextResponse

from daii.config import academicos, con_perfil, whitelist

SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".zip", ".css", ".js", ".mp4", ".pptx", ".docx", ".xml")


def clean(text: str | None) -> str | None:
    """Colapsa espacios; devuelve None si queda vacío."""
    text = " ".join((text or "").split())
    return text or None


def texts(sel) -> str | None:
    """Texto visible de un selector (incluye hijos), limpio."""
    return clean(" ".join(sel.css("::text").getall()))


INITIALS = re.compile(r"^(?:[A-Z][a-z]?\.\s?-?)+$")


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

    def personas(self, plataforma: str | None = None) -> list[dict]:
        ps = con_perfil(plataforma) if plataforma else academicos()
        return [p for p in ps if not self.only or p["slug"] == self.only]

    def page(self, url: str, callback, persona: str, **meta: Any) -> scrapy.Request:
        self.handled.add(url)
        return scrapy.Request(url, callback=callback, errback=self._page_failed, meta={"persona": persona, **meta})

    def _page_failed(self, failure) -> None:
        """Una página propia no se pudo bajar: quality lo reporta como warn."""
        self.crawler.stats.inc_value("daii/page_error")
        self.logger.error("página propia falló: %s (%s)", failure.request.url, failure.value)

    def _related_failed(self, failure) -> None:
        """Links externos caídos son normales en sitios académicos: se cuentan, no se alertan."""
        self.crawler.stats.inc_value("daii/related_error")
        self.logger.info("link relacionado falló: %s (%s)", failure.request.url, failure.value)

    def item(self, tipo: str, response: Response, **fields: Any) -> dict:
        return {
            "tipo": tipo,
            "persona": response.meta["persona"],
            "url": response.url,
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
                and (u.netloc == here.netloc or any(u.netloc == d or u.netloc.endswith("." + d) for d in whitelist()))
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
