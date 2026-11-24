"""Auditoría del deduplicador: qué registros unió cada heurística de silver/dedup.py (tabla `fusion` de gold)."""

import polars as pl
import streamlit as st

from daii.explorar import datos, ui

# tabla gold → (tipo bronze, campos que identifican el registro para mostrarlo)
REGISTRO = {
    "publicacion": ("publicacion", ["titulo", "anio", "doi"]),
    "proyecto": ("proyecto", ["titulo", "codigo", "anio_inicio"]),
    "tesis": ("tesis", ["titulo", "estudiante", "nivel", "anio"]),
    "formacion": ("formacion", ["grado", "institucion", "anio"]),
    "afiliacion": ("afiliacion", ["organizacion", "rol", "desde", "hasta"]),
    "area": ("area", ["nombre"]),
    "distincion": ("distincion", ["nombre", "otorgante", "anio"]),
    "actividad": ("actividad", ["titulo", "fecha", "rol"]),
    "perfilexterno": ("perfil", ["plataforma", "url_destino", "identificador"]),
    "dictacion": ("dictacion", ["codigo_curso", "nombre_curso", "anio", "semestre", "rol"]),
    "linkdescubierto": ("link", ["url_destino", "texto"]),
    "paginarelacionada": ("pagina", ["url", "titulo"]),
}

SQL = (
    "SELECT f.tabla, "
    + datos.nombre("fusion.regla", "f.regla")
    + ", f.similitud, ia.persona, f.item_a, ia.spider AS fuente_a, f.item_b, ib.spider AS fuente_b, f.fila_id"
    " FROM fusion f JOIN itembronze ia ON ia.id = f.item_a JOIN itembronze ib ON ib.id = f.item_b"
)


def _textos(tabla: str, ids: list[str]) -> dict[str, str]:
    """item_id → los campos que identifican el registro, tal como los trajo la fuente."""
    tipo, campos = REGISTRO.get(tabla, (tabla, []))
    # el run del que salió cada ítem ("<spider>/<run_id>#<n>"; gold usa un run por spider), no el último en uso
    runs = {i.split("/")[0]: i.split("/")[1].split("#")[0] for i in ids}
    df = datos.bronze(tipo, run_ids=runs)
    if df.is_empty():
        return {}
    df = df.filter(pl.col("item_id").is_in(ids))
    partes = [pl.col(c).cast(pl.String) for c in campos if c in df.columns]
    if not partes:
        return {}
    texto = pl.concat_str(partes, separator=" · ", ignore_nulls=True)
    return dict(df.select("item_id", texto.alias("t")).iter_rows())


def fusiones() -> pl.DataFrame:
    existe = datos.gold_sql("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'fusion'")
    return pl.DataFrame() if existe.is_empty() else datos.gold_sql(SQL)


def pagina() -> None:
    st.title("Fusiones")
    st.caption(
        "Registros que el deduplicador unió en una sola fila, y con qué regla. Las uniones por clave idéntica "
        "(mismo DOI, filas iguales) no aparecen aquí: se ven en la evidencia de cada fila. Las reglas están en "
        "`src/daii/silver/dedup.py` y se describen en el README."
    )
    df = fusiones()
    if df.is_empty():
        if datos.GOLD_DB.exists():
            st.info("La versión publicada no tiene fusiones registradas.", icon=":material/merge:")
        else:
            ui.sin_gold()
        return

    resumen = df.group_by("tabla", "regla").agg(
        pl.len().alias("fusiones"), pl.col("similitud").min().alias("similitud mínima")
    )
    ui.tabla(resumen.sort("tabla", "fusiones", descending=[False, True]), key="fusiones_resumen", altura="content")

    c1, c2 = st.columns(2)
    tablas = sorted(df["tabla"].unique())
    tabla = c1.selectbox("Tabla", tablas, index=tablas.index("publicacion") if "publicacion" in tablas else 0)
    vista = df.filter(pl.col("tabla") == tabla)
    reglas = c2.multiselect("Regla", sorted(vista["regla"].unique()), placeholder="Todas")
    if reglas:
        vista = vista.filter(pl.col("regla").is_in(reglas))

    textos = _textos(tabla, vista["item_a"].to_list() + vista["item_b"].to_list())
    legibles = datos.catalogo("itembronze.spider")
    vista = vista.with_columns(
        registro_a=pl.col("item_a").replace_strict(textos, default=None),
        registro_b=pl.col("item_b").replace_strict(textos, default=None),
        fuente_a=pl.col("fuente_a").replace(legibles),
        fuente_b=pl.col("fuente_b").replace(legibles),
    ).sort("similitud", nulls_last=True)  # los difusos más dudosos primero
    st.caption(
        f"{vista.height} fusiones. Ordenadas por similitud (las más dudosas primero). Registro = lo que trajo la "
        "fuente."
    )
    ui.tabla(
        vista.select(
            "persona", "regla", "similitud", "registro_a", "fuente_a", "registro_b", "fuente_b", "item_a", "item_b"
        ),
        key="fusiones_detalle",
    )
