import asyncio

from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.javier_ruiz_del_solar import JavierRuizDelSolarSpider

SITIO = 'https://www.cec.uchile.cl/~jruizd/'
P = 'javier-ruiz-del-solar'


def parse(fixture: str, page: str, callback: str) -> dict[str, list[dict]]:
    spider = JavierRuizDelSolarSpider()
    return run_parse(getattr(spider, callback)(fixture_response(fixture, SITIO + page, P)))


def test_home():
    out = parse('ruizdelsolar_home.html', '', 'parse')
    p = out['persona'][0]
    assert (p['nombre'], p['email'], p['telefono']) == (
        'Dr. Javier Ruiz del Solar',
        'jruizd@ing.uchile.cl',
        '(+562) 978 4207',
    )
    grados = [(f['grado'], f['institucion']) for f in out['formacion']]
    assert grados[-1] == ('Doctor Engineer', 'Technical University Berlin')
    assert grados[0] == ('Electrical Engineer', 'Universidad Técnica Federico Santa María')  # &eacute; decodificado

    afil = {a['organizacion']: a for a in out['afiliacion']}
    assert afil['Universidad de Chile']['rol'] == 'Professor of Electrical Engineering'
    assert afil['Advanced Mining Technology Center']['url_organizacion'] == 'http://www.amtc.cl'
    assert afil['University of Chile ROBOCUP Teams']['url_organizacion'] == 'http://www.robocup.cl'
    assert len(out['afiliacion']) == 7

    assert [a['nombre'] for a in out['area']] == [
        'Robotics and Autonomous Systems',
        'Computer Vision',
        'Mining Technology',
    ]
    (div,) = out['actividad']
    assert div['tipo_actividad'] == 'divulgacion' and div['url_destino'] == 'http://www.robot.cl'
    assert div['titulo'] == 'Educational Activities with Children using Robotics'


def test_cv():
    out = parse('ruizdelsolar_curriculum.html', 'curriculum.html', 'parse_cv')  # charset=macintosh
    prof = out['afiliacion'][0]
    assert (prof['rol'], prof['organizacion'], prof['desde']) == (
        'Professor of Electrical Engineering',
        'Universidad de Chile',
        '2011',
    )
    gsc = next(a for a in out['afiliacion'] if a['rol'] == 'Graduate Studies Chairman')
    assert (gsc['desde'], gsc['hasta']) == ('May 2005', 'present')

    dr = out['formacion'][0]
    assert (dr['grado'], dr['anio'], dr['institucion']) == (
        'Doctor-Engineer',
        1997,
        'Technical University Berlin, Germany',
    )
    assert any(f['institucion'] == 'Universidad Técnica Federico Santa María, Chile' for f in out['formacion'])

    assert len(out['distincion']) >= 20
    assert any(d['nombre'] == 'DAAD Fellowship' and d['anio'] == 1993 for d in out['distincion'])

    tipos = {}
    for a in out['actividad']:
        tipos[a['tipo_actividad']] = tipos.get(a['tipo_actividad'], 0) + 1
    assert tipos['comite_programa'] >= 60 and tipos['revisor'] >= 30 and tipos['editorial'] == 3
    assert tipos['comite'] >= 1 and tipos['charla'] >= 1 and tipos['tutorial'] >= 1
    ed = next(a for a in out['actividad'] if a['tipo_actividad'] == 'editorial')
    assert (
        ed['titulo'].startswith('International Journal of Hybrid Intelligent Systems') and ed['fecha'] == '2004 – 2006'
    )
    # datos personales del CV (RUT, fecha de nacimiento) no se extraen
    assert not any('8.323.448' in str(v) for items in out.values() for i in items for v in i.values())


def test_cv_no_se_guarda():
    async def reqs():
        return [r async for r in JavierRuizDelSolarSpider().start()]

    cv = next(r for r in asyncio.run(reqs()) if r.url.endswith('curriculum.html'))
    assert cv.meta['guardar'] is False


def test_publications():
    out = parse('ruizdelsolar_publications.html', 'publications.html', 'parse_publications')
    assert all(p['titulo'] for p in out['publicacion'])  # libros editados: la itálica es el título
    assert {'titulo': 'RoboCup 2010: Robot Soccer World Cup XIV', 'venue': None}.items() <= next(
        p for p in out['publicacion'] if p['titulo'].startswith('RoboCup 2010')
    ).items()
    pubs = out['publicacion']
    assert len(pubs) >= 230
    p = pubs[0]
    assert p['titulo'] == (
        'Human Detection and Identification by Robots using Thermal and Visual Information in Domestic Environments'
    )
    assert (p['anio'], p['venue'], p['doi'], p['estado']) == (
        2012,
        'Journal of Intelligent and Robotic Systems',
        '10.1007/s10846-011-9612-2',
        'in press',
    )
    assert p['autores'] == ['Correa, M.', 'Hermosilla, G.', 'Verschae, R.', 'Ruiz-del-Solar, J.']
    assert p['tipo_publicacion'] == 'International Journal Papers'
    gabor = next(x for x in pubs if x['titulo'].startswith('Automatic Gabor-like'))
    assert gabor['venue'] == 'Proc. of the 5th Int. Conf. on Cognitive and Neural Systems - ICCNS 2001'
    chap = next(x for x in pubs if x['titulo'] == 'State of the Art Face Detection: Cascade Boosting Approaches')
    assert chap['tipo_publicacion'] == 'Book Chapters' and chap['venue'] == 'Applications of Soft Computing'
    assert sum(x['tipo_publicacion'] == 'Conference Papers' for x in pubs) >= 100


def test_thesis():
    out = parse('ruizdelsolar_thesis.html', 'thesis.html', 'parse_thesis')
    tesis = out['tesis']
    assert len(tesis) >= 25
    t = tesis[0]
    assert (t['estudiante'], t['titulo'], t['anio'], t['nivel']) == (
        'Escobar Silva, María José',
        'Reconocimiento de Caras mediante Wavelets',
        2001,
        'Tesis de Magister',
    )
    assert any(x['rol'] == 'profesor co-guía' for x in tesis)
    assert sum('comisión' in (x['rol'] or '') for x in tesis) >= 5


def test_research_y_cursos():
    areas = parse('ruizdelsolar_research.html', 'research.html', 'parse_research')['area']
    assert 'Reconocimiento de Caras' in [a['nombre'] for a in areas] and len(areas) == 7
    cursos = parse('ruizdelsolar_courses.htm', 'courses.htm', 'parse_courses')['dictacion']
    assert [c['codigo_curso'] for c in cursos] == ['EL54B', 'EL708', 'SD20A']
    assert cursos[1]['nombre_curso'] == 'Procesamiento Avanzado de Imágenes (Advance Image Processing)'
