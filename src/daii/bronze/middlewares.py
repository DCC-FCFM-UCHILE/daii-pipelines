import gzip
import hashlib
import json

from daii.bronze.spiders.base import redact
from daii.config import BRONZE


class SavePagesMiddleware:
    """Guarda cada respuesta tal cual (gzip) en bronze/<spider>/<run_id>/pages/, más un índice pages.jsonl.

    Permite re-parsear sin volver a scrapear y depurar cuando una página cambia de estructura.
    """

    def process_response(self, request, response, spider):
        # robots.txt de Scrapy, o páginas marcadas page(..., guardar=False) (p. ej. CVs con RUT en la cabecera)
        if request.meta.get("dont_obey_robotstxt") or request.meta.get("guardar") is False:
            return response
        run = BRONZE / spider.name / spider.run_id
        (run / "pages").mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(response.url.encode()).hexdigest() + ".gz"
        (run / "pages" / name).write_bytes(gzip.compress(response.body))
        entry = {
            "url": redact(response.url),
            "status": response.status,
            "content_type": response.headers.get("Content-Type", b"").decode(errors="replace"),
            "file": f"pages/{name}",
        }
        with (run / "pages.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return response
