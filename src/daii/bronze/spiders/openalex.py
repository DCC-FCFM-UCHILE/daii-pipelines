"""OpenAlex: autor (métricas, temas, instituciones) y obras (coautores, venue, citas, DOI) por ORCID.

OpenAlex desambigua autores automáticamente y a veces mezcla personas homónimas; silver trata como
baja confianza las publicaciones que solo aparecen aquí. API key opcional: env OPENALEX_API_KEY.
"""

import json
import os
from collections.abc import Iterator
from urllib.parse import urlencode

from scrapy import Request
from scrapy.http import Response

from daii.bronze.spiders.base import AcademicSpider

BASE = "https://api.openalex.org"
PER_PAGE = 200
SELECT = "id,doi,title,publication_year,type,primary_location,authorships,cited_by_count,open_access,ids"


def _url(path: str, **params: str) -> str:
    if key := os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = key
    return f"{BASE}/{path}?{urlencode(params)}" if params else f"{BASE}/{path}"


class OpenalexSpider(AcademicSpider):
    name = "openalex"
    expect = {"metrica": 3, "publicacion": 10}

    async def start(self):
        for p in self.personas("orcid"):
            orcid = p["perfiles"]["orcid"]
            yield self.page(_url(f"authors/orcid:{orcid}"), self.parse_author, p["slug"])
            yield self.page(self._works_url(orcid, 1), self.parse_works, p["slug"], orcid=orcid, n=1)

    @staticmethod
    def _works_url(orcid: str, page: int) -> str:
        # Paginación por número (no cursor): el cursor exige API key; `page` funciona hasta 10.000 resultados.
        return _url(
            "works", filter=f"author.orcid:{orcid}", **{"per-page": str(PER_PAGE), "page": str(page), "select": SELECT}
        )

    def parse_author(self, response: Response) -> Iterator[dict]:
        a = json.loads(response.text)
        yield self.item(
            "perfil", response, plataforma="openalex", url_destino=a["id"], identificador=a["id"].rsplit("/", 1)[-1]
        )
        stats = {"works_count": a.get("works_count"), "cited_by_count": a.get("cited_by_count")}
        stats |= a.get("summary_stats") or {}
        for nombre, valor in stats.items():
            if valor is not None:
                yield self.item("metrica", response, plataforma="openalex", nombre=nombre, valor=valor)
        for c in a.get("counts_by_year") or []:
            yield self.item(
                "metrica", response, plataforma="openalex", nombre="citas", valor=c["cited_by_count"], anio=c["year"]
            )
        for t in (a.get("topics") or [])[:10]:
            yield self.item("area", response, nombre=t["display_name"])
        for af in a.get("affiliations") or []:
            years = sorted(af.get("years") or [])
            yield self.item(
                "afiliacion",
                response,
                organizacion=af["institution"]["display_name"],
                rol="afiliación declarada en publicaciones",
                desde=str(years[0]) if years else None,
                hasta=str(years[-1]) if years else None,
                url_organizacion=af["institution"].get("ror"),
            )

    def parse_works(self, response: Response) -> Iterator[dict | Request]:
        d = json.loads(response.text)
        for w in d["results"]:
            if not w.get("title"):
                continue
            loc = w.get("primary_location") or {}
            yield self.item(
                "publicacion",
                response,
                titulo=w["title"],
                anio=w.get("publication_year"),
                tipo_publicacion=loc.get("raw_type") or w.get("type"),
                venue=(loc.get("source") or {}).get("display_name"),
                autores=[a["author"]["display_name"] for a in w.get("authorships") or []],
                doi=(w.get("doi") or "").removeprefix("https://doi.org/") or None,
                url_destino=loc.get("pdf_url") or loc.get("landing_page_url"),
                citas=w.get("cited_by_count"),
                ids={"openalex": w["id"].rsplit("/", 1)[-1]},
            )
        n, orcid = response.meta["n"], response.meta["orcid"]
        if n * d["meta"]["per_page"] < d["meta"]["count"]:
            yield self.page(
                self._works_url(orcid, n + 1), self.parse_works, response.meta["persona"], orcid=orcid, n=n + 1
            )
