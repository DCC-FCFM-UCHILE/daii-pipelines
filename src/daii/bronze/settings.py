"""Settings de Scrapy. Todo lo que un spider escribe queda en data/bronze/<spider>/<run_id>/."""

from daii.config import BRONZE

BOT_NAME = "daii"
SPIDER_MODULES = ["daii.bronze.spiders"]
USER_AGENT = "daii-bot/0.1 (+https://github.com/idia-tt/daii; IDIA FCFM U. de Chile)"
ROBOTSTXT_OBEY = True

# Sitios personales pequeños: ser amables (claudialopezmoncada.com devuelve 429 si se apura).
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = 1.0
AUTOTHROTTLE_ENABLED = True
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524, 408]
RETRY_TIMES = 3
DOWNLOAD_TIMEOUT = 30  # hosts académicos caídos no deben bloquear la corrida (default Scrapy: 180s)

# Playwright solo para requests con meta={"playwright": True} (sitios con JS o desafíos anti-bot).
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}

DOWNLOADER_MIDDLEWARES = {"daii.bronze.middlewares.SavePagesMiddleware": 950}
ITEM_PIPELINES = {"daii.bronze.pipelines.ValidatePipeline": 100}
EXTENSIONS = {"daii.bronze.extensions.DumpStats": 500}

FEEDS = {
    str(BRONZE / "%(name)s" / "%(run_id)s" / "items.jsonl"): {"format": "jsonlines", "encoding": "utf8"},
}
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"
