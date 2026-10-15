"""
COTIZADOR SIDEREXPRESS
======================
Este es el archivo que se ejecuta. Solo hace dos cosas:
  1. Si nadie inició sesión, muestra el login.
  2. Si ya hay sesión, muestra el menú y la pantalla elegida.

Para ejecutar:  streamlit run app.py
"""
import time

import streamlit as st

from pathlib import Path                    # noqa: E402

# Ícono de la pestaña del navegador. Se usa assets/icono.png si existe; si no,
# el logo. Conviene un ícono cuadrado: el logo, que es ancho, se ve aplastado.
_ASSETS = Path(__file__).parent / "assets"
_ICONO = _ASSETS / "icono.png" if (_ASSETS / "icono.png").exists() else _ASSETS / "logo.png"

st.set_page_config(page_title="SIDER EXPRESS", page_icon=str(_ICONO), layout="wide")

import config                                # noqa: E402
import db                                    # noqa: E402
import sesion                                # noqa: E402
from paginas import (ferreterias, login, negociaciones,  # noqa: E402
                     precios, productos, promociones, seguimiento)


# Qué pantallas ve cada rol.
# Para agregar una pantalla nueva: créala en paginas/ y agrégala aquí.
MENU = {
    "asesor":     ["Negociaciones", "Precios"],
    "supervisor": ["Negociaciones", "Seguimiento", "Precios",
                   "Ferreterías", "Clientes"],
    "master":     ["Negociaciones", "Seguimiento", "Precios", "Productos",
                   "Ferreterías", "Clientes", "Promociones"],
}


def main():
    # --- Al recargar la página (F5) Streamlit olvida todo.
    # Si hay una cookie guardada, se reanuda la sesión sin pedir la clave.
    if "usuario" not in st.session_state:
        token = sesion.leer_token()
        if token:
            perfil = db.reanudar_sesion(token)
            if perfil:
                st.session_state.usuario = perfil

    # --- Sin sesión: solo el login
    if "usuario" not in st.session_state:
        login.mostrar()
        return

    usuario = st.session_state.usuario

    # --- Menú lateral
    # st.logo lo muestra arriba de la barra lateral y también cuando está
    # colapsada, así que no hace falta repetirlo con st.image.
    st.logo(config.LOGO, size="large")

    with st.sidebar:
        st.caption(f"{usuario['nombre']} · {usuario['rol']}")

        # Un usuario puede cubrir varias zonas: conviene que vea cuáles
        zonas = [(z.get("m_zonas") or {}).get("nombre")
                 for z in (usuario.get("rel_usuarios_zonas") or [])]
        zonas = sorted(z for z in zonas if z)
        if zonas:
            st.caption("Zonas: " + ", ".join(zonas))
        st.divider()

        opciones = MENU.get(usuario["rol"], ["Negociaciones"])
        pantalla = st.radio("Menú", opciones, label_visibility="collapsed")

        st.divider()
        if st.button("Cerrar sesión", width="stretch"):
            db.cerrar_sesion()
            sesion.borrar_token()
            st.session_state.clear()
            st.rerun()

    # --- Pantalla elegida
    pantallas = {
        "Negociaciones": negociaciones.mostrar,
        "Precios": precios.mostrar,
        "Promociones": promociones.mostrar,
        "Seguimiento": seguimiento.mostrar,
        "Productos": productos.mostrar,
        "Ferreterías": ferreterias.mostrar,
    }
    if pantalla in pantallas:
        _mostrar_con_sesion_valida(pantallas[pantalla], usuario)
    else:
        st.info(f"La pantalla «{pantalla}» todavía no está construida.")


# ---------------------------------------------------------------------------
# ERRORES DE SESIÓN
# Supabase puede rechazar el permiso de acceso (el token) por dos motivos que
# no son errores de la app:
#   PGRST303 «JWT issued at future»: el token recién emitido llega unos
#            segundos antes de lo que marca el reloj del servidor que responde.
#            Se resuelve esperando un momento.
#   PGRST301 «JWT expired»: el token venció. Se renueva la sesión.
# En ambos casos se reintenta la pantalla sola, hasta dos veces. Si sigue
# fallando, se pide volver a ingresar en vez de mostrar el error técnico.
# ---------------------------------------------------------------------------
ERRORES_DE_SESION = {"PGRST303", "PGRST301"}
REINTENTOS = 2


def _mostrar_con_sesion_valida(mostrar, usuario):
    from postgrest.exceptions import APIError

    try:
        mostrar(usuario)
        st.session_state.pop("reintentos_sesion", None)
    except APIError as e:
        codigo = getattr(e, "code", None)
        if codigo not in ERRORES_DE_SESION:
            raise

        intento = st.session_state.get("reintentos_sesion", 0) + 1
        if intento <= REINTENTOS:
            st.session_state.reintentos_sesion = intento
            if codigo == "PGRST301":
                db.renovar_sesion()
            time.sleep(intento)          # 1 segundo, luego 2
            st.rerun()

        st.session_state.pop("reintentos_sesion", None)
        st.warning("Tu sesión necesita renovarse. Vuelve a ingresar, por favor.")
        if st.button("Ingresar de nuevo", type="primary"):
            db.cerrar_sesion()
            sesion.borrar_token()
            st.session_state.clear()
            st.rerun()


main()
