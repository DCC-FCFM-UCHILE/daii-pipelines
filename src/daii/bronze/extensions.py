import json
from contextlib import ExitStack

from scrapy import signals

from daii.config import BRONZE
from daii.log import archivo, logger, setup


class Logs:
    """Logs del run: consola, bronze/<spider>/<run_id>/log.jsonl y data/logs.sqlite (ver daii.log).

    Se configura al abrir el spider (antes no se conoce el run_id): lo que Scrapy loguea al arrancar solo sale por
    stderr desde WARNING, y el flow guarda su cola si el proceso falla.
    """

    def __init__(self):
        self.files = ExitStack()

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls()
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        crawler.signals.connect(ext.engine_stopped, signal=signals.engine_stopped)
        return ext

    def spider_opened(self, spider):
        setup(f"bronze.{spider.name}", spider=spider.name, run_id=spider.run_id, persona=None)
        self.files.enter_context(archivo(BRONZE / spider.name / spider.run_id / "log.jsonl"))
        logger.bind(evento="spider_iniciado").info(f"persona={spider.only or 'todas'}")

    def spider_closed(self, spider, reason):
        logger.bind(evento="spider_terminado").info(f"finish_reason={reason}")

    def engine_stopped(self):  # después de "Dumping Scrapy stats" y "Spider closed", que llegan tras spider_closed
        self.files.close()


class DumpStats:
    """Escribe las stats de Scrapy a bronze/<spider>/<run_id>/stats.json al cerrar (insumo de quality)."""

    def __init__(self, stats):
        self.stats = stats

    @classmethod
    def from_crawler(cls, crawler):
        ext = cls(crawler.stats)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_closed(self, spider, reason):
        run = BRONZE / spider.name / spider.run_id
        run.mkdir(parents=True, exist_ok=True)
        stats = self.stats.get_stats() | {"finish_reason": reason}
        stats["expect"] = getattr(spider, "expect", {})
        (run / "stats.json").write_text(json.dumps(stats, default=str, indent=1))
