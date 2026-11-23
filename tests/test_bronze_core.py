import pytest
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from scrapy.utils.test import get_crawler

from daii.bronze.pipelines import ValidatePipeline
from daii.bronze.spiders.base import AcademicSpider


def test_save_pages_corre_despues_de_descomprimir_redirigir_y_reintentar():
    s = Settings()
    s.setmodule("daii.bronze.settings")
    base = s.getdict("DOWNLOADER_MIDDLEWARES_BASE")
    mine = s.getdict("DOWNLOADER_MIDDLEWARES")["daii.bronze.middlewares.SavePagesMiddleware"]
    # process_response va de mayor a menor prioridad: el middleware debe quedar por debajo de estos tres.
    for mw in ("HttpCompressionMiddleware", "RedirectMiddleware", "RetryMiddleware"):
        prio = next(v for k, v in base.items() if k.endswith(mw))
        assert mine < prio, mw


def test_item_invalido_se_descarta_y_cuenta():
    crawler = get_crawler(AcademicSpider)
    spider = crawler._create_spider("t")
    meta = {"persona": "x", "url": "u", "spider": "t", "run_id": "r", "scraped_at": "s"}
    pipe = ValidatePipeline()
    assert pipe.process_item({"tipo": "area", "nombre": "IA", **meta}, spider)["nombre"] == "IA"
    with pytest.raises(DropItem):
        pipe.process_item({"tipo": "area", "nombre": "IA", "campo_extra": 1, **meta}, spider)
    assert crawler.stats.get_value("daii/invalid_item/area") == 1
