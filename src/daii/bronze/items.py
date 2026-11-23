"""Contrato de los ítems bronze: cada spider emite dicts que validan contra uno de estos modelos.

Bronze guarda los valores *como aparecen* en la fuente (texto), con mínima limpieza (strip).
La normalización (fechas, DOIs, deduplicación, mapeo a catálogos) ocurre en silver.
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# Vocabulario cerrado: el texto original de la fuente va en `descripcion` o `rol`.
TipoActividad = Literal[
    "charla",  # charla invitada, seminario, talk
    "keynote",
    "tutorial",
    "editorial",  # editor/a, comité editorial, guest editor
    "comite_programa",  # PC/SPC de conferencias
    "comite",  # otros comités (asesores, técnicos, sociedades)
    "organizacion_evento",  # chair, organización de eventos o escuelas
    "revisor",
    "divulgacion",  # outreach, ciencia para público general
    "prensa",  # medios, noticias sobre la persona
    "noticia",  # noticias del propio sitio (nuevo cargo, proyecto, visita...)
    "asesoria",  # consultoría, asesoría a empresas o Estado
    "transferencia",  # transferencia tecnológica
    "politica_publica",
    "consejo_directivo",
    "gestion",  # cargos de gestión universitaria
    "servicio",  # servicio académico no clasificado arriba
    "visita",  # estadías y visitas académicas
    "vinculacion",  # vinculación con comunidades
    "extension",  # extensión universitaria (cursos, prestaciones)
    "otro",
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    persona: str  # slug de config/academicos.yaml
    url: str  # página de donde se extrajo
    spider: str
    run_id: str
    scraped_at: str


class Persona(_Base):
    tipo: Literal["persona"] = "persona"
    nombre: str
    cargo: str | None = None
    email: str | None = None
    telefono: str | None = None
    oficina: str | None = None
    foto_url: str | None = None
    bio: str | None = None


class Perfil(_Base):
    tipo: Literal["perfil"] = "perfil"
    plataforma: str  # orcid|scholar|dblp|github|linkedin|...
    url_destino: str
    identificador: str | None = None


class Afiliacion(_Base):
    tipo: Literal["afiliacion"] = "afiliacion"
    organizacion: str
    rol: str | None = None  # texto del cargo tal como aparece
    desde: str | None = None
    hasta: str | None = None
    url_organizacion: str | None = None


class Area(_Base):
    tipo: Literal["area"] = "area"
    nombre: str


class Formacion(_Base):
    tipo: Literal["formacion"] = "formacion"
    grado: str  # texto tal cual: "Doctor", "PhD in EE", ...
    institucion: str | None = None
    anio: int | None = None
    titulo_tesis: str | None = None


class Publicacion(_Base):
    tipo: Literal["publicacion"] = "publicacion"
    titulo: str
    anio: int | None = None
    tipo_publicacion: str | None = None  # journal|conference|book|chapter|preprint|... (texto de la fuente)
    venue: str | None = None
    autores: list[str] = Field(default_factory=list)
    doi: str | None = None
    url_destino: str | None = None  # link al paper/PDF
    estado: str | None = None  # "to appear", "under review"...
    citas: int | None = None
    ids: dict[str, str] = Field(default_factory=dict)  # openalex, dblp, arxiv...


class Tesis(_Base):
    tipo: Literal["tesis"] = "tesis"
    titulo: str | None = None  # muchas fuentes listan estudiantes sin título: no se inventa
    anio: int | None = None
    nivel: str | None = None  # memoria|magister|doctorado|postdoc (texto)
    estudiante: str | None = None
    rol: str | None = None  # guia|coguia|comision
    programa: str | None = None
    estado: str | None = None  # "en desarrollo", "aprobada"... (texto)
    url_destino: str | None = None


class Proyecto(_Base):
    tipo: Literal["proyecto"] = "proyecto"
    titulo: str
    codigo: str | None = None
    fuente: str | None = None  # instrumento/agencia tal como aparece: "Fondecyt_Anid", "CORFO"...
    rol: str | None = None
    anio_inicio: int | None = None
    anio_fin: int | None = None
    monto: str | None = None
    investigador_responsable: str | None = None


class Dictacion(_Base):
    tipo: Literal["dictacion"] = "dictacion"
    nombre_curso: str
    codigo_curso: str | None = None
    anio: int | None = None
    semestre: str | None = None  # Otoño|Primavera|Verano (texto)
    rol: str | None = None
    institucion: str | None = None  # si el curso se dictó fuera de la U. de Chile
    url_curso: str | None = None


class Actividad(_Base):
    tipo: Literal["actividad"] = "actividad"
    tipo_actividad: TipoActividad
    titulo: str
    descripcion: str | None = None
    evento: str | None = None
    fecha: str | None = None
    rol: str | None = None
    url_destino: str | None = None


class Producto(_Base):
    tipo: Literal["producto"] = "producto"
    tipo_producto: str  # software|dataset|patente|plataforma|...
    nombre: str
    descripcion: str | None = None
    url_destino: str | None = None
    rol: str | None = None


class Distincion(_Base):
    tipo: Literal["distincion"] = "distincion"
    nombre: str
    otorgante: str | None = None
    anio: int | None = None


class Metrica(_Base):
    """Indicador bibliométrico de la persona en una plataforma (h_index, citas, n° de obras...)."""

    tipo: Literal["metrica"] = "metrica"
    plataforma: str
    nombre: str
    valor: float
    anio: int | None = None  # None = acumulado a la fecha del scrapeo


class Link(_Base):
    """Link saliente descubierto en una página de la persona (para decidir futuros spiders)."""

    tipo: Literal["link"] = "link"
    url_destino: str
    texto: str | None = None
    seguido: bool = False


class Pagina(_Base):
    """Página relacionada (profundidad 1, lista blanca) sin parser propio: se guarda título y texto."""

    tipo: Literal["pagina"] = "pagina"
    titulo: str | None = None
    texto: str | None = None


RawItem = Annotated[
    Persona
    | Perfil
    | Afiliacion
    | Area
    | Formacion
    | Publicacion
    | Tesis
    | Proyecto
    | Dictacion
    | Actividad
    | Producto
    | Distincion
    | Metrica
    | Link
    | Pagina,
    Field(discriminator="tipo"),
]
bronze_item = TypeAdapter(RawItem)
TIPOS: list[str] = [m.model_fields["tipo"].default for m in get_args(get_args(RawItem)[0])]
