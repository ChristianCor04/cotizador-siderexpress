"""
PANTALLA DE PROMOCIONES
=======================
Crear y administrar promociones sin escribir SQL.

Está dividida en tres pestañas:
  Vigentes    la lista, con un simulador para ver cuánto daría cada una
  Nueva       el formulario, agrupado en cinco preguntas
  Afiliación  qué ferreterías aceptaron las que ellas financian

Solo el master entra: el RLS de la base lo impone, esta pantalla solo evita
mostrar botones que igual no funcionarían.
"""
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import config
import db

# Etiquetas legibles para lo que en la base son códigos
TIPOS = {
    "porcentaje":      "Porcentaje del total",
    "monto_fijo":      "Monto fijo en soles",
    "por_bloques":     "Por cada X soles, da Y",
    "escalonada":      "Escalonada por tramos",
    "precio_especial": "Precio especial de un producto",
}
MODALIDADES = {
    "descuento":  "Descuento · baja lo que paga hoy",
    "devolucion": "Devolución · se le entrega después de comprar",
}
APLICACIONES = {
    "automatica": "Automática · el asesor no la puede quitar",
    "sugerida":   "Sugerida · viene marcada y puede quitarla",
    "manual":     "Manual · viene desmarcada",
}
FINANCIADORES = ["siderexpress", "ferreteria", "proveedor", "compartido"]


def mostrar(usuario: dict):
    if usuario["rol"] != "master":
        st.info("Solo el administrador puede crear o editar promociones.")
        return

    st.markdown("##### Promociones")
    vigentes, nueva, afiliacion = st.tabs(["Vigentes", "Nueva promoción", "Afiliación"])

    with vigentes:
        _lista()
    with nueva:
        _formulario(usuario)
    with afiliacion:
        _afiliacion(usuario)


# =========================================================== 1. LA LISTA ===
def _lista():
    todas = db.promociones()
    if not todas:
        st.caption("Todavía no hay promociones. Créala en la pestaña de al lado.")
        return

    hoy = date.today().isoformat()
    activas = [p for p in todas
               if p["activo"] and p["vigente_desde"][:10] <= hoy <= p["vigente_hasta"][:10]]

    c1, c2, c3 = st.columns(3)
    c1.metric("Vigentes hoy", len(activas))
    c2.metric("Creadas", len(todas))
    c3.metric("Apagadas", sum(1 for p in todas if not p["activo"]))

    monto = st.number_input(
        "Simular con una canasta de", min_value=0.0, value=7000.0, step=500.0,
        format="%.2f",
        help="Muestra cuánto daría cada promoción para ese monto.",
    )

    for promo in todas:
        _tarjeta(promo, monto)


def _tarjeta(promo, monto):
    vigente = (promo["activo"]
               and promo["vigente_desde"][:10] <= date.today().isoformat()
               <= promo["vigente_hasta"][:10])
    estado = "🟢 vigente" if vigente else ("⚪ apagada" if not promo["activo"] else "🔴 fuera de fecha")

    with st.container(border=True):
        col_nombre, col_simula = st.columns([2.5, 1])
        col_nombre.markdown(f"**{promo['nombre']}** · `{promo['codigo']}`")
        col_nombre.caption(
            f"{estado} · {MODALIDADES[promo['modalidad']].split(' · ')[0]} · "
            f"{TIPOS[promo['tipo']]} · hasta {promo['vigente_hasta'][:10]}"
        )

        if vigente:
            try:
                beneficio = db.simular_beneficio(promo["id_promocion"], monto)
            except Exception:
                beneficio = 0
            col_simula.metric("Daría", config.soles(beneficio))

        with st.expander("Ver y editar"):
            _detalle(promo)


def _detalle(promo):
    st.caption(promo.get("descripcion") or "Sin descripción")

    datos = {
        "Quién la paga": promo["financiado_por"],
        "Cómo llega al asesor": APLICACIONES[promo["aplicacion"]].split(" · ")[0],
        "Acumulable": "sí" if promo["acumulable"] else "no",
        "Requiere afiliación": "sí" if promo["requiere_afiliacion"] else "no",
        "Momento": promo["momento"],
        "Monto mínimo": config.soles(promo["monto_minimo"]) if promo["monto_minimo"] else "—",
        "Tope": config.soles(promo["tope_beneficio"]) if promo["tope_beneficio"] else "sin tope",
    }
    condiciones = _texto_condiciones(promo)
    if condiciones:
        datos["Solo para"] = condiciones

    st.dataframe(pd.DataFrame(datos.items(), columns=["Campo", "Valor"]),
                 hide_index=True, width="stretch")

    if promo["tipo"] == "escalonada":
        tramos = db.tramos_de(promo["id_promocion"])
        if tramos:
            st.caption("Tramos")
            st.dataframe(pd.DataFrame([{
                "Desde": config.soles(t["monto_desde"]),
                "Hasta": config.soles(t["monto_hasta"]) if t["monto_hasta"] else "a más",
                "Da": (f"{float(t['valor']):g}%" if t["tipo_valor"] == "porcentaje"
                       else config.soles(t["valor"])),
            } for t in tramos]), hide_index=True, width="stretch")

    col_apagar, col_fecha = st.columns(2)

    if promo["activo"]:
        if col_apagar.button("Apagar promoción", key=f"apagar_{promo['id_promocion']}",
                             width="stretch",
                             help="No se borra: deja de aplicarse y las cotizaciones "
                                  "antiguas la siguen mostrando."):
            db.actualizar_promocion(promo["id_promocion"], {"activo": False})
            st.rerun()
    else:
        if col_apagar.button("Reactivar", key=f"prender_{promo['id_promocion']}",
                             width="stretch"):
            db.actualizar_promocion(promo["id_promocion"], {"activo": True})
            st.rerun()

    nueva_fecha = col_fecha.date_input(
        "Vence el", value=date.fromisoformat(promo["vigente_hasta"][:10]),
        key=f"fecha_{promo['id_promocion']}",
    )
    if nueva_fecha.isoformat() != promo["vigente_hasta"][:10]:
        if col_fecha.button("Cambiar fecha", key=f"guardar_fecha_{promo['id_promocion']}",
                            width="stretch"):
            db.actualizar_promocion(promo["id_promocion"],
                                    {"vigente_hasta": f"{nueva_fecha}T23:59:59"})
            st.rerun()


def _texto_condiciones(promo) -> str:
    partes = []
    if promo.get("segmento_cliente"):
        partes.append(f"clientes {promo['segmento_cliente']}")
    if promo.get("compras_previas_max") == 0:
        partes.append("primera compra")
    elif promo.get("compras_previas_min"):
        partes.append(f"desde la compra n° {promo['compras_previas_min'] + 1}")
    if promo.get("dias_sin_comprar_min"):
        partes.append(f"sin comprar hace {promo['dias_sin_comprar_min']} días")
    return ", ".join(partes)


# ======================================================== 2. FORMULARIO ===
def _formulario(usuario):
    # El mensaje del guardado anterior: se muestra después de la recarga,
    # porque st.rerun() borra lo que se escriba justo antes.
    mensaje = st.session_state.pop("promo_mensaje", None)
    if mensaje:
        st.success(mensaje["texto"])
        if mensaje.get("aviso"):
            st.info(mensaje["aviso"])

    st.caption("Las cinco preguntas que definen una promoción.")

    # ---------------------------------------------------- qué da
    st.markdown("**1 · ¿Qué da la promoción?**")
    col_nombre, col_codigo = st.columns([2, 1])
    nombre = col_nombre.text_input("Nombre", placeholder="Ej. 10% por compras grandes")
    codigo = col_codigo.text_input("Código", placeholder="PROMO-10",
                                   help="Identificador corto y único.")
    descripcion = st.text_input("Descripción", placeholder="Opcional")

    col_mod, col_tipo = st.columns(2)
    modalidad = col_mod.selectbox("Modalidad", list(MODALIDADES),
                                  format_func=lambda m: MODALIDADES[m])
    tipo = col_tipo.selectbox("Tipo de cálculo", list(TIPOS),
                              format_func=lambda t: TIPOS[t])

    valor, base_bloque, tramos = None, None, []

    if tipo == "porcentaje":
        valor = st.number_input("Porcentaje", min_value=0.1, max_value=100.0,
                                value=5.0, step=0.5, format="%.2f")
    elif tipo in ("monto_fijo", "precio_especial"):
        etiqueta = "Monto a descontar" if tipo == "monto_fijo" else "Precio especial"
        valor = st.number_input(etiqueta, min_value=0.01, value=50.0, step=5.0,
                                format="%.2f")
    elif tipo == "por_bloques":
        col_cada, col_da = st.columns(2)
        base_bloque = col_cada.number_input("Por cada (S/)", min_value=1.0,
                                            value=1500.0, step=100.0, format="%.2f")
        valor = col_da.number_input("Da (S/)", min_value=0.01, value=50.0,
                                    step=5.0, format="%.2f")
        st.caption(f"Ejemplo: con S/ {base_bloque * 2:,.0f} de compra daría "
                   f"{config.soles(valor * 2)}. Solo cuentan los bloques completos.")
    elif tipo == "escalonada":
        st.caption("Define los tramos. El último se deja sin tope para que cubra "
                   "de ahí en adelante.")
        tramos = _editor_tramos()

    # ---------------------------------------------------- cuándo
    st.divider()
    st.markdown("**2 · ¿Cuándo aplica?**")
    col_desde, col_hasta = st.columns(2)
    desde = col_desde.date_input("Desde", value=date.today())
    hasta = col_hasta.date_input("Hasta", value=date.today() + timedelta(days=30))

    col_min, col_tope, col_momento = st.columns(3)
    monto_minimo = col_min.number_input("Compra mínima (S/)", min_value=0.0,
                                        value=0.0, step=100.0, format="%.2f",
                                        help="0 = sin mínimo")
    tope = col_tope.number_input("Tope del beneficio (S/)", min_value=0.0,
                                 value=0.0, step=50.0, format="%.2f",
                                 help="0 = sin tope")
    momento = col_momento.selectbox(
        "Se calcula", ["cotizacion", "venta"],
        format_func=lambda m: ("Al cotizar" if m == "cotizacion"
                               else "Al vender, sobre lo pagado"),
        help="«Al vender» sirve para los bonos: se calcula sobre lo que el "
             "cliente realmente pagó, no sobre lo cotizado.",
    )

    # ---------------------------------------------------- a quién
    st.divider()
    st.markdown("**3 · ¿A qué clientes?**")
    col_seg, col_compras = st.columns(2)
    segmento = col_seg.selectbox("Segmento", ["Todos", "B2B", "B2C"])
    condicion = col_compras.selectbox(
        "Historial de compras",
        ["Todos", "Solo primera compra", "Solo recompras", "Clientes dormidos"],
    )

    dias_sin_comprar = None
    compras_min, compras_max = None, None
    if condicion == "Solo primera compra":
        compras_max = 0
    elif condicion == "Solo recompras":
        compras_min = 1
    elif condicion == "Clientes dormidos":
        dias_sin_comprar = st.number_input("Días sin comprar", min_value=1,
                                           value=90, step=15)

    tipos_cliente = db.tipos_cliente()
    etiquetas_tipo = {t["id_tipo_cliente"]: f"{t['segmento']} · {t['nombre']}"
                      for t in tipos_cliente}
    tipos_elegidos = st.multiselect(
        "Solo estos tipos de cliente", list(etiquetas_tipo),
        format_func=lambda i: etiquetas_tipo[i],
        help="Vacío = todos los tipos del segmento elegido.",
    )

    # ---------------------------------------------------- dónde
    st.divider()
    st.markdown("**4 · ¿Sobre qué y dónde?**")
    cats = db.categorias()
    etiquetas_cat = {c["id_categoria"]: c["nombre"] for c in cats}
    categorias_elegidas = st.multiselect(
        "Solo estas categorías", list(etiquetas_cat),
        format_func=lambda i: etiquetas_cat[i],
        help="Vacío = todos los productos.",
    )

    zonas = db.zonas()
    etiquetas_zona = {z["id_zona"]: z["nombre"] for z in zonas}
    zonas_elegidas = st.multiselect(
        "Solo estas zonas", list(etiquetas_zona),
        format_func=lambda i: etiquetas_zona[i],
        help="Vacío = todas las zonas.",
    )

    # ---------------------------------------------------- cómo se aplica
    st.divider()
    st.markdown("**5 · ¿Cómo se aplica?**")
    col_fin, col_apl = st.columns(2)
    financiado = col_fin.selectbox("Quién la paga", FINANCIADORES)
    aplicacion = col_apl.selectbox("Cómo llega al asesor", list(APLICACIONES),
                                   format_func=lambda a: APLICACIONES[a])

    col_afi, col_acu, col_pri = st.columns(3)
    requiere_afiliacion = col_afi.checkbox(
        "Requiere afiliación", value=(financiado == "ferreteria"),
        help="Si la paga la ferretería, solo aplica donde la aceptaron.",
    )
    acumulable = col_acu.checkbox("Acumulable con otras", value=True)
    prioridad = col_pri.number_input("Prioridad", min_value=1, value=100, step=10,
                                     help="Menor número = se evalúa primero.")

    # ---------------------------------------------------- guardar
    st.divider()
    if st.button("Crear promoción", type="primary", width="stretch"):
        errores = _validar(nombre, codigo, tipo, tramos, desde, hasta)
        if errores:
            st.error("\n".join(f"- {e}" for e in errores))
            return

        datos = {
            "codigo": codigo.strip().upper(),
            "nombre": nombre.strip(),
            "descripcion": descripcion.strip() or None,
            "modalidad": modalidad,
            "tipo": tipo,
            "valor": valor,
            "base_bloque": base_bloque,
            "alcance": "producto" if tipo == "precio_especial" else "cotizacion",
            "vigente_desde": f"{desde}T00:00:00",
            "vigente_hasta": f"{hasta}T23:59:59",
            "monto_minimo": monto_minimo or None,
            "tope_beneficio": tope or None,
            "momento": momento,
            "segmento_cliente": None if segmento == "Todos" else segmento,
            "compras_previas_min": compras_min,
            "compras_previas_max": compras_max,
            "dias_sin_comprar_min": dias_sin_comprar,
            "financiado_por": financiado,
            "aplicacion": aplicacion,
            "requiere_afiliacion": requiere_afiliacion,
            "acumulable": acumulable,
            "prioridad": int(prioridad),
            "activo": True,
        }

        try:
            creada = db.crear_promocion(datos)
        except Exception as e:
            st.error(_error(e))
            return

        id_promocion = creada["id_promocion"]

        for t in tramos:
            db.crear_tramo({**t, "id_promocion": id_promocion})
        if categorias_elegidas:
            db.guardar_alcance("rel_promociones_categorias", id_promocion,
                               categorias_elegidas)
        if zonas_elegidas:
            db.guardar_alcance("rel_promociones_zonas", id_promocion, zonas_elegidas)
        if tipos_elegidos:
            db.guardar_alcance("rel_promociones_tipos_cliente", id_promocion,
                               tipos_elegidos)

        st.session_state.promo_mensaje = {
            "texto": f"Promoción {creada['codigo']} creada.",
            "aviso": ("Como requiere afiliación, todavía no aplica en ninguna "
                      "ferretería. Regístralas en la pestaña Afiliación.")
                     if requiere_afiliacion else None,
        }
        st.session_state.pop("tramos_nuevos", None)
        st.rerun()


def _editor_tramos() -> list[dict]:
    """Tramos de una promoción escalonada, con el último abierto."""
    if "tramos_nuevos" not in st.session_state:
        st.session_state.tramos_nuevos = [
            {"monto_desde": 3000.0, "monto_hasta": 6000.0,
             "tipo_valor": "porcentaje", "valor": 1.0},
            {"monto_desde": 6000.0, "monto_hasta": None,
             "tipo_valor": "porcentaje", "valor": 2.0},
        ]

    for i, tramo in enumerate(st.session_state.tramos_nuevos):
        col_d, col_h, col_t, col_v, col_x = st.columns([1, 1, 1, 1, 0.4])
        tramo["monto_desde"] = col_d.number_input(
            "Desde", value=float(tramo["monto_desde"]), step=500.0,
            key=f"td_{i}", format="%.0f")
        sin_tope = tramo["monto_hasta"] is None
        hasta = col_h.number_input(
            "Hasta", value=float(tramo["monto_hasta"] or 0), step=500.0,
            key=f"th_{i}", format="%.0f",
            help="0 = de ahí en adelante")
        tramo["monto_hasta"] = None if hasta == 0 else hasta
        tramo["tipo_valor"] = col_t.selectbox(
            "Tipo", ["porcentaje", "monto_fijo"], key=f"tt_{i}",
            index=0 if tramo["tipo_valor"] == "porcentaje" else 1)
        tramo["valor"] = col_v.number_input(
            "Da", value=float(tramo["valor"]), step=0.5, key=f"tv_{i}",
            format="%.2f")
        col_x.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if col_x.button("🗑", key=f"tx_{i}"):
            st.session_state.tramos_nuevos.pop(i)
            st.rerun()

    if st.button("＋ Agregar tramo"):
        ultimo = st.session_state.tramos_nuevos[-1] if st.session_state.tramos_nuevos else None
        desde = float(ultimo["monto_hasta"] or ultimo["monto_desde"] + 3000) if ultimo else 0.0
        st.session_state.tramos_nuevos.append(
            {"monto_desde": desde, "monto_hasta": None,
             "tipo_valor": "porcentaje", "valor": 1.0})
        st.rerun()

    return st.session_state.tramos_nuevos


def _validar(nombre, codigo, tipo, tramos, desde, hasta) -> list[str]:
    errores = []
    if not nombre.strip():
        errores.append("Falta el nombre.")
    if not codigo.strip():
        errores.append("Falta el código.")
    if hasta <= desde:
        errores.append("La fecha de fin debe ser posterior a la de inicio.")

    if tipo == "escalonada":
        if not tramos:
            errores.append("Una promoción escalonada necesita al menos un tramo.")
        for t in tramos:
            if t["monto_hasta"] is not None and t["monto_hasta"] <= t["monto_desde"]:
                errores.append(
                    f"El tramo que empieza en {t['monto_desde']:,.0f} termina antes de empezar.")
        abiertos = [t for t in tramos if t["monto_hasta"] is None]
        if len(abiertos) > 1:
            errores.append("Solo un tramo puede quedar sin tope.")
    return errores


def _error(e) -> str:
    detalle = str(e)
    if "uq_promocion_codigo" in detalle:
        return "Ya existe una promoción con ese código."
    if "chk_promo_valor" in detalle:
        return "El valor no corresponde al tipo elegido. Revisa el porcentaje o el monto."
    if "chk_promo_fechas" in detalle:
        return "La fecha de fin debe ser posterior a la de inicio."
    if "permission denied" in detalle or "row-level security" in detalle:
        return "Tu usuario no tiene permiso para crear promociones."
    return f"No se pudo crear: {e}"


# ========================================================= 3. AFILIACIÓN ===
def _afiliacion(usuario):
    st.caption("Solo hace falta en las promociones que paga la ferretería: "
               "mientras no acepten, no aplican en sus sedes.")

    promos = [p for p in db.promociones(incluir_inactivas=False)
              if p["requiere_afiliacion"]]
    if not promos:
        st.info("Ninguna promoción activa requiere afiliación.")
        return

    etiquetas = {p["codigo"]: p for p in promos}
    elegida = st.selectbox("Promoción", list(etiquetas),
                           format_func=lambda c: f"{c} · {etiquetas[c]['nombre']}")
    promo = etiquetas[elegida]

    filas = db.afiliacion_de(promo["codigo"])
    if filas:
        resumen = pd.DataFrame([{
            "Ferretería": f["ferreteria"],
            "Sede": f["sede_codigo"],
            "Distrito": (f.get("distrito") or "").replace("_", " "),
            "Estado": f["estado"],
        } for f in filas])
        st.dataframe(resumen, hide_index=True, width="stretch", height=280)

    st.markdown("**Registrar respuesta**")
    col_fer, col_resp, col_btn = st.columns([2, 1, 1])
    ferreterias = db.ferreterias()
    nombres = {f["id_ferreteria"]: f["nombre"] for f in ferreterias}
    id_ferreteria = col_fer.selectbox("Ferretería", list(nombres),
                                      format_func=lambda i: nombres[i])
    respuesta = col_resp.selectbox("Respuesta", ["Acepta", "Rechaza"])
    col_btn.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)

    if col_btn.button("Registrar", width="stretch"):
        try:
            n = db.afiliar_ferreteria(promo["id_promocion"], id_ferreteria,
                                      respuesta == "Acepta", usuario["nombre"])
            st.success(f"Registrado en {n} sede(s).")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo registrar: {e}")
