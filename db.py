"""
CONSULTAS A LA BASE DE DATOS
============================
Todo lo que habla con Supabase está en este archivo, y en ningún otro.

Ventaja: si mañana cambias de base de datos o pasas a una API, solo tocas
este archivo. Las pantallas y la lógica no se enteran.

Cada función hace UNA consulta y devuelve listas o diccionarios de Python.
"""
import streamlit as st

from config import conectar


# ===========================================================================
# LOGIN
# ===========================================================================

def iniciar_sesion(email: str, password: str) -> tuple[dict | None, str | None]:
    """Valida usuario y contraseña.

    Devuelve (perfil, error). Si el perfil viene en None, el texto de error
    dice exactamente qué falló, para no confundir "contraseña incorrecta"
    con "falta el perfil en m_usuarios".
    """
    sb = conectar()

    # Paso 1: validar contra Supabase Auth
    try:
        sesion = sb.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        detalle = str(e).lower()
        if "email not confirmed" in detalle:
            return None, ("El usuario existe pero no está confirmado. En Supabase, "
                          "entra a Authentication > Users, abre el usuario y confírmalo.")
        if "invalid login credentials" in detalle:
            return None, "Correo o contraseña incorrectos."
        return None, f"No se pudo iniciar sesión: {e}"

    id_usuario = sesion.user.id
    # Se guarda para poder reanudar la sesión al recargar la página
    st.session_state.refresh_token = sesion.session.refresh_token

    # Paso 2: buscar su perfil. Auth guarda la contraseña; m_usuarios el rol.
    perfil = sb.table("m_usuarios").select("*, m_zonas(nombre)") \
        .eq("id_usuario", id_usuario).execute().data

    if not perfil:
        sb.auth.sign_out()
        return None, (
            "Tu usuario existe en Supabase pero no tiene perfil. Ejecuta esto en el "
            "SQL Editor:\n\n"
            "```sql\n"
            "insert into m_usuarios (id_usuario, nombre, email, rol)\n"
            f"values ('{id_usuario}', 'Tu Nombre', '{email}', 'master');\n"
            "```"
        )

    if not perfil[0].get("activo", True):
        sb.auth.sign_out()
        return None, "Tu usuario está desactivado. Contacta al administrador."

    return perfil[0], None


def reanudar_sesion(refresh_token: str) -> dict | None:
    """Reanuda una sesión guardada. Devuelve el perfil o None si ya venció."""
    sb = conectar()
    try:
        sesion = sb.auth.refresh_session(refresh_token)
    except Exception:
        return None

    if sesion is None or sesion.user is None:
        return None

    st.session_state.refresh_token = sesion.session.refresh_token
    perfil = sb.table("m_usuarios").select("*, m_zonas(nombre)") \
        .eq("id_usuario", sesion.user.id).execute().data
    return perfil[0] if perfil else None


def cerrar_sesion():
    try:
        conectar().auth.sign_out()
    except Exception:
        pass


# ===========================================================================
# CATÁLOGOS
# Se guardan en caché porque son iguales para todos y casi no cambian.
# ttl=600 significa que se refrescan cada 10 minutos.
# ===========================================================================

@st.cache_data(ttl=600)
def catalogo_skus() -> list[dict]:
    """Productos disponibles, con marca y unidad. Alimenta el buscador."""
    filas = conectar().table("m_skus").select(
        "id_sku, peso_kg, "
        "m_productos(id_producto, nombre, m_categorias(nombre)), "
        "m_marcas(id_marca, nombre), "
        "m_unidades_medida(codigo, nombre)"
    ).eq("activo", True).execute().data

    catalogo = []
    for f in filas:
        catalogo.append({
            "id_sku": f["id_sku"],
            "producto": f["m_productos"]["nombre"],
            "id_producto": f["m_productos"]["id_producto"],
            "categoria": f["m_productos"]["m_categorias"]["nombre"],
            "marca": f["m_marcas"]["nombre"],
            "unidad": f["m_unidades_medida"]["codigo"],
            "peso_kg": f["peso_kg"],
        })
    return sorted(catalogo, key=lambda x: (x["producto"], x["marca"]))


@st.cache_data(ttl=600)
def catalogo_sedes() -> list[dict]:
    """Sedes activas con su ubicación. Se usa para calcular distancias."""
    filas = conectar().table("m_sedes").select(
        "id_sede, codigo, nombre, latitud, longitud, id_distrito, "
        "m_ferreterias(nombre), m_distritos(nombre, id_zona, id_provincia)"
    ).eq("activo", True).execute().data

    return [{
        "id_sede": f["id_sede"],
        "codigo": f["codigo"],
        "sede": f["nombre"],
        "ferreteria": f["m_ferreterias"]["nombre"],
        "latitud": f["latitud"],
        "longitud": f["longitud"],
        "id_distrito": f["id_distrito"],
        "distrito": f["m_distritos"]["nombre"] if f["m_distritos"] else None,
        "id_provincia": f["m_distritos"]["id_provincia"] if f["m_distritos"] else None,
    } for f in filas]


@st.cache_data(ttl=600)
def catalogo_distritos() -> list[dict]:
    """Distritos con cobertura, con su provincia y departamento.

    Se usa cuando el cliente no pasa ubicación exacta: el asesor elige
    departamento, provincia y distrito, y con eso se aplican las reglas 2.x.
    """
    filas = conectar().table("m_distritos").select(
        "id_distrito, nombre, con_cobertura, "
        "m_provincias(id_provincia, nombre, m_departamentos(id_departamento, nombre))"
    ).execute().data

    distritos = []
    for f in filas:
        provincia = f.get("m_provincias") or {}
        departamento = provincia.get("m_departamentos") or {}
        distritos.append({
            "id_distrito": f["id_distrito"],
            "distrito": f["nombre"],
            "con_cobertura": f["con_cobertura"],
            "id_provincia": provincia.get("id_provincia"),
            "provincia": provincia.get("nombre"),
            "id_departamento": departamento.get("id_departamento"),
            "departamento": departamento.get("nombre"),
        })
    return sorted(distritos, key=lambda d: (d["departamento"] or "",
                                            d["provincia"] or "", d["distrito"]))


@st.cache_data(ttl=600)
def reglas_cotizacion() -> list[dict]:
    """Los umbrales de monto y radio. Se editan en Supabase, no aquí."""
    return conectar().table("m_reglas_cotizacion").select("*") \
        .eq("activo", True).order("monto_desde").execute().data


@st.cache_data(ttl=600)
def tipos_cliente() -> list[dict]:
    return conectar().table("m_tipos_cliente").select("*") \
        .eq("activo", True).order("segmento").order("nombre").execute().data


@st.cache_data(ttl=600)
def tipos_pago() -> list[dict]:
    return conectar().table("m_tipos_pago").select("*") \
        .eq("activo", True).order("nombre").execute().data


@st.cache_data(ttl=600)
def motivos_perdida() -> list[dict]:
    return conectar().table("m_motivos_perdida").select("*") \
        .eq("activo", True).eq("automatico", False).order("nombre").execute().data


def limpiar_cache():
    """Llama a esto después de cargar precios o crear una ferretería."""
    st.cache_data.clear()


# ===========================================================================
# PRECIOS
# ===========================================================================

def precios_de(ids_sku: list[int], ids_sede: list[int]) -> list[dict]:
    """Precios vigentes de ciertos productos en ciertas sedes.

    Se pide solo lo necesario, no toda la tabla: con miles de precios,
    traerlos todos haría la app lenta.
    """
    if not ids_sku or not ids_sede:
        return []
    filas = conectar().table("m_precios").select("id_precio, id_sede, id_sku, precio") \
        .in_("id_sku", ids_sku).in_("id_sede", ids_sede).eq("activo", True).execute().data
    return [{**f, "precio": float(f["precio"])} for f in filas]


@st.cache_data(ttl=600)
def precios_referenciales() -> dict[int, float]:
    """Precio promedio por producto. Sirve para decidir el radio de búsqueda."""
    filas = conectar().table("v_precios_referenciales") \
        .select("id_producto, precio_promedio").execute().data
    return {f["id_producto"]: float(f["precio_promedio"]) for f in filas}


# ===========================================================================
# CLIENTES
# ===========================================================================

def buscar_cliente_por_telefono(telefono: str) -> dict | None:
    """Busca por teléfono escrito en cualquier formato.

    La base normaliza el número antes de comparar, así que da igual si el
    asesor escribe 987654321, 51987654321 o +51 987 654 321.
    """
    filas = conectar().rpc("buscar_cliente", {"p_telefono": telefono}).execute().data
    if not filas:
        return None

    cliente = filas[0]
    tipo = conectar().table("m_tipos_cliente").select("segmento, nombre") \
        .eq("id_tipo_cliente", cliente.get("id_tipo_cliente")).execute().data \
        if cliente.get("id_tipo_cliente") else []
    cliente["m_tipos_cliente"] = tipo[0] if tipo else None
    return cliente


def crear_cliente(datos: dict) -> dict:
    return conectar().table("m_clientes").insert(datos).execute().data[0]


def actualizar_cliente(id_cliente: int, datos: dict) -> dict:
    return conectar().table("m_clientes").update(datos) \
        .eq("id_cliente", id_cliente).execute().data[0]


# ===========================================================================
# NEGOCIACIONES
# ===========================================================================

def negociaciones_del_asesor(id_usuario: str, estados: list[str]) -> list[dict]:
    """Las negociaciones del asesor. El RLS ya impide ver las de otros."""
    # Se piden TODAS las columnas del cliente ("m_clientes(*)"): si se listan
    # una por una, es fácil olvidar alguna y la app cree que el dato falta.
    return conectar().table("fact_negociaciones").select(
        "*, m_clientes(*, m_tipos_cliente(segmento, nombre)), m_distritos(nombre)"
    ).eq("id_usuario", id_usuario).in_("estado", estados) \
     .order("fecha_inicio", desc=True).execute().data


def crear_negociacion(datos: dict) -> dict:
    return conectar().table("fact_negociaciones").insert(datos).execute().data[0]


def cerrar_negociacion(id_negociacion: int, id_motivo: int) -> None:
    conectar().table("fact_negociaciones").update({
        "estado": "perdida",
        "id_motivo_perdida": id_motivo,
        "fecha_cierre": "now()",
    }).eq("id_negociacion", id_negociacion).execute()


# ===========================================================================
# COTIZACIONES
# ===========================================================================

def cotizaciones_de(id_negociacion: int) -> list[dict]:
    return conectar().table("fact_cotizaciones").select("*") \
        .eq("id_negociacion", id_negociacion).order("version", desc=True).execute().data


def detalle_de_cotizacion(id_cotizacion: int) -> list[dict]:
    filas = conectar().table("fact_cotizaciones_detalle").select(
        "*, m_skus(id_sku, m_productos(nombre), m_marcas(nombre))"
    ).eq("id_cotizacion", id_cotizacion).execute().data

    return [{
        "id_sku": f["id_sku"],
        "producto": f["m_skus"]["m_productos"]["nombre"],
        "marca": f["m_skus"]["m_marcas"]["nombre"],
        "cantidad": float(f["cantidad"]),
        "precio_unitario": float(f["precio_unitario"]),
        "precio_modificado": float(f["precio_modificado"]) if f["precio_modificado"] else None,
        "motivo_modificacion": f["motivo_modificacion"],
    } for f in filas]


def guardar_cotizacion(cabecera: dict, lineas: list[dict],
                       promociones: list[dict], ferreterias: list[dict]) -> int:
    """Guarda una cotización completa y devuelve su id.

    Se llama a una función de Supabase (RPC) en vez de hacer varios inserts,
    para que sea todo o nada: nunca queda una cotización sin productos.
    """
    respuesta = conectar().rpc("registrar_cotizacion", {
        "p": {
            "cabecera": cabecera,
            "lineas": lineas,
            "promociones": promociones,
            "ferreterias": ferreterias,
        }
    }).execute()
    return respuesta.data


def buscar_por_codigo_cotizacion(id_cotizacion: int) -> dict | None:
    filas = conectar().table("fact_cotizaciones").select("id_cotizacion, id_negociacion") \
        .eq("id_cotizacion", id_cotizacion).execute().data
    return filas[0] if filas else None


# ===========================================================================
# PROMOCIONES
# La base hace el cálculo: la app solo pregunta y muestra.
# ===========================================================================

def promociones_de_sede(id_sede: int, monto: float, id_cliente: int | None) -> list[dict]:
    return conectar().rpc("beneficio_promocional", {
        "p_id_sede": id_sede,
        "p_monto": monto,
        "p_id_cliente": id_cliente,
        "p_momento": "cotizacion",
    }).execute().data or []


def bonos_post_venta(id_sede: int, monto: float, id_cliente: int | None) -> list[dict]:
    return conectar().rpc("beneficio_promocional", {
        "p_id_sede": id_sede,
        "p_monto": monto,
        "p_id_cliente": id_cliente,
        "p_momento": "venta",
    }).execute().data or []


# ===========================================================================
# VENTAS
# ===========================================================================

def registrar_venta(datos: dict) -> int:
    """Acepta la cotización y crea la venta. Devuelve el id de la venta.

    Si no se envían líneas, la base copia el detalle de la cotización tal cual.
    """
    return conectar().rpc("registrar_venta", {"p": datos}).execute().data


def validar_venta(id_venta: int) -> None:
    conectar().rpc("validar_venta", {"p_id_venta": id_venta}).execute()


def anular_venta(id_venta: int, motivo: str) -> None:
    conectar().rpc("anular_venta", {
        "p_id_venta": id_venta, "p_motivo": motivo}).execute()


def ventas_de(id_negociacion: int) -> list[dict]:
    return conectar().table("fact_ventas").select("*") \
        .eq("id_negociacion", id_negociacion).order("fecha_venta", desc=True).execute().data
