"""Checks de calidad por run de spider. Resultado en bronze/<spider>/<run_id>/quality.json.

fail → el run no se usa en silver (se mantiene el último bueno) y el flow termina en Failed.
warn → el run se usa, pero se reporta.
"""

import json
from collections import Counter
from pathlib import Path

from daii.config import BRONZE

DROP_WARN = 0.5  # caída relativa vs. el último run bueno que dispara warn
DROP_MIN_BASE = 5  # no comparar tipos con menos ítems que esto en el run anterior


def runs(spider: str) -> list[Path]:
    """Runs de un spider, del más reciente al más antiguo."""
    d = BRONZE / spider
    return sorted((p for p in d.iterdir() if p.is_dir()), reverse=True) if d.exists() else []


def status(run: Path) -> str | None:
    q = run / "quality.json"
    return json.loads(q.read_text())["status"] if q.exists() else None


def last_good(spider: str, before: Path | None = None) -> Path | None:
    """Último run evaluado que no falló (opcionalmente, anterior a `before`)."""
    return next(
        (r for r in runs(spider) if (before is None or r.name < before.name) and status(r) in ("ok", "warn")), None
    )


def counts(run: Path) -> Counter:
    f = run / "items.jsonl"
    return Counter(json.loads(line)["tipo"] for line in f.open()) if f.exists() else Counter()


def check(spider: str, run: Path) -> dict:
    fails, warns = [], []
    stats_f = run / "stats.json"
    stats = json.loads(stats_f.read_text()) if stats_f.exists() else {}
    got = counts(run)

    if not stats:
        fails.append("sin stats.json: el proceso de Scrapy se cayó")
    elif stats.get("finish_reason") != "finished":
        fails.append(f"finish_reason={stats.get('finish_reason')}")
    if not got:
        fails.append("0 ítems")
    for tipo, minimo in stats.get("expect", {}).items():
        if got[tipo] < minimo:
            fails.append(f"{tipo}: {got[tipo]} < mínimo esperado {minimo}")

    invalid = {k.rsplit("/", 1)[-1]: v for k, v in stats.items() if k.startswith("daii/invalid_item/")}
    if invalid:
        warns.append(f"ítems inválidos descartados: {invalid}")
    # Solo errores accionables: parsers que lanzan excepción y páginas propias que no bajaron.
    # Los links relacionados caídos (daii/related_error) y los robots.txt de terceros no alertan.
    if exc := sum(v for k, v in stats.items() if k.startswith("spider_exceptions/")):
        warns.append(f"{exc} excepciones en parsers")
    if perr := stats.get("daii/page_error"):
        warns.append(f"{perr} páginas propias fallaron")
    if prev := last_good(spider, before=run):
        before = counts(prev)
        for tipo, n in before.items():
            if n >= DROP_MIN_BASE and got[tipo] < n * (1 - DROP_WARN):
                warns.append(f"{tipo}: cayó de {n} a {got[tipo]} vs run {prev.name}")

    result = {
        "spider": spider,
        "run_id": run.name,
        "status": "fail" if fails else "warn" if warns else "ok",
        "problems": fails + warns,
        "counts": dict(got),
    }
    (run / "quality.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    return result
