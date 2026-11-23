"""Silver: une el último run bueno de cada spider, normaliza y deduplica. Salida: data/silver/<tipo>.parquet.

Silver sigue siendo "por persona": una fila dice "según la fuente X, la persona P tiene Y".
La consolidación entre personas (p. ej. un paper compartido por dos académicos) ocurre en gold.
"""

import json
import re
import unicodedata
from collections import defaultdict

import polars as pl

from daii.bronze.items import TIPOS
from daii.config import BRONZE, SILVER
from daii.quality.checks import last_good

# Prioridad de fuentes al consolidar campos (menor = más confiable). Fuentes curadas por la persona primero.
PRIORIDAD = {"orcid": 0, "ucurriculum": 2, "dblp": 3, "openalex": 4}  # sitio_* = 1

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
TITULO_MIN_PALABRAS = 4  # bajo esto un título es "genérico" (ver publicaciones())
NIVEL_FORMACION = [
    ("postdoctorado", r"post-?doc"),
    ("doctorado", r"doct|ph\.? ?d|dr\.|doktor"),
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


def norm_text(s: str | None) -> str:
    """Clave de comparación: minúsculas, sin tildes ni puntuación."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def classify(value: str | None, rules: list[tuple[str, str]], default: str = "otro") -> str:
    v = (value or "").lower()
    return next((k for k, rx in rules if re.search(rx, v)), default)


def _prio(spider: str) -> int:
    return PRIORIDAD.get(spider, 1)


def load_bronze() -> dict[str, list[dict]]:
    """Ítems del último run bueno de cada spider, agrupados por tipo."""
    by_tipo: dict[str, list[dict]] = defaultdict(list)
    for spider_dir in sorted(BRONZE.iterdir()) if BRONZE.exists() else []:
        run = last_good(spider_dir.name)
        if run and (run / "items.jsonl").exists():
            for line in (run / "items.jsonl").open():
                try:
                    it = json.loads(line)
                except json.JSONDecodeError:  # última línea a medio escribir (proceso matado)
                    continue
                if "ids" in it:
                    it["ids"] = json.dumps(it["ids"], sort_keys=True)
                by_tipo[it["tipo"]].append(it)
    return by_tipo


def publicaciones(df: pl.DataFrame) -> pl.DataFrame:
    df = df.with_columns(
        # extrae el DOI aunque venga como URL o con basura alrededor ("bar050\n10.1093/database/bar050")
        doi=pl.col("doi").str.to_lowercase().str.extract(r"(10\.\d{4,9}/\S+)"),
        titulo_norm=pl.col("titulo").map_elements(norm_text, return_dtype=pl.String),
        tipo_publicacion=pl.col("tipo_publicacion").map_elements(
            lambda v: classify(v, TIPO_PUB), return_dtype=pl.String
        ),
        prio=pl.col("spider").map_elements(_prio, return_dtype=pl.Int64),
    )
    # Clave: DOI; si no hay, el DOI que otra fuente asocia al mismo título; si no, el título normalizado.
    # Títulos cortos ("Preface", "Editorial", "On the cover") se repiten entre obras distintas: para ellos no se
    # hereda DOI por título y la clave incluye el año.
    df = df.filter(pl.col("titulo_norm") != "").with_columns(
        titulo_largo=pl.col("titulo_norm").str.count_matches(" ") >= TITULO_MIN_PALABRAS - 1
    )
    doi_por_titulo = (
        df.filter(pl.col("doi").is_not_null() & pl.col("titulo_largo"))
        .group_by("titulo_norm")
        .agg(doi_t=pl.col("doi").first())
    )
    clave_titulo = pl.lit("t:") + pl.col("titulo_norm")
    df = df.join(doi_por_titulo, on="titulo_norm", how="left").with_columns(
        pub_key=pl.coalesce(
            "doi",
            "doi_t",
            pl.when(pl.col("titulo_largo"))
            .then(clave_titulo)
            .otherwise(clave_titulo + "|" + pl.col("anio").cast(pl.String).fill_null("?")),
        )
    )
    df = df.sort("prio", maintain_order=True)  # estable: misma prioridad → orden de llegada (determinista)
    out = df.group_by("persona", "pub_key", maintain_order=True).agg(
        pl.col("titulo").first(),
        pl.col("anio").drop_nulls().first(),
        pl.col("tipo_publicacion").filter(pl.col("tipo_publicacion") != "otro").first().fill_null("otro"),
        pl.col("venue").drop_nulls().first(),
        pl.col("autores").filter(pl.col("autores").list.len() > 0).first(),
        pl.coalesce("doi", "doi_t").drop_nulls().first().alias("doi"),
        pl.col("url_destino").drop_nulls().first(),
        pl.col("estado").drop_nulls().first(),
        pl.col("citas").max(),
        pl.col("ids").unique().alias("ids"),
        # Indexación declarada por el portafolio U. de Chile (p. ej. "WOS/SCOPUS/UCH/VID").
        pl.col("ids").str.contains(r'"indexacion": "[^"]*WOS').any().alias("indexada_wos"),
        pl.col("ids").str.contains(r'"indexacion": "[^"]*SCOPUS').any().alias("indexada_scopus"),
        pl.col("spider").unique().sort().alias("fuentes"),
    )
    # Lo que solo reporta OpenAlex puede ser un homónimo mal desambiguado.
    return out.with_columns(confianza=pl.when(pl.col("fuentes") == ["openalex"]).then(0.5).otherwise(1.0))


TRANSFORMS = {
    "publicacion": publicaciones,
    "formacion": lambda df: df.with_columns(
        nivel=pl.col("grado").map_elements(lambda v: classify(v, NIVEL_FORMACION), return_dtype=pl.String)
    ),
    "proyecto": lambda df: df.with_columns(
        codigo=pl.col("codigo").str.strip_chars(),
        instrumento=pl.concat_str("fuente", "titulo", separator=" ", ignore_nulls=True).map_elements(
            lambda v: classify(v, INSTRUMENTO), return_dtype=pl.String
        ),
    ),
    "dictacion": lambda df: df.with_columns(
        codigo_curso=pl.col("codigo_curso").str.to_uppercase(),
        # Cada fuente nombra los semestres a su modo; el calendario chileno: 1er semestre = Otoño.
        semestre=pl.col("semestre").str.to_titlecase().replace(SEMESTRES),
    ),
    "tesis": lambda df: df.with_columns(
        rol_norm=pl.col("rol").fill_null("").map_elements(lambda v: classify(v, ROL_TESIS), return_dtype=pl.String)
    ),
}
# Campos que definen "la misma fila" para deduplicar (además de persona y tipo).
DEDUP_IGNORA = {"url", "spider", "run_id", "scraped_at", "tipo"}


def build() -> dict[str, int]:
    SILVER.mkdir(parents=True, exist_ok=True)
    out = {}
    for tipo, rows in load_bronze().items():
        df = pl.DataFrame(rows, infer_schema_length=None)
        if tipo != "publicacion":
            df = df.unique(subset=[c for c in df.columns if c not in DEDUP_IGNORA], keep="first", maintain_order=True)
        df = TRANSFORMS.get(tipo, lambda d: d)(df)
        df.write_parquet(SILVER / f"{tipo}.parquet")
        out[tipo] = df.height
    for stale in set(TIPOS) - set(out):  # no dejar parquet viejos de tipos que ya no vienen
        (SILVER / f"{stale}.parquet").unlink(missing_ok=True)
    return out
