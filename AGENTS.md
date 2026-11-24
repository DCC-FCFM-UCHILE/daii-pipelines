# AGENTS.md

Guía para agentes (y humanos) que trabajan en este repo. Léela entera antes de cambiar código.

## Qué es

Pipeline de datos para el dashboard de la DAII (FCFM, U. de Chile). Usa **scrapers custom en código**, no
extracción con LLM en cada corrida: las páginas cambian poco y un parser determinista es barato, testeable y auditable.
El modelo conceptual está en `docs/modelo_datos.md`.

## Comandos

`make help` lista atajos comunes (`make install`, `make check`, `make run`, `make crawl SPIDER=… PERSONA=…`).

```bash
uv sync                                   # instalar
uv run playwright install chromium        # una vez, para spiders con Playwright
uv run pre-commit install --allow-missing-config  # instala los hooks de código y de mensaje
uv run pytest                             # tests (parsers contra fixtures, sin red)
uv run ruff check --fix && uv run ruff format
uv run ty check src
uv run scrapy list                        # spiders disponibles
uv run scrapy crawl <spider> [-a persona=<slug>]   # un spider; escribe en data/bronze/<spider>/<run_id>/
uv run daii run [--spiders a,b]           # pipeline completo: bronze → quality → silver → gold (flow Prefect)
uv run daii serve                         # deployment programado (cron) en Prefect
uv run daii explorar                      # explorador local (Streamlit) de bronze, silver y gold: http://localhost:8501
```

## Arquitectura (medallion, por capas)

```
config/academicos.yaml  ──semillas──▶  src/daii/bronze/      Scrapy (+Playwright) → data/bronze/<spider>/<run_id>/
                                        src/daii/quality/  checks por run → quality.json + email si falla
                                        src/daii/silver/   Polars: normaliza/deduplica → data/versions/<build_id>/silver/
                                        src/daii/gold/     SQLModel + Alembic → data/gold/daii.sqlite
                                        src/daii/flows/    Prefect: orquesta todo
                                        src/daii/explorar/ Streamlit: explorador local, solo lee data/
```

- **bronze** = lo que dice la fuente, casi sin tocar. Cada run guarda `items.jsonl`, `pages/` (HTML/PDF gzip
  original), `pages.jsonl` (índice), `stats.json` (stats Scrapy) y `quality.json`.
- **silver** usa, por spider, el **último run `ok`** de quality (`warn` y `fail` no se publican). Si un scraper se
  rompe, el dashboard sigue mostrando los últimos datos buenos; el email dice qué run se está usando.
- **gold** se reconstruye completo cada vez desde silver (idempotente). No editar la SQLite a mano. El esquema lo
  crean las migraciones de Alembic (`src/daii/gold/migrations/`): al cambiar `gold/models.py`, correr
  `make migration MSG="..."`, revisar el archivo generado y commitearlo (un test exige que coincidan).
- Las capas solo dependen hacia atrás (gold lee silver, silver lee bronze). Nunca al revés.
- `explorar/` es solo presentación: lee las tres capas y nunca escribe en `data/`; nada del pipeline lo importa. Su
  diseño (identidad FCFM, estados, gráficos) está en `DESIGN.md` y el producto en `PRODUCT.md`.

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
  `bronze/items.py` (pydantic, `extra="forbid"`). Un ítem inválido se descarta y quality lo reporta.
- Llamar `yield from self.related(response)` en cada página propia: registra todos los links salientes (`link`)
  y sigue (profundidad 1) los del mismo dominio o de `config/whitelist.yaml` (`pagina`). Pasar `region=` si la
  página tiene menús de navegación ajenos al académico.
- Bronze guarda **texto como aparece**: no traducir, no mapear a catálogos, no inferir. Solo `clean()`/`texts()` y,
  cuando sea obvio, separar campos (título/venue/año). Lo demás va en silver.
- Declarar `expect = {"tipo": mínimo}` con los mínimos que una corrida sana debe traer (con margen, por ejemplo
  ~50% de lo que hay hoy). Es la alarma principal cuando un sitio cambia de estructura.
- Usar Playwright (`meta={"playwright": True}`) solo si hace falta JS o un desafío anti-bot (p. ej. DBLP/Anubis).
- Logs con `daii.log.logger` y un `evento` (ver "Logs"), nunca `self.logger` ni `print`. Si el problema debe alertar,
  además sumar una stat que `quality` lea (p. ej. `daii/page_error`): los logs no cambian el estado del run.
- PDFs: el `Response` no es texto. Usar `pypdf` sobre `response.body`.
- Helpers compartidos van en `spiders/base.py`, nunca se importan de otro spider. Ya existen: `clean`, `texts`,
  `plain`, `anio`/`anios`, `autores`, `email`, `abs_url`, `pdf_texto`, `latex_acentos`, `redact`.
- URLs: pasar el href **crudo** (o `None`) en `url_destino`, `url_organizacion`, `url_curso` y `foto_url`; `item()` las
  vuelve absolutas. Nunca `response.urljoin(x.get(""))`: con href vacío devuelve la URL de la página (dato falso).
- `tipo_actividad` es un vocabulario cerrado (`TipoActividad` en `bronze/items.py`): mapear la sección de la fuente a
  ese vocabulario y dejar el texto original en `descripcion` o `rol`.
- Si no hay título de tesis, `titulo=None`. Nunca rellenar con el programa, el nivel o la línea completa del CV.
- Páginas con datos sensibles en el documento (CVs con RUT): pedirlas con `self.page(..., guardar=False)` para que no
  se archiven en `pages/`.
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
  `warn` si cayó >50% respecto al run ok anterior (por tipo y por persona+tipo), si hubo ítems inválidos, excepciones
  en parsers, páginas propias que no bajaron o pestañas incompletas (los links relacionados caídos no alertan).
- Al final del flow se manda **un email** con la tabla de problemas (si hubo). Variables: `SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_FROM`, `ALERT_TO` (ver `.env.example`). Sin SMTP
  configurado solo se loguea.

## Logs

Todo el código emite con loguru vía `daii.log` (configuración única en `src/daii/log.py`):

```python
from daii.log import logger

logger.bind(evento='pagina_fallida', persona=slug, url=url).error(f'página propia falló: {err}')
```

- **Campos estándar** (`log.CAMPOS`): `componente`, `evento`, `spider`, `persona`, `run_id`, `build_id`,
  `flow_run_id`, `url`. Cualquier otro campo enlazado queda en `extra` (JSON). Pasar contexto con `bind()`, no con
  kwargs del mensaje (loguru formatearía las llaves del texto).
- **`evento`**: código estable en snake_case que describe qué pasó (`pagina_fallida`, `pestania_incompleta`,
  `run_evaluado`, `silver_preparado`, `gold_publicado`…). Sin `evento` queda `log`. Reutilizar los existentes.
- Solo los puntos de entrada llaman `setup()` (CLI, flow, extensión `Logs` de Scrapy); las librerías solo emiten.
  `logging` estándar (Scrapy, Playwright, etc.) se intercepta y llega con `componente` = nombre del logger.
- **Dónde queda:** consola (texto; dentro de Prefect, en su UI), `bronze/<spider>/<run_id>/log.jsonl` y
  `versions/<build_id>/log.jsonl` (JSON por línea) y `data/logs.sqlite` (todo desde INFO; solo crece).
  Consultar con `uv run daii logs [--run-id X] [--spider S] [--nivel WARNING] [--desde 2026-11-01]`.
- `logs.sqlite` es persistente: su esquema cambia solo con una migración (`make migration ESQUEMA=logs MSG="..."`).

## Convenciones

- Python 3.14, `uv`, `ruff` (line-length 120), `ty`. Polars, no pandas.
- Identificadores estables: `slug` de persona (config), DOI, ORCID, código de proyecto.
- Código y nombres de dominio en español (como el modelo de datos). Nombres técnicos en inglés cuando son de librería.
- `data/` no se versiona.
- No scrapear Google Scholar (bloquea y sus términos lo prohíben). Respetar `robots.txt`.

## Flujo de cambios y revisión

1. Trabajar en una rama, nunca directo en `main`.
2. Revisar el código con el revisor **ponytail** (`/ponytail-review`) mediante **handoffs independientes y sin
   contexto previo**: un revisor por conjunto de módulos (núcleo bronze, spiders de plataforma, spiders de sitios,
   quality/silver/gold/flows). Cada revisor recibe solo la lista de archivos; así no hereda los supuestos de quien
   escribió el código.
3. Aplicar las observaciones (o justificar por qué no) y volver a correr `pytest`, `ruff` y `ty`.
4. Antes de mergear, revisar el diff final otra vez con ponytail.
5. Abrir el PR y subir la revisión (hallazgos y cómo se resolvieron) como comentario del PR.
