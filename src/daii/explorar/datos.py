"""Lectura de las tres capas para el explorador. Solo lee: nunca escribe en data/.

Cada loader cacheado recibe la firma (ruta, mtime) de lo que lee: si el pipeline publica de nuevo, el caché se invalida
solo y la app no muestra datos viejos.
"""

import json
import sqlite3
from pathlib import Path

import polars as pl
import streamlit as st

from daii.config import BRONZE, GOLD_DB, SILVER, academicos
from daii.gold.load import run_manifest
from daii.log import NIVELES, logs_db
from daii.quality.checks import runs
from daii.silver.transform import norm_text
from daii.versions import VERSIONS

# tipo (nombre en bronze/silver) → (etiqueta, SQL gold con una fila por académico, columna de año)
TIPOS: dict[str, tuple[str, str, str | None]] = {
    "publicacion": (
        "Publicaciones",
        "SELECT pa.academico_id, p.titulo, p.anio, p.tipo, p.venue, p.doi, p.url, p.citas, pa.fuentes, pa.confianza"
        " FROM publicacionacademico pa JOIN publicacion p ON p.id = pa.publicacion_id",
        "anio",
    ),
    "proyecto": (
        "Proyectos",
        "SELECT pp.academico_id, p.titulo, p.codigo, p.instrumento, pp.rol, p.anio_inicio, p.anio_fin, p.monto,"
        " pp.fuentes FROM participacionproyecto pp JOIN proyecto p ON p.id = pp.proyecto_id",
        "anio_inicio",
    ),
    "tesis": (
        "Tesis",
        "SELECT d.academico_id, t.titulo, t.estudiante, t.nivel, t.anio, t.programa, d.rol, t.url, d.fuentes"
        " FROM direcciontesis d JOIN tesis t ON t.id = d.tesis_id",
        "anio",
    ),
    "dictacion": (
        "Docencia",
        "SELECT d.academico_id, c.codigo, c.nombre, d.anio, d.semestre, d.rol, d.institucion, d.fuente"
        " FROM dictacion d JOIN curso c ON c.id = d.curso_id",
        "anio",
    ),
    "actividad": (
        "Actividades",
        "SELECT academico_id, tipo, titulo, evento, fecha, rol, descripcion, url, fuente FROM actividad",
        None,
    ),
    "producto": (
        "Productos",
        "SELECT pa.academico_id, p.nombre, p.tipo, pa.rol, p.descripcion, p.url"
        " FROM productoacademico pa JOIN producto p ON p.id = pa.producto_id",
        None,
    ),
    "distincion": ("Distinciones", "SELECT academico_id, nombre, otorgante, anio, fuente FROM distincion", "anio"),
    "formacion": (
        "Formación",
        "SELECT academico_id, nivel, grado, institucion, anio, titulo_tesis, fuente FROM formacion",
        "anio",
    ),
    "afiliacion": (
        "Afiliaciones",
        "SELECT academico_id, organizacion, rol, desde, hasta, url_organizacion, fuente FROM afiliacion",
        None,
    ),
    "area": ("Áreas", "SELECT academico_id, nombre, fuente FROM area", None),
    "metrica": ("Métricas", "SELECT academico_id, plataforma, nombre, valor, anio FROM metrica", "anio"),
    "perfil": ("Perfiles", "SELECT academico_id, plataforma, url, identificador, fuente FROM perfilexterno", None),
    "link": (
        "Links",
        "SELECT academico_id, url_origen, url_destino, texto, seguido, fuente FROM linkdescubierto",
        None,
    ),
    "pagina": ("Páginas", "SELECT academico_id, url, titulo FROM paginarelacionada", None),
}
CAPAS = ("bronze", "silver", "gold")


def _firma(path: Path) -> tuple[str, float]:
    return str(path), path.stat().st_mtime if path.exists() else 0.0


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def nombres() -> dict[str, str]:
    return {a["slug"]: a["nombre"] for a in academicos()}


# --- gold ---------------------------------------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _sql(sql: str, firma: tuple[str, float]) -> pl.DataFrame:
    with _ro(Path(firma[0])) as db:
        return pl.read_database(sql, db, infer_schema_length=None)


def gold_sql(sql: str) -> pl.DataFrame:
    """Consulta a la SQLite publicada; DataFrame vacío si todavía no hay gold."""
    return _sql(sql, _firma(GOLD_DB)) if GOLD_DB.exists() else pl.DataFrame()


def gold(tipo: str) -> pl.DataFrame:
    return gold_sql(TIPOS[tipo][1])


def release() -> dict | None:
    """Versión publicada en gold y su manifiesto (si la versión sigue en data/versions)."""
    tablas = gold_sql("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'datarelease'")
    rows = gold_sql("SELECT build_id, published_at FROM datarelease") if not tablas.is_empty() else tablas
    if rows.is_empty():  # gold previo al versionado, o sin publicar
        return None
    row = rows.row(0, named=True)
    manifest = VERSIONS / row["build_id"] / "manifest.json"
    return {**row, "manifest": json.loads(manifest.read_text()) if manifest.exists() else None}


# --- silver -------------------------------------------------------------------------------------------------------


def silver_dir() -> Path:
    """Silver del build publicado; sin release (instalaciones previas al versionado) cae a data/silver."""
    published = release()
    directory = VERSIONS / published["build_id"] / "silver" if published else None
    return directory if directory and directory.is_dir() else SILVER


@st.cache_data(show_spinner=False)
def _parquet(firma: tuple[str, float]) -> pl.DataFrame:
    return pl.read_parquet(firma[0])


def silver(tipo: str) -> pl.DataFrame:
    f = silver_dir() / f"{tipo}.parquet"
    return _parquet(_firma(f)) if f.exists() else pl.DataFrame()


# --- bronze -------------------------------------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _bronze(firmas: tuple[tuple[str, float], ...]) -> dict[str, pl.DataFrame]:
    frames = [pl.read_ndjson(f, infer_schema_length=None) for f, _ in firmas]
    if not frames:
        return {}
    todo = pl.concat(frames, how="diagonal_relaxed")
    return {
        tipo: df.select([c for c in df.columns if df[c].null_count() < df.height])  # columnas de otros tipos
        for (tipo,), df in todo.partition_by("tipo", as_dict=True).items()
    }


def bronze_runs() -> list[dict]:
    """Estado por spider (`gold.load.run_manifest`): último run evaluado y el run que alimenta silver."""
    return run_manifest() if BRONZE.exists() else []


def bronze(tipo: str, *, run_ids: dict[str, str] | None = None) -> pl.DataFrame:
    """Ítems bronze de un tipo, del run en uso de cada spider (o del run indicado por spider)."""
    elegidos = run_ids or {r["spider"]: r["run_en_uso"] for r in bronze_runs() if r["run_en_uso"]}
    files = [BRONZE / spider / run / "items.jsonl" for spider, run in sorted(elegidos.items())]
    return _bronze(tuple(_firma(f) for f in files if f.is_file())).get(tipo, pl.DataFrame())


# --- trazabilidad y agregados -------------------------------------------------------------------------------------


def con_fuente(df: pl.DataFrame) -> pl.DataFrame:
    """Columna `fuente` = spider. Silver de publicaciones ya fusionó fuentes: una fila por fuente que la reporta."""
    if df.is_empty():
        return df
    if "spider" in df.columns:
        return df.with_columns(fuente=pl.col("spider"))
    if "fuentes" in df.columns:
        fuentes = pl.col("fuentes")
        if df.schema["fuentes"] == pl.String:  # gold guarda la lista como JSON
            fuentes = fuentes.str.json_decode(pl.List(pl.String))
        return df.with_columns(fuente=fuentes).explode("fuente")
    if "fuente" in df.columns:
        return df
    return df.with_columns(fuente=pl.lit(None, pl.String))


def con_persona(df: pl.DataFrame) -> pl.DataFrame:
    return df.rename({"academico_id": "persona"}) if "academico_id" in df.columns else df


def capa(nombre: str, tipo: str) -> pl.DataFrame:
    """Filas de un tipo en una capa, con columnas comunes `persona` y `fuente`."""
    df = {"bronze": bronze, "silver": silver, "gold": gold}[nombre](tipo)
    return con_fuente(con_persona(df)) if not df.is_empty() else df


def origen(fila: dict, tipo: str) -> pl.DataFrame:
    """Ítems bronze que originan una fila silver, del más exacto al más amplio: todos los campos en común iguales; el
    mismo título normalizado; la misma página. Siempre dentro de la persona (y del spider, si la fila lo trae).

    shortcut: silver no guarda el id del ítem bronze, así que el rastro es por contenido, no exacto. Guardar un
    `item_id` en bronze cuando haga falta un rastro exacto.
    """
    df = bronze(tipo)
    if df.is_empty():
        return df
    df = df.filter(pl.col("persona") == fila.get("persona"))
    if fila.get("spider"):
        df = df.filter(pl.col("spider") == fila["spider"])
    comunes = [c for c in df.columns if c in fila and c not in ("persona", "tipo", "spider", "run_id", "scraped_at")]
    candidatos = [
        pl.all_horizontal(  # bronze puede traer el año como texto: se compara como texto
            pl.col(c).cast(pl.String).eq_missing(None if fila[c] is None else str(fila[c])) for c in comunes
        )
        if comunes and not any(isinstance(fila[c], list | dict) for c in comunes)
        else None
    ]
    titulo = fila.get("titulo") or fila.get("nombre")
    campo = next((c for c in ("titulo", "nombre") if c in df.columns), None)
    if titulo and campo:
        candidatos.append(pl.col(campo).map_elements(norm_text, return_dtype=pl.String) == norm_text(titulo))
    if fila.get("url"):
        candidatos.append(pl.col("url") == fila["url"])
    for condicion in candidatos:
        encontrados = df.filter(condicion) if condicion is not None else df.clear()
        if not encontrados.is_empty():
            return encontrados
    return df.clear()


def embudo() -> pl.DataFrame:
    """Filas por tipo y capa (por académico: gold cuenta las tablas puente, no las entidades deduplicadas)."""
    lectores = {"bronze": bronze, "silver": silver, "gold": gold}
    return pl.DataFrame(
        [{"tipo": TIPOS[t][0], "capa": c, "filas": lectores[c](t).height} for t in TIPOS for c in CAPAS],
        schema={"tipo": pl.String, "capa": pl.String, "filas": pl.Int64},
    )


def nulos(df: pl.DataFrame) -> pl.DataFrame:
    """% de nulos (o texto vacío) por campo y fuente, en formato largo para el heatmap."""
    tecnicas = {"persona", "url", "spider", "run_id", "scraped_at", "tipo", "fuente", "fuentes", "academico_id"}
    campos = [c for c in df.columns if c not in tecnicas]
    if df.is_empty() or not campos:
        return pl.DataFrame(
            schema={"fuente": pl.String, "campo": pl.String, "pct_nulos": pl.Float64, "filas": pl.Int64}
        )

    def vacio(c: str) -> pl.Expr:
        col = pl.col(c)
        return (col.is_null() | (col.str.strip_chars() == "")) if df.schema[c] == pl.String else col.is_null()

    return (
        df.group_by("fuente")
        .agg(pl.len().alias("filas"), *[(vacio(c).mean() * 100).alias(c) for c in campos])
        .unpivot(index=["fuente", "filas"], variable_name="campo", value_name="pct_nulos")
        .sort("fuente", "campo")
    )


# --- runs, versiones y logs ---------------------------------------------------------------------------------------


def historial(spider: str) -> pl.DataFrame:
    """Runs de un spider (más reciente primero) con estado, problemas y conteos de quality.json."""
    filas = []
    for run in runs(spider):
        q = run / "quality.json"
        data = json.loads(q.read_text()) if q.exists() else {}
        filas.append(
            {
                "run_id": run.name,
                "estado": data.get("status", "sin_evaluar"),
                "problemas": data.get("problems", []),
                "conteos": data.get("counts", {}),
            }
        )
    return pl.DataFrame(filas, schema_overrides={"problemas": pl.Object, "conteos": pl.Object})


def logs(
    *,
    nivel: str = "INFO",
    spider: str | None = None,
    run_id: str | None = None,
    persona: str | None = None,
    evento: str | None = None,
    desde: str | None = None,
    limite: int = 2000,
) -> pl.DataFrame:
    """Registros de logs.sqlite (más reciente primero), con los mismos filtros que `daii logs` más persona y evento."""
    db = logs_db()
    if not db.exists():
        return pl.DataFrame()
    niveles = NIVELES[NIVELES.index(nivel) :]
    where, params = [f"nivel IN ({', '.join('?' * len(niveles))})"], list(niveles)
    for col, value, op in (
        ("spider", spider, "="),
        ("run_id", run_id, "="),
        ("persona", persona, "="),
        ("evento", evento, "="),
        ("ts", desde, ">="),
    ):
        if value:
            where.append(f"{col} {op} ?")
            params.append(value)
    sql = f"SELECT * FROM log WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT {int(limite)}"
    with _ro(db) as conn:
        return pl.read_database(sql, conn, execute_options={"parameters": params}, infer_schema_length=None)


def valores_log(columna: str) -> list[str]:
    """Valores distintos de una columna de logs.sqlite, para poblar filtros."""
    if columna not in ("spider", "evento", "persona", "run_id") or not logs_db().exists():
        return []
    with _ro(logs_db()) as conn:
        rows = conn.execute(f"SELECT DISTINCT {columna} FROM log WHERE {columna} IS NOT NULL ORDER BY 1").fetchall()
    return [r[0] for r in rows]
