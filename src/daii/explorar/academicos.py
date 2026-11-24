"""Académicos: lista con conteos y ficha por persona. En modo Pipeline, cada tipo se ve en sus tres capas."""

import polars as pl
import streamlit as st

from daii.explorar import datos, ui

RESUMEN = {"publicacion": "Publicaciones", "proyecto": "Proyectos", "tesis": "Tesis", "dictacion": "Cursos"}
CABECERA = {"perfil"}  # va en la cabecera de la ficha, no en pestañas


def _academicos() -> pl.DataFrame:
    unidad = datos.nombre("academico.unidad", "unidad")
    return datos.gold_sql(f"SELECT id, nombre, {unidad}, cargo, email, foto_url, bio FROM academico ORDER BY nombre")


def _lista(gente: pl.DataFrame) -> None:
    resumen = gente.select("id", pl.col("nombre").alias("Nombre"), pl.col("unidad").alias("Unidad"))
    for tipo, etiqueta in RESUMEN.items():
        conteo = datos.gold(tipo).group_by("academico_id").len().rename({"academico_id": "id", "len": etiqueta})
        conteo = conteo.cast({"id": pl.String})  # sin filas, SQLite no tipa la columna
        resumen = resumen.join(conteo, on="id", how="left").with_columns(pl.col(etiqueta).fill_null(0))
    elegida = ui.tabla(resumen, key="lista", seleccion=True, ocultas=("id",), altura="content")
    if elegida:
        _ir(elegida["id"])
        st.rerun()


def _cabecera(a: dict) -> None:
    izquierda, derecha = st.columns([1, 6], vertical_alignment="center") if a["foto_url"] else (None, st.container())
    if izquierda:
        izquierda.image(a["foto_url"], width=112)
    with derecha:
        st.title(a["nombre"])
        st.caption(" · ".join(x for x in (a["cargo"], a["unidad"]) if x))
        perfiles = datos.gold("perfil").filter(pl.col("academico_id") == a["id"], pl.col("url").is_not_null())
        enlaces = [
            f"[{p['plataforma']}]({p['url']})"
            for p in perfiles.unique("plataforma").sort("plataforma").rows(named=True)
        ]
        if a["email"]:  # algunas fuentes ofuscan el correo ("x at y"): solo se enlaza si es un correo real
            correo = f"[{a['email']}](mailto:{a['email']})" if "@" in a["email"] else a["email"]
            enlaces.insert(0, correo)
        if enlaces:
            st.caption(" · ".join(enlaces))
    if a["bio"]:
        with st.expander("Biografía"):
            st.write(a["bio"])


def _capas(slug: str, tipo: str) -> None:
    """Modo Pipeline: el tipo en gold, silver y bronze; elegir una fila silver muestra su origen en bronze."""
    filas = {c: datos.capa(c, tipo) for c in datos.CAPAS}
    filas = {c: df.filter(pl.col("persona") == slug) if not df.is_empty() else df for c, df in filas.items()}
    capa = st.segmented_control(
        "Capa",
        ["gold", "silver", "bronze"],
        default="gold",
        required=True,
        key=f"capa_{tipo}",
        format_func=lambda c: f"{c} · {filas[c].height}",
    )
    df = ui.procedencia_al_final(filas[capa].drop([c for c in ("persona", "tipo") if c in filas[capa].columns]))
    if capa == "bronze":
        st.caption("Ítems del run en uso de cada spider, tal como los dijo la fuente.")
    if capa != "silver":
        ui.tabla(df, key=f"t_{slug}_{tipo}_{capa}")
        return
    st.caption("Elige una fila para ver los ítems bronze que la originan.")
    fila = ui.tabla(df, key=f"t_{slug}_{tipo}_silver", seleccion=True)
    if fila:
        origen = datos.origen({**fila, "persona": slug}, tipo)
        st.subheader("Origen en bronze")
        if origen.is_empty():
            st.caption("No se encontró el ítem bronze: el run en uso ya no es el que alimentó esta versión de silver.")
        else:
            ui.tabla(ui.procedencia_al_final(origen.drop("persona", "tipo")), key=f"o_{slug}_{tipo}")


def _ficha(a: dict, pipeline: bool) -> None:
    _cabecera(a)
    conteos = {t: datos.gold(t).filter(pl.col("academico_id") == a["id"]).height for t in datos.TIPOS}
    tipos = [t for t in datos.TIPOS if t not in CABECERA and (conteos[t] or pipeline)]
    vacios = [datos.TIPOS[t][0] for t in datos.TIPOS if t not in CABECERA and not conteos[t]]
    if vacios and not pipeline:
        st.caption("Sin datos publicados de: " + ", ".join(vacios) + ".")
    if not tipos:
        return
    for tab, tipo in zip(st.tabs([f"{datos.TIPOS[t][0]} {conteos[t]}" for t in tipos]), tipos, strict=True):
        with tab:
            if pipeline:
                _capas(a["id"], tipo)
            else:
                df = datos.gold(tipo).filter(pl.col("academico_id") == a["id"])
                ui.tabla(df.drop([c for c in ("fuente", "fuentes", "confianza") if c in df.columns]), key=f"g_{tipo}")


def _ir(slug: str | None) -> None:
    """La URL (`?persona=`) es la única fuente de verdad: se puede compartir o recargar la ficha."""
    if slug:
        st.query_params["persona"] = slug
    else:
        st.query_params.pop("persona", None)


def pagina() -> None:
    gente = _academicos()
    if gente.is_empty():
        st.title("Académicos")
        ui.sin_gold()
        return
    nombres = dict(gente.select("id", "nombre").iter_rows())
    actual = st.query_params.get("persona")
    st.session_state["persona"] = actual if actual in nombres else None
    if st.session_state["persona"]:
        volver, buscar = st.columns([1, 2], vertical_alignment="center")
        volver.button("Todos los académicos", icon=":material/arrow_back:", type="tertiary", on_click=_ir, args=(None,))
    else:
        st.title("Académicos")
        st.caption(f"{gente.height} académicos en la versión publicada. Busca por nombre o elige una fila.")
        buscar = st.container()
    buscar.selectbox(
        "Académico/a",
        list(nombres),
        key="persona",
        format_func=lambda s: nombres[s],
        placeholder="Buscar por nombre…",
        label_visibility="collapsed",
        on_change=lambda: _ir(st.session_state["persona"]),
    )
    if not st.session_state["persona"]:
        _lista(gente)
        return
    ficha = gente.filter(pl.col("id") == st.session_state["persona"]).row(0, named=True)
    _ficha(ficha, st.session_state.get("modo") == "Pipeline")
