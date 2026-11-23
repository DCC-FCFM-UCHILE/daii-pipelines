"""Gold: reconstruye data/gold/daii.sqlite completa desde silver (idempotente)."""

import hashlib
import json
import os
from pathlib import Path

import polars as pl
from sqlalchemy import insert
from sqlmodel import Session, SQLModel, create_engine

from daii.config import BRONZE, GOLD_DB, SILVER, academicos
from daii.config import GOLD as GOLD
from daii.gold import models as m
from daii.quality.checks import last_good, runs, status
from daii.silver.transform import _prio, norm_text


def _hid(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _json(col: str) -> pl.Expr:
    """Columna lista → texto JSON (SQLite no tiene listas)."""
    return pl.col(col).map_elements(lambda v: json.dumps(v.to_list(), ensure_ascii=False), return_dtype=pl.String)


def _read(tipo: str, silver: Path | None = None) -> pl.DataFrame:
    """Silver de un tipo, solo de personas que siguen en config (también para entidades compartidas)."""
    f = (silver or SILVER) / f"{tipo}.parquet"
    if not f.exists():
        return pl.DataFrame()
    return pl.read_parquet(f).filter(pl.col("persona").is_in([a["slug"] for a in academicos()]))


def _cols(df: pl.DataFrame, **mapping: str | pl.Expr) -> list[dict]:
    """Selecciona/renombra columnas (`destino=origen` o expresión) y devuelve filas; columnas faltantes → null."""
    if df.is_empty():
        return []
    exprs = [
        (pl.col(src) if src in df.columns else pl.lit(None)).alias(dst) if isinstance(src, str) else src.alias(dst)
        for dst, src in mapping.items()
    ]
    return df.select(exprs).to_dicts()


def _academicos(silver: Path | None = None) -> list[dict]:
    personas = _read("persona", silver)
    rows = []
    for a in academicos():
        cand = personas.filter(pl.col("persona") == a["slug"]).to_dicts() if not personas.is_empty() else []
        cand.sort(key=lambda r: _prio(r["spider"]))

        def first(field: str, cand=cand):
            return next((r[field] for r in cand if r.get(field)), None)

        rows.append(
            {
                "id": a["slug"],
                "nombre": a["nombre"],
                "unidad": a.get("unidad"),
                "orcid": a.get("perfiles", {}).get("orcid"),
                **{f: first(f) for f in ("cargo", "email", "foto_url", "bio")},
            }
        )
    return rows


def _shared(df: pl.DataFrame, key: pl.Expr, entity: dict, link: dict) -> tuple[list[dict], list[dict]]:
    """Separa una tabla silver por persona en (entidad compartida, puente persona↔entidad)."""
    if df.is_empty():
        return [], []
    df = df.with_columns(_key=key, _prio=pl.col("spider").map_elements(_prio, return_dtype=pl.Int64)).sort(
        "_prio", maintain_order=True
    )
    ent = df.unique("_key", keep="first", maintain_order=True)
    bridge = (
        df.group_by("_key", "persona", maintain_order=True)
        .agg(pl.all().exclude("spider").first(), fuentes=pl.col("spider").unique().sort())
        .with_columns(fuentes=_json("fuentes"))
    )
    return _cols(ent, id="_key", **entity), _cols(bridge, academico_id="persona", **link)


def build(
    silver: Path | None = None, destination: Path | None = None, run_rows: list[dict] | None = None
) -> dict[str, int]:
    destination = destination or GOLD_DB
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Se construye aparte y se reemplaza al final: el dashboard nunca ve una base vacía o a medias.
    tmp = destination.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{tmp}")
    SQLModel.metadata.create_all(engine)
    tables: dict[type[SQLModel], list[dict]] = {m.Academico: _academicos(silver)}

    tables[m.PerfilExterno] = _cols(
        _read("perfil", silver),
        academico_id="persona",
        plataforma="plataforma",
        url="url_destino",
        identificador="identificador",
        fuente="spider",
    )
    tables[m.Afiliacion] = _cols(
        _read("afiliacion", silver),
        academico_id="persona",
        organizacion="organizacion",
        rol="rol",
        desde="desde",
        hasta="hasta",
        url_organizacion="url_organizacion",
        fuente="spider",
    )
    tables[m.Formacion] = _cols(
        _read("formacion", silver),
        academico_id="persona",
        nivel="nivel",
        grado="grado",
        institucion="institucion",
        anio="anio",
        titulo_tesis="titulo_tesis",
        fuente="spider",
    )
    tables[m.Area] = _cols(_read("area", silver), academico_id="persona", nombre="nombre", fuente="spider")
    tables[m.Distincion] = _cols(
        _read("distincion", silver),
        academico_id="persona",
        nombre="nombre",
        otorgante="otorgante",
        anio="anio",
        fuente="spider",
    )
    tables[m.Metrica] = _cols(
        _read("metrica", silver),
        academico_id="persona",
        plataforma="plataforma",
        nombre="nombre",
        valor="valor",
        anio="anio",
    )
    tables[m.Actividad] = _cols(
        _read("actividad", silver),
        academico_id="persona",
        tipo="tipo_actividad",
        titulo="titulo",
        descripcion="descripcion",
        evento="evento",
        fecha="fecha",
        rol="rol",
        url="url_destino",
        fuente="spider",
    )
    tables[m.LinkDescubierto] = _cols(
        _read("link", silver),
        academico_id="persona",
        url_origen="url",
        url_destino="url_destino",
        texto="texto",
        seguido="seguido",
        fuente="spider",
    )
    tables[m.PaginaRelacionada] = _cols(
        _read("pagina", silver), academico_id="persona", url="url", titulo="titulo", texto="texto"
    )

    pubs = _read("publicacion", silver)
    if not pubs.is_empty():
        pubs = pubs.with_columns(spider=pl.lit("silver"), autores=_json("autores"))
        # silver ya consolidó por persona; aquí se une entre personas por pub_key (primera fila gana).
        tables[m.Publicacion] = _cols(
            # una publicación compartida queda indexada si cualquier persona la reporta indexada
            pubs.with_columns(
                pl.col("indexada_wos", "indexada_scopus").any().over("pub_key"),
                pl.col("autores", "anio", "venue", "url_destino", "estado").drop_nulls().first().over("pub_key"),
                pl.col("citas").max().over("pub_key"),
            ).unique("pub_key", keep="first", maintain_order=True),
            id="pub_key",
            indexada_wos="indexada_wos",
            indexada_scopus="indexada_scopus",
            titulo="titulo",
            anio="anio",
            tipo="tipo_publicacion",
            venue="venue",
            doi="doi",
            url="url_destino",
            estado="estado",
            citas="citas",
            autores="autores",
        )
        tables[m.PublicacionAcademico] = _cols(
            pubs,
            publicacion_id="pub_key",
            academico_id="persona",
            confianza="confianza",
            fuentes=_json("fuentes"),
        )

    proy = _read("proyecto", silver)
    if not proy.is_empty():
        key = pl.coalesce(
            pl.col("codigo"), pl.lit("t:") + pl.col("titulo").map_elements(norm_text, return_dtype=pl.String)
        )
        tables[m.Proyecto], tables[m.ParticipacionProyecto] = _shared(
            proy,
            key,
            dict(
                titulo="titulo",
                codigo="codigo",
                instrumento="instrumento",
                fuente_texto="fuente",
                anio_inicio="anio_inicio",
                anio_fin="anio_fin",
                monto="monto",
            ),
            dict(proyecto_id="_key", rol="rol", fuentes="fuentes"),
        )

    tesis = _read("tesis", silver)
    if not tesis.is_empty():
        # Sin título, "nivel|año" no distingue a nadie: entonces entra el estudiante. Con título NO, porque una
        # fuente puede traer estudiante y otra no (ucurriculum vs sitio personal) y la misma tesis se duplicaría.
        key = pl.concat_str(
            pl.col("titulo").map_elements(norm_text, return_dtype=pl.String),
            pl.when(pl.col("titulo").is_null()).then(
                pl.col("estudiante").map_elements(norm_text, return_dtype=pl.String)
            ),
            pl.col("anio").cast(pl.String),
            separator="|",
            ignore_nulls=True,
        )
        tables[m.Tesis], tables[m.DireccionTesis] = _shared(
            tesis,
            key.map_elements(_hid, return_dtype=pl.String),
            dict(
                titulo="titulo",
                anio="anio",
                nivel="nivel",
                estudiante="estudiante",
                programa="programa",
                estado="estado",
                url="url_destino",
            ),
            dict(tesis_id="_key", rol="rol_norm", fuentes="fuentes"),
        )

    dict_ = _read("dictacion", silver)
    if not dict_.is_empty():
        dict_ = dict_.with_columns(
            curso_id=pl.coalesce(
                "codigo_curso",
                pl.col("nombre_curso").map_elements(lambda s: "n:" + norm_text(s), return_dtype=pl.String),
            )
        )
        tables[m.Curso] = _cols(
            dict_.unique("curso_id", keep="first", maintain_order=True),
            id="curso_id",
            codigo="codigo_curso",
            nombre="nombre_curso",
        )
        tables[m.Dictacion] = _cols(
            dict_,
            curso_id="curso_id",
            academico_id="persona",
            anio="anio",
            semestre="semestre",
            rol="rol",
            institucion="institucion",
            fuente="spider",
        )

    prod = _read("producto", silver)
    if not prod.is_empty():
        tables[m.Producto], tables[m.ProductoAcademico] = _shared(
            prod,
            pl.col("nombre").map_elements(norm_text, return_dtype=pl.String),
            dict(nombre="nombre", tipo="tipo_producto", descripcion="descripcion", url="url_destino"),
            dict(producto_id="_key", rol="rol"),
        )

    tables[m.ScrapeRun] = run_rows if run_rows is not None else run_manifest()

    counts = {}
    with Session(engine) as s:
        for model, rows in tables.items():
            if rows:
                s.connection().execute(insert(model), rows)  # bulk insert (Core)
            counts[str(model.__tablename__)] = len(rows)
        s.commit()
    engine.dispose()
    os.replace(tmp, destination)
    return counts


def run_manifest() -> list[dict]:
    return [_run_row(d.name) for d in sorted(BRONZE.glob("*")) if d.is_dir() and runs(d.name)]


def _run_row(spider: str) -> dict:
    # el último run evaluado: un `scrapy crawl` manual de depuración no tapa la salud real del spider
    last = next((r for r in runs(spider) if status(r)), runs(spider)[0])
    q = json.loads((last / "quality.json").read_text()) if (last / "quality.json").exists() else {}
    good = last_good(spider)
    return {
        "spider": spider,
        "ultimo_run": last.name,
        "estado": status(last) or "sin_evaluar",
        "problemas": json.dumps(q.get("problems", []), ensure_ascii=False),
        "conteos": json.dumps(q.get("counts", {})),
        "run_en_uso": good.name if good else None,
    }
