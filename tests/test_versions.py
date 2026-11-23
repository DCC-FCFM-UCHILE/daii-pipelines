import json
import sqlite3

import pytest

from daii import versions
from daii.gold import load
from daii.quality import checks


def test_publica_la_corrida_fijada_y_preserva_historial(tmp_path, monkeypatch):
    bronze = tmp_path / "bronze"
    gold = tmp_path / "gold" / "daii.sqlite"
    for module, field, value in (
        (versions, "DATA", tmp_path),
        (versions, "VERSIONS", tmp_path / "versions"),
        (versions, "BRONZE", bronze),
        (versions, "GOLD_DB", gold),
        (load, "BRONZE", bronze),
        (checks, "BRONZE", bronze),
    ):
        monkeypatch.setattr(module, field, value)

    def run(name, state):
        directory = bronze / "orcid" / name
        directory.mkdir(parents=True)
        (directory / "quality.json").write_text(json.dumps({"status": state}))
        item = {"tipo": "area", "persona": "aidan-hogan", "spider": "orcid", "nombre": name}
        (directory / "items.jsonl").write_text(json.dumps(item) + "\n")

    run("20261123T175501Z", "ok")
    first = versions.prepare()
    run("20261123T185212Z", "warn")
    versions.publish(first)
    second = versions.prepare()
    versions.publish(second)
    with sqlite3.connect(gold) as db:
        assert db.execute("SELECT run_en_uso, estado FROM scraperun").fetchone() == ("20261123T175501Z", "warn")
        assert db.execute("SELECT build_id FROM datarelease").fetchone() == (second,)
    assert (tmp_path / "versions" / first / "daii.sqlite").exists()
    assert "area" not in versions.diff(first, second)["cambios"]

    with pytest.raises(ValueError, match="anterior"):
        versions.publish(first)
    versions.publish(second)
    added = tmp_path / "versions" / second / "silver" / "proyecto.parquet"
    added.write_bytes(b"archivo imprevisto")
    with pytest.raises(ValueError, match="Silver cambió"):
        versions.publish(second)
