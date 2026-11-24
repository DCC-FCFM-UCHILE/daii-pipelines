"""Heurísticas de deduplicación: cuándo dos filas son el mismo registro y cómo se fusionan.

Todo lo que decide "esto es lo mismo" vive aquí; `transform.py` y `gold/load.py` solo lo llaman.

- Tablas por persona (afiliación, formación…): `aplicar()` agrupa con una regla `REGLAS[tipo]` y fusiona cada grupo
  en una fila. Cada campo sale de la fila más prioritaria que lo trae; `origen` dice de qué ítem.
- Entidades compartidas (publicación, proyecto, tesis): `clave_*()` les asigna la misma clave a las filas de todas las
  personas que son la misma entidad; gold las une por esa clave.

Auditoría: cada unión hecha por una heurística deja una arista (item_a, item_b, regla, similitud) en la columna
`fusiones` de las filas resultantes; gold la publica en la tabla `fusion`. Las uniones por clave idéntica (mismo DOI,
mismo título y año, filas idénticas) no dejan arista: ya pasaban antes y la evidencia las muestra.
"""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterator
from difflib import SequenceMatcher
from functools import lru_cache

import polars as pl

UMBRAL = 0.95  # similitud difusa mínima entre textos (difflib ratio sobre texto normalizado)
PALABRA = 0.8  # dos palabras distintas cuentan como typo una de otra sobre este ratio ("filter"/"filtering")
TITULO_MIN_PALABRAS = 4  # bajo esto un título es "genérico" ("Preface"): no se compara difuso ni se hereda DOI

# Código de cada regla (va a la tabla `fusion`; su nombre legible está en config/catalogos.yaml, `fusion.regla`).
REGLAS_FUSION = (
    "doi_canonico",
    "arxiv_titulo",
    "titulo_sin_doi",
    "titulo_corto_mismo_anio",
    "titulo_difuso",
    "codigo_canonico",
    "codigo_sufijo",
    "titulo_sin_codigo",
    "titulo_anio_cercano",
    "estudiante_sin_titulo",
    "misma_afiliacion",
    "misma_formacion",
    "misma_area",
    "misma_distincion",
    "misma_actividad",
    "mismo_perfil",
    "misma_dictacion",
    "misma_url",
)
FUSION = pl.List(pl.Struct({"item_a": pl.String, "item_b": pl.String, "regla": pl.String, "similitud": pl.Float64}))

Coincide = tuple[str, float | None] | None  # (regla, similitud) o None si no son el mismo registro


@lru_cache(maxsize=200_000)
def norm_text(s: str | None) -> str:
    """Clave de comparación: minúsculas, sin tildes ni puntuación."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def largo(texto_norm: str) -> bool:
    return texto_norm.count(" ") >= TITULO_MIN_PALABRAS - 1


def similar(a: str | None, b: str | None) -> float | None:
    """1.0 si son iguales normalizados; el ratio si ambos son largos y superan UMBRAL; si no, None."""
    na, nb = norm_text(a), norm_text(b)
    if not na or not nb:
        return None
    if na == nb:
        return 1.0
    return _ratio(na, nb) if largo(na) and largo(nb) else None


def _ratio(na: str, nb: str) -> float | None:
    # "Transient Discovery Report for 2018-02-14" ≠ "… 2018-04-21", "Part 1" ≠ "Part 2": los números deben coincidir
    if re.findall(r"\d+", na) != re.findall(r"\d+", nb):
        return None
    sm = SequenceMatcher(None, na, nb, autojunk=False)
    if sm.real_quick_ratio() < UMBRAL or sm.quick_ratio() < UMBRAL:  # filtros baratos primero
        return None
    r = sm.ratio()
    return r if r >= UMBRAL and _palabras_compatibles(na, nb) else None


def _palabras_compatibles(na: str, nb: str) -> bool:
    """Uno solo agrega palabras ("A Gradual…" ⊇ "Gradual…"), o cada palabra distinta es un typo de otra
    ("Filter"/"Filtering"). Así "WWW2011 Tutorial" ≠ "ISWC2011 Tutorial" y "Simple…" ≠ "Improved…" aunque el ratio
    de caracteres pase el umbral.
    """
    sa, sb = set(na.split()), set(nb.split())
    solo_a, solo_b = sa - sb, sb - sa
    if not solo_a or not solo_b:
        return True
    cerca = lambda w, otras: any(SequenceMatcher(None, w, o).ratio() >= PALABRA for o in otras)  # noqa: E731
    return all(cerca(w, solo_b) for w in solo_a) and all(cerca(w, solo_a) for w in solo_b)


def compatible(a: str | None, b: str | None) -> bool:
    """Campo secundario: alguno falta, son iguales, o las palabras de uno están todas en el otro."""
    na, nb = set(norm_text(a).split()), set(norm_text(b).split())
    return not na or not nb or na <= nb or nb <= na


def pares_difusos(textos: list[str]) -> Iterator[tuple[int, int, float]]:
    """Pares (i, j, ratio) de textos normalizados largos y distintos con ratio ≥ UMBRAL.

    ratio ≥ 0.95 exige largos parecidos (2·min/(a+b)): se ordena por largo y se compara solo dentro de esa ventana.
    """
    orden = sorted((len(t), i) for i, t in enumerate(textos) if largo(t))
    for x, (la, i) in enumerate(orden):
        for lb, j in orden[x + 1 :]:
            if 2 * la / (la + lb) < UMBRAL:
                break
            if textos[i] != textos[j] and (r := _ratio(textos[i], textos[j])):
                yield i, j, r


def url_canon(u: str | None) -> str:
    # shortcut: pasa todo a minúsculas (también la ruta, que en rigor distingue mayúsculas); afinar si fusiona de más
    return re.sub(r"^https?://(www\.)?", "", (u or "").strip().lower()).rstrip("/")


# --- agrupación (union-find) -----------------------------------------------------------------------------------


class _Grupos:
    """Union-find sobre filas; cada unión hecha por una regla queda como arista auditable."""

    def __init__(self, items: list[str], veto: Callable[[int, int], bool] | None = None) -> None:
        self.padre, self.items, self.veto = list(range(len(items))), items, veto
        self.aristas: list[tuple[int, dict]] = []  # (raíz al unir, arista)

    def raiz(self, i: int) -> int:
        while self.padre[i] != i:
            self.padre[i] = self.padre[self.padre[i]]
            i = self.padre[i]
        return i

    def unir(self, i: int, j: int, regla: str | None = None, similitud: float | None = None) -> bool:
        """Une los grupos de i y j (la raíz es la de menor índice = más prioritaria). `regla=None`: sin arista."""
        ri, rj = sorted((self.raiz(i), self.raiz(j)))
        if ri == rj or (self.veto and self.veto(ri, rj)):
            return False
        self.padre[rj] = ri
        if regla:
            assert regla in REGLAS_FUSION, regla
            arista = dict(item_a=self.items[i], item_b=self.items[j], regla=regla, similitud=similitud)
            self.aristas.append((ri, arista))
        return True

    def resultado(self) -> tuple[list[int], dict[int, list[dict]]]:
        """Id de grupo por fila (su raíz) y las aristas de cada grupo."""
        grupo = [self.raiz(i) for i in range(len(self.padre))]
        por_grupo: dict[int, list[dict]] = defaultdict(list)
        for r, arista in self.aristas:
            por_grupo[self.raiz(r)].append(arista)
        return grupo, por_grupo


def _con_grupos(df: pl.DataFrame, grupo: list[int], aristas: dict[int, list[dict]]) -> pl.DataFrame:
    """Agrega `_grupo` y `fusiones` (aristas del grupo; null si no hubo heurística)."""
    return df.with_columns(
        _grupo=pl.Series(grupo, dtype=pl.Int64),
        fusiones=pl.Series([aristas.get(g) for g in grupo], dtype=FUSION),
    )


# --- tablas por persona ----------------------------------------------------------------------------------------


def _afiliacion(a: dict, b: dict) -> Coincide:
    s = similar(a["organizacion"], b["organizacion"])
    fechas = all(a[c] is None or b[c] is None or a[c] == b[c] for c in ("desde", "hasta"))
    # rol igual o ausente: por contención "Professor" ⊂ "Assistant Professor" uniría cargos distintos
    rol = not a["rol"] or not b["rol"] or norm_text(a["rol"]) == norm_text(b["rol"])
    return ("misma_afiliacion", s) if s and rol and fechas else None


# Palabras que no distinguen instituciones ("Universidad de Chile" ≡ "University of Chile").
_GENERICAS = {
    "universidad", "university", "universite", "universitat", "universidade", "universita",
    "de", "del", "la", "el", "of", "the", "at", "in", "en", "y", "and",
    "francia", "france", "usa", "uk", "eeuu",  # el país al final ("…, Francia") tampoco distingue
}  # fmt: skip


def _institucion(s: str | None) -> frozenset[str]:
    palabras = set(norm_text(s).split())
    return frozenset(palabras - _GENERICAS) or frozenset(palabras)  # "Universidad de Chile" → {"chile"}


def _formacion(a: dict, b: dict) -> Coincide:
    if a["anio"] is None:
        return None
    ia, ib = _institucion(a["institucion"]), _institucion(b["institucion"])
    # postgrado: uno por nivel y año; pregrado: se puede titular de dos carreras el mismo año (grado compatible)
    grado = a["nivel"] in ("doctorado", "magister", "postdoctorado") or compatible(a["grado"], b["grado"])
    return ("misma_formacion", None) if (not ia or not ib or ia == ib) and grado else None


def _area(a: dict, b: dict) -> Coincide:
    return ("misma_area", s) if (s := similar(a["nombre"], b["nombre"])) else None


def _distincion(a: dict, b: dict) -> Coincide:
    s = similar(a["nombre"], b["nombre"])
    return ("misma_distincion", s) if s and compatible(a["otorgante"], b["otorgante"]) else None


def _actividad(a: dict, b: dict) -> Coincide:
    s = similar(a["titulo"], b["titulo"])
    ok = s and norm_text(a["fecha"]) == norm_text(b["fecha"]) and compatible(a["rol"], b["rol"])
    return ("misma_actividad", s) if ok else None


def _perfil(a: dict, b: dict) -> Coincide:
    if norm_text(a["plataforma"]) != norm_text(b["plataforma"]):
        return None
    misma_url = url_canon(a["url_destino"]) == url_canon(b["url_destino"])
    mismo_id = a["identificador"] is not None and a["identificador"] == b["identificador"]
    return ("mismo_perfil", None) if misma_url or mismo_id else None


def _dictacion(a: dict, b: dict) -> Coincide:
    # el bloque ya es persona + curso + año + semestre; sin año no hay cómo saber si es la misma dictación
    return ("misma_dictacion", None) if a["anio"] is not None else None


def _url(campo: str) -> Callable[[dict, dict], Coincide]:
    return lambda a, b: ("misma_url", None) if url_canon(a[campo]) == url_canon(b[campo]) else None


# tipo → (columnas de bloque: solo se comparan filas con los mismos valores, regla, agregaciones especiales)
REGLAS: dict[str, tuple[list[str], Callable[[dict, dict], Coincide], dict[str, pl.Expr]]] = {
    "afiliacion": (["persona"], _afiliacion, {}),
    "formacion": (["persona", "nivel", "anio"], _formacion, {}),
    "area": (["persona"], _area, {}),
    "distincion": (["persona", "anio"], _distincion, {}),
    "actividad": (["persona", "tipo_actividad"], _actividad, {}),
    "perfil": (["persona"], _perfil, {}),
    "dictacion": (
        ["persona", "curso_id", "anio", "semestre"],
        _dictacion,
        # coordinador y profesor de cátedra del mismo curso: una dictación con ambos roles
        {"rol": pl.col("rol").drop_nulls().unique(maintain_order=True).str.join("; ")},
    ),
    "link": (["persona", "url"], _url("url_destino"), {}),
    "pagina": (["persona"], _url("url"), {}),
}
# Columnas de procedencia: no son datos del registro, se toma la de la fila más prioritaria.
TECNICAS = {"persona", "url", "spider", "run_id", "scraped_at", "observacion_id", "tipo", "item_id", "item_ids"}


def agrupar(
    df: pl.DataFrame, bloque: list[str], mismo: Callable[[dict, dict], Coincide]
) -> tuple[list[int], dict[int, list[dict]]]:
    """Compara todas las filas de cada bloque (df ya ordenado por prioridad) y une las que `mismo` dice iguales.

    Una fila entra a un grupo solo si es igual a *todos* sus miembros: "Profesor" sin fechas es compatible con
    2005–2010 y con 2015–2020, pero no puede pegar esos dos períodos en una fila (las reglas no son transitivas).
    """
    filas = df.to_dicts()
    g = _Grupos([f["item_id"] for f in filas])
    miembros: dict[int, list[int]] = {i: [i] for i in range(len(filas))}
    bloques: dict[tuple, list[int]] = defaultdict(list)
    for i, f in enumerate(filas):
        bloques[tuple(f[c] for c in bloque)].append(i)
    for idx in bloques.values():
        for x, i in enumerate(idx):
            for j in idx[:x]:
                ri, rj = g.raiz(i), g.raiz(j)
                if ri == rj or not (c := mismo(filas[j], filas[i])):
                    continue
                if all(mismo(filas[a], filas[b]) for a in miembros[rj] for b in miembros[ri] if (a, b) != (j, i)):
                    g.unir(j, i, *c)
                    raiz = g.raiz(i)
                    miembros[raiz] += miembros.pop(rj if raiz == ri else ri)
    return g.resultado()


def aplicar(tipo: str, df: pl.DataFrame) -> pl.DataFrame:
    """Fusiona las filas que la regla de `tipo` considera el mismo registro. `df` debe venir ordenado por prioridad.

    Cada campo sale de la primera fila del grupo que lo trae; `origen` (campo → item_id) solo en grupos fusionados.
    """
    if tipo not in REGLAS or df.is_empty():
        return df
    bloque, mismo, especiales = REGLAS[tipo]
    df = _con_grupos(df, *agrupar(df, bloque, mismo))
    datos = [c for c in df.columns if c not in TECNICAS | {"_grupo", "fusiones"}]
    de = lambda cond: pl.col("item_id").filter(cond).first()  # noqa: E731
    out = df.group_by("_grupo", maintain_order=True).agg(
        *(pl.col(c).first() for c in TECNICAS - {"item_ids"} if c in df.columns),
        *(especiales.get(c, pl.col(c).drop_nulls().first()) for c in datos),
        pl.col("item_ids").explode(),
        pl.col("fusiones").first(),
        pl.struct([de(pl.col(c).is_not_null()).alias(c) for c in datos]).alias("origen"),
        pl.len().alias("_filas"),
    )
    return (
        out.with_columns(origen=pl.when(pl.col("_filas") > 1).then("origen"))
        .drop("_grupo", "_filas")
        .select(*df.columns[: df.columns.index("_grupo")], "fusiones", "origen")
    )


# --- publicaciones ---------------------------------------------------------------------------------------------


def doi_limpio(col: pl.Expr) -> pl.Expr:
    """DOI desde URL o texto con basura ("bar050\\n10.1093/…"), sin sufijos de formato (/pdf, /full, .pdf)."""
    return (
        col.cast(pl.String)
        .str.to_lowercase()
        .str.extract(r"(10\.\d{4,9}/\S+)")
        .str.strip_chars_end(";.")
        .str.replace(r"/(pdf|full|abstract)$|\.pdf$", "")
    )


def es_arxiv(doi: str | None) -> bool:
    return bool(doi) and doi.startswith("10.48550/arxiv")


def _alnum(doi: str) -> str:
    return re.sub(r"[^a-z0-9]", "", doi)  # 978-3-642-34109-0_15 ≡ 978-3-642-34109-0-15


def clave_publicacion(df: pl.DataFrame) -> pl.DataFrame:
    """`pub_key`, `doi_grupo` y `fusiones` por fila, sobre todas las personas (df ordenado por prioridad).

    Requiere columnas `doi` (limpio), `titulo_norm`, `anio`, `persona`, `item_id`.
    1. Mismo DOI (comparado sin puntuación) → misma obra. Dos DOIs reales distintos nunca se unen (veto).
    2. Mismo título largo: si a lo más un DOI real lo usa, se le unen las filas sin DOI y las de arXiv.
       Título corto ("Preface"): solo filas de la misma persona y el mismo año.
    3. Títulos largos casi iguales (ratio ≥ UMBRAL) con años a ±1 (±2 si una es arXiv) → misma obra.
    Clave: DOI real (de la fila más prioritaria) > DOI arXiv > "t:<título>" ("|<año>" si es corto).
    """
    filas = df.select("doi", "titulo_norm", "anio", "persona", "item_id").to_dicts()
    reales = [{_alnum(f["doi"])} if f["doi"] and not es_arxiv(f["doi"]) else set() for f in filas]

    def veto(ri: int, rj: int) -> bool:
        if reales[ri] and reales[rj] and reales[ri] != reales[rj]:
            return True
        reales[ri] |= reales[rj]
        return False

    g = _Grupos([f["item_id"] for f in filas], veto)
    primero: dict[str, int] = {}
    for i, f in enumerate(filas):  # 1. DOI
        if f["doi"]:
            j = primero.setdefault(_alnum(f["doi"]), i)
            g.unir(j, i, "doi_canonico" if filas[j]["doi"] != f["doi"] else None)

    por_titulo: dict[tuple, list[int]] = defaultdict(list)  # 2. título
    for i, f in enumerate(filas):
        t = f["titulo_norm"]
        por_titulo[(t,) if largo(t) else (t, f["anio"], f["persona"])].append(i)
    for clave, idx in por_titulo.items():
        sin = [i for i in idx if not filas[i]["doi"]]
        for i in sin[1:]:
            g.unir(sin[0], i)  # mismo título sin DOI: misma clave "t:" de siempre
        if len({d for i in idx for d in reales[i]}) > 1:
            continue  # título ambiguo (dos DOIs reales): no se le asigna a ninguno
        con = [i for i in idx if reales[i]]
        destino = con[0] if con else (sin[0] if sin else idx[0])
        for i in idx:
            if es_arxiv(filas[i]["doi"]):
                g.unir(destino, i, "arxiv_titulo")
            elif not filas[i]["doi"] and con:
                g.unir(destino, i, "titulo_sin_doi" if len(clave) == 1 else "titulo_corto_mismo_anio")

    titulos = list({f["titulo_norm"]: None for f in filas})  # 3. difuso
    rep = {t: next(i for i, f in enumerate(filas) if f["titulo_norm"] == t) for t in titulos if largo(t)}
    anios: dict[str, set[int]] = defaultdict(set)
    arxiv: dict[str, bool] = defaultdict(bool)
    for f in filas:
        if f["anio"] is not None:
            anios[f["titulo_norm"]].add(f["anio"])
        arxiv[f["titulo_norm"]] |= es_arxiv(f["doi"])
    for a, b, r in pares_difusos(titulos):
        ta, tb = titulos[a], titulos[b]
        tol = 2 if arxiv[ta] or arxiv[tb] else 1
        if not anios[ta] or not anios[tb] or any(abs(x - y) <= tol for x in anios[ta] for y in anios[tb]):
            g.unir(rep[ta], rep[tb], "titulo_difuso", round(r, 4))

    grupo, aristas = g.resultado()

    def rango(i: int) -> tuple[int, int]:  # DOI real > DOI arXiv > sin DOI; dentro, la fila más prioritaria
        d = filas[i]["doi"]
        return (0 if d and not es_arxiv(d) else 1 if d else 2), i

    claves: dict[int, tuple[str, str | None]] = {}
    for i in sorted(range(len(filas)), key=rango):
        if (r := grupo[i]) not in claves:
            f, t = filas[i], "t:" + filas[i]["titulo_norm"]
            anio = "?" if f["anio"] is None else f["anio"]
            claves[r] = (f["doi"], f["doi"]) if f["doi"] else (t if largo(f["titulo_norm"]) else f"{t}|{anio}", None)
    return _con_grupos(df, grupo, aristas).with_columns(
        pub_key=pl.Series([claves[r][0] for r in grupo], dtype=pl.String),
        doi_grupo=pl.Series([claves[r][1] for r in grupo], dtype=pl.String),
    )


def _clave_por_rango(filas: list[dict], grupo: list[int], rango: Callable[[int], tuple], clave: Callable[[dict], str]):
    """Clave de cada grupo: la de su fila de menor `rango` (la más identificable y prioritaria)."""
    claves: dict[int, str] = {}
    for i in sorted(range(len(filas)), key=rango):
        claves.setdefault(grupo[i], clave(filas[i]))
    return pl.Series([claves[r] for r in grupo], dtype=pl.String)


def _unir_difusos(g: _Grupos, filas: list[dict], ok: Callable[[int, int], bool]) -> None:
    """Une la primera fila de cada par de títulos casi iguales si `ok(fila_a, fila_b)`."""
    titulos = list({f["_t"]: None for f in filas if f["_t"]})
    rep = {t: next(i for i, f in enumerate(filas) if f["_t"] == t) for t in titulos}
    for a, b, r in pares_difusos(titulos):
        i, j = rep[titulos[a]], rep[titulos[b]]
        if ok(i, j):
            g.unir(i, j, "titulo_difuso", round(r, 4))


# --- proyectos -------------------------------------------------------------------------------------------------


def codigo_canon(c: str | None) -> str | None:
    return re.sub(r"[^A-Z0-9]", "", (c or "").upper()) or None  # "I D25I10330" ≡ "ID25I10330"


def _codigos_compatibles(a: str, b: str) -> bool:
    """Iguales, o uno es sufijo del otro con ≥ 6 dígitos: "ACT192015" ⊂ "PIAACT192015", "150083" ⊂ "REDES150083"."""
    corto, largo_ = sorted((a, b), key=len)
    return largo_.endswith(corto) and sum(ch.isdigit() for ch in corto) >= 6


def clave_proyecto(df: pl.DataFrame) -> pl.DataFrame:
    """`clave` y `fusiones` por fila, sobre todas las personas (df ordenado por prioridad).

    Mismo código canónico → mismo proyecto. Mismo título (o casi igual) → mismo proyecto si los códigos son
    compatibles o alguno falta. Códigos incompatibles nunca se unen (Basal PFB03 ≠ FB210005: períodos distintos).
    """
    df = df.with_columns(_t=pl.col("titulo").map_elements(norm_text, return_dtype=pl.String))
    filas = df.select("codigo", "_t", "item_id").to_dicts()
    cods = [{c} if (c := codigo_canon(f["codigo"])) else set() for f in filas]

    def veto(ri: int, rj: int) -> bool:
        if not all(a == b or _codigos_compatibles(a, b) for a in cods[ri] for b in cods[rj]):
            return True
        cods[ri] |= cods[rj]
        return False

    g = _Grupos([f["item_id"] for f in filas], veto)
    primero: dict[str, int] = {}
    for i, f in enumerate(filas):
        if c := codigo_canon(f["codigo"]):
            j = primero.setdefault(c, i)
            g.unir(j, i, "codigo_canonico" if filas[j]["codigo"] != f["codigo"] else None)
    por_titulo: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(filas):
        por_titulo[f["_t"]].append(i)
    for idx in por_titulo.values():
        con = [i for i in idx if filas[i]["codigo"]]
        sin = [i for i in idx if not filas[i]["codigo"]]
        for i in sin[1:]:
            g.unir(sin[0], i)  # mismo título sin código: misma clave "t:" de siempre
        for i in con[1:]:
            g.unir(con[0], i, "codigo_sufijo")  # el veto rechaza los incompatibles
        if con and sin:
            g.unir(con[0], sin[0], "titulo_sin_codigo")
    _unir_difusos(g, filas, lambda i, j: True)  # el veto cuida los códigos
    grupo, aristas = g.resultado()
    clave = _clave_por_rango(
        filas, grupo, lambda i: (not filas[i]["codigo"], i), lambda f: f["codigo"] or "t:" + f["_t"]
    )
    return _con_grupos(df, grupo, aristas).with_columns(clave=clave).drop("_t", "_grupo")


# --- cursos ----------------------------------------------------------------------------------------------------


def clave_curso() -> pl.Expr:
    """Manda el código (mismo nombre con códigos distintos son cursos distintos: CI41C ≠ CI5101); sin código, el nombre.

    `codigo_curso` ya viene en mayúsculas y sin espacios (transform).
    """
    return pl.coalesce(
        "codigo_curso", pl.col("nombre_curso").map_elements(lambda s: "n:" + norm_text(s), return_dtype=pl.String)
    )


# --- tesis -----------------------------------------------------------------------------------------------------

NIVEL_TESIS = [  # grueso: las fuentes escriben "Eng", "Undergraduate Students", "B.Sc.", "Masters in CS"…
    ("doctorado", r"doct|ph\.? ?d|\bdr\b"),
    ("magister", r"mag[ií]ster|master|m\.? ?sc|msc"),
    ("pregrado", r"\beng|ingenier|undergrad|b\.? ?sc|licenc|memoria|pregrado|t[ií]tulo|bachelor"),
]


def _nivel_tesis(v: str | None) -> str | None:
    return next((k for k, rx in NIVEL_TESIS if re.search(rx, (v or "").lower())), None)


def clave_tesis(df: pl.DataFrame) -> pl.DataFrame:
    """`clave` (texto; gold la hashea) y `fusiones` por fila, sobre todas las personas (df ordenado por prioridad).

    Con título: mismo título (o casi igual) con año a ±1 o desconocido y estudiante compatible.
    Sin título: se une a la única tesis de la misma persona y estudiante con nivel compatible (doctorado/magíster/
    pregrado) y año a ±1 o desconocido. Sin título ni estudiante no hay con qué identificarla: queda sola.
    """
    df = df.with_columns(_t=pl.col("titulo").map_elements(norm_text, return_dtype=pl.String))
    filas = df.select("_t", "anio", "estudiante", "nivel", "persona", "item_id").to_dicts()
    for f in filas:
        f["_e"], f["_n"] = norm_text(f["estudiante"]), _nivel_tesis(f["nivel"])
    g = _Grupos([f["item_id"] for f in filas])

    def anio_cerca(a: dict, b: dict) -> bool:
        return a["anio"] is None or b["anio"] is None or abs(a["anio"] - b["anio"]) <= 1

    def cerca(i: int, j: int) -> bool:
        return anio_cerca(filas[i], filas[j]) and compatible(filas[i]["estudiante"], filas[j]["estudiante"])

    def mismo_nivel(i: int, j: int) -> bool:
        a, b = filas[i], filas[j]
        return anio_cerca(a, b) and (not a["_n"] or not b["_n"] or a["_n"] == b["_n"])

    por_titulo: dict[str, list[int]] = defaultdict(list)
    for i, f in enumerate(filas):
        if f["_t"]:
            por_titulo[f["_t"]].append(i)
    for idx in por_titulo.values():
        for x, i in enumerate(idx):
            for j in idx[:x]:
                if filas[i]["anio"] == filas[j]["anio"]:
                    g.unir(j, i)  # mismo título y año: misma clave de siempre
                elif cerca(j, i):
                    g.unir(j, i, "titulo_anio_cercano")
    _unir_difusos(g, filas, cerca)

    # sin título: con la única tesis (con título si la hay) de la misma persona y estudiante, de nivel compatible
    por_estudiante: dict[tuple, list[int]] = defaultdict(list)
    for i, f in enumerate(filas):
        if f["_e"]:
            por_estudiante[(f["persona"], f["_e"])].append(i)
    for idx in por_estudiante.values():
        for i in (i for i in idx if not filas[i]["_t"]):
            cand = {g.raiz(j) for j in idx if filas[j]["_t"] and mismo_nivel(i, j)}
            if len(cand) == 1:
                g.unir(cand.pop(), i, "estudiante_sin_titulo")
            elif not cand:
                for j in (j for j in idx if j < i and not filas[j]["_t"] and mismo_nivel(i, j)):
                    same = filas[i]["anio"] == filas[j]["anio"]
                    g.unir(j, i, None if same else "estudiante_sin_titulo")
                    break
    grupo, aristas = g.resultado()

    def clave(f: dict) -> str:
        if f["_t"]:
            return f"{f['_t']}|{f['anio']}"
        return f"e:{f['_e']}|{f['anio']}" if f["_e"] else f"i:{f['item_id']}"

    claves = _clave_por_rango(filas, grupo, lambda i: (not filas[i]["_t"], i), clave)
    return _con_grupos(df, grupo, aristas).with_columns(clave=claves).drop("_t", "_grupo")
