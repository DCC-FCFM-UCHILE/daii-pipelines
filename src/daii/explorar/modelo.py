"""Modelo de datos, generado desde el código: el esquema gold (SQLModel), el contrato bronze (pydantic) y los parquet
silver publicados. Así el visor nunca queda desactualizado respecto de lo que el pipeline realmente produce."""

import inspect
import re
from html import escape

import polars as pl
import streamlit as st
from sqlmodel import SQLModel

from daii.bronze.items import MODELOS
from daii.explorar import datos, ui
from daii.gold import models

TIPOS_PY = {
    "str": "texto",
    "int": "entero",
    "float": "decimal",
    "bool": "sí/no",
    "list[str]": "lista de textos",
    "dict[str, str]": "diccionario",
}
TIPOS_SQL = {"VARCHAR": "texto", "INTEGER": "entero", "FLOAT": "decimal", "BOOLEAN": "sí/no"}
OPERACION = {"scraperun", "datarelease"}  # tablas de operación del pipeline, sin relaciones con los datos
AZUL, BORDE, TENUE = "#324366", "#c9cfdc", "#5b5858"  # DESIGN.md


def comentarios(cls: type) -> dict[str, str]:
    """Comentario en línea de cada campo (`campo: tipo  # comentario`), incluidos los heredados de clases de daii."""
    out: dict[str, str] = {}
    for clase in reversed(cls.__mro__):
        if not clase.__module__.startswith("daii"):
            continue
        for linea in inspect.getsource(clase).splitlines():
            if m := re.match(r"\s+(\w+):[^#]*#\s*(.+)", linea):
                out[m[1]] = m[2].strip()
    return out


def _clases_gold() -> dict[str, type]:
    return {
        c.__tablename__: c
        for c in vars(models).values()
        if isinstance(c, type) and issubclass(c, SQLModel) and hasattr(c, "__table__")
    }


def _columnas_gold(tabla: str, clase: type) -> pl.DataFrame:
    notas = comentarios(clase)
    filas = []
    for c in SQLModel.metadata.tables[tabla].columns:
        destino = [f.column.table.name for f in c.foreign_keys]
        clave = "PK" if c.primary_key else ""
        if destino:
            clave = (clave + " · " if clave else "") + f"→ {destino[0]}"
        filas.append(
            {
                "campo": c.name,
                "tipo": TIPOS_SQL.get(str(c.type), str(c.type).lower()),
                "clave": clave or None,
                "obligatorio": not c.nullable,
                "descripción": notas.get(c.name),
            }
        )
    return pl.DataFrame(filas)


def _diagrama() -> str:
    """DOT con una caja por tabla: nombre y sus claves (PK/FK). El detalle completo va en la tabla de abajo."""
    nodos, aristas = [], []
    for nombre, tabla in sorted(SQLModel.metadata.tables.items()):
        if nombre in OPERACION:
            continue
        claves = [c for c in tabla.columns if c.primary_key or c.foreign_keys]
        resto = len(tabla.columns) - len(claves)
        filas = "".join(
            f'<TR><TD ALIGN="LEFT">{"<B>" if c.primary_key else ""}{escape(c.name)}'
            f"{'</B>' if c.primary_key else ''}</TD></TR>"
            for c in claves
        )
        if resto:
            filas += f'<TR><TD ALIGN="LEFT"><FONT COLOR="{TENUE}">+{resto} campos</FONT></TD></TR>'
        nodos.append(
            f'{nombre} [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4" COLOR="{BORDE}">'
            f'<TR><TD BGCOLOR="{AZUL}"><FONT COLOR="white"><B>{nombre}</B></FONT></TD></TR>{filas}</TABLE>>];'
        )
        aristas += [f"{nombre} -> {f.column.table.name};" for c in tabla.columns for f in c.foreign_keys]
    return (
        # académico al centro: casi todo apunta a él, así que un layout radial cabe en pantalla y uno por capas no
        'digraph { layout=neato; overlap=false; sep="+12"; splines=true; bgcolor="transparent";'
        f' node [shape=plain, fontname="Lato", fontsize=11]; edge [color="{BORDE}", arrowsize=0.6];'
        + " ".join(nodos + aristas)
        + "}"
    )


def _gold() -> None:
    st.caption(
        "Tablas de la base publicada y cómo se relacionan. Las entidades compartidas (publicación, proyecto, tesis, "
        "curso, producto) se unen a cada académico por una tabla puente. Las flechas apuntan a la tabla referida."
    )
    st.graphviz_chart(_diagrama(), width="content")
    st.caption("Fuera del diagrama, tablas de operación del pipeline: " + ", ".join(sorted(OPERACION)) + ".")
    with st.expander("Decisiones y simplificaciones del modelo"):
        st.markdown(inspect.getdoc(models) or "")
    clases = _clases_gold()
    # la base publicada puede ser más vieja que el código: contar solo las tablas que existen
    existentes = datos.gold_sql("SELECT name FROM sqlite_master WHERE type = 'table'")
    existentes = set(existentes["name"]) if not existentes.is_empty() else set()
    filas = {t: datos.gold_sql(f'SELECT COUNT(*) AS n FROM "{t}"')["n"][0] for t in clases if t in existentes}
    tabla = st.selectbox(
        "Tabla",
        sorted(clases),
        format_func=lambda t: f"{t} · {filas[t]:,} filas".replace(",", ".") if t in filas else t,
        key="modelo_tabla",
    )
    if doc := clases[tabla].__dict__.get("__doc__"):  # solo el propio: getdoc heredaría el de pydantic
        st.markdown(inspect.cleandoc(doc))
    ui.tabla(_columnas_gold(tabla, clases[tabla]), key=f"modelo_cols_{tabla}", altura="content")


def _etiqueta(tipo: str) -> str:
    return datos.TIPOS[tipo][0] if tipo in datos.TIPOS else "Personas" if tipo == "persona" else tipo.capitalize()


def _tipo_python(anotacion: object) -> str:
    """`str | None` → `texto`: lo opcional ya lo dice la columna «obligatorio»; mismo vocabulario que gold."""
    texto = re.sub(r"<class '(\w+)'>", r"\1", str(anotacion)).replace("typing.", "").replace(" | None", "")
    # vocabulario cerrado: lo que el lector necesita son los valores
    if valores := re.fullmatch(r"Literal\[(.*)\]", texto):
        return "uno de: " + valores[1].replace("'", "")
    return TIPOS_PY.get(texto, texto)


def _bronze() -> None:
    st.caption(
        "Contrato de los ítems que emiten los spiders (`bronze/items.py`). Un ítem con campos fuera del contrato se "
        "descarta y quality lo reporta."
    )
    clases = MODELOS
    tipo = st.selectbox("Tipo de ítem", list(clases), format_func=_etiqueta, key="modelo_bronze")
    clase, notas = clases[tipo], comentarios(clases[tipo])
    filas = [
        {
            "campo": nombre,
            "tipo": _tipo_python(campo.annotation),
            "obligatorio": campo.is_required(),
            "descripción": notas.get(nombre),
        }
        for nombre, campo in clase.model_fields.items()
        if nombre != "tipo"
    ]
    ui.tabla(pl.DataFrame(filas), key=f"modelo_bronze_{tipo}", altura="content")


def _silver() -> None:
    directorio = datos.silver_dir()
    archivos = sorted(directorio.glob("*.parquet"))
    if not archivos:
        st.info("No hay silver todavía: `make silver` lo prepara desde bronze.", icon=":material/database:")
        return
    st.caption(f"Esquema de los parquet de `{directorio.relative_to(datos.BRONZE.parent)}`.")
    nombre = st.selectbox(
        "Tabla", sorted((a.stem for a in archivos), key=_etiqueta), format_func=_etiqueta, key="modelo_silver"
    )
    esquema = pl.read_parquet_schema(directorio / f"{nombre}.parquet")
    ui.tabla(
        pl.DataFrame({"campo": list(esquema), "tipo": [str(t) for t in esquema.values()]}),
        key=f"modelo_silver_{nombre}",
        altura="content",
    )


def pagina() -> None:
    st.title("Modelo de datos")
    if st.session_state.get("modo") != "Pipeline":
        _gold()
        return
    gold, silver, bronze = st.tabs(["Gold", "Silver", "Bronze"])
    with gold:
        _gold()
    with silver:
        _silver()
    with bronze:
        _bronze()
