"""DBLP vía su endpoint SPARQL oficial (https://sparql.dblp.org).

Las páginas HTML/XML de dblp.org están detrás de Anubis, que bloquea explícitamente navegadores headless:
no se evade. El SPARQL es la vía programática que DBLP ofrece.
"""

import json
from collections.abc import Iterator
from urllib.parse import urlencode

from scrapy.http import Response

from daii.raw.spiders.base import AcademicSpider

ENDPOINT = "https://sparql.dblp.org/sparql"
QUERY = """
PREFIX dblp: <https://dblp.org/rdf/schema#>
SELECT ?publ ?title ?year ?type (SAMPLE(?doi_) AS ?doi) (SAMPLE(?venue_) AS ?venue)
       (GROUP_CONCAT(DISTINCT CONCAT(STR(?ord), "|", ?name); SEPARATOR="\\n") AS ?authors)
WHERE {
  ?publ dblp:authoredBy <https://dblp.org/pid/%s> ; dblp:title ?title ; dblp:yearOfPublication ?year ; a ?type .
  FILTER(?type != dblp:Publication)
  ?publ dblp:hasSignature ?sig . ?sig dblp:signatureOrdinal ?ord ; dblp:signatureDblpName ?name .
  OPTIONAL { ?publ dblp:doi ?doi_ }
  OPTIONAL { ?publ dblp:publishedIn ?venue_ }
}
GROUP BY ?publ ?title ?year ?type
"""


def _val(row: dict, k: str) -> str | None:
    return row[k]["value"] if k in row else None


class DblpSpider(AcademicSpider):
    name = "dblp"
    expect = {"publicacion": 10}

    async def start(self):
        for p in self.personas("dblp"):
            pid = p["perfiles"]["dblp"]
            url = f"{ENDPOINT}?{urlencode({'query': QUERY % pid})}"
            req = self.page(url, self.parse, p["slug"], pid=pid)
            req.headers["Accept"] = "application/sparql-results+json"
            yield req

    def parse(self, response: Response) -> Iterator[dict]:
        pid = response.meta.get("pid")
        if pid:
            yield self.item(
                "perfil", response, plataforma="dblp", identificador=pid, url_destino=f"https://dblp.org/pid/{pid}.html"
            )
        for row in json.loads(response.text)["results"]["bindings"]:
            signed = sorted((_val(row, "authors") or "").splitlines(), key=lambda s: int(s.split("|", 1)[0]))
            yield self.item(
                "publicacion",
                response,
                titulo=row["title"]["value"].rstrip("."),
                anio=_val(row, "year"),
                tipo_publicacion=(_val(row, "type") or "").rsplit("#", 1)[-1] or None,
                venue=_val(row, "venue"),
                autores=[s.split("|", 1)[1] for s in signed],
                doi=(_val(row, "doi") or "").removeprefix("https://doi.org/") or None,
                ids={"dblp": row["publ"]["value"].rsplit("/rec/", 1)[-1]},
            )
