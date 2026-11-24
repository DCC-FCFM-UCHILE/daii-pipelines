import pytest
from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.aidan_hogan import AidanHoganSpider


@pytest.fixture(scope='module')
def out() -> dict[str, list[dict]]:
    resp = fixture_response('hogan_home.html', 'https://aidanhogan.com/', 'aidan-hogan')
    return run_parse(AidanHoganSpider().parse(resp))


def test_persona_afiliaciones(out):
    (p,) = out['persona']
    assert (p['nombre'], p['cargo'], p['email']) == ('Aidan Hogan', 'Professor', 'aidhog@gmail.com')
    assert p['foto_url'] == 'https://aidanhogan.com/img/me-sp.png'
    afil = {(a['organizacion'], a['rol']): a for a in out['afiliacion']}
    assert (
        afil['Department of Computer Science (DCC) at the Universidad de Chile', 'Professor']['url_organizacion']
        == 'http://www.dcc.uchile.cl/'
    )
    assert ('Millennium Institute for Foundational Research on Data (IMFD)', 'Associate Researcher') in afil
    deri = afil['Digital Enterprise Research Institute (DERI)', None]
    assert (deri['desde'], deri['hasta']) == ('April 2005', 'November 2013')
    assert ('Digital Enterprise Research Institute (DERI)', 'PostDoc') in afil
    (phd,) = out['formacion']
    assert phd == phd | {'grado': 'PhD', 'anio': 2011, 'institucion': 'National University of Ireland, Galway'}
    assert phd['titulo_tesis'].startswith('Exploiting RDFS and OWL')
    perfiles = {x['plataforma']: x for x in out['perfil']}
    assert perfiles['orcid']['identificador'] == '0000-0001-9482-1982' and len(perfiles) == 6
    assert {'dblp', 'scholar', 'researcherid', 'semanticscholar'} <= perfiles.keys()


def test_publicaciones(out):
    pubs = out['publicacion']
    assert len(pubs) >= 150
    assert {p['tipo_publicacion'] for p in pubs} >= {'Books', 'Journal Articles', 'Conference Papers', 'Other'}
    ring = next(p for p in pubs if p['titulo'].startswith('The Ring: Worst-Case Optimal Joins'))
    assert ring['venue'] == 'ACM Transactions on Database Systems 49(2): 5:1--5:45, 2024' and ring['anio'] == 2024
    assert ring['url_destino'] == 'https://aidanhogan.com/docs/ring-graph-wco.pdf'
    assert ring['autores'][0] == 'Diego Arroyuelo' and 'Aidan Hogan' in ring['autores']
    rdfx = next(p for p in pubs if p['titulo'] == 'RDF Explorer: A Visual SPARQL Query Builder')
    assert rdfx['anio'] == 2019 and 'Best Student Paper' not in rdfx['venue']  # el premio va en otro <span>
    assert sum(p['anio'] is None for p in pubs) <= 2


def test_actividades(out):
    acts = out['actividad']
    assert len(acts) >= 80
    por_tipo = {t: [a for a in acts if a['tipo_actividad'] == t] for t in {a['tipo_actividad'] for a in acts}}
    assert len(por_tipo['keynote']) == 7 and len(por_tipo['prensa']) >= 2 and len(por_tipo['revisor']) >= 1
    k = por_tipo['keynote'][0]
    assert k['titulo'] == 'Wikidata: A Nucleus for a Web of Open Data' and k['fecha'] == '2024'
    assert k['evento'] == 'Distributed Knowledge Graphs Plenary Meeting (COST CA19134 2024)'
    gc = next(a for a in acts if a['rol'] == 'General Chair')
    assert gc['titulo'] == '23rd International Semantic Web Conference (ISWC 2024)'
    eic = next(a for a in acts if a['rol'] == 'Editor-in-Chief')
    assert eic['tipo_actividad'] == 'editorial' and eic['url_destino'] == 'https://tgdk.org'
    aaai = next(a for a in acts if a['titulo'] == 'AAAI' and a['rol'] == 'PC Memberships')
    assert aaai['fecha'] == '2013, 2015, 2021'
    isws = next(a for a in acts if a['titulo'].startswith('Knowledge Representation, Querying'))
    assert isws['evento'] == 'International Semantic Web Research Summer School (ISWS)'  # no el coautor enlazado


def test_docencia_tesis_premios(out):
    assert len(out['dictacion']) == 4
    assert out['dictacion'][0]['nombre_curso'] == 'La Web de Datos (Web of Data)'
    tesis = out['tesis']
    assert len(tesis) >= 60
    moya = {'estudiante': 'Alberto Moya', 'nivel': 'PhD in Computer Science', 'estado': 'Current'}
    assert tesis[0] == tesis[0] | moya
    assert all(t['titulo'] is None for t in tesis)  # la fuente no trae títulos: no se usa el nivel como título
    assert len({(t['estudiante'], t['nivel']) for t in tesis}) >= 60
    sf = next(t for t in tesis if t['estudiante'] == 'Sebastián Ferrada' and t['nivel'].startswith('PhD'))
    assert sf['rol'] == 'co-supervised with Benjamín Bustos' and sf['estado'] == 'Alumni'
    dist = out['distincion']
    assert len(dist) >= 30
    assert dist[0] == dist[0] | {'nombre': 'SIGMOD 2026 Outstanding Program Committee Member', 'anio': 2026}
