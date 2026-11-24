import gzip
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from daii.bronze.spiders.base import redact
from daii.config import BRONZE


def archive_observation(spider, entry: dict, body: bytes | None) -> str:
    run = BRONZE / spider.name / spider.run_id
    run.mkdir(parents=True, exist_ok=True)
    observation = uuid4().hex
    body_hash = filename = None
    if body is not None:  # None = página con datos sensibles (guardar=False): solo queda en el índice
        body_hash = hashlib.sha256(body).hexdigest()
        filename = f"pages/{body_hash}.gz"
        if not (run / filename).exists():
            (run / "pages").mkdir(exist_ok=True)
            (run / filename).write_bytes(gzip.compress(body, mtime=0))
    record = entry | {
        "observacion_id": observation,
        "capturado_en": datetime.now(UTC).isoformat(),
        "file": filename,
        "sha256": body_hash,
    }
    with (run / "pages.jsonl").open("a") as f:
        f.write(json.dumps(record) + "\n")
    return observation


class SavePagesMiddleware:
    """Guarda cada respuesta tal cual (gzip) en bronze/<spider>/<run_id>/pages/, más un índice pages.jsonl.

    Permite re-parsear sin volver a scrapear y depurar cuando una página cambia de estructura.
    """

    def process_response(self, request, response, spider):
        # Scrapy descarga robots.txt por separado.
        if request.meta.get("dont_obey_robotstxt"):
            return response
        redirects = request.meta.get("redirect_urls", [])
        entry = {
            "url_solicitada": redact(redirects[0] if redirects else request.url),
            "redirects": [redact(url) for url in redirects],
            "persona": request.meta.get("persona"),
            "modo": "playwright" if request.meta.get("playwright") else "http",
            "url": redact(response.url),
            "status": response.status,
            "content_type": response.headers.get("Content-Type", b"").decode(errors="replace"),
        }
        body = response.body if request.meta.get("guardar") is not False else None
        request.meta["observacion_id"] = archive_observation(spider, entry, body)
        return response
