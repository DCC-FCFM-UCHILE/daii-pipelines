"""Gold: reconstruye data/gold/daii.sqlite completa desde silver (idempotente)."""

import hashlib
import json
from pathlib import Path

import polars as pl
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import insert
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from daii.config import BRONZE, GOLD_DB, SILVER, academicos, catalogos
from daii.gold import models as m
from daii.quality.checks import last_good, runs, status
from daii.silver.transform import _prio, norm_text, prio_expr

MIGRATIONS = Path(__file__).parent / "migrations"


def head() -> str | None:
    """Revisión de esquema que espera este código."""
    return ScriptDirectory(str(MIGRATIONS)).get_current_head()


def migrate(engine: Engine) -> None:
    """Crea el esquema con las migraciones de Alembic (deja `alembic_version` en la SQLite)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")


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


CONFIG_ITEM = "config:academicos.yaml"


def _fila(*valores: object) -> str:
    """PK como json_array de SQLite (sin espacios, UTF-8): así se cruza en SQL con `e.fila_id = json_array(t.id)`."""
    return json.dumps(list(valores), ensure_ascii=False, separators=(",", ":"))


def _evidencia(
    model: type[SQLModel], df: pl.DataFrame, pk: list[str], campos: dict[str, tuple[str, str]] | None = None
) -> list[dict]:
    """Cada ítem de `item_ids` respalda la fila; `campos` = {campo gold: (columna valor, columna item de origen)}."""
    if df.is_empty():
        return []
    tabla, campos = str(model.__tablename__), campos or {}
    cols = dict.fromkeys([*pk, "item_ids", *(c for par in campos.values() for c in par)])
    out = []
    for r in df.select(list(cols)).to_dicts():
        fila = _fila(*(r[c] for c in pk))
        out += [dict(tabla=tabla, fila_id=fila, item_id=i, campo="") for i in dict.fromkeys(r["item_ids"] or [])]
        out += [
            dict(tabla=tabla, fila_id=fila, item_id=r[origen], campo=campo)
            for campo, (valor, origen) in campos.items()
            if r[valor] is not None and r[origen] is not None
        ]
    return out


def _fusiones(model: type[SQLModel], df: pl.DataFrame, pk: list[str]) -> list[dict]:
    """Aristas del deduplicador (columna `fusiones` de silver) hacia la fila gold que resultó (tabla `fusion`)."""
    if df.is_empty() or "fusiones" not in df.columns:
        return []
    aristas = df.select(*pk, "fusiones").explode("fusiones").drop_nulls("fusiones").unnest("fusiones")
    tabla = str(model.__tablename__)
    out = {}  # una entidad compartida repite sus aristas en la fila de cada persona
    for r in aristas.to_dicts():
        f = dict(tabla=tabla, fila_id=_fila(*(r[c] for c in pk)), item_a=r["item_a"], item_b=r["item_b"])
        out[tuple(f.values())] = f | {"regla": r["regla"], "similitud": r["similitud"]}
    return list(out.values())


def _origen(df: pl.DataFrame, mapping: dict) -> tuple[pl.DataFrame, dict[str, tuple[str, str]]]:
    """Filas fusionadas en silver traen `origen` (campo → item_id): campos para `_evidencia()`."""
    if not isinstance(origen := df.schema.get("origen"), pl.Struct):  # sin fusiones en el build: null
        return df, {}
    fuentes = {f.name for f in origen.fields}
    campos = {dst: (src, f"_o_{src}") for dst, src in mapping.items() if src in fuentes and dst != "academico_id"}
    return df.with_columns(pl.col("origen").struct.field(src).alias(o) for src, o in campos.values()), campos


def _por_persona(tipo: str, model: type[SQLModel], silver: Path | None, mapping: dict) -> tuple[list, list, list]:
    """Tabla por persona: id correlativo, la evidencia de la fila (y de cada campo si se fusionó) y sus fusiones."""
    df = _read(tipo, silver)
    if df.is_empty():
        return [], [], []
    df, campos = _origen(df.with_row_index("id", offset=1), mapping)
    return _cols(df, id="id", **mapping), _evidencia(model, df, ["id"], campos), _fusiones(model, df, ["id"])


def _academicos(silver: Path | None = None) -> tuple[list[dict], list[dict]]:
    personas = _read("persona", silver)
    rows, ev = [], []
    for a in academicos():
        cand = personas.filter(pl.col("persona") == a["slug"]).to_dicts() if not personas.is_empty() else []
        cand.sort(key=lambda r: _prio(r["spider"], a.get("prioridad")))
        row = {
            "id": a["slug"],
            "nombre": a["nombre"],
            "unidad": a.get("unidad"),
            "orcid": a.get("perfiles", {}).get("orcid"),
        }
        origen: dict[str, str | None] = dict.fromkeys(row, CONFIG_ITEM)
        for f in ("cargo", "email", "foto_url", "bio"):
            elegido = next((r for r in cand if r.get(f)), None)
            row[f] = elegido[f] if elegido else None
            origen[f] = elegido["item_id"] if elegido else None
        rows.append(row)
        fila = _fila(a["slug"])
        respaldo = dict.fromkeys([CONFIG_ITEM, *(i for r in cand for i in r["item_ids"])], "")
        campos = [(o, f) for f, o in origen.items() if f != "id" and row[f] is not None and o]
        ev += [dict(tabla="academico", fila_id=fila, item_id=i, campo=c) for i, c in [*respaldo.items(), *campos]]
    return rows, ev


def _shared(
    df: pl.DataFrame, key: pl.Expr, models: tuple[type[SQLModel], type[SQLModel]], entity: dict, link: dict
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Separa una tabla silver por persona en (entidad compartida, puente, evidencia de ambas, fusiones)."""
    if df.is_empty():
        return [], [], [], []
    df = df.with_columns(_key=key, _prio=prio_expr()).sort("_prio", maintain_order=True)
    # la entidad es la fila de la fuente más prioritaria (cada campo sale de ese ítem) con los ítems de todas sus filas
    todos = df.group_by("_key").agg(pl.col("item_ids").explode())
    ent = (
        df.unique("_key", keep="first", maintain_order=True)
        .drop("item_ids")
        .join(todos, on="_key", how="left", maintain_order="left")
    )
    bridge = df.group_by("_key", "persona", maintain_order=True).agg(
        pl.exclude("item_ids").first(), pl.col("item_ids").explode()
    )
    ent_model, link_model = models
    return (
        _cols(ent, id="_key", **entity),
        _cols(bridge, academico_id="persona", **link),
        _evidencia(ent_model, ent, ["_key"], {c: (src, "item_id") for c, src in entity.items()})
        + _evidencia(
            link_model,
            bridge,
            ["_key", "persona"],  # PK de los puentes: (entidad, académico)
            {c: (src, "item_id") for c, src in link.items() if src != "_key"},
        ),
        _fusiones(ent_model, df, ["_key"]),
    )


def _items(silver: Path | None, usados: set[str]) -> list[dict]:
    """Procedencia de los ítems referenciados por la evidencia (más el de config)."""
    f = (silver or SILVER) / "item.parquet"
    df = pl.read_parquet(f) if f.exists() else pl.DataFrame(schema={"item_id": pl.String})
    rows = _cols(
        df.filter(pl.col("item_id").is_in(list(usados))),
        id="item_id",
        spider="spider",
        run_id="run_id",
        persona="persona",
        url="url",
        observacion_id="observacion_id",
        scraped_at="scraped_at",
    )
    # el bulk insert toma las columnas de la primera fila: la de config lleva todas
    return [dict.fromkeys(rows[0] if rows else ["id"]) | {"id": CONFIG_ITEM, "spider": "config"}, *rows]


def _candidatos(silver: Path | None, usados: set[str]) -> list[dict]:
    """Uniones dudosas que silver no hizo (candidato.parquet), entre ítems publicados."""
    f = (silver or SILVER) / "candidato.parquet"
    if not f.exists():
        return []
    df = pl.read_parquet(f).filter(pl.col("item_a").is_in(list(usados)) & pl.col("item_b").is_in(list(usados)))
    return df.unique(["tabla", "item_a", "item_b"], maintain_order=True).to_dicts()


def build(
    silver: Path | None = None, destination: Path | None = None, run_rows: list[dict] | None = None
) -> dict[str, int]:
    if not ((silver or SILVER) / "item.parquet").exists():
        raise ValueError("silver sin trazabilidad (falta item.parquet): vuelva a generar silver con `daii silver`")
    destination = destination or GOLD_DB
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Se construye aparte y se reemplaza al final: el dashboard nunca ve una base vacía o a medias.
    tmp = destination.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{tmp}")
    migrate(engine)
    tables: dict[type[SQLModel], list[dict]] = {}
    tables[m.Academico], ev = _academicos(silver)

    por_persona = {
        m.PerfilExterno: (
            "perfil",
            dict(academico_id="persona", plataforma="plataforma", url="url_destino", identificador="identificador"),
        ),
        m.Afiliacion: (
            "afiliacion",
            dict(
                academico_id="persona",
                organizacion="organizacion",
                rol="rol",
                desde="desde",
                hasta="hasta",
                url_organizacion="url_organizacion",
            ),
        ),
        m.Formacion: (
            "formacion",
            dict(
                academico_id="persona",
                nivel="nivel",
                grado="grado",
                institucion="institucion",
                anio="anio",
                titulo_tesis="titulo_tesis",
            ),
        ),
        m.Area: ("area", dict(academico_id="persona", nombre="nombre")),
        m.Distincion: (
            "distincion",
            dict(academico_id="persona", nombre="nombre", otorgante="otorgante", anio="anio"),
        ),
        m.Metrica: (
            "metrica",
            dict(academico_id="persona", plataforma="plataforma", nombre="nombre", valor="valor", anio="anio"),
        ),
        m.Actividad: (
            "actividad",
            dict(
                academico_id="persona",
                tipo="tipo_actividad",
                titulo="titulo",
                descripcion="descripcion",
                evento="evento",
                fecha="fecha",
                rol="rol",
                url="url_destino",
            ),
        ),
        m.LinkDescubierto: (
            "link",
            dict(academico_id="persona", url_origen="url", url_destino="url_destino", texto="texto", seguido="seguido"),
        ),
        m.PaginaRelacionada: ("pagina", dict(academico_id="persona", url="url", titulo="titulo", texto="texto")),
    }
    fus: list[dict] = []
    for model, (tipo, mapping) in por_persona.items():
        tables[model], e, f = _por_persona(tipo, model, silver, mapping)
        ev += e
        fus += f

    pubs = _read("publicacion", silver)
    if not pubs.is_empty():
        pubs = pubs.with_columns(autores=_json("autores"))
        o = pl.col("origen").struct.field
        # silver ya consolidó por persona; aquí se une entre personas por pub_key (primera fila gana) y cada campo
        # apunta al ítem del que salió su valor (`origen` de la fila de persona elegida)
        nn = ("autores", "anio", "venue", "url_destino", "estado")
        ent = (
            pubs.with_columns(
                # una publicación compartida queda indexada si cualquier persona la reporta indexada
                *(
                    o(f).filter(pl.col(f)).first().over("pub_key").alias(f"_o_{f}")
                    for f in ("indexada_wos", "indexada_scopus")
                ),
                *(o(f).filter(pl.col(f).is_not_null()).first().over("pub_key").alias(f"_o_{f}") for f in nn),
                o("citas").filter(pl.col("citas") == pl.col("citas").max()).first().over("pub_key").alias("_o_citas"),
                *(o(f).alias(f"_o_{f}") for f in ("titulo", "tipo_publicacion", "doi")),
            )
            .with_columns(
                pl.col("indexada_wos", "indexada_scopus").any().over("pub_key"),
                pl.col(*nn).drop_nulls().first().over("pub_key"),
                pl.col("citas").max().over("pub_key"),
                pl.col("item_ids").explode().over("pub_key", mapping_strategy="join"),
            )
            .unique("pub_key", keep="first", maintain_order=True)
        )
        campos = dict(
            titulo="titulo",
            anio="anio",
            tipo="tipo_publicacion",
            venue="venue",
            doi="doi",
            url="url_destino",
            estado="estado",
            citas="citas",
            autores="autores",
            indexada_wos="indexada_wos",
            indexada_scopus="indexada_scopus",
        )
        tables[m.Publicacion] = _cols(ent, id="pub_key", **campos)
        ev += _evidencia(m.Publicacion, ent, ["pub_key"], {c: (src, f"_o_{src}") for c, src in campos.items()})
        tables[m.PublicacionAcademico] = _cols(
            pubs, publicacion_id="pub_key", academico_id="persona", confianza="confianza"
        )
        ev += _evidencia(m.PublicacionAcademico, pubs, ["pub_key", "persona"])
        fus += _fusiones(m.Publicacion, pubs, ["pub_key"])

    proy = _read("proyecto", silver)
    if not proy.is_empty():
        tables[m.Proyecto], tables[m.ParticipacionProyecto], e, f = _shared(
            proy,
            pl.col("clave"),  # silver/dedup.py: el mismo proyecto entre fuentes y personas
            (m.Proyecto, m.ParticipacionProyecto),
            dict(
                titulo="titulo",
                codigo="codigo",
                instrumento="instrumento",
                fuente_texto="fuente",
                anio_inicio="anio_inicio",
                anio_fin="anio_fin",
                monto="monto",
            ),
            dict(proyecto_id="_key", rol="rol"),
        )
        ev += e
        fus += f

    tesis = _read("tesis", silver)
    if not tesis.is_empty():
        tables[m.Tesis], tables[m.DireccionTesis], e, f = _shared(
            tesis,
            pl.col("clave").map_elements(_hid, return_dtype=pl.String),  # silver/dedup.py
            (m.Tesis, m.DireccionTesis),
            dict(
                titulo="titulo",
                anio="anio",
                nivel="nivel",
                estudiante="estudiante",
                programa="programa",
                estado="estado",
                url="url_destino",
            ),
            dict(tesis_id="_key", rol="rol_norm"),
        )
        ev += e
        fus += f

    dict_ = _read("dictacion", silver)
    if not dict_.is_empty():
        dict_ = dict_.with_row_index("id", offset=1)  # curso_id viene de silver
        cursos = dict_.with_columns(pl.col("item_ids").explode().over("curso_id", mapping_strategy="join")).unique(
            "curso_id", keep="first", maintain_order=True
        )
        tables[m.Curso] = _cols(cursos, id="curso_id", codigo="codigo_curso", nombre="nombre_curso")
        ev += _evidencia(
            m.Curso,
            cursos,
            ["curso_id"],
            {"codigo": ("codigo_curso", "item_id"), "nombre": ("nombre_curso", "item_id")},
        )
        tables[m.Dictacion] = _cols(
            dict_,
            id="id",
            curso_id="curso_id",
            academico_id="persona",
            anio="anio",
            semestre="semestre",
            rol="rol",
            institucion="institucion",
        )
        mapping = dict(anio="anio", semestre="semestre", rol="rol", institucion="institucion")
        dict_, campos = _origen(dict_, mapping)
        ev += _evidencia(m.Dictacion, dict_, ["id"], campos)
        fus += _fusiones(m.Dictacion, dict_, ["id"])

    prod = _read("producto", silver)
    if not prod.is_empty():
        tables[m.Producto], tables[m.ProductoAcademico], e, f = _shared(
            prod,
            pl.col("nombre").map_elements(norm_text, return_dtype=pl.String),
            (m.Producto, m.ProductoAcademico),
            dict(nombre="nombre", tipo="tipo_producto", descripcion="descripcion", url="url_destino"),
            dict(producto_id="_key", rol="rol"),
        )
        ev += e
        fus += f

    usados = {e["item_id"] for e in ev}
    # las claves compartidas se calculan en silver con todas las personas: aristas hacia ítems de alguien que ya no
    # está en config (o que no respaldan ninguna fila publicada) no se publican
    fus = [f for f in fus if f["item_a"] in usados and f["item_b"] in usados]
    tables[m.ItemBronze] = _items(silver, usados)
    tables[m.Catalogo] = catalogo()
    tables[m.Evidencia] = ev
    tables[m.Fusion] = fus
    tables[m.CandidatoFusion] = _candidatos(silver, usados)
    tables[m.ScrapeRun] = run_rows if run_rows is not None else run_manifest()

    counts = {}
    with Session(engine) as s:
        for model, rows in tables.items():
            if rows:
                s.connection().execute(insert(model), rows)  # bulk insert (Core)
            counts[str(model.__tablename__)] = len(rows)
        s.commit()
    engine.dispose()
    tmp.replace(destination)
    return counts


def catalogo() -> list[dict]:
    """config/catalogos.yaml más los sitios personales, nombrados desde academicos.yaml."""
    sitios = {
        "sitio_" + a["slug"].replace("-", "_"): f"Sitio personal de {a['nombre']}"
        for a in academicos()
        if "sitio" in a.get("perfiles", {})
    }
    nombres = catalogos() | {"itembronze.spider": sitios | catalogos()["itembronze.spider"]}
    return [{"campo": c, "codigo": str(k), "nombre": v} for c, vs in nombres.items() for k, v in vs.items()]


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
