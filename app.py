"""
COTIZADOR SIDEREXPRESS
======================
Este es el archivo que se ejecuta. Solo hace dos cosas:
  1. Si nadie inició sesión, muestra el login.
  2. Si ya hay sesión, muestra el menú y la pantalla elegida.

Para ejecutar:  streamlit run app.py
"""
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
    "asesor":     ["Negociaciones", "Precios","seguimiento"],
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
    if pantalla == "Negociaciones":
        negociaciones.mostrar(usuario)
    elif pantalla == "Precios":
        precios.mostrar(usuario)
    elif pantalla == "Promociones":
        promociones.mostrar(usuario)
    elif pantalla == "Seguimiento":
        seguimiento.mostrar(usuario)
    elif pantalla == "Productos":
        productos.mostrar(usuario)
    elif pantalla == "Ferreterías":
        ferreterias.mostrar(usuario)
    else:
        st.info(f"La pantalla «{pantalla}» todavía no está construida.")


main()
