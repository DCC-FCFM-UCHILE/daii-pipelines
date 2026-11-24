"""Settings de Scrapy. Todo lo que un spider escribe queda en data/bronze/<spider>/<run_id>/."""

from daii.config import BRONZE

BOT_NAME = 'daii'
SPIDER_MODULES = ['daii.bronze.spiders']
USER_AGENT = 'daii-bot/0.1 (+https://github.com/idia-tt/daii; IDIA FCFM U. de Chile)'
ROBOTSTXT_OBEY = True

# Sitios personales pequeños: ser amables (claudialopezmoncada.com devuelve 429 si se apura).
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0
AUTOTHROTTLE_ENABLED = True
RETRY_TIMES = 3
CLOSESPIDER_TIMEOUT = 3600  # un spider colgado termina como closespider_timeout → quality lo marca fail
DOWNLOAD_TIMEOUT = 30  # hosts académicos caídos no deben bloquear la corrida (default Scrapy: 180s)

# Playwright solo para requests con meta={"playwright": True} (sitios con JS o desafíos anti-bot).
DOWNLOAD_HANDLERS = {
    'http': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
    'https': 'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler',
}

# 540: process_response corre después de Retry (550), Compression (590) y Redirect (600) → se guarda el cuerpo
# ya descomprimido, sin 3xx ni reintentos fallidos.
DOWNLOADER_MIDDLEWARES = {'daii.bronze.middlewares.SavePagesMiddleware': 540}
ITEM_PIPELINES = {'daii.bronze.pipelines.ValidatePipeline': 100}
EXTENSIONS = {'daii.bronze.extensions.DumpStats': 500, 'daii.bronze.extensions.Logs': 0}

FEEDS = {
    str(BRONZE / '%(name)s' / '%(run_id)s' / 'items.jsonl'): {'format': 'jsonlines', 'encoding': 'utf8'},
}
# Scrapy no instala su handler: daii.log intercepta `logging` y lo manda a consola, log.jsonl y logs.sqlite.
LOG_ENABLED = False
