from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.bronze.spiders.sites.francielle_vargas import FrancielleVargasSpider

URL = "https://franciellevargas.github.io/"
P = "francielle-vargas"


def parse(fixture: str, path: str, callback: str, cls=None) -> dict[str, list[dict]]:
    spider = FrancielleVargasSpider()
    kw = {"cls": cls} if cls else {}
    return run_parse(getattr(spider, callback)(fixture_response(fixture, URL + path, P, **kw)))


def test_home():
    out = parse("vargas_home.html", "", "parse_home")
    p = out["persona"][0]
    assert p["nombre"] == "Francielle Vargas" and p["cargo"] == "Assistant Professor"
    assert p["bio"].startswith("I am a Natural Language Processing researcher")
    orcid = next(x for x in out["perfil"] if x["plataforma"] == "orcid")
    assert orcid["identificador"] == "0000-0003-3164-2682"

    afil = {a["rol"]: a for a in out["afiliacion"]}
    idia = afil["Assistant Professor"]
    assert idia["organizacion"].startswith("Data and Artificial Intelligence Initiative")
    assert idia["organizacion"].endswith("University of Chile")
    tub = afil["Co-Lead Principal Investigator in the “AI and Global Justice” working group"]
    assert tub["organizacion"] == "Interdisciplinary Centre for Global South Studies, University of Tübingen"
    assert afil["Research Collaborator"]["url_organizacion"] == "https://digitaltrustcouncil.com/research"

    proy = {x["titulo"]: x for x in out["proyecto"]}
    snf = proy["Robust Augmented Retrieval for Natural Language Inference over Transformer-based Models"]
    assert snf["codigo"] == "229196" and snf["anio_inicio"] == 2025
    assert len(out["proyecto"]) == 8
    assert "AI Safety and Alignment" in {a["nombre"] for a in out["area"]}


def test_teaching_publicaciones_recursos():
    out = parse("vargas_teaching.html", "pages/teaching.html", "parse_teaching")
    cursos = out["dictacion"]
    tesis = {t["estudiante"]: t for t in out["tesis"]}
    assert len(tesis) == 4 and "Kevin Blanco" not in tesis  # pasantía, no tesis
    assert tesis["Isadora Salles"] == tesis["Isadora Salles"] | {
        "titulo": None,
        "nivel": "Master's Student in Computer Science",
        "rol": "Co-Advisor",
        "anio": 2024,
    }
    nlp = next(c for c in cursos if c["nombre_curso"] == "Natural Language Processing")
    assert nlp["anio"] == 2026 and nlp["institucion"].endswith("University of Chile")

    pubs = parse("vargas_publications.html", "pages/publications.html", "parse_publications")["publicacion"]
    acl = next(x for x in pubs if x["titulo"] == "Self-Explaining Hate Speech Detection with Moral Rationales")
    assert acl["anio"] == 2026 and acl["venue"].startswith("Findings of the Association for Computational Linguistics")
    assert acl["autores"][0] == "Francielle Vargas" and acl["ids"] == {"acl": "2026.findings-acl.1704"}
    pre = next(x for x in pubs if x["tipo_publicacion"] == "Preprints")
    assert pre["ids"] == {"arxiv": "2607.15992"} and pre["anio"] == 2026
    assert len(pubs) >= 25

    out = parse("vargas_resources.html", "pages/resources.html", "parse_resources")
    hausa = next(x for x in out["producto"] if x["nombre"] == "HausaHate")
    assert hausa["tipo_producto"] == "Benchmark Datasets"
    assert hausa["url_destino"] == "https://github.com/franciellevargas/HausaHate"
    assert hausa["descripcion"].startswith("A Benchmark Dataset for Hate Speech Detection")
    assert len(out["producto"]) >= 14


def test_servicio_charlas_prensa_premios():
    act = parse("vargas_service.html", "pages/service.html", "parse_service")["actividad"]
    neurips = next(a for a in act if a["titulo"].startswith("NeurIPS"))
    assert neurips["tipo_actividad"] == "comite_programa" and neurips["fecha"] == "2026"
    icwsm = next(a for a in act if a["titulo"] == "International AAAI Conference on Web and Social Media")
    assert icwsm["tipo_actividad"] == "organizacion_evento" and icwsm["fecha"] == "ICWSM 2023, ICWSM 2022, ICWSM 2021"
    assert sum(a["tipo_actividad"] == "revisor" for a in act) == 5

    talks = parse("vargas_talks.html", "pages/talks.html", "parse_talks")["actividad"]
    raia = next(t for t in talks if t["tipo_actividad"] == "keynote")
    assert raia["evento"].startswith("2nd RAIA Conference") and raia["fecha"] == "2026"
    leiden = next(t for t in talks if "LIACS" in t["evento"])
    assert leiden["descripcion"] == "Leiden University, The Netherlands"
    assert leiden["url_destino"] == URL + "doc/slides_talks/liacs_leiden_2026.pdf"  # relativo a la raíz, no a pages/
    assert len(talks) == 9

    prensa = parse("vargas_press.html", "pages/press.html", "parse_press")["actividad"]
    tvn = next(x for x in prensa if x["evento"] == "National Television of Chile (TVN)")
    assert tvn["titulo"] == "New Chilean AI Explains Its Decisions When Moderating Content"
    assert tvn["fecha"] == "August 2026"
    assert len(prensa) >= 15

    premios = parse("vargas_awards.html", "pages/awards.html", "parse_awards")["distincion"]
    naacl = next(d for d in premios if d["nombre"] == "NAACL Regional Americas Fund Award")
    assert naacl["anio"] == 2026 and naacl["otorgante"].endswith("(NAACL)")
    assert len(premios) == 12


def test_cv():
    out = parse("vargas_cv.pdf", "doc/cv.pdf", "parse_cv", cls=Response)
    grados = {f["grado"]: f for f in out["formacion"]}
    phd = grados["PhD in Computer Science and Computational Mathematics"]
    assert phd["anio"] == 2024 and phd["institucion"] == "University of São Paulo (USP)"
    assert grados["MSc in Computer Science and Computational Mathematics"]["anio"] == 2017

    afil = {a["rol"]: a for a in out["afiliacion"]}
    assert (afil["Assistant Professor"]["desde"], afil["Assistant Professor"]["hasta"]) == ("05/2026", None)
    assert afil["Postdoctoral Researcher"]["hasta"] == "04/2026"
    assert len(out["afiliacion"]) == 8

    proy = {p["titulo"]: p for p in out["proyecto"]}
    rag = proy["Robust Augmented Retrieval for Natural Language Inference over Transformer-based Models"]
    assert rag["codigo"] == "25/01118-2" and rag["monto"] == "USD 30.000,00" and rag["anio_inicio"] == 2025
    lara = proy["Responsible and Explainable Fact-Checking through Fine-Grained Factual Reasoning"]
    assert lara["codigo"] == "1598741" and lara["fuente"] == "Google Latin America Research Award (LARA)"
    assert len(out["proyecto"]) == 6
