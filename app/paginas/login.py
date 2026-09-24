"""
PANTALLA DE LOGIN
=================
"""
import streamlit as st

import config
import db
import sesion


def mostrar():
    st.markdown("<div style='height:60px'></div>", unsafe_allow_html=True)
    izq, centro, der = st.columns([1, 1.2, 1])

    with centro:
        with st.container(border=True):
            izq_logo, centro_logo, der_logo = st.columns([1, 3, 1])
            centro_logo.image(config.LOGO, width="stretch")
            st.markdown(
                "<p style='text-align:center;margin-top:-6px'>Cotizador comercial</p>",
                unsafe_allow_html=True,
            )

            with st.form("login"):
                email = st.text_input("Correo", placeholder="ana.ruiz@bpo.pe")
                password = st.text_input("Contraseña", type="password")
                entrar = st.form_submit_button("Ingresar", width="stretch", type="primary")

            if entrar:
                if not email or not password:
                    st.warning("Completa correo y contraseña.")
                    return

                with st.spinner("Verificando…"):
                    perfil, error = db.iniciar_sesion(email.strip(), password)

                if error:
                    st.error(error)
                else:
                    st.session_state.usuario = perfil
                    # Guarda la sesión para que F5 no devuelva al login
                    if st.session_state.get("refresh_token"):
                        sesion.guardar_token(st.session_state.refresh_token)
                    st.rerun()
