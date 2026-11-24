# daii

Datos para el dashboard de la **Dirección Académica, de Investigación e Innovación (DAII)** de la FCFM, U. de Chile:
académicos, afiliaciones, áreas, publicaciones, tesis, proyectos y fondos, cursos, vinculación con el medio,
productos y perfiles. Todo se obtiene con **scrapers custom por fuente** (Scrapy + Playwright) y se organiza
en una arquitectura **medallion** (bronze → silver → gold), orquestada con **Prefect**.

- Modelo conceptual: [`docs/modelo_datos.md`](docs/modelo_datos.md)
- Guía para contribuir y para agentes de código: [`AGENTS.md`](AGENTS.md)

## Inicio rápido

```bash
uv sync
uv run playwright install chromium
cp .env.example .env          # SMTP para alertas, API key OpenAlex (opcionales)
uv run daii run               # todos los spiders → data/gold/daii.sqlite
```

Otros comandos (`make help` muestra los atajos equivalentes):

```bash
uv run daii spiders                         # lista de spiders
uv run daii run --spiders orcid,ucurriculum # solo algunos
uv run scrapy crawl sitio_marcos_orchard -a persona=marcos-orchard   # un spider suelto (depuración)
uv run daii silver && uv run daii gold      # reconstruir capas sin volver a scrapear
uv run prefect server start                 # UI en http://127.0.0.1:4200
uv run daii serve --cron "0 6 * * 1"        # ejecución programada (lunes 06:00)
uv run daii explorar                        # explorador de datos (Streamlit) en http://localhost:8501
uv run pytest && uv run ruff check && uv run ty check src
```

## Commits y releases

Instala los hooks locales con `uv run pre-commit install --allow-missing-config`.
Los hooks verifican portabilidad de archivos, sintaxis, claves privadas y formato. Los correctores de texto
preservan las fixtures de los scrapers tal como se descargaron.
Usa Conventional Commits en los commits y en el título de cada PR, por ejemplo `fix(bronze): valida el código de proyecto`.
GitHub solo permite squash merge y propone el título del PR como mensaje del commit en `main`.

Tras pasar el CI en `main`, Commitizen actualiza la versión del proyecto y crea un tag `vX.Y.Z`. GitHub publica
la release con un changelog generado a partir de los PR fusionados desde la release anterior.

| Título del PR | Versión |
|---|---|
| `tipo!:` o `tipo(ámbito)!:` | Major |
| `feat:`, `perf:` | Minor |
| `fix:`, `refactor:` | Patch |
| `chore:`, `docs:`, `style:`, otros | Se incluyen en la próxima release |

Si la publicación falla después de subir el tag, ejecuta el workflow **CI** manualmente sobre `main` para completarla.

## Arquitectura

```mermaid
flowchart LR
    cfg[config/academicos.yaml<br/>config/whitelist.yaml] --> bronze
    subgraph bronze [bronze · Scrapy]
      p[Plataformas<br/>orcid · openalex · dblp · ucurriculum]
      s[Sitios personales<br/>sitio_&lt;slug&gt;]
      r[Links relacionados<br/>profundidad 1, lista blanca]
    end
    bronze -->|items.jsonl, pages/, stats.json| q[quality<br/>ok / warn / fail]
    q -->|último run ok por spider| silver[silver · Polars<br/>parquet por tipo]
    silver --> gold[gold · SQLModel<br/>SQLite]
    q -->|problemas| mail[email]
    gold --> dash[dashboard]
```

| Capa | Dónde | Qué contiene |
|---|---|---|
| bronze | `data/bronze/<spider>/<run_id>/` | `items.jsonl` (ítems validados con pydantic, texto como en la fuente), `pages/` (respuestas originales gzip), `stats.json`, `quality.json` |
| silver | `data/versions/<build_id>/silver/<tipo>.parquet` | Por persona: normalizado (DOI, catálogos de tipo de publicación, nivel de formación, instrumento) y deduplicado entre fuentes, con `fuentes` y `confianza` |
| gold | `data/gold/daii.sqlite` | Modelo relacional (`src/daii/gold/models.py`): entidades compartidas (publicación, proyecto, tesis, curso, producto) con tablas puente a `academico` y estado de cada scraper (`scraperun`) |

### Fuentes

| Spider | Fuente | Para quién |
|---|---|---|
| `orcid` | API pública ORCID v3 | quien tenga `orcid` en config |
| `openalex` | API OpenAlex (autor + obras, métricas) | quien tenga `orcid` |
| `dblp` | SPARQL oficial de DBLP | quien tenga `dblp` |
| `ucurriculum` | Fichas FCFM (`dcc.uchile.cl/nosotros/academico/...`): cursos por semestre, tesis guiadas, proyectos, publicaciones | quien tenga `ucurriculum` |
| `portafolio` | Portafolio Académico U. de Chile (fuente oficial: nombramientos, cargos, docencia U-Campus, publicaciones con indexación WoS/Scopus, proyectos, tesis, extensión). SPA: Playwright + paginación por clics | quien tenga `portafolio` |
| `cmm` | Fichas de investigadores del CMM | quien tenga `cmm` |
| `cr2` | Fichas del CR2 (papers con línea CR2, indexación y acceso abierto) | quien tenga `cr2` |
| `anid` | Portal del Investigador ANID (currículo, producción con DOI, proyectos con fuente y años; sin código ni rol) | quien tenga `anid` |
| `sitio_<slug>` | Sitio personal y CV, un spider por persona | cada académico/a |

Notas:

- **DBLP:** sus páginas HTML están detrás de Anubis, que bloquea navegadores automatizados. No se evade: se usa su endpoint SPARQL.
- **OpenAlex:** desambigua autores automáticamente y a veces mezcla homónimos. Lo que solo él reporta queda con `confianza = 0.5`.
- **Portafolio:** su API interna exige una credencial y responde ofuscada, así que no se usa directamente: se lee el DOM renderizado, como lo vería cualquier visitante.
- **Maisa Rojas:** `dgf.uchile.cl` publica un registro DNS `127.0.0.1` y tiene la cadena TLS incompleta, así que su sitio no tiene spider (la cubren ORCID y OpenAlex).
- **Google Scholar:** no se scrapea (lo prohíbe y bloquea).

### Agregar un académico

1. Agregar su entrada en `config/academicos.yaml` (slug, nombre, unidad, perfiles). Solo con eso los spiders
   de plataforma ya lo cubren.
2. Si tiene sitio propio, escribir `src/daii/bronze/spiders/sites/<slug>.py` y su test según `AGENTS.md`.

## Observabilidad

- **Prefect UI:** cada corrida, spider (`crawl-<spider>`), log y duración. Cada flow publica el artefacto
  `calidad-scrapers` con una tabla de estado por spider.
- **Logs** (`src/daii/log.py`, loguru): un mismo formato para spiders, quality, silver, gold y el flow, con
  `componente`, `evento`, `spider`, `persona` y `run_id`. Se ven en consola y Prefect, quedan en `log.jsonl` de cada
  corrida y versión, y en `data/logs.sqlite`: `uv run daii logs --nivel WARNING` o `make logs`.
- **Quality** (`src/daii/quality/checks.py`), por run:
  - `fail`: crash, 0 ítems o bajo el mínimo `expect` del spider. Ese run no se usa: silver y gold mantienen el último run `ok`.
  - `warn`: caída >50% de algún tipo, en total o para una persona, respecto al run ok anterior, ítems inválidos, excepciones en parsers, páginas propias caídas o pestañas de Portafolio incompletas. Tampoco se publica. Los links externos caídos no alertan.
- **Email:** un solo correo por corrida con los spiders en `fail`/`warn` y el run que se publica de cada uno, más otro si el pipeline se cae.
  Se configura con las variables `SMTP_*` y `ALERT_*` de `.env`.
- **Tabla `scraperun` en gold:** el dashboard puede mostrar la salud de cada fuente y la fecha de su último dato bueno.

## Pendientes conocidos

- Normalizar organizaciones (tabla `Organizacion` + ROR) y áreas a una taxonomía (OCDE/ANID).
- Coautores y estudiantes como personas propias (hoy son texto).
- Montos de proyectos: ANID publica bases abiertas que se pueden cruzar por código.
- Cursos: las fichas DCC cubren 7 años; para el resto hay que pedirle una exportación de U-Campus a la DAII.


### Versiones locales

`uv run daii silver` prepara un candidato e imprime su identificador.
`uv run daii gold --build-id <id>` publica ese candidato bajo
`DAII_DATA/versions/<id>/` y actualiza la SQLite vigente. El flow programado pasa
el identificador automáticamente. `uv run daii versions` lista los manifiestos y
`uv run daii diff <anterior> <posterior>` compara las filas de dos versiones.
`uv run daii gold --build-id <id>` con una versión ya publicada vuelve a ella (rollback) sin reconstruirla.
Una versión anterior a la vigente que nunca se publicó se rechaza.

El esquema de cada SQLite lo crean las migraciones de Alembic (`src/daii/gold/migrations/`); la tabla
`alembic_version` dice con qué revisión se construyó. Al cambiar `gold/models.py`: `make migration MSG="..."`.

La publicación selecciona la última corrida `ok` de cada spider. Un `warn` o
`fail` posterior queda visible en `scraperun` y se conserva la corrida `ok`
previa. El manifiesto fija las corridas antes de leer los Parquet en Gold.
