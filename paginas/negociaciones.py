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
    # Streamlit recuerda el contenido de la tabla editable por su "key".
    # Si la key no cambia, al abrir otra negociación seguiría mostrando lo
    # anterior. Subir este número obliga a la tabla a redibujarse.
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
            "Producto": d["producto"],
            "Marca": d["marca"],
            "Cantidad": d["cantidad"],
            "Precio negociado": d["precio_modificado"],
            "Motivo": d["motivo_modificacion"],
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
    st.markdown("**Lista de materiales**")
    catalogo = db.catalogo_skus()

    # Dos columnas separadas: el producto es obligatorio y la marca no.
    # Si el asesor deja la marca vacía, se toma la más barata de cada ferretería.
    productos = sorted({c["producto"] for c in catalogo})
    marcas = sorted({c["marca"] for c in catalogo})

    tabla = pd.DataFrame(st.session_state.materiales or [{
        "Producto": None, "Marca": None, "Cantidad": None,
        "Precio negociado": None, "Motivo": None,
    }])
    for columna in ["Producto", "Marca", "Cantidad", "Precio negociado", "Motivo"]:
        if columna not in tabla.columns:
            tabla[columna] = None

    # Hay que fijar el tipo de cada columna. Si una queda toda vacía, pandas
    # la trata como número y el editor no acepta texto ahí.
    for columna in ["Producto", "Marca", "Motivo"]:
        tabla[columna] = tabla[columna].astype("object").where(tabla[columna].notna(), None)
    for columna in ["Cantidad", "Precio negociado"]:
        tabla[columna] = pd.to_numeric(tabla[columna], errors="coerce").astype("float64")

    editada = st.data_editor(
        tabla[["Producto", "Marca", "Cantidad", "Precio negociado", "Motivo"]],
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key=f"editor_materiales_{st.session_state.version_tabla}",
        column_config={
            "Producto": st.column_config.SelectboxColumn(options=productos, width="large"),
            "Marca": st.column_config.SelectboxColumn(
                options=marcas, width="medium",
                help="Opcional. Vacía = se toma la marca más barata de cada ferretería.",
            ),
            "Cantidad": st.column_config.NumberColumn(min_value=0.01, step=1, format="%.2f"),
            "Precio negociado": st.column_config.NumberColumn(
                min_value=0.0, step=0.10, format="%.2f",
                help="Solo si la ferretería autorizó un precio distinto al de lista.",
            ),
            "Motivo": st.column_config.TextColumn(
                help="Obligatorio si escribiste un precio negociado.",
            ),
        },
    )
    st.session_state.materiales = editada.to_dict("records")

    anterior = st.session_state.cotizacion_actual
    if anterior:
        st.caption(
            f"Cargado de {config.codigo_cotizacion(anterior['id_cotizacion'])} "
            f"(versión {anterior['version']}). Si cambias algo, recotiza."
        )
    st.caption("Deja la marca vacía si al cliente le da igual: se buscará la más barata.")

    if st.button("Buscar ferreterías", type="primary", width="stretch"):
        _recotizar()


# ---------------------------------------------------------------- cotizar
def _celda(fila: dict, clave: str):
    """Lee una celda de la tabla y devuelve None si está vacía.

    Hace falta porque pandas rellena las celdas vacías con "nan", que NO es
    lo mismo que vacío: `if valor:` daría verdadero y rompería las validaciones.
    """
    valor = fila.get(clave)
    if valor is None:
        return None
    if isinstance(valor, float) and pd.isna(valor):
        return None
    if isinstance(valor, str) and not valor.strip():
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return valor


def _armar_lineas(catalogo) -> tuple[list[dict], list[str]]:
    """Convierte la tabla que llenó el asesor en lo que espera la lógica.

    Si la fila trae marca, se busca solo ese producto con esa marca.
    Si no, se admiten todas las marcas de ese producto y después se
    elige la más barata en cada ferretería.
    """
    lineas, errores = [], []

    for i, fila in enumerate(st.session_state.materiales, start=1):
        producto = _celda(fila, "Producto")
        marca = _celda(fila, "Marca")
        cantidad = _celda(fila, "Cantidad")

        # Fila vacía: se ignora
        if not producto and not cantidad and not marca:
            continue
        if not producto:
            errores.append(f"Fila {i}: elige un producto.")
            continue
        if not cantidad or float(cantidad) <= 0:
            errores.append(f"Fila {i}: falta la cantidad.")
            continue

        precio_manual = _celda(fila, "Precio negociado")
        motivo = _celda(fila, "Motivo")
        if precio_manual and not motivo:
            errores.append(f"Fila {i}: el precio negociado necesita un motivo.")
            continue

        opciones = [c for c in catalogo if c["producto"] == producto]
        if not opciones:
            errores.append(
                f"Fila {i}: «{producto}» ya no está en el catálogo. "
                "Bórralo y elige el producto de la lista."
            )
            continue
        if marca:
            opciones = [c for c in opciones if c["marca"] == marca]
            if not opciones:
                disponibles = sorted({c["marca"] for c in catalogo if c["producto"] == producto})
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
            "precio_manual": float(precio_manual) if precio_manual else None,
            "motivo": str(motivo).strip() if motivo else None,
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
