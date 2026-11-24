"""Explorador DAII: `daii explorar` (o `make explorar`). Solo lee data/. Diseño en DESIGN.md."""

import streamlit as st

from daii.explorar import academicos, agregados, conciliacion, datos, logs, modelo, runs, versiones

st.set_page_config(page_title="Explorador DAII", page_icon=":material/school:", layout="wide")

with st.sidebar:
    st.markdown(":red[**Explorador DAII**]  \nFCFM · Universidad de Chile")
    modo = st.segmented_control(
        "Modo",
        ["DAII", "Pipeline"],
        default="DAII",
        required=True,
        key="modo",
        bind="query-params",  # ?modo=Pipeline: los links a una vista conservan el modo
        help="DAII muestra los datos publicados. Pipeline agrega las capas bronze y silver, runs, versiones y logs.",
    )


def _pipeline(pagina):
    """Las vistas Pipeline existen siempre (un link no rompe), pero en modo DAII invitan a cambiar de modo."""

    def vista() -> None:
        if st.session_state.get("modo") == "Pipeline":
            pagina()
            return
        st.info("Esta vista es del modo Pipeline: muestra runs, versiones y logs del pipeline.", icon=":material/lock:")
        st.button("Cambiar a modo Pipeline", on_click=lambda: st.session_state.update(modo="Pipeline"))

    return vista


paginas = {
    "Explorar": [
        st.Page(
            academicos.pagina, title="Académicos", icon=":material/person_search:", url_path="academicos", default=True
        ),
        st.Page(agregados.pagina, title="Agregados", icon=":material/bar_chart:", url_path="agregados"),
        st.Page(modelo.pagina, title="Modelo de datos", icon=":material/schema:", url_path="modelo"),
        st.Page(conciliacion.pagina, title="Conciliación", icon=":material/merge:", url_path="conciliacion"),
    ]
}
paginas["Pipeline"] = [
    st.Page(_pipeline(runs.pagina), title="Runs", icon=":material/monitor_heart:", url_path="runs"),
    st.Page(_pipeline(versiones.pagina), title="Versiones", icon=":material/history:", url_path="versiones"),
    st.Page(_pipeline(logs.pagina), title="Logs", icon=":material/receipt_long:", url_path="logs"),
]
navegacion = st.navigation(paginas, position="hidden")  # menú propio: la marca y el modo van antes que las páginas

with st.sidebar:
    for seccion, lista in paginas.items():
        if seccion == "Pipeline" and modo != "Pipeline":
            continue
        st.caption(seccion)
        for pagina in lista:
            st.page_link(pagina)
    publicada = datos.release()
    if publicada:
        cuando = publicada["published_at"][:16].replace("T", " ")
        st.caption(f"Versión publicada {publicada['build_id'][:15]}, {cuando} UTC")
    elif datos.GOLD_DB.exists():
        st.caption("Gold sin versión registrada: se publicó antes del versionado.")

navegacion.run()
