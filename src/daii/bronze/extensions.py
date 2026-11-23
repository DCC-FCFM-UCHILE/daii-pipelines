import json

from scrapy import signals

from daii.config import BRONZE


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
