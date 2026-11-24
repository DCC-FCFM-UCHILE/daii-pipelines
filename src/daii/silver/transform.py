"""Silver: une el último run bueno de cada spider, normaliza y deduplica. Salida: data/silver/<tipo>.parquet.

Silver sigue siendo "por persona": una fila dice "según la fuente X, la persona P tiene Y".
La consolidación entre personas (p. ej. un paper compartido por dos académicos) ocurre en gold.

Trazabilidad: cada ítem bronze tiene `item_id = "<spider>/<run_id>#<línea>"` (item.parquet guarda su procedencia).
Cada fila silver lleva `item_ids` (los ítems que fusiona); publicaciones además `origen` (campo → item_id).
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import polars as pl

from daii.bronze.items import TIPOS
from daii.config import BRONZE, SILVER, academicos
from daii.log import logger
from daii.quality.checks import last_good
from daii.silver import dedup
from daii.silver.dedup import doi_limpio, norm_text

# Prioridad de fuentes al consolidar campos (menor = más confiable). Fuentes curadas por la persona primero.
PRIORIDAD = {"portafolio": 1, "orcid": 2, "ucurriculum": 3, "dblp": 4, "openalex": 5}  # sitio_* = 0; otros = 9

TIPO_PUB = [
    ("revista", r"journal|^article$|revista"),
    ("conferencia", r"inproceedings|proceedings|conference|congreso|workshop|symposium"),
    ("capitulo", r"chapter|incollection|capitulo"),
    ("libro", r"^book$|libro|monograph"),
    ("preprint", r"preprint|arxiv|posted-content|informal"),
    ("tesis", r"thesis|tesis|dissertation"),
]
ROL_TESIS = [  # orden importa: "co-guía" antes que "guía"; \b evita leer "co" dentro de "como"
    ("coguia", r"\bco-?(gu[ií]a|supervis|advis)"),
    ("guia", r"gu[ií]a|supervis|advis"),
    ("comision", r"comisi[oó]n|committee"),
]
SEMESTRES = {
    "Primer Semestre": "Otoño",
    "Segundo Semestre": "Primavera",
    "Semester 1": "Otoño",
    "Semester 2": "Primavera",
    "Autumn": "Otoño",
    "Fall": "Otoño",
    "Spring": "Primavera",
}
NIVEL_FORMACION = [
    ("postdoctorado", r"post-?doc"),
    ("doctorado", r"doct|ph\.? ?d|dr\.|doktor|d\.? ?phil"),
    ("magister", r"mag[ií]ster|master|m\.? ?sc|msc|\bm\.?s\.?\b|dea"),
    ("titulo_profesional", r"ingenier|engineer|t[ií]tulo"),
    ("licenciatura", r"licenci|bachelor|b\.? ?sc|bachiller"),
]
INSTRUMENTO = [
    ("fondecyt", r"fondecyt"),
    ("fondef", r"fondef|\bidea\b|\bid\d{2}i"),
    ("milenio", r"milenio|millennium|\bncn"),
    ("basal", r"basal|centros? de excelencia|afb"),
    ("anillo", r"anillo|\bpia\b|act\d"),
    ("fondequip", r"fondequip"),
    ("corfo", r"corfo"),
    ("anid_otro", r"anid|conicyt|subdirecci[oó]n de investigaci[oó]n aplicada"),
]


def classify(value: str | None, rules: list[tuple[str, str]], default: str = "otro") -> str:
    v = (value or "").lower()
    return next((k for k, rx in rules if re.search(rx, v)), default)


def _prio(spider: str, orden: list[str] | None = None) -> int:
    """Menor = más confiable. `orden` (campo `prioridad` de la persona en academicos.yaml) adelanta esas fuentes."""
    clave = "sitio" if spider.startswith("sitio_") else spider
    if orden and clave in orden:
        return orden.index(clave) - len(orden)  # negativo: antes que cualquier fuente del orden global
    return 0 if clave == "sitio" else PRIORIDAD.get(spider, 9)


def prio_expr() -> pl.Expr:
    """`_prio` por fila (columnas `spider` y `persona`), con el orden propio de cada persona."""
    ordenes = {a["slug"]: a.get("prioridad") for a in academicos()}
    return pl.struct("spider", "persona").map_elements(
        lambda r: _prio(r["spider"], ordenes.get(r["persona"])), return_dtype=pl.Int64
    )


def load_bronze(selected: list[Path] | None = None) -> dict[str, list[dict]]:
    """Ítems del último run bueno de cada spider, agrupados por tipo."""
    by_tipo: dict[str, list[dict]] = defaultdict(list)
    if selected is None:
        selected = [run for d in sorted(BRONZE.glob("*")) if (run := last_good(d.name))]
    for run in selected:
        if run and (run / "items.jsonl").exists():
            for n, line in enumerate((run / "items.jsonl").open(), 1):
                try:
                    it = json.loads(line)
                except json.JSONDecodeError:  # última línea a medio escribir (proceso matado)
                    continue
                it["item_id"] = f"{run.parent.name}/{run.name}#{n}"
                if "ids" in it:
                    it["ids"] = json.dumps(it["ids"], sort_keys=True)
                by_tipo[it["tipo"]].append(it)
    return by_tipo


def _de(cond: pl.Expr) -> pl.Expr:
    """item_id de la primera fila que cumple `cond`: de dónde sale un valor elegido con filter/drop_nulls().first()."""
    return pl.col("item_id").filter(cond).first()


def publicaciones(df: pl.DataFrame) -> pl.DataFrame:
    # OpenAlex le atribuye a Richard Weber obras de homónimos: física de 1931 y portadas "On the Cover" de Annals of
    # Allergy. shortcut: excepción en código; pasarla a config/ si aparecen más casos.
    unrelated = (
        (pl.col("persona") == "richard-weber")
        & (pl.col("spider") == "openalex")
        & ((pl.col("titulo").str.to_lowercase() == "on the cover") | (pl.col("anio") < 1950))
    ).fill_null(False)
    df = df.filter(~unrelated).with_columns(
        doi=doi_limpio(pl.col("doi")),
        titulo_norm=pl.col("titulo").map_elements(norm_text, return_dtype=pl.String),
        tipo_publicacion=pl.col("tipo_publicacion").map_elements(
            lambda v: classify(v, TIPO_PUB), return_dtype=pl.String
        ),
        prio=prio_expr(),
    )
    # sin título normalizable (vacío, o solo caracteres no latinos) y sin DOI no hay con qué identificarla
    df = df.filter((pl.col("titulo_norm") != "") | pl.col("doi").is_not_null())
    df = df.sort("prio", maintain_order=True)  # estable: misma prioridad → orden de llegada (determinista)
    df = dedup.clave_publicacion(df)  # pub_key: misma obra entre fuentes y personas (ver dedup.py)
    # tipo: la versión publicada antes que el preprint con que se fusionó; "otro" solo si no hay nada mejor
    publicado, conocido = ~pl.col("tipo_publicacion").is_in(["otro", "preprint"]), pl.col("tipo_publicacion") != "otro"
    out = df.group_by("persona", "pub_key", maintain_order=True).agg(
        pl.col("titulo").first(),
        pl.col("anio").drop_nulls().first(),
        pl.coalesce(
            pl.col("tipo_publicacion").filter(publicado).first(),
            pl.col("tipo_publicacion").filter(conocido).first(),
            pl.lit("otro"),
        ).alias("tipo_publicacion"),
        pl.col("venue").drop_nulls().first(),
        pl.col("autores").filter(pl.col("autores").list.len() > 0).first(),
        pl.col("doi_grupo").first().alias("doi"),
        pl.col("url_destino").drop_nulls().first(),
        pl.col("estado").drop_nulls().first(),
        pl.col("citas").max(),
        pl.col("ids").unique().alias("ids"),
        # Indexación declarada por el portafolio U. de Chile (p. ej. "WOS/SCOPUS/UCH/VID").
        pl.col("ids").str.contains(r'"indexacion": "[^"]*WOS').any().alias("indexada_wos"),
        pl.col("ids").str.contains(r'"indexacion": "[^"]*SCOPUS').any().alias("indexada_scopus"),
        pl.col("spider").unique().sort().alias("fuentes"),
        pl.col("item_id").alias("item_ids"),
        pl.col("fusiones").first(),  # aristas de la obra completa (todas sus filas las comparten)
        pl.struct(
            titulo=pl.col("item_id").first(),
            anio=_de(pl.col("anio").is_not_null()),
            tipo_publicacion=pl.coalesce(_de(publicado), _de(conocido)),
            venue=_de(pl.col("venue").is_not_null()),
            autores=_de(pl.col("autores").list.len() > 0),
            doi=_de(pl.col("doi") == pl.col("doi_grupo")),  # el ítem que trae el DOI, no el que lo heredó
            url_destino=_de(pl.col("url_destino").is_not_null()),
            estado=_de(pl.col("estado").is_not_null()),
            citas=_de(pl.col("citas") == pl.col("citas").max()),
            indexada_wos=_de(pl.col("ids").str.contains(r'"indexacion": "[^"]*WOS')),
            indexada_scopus=_de(pl.col("ids").str.contains(r'"indexacion": "[^"]*SCOPUS')),
        ).alias("origen"),
    )
    # Lo que solo reporta OpenAlex puede ser un homónimo mal desambiguado.
    return out.with_columns(confianza=pl.when(pl.col("fuentes") == ["openalex"]).then(0.5).otherwise(1.0))


TRANSFORMS = {
    "publicacion": publicaciones,
    "formacion": lambda df: df.with_columns(
        nivel=pl.col("grado").map_elements(lambda v: classify(v, NIVEL_FORMACION), return_dtype=pl.String)
    ),
    "proyecto": lambda df: df.with_columns(
        codigo=pl.col("codigo").cast(pl.String).str.strip_chars(),
        instrumento=pl.concat_str("fuente", "titulo", separator=" ", ignore_nulls=True).map_elements(
            lambda v: classify(v, INSTRUMENTO), return_dtype=pl.String
        ),
    ).pipe(dedup.clave_proyecto),
    "dictacion": lambda df: df.with_columns(
        codigo_curso=pl.col("codigo_curso").cast(pl.String).str.to_uppercase().str.replace_all(r"\s+", ""),
        # Cada fuente nombra los semestres a su modo; el calendario chileno: 1er semestre = Otoño.
        semestre=pl.col("semestre").cast(pl.String).str.to_titlecase().replace(SEMESTRES),
    ).with_columns(curso_id=dedup.clave_curso()),
    "tesis": lambda df: df.with_columns(
        rol_norm=pl.col("rol").fill_null("").map_elements(lambda v: classify(v, ROL_TESIS), return_dtype=pl.String)
    ).pipe(dedup.clave_tesis),
}
# Campos que definen "la misma fila" para deduplicar (además de persona y tipo).
DEDUP_IGNORA = {"url", "spider", "run_id", "scraped_at", "observacion_id", "tipo", "item_id"}
# Procedencia de cada ítem bronze (item.parquet): gold la publica como ItemBronze.
PROCEDENCIA = ["item_id", "spider", "run_id", "persona", "url", "observacion_id", "scraped_at"]


def build(destination: Path | None = None, selected: list[Path] | None = None) -> dict[str, int]:
    destination = destination or SILVER
    destination.mkdir(parents=True, exist_ok=True)
    out = {}
    items = []
    for tipo, rows in load_bronze(selected).items():
        df = pl.DataFrame(rows, infer_schema_length=None)
        items.append(df.select(pl.col(c) if c in df.columns else pl.lit(None, pl.String).alias(c) for c in PROCEDENCIA))
        if tipo != "publicacion":
            # filas idénticas salvo procedencia → una, con todos sus ítems (la técnica queda la de la primera)
            claves = [c for c in df.columns if c not in DEDUP_IGNORA]
            df = df.group_by(claves, maintain_order=True).agg(pl.exclude(claves).first(), item_ids=pl.col("item_id"))
        antes = df.height
        # estable: misma prioridad → orden de llegada; la fusión toma cada campo de la fila más prioritaria
        df = df.with_columns(_prio=prio_expr()).sort("_prio", maintain_order=True).drop("_prio")
        df = dedup.aplicar(tipo, TRANSFORMS.get(tipo, lambda d: d)(df))
        df.write_parquet(destination / f"{tipo}.parquet")
        out[tipo] = df.height
        if "fusiones" in df.columns:
            # varias filas (personas) de una misma entidad comparten aristas: se cuentan una vez
            aristas = df["fusiones"].explode().drop_nulls().unique()
            por_regla = aristas.struct.field("regla").value_counts().rows()
            logger.bind(
                evento="dedup_aplicado", tipo=tipo, antes=antes, despues=df.height, reglas=dict(por_regla)
            ).info(f"{tipo}: {antes} → {df.height} filas, {aristas.len()} fusiones por heurística")
    item = (
        pl.concat(items, how="vertical_relaxed")
        if items
        else pl.DataFrame(schema=dict.fromkeys(PROCEDENCIA, pl.String))
    )
    item.write_parquet(destination / "item.parquet")
    for stale in set(TIPOS) - set(out):  # no dejar parquet viejos de tipos que ya no vienen
        (destination / f"{stale}.parquet").unlink(missing_ok=True)
    return out
