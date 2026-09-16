"""
CONFIGURACIÓN Y CONEXIÓN
========================
Este archivo hace dos cosas:
  1. Guarda los valores que puedes querer cambiar sin tocar el resto del código.
  2. Abre la conexión con Supabase.

Si quieres cambiar cómo se comporta la app, empieza mirando aquí.
"""
import streamlit as st
from supabase import create_client


# ---------------------------------------------------------------------------
# VALORES QUE PUEDES CAMBIAR
# ---------------------------------------------------------------------------

# Cuántas sedes cercanas se evalúan al cotizar.
# Ojo: los montos y radios de las reglas 1.1, 1.2 y 1.3 NO están aquí.
# Viven en la tabla m_reglas_cotizacion de Supabase, para poder cambiarlos
# sin tocar código.
TOP_N_SEDES = 5

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
