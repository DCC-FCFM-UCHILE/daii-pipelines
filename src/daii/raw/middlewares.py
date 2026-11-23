import gzip
import hashlib
import json

from daii.config import RAW


class SavePagesMiddleware:
    """Guarda cada respuesta tal cual (gzip) en raw/<spider>/<run_id>/pages/, más un índice pages.jsonl.

    Permite re-parsear sin volver a scrapear y depurar cuando una página cambia de estructura.
    """

    def process_response(self, request, response, spider):
        run = RAW / spider.name / spider.run_id
        (run / "pages").mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(response.url.encode()).hexdigest() + ".gz"
        (run / "pages" / name).write_bytes(gzip.compress(response.body))
        entry = {
            "url": response.url,
            "status": response.status,
            "content_type": response.headers.get("Content-Type", b"").decode(errors="replace"),
            "file": f"pages/{name}",
        }
        with (run / "pages.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")
        return response
