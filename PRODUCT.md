# Producto: Explorador DAII

App local (Streamlit) para explorar los datos del pipeline DAII (FCFM, U. de Chile) en sus tres capas:
bronze (lo que dijo cada fuente), silver (normalizado) y gold (la SQLite publicada).

## Audiencias y modos

| Modo | Quién | Qué necesita | Ve |
|---|---|---|---|
| **DAII** | Personal de la Dirección Académica, de Investigación e Innovación; no técnico | Consultar a un/a académico/a y la producción de la facultad, con confianza en el dato | Solo gold, contacto visible |
| **Pipeline** | Equipo de datos que mantiene los scrapers | Ver si una fuente se rompió, de dónde viene un dato, qué cambió entre versiones | Las tres capas, salud de runs, versiones/diff, logs |

## Tareas principales

1. Encontrar a un académico y ver todo lo que sabemos de él/ella, por tipo de dato.
2. (Pipeline) Rastrear una fila hasta su origen: gold → silver → ítem bronze (spider, run, URL).
3. Ver agregados por tipo y capa: cobertura por fuente, producción en el tiempo, calidad de campos, embudo de capas.
4. (Pipeline) Saber qué spider falló, desde cuándo, y qué run alimenta lo publicado.
5. (Pipeline) Comparar dos versiones publicadas y leer los logs de un run.

## Tono y principios

- Español, vocabulario del modelo de datos (`docs/modelo_datos.md`): académico, publicación, tesis, dictación, run.
- Herramienta institucional sobria: la identidad FCFM se nota en detalles precisos, no en decoración.
- Honesta con el dato: mostrar de qué fuente y versión viene cada cifra; los vacíos se ven, no se esconden.
- Solo lectura: la app nunca modifica `data/`.

## Restricciones

- Local, sin autenticación. Python 3.14, Streamlit, Polars, Altair (incluido en Streamlit).
- Datos chicos (decenas de académicos, miles de filas): sin paginación de servidor.
