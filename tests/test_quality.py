import json

from daii.quality import checks


def _run(root, name, items, stats):
    run = root / "spi" / name
    run.mkdir(parents=True)
    (run / "items.jsonl").write_text("".join(json.dumps({"tipo": t}) + "\n" for t in items))
    (run / "stats.json").write_text(json.dumps(stats))
    return run


def test_check_statuses(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "RAW", tmp_path)
    ok = {"finish_reason": "finished", "expect": {"publicacion": 2}}
    r1 = _run(tmp_path, "20260101T000000Z", ["publicacion"] * 10, ok)
    assert checks.check("spi", r1)["status"] == "ok"

    r2 = _run(tmp_path, "20260102T000000Z", ["publicacion"] * 3, ok)  # cae de 10 a 3
    res = checks.check("spi", r2)
    assert res["status"] == "warn" and "cayó de 10 a 3" in res["problems"][0]

    r3 = _run(tmp_path, "20260103T000000Z", ["publicacion"], ok)  # bajo el mínimo
    assert checks.check("spi", r3)["status"] == "fail"
    assert checks.last_good("spi") == r2  # silver ignora el run fallido

    r4 = _run(tmp_path, "20260104T000000Z", [], {})  # crash
    assert set(checks.check("spi", r4)["problems"]) >= {"0 ítems", "sin stats.json: el proceso de Scrapy se cayó"}
