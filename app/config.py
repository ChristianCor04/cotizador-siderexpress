"""
CONFIGURACIÓN Y CONEXIÓN
========================
Este archivo hace dos cosas:
  1. Guarda los valores que puedes querer cambiar sin tocar el resto del código.
  2. Abre la conexión con Supabase.

Si quieres cambiar cómo se comporta la app, empieza mirando aquí.
"""
from pathlib import Path

import streamlit as st
from supabase import create_client

# Logo de la marca. Para cambiarlo, reemplaza el archivo manteniendo el nombre.
LOGO = str(Path(__file__).parent / "assets" / "logo.png")


# ---------------------------------------------------------------------------
# VALORES QUE PUEDES CAMBIAR
# ---------------------------------------------------------------------------

# Tope de sedes que se cotizan, de la más cercana a la más lejana.
# No limita cuántas ferreterías se muestran: es solo un freno de rendimiento
# para no consultar precios de cientos de sedes.
#
# Ojo: los montos y radios de las reglas NO están aquí. Viven en la tabla
# m_reglas_cotizacion de Supabase, y ahora pueden variar por zona.
TOP_N_SEDES = 60

# Hasta cuántos productos faltantes se muestran por defecto en el panel
# de ferreterías. 0 = solo las que tienen la canasta completa.
FALTANTES_POR_DEFECTO = 0

# Formato de los códigos que ve el asesor. El número real es el id.
FORMATO_NEGOCIACION = "NEG-{:05d}"
FORMATO_COTIZACION = "COT-{:06d}"


def codigo_negociacion(id_negociacion: int) -> str:
    return FORMATO_NEGOCIACION.format(id_negociacion)


def codigo_cotizacion(id_cotizacion: int) -> str:
    return FORMATO_COTIZACION.format(id_cotizacion)


def soles(monto) -> str:
    """Formatea un número como S/ 1,234.56"""
    if monto is None:
        return "—"
    return f"S/ {float(monto):,.2f}"


# ---------------------------------------------------------------------------
# CONEXIÓN CON SUPABASE
# ---------------------------------------------------------------------------

def conectar():
    """Devuelve el cliente de Supabase de ESTE usuario.

    Importante: se guarda en session_state y NO en una caché de Streamlit.
    Las cachés se comparten entre todos los usuarios de la app, así que si
    guardáramos aquí la sesión de un asesor, otro podría terminar viendo
    sus datos.
    """
    if "supabase" not in st.session_state:
        try:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_KEY"]
        except (KeyError, FileNotFoundError):
            st.error(
                "Faltan las credenciales. Copia `.streamlit/secrets.toml.ejemplo` "
                "como `.streamlit/secrets.toml` y pon la URL y la llave de tu proyecto."
            )
            st.stop()
        st.session_state.supabase = create_client(url, key)
    return st.session_state.supabase


# ---------------------------------------------------------------------------
# FECHAS EN HORA DE PERÚ
# El servidor trabaja en UTC. Sin esto, las fechas saldrían 5 horas adelante.
# ---------------------------------------------------------------------------
from datetime import datetime          # noqa: E402
from zoneinfo import ZoneInfo          # noqa: E402

LIMA = ZoneInfo("America/Lima")


def ahora_lima() -> datetime:
    return datetime.now(LIMA)


def a_lima(valor) -> datetime | None:
    """Convierte a hora de Lima una fecha que viene de la base (en UTC)."""
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    return valor.astimezone(LIMA)


def fecha_hora(valor) -> str:
    fecha = a_lima(valor)
    return fecha.strftime("%d/%m/%Y %H:%M") if fecha else "—"


def vence_texto(valor) -> str:
    """La cotización vence a la medianoche: se muestra como 23:59 del día anterior."""
    fecha = a_lima(valor)
    if fecha is None:
        return "—"
    from datetime import timedelta
    return (fecha - timedelta(minutes=1)).strftime("%d/%m/%Y 23:59")
