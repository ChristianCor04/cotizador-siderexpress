"""
MANTENER LA SESIÓN AL RECARGAR
==============================
Streamlit olvida todo cuando recargas la página (F5). Para no obligar al
asesor a entrar de nuevo, se guarda el "refresh token" de Supabase en una
cookie del navegador y al arrancar se intenta reanudar la sesión.

La cookie dura 7 días y se borra al cerrar sesión.

Nota de seguridad: la cookie es legible por el navegador. Para el MVP es
aceptable; si más adelante la app sale a internet, conviene revisarlo.
"""
import streamlit as st
import streamlit.components.v1 as components

NOMBRE_COOKIE = "se_token"
DIAS = 7


def guardar_token(token: str) -> None:
    """Escribe la cookie desde el navegador."""
    components.html(
        f"""<script>
        document.cookie = "{NOMBRE_COOKIE}={token}; path=/; max-age={DIAS * 86400}; SameSite=Lax";
        </script>""",
        height=0,
    )


def borrar_token() -> None:
    components.html(
        f"""<script>
        document.cookie = "{NOMBRE_COOKIE}=; path=/; max-age=0";
        </script>""",
        height=0,
    )


def leer_token() -> str | None:
    """Lee la cookie. Si el navegador no la envió, devuelve None."""
    try:
        return st.context.cookies.get(NOMBRE_COOKIE) or None
    except Exception:
        # Versiones viejas de Streamlit no tienen st.context: no pasa nada,
        # simplemente habrá que iniciar sesión de nuevo.
        return None
