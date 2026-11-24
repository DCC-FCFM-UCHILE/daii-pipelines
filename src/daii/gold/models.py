"""Modelo relacional gold (SQLModel/SQLite). Implementa docs/modelo_datos.md, con dos simplificaciones:

- Solo los académicos son filas propias (`Academico`). Coautores y estudiantes quedan como texto
  (`Publicacion.autores`, `Tesis.estudiante`) hasta que haga falta identificarlos.
- Las organizaciones de las afiliaciones quedan como texto (`Afiliacion.organizacion`). Falta normalizarlas
  a una tabla `Organizacion` con ROR.

Entidades compartidas (publicación, proyecto, tesis, curso, producto) tienen clave estable (DOI, código o hash)
y una tabla puente hacia `Academico`. Así se arma la red de colaboración.
"""

from sqlmodel import Field, SQLModel


class Academico(SQLModel, table=True):
    id: str = Field(primary_key=True)  # slug de config/academicos.yaml
    nombre: str
    unidad: str | None = Field(default=None, index=True)  # unidad principal (config)
    cargo: str | None = None
    orcid: str | None = None
    email: str | None = None
    foto_url: str | None = None
    bio: str | None = None


class PerfilExterno(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    plataforma: str
    url: str | None = None
    identificador: str | None = None
    fuente: str


class Afiliacion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    organizacion: str
    rol: str | None = None
    desde: str | None = None
    hasta: str | None = None
    url_organizacion: str | None = None
    fuente: str


class Formacion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    nivel: str  # doctorado|magister|titulo_profesional|licenciatura|postdoctorado|otro
    grado: str
    institucion: str | None = None
    anio: int | None = None
    titulo_tesis: str | None = None
    fuente: str


class Area(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    nombre: str
    fuente: str


class Publicacion(SQLModel, table=True):
    id: str = Field(primary_key=True)  # DOI o "t:<título normalizado>"
    titulo: str
    anio: int | None = Field(default=None, index=True)
    tipo: str = Field(index=True)  # revista|conferencia|capitulo|libro|preprint|tesis|otro
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    estado: str | None = None
    citas: int | None = None
    indexada_wos: bool = False
    indexada_scopus: bool = False
    autores: str | None = None  # JSON list, en orden


class PublicacionAcademico(SQLModel, table=True):
    publicacion_id: str = Field(foreign_key='publicacion.id', primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', primary_key=True)
    fuentes: str  # JSON list de spiders que la reportan
    confianza: float  # 0.5 si solo la reporta OpenAlex (posible homónimo)


class Proyecto(SQLModel, table=True):
    id: str = Field(primary_key=True)  # código o hash del título
    titulo: str
    codigo: str | None = None
    instrumento: str = Field(index=True)  # fondecyt|fondef|milenio|basal|anillo|corfo|anid_otro|otro
    fuente_texto: str | None = None
    anio_inicio: int | None = None
    anio_fin: int | None = None
    monto: str | None = None


class ParticipacionProyecto(SQLModel, table=True):
    proyecto_id: str = Field(foreign_key='proyecto.id', primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', primary_key=True)
    rol: str | None = None
    fuentes: str


class Tesis(SQLModel, table=True):
    id: str = Field(primary_key=True)
    titulo: str | None = None  # varias fuentes listan estudiantes sin título
    anio: int | None = None
    nivel: str | None = None
    estudiante: str | None = None
    programa: str | None = None
    estado: str | None = None
    url: str | None = None


class DireccionTesis(SQLModel, table=True):
    tesis_id: str = Field(foreign_key='tesis.id', primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', primary_key=True)
    rol: str  # guia|coguia|comision|otro
    fuentes: str


class Curso(SQLModel, table=True):
    id: str = Field(primary_key=True)  # código o hash del nombre
    codigo: str | None = None
    nombre: str


class Dictacion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    curso_id: str = Field(foreign_key='curso.id', index=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    anio: int | None = None
    semestre: str | None = None
    rol: str | None = None
    institucion: str | None = None
    fuente: str


class Actividad(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    tipo: str = Field(index=True)
    titulo: str
    descripcion: str | None = None
    evento: str | None = None
    fecha: str | None = None
    rol: str | None = None
    url: str | None = None
    fuente: str


class Producto(SQLModel, table=True):
    id: str = Field(primary_key=True)
    nombre: str
    tipo: str
    descripcion: str | None = None
    url: str | None = None


class ProductoAcademico(SQLModel, table=True):
    producto_id: str = Field(foreign_key='producto.id', primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', primary_key=True)
    rol: str | None = None


class Distincion(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    nombre: str
    otorgante: str | None = None
    anio: int | None = None
    fuente: str


class Metrica(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    plataforma: str
    nombre: str
    valor: float
    anio: int | None = None


class LinkDescubierto(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    url_origen: str
    url_destino: str = Field(index=True)
    texto: str | None = None
    seguido: bool
    fuente: str


class PaginaRelacionada(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    academico_id: str = Field(foreign_key='academico.id', index=True)
    url: str
    titulo: str | None = None
    texto: str | None = None


class ScrapeRun(SQLModel, table=True):
    """Estado de cada spider (último run evaluado): base de la vista de salud de las fuentes."""

    spider: str = Field(primary_key=True)
    ultimo_run: str
    estado: str
    problemas: str  # JSON
    conteos: str  # JSON
    run_en_uso: str | None = None  # run que alimenta silver (último bueno)


class DataRelease(SQLModel, table=True):
    """Versión publicada (una fila): enlaza la SQLite con su manifiesto en data/versions/<build_id>/."""

    build_id: str = Field(primary_key=True)
    published_at: str
