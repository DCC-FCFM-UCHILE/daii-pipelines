from pathlib import Path

from scrapy import Request
from scrapy.http import HtmlResponse, Response, TextResponse

from daii.bronze.items import bronze_item

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_response(name: str, url: str, persona: str, cls: type[Response] = HtmlResponse) -> Response:
    """Respuesta Scrapy construida desde un archivo guardado en tests/fixtures (sin red)."""
    req = Request(url, meta={"persona": persona})
    kw = {"encoding": "utf-8"} if issubclass(cls, TextResponse) else {}  # Response binario (PDF) no acepta encoding
    return cls(url=url, body=(FIXTURES / name).read_bytes(), request=req, **kw)


def run_parse(gen) -> dict[str, list[dict]]:
    """Ejecuta un callback, valida cada ítem contra el contrato bronze y los agrupa por tipo (ignora Requests)."""
    out: dict[str, list[dict]] = {}
    for x in gen:
        if isinstance(x, dict):
            item = bronze_item.validate_python(x).model_dump()
            out.setdefault(item["tipo"], []).append(item)
    return out
