"""
PANTALLA DE REMARKETING
=======================
Bandeja de la asesora de remarketing. Digitaliza su tracker de Excel.

  - Izquierda: los casos, en el orden en que se trabajan: urgentes (pedidos
    por un asesor con «Llamar»), luego los programados para hoy o atrasados,
    y después el resto de mayor a menor monto.
  - Derecha: el caso abierto, con los datos de su cotización, el registro de
    la gestión y su historial.

Las reglas viven en la base (rmkt_registrar_gestion): esta pantalla solo
pide los datos que cada resultado necesita y muestra lo que la base devuelve.

El panel del caso es un fragmento: al marcar opciones se recarga solo él, no
la bandeja entera. Así responde rápido aunque la conexión sea lenta.
"""
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

import config
import db

CONTACTABILIDAD = ["Contactado", "No contesta", "Apagado / fuera de servicio",
                   "Ocupado / colgó sin hablar", "Bloqueado", "Número incorrecto"]
RESULTADOS = ["Retornó al flujo", "Derivado", "Seguimiento interesado",
              "Recontacto", "Prospecto futuro", "Pérdida confirmada"]
OBJECIONES = ["Precio", "Logística", "Confianza", "Forma de pago",
              "No decide ahora", "Nuestra falla", "Sin motivo"]
BENEFICIOS = ["Bono x2", "RUC20", "SIDER100", "Plan Referidos", "Otra"]

PIDE_FECHA = {"Seguimiento interesado", "Recontacto"}
FECHA_OPCIONAL = {"Prospecto futuro"}
PIDE_OBJECION = {"Pérdida confirmada", "Prospecto futuro"}
ATAJOS_FECHA = {"Mañana": 1, "Pasado mañana": 2, "En 1 semana": 7,
                "En 15 días": 15, "En 1 mes": 30, "En 3 meses": 90}
INTENTOS_MAXIMOS = 3

QUE_PASO = {
    "pendiente": "Sigue en la bandeja",
    "programado": "Programado para el",
    "recuperado": "Pasó a Recuperados: queda ahí hasta que la negociación se cierre",
    "cerrado": "Caso cerrado",
}


def mostrar(usuario: dict):
    st.session_state.setdefault("rmkt_version", 0)
    mensaje = st.session_state.pop("rmkt_mensaje", None)
    if mensaje:
        st.success(mensaje)

    hoy = config.hoy_lima()
    casos = db.rmkt_bandeja()
    for c in casos:
        c["fecha_prox"] = date.fromisoformat(c["fecha_proximo_contacto"]) \
            if c.get("fecha_proximo_contacto") else None
        c["para_hoy"] = c["estado"] == "programado" and c["fecha_prox"] is not None \
            and c["fecha_prox"] <= hoy

    bandeja = [c for c in casos if c["estado"] == "pendiente" or c["para_hoy"]]
    programados = [c for c in casos if c["estado"] == "programado" and not c["para_hoy"]]
    recuperados = [c for c in casos if c["estado"] == "recuperado"]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Por gestionar", len(bandeja))
    m2.metric("Urgentes", sum(1 for c in bandeja if c["prioridad"] == 1))
    m3.metric("Programados para hoy", sum(1 for c in bandeja if c["para_hoy"]))
    m4.metric("Gestionados hoy", db.rmkt_gestiones_hoy())

    col_vista, col_zona = st.columns([3, 1], vertical_alignment="bottom")
    vista = col_vista.segmented_control(
        "Vista", ["Bandeja", "Programados", "Recuperados"], default="Bandeja",
        key="rmkt_vista", label_visibility="collapsed") or "Bandeja"
    zonas = sorted({c["zona"] or "Sin zona" for c in casos})
    zona = col_zona.selectbox("Zona", ["Todas las zonas"] + zonas,
                              label_visibility="collapsed", key="rmkt_zona")

    lista = {"Bandeja": bandeja, "Programados": programados, "Recuperados": recuperados}[vista]
    if zona != "Todas las zonas":
        lista = [c for c in lista if (c["zona"] or "Sin zona") == zona]
    lista = _ordenar(lista, vista)

    if not lista:
        st.info({"Bandeja": "No hay casos por gestionar. ¡Bandeja al día!",
                 "Programados": "No hay casos programados para los próximos días.",
                 "Recuperados": "No hay casos recuperados esperando el cierre."}[vista])
        return

    col_lista, col_detalle = st.columns([1, 1.5])
    with col_lista:
        caso = _lista(lista, vista, hoy)
    with col_detalle:
        if caso:
            _detalle(caso, hoy)
        else:
            st.caption("Elige un caso de la lista para gestionarlo.")


# ------------------------------------------------------------------ la lista
def _ordenar(lista, vista):
    if vista == "Programados":
        return sorted(lista, key=lambda c: c["fecha_prox"] or date.max)
    if vista == "Recuperados":
        return sorted(lista, key=lambda c: -(c["monto"] or 0))
    # Bandeja: urgentes, programados para hoy (el más atrasado primero), monto
    return sorted(lista, key=lambda c: (
        0 if c["prioridad"] == 1 else 1 if c["para_hoy"] else 2,
        c["fecha_prox"] or date.max,
        -(c["monto"] or 0)))


def _etiqueta(c, hoy) -> str:
    if c["prioridad"] == 1:
        return "🔴 Urgente"
    if c["para_hoy"]:
        atraso = (hoy - c["fecha_prox"]).days
        return "🟠 Para hoy" if atraso == 0 else f"🟠 Atrasado {atraso} d"
    if c["estado"] == "programado":
        return f"📅 {c['fecha_prox']:%d/%m}"
    if c["estado"] == "recuperado":
        return "✅ " + (c.get("ultimo_resultado") or "Recuperado")
    return "Sin gestión" if not c.get("ultima_gestion") else "En gestión"


def _lista(lista, vista, hoy):
    tabla = pd.DataFrame([{
        "Estado": _etiqueta(c, hoy),
        "Cliente": c["cliente"] or "Sin nombre",
        "Monto": f"S/ {c['monto']:,.0f}" if c["monto"] else "—",
        "Zona": c["zona"] or "—",
        "Cierra en": f"{c['dias_para_cierre']} d" if c.get("dias_para_cierre") is not None
                     else "cerrada",
        "Intento": f"{c['intentos_sin_contacto'] + 1} de {INTENTOS_MAXIMOS}",
    } for c in lista])

    evento = st.dataframe(
        tabla, hide_index=True, width="stretch", height=min(38 + 35 * len(lista), 560),
        on_select="rerun", selection_mode="single-row",
        key=f"rmkt_tabla_{vista}_{st.session_state.rmkt_version}",
        column_config={"Cierra en": st.column_config.TextColumn(
            help="Días hasta que la negociación se cierra sola por inactividad")})
    st.caption(f"{len(lista)} caso(s) · urgentes, programados, monto ↓"
               if vista == "Bandeja" else f"{len(lista)} caso(s)")

    filas = evento.selection.rows if evento and evento.selection else []
    return lista[filas[0]] if filas else None


# ----------------------------------------------------------------- el caso
@st.fragment
def _detalle(caso, hoy):
    id_caso = caso["id_caso"]
    v = f"{id_caso}_{st.session_state.rmkt_version}"

    with st.container(border=True):
        st.markdown(f"##### {caso['cliente'] or 'Sin nombre'} · {caso['telefono'] or 'sin teléfono'}")
        st.caption(" · ".join(x for x in [
            f"3-{caso['id_cotizacion']}" if caso.get("id_cotizacion") else None,
            caso.get("ferreteria"), caso.get("distrito"), caso.get("zona"),
            f"Asesor: {caso['asesor']}" if caso.get("asesor") else None] if x))
        st.caption(" · ".join(x for x in [
            caso.get("categorias"),
            f"**{config.soles(caso['monto'])}**" if caso.get("monto") else None,
            f"versión {caso['version']}" if caso.get("version") and caso["version"] > 1 else None] if x))
        if caso.get("nota_solicitud") or caso["fuente"] == "urgente":
            st.info(f"📞 {caso.get('solicitado_por') or 'El asesor'} pidió llamar"
                    + (f": «{caso['nota_solicitud']}»" if caso.get("nota_solicitud") else "."))

        with st.expander("Productos cotizados"):
            productos = db.rmkt_productos(id_caso)
            if productos:
                st.dataframe(pd.DataFrame([{
                    "Producto": p["producto"], "Marca": p["marca"], "Unidad": p["unidad"],
                    "Cant.": float(p["cantidad"]), "Subtotal": config.soles(p["subtotal"]),
                } for p in productos]), hide_index=True, width="stretch")
            else:
                st.caption("Sin detalle de productos.")

        _formulario(caso, hoy, v)
        _historial(caso)


def _formulario(caso, hoy, v):
    id_caso = caso["id_caso"]
    clave_inicio = f"rmkt_inicio_{id_caso}"

    col_canal, col_boton, col_hora = st.columns([1.3, 1.2, 1], vertical_alignment="bottom")
    canal = col_canal.segmented_control("Canal", ["Llamada", "WhatsApp"], default="Llamada",
                                        key=f"canal_{v}") or "Llamada"
    if col_boton.button("📞 Iniciar llamada" if canal == "Llamada" else "💬 Iniciar contacto",
                        key=f"iniciar_{v}", width="stretch"):
        st.session_state[clave_inicio] = datetime.now(timezone.utc)
    inicio = st.session_state.get(clave_inicio)
    if inicio:
        col_hora.caption(f":green[● Iniciada {inicio.astimezone(config.LIMA):%H:%M}]")

    contacto = st.pills("Contactabilidad", CONTACTABILIDAD, key=f"contacto_{v}")

    resultado = objecion = fecha = None
    if contacto == "Contactado":
        resultado = st.pills("Resultado", RESULTADOS, key=f"resultado_{v}")

    col_a, col_b = st.columns(2)
    if resultado in PIDE_OBJECION:
        objecion = col_a.selectbox("Objeción", OBJECIONES, index=None,
                                   placeholder="Elige la objeción", key=f"objecion_{v}")
    if resultado in PIDE_FECHA | FECHA_OPCIONAL:
        with col_b:
            etiqueta = "Próximo contacto" + (" · opcional" if resultado in FECHA_OPCIONAL else "")
            atajo = st.pills(etiqueta, list(ATAJOS_FECHA), key=f"atajo_{v}")
            otra = st.date_input("Otra fecha", value=None, min_value=hoy, format="DD/MM/YYYY",
                                 key=f"fecha_{v}")
            fecha = otra or (hoy + timedelta(days=ATAJOS_FECHA[atajo]) if atajo else None)
            if fecha:
                st.caption(f"Volverá a la bandeja el {fecha:%d/%m/%Y}")

    beneficio = st.selectbox("Beneficio ofrecido", BENEFICIOS, index=None,
                             placeholder="Ninguno", key=f"beneficio_{v}")
    observacion = st.text_area("Observación", key=f"obs_{v}", height=68,
                               placeholder="Lo que dijo el cliente")

    if resultado in FECHA_OPCIONAL and not fecha:
        st.caption("Sin fecha, el caso se cierra como Prospecto futuro.")
    elif contacto and contacto != "Contactado":
        restantes = INTENTOS_MAXIMOS - caso["intentos_sin_contacto"] - 1
        if contacto in ("Bloqueado", "Número incorrecto"):
            st.caption("El caso se cerrará: no hay forma de contactar al cliente.")
        elif restantes <= 0:
            st.caption("Es el tercer intento sin contacto: el caso se cerrará como Sin contacto agotado.")
        else:
            st.caption(f"Queda en la bandeja. Le quedan {restantes} intento(s).")

    if st.button("Guardar gestión", type="primary", key=f"guardar_{v}"):
        error = _validar(contacto, resultado, objecion, fecha)
        if error:
            st.error(error)
            return
        try:
            r = db.rmkt_registrar_gestion({
                "id_caso": id_caso, "canal": canal, "contactabilidad": contacto,
                "resultado": resultado, "objecion": objecion,
                "fecha_proximo_contacto": str(fecha) if fecha else None,
                "beneficio": beneficio, "observacion": observacion,
                "hora_inicio": inicio.isoformat() if inicio else None,
            })
        except Exception as e:
            st.error(_error(e))
            return
        st.session_state.pop(clave_inicio, None)
        st.session_state.rmkt_version += 1
        st.session_state.rmkt_mensaje = _mensaje(caso, r)
        st.rerun(scope="app")


def _validar(contacto, resultado, objecion, fecha) -> str | None:
    if not contacto:
        return "Indica si el cliente contestó."
    if contacto == "Contactado" and not resultado:
        return "Indica el resultado de la llamada."
    if resultado in PIDE_OBJECION and not objecion:
        return "Indica la objeción del cliente."
    if resultado in PIDE_FECHA and not fecha:
        return "Indica la fecha del próximo contacto."
    return None


def _mensaje(caso, r) -> str:
    nombre = caso["cliente"] or "el cliente"
    estado = (r or {}).get("estado")
    if estado == "cerrado":
        return f"Gestión guardada. Caso de {nombre} cerrado: {r.get('motivo')}."
    if estado == "programado":
        return f"Gestión guardada. {nombre} vuelve a la bandeja en la fecha pactada."
    if estado == "recuperado":
        return f"Gestión guardada. {nombre} pasó a Recuperados."
    return f"Gestión guardada. {nombre} sigue en la bandeja (intento {r.get('intento')})."


def _historial(caso):
    gestiones = db.rmkt_gestiones(caso["id_caso"])
    if not gestiones:
        st.caption("Sin gestiones todavía.")
        return
    st.markdown("**Historial**")
    for g in gestiones:
        partes = [config.fecha_hora(g["hora_fin"])[:16], g["canal"], g["contactabilidad"]]
        if g.get("resultado"):
            partes.append(g["resultado"])
        if g.get("objecion"):
            partes.append(f"objeción: {g['objecion']}")
        if g.get("fecha_proximo_contacto"):
            partes.append(f"próximo: {date.fromisoformat(g['fecha_proximo_contacto']):%d/%m}")
        if g.get("beneficio"):
            partes.append(g["beneficio"])
        linea = " · ".join(partes)
        if g.get("observacion"):
            linea += f" — {g['observacion']}"
        st.caption(linea)


def _error(e) -> str:
    """El mensaje de la base, sin el envoltorio técnico."""
    mensaje = getattr(e, "message", None)
    if mensaje:
        return mensaje
    texto = str(e)
    if "'message': '" in texto:
        return texto.split("'message': '")[1].split("'")[0]
    return f"No se pudo guardar: {texto}"
