"""
PANTALLA DE SEGUIMIENTO
=======================
El tablero del supervisor y del master.

Los cálculos NO se hacen aquí: los hace la base, en las funciones
seguimiento_*. Eso tiene dos ventajas: la app no descarga miles de filas, y
el RLS aplica solo, así que el supervisor ve los mismos indicadores pero
limitados a sus zonas.
"""
from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import streamlit as st

import config
import db

PERIODOS = {
    "Hoy": lambda: (date.today(), date.today()),
    "7 días": lambda: (date.today() - timedelta(days=6), date.today()),
    "Este mes": lambda: (date.today().replace(day=1), date.today()),
    "Mes pasado": lambda: _mes_pasado(),
}


def _mes_pasado():
    primero = date.today().replace(day=1)
    fin = primero - timedelta(days=1)
    return fin.replace(day=1), fin


def mostrar(usuario: dict):
    if usuario["rol"] not in ("supervisor", "master"):
        st.info("Esta pantalla es para supervisores y administradores.")
        return

    desde, hasta = _selector_periodo(usuario)

    resumen = db.seguimiento_resumen(desde, hasta)
    asesores = db.seguimiento_asesores(desde, hasta)
    zonas = db.seguimiento_zonas(desde, hasta)
    perdidas = db.seguimiento_perdidas(desde, hasta)
    ferreterias = db.seguimiento_ferreterias(desde, hasta)

    _pulso(resumen)
    _aperturas(desde, hasta)
    _tabla_asesores(asesores)

    col_zona, col_perdida = st.columns([1, 1.3])
    with col_zona:
        _tabla_zonas(zonas)
    with col_perdida:
        _tabla_perdidas(perdidas)

    _tabla_ferreterias(ferreterias)
    _exportar(desde, hasta, resumen, asesores, zonas, perdidas, ferreterias)


# ==================================================== selector de fechas ===
def _selector_periodo(usuario):
    col_titulo, col_rapido, col_fechas = st.columns([1.4, 1.6, 1.5],
                                                    vertical_alignment="bottom")

    with col_titulo:
        st.markdown("##### Seguimiento")
        zonas = [(z.get("m_zonas") or {}).get("nombre")
                 for z in (usuario.get("rel_usuarios_zonas") or [])]
        zonas = sorted(z for z in zonas if z)
        st.caption(", ".join(zonas) if zonas else "Todas las zonas")

    with col_rapido:
        atajo = st.segmented_control("Periodo", list(PERIODOS),
                                     default="Este mes",
                                     label_visibility="collapsed")

    if atajo:
        st.session_state.seguimiento_rango = PERIODOS[atajo]()

    rango_actual = st.session_state.get("seguimiento_rango") or PERIODOS["Este mes"]()

    with col_fechas:
        elegido = st.date_input("Rango", value=rango_actual,
                                format="DD/MM/YYYY", label_visibility="collapsed")

    # date_input devuelve una sola fecha mientras el usuario elige la segunda
    if isinstance(elegido, (list, tuple)) and len(elegido) == 2:
        st.session_state.seguimiento_rango = tuple(elegido)
        return elegido[0], elegido[1]

    return rango_actual[0], rango_actual[1]


# ============================================================ el pulso ===
def _pulso(r):
    if not r:
        st.info("No hay negociaciones en este periodo.")
        return

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Activas", r.get("activas", 0))
    c2.metric("Por cerrar", r.get("por_cerrar", 0))
    c3.metric("Ganadas", r.get("ganadas", 0))
    c4.metric("Perdidas", r.get("perdidas", 0))
    c5.metric("Conversión", f"{r.get('conversion_pct') or 0}%",
              help=f"{r.get('ganadas', 0)} de {r.get('cerradas', 0)} cerradas. "
                   "Las activas no cuentan porque todavía no se deciden.")
    c6.metric("Facturación", f"S/ {float(r.get('facturacion') or 0):,.0f}",
              help=f"{r.get('ventas', 0)} ventas registradas · "
                   f"{config.soles(r.get('facturacion'))}")

    por_validar = r.get("ventas_por_validar") or 0
    if por_validar:
        st.caption(f":orange[{por_validar} venta(s) esperando validación.] "
                   "Ya cuentan como ganadas, pero conviene confirmarlas.")


# ========================================================== evolutivo ===
def _aperturas(desde, hasta):
    filas = db.seguimiento_aperturas(desde, hasta)
    if not filas:
        return

    with st.container(border=True):
        total = sum(f["negociaciones"] for f in filas)
        promedio = round(total / len(filas), 1) if filas else 0
        st.markdown(f"**Apertura de negociaciones** · {total} en el periodo, "
                    f"promedio {promedio} por día")

        # El eje va como texto dd/mm: con fechas, Streamlit las rotula en
        # inglés y no hay forma de cambiarlo desde el gráfico.
        tabla = pd.DataFrame(filas)
        tabla["dia"] = pd.to_datetime(tabla["dia"]).dt.strftime("%d/%m")
        st.bar_chart(tabla.set_index("dia")["negociaciones"], height=200)


# =========================================================== por asesor ===
def _tabla_asesores(filas):
    with st.container(border=True):
        st.markdown("**Por asesor**")
        if not filas:
            st.caption("Sin datos en el periodo.")
            return

        tabla = pd.DataFrame([{
            "Asesor": f["asesor"],
            "Negociaciones": f["negociaciones"],
            "Cotizaciones": f["cotizaciones"],
            "Ventas": f["ventas"],
            "Facturación": float(f["facturacion"] or 0),
            "Conversión %": float(f["conversion_pct"] or 0),
            "Cotiz. por negoc.": float(f["cotiz_por_negociacion"] or 0),
        } for f in filas])

        st.dataframe(
            tabla, hide_index=True, width="stretch",
            column_config={
                "Facturación": st.column_config.NumberColumn(format="S/ %.2f"),
                "Conversión %": st.column_config.ProgressColumn(
                    format="%.1f%%", min_value=0, max_value=100),
                "Cotiz. por negoc.": st.column_config.NumberColumn(
                    format="%.1f",
                    help="Recotizar mucho y cerrar poco señala un problema de "
                         "precio o de calificación del cliente."),
            },
        )


# ============================================================= por zona ===
def _tabla_zonas(filas):
    with st.container(border=True):
        st.markdown("**Por zona**")
        if not filas:
            st.caption("Sin datos en el periodo.")
            return

        st.dataframe(pd.DataFrame([{
            "Zona": f["zona"],
            "Negociaciones": f["negociaciones"],
            "Ventas": f["ventas"],
            "Facturación": float(f["facturacion"] or 0),
            "Conversión %": float(f["conversion_pct"] or 0),
        } for f in filas]), hide_index=True, width="stretch",
            column_config={
                "Facturación": st.column_config.NumberColumn(format="S/ %.2f"),
                "Conversión %": st.column_config.NumberColumn(format="%.1f%%"),
            })


# ======================================================== por qué pierden ===
def _tabla_perdidas(filas):
    with st.container(border=True):
        st.markdown("**Por qué se pierden**")
        if not filas:
            st.caption("Ninguna negociación perdida en el periodo.")
            return

        st.dataframe(pd.DataFrame([{
            "Motivo": f["motivo"] + (" (automático)" if f["automatico"] else ""),
            "Casos": f["casos"],
            "Monto": float(f["monto"] or 0),
        } for f in filas]), hide_index=True, width="stretch",
            column_config={"Monto": st.column_config.NumberColumn(format="S/ %.2f")})

        st.caption("El monto sale de la última cotización de cada negociación.")


# ========================================================== ferreterías ===
def _tabla_ferreterias(filas):
    with st.container(border=True):
        st.markdown("**Ferreterías**")
        if not filas:
            st.caption("Sin cotizaciones en el periodo.")
            return

        tabla = pd.DataFrame([{
            "Ferretería": f["ferreteria"],
            "Compitió": f["compitio"],
            "Elegida": f["elegida"],
            "Vendida": f["vendida"],
            "% elegida": float(f["tasa_elegida_pct"] or 0),
            "% cierre": float(f["conversion_pct"] or 0),
        } for f in filas])

        st.dataframe(tabla, hide_index=True, width="stretch",
                     column_config={
                         "% elegida": st.column_config.ProgressColumn(
                             format="%.1f%%", min_value=0, max_value=100,
                             help="De las veces que compitió, cuántas la eligió el asesor."),
                         "% cierre": st.column_config.NumberColumn(format="%.1f%%"),
                     })

        # La señal más accionable del tablero
        flojas = [f for f in filas
                  if f["compitio"] >= 10 and (f["tasa_elegida_pct"] or 0) < 15]
        if flojas:
            nombres = ", ".join(f["ferreteria"] for f in flojas[:3])
            st.caption(f":orange[{nombres} compite seguido y casi nunca es "
                       "elegida: sus precios no son competitivos.]")


# ============================================================== exportar ===
def _exportar(desde, hasta, resumen, asesores, zonas, perdidas, ferreterias):
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([resumen]).to_excel(writer, sheet_name="Resumen", index=False)
        for nombre, filas in [("Asesores", asesores), ("Zonas", zonas),
                              ("Perdidas", perdidas), ("Ferreterias", ferreterias)]:
            pd.DataFrame(filas).to_excel(writer, sheet_name=nombre, index=False)

    st.download_button(
        "⬇ Exportar a Excel",
        data=buffer.getvalue(),
        file_name=f"seguimiento_{desde}_{hasta}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
    )
