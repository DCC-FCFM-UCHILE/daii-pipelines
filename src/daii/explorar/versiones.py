"""Versiones de datos (data/versions): builds Silver, cuál está publicada y qué cambió entre dos."""

import polars as pl
import streamlit as st

from daii import versions
from daii.explorar import datos, ui


@st.cache_data(show_spinner="Comparando versiones…")
def _diff(anterior: str, posterior: str) -> dict:
    return versions.diff(anterior, posterior)  # las versiones publicadas son inmutables: el caché no envejece


def _detalle(m: dict) -> None:
    st.subheader(m["build_id"])
    commit = (m.get("commit") or "desconocido")[:10] + (" con cambios sin commitear" if m.get("dirty") else "")
    st.caption(f"Código: commit {commit}. Esquema de manifiesto v{m.get('schema_version')}.")
    corridas = pl.DataFrame(m.get("runs", []))
    if not corridas.is_empty():
        st.markdown("**Corridas bronze fijadas**")
        ui.tabla(corridas.select("spider", "estado", "ultimo_run", "run_en_uso"), key=f"runs_{m['build_id']}")
    silver = m.get("silver") or {}
    if silver:
        st.markdown(f"**Silver:** {len(silver)} tablas · **Config:** {', '.join(m.get('config', {}))}")


def _comparar(publicables: list[str]) -> None:
    st.subheader("Comparar versiones")
    if len(publicables) < 2:
        st.caption("Hacen falta dos versiones publicadas para comparar.")
        return
    izquierda, derecha = st.columns(2)
    anterior = izquierda.selectbox("Anterior", publicables, index=len(publicables) - 2, key="diff_a")
    posterior = derecha.selectbox("Posterior", publicables, index=len(publicables) - 1, key="diff_b")
    if anterior == posterior:
        st.caption("Elige dos versiones distintas.")
        return
    cambios = _diff(anterior, posterior)["cambios"]
    if not cambios:
        st.success("Las dos versiones tienen exactamente los mismos datos.", icon=":material/check_circle:")
        return
    resumen = pl.DataFrame(
        [
            {"tabla": t, "salen": len(c["observaciones_anteriores"]), "entran": len(c["observaciones_posteriores"])}
            for t, c in cambios.items()
        ]
    )
    ui.tabla(resumen, key="diff_resumen")
    for tabla, c in cambios.items():
        with st.expander(f"{tabla}: −{len(c['observaciones_anteriores'])} / +{len(c['observaciones_posteriores'])}"):
            for titulo, filas in (("Salen", c["observaciones_anteriores"]), ("Entran", c["observaciones_posteriores"])):
                if filas:
                    st.markdown(f"**{titulo}**")
                    ui.tabla(pl.DataFrame(filas, infer_schema_length=None), key=f"diff_{tabla}_{titulo}")


def pagina() -> None:
    st.title("Versiones")
    lista = versions.versions() if versions.VERSIONS.exists() else []
    if not lista:
        st.info(
            "Aún no hay versiones. `make silver` prepara un candidato desde bronze y `make gold` lo publica.",
            icon=":material/history:",
        )
        return
    publicada = (datos.release() or {}).get("build_id")
    publicables = [m["build_id"] for m in lista if (versions.VERSIONS / m["build_id"] / "daii.sqlite").exists()]
    tabla = pl.DataFrame(
        [
            {
                "build_id": m["build_id"],
                "fecha": ui.fecha_run(m["build_id"]),
                "estado": "publicada"
                if m["build_id"] == publicada
                else "publicada antes"
                if m["build_id"] in publicables
                else "candidato",
                "commit": (m.get("commit") or "")[:10],
                "cambios sin commitear": bool(m.get("dirty")),
                "corridas": sum(1 for r in m.get("runs", []) if r.get("run_en_uso")),
            }
            for m in reversed(lista)
        ]
    )
    st.caption("Elige una versión para ver su manifiesto.")
    fila = ui.tabla(tabla, key="versiones", seleccion=True)
    if fila:
        _detalle(next(m for m in lista if m["build_id"] == fila["build_id"]))
    _comparar(publicables)
