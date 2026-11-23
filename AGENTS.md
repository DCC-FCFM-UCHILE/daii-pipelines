# AGENTS.md

Guía para agentes (y humanos) que trabajan en este repo. Léela entera antes de cambiar código.

## Qué es

Pipeline de datos para el dashboard de la DAII (FCFM, U. de Chile). Usa **scrapers custom en código**, no
extracción con LLM en cada corrida: las páginas cambian poco y un parser determinista es barato, testeable y auditable.
El modelo conceptual está en `docs/modelo_datos.md`.

## Comandos

```bash
uv sync                                   # instalar
uv run playwright install chromium        # una vez, para spiders con Playwright
uv run pytest                             # tests (parsers contra fixtures, sin red)
uv run ruff check --fix && uv run ruff format
uv run ty check src
uv run scrapy list                        # spiders disponibles
uv run scrapy crawl <spider> [-a persona=<slug>]   # un spider; escribe en data/raw/<spider>/<run_id>/
uv run daii run [--spiders a,b]           # pipeline completo: raw → quality → silver → gold (flow Prefect)
uv run daii serve                         # deployment programado (cron) en Prefect
```

## Arquitectura (medallion, por capas)

```
config/academicos.yaml  ──semillas──▶  src/daii/raw/      Scrapy (+Playwright) → data/raw/<spider>/<run_id>/
                                        src/daii/quality/  checks por run → quality.json + email si falla
                                        src/daii/silver/   Polars: normaliza/deduplica → data/silver/<tipo>.parquet
                                        src/daii/gold/     SQLModel: modelo relacional → data/gold/daii.sqlite
                                        src/daii/flows/    Prefect: orquesta todo
```

- **raw** = lo que dice la fuente, casi sin tocar. Cada run guarda `items.jsonl`, `pages/` (HTML/PDF gzip
  original), `pages.jsonl` (índice), `stats.json` (stats Scrapy) y `quality.json`.
- **silver** usa, por spider, el **último run que no falló quality**. Si un scraper se rompe, el dashboard
  sigue mostrando los últimos datos buenos.
- **gold** se reconstruye completo cada vez desde silver (idempotente). No editar la SQLite a mano.
- Las capas solo dependen hacia atrás (gold lee silver, silver lee raw). Nunca al revés.

## Cómo escribir un spider

Hay dos clases:

1. **Plataforma** (`spiders/orcid.py`, `openalex.py`, `dblp.py`, `ucurriculum.py`): un spider para *todos*
   los académicos que tengan ese perfil en `config/academicos.yaml`. Usar la API oficial cuando exista.
2. **Sitio personal** (`spiders/sites/<slug>.py`): uno por académico/a. Cubre su sitio, sus subpáginas
   y su CV.

Reglas:

- Heredar de `AcademicSpider` (`spiders/base.py`). Pedir las páginas propias con `self.page(url, callback, persona)`
  desde `async def start(self)`. Así quedan registradas y `related()` no las duplica.
- Emitir ítems **solo** con `self.item(tipo, response, **campos)`. Los campos válidos por tipo están en
  `raw/items.py` (pydantic, `extra="forbid"`). Un ítem inválido se descarta y quality lo reporta.
- Llamar `yield from self.related(response)` en cada página propia: registra todos los links salientes (`link`)
  y sigue (profundidad 1) los del mismo dominio o de `config/whitelist.yaml` (`pagina`). Pasar `region=` si la
  página tiene menús de navegación ajenos al académico.
- Raw guarda **texto como aparece**: no traducir, no mapear a catálogos, no inferir. Solo `clean()`/`texts()` y,
  cuando sea obvio, separar campos (título/venue/año). Lo demás va en silver.
- Declarar `expect = {"tipo": mínimo}` con los mínimos que una corrida sana debe traer (con margen, por ejemplo
  ~50% de lo que hay hoy). Es la alarma principal cuando un sitio cambia de estructura.
- Usar Playwright (`meta={"playwright": True}`) solo si hace falta JS o un desafío anti-bot (p. ej. DBLP/Anubis).
- PDFs: el `Response` no es texto. Usar `pypdf` sobre `response.body`.
- Helpers compartidos entre spiders (p. ej. `autores()`) van en `spiders/base.py`, nunca se importan de otro spider.
- No extraer datos sensibles (RUT, fecha de nacimiento, dirección particular, datos de terceros como emails de referencias).
- Nombre del spider: `sitio_<slug_con_guiones_bajos>` para sitios personales (p. ej. `sitio_felipe_bravo`).

### Test obligatorio por spider

- Guardar la(s) página(s) en `tests/fixtures/` (HTML o PDF tal como se descargan).
- `tests/spiders/test_<spider>.py`: construir la respuesta con `fixture_response(...)` y validar con
  `run_parse(...)` (ver `tests/spiders/test_ucurriculum.py`). Verificar valores concretos (un título, un año,
  un DOI) y cantidades mínimas, no solo que "algo" salió.
- Cuando un sitio cambie: descargar la página nueva sobre el fixture, ajustar el parser y correr el test.

## Observabilidad

- Cada flow y task es visible en la UI de Prefect (`uv run prefect server start` → http://127.0.0.1:4200).
- `quality` evalúa cada run: `fail` si el spider no terminó bien, si no trajo ítems o si no alcanzó `expect`;
  `warn` si cayó >50% respecto al run bueno anterior, si hubo ítems inválidos, excepciones en parsers o páginas propias que no bajaron (los links relacionados caídos no alertan).
- Al final del flow se manda **un email** con la tabla de problemas (si hubo). Variables: `SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_FROM`, `ALERT_TO` (ver `.env.example`). Sin SMTP
  configurado solo se loguea.

## Convenciones

- Python 3.14, `uv`, `ruff` (line-length 120), `ty`. Polars, no pandas.
- Identificadores estables: `slug` de persona (config), DOI, ORCID, código de proyecto.
- Código y nombres de dominio en español (como el modelo de datos). Nombres técnicos en inglés cuando son de librería.
- `data/` no se versiona.
- No scrapear Google Scholar (bloquea y sus términos lo prohíben). Respetar `robots.txt`.
