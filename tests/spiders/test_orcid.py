from conftest import fixture_response, run_parse
from scrapy.http import TextResponse

from daii.bronze.spiders.orcid import OrcidSpider


def test_orcid_silva():
    url = 'https://pub.orcid.org/v3.0/0000-0002-0256-282X/record'
    out = run_parse(OrcidSpider().parse(fixture_response('orcid_silva.json', url, 'jorge-silva', cls=TextResponse)))

    assert out['persona'][0]['nombre'] == 'Jorge F. Silva'
    assert 'Machine Learning' in {a['nombre'] for a in out['area']}
    assert out['afiliacion'][0]['organizacion'] == 'Universidad de Chile'
    assert len(out['publicacion']) >= 50
    pub = next(p for p in out['publicacion'] if p['doi'] == '10.1016/j.newar.2025.101745')
    assert pub['titulo'].startswith('A review on fundamental bounds') and pub['tipo_publicacion'] == 'journal-article'
