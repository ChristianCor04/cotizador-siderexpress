"""
CONSULTAS A LA BASE DE DATOS
============================
Todo lo que habla con Supabase está en este archivo, y en ningún otro.

Ventaja: si mañana cambias de base de datos o pasas a una API, solo tocas
este archivo. Las pantallas y la lógica no se enteran.

Cada función hace UNA consulta y devuelve listas o diccionarios de Python.
"""
from datetime import datetime, timezone

import streamlit as st

from config import conectar


def _ahora() -> str:
    """Fecha y hora actual en UTC, en el formato que espera Supabase."""
    return datetime.now(timezone.utc).isoformat()


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
    perfil = sb.table("m_usuarios").select(
        # "m_zonas!fk_usuario_zona" precisa el camino: m_usuarios llega a
        # m_zonas por la zona principal y también por rel_usuarios_zonas,
        # que es una tabla puente. Sin precisarlo, la API lo rechaza.
        "*, m_zonas!fk_usuario_zona(nombre), "
        "rel_usuarios_zonas(id_zona, m_zonas(nombre))"
    ).eq("id_usuario", id_usuario).execute().data

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
    perfil = sb.table("m_usuarios").select(
        # "m_zonas!fk_usuario_zona" precisa el camino: m_usuarios llega a
        # m_zonas por la zona principal y también por rel_usuarios_zonas,
        # que es una tabla puente. Sin precisarlo, la API lo rechaza.
        "*, m_zonas!fk_usuario_zona(nombre), "
        "rel_usuarios_zonas(id_zona, m_zonas(nombre))"
    ).eq("id_usuario", sesion.user.id).execute().data
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
    """Productos disponibles, con marca, unidad y en cuántas sedes hay precio.

    Viene de la vista v_catalogo_skus: así la app sabe qué unidades se cotizan
    de verdad y cuáles están creadas pero sin precio.
    """
    filas = conectar().table("v_catalogo_skus").select("*").execute().data

    catalogo = [{
        "id_sku": f["id_sku"],
        "producto": f["producto"],
        "id_producto": f["id_producto"],
        "categoria": f["categoria"],
        "marca": f["marca"],
        "unidad": f["unidad"],
        "unidad_nombre": f["unidad_nombre"],
        "peso_kg": f["peso_kg"],
        "n_sedes": f.get("n_sedes") or 0,
    } for f in filas]

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
    # Si el texto no se parece a un teléfono, ni se consulta: la base
    # lanzaría un error al intentar normalizarlo.
    digitos = "".join(c for c in telefono if c.isdigit())
    if not 8 <= len(digitos) <= 11:
        return None

    try:
        filas = conectar().rpc("buscar_cliente", {"p_telefono": telefono}).execute().data
    except Exception:
        return None
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

# Lo que se trae de cada negociación. Está en un solo lugar para que la lista
# y la búsqueda devuelvan exactamente los mismos campos.
SELECT_NEGOCIACION = (
    "*, m_clientes(*, m_tipos_cliente(segmento, nombre)), "
    "m_distritos(nombre), "
    "rel_negociacion_tickets(ticket, tipo, fecha_ticket)"
)


def negociacion_por_id(id_negociacion: int) -> dict | None:
    filas = conectar().table("fact_negociaciones").select(SELECT_NEGOCIACION) \
        .eq("id_negociacion", id_negociacion).execute().data
    return filas[0] if filas else None


def negociaciones_del_asesor(id_usuario: str, estados: list[str]) -> list[dict]:
    """Las negociaciones del asesor. El RLS ya impide ver las de otros."""
    # Se piden TODAS las columnas del cliente ("m_clientes(*)"): si se listan
    # una por una, es fácil olvidar alguna y la app cree que el dato falta.
    return conectar().table("fact_negociaciones").select(SELECT_NEGOCIACION) \
        .eq("id_usuario", id_usuario).in_("estado", estados) \
        .order("fecha_inicio", desc=True).execute().data


def crear_negociacion(datos: dict) -> dict:
    return conectar().table("fact_negociaciones").insert(datos).execute().data[0]


def cerrar_negociacion(id_negociacion: int, id_motivo: int) -> None:
    """Cierra la negociación como perdida, con su motivo.

    Usa la función de la base porque además valida que no tenga una venta
    viva y marca como rechazadas las cotizaciones que seguían abiertas.
    """
    conectar().rpc("cerrar_negociacion", {
        "p_id_negociacion": id_negociacion,
        "p_id_motivo": id_motivo,
    }).execute()


def negociacion_abierta_de(id_cliente: int) -> dict | None:
    """Si el cliente ya tiene una negociación activa, devuelve lo mínimo de ella.

    Funciona aunque sea de otro asesor: por eso la consulta va por una función
    de la base con permisos elevados.
    """
    filas = conectar().rpc("negociacion_abierta_de_cliente",
                           {"p_id_cliente": id_cliente}).execute().data
    return filas[0] if filas else None


# ===========================================================================
# COTIZACIONES
# ===========================================================================

def cotizaciones_de(id_negociacion: int) -> list[dict]:
    """Cotizaciones de la negociación, de la más nueva a la más vieja.

    Incluye la ferretería con la que se cotizó: el asesor necesita verla al
    retomar la negociación.
    """
    # "m_sedes!fk_cot_sede" indica por cuál camino unir: fact_cotizaciones
    # llega a m_sedes de dos formas (la sede elegida y las evaluadas), y sin
    # precisarlo la API responde que la relación es ambigua.
    filas = conectar().table("fact_cotizaciones").select(
        "*, m_sedes!fk_cot_sede(id_sede, codigo, nombre, m_ferreterias(nombre))"
    ).eq("id_negociacion", id_negociacion).order("version", desc=True).execute().data

    for f in filas:
        sede = f.get("m_sedes") or {}
        f["sede_codigo"] = sede.get("codigo")
        f["sede_nombre"] = sede.get("nombre")
        f["ferreteria"] = (sede.get("m_ferreterias") or {}).get("nombre")
    return filas


def detalle_de_cotizacion(id_cotizacion: int) -> list[dict]:
    filas = conectar().table("fact_cotizaciones_detalle").select(
        "*, m_skus(id_sku, m_productos(nombre), m_marcas(nombre), "
        "m_unidades_medida(codigo, nombre))"
    ).eq("id_cotizacion", id_cotizacion).execute().data

    return [{
        "id_sku": f["id_sku"],
        "producto": f["m_skus"]["m_productos"]["nombre"],
        "marca": f["m_skus"]["m_marcas"]["nombre"],
        "unidad": (f["m_skus"].get("m_unidades_medida") or {}).get("codigo"),
        "unidad_nombre": (f["m_skus"].get("m_unidades_medida") or {}).get("nombre"),
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
    """TODAS las promociones que aplican, no solo la mejor.

    Se usa promociones_aplicables en vez de beneficio_promocional porque la
    pantalla deja que el asesor elija: necesita ver también las que compiten
    entre sí, no solo la que ganaría por defecto.
    """
    return conectar().rpc("promociones_aplicables", {
        "p_id_sede": id_sede,
        "p_monto": monto,
        "p_id_cliente": id_cliente,
        "p_momento": "cotizacion",
    }).execute().data or []


def bonos_post_venta(id_sede: int, monto: float, id_cliente: int | None) -> list[dict]:
    """Bonos que se entregan después de comprar.

    El asesor también los elige: la decisión se guarda en la cotización y la
    venta la respeta. El monto se recalcula al vender, sobre lo realmente
    pagado, así que el que se ve aquí es una estimación.
    """
    return conectar().rpc("promociones_aplicables", {
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


# ===========================================================================
# PRECIOS
# ===========================================================================

def estado_precios() -> list[dict]:
    """Una fila por sede: cuántos productos tiene y hace cuánto se confirmaron.

    Es lo que alimenta el semáforo de la pantalla de precios.
    """
    return conectar().table("v_estado_precios").select("*") \
        .order("ferreteria").execute().data


def precios_de_ferreteria(id_ferreteria: int) -> list[dict]:
    """Todos los precios de una ferretería, de todas sus sedes."""
    sedes = conectar().table("m_sedes").select("id_sede") \
        .eq("id_ferreteria", id_ferreteria).eq("activo", True).execute().data
    ids = [s["id_sede"] for s in sedes]
    if not ids:
        return []

    filas = conectar().table("m_precios").select(
        "id_precio, id_sede, id_sku, precio, activo, "
        "fecha_actualizacion, fecha_confirmacion"
    ).in_("id_sede", ids).execute().data

    return [{**f, "precio": float(f["precio"])} for f in filas]


def confirmar_precios_ferreteria(id_ferreteria: int) -> int:
    """Botón «Mantienen precios»: registra la confirmación sin tocar montos."""
    return conectar().rpc("confirmar_precios_ferreteria",
                          {"p_id_ferreteria": id_ferreteria}).execute().data


def guardar_precios(precios: list[dict], modo: str = "actualizar") -> dict:
    """Guarda precios en lote.

    modo 'actualizar': toca solo lo que viene en la lista.
    modo 'reemplazar': además desactiva lo que no viene, por sede.
    """
    return conectar().rpc("guardar_precios", {
        "p": {"modo": modo, "precios": precios}
    }).execute().data


def sedes_de_ferreteria(id_ferreteria: int) -> list[dict]:
    return conectar().table("m_sedes") \
        .select("id_sede, codigo, nombre, m_distritos(nombre)") \
        .eq("id_ferreteria", id_ferreteria).eq("activo", True) \
        .order("codigo").execute().data


# ===========================================================================
# TICKETS DEL CRM
# Una negociación puede tener varios: el bot cierra el ticket a las 2 horas,
# así que si el cliente vuelve al día siguiente llega con uno nuevo.
# ===========================================================================

def agregar_ticket(id_negociacion: int, ticket: str, tipo: str) -> None:
    """Asocia un ticket a la negociación. Si ya estaba asociado, no hace nada.

    tipo: 'origen' (el primero), 'seguimiento' (los siguientes) o
          'cierre' (donde llegó el comprobante de pago).
    """
    conectar().table("rel_negociacion_tickets").upsert(
        {"id_negociacion": id_negociacion, "ticket": ticket,
         "tipo": tipo, "fecha_ticket": _ahora()},
        on_conflict="id_negociacion,ticket",
        ignore_duplicates=True,
    ).execute()


def buscar_por_ticket(ticket: str) -> list[dict]:
    """Negociaciones asociadas a un ticket. El RLS limita a las que puedes ver."""
    return conectar().table("rel_negociacion_tickets") \
        .select("id_negociacion, tipo") \
        .eq("ticket", ticket.strip()).execute().data


# ===========================================================================
# PROMOCIONES
# Solo el master puede escribir: el RLS lo impone, no la pantalla.
# ===========================================================================

def promociones(incluir_inactivas: bool = True) -> list[dict]:
    consulta = conectar().table("m_promociones").select("*")
    if not incluir_inactivas:
        consulta = consulta.eq("activo", True)
    return consulta.order("vigente_hasta", desc=True).execute().data


def promocion(id_promocion: int) -> dict | None:
    filas = conectar().table("m_promociones").select("*") \
        .eq("id_promocion", id_promocion).execute().data
    return filas[0] if filas else None


def crear_promocion(datos: dict) -> dict:
    return conectar().table("m_promociones").insert(datos).execute().data[0]


def actualizar_promocion(id_promocion: int, datos: dict) -> dict:
    return conectar().table("m_promociones").update(datos) \
        .eq("id_promocion", id_promocion).execute().data[0]


# ------------------------------------------------------------------ tramos
def tramos_de(id_promocion: int) -> list[dict]:
    return conectar().table("m_promociones_tramos").select("*") \
        .eq("id_promocion", id_promocion).order("monto_desde").execute().data


def crear_tramo(datos: dict) -> dict:
    return conectar().table("m_promociones_tramos").insert(datos).execute().data[0]


def borrar_tramo(id_tramo: int) -> None:
    conectar().table("m_promociones_tramos").delete().eq("id_tramo", id_tramo).execute()


# ------------------------------------------------------------ alcance
def categorias() -> list[dict]:
    return conectar().table("m_categorias").select("*").order("nombre").execute().data


def zonas() -> list[dict]:
    return conectar().table("m_zonas").select("*").eq("activo", True) \
        .order("nombre").execute().data


def ferreterias() -> list[dict]:
    return conectar().table("m_ferreterias").select("id_ferreteria, nombre") \
        .eq("activo", True).order("nombre").execute().data


def alcance_de(tabla: str, id_promocion: int) -> list[int]:
    """Ids del alcance de una promoción (categorías, zonas o tipos de cliente)."""
    columna = {"rel_promociones_categorias": "id_categoria",
               "rel_promociones_zonas": "id_zona",
               "rel_promociones_tipos_cliente": "id_tipo_cliente"}[tabla]
    filas = conectar().table(tabla).select(columna) \
        .eq("id_promocion", id_promocion).execute().data
    return [f[columna] for f in filas]


def guardar_alcance(tabla: str, id_promocion: int, ids: list[int]) -> None:
    """Reemplaza el alcance: borra lo que había y guarda la selección nueva."""
    columna = {"rel_promociones_categorias": "id_categoria",
               "rel_promociones_zonas": "id_zona",
               "rel_promociones_tipos_cliente": "id_tipo_cliente"}[tabla]
    conectar().table(tabla).delete().eq("id_promocion", id_promocion).execute()
    if ids:
        conectar().table(tabla).insert(
            [{"id_promocion": id_promocion, columna: i} for i in ids]).execute()


# ------------------------------------------------------------ afiliación
def afiliacion_de(codigo: str) -> list[dict]:
    return conectar().table("v_promociones_afiliacion").select("*") \
        .eq("promocion", codigo).order("ferreteria").execute().data


def afiliar_ferreteria(id_promocion: int, id_ferreteria: int,
                       acepta: bool, quien: str) -> int:
    return conectar().rpc("afiliar_ferreteria_a_promocion", {
        "p_id_promocion": id_promocion,
        "p_id_ferreteria": id_ferreteria,
        "p_acepta": acepta,
        "p_registrado_por": quien,
    }).execute().data


# ------------------------------------------------------------ simulador
def simular_beneficio(id_promocion: int, monto: float) -> float:
    """Cuánto daría la promoción para una canasta de ese monto."""
    valor = conectar().rpc("calcular_beneficio_promocion", {
        "p_id_promocion": id_promocion, "p_monto": monto}).execute().data
    return float(valor or 0)


# ===========================================================================
# SEGUIMIENTO
# Los cálculos los hace la base. El RLS decide qué ve cada quien: el
# supervisor obtiene los mismos indicadores pero solo de sus zonas.
# ===========================================================================

def _seguimiento(funcion: str, desde, hasta) -> list[dict]:
    return conectar().rpc(funcion, {
        "p_desde": str(desde), "p_hasta": str(hasta)
    }).execute().data or []


def seguimiento_resumen(desde, hasta) -> dict:
    filas = _seguimiento("seguimiento_resumen", desde, hasta)
    return filas[0] if filas else {}


def seguimiento_aperturas(desde, hasta) -> list[dict]:
    return _seguimiento("seguimiento_aperturas", desde, hasta)


def seguimiento_asesores(desde, hasta) -> list[dict]:
    return _seguimiento("seguimiento_asesores", desde, hasta)


def seguimiento_zonas(desde, hasta) -> list[dict]:
    return _seguimiento("seguimiento_zonas", desde, hasta)


def seguimiento_perdidas(desde, hasta) -> list[dict]:
    return _seguimiento("seguimiento_perdidas", desde, hasta)


def seguimiento_ferreterias(desde, hasta) -> list[dict]:
    return _seguimiento("seguimiento_ferreterias", desde, hasta)
