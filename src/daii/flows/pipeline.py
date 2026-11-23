"""Flow Prefect: bronze (spiders en paralelo) → quality → silver → gold → alerta por email."""

import os
import signal
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from uuid import uuid4

from prefect import flow, get_run_logger, task
from prefect.artifacts import create_markdown_artifact
from prefect.task_runners import ThreadPoolTaskRunner
from scrapy.settings import Settings
from scrapy.spiderloader import SpiderLoader

from daii.config import BRONZE, ROOT
from daii.quality import checks, notify
from daii.versions import prepare, publish


def all_spiders() -> list[str]:
    s = Settings()
    s.setmodule("daii.bronze.settings")
    return sorted(SpiderLoader.from_settings(s).list())


CRAWL_TIMEOUT_S = 4200  # > CLOSESPIDER_TIMEOUT (3600) de bronze/settings.py


@task(task_run_name="crawl-{spider}")
def crawl(spider: str, run_id: str) -> dict:
    """Corre un spider en su propio proceso (el reactor de Twisted no se puede reiniciar) y evalúa el run."""
    log = get_run_logger()
    # grupo de procesos propio: si hay que matarlo, también mueren sus hijos (Chromium de Playwright)
    proc = subprocess.Popen(
        [sys.executable, "-m", "scrapy", "crawl", spider, "-a", f"run_id={run_id}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        _, stderr = proc.communicate(timeout=CRAWL_TIMEOUT_S)  # respaldo de CLOSESPIDER_TIMEOUT
        if proc.returncode:
            log.error("scrapy terminó con código %s:\n%s", proc.returncode, stderr[-3000:])
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        log.error("scrapy no terminó en %s s; se mató el proceso y sus hijos", CRAWL_TIMEOUT_S)
    result = checks.check(spider, BRONZE / spider / run_id)
    (log.info if result["status"] == "ok" else log.warning)("%s: %s %s", spider, result["status"], result["problems"])
    return result


@task
def silver() -> str:
    return prepare()


@task
def gold(build_id: str) -> dict[str, int]:
    return publish(build_id)


def _result(spider: str, run_id: str, future) -> dict:
    out = future.result(raise_on_failure=False)
    if isinstance(out, dict):
        return out
    return {"spider": spider, "run_id": run_id, "status": "fail", "problems": [repr(out)], "counts": {}}


def _summary(results: list[dict]) -> str:
    rows = ["| spider | estado | ítems | problemas |", "|---|---|---|---|"]
    rows += [
        f"| {r['spider']} | {r['status']} | {sum(r['counts'].values())} | {'; '.join(r['problems'])} |"
        for r in sorted(results, key=lambda r: (r["status"] == "ok", r["spider"]))
    ]
    return "\n".join(rows)


@flow(name="daii-pipeline", task_runner=ThreadPoolTaskRunner(max_workers=4))
def pipeline(spiders: list[str] | None = None) -> dict:
    if unknown := set(spiders or []) - set(all_spiders()):
        raise ValueError(f"spiders inexistentes: {sorted(unknown)}")  # antes de crear carpetas fantasma en bronze
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    try:
        futures = {s: crawl.submit(s, run_id) for s in spiders or all_spiders()}
        # un spider que revienta (nombre mal escrito, error de import) es un `fail`, no aborta silver/gold
        results = [_result(s, run_id, f) for s, f in futures.items()]
        build_id = silver()
        counts = {"build_id": build_id, "gold": gold(build_id)}
    except Exception:
        notify.send("[daii] pipeline con error", traceback.format_exc())
        raise

    create_markdown_artifact(_summary(results), key="calidad-scrapers", description="Estado de cada spider en este run")
    bad = [r for r in results if r["status"] != "ok"]
    if bad:
        fails = sum(r["status"] == "fail" for r in bad)
        notify.send(
            f"[daii] {fails} fallas, {len(bad) - fails} avisos",
            notify.report(bad, "Para spiders en 'warn' o 'fail', se conserva su último run ok."),
        )
    if failed := [r["spider"] for r in bad if r["status"] == "fail"]:
        raise RuntimeError(f"spiders con fallas de calidad: {failed}")  # el flow queda en Failed en Prefect
    return counts
