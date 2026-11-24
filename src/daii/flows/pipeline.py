"""Flow Prefect: bronze (spiders en paralelo) → quality → silver → gold → alerta por email."""

import os
import signal
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from uuid import uuid4

from prefect import flow, task
from prefect.artifacts import create_markdown_artifact
from prefect.runtime import flow_run
from prefect.task_runners import ThreadPoolTaskRunner
from scrapy.settings import Settings
from scrapy.spiderloader import SpiderLoader

from daii.config import BRONZE, ROOT
from daii.log import logger, setup
from daii.quality import checks, notify
from daii.quality.checks import last_good
from daii.versions import prepare, publish


def all_spiders() -> list[str]:
    s = Settings()
    s.setmodule('daii.bronze.settings')
    return sorted(SpiderLoader.from_settings(s).list())


CRAWL_TIMEOUT_S = 4200  # > CLOSESPIDER_TIMEOUT (3600) de bronze/settings.py


@task(task_run_name='crawl-{spider}')
def crawl(spider: str, run_id: str) -> dict:
    """Corre un spider en su propio proceso (el reactor de Twisted no se puede reiniciar) y evalúa el run."""
    log = logger.bind(componente='flow', spider=spider)
    # grupo de procesos propio: si hay que matarlo, también mueren sus hijos (Chromium de Playwright)
    proc = subprocess.Popen(
        [sys.executable, '-m', 'scrapy', 'crawl', spider, '-a', f'run_id={run_id}'],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        _, stderr = proc.communicate(timeout=CRAWL_TIMEOUT_S)  # respaldo de CLOSESPIDER_TIMEOUT
        if proc.returncode:
            # el detalle está en log.jsonl / logs.sqlite; la cola de stderr cubre fallas antes de abrir el spider
            log.bind(evento='scrapy_terminado').error(
                f'código {proc.returncode}; log en {BRONZE / spider / run_id / "log.jsonl"}\n{stderr[-3000:]}'
            )
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        log.bind(evento='scrapy_terminado').error(f'no terminó en {CRAWL_TIMEOUT_S} s; se mató el proceso y sus hijos')
    result = checks.check(spider, BRONZE / spider / run_id)
    log.bind(evento='run_evaluado').log(
        'INFO' if result['status'] == 'ok' else 'WARNING', '; '.join([result['status'], *result['problems']])
    )
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
    return {'spider': spider, 'run_id': run_id, 'status': 'fail', 'problems': [repr(out)], 'counts': {}}


def _en_uso(bad: list[dict]) -> str:
    """Qué run publica cada spider con problemas: un warn crónico deja datos viejos sin otro aviso."""
    lines = [f'  {r["spider"]}: {run.name if (run := last_good(r["spider"])) else "ninguno (no aparece)"}' for r in bad]
    return '\n'.join(["Para spiders en 'warn' o 'fail' se publica su último run ok:", *lines])


def _summary(results: list[dict]) -> str:
    rows = ['| spider | estado | ítems | problemas |', '|---|---|---|---|']
    rows += [
        f'| {r["spider"]} | {r["status"]} | {sum(r["counts"].values())} | {"; ".join(r["problems"])} |'
        for r in sorted(results, key=lambda r: (r['status'] == 'ok', r['spider']))
    ]
    return '\n'.join(rows)


@flow(name='daii-pipeline', task_runner=ThreadPoolTaskRunner(max_workers=4))
def pipeline(spiders: list[str] | None = None) -> dict:
    if unknown := set(spiders or []) - set(all_spiders()):
        raise ValueError(f'spiders inexistentes: {sorted(unknown)}')  # antes de crear carpetas fantasma en bronze
    run_id = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ-%f') + '-' + uuid4().hex[:8]
    setup('flow', prefect=True, run_id=run_id, flow_run_id=flow_run.id)
    try:
        futures = {s: crawl.submit(s, run_id) for s in spiders or all_spiders()}
        # un spider que revienta (nombre mal escrito, error de import) es un `fail`, no aborta silver/gold
        results = [_result(s, run_id, f) for s, f in futures.items()]
        build_id = silver()
        counts = {'build_id': build_id, 'gold': gold(build_id)}
    except Exception:
        notify.send('[daii] pipeline con error', traceback.format_exc())
        raise

    create_markdown_artifact(_summary(results), key='calidad-scrapers', description='Estado de cada spider en este run')
    bad = [r for r in results if r['status'] != 'ok']
    if bad:
        fails = sum(r['status'] == 'fail' for r in bad)
        notify.send(
            f'[daii] {fails} fallas, {len(bad) - fails} avisos',
            notify.report(bad, _en_uso(bad)),
        )
    if failed := [r['spider'] for r in bad if r['status'] == 'fail']:
        raise RuntimeError(f'spiders con fallas de calidad: {failed}')  # el flow queda en Failed en Prefect
    return counts
