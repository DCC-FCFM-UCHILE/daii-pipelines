"""Piezas de interfaz compartidas por las páginas del explorador (vocabulario único: ver DESIGN.md)."""

from datetime import datetime
from typing import Literal

import polars as pl
import streamlit as st

ESTADOS = {
    "ok": ("green", ":material/check_circle:"),
    "warn": ("orange", ":material/warning:"),
    "fail": ("red", ":material/error:"),
}


def fecha_run(run_id: str, *, corta: bool = False) -> str:
    """`20261123T185212Z` → `2026-11-23 18:52 UTC` (o `23/11 18:52` para ejes); los run_id son timestamps UTC."""
    try:
        return datetime.strptime(run_id[:15], "%Y%m%dT%H%M%S").strftime(
            "%d/%m %H:%M" if corta else "%Y-%m-%d %H:%M UTC"
        )
    except ValueError:
        return run_id


ACENTOS = {
    "anio": "año",
    "titulo": "título",
    "codigo": "código",
    "institucion": "institución",
    "descripcion": "descripción",
    "organizacion": "organización",
    "metrica": "métrica",
    "pagina": "página",
}


TECNICAS = (
    "fuente",
    "fuentes",
    "confianza",
    "spider",
    "url",
    "run_id",
    "scraped_at",
    "observacion_id",
    "item_id",
    "item_ids",
    "origen",
)


def procedencia_al_final(df: pl.DataFrame) -> pl.DataFrame:
    """En filas de contenido (publicaciones, tesis…), primero el dato y al final de dónde viene."""
    return df.select(sorted(df.columns, key=lambda c: c in TECNICAS))


def etiqueta(columna: str) -> str:
    """`anio_inicio` → `Año inicio`: los nombres de columna del modelo, legibles."""
    texto = " ".join(ACENTOS.get(p, p) for p in columna.split("_"))
    return texto[:1].upper() + texto[1:]


def _config(df: pl.DataFrame, ocultas: tuple[str, ...]) -> dict:
    config: dict = dict.fromkeys(("academico_id", *ocultas))  # None oculta la columna; la persona ya está en contexto
    for c in df.columns:
        if c in config:
            continue
        if c.startswith("url") or c == "foto_url":
            config[c] = st.column_config.LinkColumn(etiqueta(c))
        elif c.startswith("anio") and df.schema[c].is_integer():
            config[c] = st.column_config.NumberColumn(etiqueta(c), format="%d")
        else:
            config[c] = st.column_config.Column(etiqueta(c))
    return config


def tabla(
    df: pl.DataFrame,
    *,
    key: str | None = None,
    seleccion: bool = False,
    altura: int | Literal["content"] | None = None,
    ocultas: tuple[str, ...] = (),
) -> dict | None:
    """Tabla a todo el ancho con links y años bien formateados; con `seleccion`, devuelve la fila elegida."""
    config, altura_ = _config(df, ocultas), altura or "auto"
    if not seleccion:
        st.dataframe(
            df, height=altura_, hide_index=True, width="stretch", column_config=config, key=key, placeholder="—"
        )
        return None
    evento = st.dataframe(
        df,
        height=altura_,
        hide_index=True,
        width="stretch",
        column_config=config,
        key=key,
        placeholder="—",
        on_select="rerun",
        selection_mode="single-row",
    )
    filas = [i for i in evento.selection.rows if i < df.height]  # la selección sobrevive a cambios de datos
    return df.row(filas[0], named=True) if filas else None


def sin_gold() -> None:
    st.info(
        "Todavía no hay datos publicados. Corre `make run` (scrapea y publica) o, si ya hay runs en bronze, "
        "`make silver` y luego `make gold`.",
        icon=":material/database:",
    )
