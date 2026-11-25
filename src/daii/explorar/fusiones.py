"""Auditoría del deduplicador: qué registros unió cada heurística de silver/dedup.py (tabla `fusion` de gold)."""

import polars as pl
import streamlit as st

from daii.explorar import datos, ui
from daii.silver.dedup import TEXTO

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


def _textos(tabla: str, ids: list[str], solo_principal: bool = False) -> dict[str, str]:
    """item_id → los campos que identifican el registro, tal como los trajo la fuente.

    `solo_principal`: solo el texto con que config/fusiones_revisadas.yaml identifica el registro (dedup.TEXTO).
    """
    tipo, campos = REGISTRO.get(tabla, (tabla, []))
    if solo_principal:
        campos = [TEXTO[tipo]] if tipo in TEXTO else []
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


SQL_CANDIDATOS = (
    "SELECT c.tabla, c.similitud, c.diferencia, ia.persona, c.item_a, ia.spider AS fuente_a, c.item_b,"
    " ib.spider AS fuente_b FROM candidato_fusion c"
    " JOIN itembronze ia ON ia.id = c.item_a JOIN itembronze ib ON ib.id = c.item_b"
)


def _consulta(tabla: str, sql: str) -> pl.DataFrame:
    existe = datos.gold_sql(f"SELECT name FROM sqlite_master WHERE type = 'table' AND name = '{tabla}'")
    return pl.DataFrame() if existe.is_empty() else datos.gold_sql(sql)


def fusiones() -> pl.DataFrame:
    return _consulta("fusion", SQL)


def candidatos() -> pl.DataFrame:
    return _consulta("candidato_fusion", SQL_CANDIDATOS)


def _con_registros(vista: pl.DataFrame, tabla: str) -> pl.DataFrame:
    """Agrega lo que trajo cada fuente (registro_a/b) y el nombre legible de la fuente."""
    ids = vista["item_a"].to_list() + vista["item_b"].to_list()
    textos, principal = _textos(tabla, ids), _textos(tabla, ids, solo_principal=True)
    legibles = datos.catalogo("itembronze.spider")
    return vista.with_columns(
        registro_a=pl.col("item_a").replace_strict(textos, default=None),
        registro_b=pl.col("item_b").replace_strict(textos, default=None),
        # lo que se copia a config/fusiones_revisadas.yaml (a/b)
        texto_a=pl.col("item_a").replace_strict(principal, default=None),
        texto_b=pl.col("item_b").replace_strict(principal, default=None),
        fuente_a=pl.col("fuente_a").replace(legibles),
        fuente_b=pl.col("fuente_b").replace(legibles),
    ).sort("similitud", nulls_last=True)  # los difusos más dudosos primero


def pagina() -> None:
    st.title("Fusiones")
    t_fus, t_cand = st.tabs(["Fusiones hechas", "Candidatos"])
    with t_fus:
        _fusiones()
    with t_cand:
        _candidatos()


def _candidatos() -> None:
    st.caption(
        "Uniones que el deduplicador no hizo porque un texto agrega palabras con contenido sobre el otro "
        "(columna `diferencia`): puede ser el mismo registro mal escrito por una fuente o dos registros distintos. "
        "Siguen siendo dos filas hasta que alguien decida en `config/fusiones_revisadas.yaml` (`fusionar` o "
        "`separar`, copiando las columnas `texto_a` y `texto_b` como `a` y `b`) y se vuelvan a correr silver y gold."
    )
    df = candidatos()
    if df.is_empty():
        st.info("No hay candidatos pendientes.", icon=":material/task_alt:")
        return
    for tabla in sorted(df["tabla"].unique()):
        vista = _con_registros(df.filter(pl.col("tabla") == tabla), tabla)
        st.subheader(f"{tabla} ({vista.height})")
        ui.tabla(
            vista.select(
                "persona",
                "similitud",
                "diferencia",
                "registro_a",
                "fuente_a",
                "registro_b",
                "fuente_b",
                "texto_a",
                "texto_b",
                "item_a",
                "item_b",
            ),
            key=f"candidatos_{tabla}",
        )


def _fusiones() -> None:
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

    vista = _con_registros(vista, tabla)
    st.caption(
        f"{vista.height} fusiones. Ordenadas por similitud (las más dudosas primero). Registro = lo que trajo la "
        "fuente. Para deshacer una, agregar sus dos textos (columnas `texto_a` y `texto_b`) a "
        "`config/fusiones_revisadas.yaml` con `decision: separar`."
    )
    ui.tabla(
        vista.select(
            "persona",
            "regla",
            "similitud",
            "registro_a",
            "fuente_a",
            "registro_b",
            "fuente_b",
            "texto_a",
            "texto_b",
            "item_a",
            "item_b",
        ),
        key="fusiones_detalle",
    )
