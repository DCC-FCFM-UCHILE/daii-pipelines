"""Cómo se resuelven las distintas fuentes de verdad. La prioridad sale de `silver.transform.PRIORIDAD` y los spiders de
la tabla `scraperun` publicada; las reglas de identidad están escritas a mano y deben seguir a silver y gold."""

import polars as pl
import streamlit as st

from daii.config import academicos
from daii.explorar import datos, ui
from daii.silver.dedup import TITULO_MIN_PALABRAS
from daii.silver.transform import PRIORIDAD, _prio

FLUJO = """
flowchart LR
    B["Bronze<br/>último run ok de cada spider"] --> S1
    subgraph Silver["Silver, por persona"]
        S1["Filas idénticas entre fuentes<br/>se dejan una vez"]
        S2["Deduplicador: mismo<br/>registro escrito distinto<br/>→ una fila; cada campo<br/>de la más prioritaria"]
    end
    S1 --> S2
    subgraph Gold["Gold, entre personas"]
        G1["Académico: config + campos<br/>de la fuente más prioritaria"]
        G2["Entidades compartidas<br/>publicación, proyecto, tesis,<br/>curso, producto: una fila por clave"]
        G3["Puente persona ↔ entidad"]
        G4["Evidencia: ítems bronze<br/>de cada fila y campo"]
    end
    S2 --> G1 & G2
    G2 --> G3
    G1 & G2 & G3 --> G4
"""

IDENTIDAD = [
    (
        "Publicación",
        "DOI (sin puntuación) → mismo título con un solo DOI real (suma las filas sin DOI y el preprint arXiv) → "
        f"título casi igual (≥ 0.95) con año ±1 (±2 si es arXiv); títulos de menos de {TITULO_MIN_PALABRAS} palabras: "
        "misma persona y año",
        "Silver, entre personas",
        "Campo a campo por prioridad; el tipo prefiere la versión publicada. Citas: máximo. "
        "WOS/Scopus: si alguna lo dice",
    ),
    (
        "Proyecto",
        "Código canónico → mismo título con códigos compatibles",
        "Silver (clave) y gold",
        "Fila de la fuente más prioritaria",
    ),
    (
        "Tesis",
        "Título (o casi igual) con año ±1; sin título: el mismo estudiante",
        "Silver (clave) y gold",
        "Fila de la fuente más prioritaria",
    ),
    ("Curso", "Código → nombre normalizado", "Silver", "Primera fila"),
    ("Producto", "Nombre normalizado", "Gold", "Fila de la fuente más prioritaria"),
    ("Académico", "Slug de config/academicos.yaml", "Gold", "Nombre, unidad y ORCID de config; resto por prioridad"),
    (
        "Formación, afiliación, área, distinción, actividad, dictación, perfil, link, página",
        "Regla propia por tabla (README, sección Deduplicación)",
        "Silver, por persona",
        "Campo a campo por prioridad; en dictación los roles se unen",
    ),
]

LIMITES = """
- **Spiders sin prioridad propia** (marcados abajo) van después de todas las demás fuentes: si chocan entre ellos, gana
  el que llegó primero.
- **Similitud difusa:** puede unir dos obras de título casi idéntico sin DOI que las distinga. Cada unión queda en
  **Fusiones** para revisarla.
- **Publicación compartida por varias personas:** título y tipo salen de la primera persona, no de la fuente más
  confiable.
- **Validación humana** (`verificado` en `docs/modelo_datos.md`) todavía no existe: no hay forma de fijar a mano qué
  fuente gana ni de deshacer una fusión.
"""


def _prioridades() -> pl.DataFrame:
    spiders, legibles = datos.gold_sql("SELECT spider FROM scraperun"), datos.catalogo("itembronze.spider")
    nombres = sorted(set(PRIORIDAD) | set(spiders["spider"].to_list() if not spiders.is_empty() else []))
    sitios = [s for s in nombres if s.startswith("sitio_")]
    filas = [
        {
            "prioridad": _prio(s),
            "fuente": legibles.get(s, s),
            "nota": "propia" if s in PRIORIDAD else "sin prioridad propia: va al final",
        }
        for s in nombres
        if not s.startswith("sitio_")
    ]
    filas.append({"prioridad": 0, "fuente": f"Sitios personales ({len(sitios)})", "nota": "curado por la persona"})
    return pl.DataFrame(filas).sort("prioridad", "fuente")


def _publicaciones_por_fuente() -> pl.DataFrame:
    df = datos.gold_sql(
        "SELECT fuentes, COUNT(*) AS filas, ROUND(AVG(confianza), 2) AS confianza FROM (SELECT confianza, "
        + datos.fuentes("publicacionacademico", "pa.publicacion_id", "pa.academico_id")
        + " FROM publicacionacademico pa) GROUP BY fuentes ORDER BY filas DESC"
    )
    if df.is_empty():
        return df
    legibles = datos.catalogo("itembronze.spider")
    return df.with_columns(
        pl.col("fuentes").str.json_decode(pl.List(pl.String)).list.eval(pl.element().replace(legibles)).list.join(" · ")
    )


def pagina() -> None:
    st.title("Conciliación de fuentes")
    st.caption(
        "Varias fuentes describen a la misma persona. Así decide el pipeline qué registros son el mismo dato y, "
        "cuando difieren, qué fuente gana."
    )
    st.mermaid_chart(FLUJO, alt="Flujo de conciliación: bronze → silver por persona → gold entre personas")

    st.subheader("Prioridad de fuentes")
    st.caption("Menor gana. Se aplica campo a campo (publicaciones, académico) o a la fila completa (proyecto, tesis).")
    ui.tabla(_prioridades(), key="conciliacion_prioridad", altura="content")
    propias = [f"{a['nombre']}: {' > '.join(a['prioridad'])}" for a in academicos() if a.get("prioridad")]
    st.caption(
        "Orden propio (campo `prioridad` en config/academicos.yaml; esas fuentes van antes del orden global): "
        + ("; ".join(propias) if propias else "nadie lo tiene.")
    )

    st.subheader("Cómo se reconoce el mismo dato")
    ui.tabla(
        pl.DataFrame(IDENTIDAD, schema=["entidad", "clave", "dónde", "si difieren"], orient="row"),
        key="conciliacion_identidad",
        altura="content",
    )

    st.subheader("Publicaciones según cuántas fuentes las respaldan")
    pubs = _publicaciones_por_fuente()
    if pubs.is_empty():
        ui.sin_gold()
    else:
        st.caption("Confianza 0.5: solo OpenAlex la reporta (posible homónimo).")
        ui.tabla(pubs, key="conciliacion_pubs", altura="content")

    st.subheader("Límites conocidos")
    st.markdown(LIMITES)
