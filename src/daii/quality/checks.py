"""Checks de calidad por run de spider. Resultado en bronze/<spider>/<run_id>/quality.json.

Silver solo usa runs `ok`: ante `warn` o `fail` se publica el último run ok del spider (puede quedar viejo; el email
dice cuál se está usando). `fail` además deja el flow en Failed.
"""

import contextlib
import json
from collections import Counter
from pathlib import Path
from tempfile import NamedTemporaryFile

from daii.config import BRONZE

DROP_WARN = 0.5  # caída relativa vs. el último run bueno que dispara warn
DROP_MIN_BASE = 5  # no comparar tipos con menos ítems que esto en el run anterior
SIN_ALARMA_PERSONA = {"link", "pagina"}  # dependen de sitios externos y oscilan


def runs(spider: str) -> list[Path]:
    """Runs de un spider, del más reciente al más antiguo."""
    d = BRONZE / spider
    return sorted((p for p in d.iterdir() if p.is_dir()), reverse=True) if d.exists() else []


def status(run: Path) -> str | None:
    q = run / "quality.json"
    return json.loads(q.read_text())["status"] if q.exists() else None


def last_good(spider: str, before: Path | None = None) -> Path | None:
    """Último run `ok` con ítems (opcionalmente, anterior a `before`)."""
    return next(
        (
            r
            for r in runs(spider)
            if (before is None or r.name < before.name) and status(r) == "ok" and (r / "items.jsonl").is_file()
        ),
        None,
    )


def counts_persona(run: Path) -> Counter:
    """Ítems por (persona, tipo)."""
    f = run / "items.jsonl"
    c: Counter = Counter()
    for line in f.open() if f.exists() else []:
        with contextlib.suppress(json.JSONDecodeError):  # última línea a medio escribir (proceso matado)
            item = json.loads(line)
            c[item.get("persona"), item["tipo"]] += 1
    return c


def _por_tipo(by_persona: Counter) -> Counter:
    c: Counter = Counter()
    for (_, tipo), n in by_persona.items():
        c[tipo] += n
    return c


def counts(run: Path) -> Counter:
    return _por_tipo(counts_persona(run))


def check(spider: str, run: Path) -> dict:
    run.mkdir(parents=True, exist_ok=True)  # si Scrapy murió antes de crear el run, igual queda su quality.json
    fails, warns = [], []
    stats_f = run / "stats.json"
    stats = json.loads(stats_f.read_text()) if stats_f.exists() else {}
    got_persona = counts_persona(run)
    got = _por_tipo(got_persona)

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
    if partial := sorted(
        k.removeprefix("daii/coverage/")
        for k, v in stats.items()
        if k.startswith("daii/coverage/") and v == "incompleta"
    ):
        warns.append(f"pestañas incompletas: {partial}")
    if prev := last_good(spider, before=run):
        before_persona = counts_persona(prev)
        for tipo, n in _por_tipo(before_persona).items():
            if n >= DROP_MIN_BASE and got[tipo] < n * (1 - DROP_WARN):
                warns.append(f"{tipo}: cayó de {n} a {got[tipo]} vs run {prev.name}")
        # una pestaña que no cargó para una sola persona se diluye en el total: se compara también por persona
        for (persona, tipo), n in sorted(before_persona.items(), key=str):
            if tipo in SIN_ALARMA_PERSONA or n < DROP_MIN_BASE:
                continue
            if (now := got_persona[persona, tipo]) < n * (1 - DROP_WARN):
                warns.append(f"{persona}/{tipo}: cayó de {n} a {now} vs run {prev.name}")

    result = {
        "spider": spider,
        "run_id": run.name,
        "status": "fail" if fails else "warn" if warns else "ok",
        "problems": fails + warns,
        "counts": dict(got),
    }
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=run, delete_on_close=False) as pending:
        json.dump(result, pending, indent=1, ensure_ascii=False)
        pending.close()
        Path(pending.name).replace(run / "quality.json")
    return result
