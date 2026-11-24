# Diseño: Explorador DAII

Modo impeccable: **Operate**. La identidad es la institucional de la FCFM, aplicada con contención.

## Fuente de la identidad

Colores y tipografías extraídos de la hoja de estilos oficial de ingenieria.uchile.cl
(`/.resources/portal-ingenieria/styles/main106.css`, noviembre 2026):

| Token | Hex | Uso en el sitio FCFM | Uso aquí |
|---|---|---|---|
| `rojo-fcfm` | `#da291c` | Color de marca (174 usos) | Solo marca: nombre de la app en la barra lateral. **No** en controles: se confundiría con `fail` |
| `azul-fcfm` | `#324366` | Azul institucional | `primaryColor`: selección, botones, foco, serie única de gráficos |
| `azul-noche` | `#17203e` | Fondos oscuros | Extremo oscuro de la rampa secuencial |
| `tinta` | `#2d2d2d` | Texto | `textColor` |
| `gris` | `#5b5858` | Texto secundario | Captions |
| `gris-claro` | `#e6e6e6` | Bordes y fondos | `borderColor` |

Tipografía: **Lato** (cuerpo, como el sitio FCFM) y **Barlow** (títulos). Ambas de Google Fonts, cargadas por el tema
de Streamlit (`.streamlit/config.toml`), sin CSS propio.

## Reglas

- **Tema solo por `config.toml`.** Nada de `unsafe_allow_html` ni CSS inyectado: Streamlit cambia su DOM entre
  versiones y el CSS a mano se rompe en silencio.
- **Íconos:** Material Symbols de Streamlit (`:material/...:`). Nunca emoji ni glifos Unicode como íconos.
- **Estados de calidad** (siempre ícono + texto, nunca solo color), con `st.badge`:
  `ok` verde `:material/check_circle:` · `warn` naranja `:material/warning:` · `fail` rojo `:material/error:` ·
  `sin evaluar` gris `:material/help:`.
- **Jerarquía:** un `st.title` por página; secciones con `st.subheader`; sin kickers ni etiquetas sobre títulos;
  sin tarjetas de métricas como estructura de página (las métricas solo donde la cifra es la respuesta).
- **Densidad:** tablas `st.dataframe` a todo el ancho, `hide_index=True`, columnas con `column_config`
  (links como `LinkColumn`, años sin separador de miles).
- **Vacíos:** cada estado vacío dice qué falta y qué comando lo arregla (`make run`, `make gold`).

## Gráficos (skill dataviz)

- Serie única (producción por año, embudo por capa): `azul-fcfm`.
- Secuencial (heatmaps de cobertura y % de nulos): rampa de un solo tono `#eef0f5` → `#17203e`.
- Categórico (varias series, p. ej. conteos por tipo en el historial de runs): paleta de referencia validada
  `#2a78d6 #eb6834 #1baf7a #eda100 #e87ba4 #008300 #6250d6`, en ese orden, sin el rojo (reservado a `fail`).
  Máximo 7 series; el resto se agrupa en "otros". Hay contraste bajo en aqua/amarillo/magenta: siempre con
  leyenda y tabla al lado.
- Un solo eje Y, tooltips en cada marca, grilla recesiva.
