from conftest import fixture_response, run_parse

from daii.bronze.spiders.portafolio import PortafolioSpider

URL = "https://portafolio-academico.uchile.cl/perfil/27103-James-Peter-Mc-Phee-Torres"


def test_portafolio_mcphee_pagina_1():
    resp = fixture_response("portafolio_mcphee_rendered.html", URL, "james-mcphee")
    out = run_parse(PortafolioSpider().parse_static(resp))

    p = out["persona"][0]
    assert p["nombre"] == "James Peter Mc Phee Torres" and p["email"] == "jmcphee@ing.uchile.cl"
    roles = {a["rol"] for a in out["afiliacion"]}
    assert "Prof. Titular · Categoría académica ordinaria · Jornada: 44 hrs" in roles
    assert "Vicerrector/a De Investigacion Y Desarrollo" in roles
    assert {"grado": "Doctor", "institucion": "U. of California - Los Angeles", "anio": 2004}.items() <= out[
        "formacion"
    ][0].items()

    d = out["dictacion"][0]
    assert (d["codigo_curso"], d["anio"], d["semestre"]) == ("CD1100", 2026, "Primer Semestre")
    pub = out["publicacion"][0]
    assert pub["doi"] == "http://dx.doi.org/10.5194/tc-20-1895-2026"  # crudo; silver normaliza
    assert pub["ids"]["indexacion"] == "WOS/SCOPUS/UCH/VID"
    assert out["proyecto"][0]["codigo"] == "CIA250010" and out["proyecto"][0]["anio_fin"] == 2030
    assert out["tesis"][0]["estudiante"] == "Castillo Ávalos, Yuri Alejandro"
    assert out["actividad"][0]["rol"] == "Colaborador(a)"
    # página 1 de cada tabla: 10 por tabla paginada
    assert len(out["dictacion"]) == 10 and len(out["publicacion"]) >= 10
