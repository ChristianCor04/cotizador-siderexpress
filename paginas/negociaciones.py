"""
PANTALLA DE NEGOCIACIONES
=========================
Es la pantalla principal. Todo pasa aquí, sin cambiar de página:

  Columna 1  Lista de negociaciones y buscador
  Columna 2  Cliente, ubicación y lista de materiales
  Columna 3  Ferreterías, promociones y generar PDF

Está dividida en funciones cortas, una por bloque visual. Si quieres
cambiar cómo se ve un bloque, busca la función con ese nombre.
"""
import pandas as pd
import streamlit as st

import config
import db
from logica.cotizacion import (cotizar_en_sedes, elegir_regla, monto_referencial,
                               sedes_candidatas)
from logica.geo import extraer_coordenadas, sedes_cercanas
from logica.pdf import generar_pdf


# ===========================================================================
# MEMORIA DE LA PANTALLA
# Streamlit vuelve a ejecutar todo el archivo en cada clic, así que lo que
# debe sobrevivir se guarda en st.session_state.
# ===========================================================================

VALORES_INICIALES = {
    "negociacion": None,      # negociación abierta ahora
    "cliente": None,          # datos del cliente
    "materiales": [],         # lo que el asesor va agregando
    "ubicacion_texto": "",
    "resultados": [],         # ferreterías cotizadas
    "sede_elegida": None,
    "regla": None,
    "monto_ref": 0.0,
    "modo_nuevo": False,      # True mientras crea una negociación nueva
    "cotizacion_actual": None,  # última cotización cargada de la negociación
    "pdf_generado": None,
    # Sube cada vez que se carga otra negociación. Va en la "key" de los
    # campos para que Streamlit los trate como nuevos y no arrastre valores.
    "version_tabla": 0,
    # Cuando el cliente no pasa ubicación exacta, se elige a mano
    "id_distrito": None,
    "id_provincia": None,
    # Ticket del CRM de la conversación actual con el cliente
    "ticket_actual": None,
    # Negociación viva que impide crear otra para el mismo cliente
    "negociacion_bloqueante": None,
    # Flete: solo se cobra cuando la entrega lo exige
    "flete_monto": 0.0,
}


def _preparar_memoria():
    for clave, valor in VALORES_INICIALES.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


def _limpiar_resultados():
    """Los montos quedan viejos si cambian materiales o ubicación.

    También se descarta el PDF generado: pertenecía a la cotización anterior
    y descargarlo después llevaría a enviar un documento equivocado.
    """
    st.session_state.resultados = []
    st.session_state.sede_elegida = None
    st.session_state.pdf_generado = None
    st.session_state.flete_monto = 0.0


# ===========================================================================
# PANTALLA
# ===========================================================================

def mostrar(usuario: dict):
    _preparar_memoria()

    col_lista, col_centro, col_ferreterias = st.columns([1, 2.3, 1.4], gap="medium")

    with col_lista:
        _bloque_lista(usuario)
    with col_centro:
        _bloque_cliente_y_materiales(usuario)
    with col_ferreterias:
        _bloque_ferreterias(usuario)


# ---------------------------------------------------------------- columna 1
def _tickets_de(neg) -> list[dict]:
    """Tickets de la negociación, del más reciente al más antiguo."""
    tickets = (neg or {}).get("rel_negociacion_tickets") or []
    return sorted(tickets, key=lambda t: t.get("fecha_ticket") or "", reverse=True)


def _bloque_lista(usuario):
    st.markdown("##### Negociaciones")

    buscar = st.text_input(
        "Buscar", placeholder="ID CRM, teléfono o N° cotización",
        label_visibility="collapsed", key="buscador",
    )
    if st.button("＋ Nueva negociación", width="stretch"):
        _empezar_nueva()

    if buscar:
        _buscar(buscar)

    estados = st.segmented_control(
        "Estado", ["Activas", "Por cerrar", "Ganadas"],
        default="Activas", label_visibility="collapsed",
    ) or "Activas"

    filtro = {
        "Activas": ["abierta"],
        "Por cerrar": ["por_cerrar"],
        "Ganadas": ["ganada"],
    }[estados]

    negociaciones = db.negociaciones_del_asesor(usuario["id_usuario"], filtro)

    if not negociaciones:
        st.caption("No hay negociaciones en este estado.")
        return

    for neg in negociaciones:
        _tarjeta_negociacion(neg)


def _tarjeta_negociacion(neg):
    """Una tarjeta de la lista."""
    cliente = neg.get("m_clientes") or {}
    tipo = (cliente.get("m_tipos_cliente") or {})
    activa = (st.session_state.negociacion or {}).get("id_negociacion") == neg["id_negociacion"]

    with st.container(border=True):
        st.caption(config.codigo_negociacion(neg["id_negociacion"]))
        st.markdown(f"**{cliente.get('nombre') or 'Sin nombre'}**")
        etiqueta = f"{tipo.get('segmento','')} · {tipo.get('nombre','')}".strip(" ·")
        distrito = (neg.get("m_distritos") or {}).get("nombre") or neg.get("distrito_texto") or ""
        st.caption(f"{etiqueta} · {distrito}" if etiqueta else distrito)

        tickets = _tickets_de(neg)
        if tickets:
            extra = f" (+{len(tickets) - 1})" if len(tickets) > 1 else ""
            st.caption(f"ID CRM {tickets[0]['ticket']}{extra}")

        if st.button("Abrir" if not activa else "Abierta", key=f"abrir_{neg['id_negociacion']}",
                     width="stretch", type="primary" if activa else "secondary",
                     disabled=activa):
            _abrir_negociacion(neg)


def _abrir_negociacion(neg):
    st.session_state.negociacion = neg
    st.session_state.cliente = neg.get("m_clientes")
    st.session_state.modo_nuevo = False
    st.session_state.id_distrito = neg.get("id_distrito")
    st.session_state.id_provincia = None
    # Se propone el ticket más reciente: es el caso común si el asesor sigue
    # en la misma conversación. Si el cliente volvió por otra, lo cambia.
    tickets = _tickets_de(neg)
    st.session_state.ticket_actual = tickets[0]["ticket"] if tickets else None
    st.session_state.negociacion_bloqueante = None
    _limpiar_resultados()

    # Cargar la última cotización, si existe
    cotizaciones = db.cotizaciones_de(neg["id_negociacion"])
    if cotizaciones:
        ultima = cotizaciones[0]
        detalle = db.detalle_de_cotizacion(ultima["id_cotizacion"])
        st.session_state.materiales = [{
            "producto": d["producto"],
            "marca": d["marca"],
            "unidad": d.get("unidad_nombre"),
            "cantidad": d["cantidad"],
            "precio_negociado": d["precio_modificado"],
            "motivo": d["motivo_modificacion"],
            "autorizado_por": None,
        } for d in detalle]
        st.session_state.cotizacion_actual = ultima
        st.session_state.version_tabla += 1
        st.session_state.ubicacion_texto = (
            f"{ultima['latitud']}, {ultima['longitud']}" if ultima.get("latitud") else ""
        )
    else:
        st.session_state.materiales = []
        st.session_state.cotizacion_actual = None
        st.session_state.version_tabla += 1
    st.rerun()


def _empezar_nueva():
    st.session_state.negociacion = None
    st.session_state.cliente = None
    st.session_state.materiales = []
    st.session_state.ubicacion_texto = ""
    st.session_state.modo_nuevo = True
    st.session_state.id_distrito = None
    st.session_state.id_provincia = None
    st.session_state.ticket_actual = None
    st.session_state.negociacion_bloqueante = None
    st.session_state.cotizacion_actual = None
    st.session_state.version_tabla += 1
    _limpiar_resultados()
    st.rerun()


def _buscar(texto):
    """Busca por ticket, número de cotización o teléfono, en ese orden.

    Un mismo texto puede ser varias cosas (un ticket numérico se parece a un
    número de cotización), así que se prueban las tres y se muestran todas
    las coincidencias.
    """
    texto = texto.strip()
    encontradas = {}          # id_negociacion -> cómo se encontró

    for fila in db.buscar_por_ticket(texto):
        encontradas.setdefault(fila["id_negociacion"], f"ID CRM {texto}")

    if texto.isdigit() and len(texto) <= 7:
        cotizacion = db.buscar_por_codigo_cotizacion(int(texto))
        if cotizacion:
            encontradas.setdefault(
                cotizacion["id_negociacion"],
                f"cotización {config.codigo_cotizacion(int(texto))}")

    cliente = db.buscar_cliente_por_telefono(texto)

    if not encontradas and not cliente:
        st.warning("Sin resultados. Usa ＋ para crear una negociación nueva.")
        return

    for id_negociacion, motivo in encontradas.items():
        codigo = config.codigo_negociacion(id_negociacion)
        if st.button(f"Abrir {codigo} · {motivo}", key=f"buscar_abrir_{id_negociacion}",
                     width="stretch"):
            neg = db.negociacion_por_id(id_negociacion)
            if neg:
                _abrir_negociacion(neg)
            else:
                st.error("No tienes acceso a esa negociación.")

    if cliente:
        st.info(f"Cliente registrado: **{cliente.get('nombre') or 'sin nombre'}**. "
                "Si no ves su negociación en la lista, crea una nueva con ＋.")


# ---------------------------------------------------------------- columna 2
def _bloque_cliente_y_materiales(usuario):
    if st.session_state.negociacion is None and not st.session_state.modo_nuevo:
        st.info("Elige una negociación de la lista o crea una nueva.")
        return

    with st.container(border=True):
        _bloque_ticket()
        st.divider()
        _datos_cliente(usuario)
        st.divider()
        _ubicacion()
        st.divider()
        _lista_materiales()

    if st.session_state.negociacion:
        _bloque_venta(usuario)


def _aviso_negociacion_abierta():
    """Mensaje cuando el cliente buscado ya tiene una negociación viva."""
    abierta = st.session_state.get("negociacion_bloqueante")
    if not abierta:
        return

    codigo = config.codigo_negociacion(abierta["id_negociacion"])
    detalle = f"{codigo} · {abierta['asesor']} · desde {config.fecha_hora(abierta['fecha_inicio'])}"

    st.error(
        f"Este cliente ya tiene una negociación activa ({detalle}). "
        "Para poder crear una nueva negociación debe dar por finalizada la anterior."
    )

    if abierta.get("es_mia"):
        if st.button(f"Abrir {codigo}", key="abrir_bloqueante", width="stretch"):
            neg = db.negociacion_por_id(abierta["id_negociacion"])
            st.session_state.negociacion_bloqueante = None
            if neg:
                _abrir_negociacion(neg)
    else:
        st.caption("La atiende otro asesor. Coordina con él antes de continuar.")


def _bloque_ticket():
    """El ID CRM identifica la conversación con el cliente.

    Va arriba porque es lo primero que tiene el asesor: el ID llega del CRM
    y desde ahí abre la cotización.

    En el código y en la base sigue llamándose "ticket"; «ID CRM» es solo
    cómo se muestra en pantalla.
    """
    tickets = _tickets_de(st.session_state.negociacion)
    registrados = [t["ticket"] for t in tickets]

    col_ticket, col_info = st.columns([1.2, 2], vertical_alignment="bottom")
    ticket = col_ticket.text_input(
        "ID CRM *", value=st.session_state.ticket_actual or "",
        placeholder="Ej. 458213", key=f"ticket_{st.session_state.version_tabla}",
        help="Identifica la conversación del cliente en el CRM. "
             "Es obligatorio para generar la cotización.",
    )
    st.session_state.ticket_actual = ticket.strip() or None

    with col_info:
        if registrados:
            st.caption("ID CRM de esta negociación: " + ", ".join(registrados))
        if ticket.strip() and registrados and ticket.strip() not in registrados:
            st.caption(":orange[ID CRM nuevo: se agregará como seguimiento "
                       "al generar la cotización.]")


def _datos_cliente(usuario):
    cliente = st.session_state.cliente

    if cliente is None:
        _aviso_negociacion_abierta()
        st.markdown("##### Cliente nuevo")
        telefono = st.text_input("Teléfono", placeholder="+51987654321", key="tel_nuevo")
        if st.button("Buscar cliente", key="btn_buscar_cliente"):
            encontrado = db.buscar_cliente_por_telefono(telefono.strip())
            if encontrado:
                # Antes de adoptarlo, se revisa que no tenga otra negociación
                # viva: la base lo impide y es mejor avisar aquí.
                abierta = db.negociacion_abierta_de(encontrado["id_cliente"])
                if abierta:
                    st.session_state.cliente = None
                    st.session_state.negociacion_bloqueante = abierta
                else:
                    st.session_state.negociacion_bloqueante = None
                    st.session_state.cliente = encontrado
                st.rerun()
            else:
                st.info("Cliente nuevo. Completa sus datos abajo.")
                st.session_state.cliente = {"telefono": telefono.strip(), "nombre": ""}
                st.rerun()
        return

    tipo = cliente.get("m_tipos_cliente") or {}
    col_nombre, col_cerrar = st.columns([3, 1], vertical_alignment="center")
    col_nombre.markdown(f"##### {cliente.get('nombre') or 'Cliente nuevo'}")

    detalle = [cliente.get("telefono", ""),
               f"{tipo.get('segmento','')} {tipo.get('nombre','')}".strip()]
    documento = _documento_texto(cliente)
    if documento:
        detalle.append(documento)
    col_nombre.caption(" · ".join(d for d in detalle if d))

    with col_cerrar:
        _boton_cerrar_negociacion()

    # Se abre solo si al cliente le falta el nombre: así el asesor ve de
    # entrada lo que tiene que completar.
    with st.expander("Editar datos del cliente",
                     expanded=not (cliente.get("nombre") or "").strip()):
        nombre = st.text_input("Nombre", value=cliente.get("nombre") or "")

        tipos = db.tipos_cliente()
        etiquetas = [f"{t['segmento']} · {t['nombre']}" for t in tipos]
        actual = next((i for i, t in enumerate(tipos)
                       if t["id_tipo_cliente"] == cliente.get("id_tipo_cliente")), None)
        elegido = st.selectbox("Tipo de cliente", etiquetas, index=actual,
                               placeholder="Selecciona")

        # Documento: opcional. El asesor puede seguir sin llenarlo, pero si lo
        # llena se valida el formato para que no entre basura a la base.
        col_tipo_doc, col_num_doc = st.columns([1, 1.6])
        tipos_doc = ["DNI", "RUC", "CE", "PASAPORTE"]
        indice_doc = (tipos_doc.index(cliente["tipo_documento"])
                      if cliente.get("tipo_documento") in tipos_doc else None)
        tipo_documento = col_tipo_doc.selectbox(
            "Tipo de documento", tipos_doc, index=indice_doc,
            placeholder="Opcional", key="sel_tipo_doc",
        )
        numero_documento = col_num_doc.text_input(
            "N° de documento", value=cliente.get("numero_documento") or "",
            placeholder="Opcional", key="num_doc",
        )
        st.caption("El documento no es obligatorio para cotizar, pero sale en el PDF.")

        if st.button("Guardar cliente"):
            error = _validar_documento(tipo_documento, numero_documento)
            if error:
                st.error(error)
                return

            datos = {"nombre": nombre}
            if elegido:
                datos["id_tipo_cliente"] = tipos[etiquetas.index(elegido)]["id_tipo_cliente"]

            # Se envían siempre los dos campos: así también se puede borrar
            # un documento cargado por error.
            datos["tipo_documento"] = tipo_documento or None
            datos["numero_documento"] = numero_documento.strip() or None

            try:
                if cliente.get("id_cliente"):
                    st.session_state.cliente = db.actualizar_cliente(
                        cliente["id_cliente"], datos)
                else:
                    datos["telefono"] = cliente["telefono"]
                    st.session_state.cliente = db.crear_cliente(datos)
            except Exception as e:
                st.error(_error_cliente(e))
                return

            st.success("Guardado.")
            st.rerun()


def _documento_texto(cliente) -> str:
    """Documento en una línea, si el cliente lo tiene."""
    tipo = cliente.get("tipo_documento")
    numero = cliente.get("numero_documento")
    return f"{tipo} {numero}" if tipo and numero else ""


def _validar_documento(tipo, numero) -> str | None:
    """Revisa el documento antes de guardarlo. Devuelve el error o None.

    Los dos campos son opcionales, pero si se llena uno hay que llenar el
    otro: la base no acepta un tipo sin número ni al revés.
    """
    numero = (numero or "").strip()

    if not tipo and not numero:
        return None
    if tipo and not numero:
        return f"Escribe el número de {tipo} o deja vacío el tipo de documento."
    if numero and not tipo:
        return "Elige el tipo de documento o borra el número."

    if tipo == "DNI" and not (numero.isdigit() and len(numero) == 8):
        return "El DNI debe tener 8 dígitos."
    if tipo == "RUC" and not (numero.isdigit() and len(numero) == 11):
        return "El RUC debe tener 11 dígitos."
    return None


def _error_cliente(e) -> str:
    """Traduce los errores de la base a algo entendible."""
    detalle = str(e)
    if "uq_cliente_documento" in detalle:
        return "Ese documento ya está registrado en otro cliente."
    if "chk_cliente_dni" in detalle:
        return "El DNI debe tener 8 dígitos."
    if "chk_cliente_ruc" in detalle:
        return "El RUC debe tener 11 dígitos."
    if "uq_cliente_telefono" in detalle:
        return "Ese teléfono ya está registrado en otro cliente."
    return f"No se pudo guardar: {e}"


def _boton_cerrar_negociacion():
    """Cierra la negociación como perdida, pidiendo el motivo.

    No aparece si la negociación ya está ganada o si todavía no existe.
    """
    negociacion = st.session_state.negociacion
    if not negociacion or negociacion.get("estado") == "ganada":
        return

    with st.popover("Cerrar", width="stretch",
                    help="Dar por finalizada esta negociación"):
        motivos = db.motivos_perdida()
        if not motivos:
            st.caption("No hay motivos configurados en m_motivos_perdida.")
            return

        nombres = [m["nombre"] for m in motivos]
        elegido = st.selectbox("¿Por qué se cierra?", nombres, index=None,
                               placeholder="Elige el motivo", key="motivo_cierre")

        st.caption("La negociación queda como perdida y sus cotizaciones, rechazadas.")

        if st.button("Confirmar cierre", type="primary", width="stretch",
                     disabled=not elegido, key="btn_confirmar_cierre"):
            id_motivo = motivos[nombres.index(elegido)]["id_motivo_perdida"]
            try:
                db.cerrar_negociacion(negociacion["id_negociacion"], id_motivo)
            except Exception as e:
                st.error(f"No se pudo cerrar: {e}")
                return
            st.session_state.negociacion = None
            st.session_state.cliente = None
            st.session_state.materiales = []
            st.session_state.version_tabla += 1
            _limpiar_resultados()
            st.rerun()


def _ubicacion():
    """Ubicación de la obra.

    Hay dos caminos, y el sistema usa el primero que encuentre:
      1. Coordenadas (link de Maps o lat/lon) -> reglas 1.x, por distancia.
      2. Departamento, provincia y distrito   -> reglas 2.x, por zona.

    El segundo es para los clientes que no quieren pasar su ubicación.
    """
    st.markdown("**Ubicación de la obra**")

    texto = st.text_input(
        "Link de Google Maps o coordenadas",
        value=st.session_state.ubicacion_texto,
        placeholder="https://www.google.com/maps/... o -8.0470, -79.0499",
        label_visibility="collapsed",
    )
    if texto != st.session_state.ubicacion_texto:
        st.session_state.ubicacion_texto = texto
        _limpiar_resultados()

    coords = extraer_coordenadas(texto)

    if texto and coords is None:
        st.warning("No se reconocen las coordenadas. Pega el link completo de Google Maps.")

    elif coords:
        # Con coordenadas, el distrito lo deduce la base a partir de los
        # límites distritales. Así la negociación queda con su zona correcta.
        geo = db.distrito_de_coordenadas(coords[0], coords[1])

        if geo:
            st.session_state.id_distrito = geo["id_distrito"]
            st.session_state.id_provincia = geo["id_provincia"]
            distrito = (geo["distrito"] or "").replace("_", " ").title()
            provincia = (geo["provincia"] or "").title()
            departamento = (geo["departamento"] or "").title()
            st.caption(f"📍 {distrito} · {provincia} · {departamento} "
                       "· se buscará por distancia")
            if not geo.get("con_cobertura"):
                st.warning(f"{distrito} está fuera de las zonas que atendemos. "
                           "Igual se puede cotizar, pero quizá no haya ferreterías cerca.")
            return

        # El punto no cae en ningún distrito cargado: se pide a mano
        st.caption(f"📍 {coords[0]:.6f}, {coords[1]:.6f} · no se identificó "
                   "el distrito. Elígelo para que la negociación quede en su zona:")
        _selectores_geografia()
        return

    # --- Sin coordenadas: se elige la zona a mano
    st.caption("Sin ubicación exacta. Elige la zona del cliente:")
    _selectores_geografia()


def _selectores_geografia():
    # Solo se ofrecen los distritos con cobertura: son donde hay ferreterías
    distritos = db.catalogo_distritos()
    if not distritos:
        st.warning("No hay distritos con cobertura configurados. "
                   "Márcalos con con_cobertura = true en m_distritos.")
        return

    guardado = next((d for d in distritos
                     if d["id_distrito"] == st.session_state.id_distrito), None)

    # Departamento
    departamentos = sorted({d["departamento"] for d in distritos if d["departamento"]})
    indice_dep = (departamentos.index(guardado["departamento"])
                  if guardado and guardado["departamento"] in departamentos else None)
    departamento = st.selectbox("Departamento", departamentos, index=indice_dep,
                                placeholder="Selecciona", key="sel_departamento")

    # Provincia: solo las de ese departamento
    provincias = sorted({d["provincia"] for d in distritos
                         if d["departamento"] == departamento and d["provincia"]})
    indice_prov = (provincias.index(guardado["provincia"])
                   if guardado and guardado["provincia"] in provincias else None)
    provincia = st.selectbox("Provincia", provincias, index=indice_prov,
                             placeholder="Selecciona", disabled=not departamento,
                             key="sel_provincia")

    # Distrito: solo los de esa provincia
    opciones = [d for d in distritos if d["provincia"] == provincia
                and d["departamento"] == departamento]
    nombres = [d["distrito"].replace("_", " ") for d in opciones]
    indice_dist = (nombres.index(guardado["distrito"].replace("_", " "))
                   if guardado and guardado["distrito"].replace("_", " ") in nombres else None)
    distrito = st.selectbox("Distrito", nombres, index=indice_dist,
                            placeholder="Selecciona", disabled=not provincia,
                            key="sel_distrito")

    # Guardar la elección
    nuevo_id = opciones[nombres.index(distrito)]["id_distrito"] if distrito else None
    nueva_provincia = opciones[0]["id_provincia"] if opciones else None

    if nuevo_id != st.session_state.id_distrito:
        st.session_state.id_distrito = nuevo_id
        st.session_state.id_provincia = nueva_provincia
        _limpiar_resultados()

    if not distritos:
        st.warning("No hay distritos con cobertura configurados. "
                   "Márcalos con con_cobertura = true en m_distritos.")


def _lista_materiales():
    """Barra para agregar arriba y las filas ya agregadas abajo.

    Se dejó de usar `st.data_editor` a propósito: la tabla editable guarda su
    propio estado y entraba en conflicto con los datos que le pasábamos, así
    que las celdas se borraban al escribir. Con campos sueltos, cada uno tiene
    su identidad y eso no ocurre.
    """
    st.markdown("**Lista de materiales**")

    catalogo = db.catalogo_skus()
    _barra_agregar(catalogo)

    if not st.session_state.materiales:
        st.caption("Agrega el primer producto con la barra de arriba.")
        return

    _encabezado_lista()
    for indice, item in enumerate(list(st.session_state.materiales)):
        _fila_material(indice, item)

    _pie_lista()


def _barra_agregar(catalogo):
    """Producto, marca, unidad y cantidad. Al agregar, la barra se vacía sola."""
    productos = sorted({c["producto"] for c in catalogo})
    version = st.session_state.version_tabla

    with st.container(border=True):
        col_prod, col_marca, col_unidad, col_cant, col_boton = \
            st.columns([2.2, 1.3, 1.2, 0.8, 1])

        producto = col_prod.selectbox(
            "Producto", productos, index=None, placeholder="Escribe para buscar…",
            key=f"nuevo_producto_{version}",
        )

        # Las marcas se filtran según el producto elegido
        marcas = sorted({c["marca"] for c in catalogo if c["producto"] == producto}) \
            if producto else []
        marca = col_marca.selectbox(
            "Marca", marcas, index=None, placeholder="La más barata",
            key=f"nueva_marca_{version}", disabled=not producto,
            help="Vacío = se toma la más barata de cada ferretería.",
        )

        # La unidad depende del producto (y de la marca, si la eligió).
        # Casi siempre hay una sola: en ese caso se muestra como dato, no como
        # lista. Un desplegable con una sola opción conservaría el valor vacío
        # que tenía antes de elegir el producto.
        # Las unidades se ordenan por cobertura: primero la que más
        # ferreterías cotizan. Una unidad sin precios se puede elegir, pero
        # la lista avisa que nadie la cotiza.
        cobertura = {}
        for c in catalogo:
            if c["producto"] != producto:
                continue
            if marca and c["marca"] != marca:
                continue
            nombre = c["unidad_nombre"]
            cobertura[nombre] = cobertura.get(nombre, 0) + (c.get("n_sedes") or 0)

        unidades = sorted(cobertura, key=lambda u: (-cobertura[u], u)) if producto else []

        if len(unidades) == 1:
            unidad = unidades[0]
            col_unidad.markdown(
                "<div style='font-size:0.8rem;opacity:.7;margin-bottom:2px'>Unidad</div>"
                f"<div style='padding:7px 0'>{unidad}</div>",
                unsafe_allow_html=True,
            )
        elif len(unidades) > 1:
            def _etiqueta_unidad(nombre):
                sedes = cobertura.get(nombre, 0)
                if sedes == 0:
                    return f"{nombre} · sin precios"
                return f"{nombre} · {sedes} ferretería{'s' if sedes != 1 else ''}"

            unidad = col_unidad.selectbox(
                "Unidad", unidades, index=0,
                format_func=_etiqueta_unidad,
                key=f"nueva_unidad_{version}_{producto}_{marca or ''}",
                help="Cada unidad tiene su propio precio. Si la ferretería no "
                     "cotiza en esa unidad, no compite por esa línea.",
            )
        else:
            unidad = None
            col_unidad.markdown(
                "<div style='font-size:0.8rem;opacity:.7;margin-bottom:2px'>Unidad</div>"
                "<div style='padding:7px 0;opacity:.5'>—</div>",
                unsafe_allow_html=True,
            )

        cantidad = col_cant.number_input(
            "Cant.", min_value=0.01, step=1.0, value=1.0, format="%.2f",
            key=f"nueva_cantidad_{version}",
        )

        col_boton.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        falta_unidad = bool(unidades) and unidad is None
        if col_boton.button("＋ Agregar", width="stretch",
                            disabled=not producto or falta_unidad):
            st.session_state.materiales.append({
                "producto": producto,
                "marca": marca,
                "unidad": unidad,
                "cantidad": float(cantidad),
                "precio_negociado": None,
                "motivo": None,
                "autorizado_por": None,
            })
            # Subir la versión limpia la barra para el siguiente producto
            st.session_state.version_tabla += 1
            _limpiar_resultados()
            st.rerun()


def _encabezado_lista():
    cols = st.columns([2.4, 1.4, 0.8, 1.1, 0.4])
    etiquetas = ["Producto", "Marca y unidad", "Cant.", "Precio neg.", ""]
    for col, etiqueta in zip(cols, etiquetas):
        col.caption(etiqueta)


def _fila_material(indice, item):
    """Una línea de la canasta. Solo cantidad y precio son editables."""
    col_prod, col_marca, col_cant, col_precio, col_borrar = \
        st.columns([2.4, 1.4, 0.8, 1.1, 0.4], vertical_alignment="center")

    col_prod.markdown(item["producto"])
    detalle = [item.get("marca") or "La más barata"]
    if item.get("unidad"):
        detalle.append(item["unidad"])
    col_marca.caption(" · ".join(detalle))

    cantidad = col_cant.number_input(
        "Cantidad", min_value=0.01, step=1.0, value=float(item["cantidad"]),
        format="%.2f", label_visibility="collapsed", key=f"cant_{indice}",
    )
    if cantidad != item["cantidad"]:
        st.session_state.materiales[indice]["cantidad"] = float(cantidad)
        _limpiar_resultados()

    precio = col_precio.number_input(
        "Precio", min_value=0.0, step=0.10,
        value=float(item["precio_negociado"]) if item["precio_negociado"] else None,
        format="%.2f", label_visibility="collapsed", placeholder="—",
        key=f"precio_{indice}",
    )
    if precio != item["precio_negociado"]:
        st.session_state.materiales[indice]["precio_negociado"] = precio
        _limpiar_resultados()

    if col_borrar.button("🗑", key=f"borrar_{indice}", help="Quitar de la lista"):
        st.session_state.materiales.pop(indice)
        _limpiar_resultados()
        st.rerun()


def _pie_lista():
    """Total referencial y el botón de cotizar."""
    catalogo = db.catalogo_skus()
    lineas, _ = _armar_lineas(catalogo)
    monto = monto_referencial(lineas, db.precios_referenciales()) if lineas else 0

    st.divider()
    col_total, col_boton = st.columns([1.4, 1], vertical_alignment="center")
    col_total.caption(f"{len(st.session_state.materiales)} producto(s) · referencial")
    col_total.markdown(f"### {config.soles(monto)}")

    if col_boton.button("🔄 Buscar ferreterías", type="primary", width="stretch"):
        _recotizar()


def _armar_lineas(catalogo) -> tuple[list[dict], list[str]]:
    """Convierte la lista del asesor en lo que espera la lógica de cotización.

    Si la línea trae marca, se busca ese producto con esa marca.
    Si no, se admiten todas las marcas del producto y después se elige la
    más barata en cada ferretería.
    """
    lineas, errores = [], []

    for i, item in enumerate(st.session_state.materiales, start=1):
        producto = item.get("producto")
        marca = item.get("marca")
        unidad = item.get("unidad")
        cantidad = item.get("cantidad")

        if not producto:
            errores.append(f"Fila {i}: falta el producto.")
            continue
        if not cantidad or float(cantidad) <= 0:
            errores.append(f"Fila {i}: la cantidad debe ser mayor a 0.")
            continue

        precio_negociado = item.get("precio_negociado")

        opciones = [c for c in catalogo if c["producto"] == producto]
        if not opciones:
            errores.append(
                f"Fila {i}: «{producto}» ya no está en el catálogo. Quítalo de la lista.")
            continue

        if marca:
            opciones = [c for c in opciones if c["marca"] == marca]
            if not opciones:
                disponibles = sorted({c["marca"] for c in catalogo
                                      if c["producto"] == producto})
                errores.append(
                    f"Fila {i}: no hay precios de {producto} marca {marca}. "
                    f"Marcas disponibles: {', '.join(disponibles)}."
                )
                continue

        if unidad:
            por_unidad = [c for c in opciones if c["unidad_nombre"] == unidad]
            if not por_unidad:
                errores.append(
                    f"Fila {i}: {producto} no está registrado en {unidad}.")
                continue
            opciones = por_unidad

        lineas.append({
            "id_producto": opciones[0]["id_producto"],
            "descripcion": producto
                           + (f" · {marca}" if marca else "")
                           + (f" · {unidad}" if unidad else ""),
            "producto": producto,
            "marca": marca,
            "unidad": unidad,
            "cantidad": float(cantidad),
            "precio_manual": float(precio_negociado) if precio_negociado else None,
            "motivo": (item.get("motivo") or "").strip() or None,
            "autorizado_por": (item.get("autorizado_por") or "").strip() or None,
            "skus_posibles": [c["id_sku"] for c in opciones],
        })

    return lineas, errores


def _validar_cliente() -> list[str]:
    """El cliente debe estar completo antes de cotizar: su nombre y tipo
    salen en el PDF y en los reportes."""
    cliente = st.session_state.cliente
    faltan = []

    if not cliente:
        return ["Completa los datos del cliente antes de cotizar."]
    if not cliente.get("id_cliente"):
        faltan.append("guarda el cliente (botón «Guardar cliente»)")
    if not (cliente.get("nombre") or "").strip():
        faltan.append("el nombre del cliente")
    tiene_tipo = cliente.get("id_tipo_cliente") or cliente.get("m_tipos_cliente")
    if not tiene_tipo:
        faltan.append("el tipo de cliente (B2B o B2C)")

    if not faltan:
        return []
    return ["Antes de cotizar: " + ", ".join(faltan) + "."]


def _zona_de_la_obra(coords, id_distrito, sedes) -> int | None:
    """Zona donde está la obra, para saber qué reglas aplicar."""
    if id_distrito:
        return db.zona_de_distrito(id_distrito)

    if coords:
        cercanas = sedes_cercanas(coords[0], coords[1], sedes, top_n=1)
        if cercanas:
            return db.zona_de_distrito(cercanas[0].get("id_distrito"))

    return None


def _recotizar():
    catalogo = db.catalogo_skus()
    # Primero el cliente, después los materiales
    errores = _validar_cliente()
    lineas, errores_lineas = _armar_lineas(catalogo)
    errores += errores_lineas

    if errores:
        st.error("Revisa la lista:\n\n" + "\n".join(f"- {e}" for e in errores))
        return
    if not lineas:
        st.warning("Agrega al menos un producto.")
        return

    coords = extraer_coordenadas(st.session_state.ubicacion_texto)
    negociacion = st.session_state.negociacion or {}

    # Sin coordenadas hace falta el distrito: sin uno de los dos no hay
    # forma de saber qué ferreterías compiten.
    id_distrito = st.session_state.id_distrito or negociacion.get("id_distrito")
    id_provincia = st.session_state.id_provincia

    if coords is None and id_distrito is None:
        st.error("Indica la ubicación: pega el link de Maps o elige "
                 "departamento, provincia y distrito.")
        return

    # La provincia se saca del distrito elegido
    if coords is None and id_provincia is None:
        distrito = next((d for d in db.catalogo_distritos()
                         if d["id_distrito"] == id_distrito), None)
        id_provincia = distrito["id_provincia"] if distrito else None

    monto = monto_referencial(lineas, db.precios_referenciales())

    # Las reglas pueden variar por zona: se piden las de la zona de la obra.
    # Con coordenadas, mientras no tengamos los límites distritales, se usa
    # la zona de la sede más cercana como aproximación.
    sedes = db.catalogo_sedes()
    id_zona = _zona_de_la_obra(coords, id_distrito, sedes)
    regla = elegir_regla(monto, coords is not None, db.reglas_cotizacion(id_zona))

    if regla is None:
        st.error("No hay una regla configurada para este monto. Revisa m_reglas_cotizacion.")
        return

    candidatas = sedes_candidatas(
        regla, sedes,
        coordenadas=coords,
        id_distrito=id_distrito,
        id_provincia=id_provincia,
        top_n=config.TOP_N_SEDES,
    )

    if not candidatas:
        if regla["alcance"] == "radio":
            st.warning(f"Ninguna ferretería quedó a {regla['radio_km']} km o menos. "
                       "Revisa la ubicación o usa departamento y distrito.")
        else:
            st.warning(f"No hay ferreterías registradas en ese {regla['alcance']}.")
        return

    todos_skus = [s for l in lineas for s in l["skus_posibles"]]
    precios = db.precios_de(todos_skus, [c["id_sede"] for c in candidatas])

    st.session_state.resultados = cotizar_en_sedes(lineas, candidatas, precios)
    st.session_state.regla = regla
    st.session_state.monto_ref = monto
    st.session_state.sede_elegida = None


# ---------------------------------------------------------------- columna 3
def _bloque_ferreterias(usuario):
    st.markdown("##### Ferreterías")

    _tarjeta_ultima_cotizacion()

    resultados = st.session_state.resultados
    if not resultados:
        st.info("Arma la lista de materiales y presiona «Buscar ferreterías».")
        return

    regla = st.session_state.regla
    alcance = (f"radio {regla['radio_km']} km" if regla["alcance"] == "radio"
               else f"por {regla['alcance']}")
    st.caption(f"Regla {regla['codigo']} · {alcance} · "
               f"canasta referencial {config.soles(st.session_state.monto_ref)}")

    maximo = max(r["n_faltantes"] for r in resultados)
    limite = 0
    if maximo > 0:
        limite = st.slider("Mostrar hasta … productos faltantes", 0, maximo,
                           config.FALTANTES_POR_DEFECTO)

    visibles = [r for r in resultados if r["n_faltantes"] <= limite]
    if not visibles:
        st.warning("Ninguna ferretería tiene la canasta completa. Sube el filtro para ver las parciales.")
        return

    for resultado in visibles:
        _tarjeta_ferreteria(resultado)

    if st.session_state.sede_elegida:
        _resumen_y_pdf(usuario)


def _tarjeta_ultima_cotizacion():
    """Con qué ferretería y por cuánto se cotizó la última vez.

    Se comprueba que pertenezca a la negociación abierta: si no, al crear una
    negociación nueva seguiría mostrando la cotización de la anterior.
    """
    ultima = st.session_state.cotizacion_actual
    if not ultima:
        return

    actual = (st.session_state.negociacion or {}).get("id_negociacion")
    if ultima.get("id_negociacion") != actual:
        st.session_state.cotizacion_actual = None
        return

    with st.container(border=True):
        st.caption(f"Última cotización · {config.codigo_cotizacion(ultima['id_cotizacion'])} "
                   f"v{ultima['version']}")
        st.markdown(f"**{ultima.get('ferreteria') or 'Ferretería no registrada'}** · "
                    f"{config.soles(ultima.get('monto_total_sol'))}")
        detalles = []
        if ultima.get("sede_codigo"):
            detalles.append(ultima["sede_codigo"])
        detalles.append(f"vence {config.vence_texto(ultima.get('fecha_vencimiento'))}")
        st.caption(" · ".join(detalles))


def _tarjeta_ferreteria(r):
    elegida = st.session_state.sede_elegida == r["id_sede"]

    with st.container(border=True):
        izq, der = st.columns([2, 1])
        izq.markdown(f"**{r['ferreteria']}**")
        izq.caption(r["sede"])
        der.markdown(f"**{config.soles(r['monto'])}**")

        ultima = st.session_state.cotizacion_actual or {}
        if ultima.get("id_sede") == r["id_sede"]:
            st.caption(":orange[↺ Ferretería de la última cotización]")

        detalles = []
        if r["distancia_km"] is not None:
            detalles.append(f"{r['distancia_km']} km")
        if r["canasta_completa"]:
            detalles.append("canasta completa")
        else:
            detalles.append(f"falta: {', '.join(r['faltantes'])}")
        st.caption(" · ".join(detalles))

        with st.expander("Ver detalle"):
            por_sku = {c["id_sku"]: c for c in db.catalogo_skus()}
            filas = [{
                "Producto": por_sku.get(d["id_sku"], {}).get("producto", d["descripcion"]),
                "Marca": por_sku.get(d["id_sku"], {}).get("marca", ""),
                "Cantidad": d["cantidad"],
                "Precio": d["precio_manual"] or d["precio_lista"],
                "Subtotal": d["subtotal"],
            } for d in r["detalle"]]
            st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")

        if st.button("Elegir esta ferretería", key=f"elegir_{r['id_sede']}",
                     width="stretch", type="primary" if elegida else "secondary"):
            st.session_state.sede_elegida = r["id_sede"]
            st.rerun()


def _resumen_y_pdf(usuario):
    elegida = next(r for r in st.session_state.resultados
                   if r["id_sede"] == st.session_state.sede_elegida)
    cliente = st.session_state.cliente or {}
    id_cliente = cliente.get("id_cliente")

    # Las dos listas se juntan: el asesor elige entre todas, sean descuento
    # inmediato o bono posterior.
    en_cotizacion = db.promociones_de_sede(elegida["id_sede"], elegida["monto"], id_cliente)
    post_venta = db.bonos_post_venta(elegida["id_sede"], elegida["monto"], id_cliente)
    promos = [{**p, "momento": "cotizacion"} for p in en_cotizacion] + \
             [{**p, "momento": "venta"} for p in post_venta]

    with st.container(border=True):
        st.markdown(f"**{elegida['ferreteria']}**")

        decididas = _bloque_promociones(promos)
        descuento = sum(float(p["beneficio"]) for p in decididas
                        if p["aplicada"] and p["modalidad"] == "descuento"
                        and p["momento"] == "cotizacion")
        devolucion = sum(float(p["beneficio"]) for p in decididas
                         if p["aplicada"] and p["modalidad"] == "devolucion")

        flete = _bloque_flete()
        total = elegida["monto"] - descuento + flete

        st.divider()
        st.markdown(f"Productos · {config.soles(elegida['monto'])}")
        if descuento:
            aplicados = sum(1 for p in decididas
                            if p["aplicada"] and p["modalidad"] == "descuento")
            st.markdown(f"Descuentos aplicados ({aplicados}) · "
                        f":green[−{config.soles(descuento)}]")
        if flete:
            st.markdown(f"Flete · {config.soles(flete)}")

        st.markdown(f"### Paga hoy: {config.soles(total)}")
        if descuento:
            st.caption(f"Sin promociones pagaría {config.soles(elegida['monto'] + flete)}")
        if devolucion:
            st.info(f"Además recibirá {config.soles(devolucion)} después de comprar. "
                    "El monto exacto se calcula sobre lo que pague.")

        pdf = _pdf_de_esta_negociacion()

        if pdf is None:
            if st.button("Generar cotización PDF", type="primary", width="stretch",
                         key="btn_generar"):
                _guardar_y_generar_pdf(usuario, elegida, decididas,
                                       descuento, total, devolucion)
        else:
            st.success(f"{pdf['codigo']} generada.")
            st.download_button(
                f"⬇ Descargar {pdf['codigo']}",
                data=pdf["bytes"], file_name=pdf["nombre"],
                mime="application/pdf", width="stretch", key="btn_descargar_pdf",
            )
            st.caption("Para emitir otra versión, cambia la lista y recotiza.")


def _descripcion_bono(promo) -> str:
    """Qué recibe el cliente, dicho como se lo explicaría el asesor."""
    monto = config.soles(promo["beneficio"])
    if promo["modalidad"] == "descuento":
        return f"Se le descuentan {monto} si compra esta cotización"
    return f"Recibirá {monto} después de realizar la compra"


def _bloque_promociones(promos: list[dict]) -> list[dict]:
    """Deja que el asesor elija qué bonos darle al cliente.

    Hay dos grupos con reglas distintas:
      acumulables  se pueden dar todos, se suman
      excluyentes  solo uno, porque compiten entre sí

    Cualquiera se puede dejar sin aplicar, incluidos los automáticos.
    Se devuelven TODOS con su decisión: los descartados también se guardan,
    para saber después qué se ofreció y qué se aceptó.
    """
    if not promos:
        st.caption("Este cliente no tiene bonos activos.")
        return []

    cantidad = len(promos)
    st.markdown(f"**Tienes {cantidad} bono{'s' if cantidad != 1 else ''} "
                f"activo{'s' if cantidad != 1 else ''} para este cliente**")

    # Apaga todo de golpe. Se escriben los valores de cada campo en vez de
    # usar una bandera: así el estado de la pantalla es siempre el real.
    if st.button("No dar ninguno", width="stretch", key="btn_sin_promos"):
        for promo in promos:
            st.session_state[f"promo_{promo['id_promocion']}"] = False
        st.session_state["radio_promos"] = "Ninguno de estos"
        st.rerun()

    acumulables = [p for p in promos if p.get("acumulable")]
    excluyentes = [p for p in promos if not p.get("acumulable")]
    decididas = []

    # --- Los que compiten entre sí: solo uno
    if excluyentes:
        etiquetas = {}
        for promo in sorted(excluyentes, key=lambda x: -float(x["beneficio"])):
            etiquetas[f"{promo['nombre']} · {_descripcion_bono(promo)}"] = promo
        opciones = list(etiquetas) + ["Ninguno de estos"]

        if len(excluyentes) > 1:
            st.caption("Solo uno de estos")
        # Sin "index": con una key, el valor guardado es el que manda. Pasar
        # index además haría que la elección del asesor se pise en cada clic.
        elegida = st.radio("Bonos excluyentes", opciones,
                           label_visibility="collapsed", key="radio_promos")

        for etiqueta, promo in etiquetas.items():
            decididas.append({**promo, "aplicada": etiqueta == elegida})

    # --- Los que se pueden dar juntos
    if acumulables:
        if excluyentes:
            st.caption("Estos se pueden dar además")
        for promo in acumulables:
            marcada = st.checkbox(
                f"{promo['nombre']} · {_descripcion_bono(promo)}",
                value=promo.get("aplicacion") != "manual",
                key=f"promo_{promo['id_promocion']}",
            )
            decididas.append({**promo, "aplicada": marcada})

    return decididas


def _pdf_de_esta_negociacion():
    """El PDF en memoria, solo si pertenece a la negociación abierta.

    Sin esta comprobación, al cambiar de negociación seguiría apareciendo el
    botón de descarga del documento anterior.
    """
    pdf = st.session_state.get("pdf_generado")
    if not pdf:
        return None

    actual = (st.session_state.negociacion or {}).get("id_negociacion")
    if pdf.get("id_negociacion") != actual:
        st.session_state.pdf_generado = None
        return None
    return pdf


def _bloque_flete() -> float:
    """Costo de entrega. Solo se cobra cuando la entrega lo exige.

    Está apagado por defecto: la mayoría de las entregas no lo llevan, y un
    campo siempre visible invita a llenarlo sin necesidad.
    """
    cobrar = st.checkbox("Cobrar flete", value=bool(st.session_state.flete_monto),
                         help="Actívalo solo si esta entrega tiene costo de envío.")

    if not cobrar:
        if st.session_state.flete_monto:
            st.session_state.flete_monto = 0.0
        return 0.0

    monto = st.number_input(
        "Monto del flete", min_value=0.0, step=10.0, format="%.2f",
        value=float(st.session_state.flete_monto or 0.0),
        key="input_flete_monto",
    )
    st.session_state.flete_monto = float(monto or 0)
    return float(monto or 0)


def _guardar_y_generar_pdf(usuario, elegida, promociones, descuento, total, devolucion):
    """Guarda la cotización en la base y arma el PDF."""
    cliente = st.session_state.cliente
    negociacion = st.session_state.negociacion
    coords = extraer_coordenadas(st.session_state.ubicacion_texto)
    ticket = st.session_state.ticket_actual

    # Sin ticket no se puede saber de qué conversación salió la cotización
    if not ticket:
        st.error("Ingresa el ID CRM (arriba del cliente) antes de generar la cotización.")
        return

    # Si es una negociación nueva, primero se crea
    if negociacion is None:
        try:
            # La zona la deduce la base a partir del distrito de la obra.
            # Se manda la del asesor solo como respaldo, para cuando no hay
            # distrito conocido.
            negociacion = db.crear_negociacion({
                "id_cliente": cliente["id_cliente"],
                "id_usuario": usuario["id_usuario"],
                "id_zona": usuario.get("id_zona"),
                "id_distrito": st.session_state.id_distrito
                               or cliente.get("id_distrito_origen"),
            })
            st.session_state.negociacion = negociacion
        except Exception as e:
            detalle = str(e)
            if "ya tiene una negociación activa" in detalle:
                st.error(detalle.split("CONTEXT")[0].strip())
            else:
                st.error(f"No se pudo crear la negociación: {e}")
            return

    # El primer ticket de la negociación es el de origen; los siguientes,
    # de seguimiento (el cliente volvió por otra conversación).
    ya_registrados = [t["ticket"] for t in _tickets_de(negociacion)]
    if ticket not in ya_registrados:
        try:
            db.agregar_ticket(negociacion["id_negociacion"], ticket,
                              "origen" if not ya_registrados else "seguimiento")
        except Exception as e:
            st.error(f"No se pudo registrar el ID CRM: {e}")
            return

    # Detalle: lo que se cotizó en la ferretería elegida
    lineas = [{
        "id_sku": d["id_sku"],
        "cantidad": d["cantidad"],
        "precio_unitario": d["precio_lista"],
        "precio_modificado": d["precio_manual"],
        "motivo_modificacion": d.get("motivo"),
        "autorizado_por": d.get("autorizado_por"),
        "id_precio": d["id_precio"],
    } for d in elegida["detalle"]]

    # Todas las ferreterías que compitieron, para el análisis
    ferreterias = [{
        "id_sede": r["id_sede"],
        "distancia_km": r["distancia_km"],
        "canasta_completa": r["canasta_completa"],
        "monto_canasta": r["monto"] if r["canasta_completa"] else None,
        "ranking": i + 1 if r["canasta_completa"] else None,
        "elegida": r["id_sede"] == elegida["id_sede"],
    } for i, r in enumerate(st.session_state.resultados)]

    # Se guardan las aplicadas y las omitidas: la comparación entre lo que se
    # ofreció y lo que se aceptó es lo que alimenta v_promociones_omitidas.
    promos_json = [{
        "id_promocion": p["id_promocion"],
        "modalidad": p["modalidad"],
        "tipo": p.get("tipo") or "porcentaje",
        "monto_beneficio": float(p["beneficio"]),
        "financiado_por": p.get("financiado_por") or "siderexpress",
        "aplicada": p["aplicada"],
    } for p in promociones]

    cabecera = {
        "id_negociacion": negociacion["id_negociacion"],
        "id_sede": elegida["id_sede"],
        "id_regla": st.session_state.regla.get("id_regla"),
        "monto_referencial": st.session_state.monto_ref,
        "distancia_km": elegida["distancia_km"],
        "latitud": coords[0] if coords else None,
        "longitud": coords[1] if coords else None,
        "id_distrito": st.session_state.id_distrito or negociacion.get("id_distrito"),
        "ticket": ticket,
        "monto_flete": st.session_state.flete_monto or 0,
    }

    try:
        id_cotizacion = db.guardar_cotizacion(cabecera, lineas, promos_json, ferreterias)
    except Exception as e:
        st.error(f"No se pudo guardar la cotización: {e}")
        return

    # ------------------------------------------------------------- el PDF ---
    por_sku = {c["id_sku"]: c for c in db.catalogo_skus()}

    # Las fechas se leen de la base, que ya calculó el vencimiento en hora de
    # Lima. Calcularlas aquí daría la hora del servidor, que está en UTC.
    guardada = next((c for c in db.cotizaciones_de(negociacion["id_negociacion"])
                     if c["id_cotizacion"] == id_cotizacion), None)
    tipo = (cliente.get("m_tipos_cliente") or {})
    documento = " ".join(x for x in [cliente.get("tipo_documento"),
                                     cliente.get("numero_documento")] if x)

    datos = {
        "logo": config.LOGO,
        "cotizacion": {
            "codigo": config.codigo_cotizacion(id_cotizacion),
            "fecha": config.fecha_hora((guardada or {}).get("fecha")),
            "vence": config.vence_texto((guardada or {}).get("fecha_vencimiento")),
        },
        "cliente": {
            "nombre": cliente.get("nombre"),
            "telefono": cliente.get("telefono"),
            "documento": documento,
        },
        "ferreteria": {
            "nombre": elegida["ferreteria"],
            "sede": elegida["sede"],
            "distrito": elegida.get("distrito"),
        },
        # La marca sale del SKU que la lógica eligió, no de lo que escribió el
        # asesor: si dejó la marca vacía, el cliente igual debe saber cuál es.
        "productos": [{
            "descripcion": por_sku.get(d["id_sku"], {}).get("producto", d["descripcion"]),
            "marca": por_sku.get(d["id_sku"], {}).get("marca", ""),
            "unidad": por_sku.get(d["id_sku"], {}).get("unidad_nombre", ""),
            "cantidad": d["cantidad"],
            "precio": d["precio_manual"] or d["precio_lista"],
            "subtotal": d["subtotal"],
        } for d in elegida["detalle"]],
        "totales": {
            "subtotal": elegida["monto"],
            "descuento": descuento,
            "flete": st.session_state.flete_monto or 0,
            "total": total,
            "devolucion": devolucion,
        },
        "asesor": usuario["nombre"],
    }

    st.session_state.pdf_generado = {
        "bytes": generar_pdf(datos),
        "nombre": f"{config.codigo_cotizacion(id_cotizacion)}.pdf",
        "codigo": config.codigo_cotizacion(id_cotizacion),
        "id_negociacion": negociacion["id_negociacion"],
    }
    if guardada:
        st.session_state.cotizacion_actual = guardada
    actualizada = db.negociacion_por_id(negociacion["id_negociacion"])
    if actualizada:
        st.session_state.negociacion = actualizada
    st.success(f"Cotización {config.codigo_cotizacion(id_cotizacion)} guardada.")
    st.rerun()


# ---------------------------------------------------------------- la venta
def _bloque_venta(usuario):
    """Registrar la compra del cliente y validarla.

    Solo aparece si la negociación ya tiene al menos una cotización enviada:
    una venta siempre nace de una cotización.
    """
    negociacion = st.session_state.negociacion
    cotizaciones = db.cotizaciones_de(negociacion["id_negociacion"])
    vendibles = [c for c in cotizaciones
                 if c["estado"] in ("enviada", "aceptada", "vencida")]

    if not cotizaciones:
        return

    ventas = db.ventas_de(negociacion["id_negociacion"])
    activas = [v for v in ventas if v["estado"] != "anulada"]

    with st.container(border=True):
        st.markdown("##### Venta")

        # --- Ya hay una venta registrada
        if activas:
            for venta in activas:
                _tarjeta_venta(venta, usuario)
            return

        # --- Todavía no: se registra desde una cotización
        if not vendibles:
            st.caption("No hay cotizaciones disponibles para convertir en venta.")
            return

        etiquetas = {
            f"{config.codigo_cotizacion(c['id_cotizacion'])} · v{c['version']} · "
            f"{config.soles(c['monto_total_sol'])}": c
            for c in vendibles
        }
        elegida = st.selectbox("¿Qué cotización compró?", list(etiquetas))
        cotizacion = etiquetas[elegida]

        pagos = db.tipos_pago()
        nombres_pago = [p["nombre"] for p in pagos]
        pago = st.selectbox("¿Cómo pagó?", nombres_pago, index=None,
                            placeholder="Selecciona")

        col_tipo, col_num = st.columns(2)
        tipo_comprobante = col_tipo.selectbox("Comprobante", ["boleta", "factura"],
                                              index=None, placeholder="Opcional")
        numero = col_num.text_input("N° de comprobante", placeholder="B001-00123")
        url = st.text_input("Enlace del voucher", placeholder="Opcional por ahora")
        ticket_venta = st.text_input(
            "ID CRM donde llegó el comprobante",
            value=st.session_state.ticket_actual or "",
            help="Normalmente es el mismo de la cotización. Cámbialo si el "
                 "cliente pagó en otra conversación.",
        )

        st.caption("Se copian los productos de la cotización. "
                   "Si compró menos, se ajusta después de registrarla.")

        if st.button("Registrar venta", type="primary", width="stretch"):
            if not pago:
                st.warning("Indica cómo pagó el cliente.")
                return
            datos = {
                "id_cotizacion": cotizacion["id_cotizacion"],
                "id_tipo_pago": pagos[nombres_pago.index(pago)]["id_tipo_pago"],
                "tipo_comprobante": tipo_comprobante,
                "numero_comprobante": numero.strip() or None,
                "url_comprobante_pago": url.strip() or None,
                "ticket": ticket_venta.strip() or None,
            }
            try:
                id_venta = db.registrar_venta(datos)
                # El ticket del pago queda asociado como cierre de la negociación
                if ticket_venta.strip():
                    registrados = [t["ticket"] for t in _tickets_de(negociacion)]
                    if ticket_venta.strip() not in registrados:
                        db.agregar_ticket(negociacion["id_negociacion"],
                                          ticket_venta.strip(), "cierre")
            except Exception as e:
                st.error(f"No se pudo registrar la venta: {e}")
                return
            st.success(f"Venta registrada. Queda pendiente de validación.")
            st.rerun()


def _tarjeta_venta(venta, usuario):
    colores = {"pendiente_validacion": "orange", "validada": "green", "anulada": "red"}
    color = colores.get(venta["estado"], "gray")

    st.markdown(f"**{config.soles(venta['monto_total_sol'])}** · "
                f":{color}[{venta['estado'].replace('_', ' ')}]")
    detalles = [venta.get("numero_comprobante"), venta.get("tipo_comprobante")]
    st.caption(" · ".join(d for d in detalles if d) or "Sin comprobante")

    if venta["estado"] == "pendiente_validacion":
        if usuario["rol"] in ("supervisor", "master"):
            if st.button("Validar venta", key=f"validar_{venta['id_venta']}",
                         type="primary", width="stretch"):
                try:
                    db.validar_venta(venta["id_venta"])
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo validar: {e}")
        else:
            st.caption("Un supervisor debe validarla.")

    if venta["estado"] != "anulada":
        with st.expander("Anular venta"):
            motivo = st.text_input("Motivo", key=f"motivo_{venta['id_venta']}")
            if st.button("Anular", key=f"anular_{venta['id_venta']}"):
                try:
                    db.anular_venta(venta["id_venta"], motivo)
                    st.rerun()
                except Exception as e:
                    st.error(f"No se pudo anular: {e}")
