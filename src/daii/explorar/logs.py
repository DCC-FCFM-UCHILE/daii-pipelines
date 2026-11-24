"""Logs estructurados (data/logs.sqlite) con filtros por nivel, spider, run, persona y evento."""

import json

import polars as pl
import streamlit as st

from daii.explorar import datos, ui
from daii.log import NIVELES

NIVEL_BADGE = {
    'WARNING': ('orange', ':material/warning:'),
    'ERROR': ('red', ':material/error:'),
    'CRITICAL': ('red', ':material/error:'),
}


def pagina() -> None:
    st.title('Logs')
    if not datos.logs_db().exists():
        st.info('Todavía no hay logs: `data/logs.sqlite` se crea al correr `make run`.', icon=':material/receipt_long:')
        return
    nombres = datos.nombres()
    fila1 = st.columns(3)
    nivel = fila1[0].selectbox('Nivel mínimo', NIVELES, index=NIVELES.index('INFO'), key='log_nivel')
    spider = fila1[1].selectbox(
        'Spider', datos.valores_log('spider'), index=None, placeholder='Todos', key='log_spider'
    )
    persona = fila1[2].selectbox(
        'Académico/a',
        datos.valores_log('persona'),
        index=None,
        format_func=lambda s: nombres.get(s, s),
        placeholder='Todos',
        key='log_persona',
    )
    fila2 = st.columns(3)
    evento = fila2[0].selectbox(
        'Evento', datos.valores_log('evento'), index=None, placeholder='Todos', key='log_evento'
    )
    run_id = fila2[1].selectbox(
        'Run', datos.valores_log('run_id')[::-1], index=None, placeholder='Todos', key='log_run'
    )
    desde = fila2[2].date_input('Desde', value=None, key='log_desde', format='YYYY-MM-DD')
    df = datos.logs(
        nivel=nivel,
        spider=spider,
        run_id=run_id,
        persona=persona,
        evento=evento,
        desde=desde.isoformat() if desde else None,
    )
    if df.is_empty():
        st.caption('Ningún registro con esos filtros.')
        return
    with st.container(horizontal=True):
        for n, cantidad in (
            df.group_by('nivel')
            .len()
            .sort(pl.col('nivel').replace_strict(NIVELES, list(range(len(NIVELES)))))
            .iter_rows()
        ):
            color, icono = NIVEL_BADGE.get(n, ('gray', ':material/info:'))
            st.badge(f'{cantidad} {n}', icon=icono, color=color)  # ty: ignore[invalid-argument-type]
    st.caption(f'{df.height} registros, del más reciente al más antiguo (máximo 2.000). Elige uno para ver su detalle.')
    vista = df.with_row_index('n').select(
        'n',
        pl.col('ts').str.slice(0, 19).str.replace('T', ' ').alias('hora (UTC)'),
        'nivel',
        'componente',
        'spider',
        'persona',
        'evento',
        'mensaje',
    )
    # la clave cambia con filtros o registros nuevos: una selección vieja no apunta a otra fila
    fila = ui.tabla(
        vista,
        key=f'logs_{hash((nivel, spider, run_id, persona, evento, desde, df["ts"][0]))}',
        seleccion=True,
        altura='content' if vista.height <= 15 else 560,
        ocultas=('n',),
    )
    if fila:
        registro = df.row(fila['n'], named=True)
        st.subheader(registro['evento'] or 'log')
        st.write(registro['mensaje'])
        contexto = {k: registro[k] for k in ('run_id', 'build_id', 'flow_run_id', 'url') if registro.get(k)}
        if registro.get('extra'):
            contexto |= json.loads(registro['extra'])
        if contexto:
            st.json(contexto)
        if registro.get('excepcion'):
            st.code(registro['excepcion'], language='python')
