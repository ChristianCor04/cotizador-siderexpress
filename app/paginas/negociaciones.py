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
from logica.geo import extraer_coordenadas
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
}


def _preparar_memoria():
    for clave, valor in VALORES_INICIALES.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


def _limpiar_resultados():
    """Los montos quedan viejos si cambian materiales o ubicación."""
    st.session_state.resultados = []
    st.session_state.sede_elegida = None


# ===========================================================================
# PANTALLA
# ===========================================================================

def mostrar(usuario: dict):
    _preparar_memoria()

    col_lista, col_centro, col_ferreterias = st.columns([1.1, 2, 1.6], gap="medium")

    with col_lista:
        _bloque_lista(usuario)
    with col_centro:
        _bloque_cliente_y_materiales(usuario)
    with col_ferreterias:
        _bloque_ferreterias(usuario)


# ---------------------------------------------------------------- columna 1
def _bloque_lista(usuario):
    st.markdown("##### Negociaciones")

    buscar = st.text_input(
        "Buscar", placeholder="Teléfono o N° cotización",
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
    _limpiar_resultados()

    # Cargar la última cotización, si existe
    cotizaciones = db.cotizaciones_de(neg["id_negociacion"])
    if cotizaciones:
        ultima = cotizaciones[0]
        detalle = db.detalle_de_cotizacion(ultima["id_cotizacion"])
        st.session_state.materiales = [{
            "producto": d["producto"],
            "marca": d["marca"],
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
    st.session_state.version_tabla += 1
    _limpiar_resultados()
    st.rerun()


def _buscar(texto):
    texto = texto.strip()
    # Si son solo números y es corto, se asume número de cotización
    if texto.isdigit() and len(texto) <= 7:
        encontrado = db.buscar_por_codigo_cotizacion(int(texto))
        if encontrado:
            st.success(f"Cotización en {config.codigo_negociacion(encontrado['id_negociacion'])}")
        else:
            st.warning("No se encontró esa cotización.")
        return

    cliente = db.buscar_cliente_por_telefono(texto)
    if cliente:
        st.success(f"Cliente: {cliente['nombre']}")
    else:
        st.warning("Sin resultados. Usa ＋ para crear una negociación nueva.")


# ---------------------------------------------------------------- columna 2
def _bloque_cliente_y_materiales(usuario):
    if st.session_state.negociacion is None and not st.session_state.modo_nuevo:
        st.info("Elige una negociación de la lista o crea una nueva.")
        return

    with st.container(border=True):
        _datos_cliente(usuario)
        st.divider()
        _ubicacion()
        st.divider()
        _lista_materiales()

    if st.session_state.negociacion:
        _bloque_venta(usuario)


def _datos_cliente(usuario):
    cliente = st.session_state.cliente

    if cliente is None:
        st.markdown("##### Cliente nuevo")
        telefono = st.text_input("Teléfono", placeholder="+51987654321", key="tel_nuevo")
        if st.button("Buscar cliente", key="btn_buscar_cliente"):
            encontrado = db.buscar_cliente_por_telefono(telefono.strip())
            if encontrado:
                st.session_state.cliente = encontrado
                st.rerun()
            else:
                st.info("Cliente nuevo. Completa sus datos abajo.")
                st.session_state.cliente = {"telefono": telefono.strip(), "nombre": ""}
                st.rerun()
        return

    tipo = cliente.get("m_tipos_cliente") or {}
    st.markdown(f"##### {cliente.get('nombre') or 'Cliente nuevo'}")
    st.caption(f"{cliente.get('telefono','')} · {tipo.get('segmento','')} {tipo.get('nombre','')}")

    with st.expander("Editar datos del cliente"):
        nombre = st.text_input("Nombre", value=cliente.get("nombre") or "")
        tipos = db.tipos_cliente()
        etiquetas = [f"{t['segmento']} · {t['nombre']}" for t in tipos]
        actual = next((i for i, t in enumerate(tipos)
                       if t["id_tipo_cliente"] == cliente.get("id_tipo_cliente")), None)
        elegido = st.selectbox("Tipo de cliente", etiquetas, index=actual, placeholder="Selecciona")

        if st.button("Guardar cliente"):
            datos = {"nombre": nombre}
            if elegido:
                datos["id_tipo_cliente"] = tipos[etiquetas.index(elegido)]["id_tipo_cliente"]
            if cliente.get("id_cliente"):
                st.session_state.cliente = db.actualizar_cliente(cliente["id_cliente"], datos)
            else:
                datos["telefono"] = cliente["telefono"]
                st.session_state.cliente = db.crear_cliente(datos)
            st.success("Guardado.")
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
        st.caption(f"📍 {coords[0]:.6f}, {coords[1]:.6f} · se buscará por distancia")
        return          # con coordenadas no hace falta elegir distrito

    # --- Sin coordenadas: se elige la zona a mano
    st.caption("Sin ubicación exacta. Elige la zona del cliente:")
    _selectores_geografia()


def _selectores_geografia():
    distritos = db.catalogo_distritos()
    if not distritos:
        st.warning("No hay distritos cargados en la base.")
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

    if distrito and not opciones[nombres.index(distrito)]["con_cobertura"]:
        st.warning("Ese distrito no está marcado con cobertura. "
                   "Igual se puede cotizar, pero quizá no haya ferreterías cerca.")


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
    """Producto, marca y cantidad. Al agregar, la barra se vacía sola."""
    productos = sorted({c["producto"] for c in catalogo})
    version = st.session_state.version_tabla

    with st.container(border=True):
        col_prod, col_marca, col_cant, col_boton = st.columns([2.4, 1.5, 0.9, 1])

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

        cantidad = col_cant.number_input(
            "Cant.", min_value=0.01, step=1.0, value=1.0, format="%.2f",
            key=f"nueva_cantidad_{version}",
        )

        col_boton.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if col_boton.button("＋ Agregar", width="stretch", disabled=not producto):
            st.session_state.materiales.append({
                "producto": producto,
                "marca": marca,
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
    etiquetas = ["Producto", "Marca", "Cantidad", "Precio negociado", ""]
    for col, etiqueta in zip(cols, etiquetas):
        col.caption(etiqueta)


def _fila_material(indice, item):
    """Una línea de la canasta. Solo cantidad y precio son editables."""
    col_prod, col_marca, col_cant, col_precio, col_borrar = \
        st.columns([2.4, 1.4, 0.8, 1.1, 0.4], vertical_alignment="center")

    col_prod.markdown(item["producto"])
    col_marca.caption(item["marca"] or "La más barata")

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

    # El motivo solo aparece si hay precio negociado: así no ocupa espacio
    # en las líneas normales, que son la mayoría.
    if precio:
        _motivo_precio(indice, item)


def _motivo_precio(indice, item):
    with st.container(border=True):
        st.caption("¿Por qué el precio distinto? · obligatorio")
        col_motivo, col_quien = st.columns([1.7, 1.2])

        motivo = col_motivo.text_input(
            "Motivo", value=item.get("motivo") or "", label_visibility="collapsed",
            placeholder="Ej. rebaja por volumen", key=f"motivo_{indice}",
        )
        quien = col_quien.text_input(
            "Autorizó", value=item.get("autorizado_por") or "",
            label_visibility="collapsed", placeholder="¿Quién autorizó?",
            key=f"autorizo_{indice}",
        )
        st.session_state.materiales[indice]["motivo"] = motivo.strip() or None
        st.session_state.materiales[indice]["autorizado_por"] = quien.strip() or None


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
        cantidad = item.get("cantidad")

        if not producto:
            errores.append(f"Fila {i}: falta el producto.")
            continue
        if not cantidad or float(cantidad) <= 0:
            errores.append(f"Fila {i}: la cantidad debe ser mayor a 0.")
            continue

        precio_negociado = item.get("precio_negociado")
        if precio_negociado and not (item.get("motivo") or "").strip():
            errores.append(
                f"Fila {i} ({producto}): el precio negociado necesita un motivo.")
            continue

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

        lineas.append({
            "id_producto": opciones[0]["id_producto"],
            "descripcion": producto + (f" · {marca}" if marca else ""),
            "producto": producto,
            "marca": marca,
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
    regla = elegir_regla(monto, coords is not None, db.reglas_cotizacion())

    if regla is None:
        st.error("No hay una regla configurada para este monto. Revisa m_reglas_cotizacion.")
        return

    sedes = db.catalogo_sedes()
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


def _tarjeta_ferreteria(r):
    elegida = st.session_state.sede_elegida == r["id_sede"]

    with st.container(border=True):
        izq, der = st.columns([2, 1])
        izq.markdown(f"**{r['ferreteria']}**")
        izq.caption(r["sede"])
        der.markdown(f"**{config.soles(r['monto'])}**")

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

    promos = db.promociones_de_sede(elegida["id_sede"], elegida["monto"], id_cliente)
    bonos = db.bonos_post_venta(elegida["id_sede"], elegida["monto"], id_cliente)

    with st.container(border=True):
        st.markdown(f"**{elegida['ferreteria']}**")

        descuento = 0.0
        promos_elegidas = []
        if promos:
            st.caption("Promociones")
            for p in promos:
                automatica = p.get("aplicacion") == "automatica"
                aplicar = st.checkbox(
                    f"{p['nombre']} · {config.soles(p['beneficio'])}",
                    value=True, disabled=automatica,
                    key=f"promo_{p['id_promocion']}",
                    help="Automática: no se puede quitar." if automatica else None,
                )
                promos_elegidas.append({**p, "aplicada": aplicar})
                if aplicar and p["modalidad"] == "descuento":
                    descuento += float(p["beneficio"])

        total = elegida["monto"] - descuento
        devolucion = sum(float(b["beneficio"]) for b in bonos) if bonos else 0.0

        st.divider()
        st.markdown(f"Subtotal · {config.soles(elegida['monto'])}")
        if descuento:
            st.markdown(f"Descuento SIDEREXPRESS · :green[−{config.soles(descuento)}]")
        st.markdown(f"### {config.soles(total)}")
        if devolucion:
            st.info(f"Además recibirá {config.soles(devolucion)} de bono después de comprar.")

        if st.button("Generar cotización PDF", type="primary", width="stretch",
                     key="btn_generar"):
            _guardar_y_generar_pdf(usuario, elegida, promos_elegidas,
                                   descuento, total, devolucion)

    # El botón de descarga aparece después de generar
    if st.session_state.get("pdf_generado"):
        st.download_button(
            "⬇ Descargar PDF",
            data=st.session_state.pdf_generado["bytes"],
            file_name=st.session_state.pdf_generado["nombre"],
            mime="application/pdf",
            width="stretch",
        )


def _guardar_y_generar_pdf(usuario, elegida, promociones, descuento, total, devolucion):
    """Guarda la cotización en la base y arma el PDF."""
    from datetime import datetime, timedelta

    cliente = st.session_state.cliente
    negociacion = st.session_state.negociacion
    coords = extraer_coordenadas(st.session_state.ubicacion_texto)

    # Si es una negociación nueva, primero se crea
    if negociacion is None:
        try:
            negociacion = db.crear_negociacion({
                "id_cliente": cliente["id_cliente"],
                "id_usuario": usuario["id_usuario"],
                "id_zona": usuario.get("id_zona"),
                "id_distrito": st.session_state.id_distrito
                               or cliente.get("id_distrito_origen"),
            })
            st.session_state.negociacion = negociacion
        except Exception as e:
            st.error(f"No se pudo crear la negociación: {e}")
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

    promos_json = [{
        "id_promocion": p["id_promocion"],
        "modalidad": p["modalidad"],
        "tipo": "porcentaje",
        "monto_beneficio": float(p["beneficio"]),
        "financiado_por": "siderexpress",
        "aplicada": p["aplicada"],
        "motivo_no_aplicada": None if p["aplicada"] else "El asesor la desactivó",
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
    }

    try:
        id_cotizacion = db.guardar_cotizacion(cabecera, lineas, promos_json, ferreterias)
    except Exception as e:
        st.error(f"No se pudo guardar la cotización: {e}")
        return

    # ------------------------------------------------------------- el PDF ---
    ahora = datetime.now()
    por_sku = {c["id_sku"]: c for c in db.catalogo_skus()}
    tipo = (cliente.get("m_tipos_cliente") or {})
    documento = " ".join(x for x in [cliente.get("tipo_documento"),
                                     cliente.get("numero_documento")] if x)

    datos = {
        "cotizacion": {
            "codigo": config.codigo_cotizacion(id_cotizacion),
            "fecha": ahora.strftime("%d/%m/%Y %H:%M"),
            "vence": (ahora + timedelta(days=1)).strftime("%d/%m/%Y %H:%M"),
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
            "cantidad": d["cantidad"],
            "precio": d["precio_manual"] or d["precio_lista"],
            "subtotal": d["subtotal"],
        } for d in elegida["detalle"]],
        "totales": {
            "subtotal": elegida["monto"],
            "descuento": descuento,
            "total": total,
            "devolucion": devolucion,
        },
        "asesor": usuario["nombre"],
    }

    st.session_state.pdf_generado = {
        "bytes": generar_pdf(datos),
        "nombre": f"{config.codigo_cotizacion(id_cotizacion)}.pdf",
    }
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
            }
            try:
                id_venta = db.registrar_venta(datos)
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
