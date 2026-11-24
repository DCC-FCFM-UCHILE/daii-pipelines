"""Salud de las fuentes: estado de cada spider y su historial de runs (quality.json)."""

import json
from collections import Counter

import altair as alt
import polars as pl
import streamlit as st

from daii.explorar import datos, ui

# paleta categórica validada (DESIGN.md), en orden fijo; lo que no cabe va a "otros", en gris neutro
CATEGORICOS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
OTROS = "#8a8f98"
MAX_SERIES = len(CATEGORICOS)


def _historial(spider: str) -> None:
    hist = datos.historial(spider)
    st.subheader(spider)
    if hist.is_empty():
        st.caption("Este spider no tiene runs.")
        return
    ultimo = hist.row(0, named=True)
    for problema in ultimo["problemas"]:
        st.warning(problema, icon=":material/warning:")
    largo = pl.DataFrame(
        [
            {"run": ui.fecha_run(r["run_id"], corta=True), "tipo": tipo, "ítems": n}
            for r in hist.rows(named=True)
            for tipo, n in r["conteos"].items()
        ],
        schema={"run": pl.String, "tipo": pl.String, "ítems": pl.Int64},
    )
    if largo["run"].n_unique() > 1:
        principales = largo.group_by("tipo").agg(pl.sum("ítems")).sort("ítems", descending=True)["tipo"].to_list()
        largo = (
            largo.with_columns(
                tipo=pl.when(pl.col("tipo").is_in(principales[:MAX_SERIES])).then("tipo").otherwise(pl.lit("otros"))
            )
            .group_by("run", "tipo")
            .agg(pl.sum("ítems"))
        )
        orden = principales[:MAX_SERIES] + (["otros"] if len(principales) > MAX_SERIES else [])
        chart = (
            alt.Chart(largo)  # ty: ignore[missing-attribute]  # Altair tipa mal sus mark_*
            .mark_line(point=alt.OverlayMarkDef(size=64, filled=True), strokeWidth=2)
            .encode(
                x=alt.X("run:O", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("ítems:Q", title="Ítems"),
                color=alt.Color(
                    "tipo:N",
                    title="Tipo",
                    scale=alt.Scale(domain=orden, range=CATEGORICOS[: len(principales[:MAX_SERIES])] + [OTROS]),
                ),
                tooltip=["run", "tipo", "ítems"],
            )
            .properties(height=260)
        )
        st.altair_chart(chart, width="stretch")
    tabla = hist.select(
        pl.col("run_id").map_elements(ui.fecha_run, return_dtype=pl.String).alias("run"),
        "run_id",
        pl.col("estado").str.replace("_", " "),
        pl.col("conteos").map_elements(lambda c: sum(c.values()), return_dtype=pl.Int64).alias("ítems"),
        pl.col("problemas").map_elements(lambda p: "; ".join(p), return_dtype=pl.String).alias("problemas"),
    )
    ui.tabla(tabla, key=f"hist_{spider}")


def pagina() -> None:
    st.title("Runs")
    filas = datos.bronze_runs()
    if not filas:
        st.info("No hay runs en bronze. Corre `make run` o `make crawl SPIDER=…`.", icon=":material/database:")
        return
    estados = Counter(r["estado"] for r in filas)
    resumen = st.container(horizontal=True)
    with resumen:
        for estado in ("fail", "warn", "ok", "sin_evaluar"):
            if estados[estado]:
                color, icono = ui.ESTADOS.get(estado, ("gray", ":material/help:"))
                texto = "sin evaluar" if estado == "sin_evaluar" else estado
                st.badge(f"{estados[estado]} {texto}", icon=icono, color=color)  # ty: ignore[invalid-argument-type]
    st.caption(
        "Silver usa el último run `ok` de cada spider (run en uso). Si el último run no es `ok`, lo publicado viene de "
        "un run anterior. Para aceptar un `warn` revisado: `daii aceptar <spider> <run_id>`."
    )
    orden = {"fail": 0, "warn": 1, "sin_evaluar": 2, "ok": 3}
    tabla = pl.DataFrame(
        [
            {
                "spider": r["spider"],
                "estado": r["estado"].replace("_", " "),
                "último run": ui.fecha_run(r["ultimo_run"]),
                "run en uso": ui.fecha_run(r["run_en_uso"]) if r["run_en_uso"] else "ninguno",
                "al día": r["run_en_uso"] == r["ultimo_run"],
                "problemas": len(json.loads(r["problemas"])),
            }
            for r in sorted(filas, key=lambda r: (orden.get(r["estado"], 2), r["spider"]))
        ]
    )
    st.caption("Elige un spider para ver su historial.")
    fila = ui.tabla(tabla, key="spiders", seleccion=True, altura="content")
    if fila:
        _historial(fila["spider"])
