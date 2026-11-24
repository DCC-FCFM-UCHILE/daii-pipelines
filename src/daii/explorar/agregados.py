"""Agregados por tipo y capa: producción en el tiempo, cobertura por fuente, calidad de campos y embudo de capas."""

import altair as alt
import polars as pl
import streamlit as st

from daii.explorar import datos, ui

COMPARTIDAS = {"publicacion", "proyecto", "tesis", "producto"}
AZUL = "#324366"  # azul FCFM: serie única (DESIGN.md)
SECUENCIAL = ["#eef0f5", "#17203e"]


def _produccion(df: pl.DataFrame, tipo: str, nombres: dict[str, str]) -> None:
    columna = datos.TIPOS[tipo][2]
    st.subheader("Producción en el tiempo")
    if not columna or columna not in df.columns:
        st.caption(f"{datos.TIPOS[tipo][0]} no tiene año en esta capa.")
        return
    personas = st.multiselect(
        "Académicos",
        sorted(nombres, key=lambda s: nombres[s]),
        format_func=lambda s: nombres[s],
        placeholder="Todos",
        key="prod_personas",
    )
    if personas:
        df = df.filter(pl.col("persona").is_in(personas))
    # en gold una entidad compartida aparece una vez por académico: contar entidades distintas, no filas
    # solo las entidades compartidas entre académicos se cuentan una vez (métricas o dictaciones no se fusionan)
    clave = [c for c in ("titulo", "nombre") if c in df.columns][:1] if tipo in COMPARTIDAS else []
    if not clave:
        df = df.with_row_index("_fila")
        clave = ["_fila"]
    por_anio = (
        df.filter(pl.col(columna).is_not_null())
        .unique([columna, *clave])
        .group_by(columna)
        .len("cantidad")
        .rename({columna: "año"})
        .sort("año")
    )
    sin_anio = df.filter(pl.col(columna).is_null()).height
    if por_anio.is_empty():
        st.caption("Ninguna fila trae año.")
        return
    chart = (
        alt.Chart(por_anio)  # ty: ignore[missing-attribute]  # Altair tipa mal sus mark_*
        .mark_bar(color=AZUL, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
        .encode(
            x=alt.X("año:O", title=None, axis=alt.Axis(labelAngle=0, labelOverlap="greedy")),
            y=alt.Y("cantidad:Q", title=datos.TIPOS[tipo][0]),
            tooltip=[alt.Tooltip("año:O"), alt.Tooltip("cantidad:Q", title=datos.TIPOS[tipo][0])],
        )
        .properties(height=280)
    )
    st.altair_chart(chart, width="stretch")
    if sin_anio:
        st.caption(f"{sin_anio} filas sin año no aparecen en el gráfico.")


def _heatmap(df: pl.DataFrame, x: str, y: str, valor: str, titulo: str, formato: str = "d"):
    return (
        alt.Chart(df)  # ty: ignore[missing-attribute]  # Altair tipa mal sus mark_*
        .mark_rect(stroke="white", strokeWidth=2)
        .encode(
            # sin ocultar ni truncar etiquetas: cada fila y columna es una persona, fuente o campo concreto
            x=alt.X(
                f"{x}:N", title=None, axis=alt.Axis(labelAngle=-40, orient="top", labelOverlap=False, labelLimit=200)
            ),
            y=alt.Y(f"{y}:N", title=None, axis=alt.Axis(labelOverlap=False, labelLimit=260)),
            color=alt.Color(f"{valor}:Q", title=titulo, scale=alt.Scale(range=SECUENCIAL)),
            tooltip=[
                alt.Tooltip(f"{y}:N"),
                alt.Tooltip(f"{x}:N"),
                alt.Tooltip(f"{valor}:Q", title=titulo, format=formato),
            ],
        )
        .properties(height=alt.Step(22))
    )


def _cobertura(df: pl.DataFrame, nombres: dict[str, str]) -> None:
    st.subheader("Cobertura por fuente")
    if "fuente" not in df.columns or df["fuente"].is_null().all():
        st.caption("Esta capa no registra la fuente de este tipo.")
        return
    st.caption(
        "Filas por académico y fuente. Una celda vacía es una fuente que no aportó nada para esa persona. "
        "Los sitios personales (un spider por persona) van juntos en «Sitio personal»."
    )
    conteo = (
        df.filter(pl.col("fuente").is_not_null())
        .with_columns(
            fuente=pl.when(pl.col("fuente").str.starts_with("sitio_"))
            .then(pl.lit("Sitio personal"))
            .otherwise(pl.col("fuente").replace(datos.catalogo("itembronze.spider")))
        )
        .group_by("persona", "fuente")
        .len("filas")
        .with_columns(académico=pl.col("persona").replace_strict(nombres, default=pl.col("persona")))
    )
    st.altair_chart(_heatmap(conteo, "fuente", "académico", "filas", "Filas"), width="stretch")


def _calidad(df: pl.DataFrame) -> None:
    st.subheader("Calidad de campos")
    largo = datos.nulos(df)
    if largo.is_empty():
        st.caption("Sin campos para evaluar.")
        return
    st.caption(
        "Porcentaje de filas sin valor en cada campo, por fuente. Una columna oscura es un parser que no lo extrae."
    )
    largo = largo.with_columns(
        fuente=pl.format("{} ({})", pl.col("fuente").replace(datos.catalogo("itembronze.spider")), "filas"),
        campo=pl.col("campo").map_elements(ui.etiqueta, return_dtype=pl.String),
    )
    st.altair_chart(_heatmap(largo, "campo", "fuente", "pct_nulos", "% vacío", ".0f"), width="stretch")


def _embudo(tipo: str) -> None:
    st.subheader("Embudo de capas")
    st.caption(
        "Filas por capa. Bronze suma lo que reporta cada fuente; silver deduplica por académico; "
        "gold cuenta la relación académico ↔ entidad."
    )
    todo = datos.embudo()
    actual = todo.filter(pl.col("tipo") == datos.TIPOS[tipo][0])
    chart = (
        alt.Chart(actual)  # ty: ignore[missing-attribute]  # Altair tipa mal sus mark_*
        .mark_bar(color=AZUL, cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            y=alt.Y("capa:N", sort=list(datos.CAPAS), title=None),
            x=alt.X("filas:Q", title="Filas"),
            tooltip=["capa", "filas"],
        )
        .properties(height=alt.Step(36))
    )
    st.altair_chart(chart, width="stretch")
    with st.expander("Todos los tipos"):
        ancho = todo.pivot("capa", index="tipo", values="filas").with_columns(
            pl.when(pl.col("bronze") > 0)
            .then((100 - pl.col("silver") / pl.col("bronze") * 100).round(1))
            .alias("% deduplicado en silver")
        )
        ui.tabla(ancho, key="embudo_todo")


def pagina() -> None:
    st.title("Agregados")
    pipeline = st.session_state.get("modo") == "Pipeline"
    if datos.gold_sql("SELECT 1 FROM academico LIMIT 1").is_empty():
        ui.sin_gold()
        return
    etiquetas = {t: v[0] for t, v in datos.TIPOS.items()}
    izquierda, derecha = st.columns([2, 3], vertical_alignment="bottom")
    tipo = izquierda.selectbox("Tipo de dato", list(etiquetas), format_func=lambda t: etiquetas[t], key="agr_tipo")
    capa = "gold"
    if pipeline:
        capa = derecha.segmented_control("Capa", list(datos.CAPAS), default="gold", required=True, key="agr_capa")
    df = datos.capa(capa, tipo)
    if df.is_empty():
        st.info(f"No hay filas de {etiquetas[tipo].lower()} en {capa}.", icon=":material/info:")
        return
    nombres = datos.nombres()
    _produccion(df, tipo, nombres)
    if pipeline:
        por_fuente = datos.con_fuente(df)  # una fila por fuente que reporta cada dato
        _cobertura(por_fuente, nombres)
        _calidad(por_fuente)
        _embudo(tipo)
