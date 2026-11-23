"""Flow Prefect: bronze (spiders en paralelo) → quality → silver → gold → alerta por email."""

import subprocess
import sys
import traceback
from datetime import UTC, datetime

from prefect import flow, get_run_logger, task
from prefect.artifacts import create_markdown_artifact
from prefect.task_runners import ThreadPoolTaskRunner
from scrapy.settings import Settings
from scrapy.spiderloader import SpiderLoader

from daii.config import BRONZE, ROOT
from daii.gold.load import build as build_gold
from daii.quality import checks, notify
from daii.silver.transform import build as build_silver


def all_spiders() -> list[str]:
    s = Settings()
    s.setmodule("daii.bronze.settings")
    return sorted(SpiderLoader.from_settings(s).list())


@task(task_run_name="crawl-{spider}")
def crawl(spider: str, run_id: str) -> dict:
    """Corre un spider en su propio proceso (el reactor de Twisted no se puede reiniciar) y evalúa el run."""
    proc = subprocess.run(
        [sys.executable, "-m", "scrapy", "crawl", spider, "-a", f"run_id={run_id}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    log = get_run_logger()
    if proc.returncode:
        log.error("scrapy terminó con código %s:\n%s", proc.returncode, proc.stderr[-3000:])
    result = checks.check(spider, BRONZE / spider / run_id)
    (log.info if result["status"] == "ok" else log.warning)("%s: %s %s", spider, result["status"], result["problems"])
    return result


@task
def silver() -> dict[str, int]:
    return build_silver()


@task
def gold() -> dict[str, int]:
    return build_gold()


def _summary(results: list[dict]) -> str:
    rows = ["| spider | estado | ítems | problemas |", "|---|---|---|---|"]
    rows += [
        f"| {r['spider']} | {r['status']} | {sum(r['counts'].values())} | {'; '.join(r['problems'])} |"
        for r in sorted(results, key=lambda r: (r["status"] == "ok", r["spider"]))
    ]
    return "\n".join(rows)


@flow(name="daii-pipeline", task_runner=ThreadPoolTaskRunner(max_workers=4))
def pipeline(spiders: list[str] | None = None) -> dict:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    try:
        futures = [crawl.submit(s, run_id) for s in spiders or all_spiders()]
        results = [f.result() for f in futures]
        counts = {"silver": silver(), "gold": gold()}
    except Exception:
        notify.send("[daii] pipeline con error", traceback.format_exc())
        raise

    create_markdown_artifact(_summary(results), key="calidad-scrapers", description="Estado de cada spider en este run")
    bad = [r for r in results if r["status"] != "ok"]
    if bad:
        fails = sum(r["status"] == "fail" for r in bad)
        notify.send(
            f"[daii] {fails} fallas, {len(bad) - fails} avisos",
            notify.report(bad, "Los spiders en 'fail' no se usaron: silver/gold usan su último run bueno."),
        )
    if failed := [r["spider"] for r in bad if r["status"] == "fail"]:
        raise RuntimeError(f"spiders con fallas de calidad: {failed}")  # el flow queda en Failed en Prefect
    return counts
