"""
COTIZADOR SIDEREXPRESS
======================
Este es el archivo que se ejecuta. Solo hace dos cosas:
  1. Si nadie inició sesión, muestra el login.
  2. Si ya hay sesión, muestra el menú y la pantalla elegida.

Para ejecutar:  streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="Cotizador SIDEREXPRESS", page_icon="🧱", layout="wide")

import db                                    # noqa: E402
import sesion                                # noqa: E402
from paginas import login, negociaciones, precios  # noqa: E402


# Qué pantallas ve cada rol.
# Para agregar una pantalla nueva: créala en paginas/ y agrégala aquí.
MENU = {
    "asesor":     ["Negociaciones", "Precios", "Ferreterías", "Clientes"],
    "supervisor": ["Negociaciones", "Precios", "Ferreterías", "Clientes"],
    "master":     ["Negociaciones", "Precios", "Ferreterías", "Clientes", "Promociones"],
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
    with st.sidebar:
        st.markdown("### SIDER:red[EXPRESS]")
        st.caption(f"{usuario['nombre']} · {usuario['rol']}")
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
    else:
        st.info(f"La pantalla «{pantalla}» todavía no está construida.")


main()
