"""ORCID API pública v3.0 (/record): persona, keywords, perfiles, afiliaciones, formación, fondos, obras."""

import json
from collections.abc import Iterator

from scrapy.http import Response

from daii.raw.spiders.base import AcademicSpider

API = "https://pub.orcid.org/v3.0/{}/record"


def _v(d: dict | None, *path: str):
    """Navega dicts anidados de ORCID tolerando None en cualquier nivel."""
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _year(date: dict | None) -> str | None:
    return _v(date, "year", "value")


def _summaries(section: dict | None, key: str) -> Iterator[dict]:
    for g in _v(section, "affiliation-group") or []:
        for s in g.get("summaries", []):
            yield s[key]


class OrcidSpider(AcademicSpider):
    name = "orcid"
    expect = {"persona": 1, "publicacion": 10}
    # pub.orcid.org bloquea todo en robots.txt (apunta a crawlers web), pero es la API pública oficial,
    # pensada para consumo programático: https://info.orcid.org/documentation/features/public-api/
    custom_settings = {"ROBOTSTXT_OBEY": False}

    async def start(self):
        for p in self.personas("orcid"):
            req = self.page(API.format(p["perfiles"]["orcid"]), self.parse, p["slug"])
            req.headers["Accept"] = "application/json"
            yield req

    def parse(self, response: Response) -> Iterator[dict]:
        d = json.loads(response.text)
        person, act = d.get("person") or {}, d.get("activities-summary") or {}
        name = _v(person, "name", "credit-name", "value") or " ".join(
            filter(None, [_v(person, "name", "given-names", "value"), _v(person, "name", "family-name", "value")])
        )
        yield self.item("persona", response, nombre=name, bio=_v(person, "biography", "content"))
        orcid = d.get("orcid-identifier", {}).get("path")
        yield self.item(
            "perfil", response, plataforma="orcid", url_destino=f"https://orcid.org/{orcid}", identificador=orcid
        )

        for k in _v(person, "keywords", "keyword") or []:
            yield self.item("area", response, nombre=k["content"])
        for u in _v(person, "researcher-urls", "researcher-url") or []:
            yield self.item(
                "perfil", response, plataforma=u.get("url-name") or "web", url_destino=_v(u, "url", "value")
            )
        for e in _v(person, "external-identifiers", "external-identifier") or []:
            yield self.item(
                "perfil",
                response,
                plataforma=e["external-id-type"],
                identificador=e["external-id-value"],
                url_destino=_v(e, "external-id-url", "value") or "",
            )

        for sec, key in [
            ("employments", "employment-summary"),
            ("invited-positions", "invited-position-summary"),
            ("memberships", "membership-summary"),
        ]:
            for s in _summaries(act.get(sec), key):
                yield self.item(
                    "afiliacion",
                    response,
                    organizacion=_v(s, "organization", "name"),
                    rol=" / ".join(filter(None, [s.get("role-title"), s.get("department-name")])) or sec,
                    desde=_year(s.get("start-date")),
                    hasta=_year(s.get("end-date")),
                )
        for sec, key in [("educations", "education-summary"), ("qualifications", "qualification-summary")]:
            for s in _summaries(act.get(sec), key):
                yield self.item(
                    "formacion",
                    response,
                    grado=s.get("role-title") or sec,
                    institucion=_v(s, "organization", "name"),
                    anio=_year(s.get("end-date")),
                )
        for s in _summaries(act.get("distinctions"), "distinction-summary"):
            yield self.item(
                "distincion",
                response,
                nombre=s.get("role-title") or s.get("department-name") or "distinción",
                otorgante=_v(s, "organization", "name"),
                anio=_year(s.get("start-date")),
            )
        for s in _summaries(act.get("services"), "service-summary"):
            yield self.item(
                "actividad",
                response,
                tipo_actividad="servicio",
                titulo=s.get("role-title") or "servicio",
                evento=_v(s, "organization", "name"),
                fecha=_year(s.get("start-date")),
            )

        for g in _v(act, "fundings", "group") or []:
            s = g["funding-summary"][0]
            ids = _v(s, "external-ids", "external-id") or []
            yield self.item(
                "proyecto",
                response,
                titulo=_v(s, "title", "title", "value"),
                codigo=next((i["external-id-value"] for i in ids if i["external-id-type"] == "grant_number"), None),
                fuente=_v(s, "organization", "name"),
                anio_inicio=_year(s.get("start-date")),
                anio_fin=_year(s.get("end-date")),
            )

        for g in _v(act, "works", "group") or []:
            s = g["work-summary"][0]
            ids = {i["external-id-type"]: i["external-id-value"] for i in _v(s, "external-ids", "external-id") or []}
            yield self.item(
                "publicacion",
                response,
                titulo=_v(s, "title", "title", "value"),
                tipo_publicacion=s.get("type"),
                anio=_year(s.get("publication-date")),
                venue=_v(s, "journal-title", "value"),
                doi=ids.pop("doi", None),
                url_destino=_v(s, "url", "value"),
                ids={k: str(v) for k, v in ids.items()},
            )
