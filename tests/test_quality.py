import json

from daii.quality import checks


def _run(root, name, items, stats):
    run = root / 'spi' / name
    run.mkdir(parents=True)
    rows = ({'tipo': t} if isinstance(t, str) else {'persona': t[0], 'tipo': t[1]} for t in items)
    (run / 'items.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (run / 'stats.json').write_text(json.dumps(stats))
    return run


def test_check_statuses(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, 'BRONZE', tmp_path)
    ok = {'finish_reason': 'finished', 'expect': {'publicacion': 2}}
    r1 = _run(tmp_path, '20260101T000000Z', ['publicacion'] * 10, ok)
    assert checks.check('spi', r1)['status'] == 'ok'

    r2 = _run(tmp_path, '20260102T000000Z', ['publicacion'] * 3, ok)  # cae de 10 a 3
    res = checks.check('spi', r2)
    assert res['status'] == 'warn' and 'cayó de 10 a 3' in res['problems'][0]

    r3 = _run(tmp_path, '20260103T000000Z', ['publicacion'], ok)  # bajo el mínimo
    assert checks.check('spi', r3)['status'] == 'fail'
    assert checks.last_good('spi') == r1

    r4 = _run(tmp_path, '20260104T000000Z', [], {})  # crash
    assert set(checks.check('spi', r4)['problems']) >= {'0 ítems', 'sin stats.json: el proceso de Scrapy se cayó'}

    r5 = _run(tmp_path, '20260105T000000Z', ['publicacion'] * 3, ok)
    assert checks.check('spi', r5)['status'] == 'warn'
    assert checks.last_good('spi') == r1


def test_pestania_incompleta_es_warn_con_detalle(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, 'BRONZE', tmp_path)
    stats = {'finish_reason': 'finished', 'daii/page_error': 1, 'daii/coverage/ana/docencia': 'incompleta'}
    stats |= {'daii/coverage/ana/publicaciones': 'completa'}
    res = checks.check('spi', _run(tmp_path, '20260101T000000Z', ['persona'], stats))
    assert res['status'] == 'warn' and "pestañas incompletas: ['ana/docencia']" in res['problems']


def test_caida_de_una_persona_alerta_aunque_el_total_no_caiga(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, 'BRONZE', tmp_path)
    monkeypatch.setattr(checks, 'academicos', lambda: [{'slug': 'ana'}, {'slug': 'beto'}])
    ok = {'finish_reason': 'finished'}
    otros = [('ana', 'proyecto')] * 40 + [('ex', 'proyecto')] * 6
    first = _run(tmp_path, '20260101T000000Z', [('beto', 'proyecto')] * 31 + otros + [('ana', 'link')] * 10, ok)
    checks.check('spi', first)
    # total 77 → 46 (cae 40%); los links pasan de ana a beto (total igual) y "ex" salió de config: no alertan
    second = _run(tmp_path, '20260102T000000Z', otros[:40] + [('ana', 'link')] * 2 + [('beto', 'link')] * 8, ok)
    res = checks.check('spi', second)
    assert res['status'] == 'warn'
    assert res['problems'] == ['beto/proyecto: cayó de 31 a 0 vs run 20260101T000000Z']

    accepted = checks.aceptar('spi', second.name)
    assert accepted['status'] == 'ok' and accepted['aceptado']['problemas'] == res['problems']
    assert checks.last_good('spi') == second


def test_caida_total_no_repite_una_linea_por_persona(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, 'BRONZE', tmp_path)
    monkeypatch.setattr(checks, 'academicos', lambda: [{'slug': p} for p in 'abc'])
    ok = {'finish_reason': 'finished'}
    checks.check('spi', _run(tmp_path, '20260101T000000Z', [(p, 'publicacion') for p in 'abc' for _ in range(10)], ok))
    res = checks.check('spi', _run(tmp_path, '20260102T000000Z', [('a', 'publicacion')], ok))
    assert res['problems'] == ['publicacion: cayó de 30 a 1 vs run 20260101T000000Z']
