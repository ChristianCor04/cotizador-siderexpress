"""
PANTALLA DE PRODUCTOS
=====================
Crear productos nuevos o agregar marcas a los que ya existen.

Un SKU es producto + marca + unidad. Casi nunca aparece un producto nuevo:
lo común es una marca nueva de uno que ya tienes. Por eso la pantalla avisa
de los productos parecidos antes de crear uno.

Solo el master entra. La base lo impone por su cuenta.
"""
import streamlit as st

import db
from logica.catalogo import es_identico, parecidos

NUEVA = "+ Nueva…"

# Qué presentación extra se ofrece según la categoría. La tonelada del
# fierro y el millar del ladrillo son las que ya maneja el catálogo.
EXTRAS_POR_CATEGORIA = {
    "FIERRO": ("TON", "Crear también la presentación por tonelada"),
    "LADRILLO": ("MLL", "Crear también la presentación por millar"),
}


def _preparar_memoria():
    valores = {
        "prod_seleccionado": None,    # id del producto existente, o None = nuevo
        "prod_presentaciones": None,  # filas del formulario
        "prod_version": 0,            # limpia los campos al terminar
    }
    for clave, valor in valores.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor
    if st.session_state.prod_presentaciones is None:
        st.session_state.prod_presentaciones = [_fila_vacia()]


def _fila_vacia():
    return {"marca": None, "marca_nueva": "", "unidad": None,
            "unidad_codigo": "", "unidad_nombre": "", "peso": None}


def mostrar(usuario: dict):
    if usuario["rol"] != "master":
        st.info("Solo el administrador puede crear productos.")
        return

    _preparar_memoria()

    mensaje = st.session_state.pop("prod_mensaje", None)
    if mensaje:
        st.success(mensaje)

    productos = db.productos_resumen()
    col_lista, col_form = st.columns([1, 2.3], gap="medium")

    with col_lista:
        _lista(productos)
    with col_form:
        _formulario(productos)


# ================================================================= lista ===
def _lista(productos):
    st.markdown("##### Productos")
    buscar = st.text_input("Buscar", placeholder="Buscar producto",
                           label_visibility="collapsed")

    categorias = sorted({p["categoria"] for p in productos})
    filtro = st.selectbox("Categoría", ["Todas"] + categorias,
                          label_visibility="collapsed")

    lista = productos
    if buscar:
        lista = [p for p in lista if buscar.lower() in p["producto"].lower()]
    if filtro != "Todas":
        lista = [p for p in lista if p["categoria"] == filtro]

    if st.button("＋ Nuevo producto", type="primary", width="stretch"):
        _reiniciar()

    for p in lista[:60]:
        seleccionado = st.session_state.prod_seleccionado == p["id_producto"]
        with st.container(border=True):
            st.markdown(f"**{p['producto']}**")
            detalle = f"{p['categoria'].title()} · {p['marcas']} marca(s) · {p['skus']} SKU"
            st.caption(detalle)
            if p.get("skus_sin_peso"):
                st.caption(f":orange[{p['skus_sin_peso']} sin peso: no suman en toneladas]")
            if st.button("Agregar marca" if not seleccionado else "Seleccionado",
                         key=f"sel_prod_{p['id_producto']}", width="stretch",
                         disabled=seleccionado):
                st.session_state.prod_seleccionado = p["id_producto"]
                st.session_state.prod_presentaciones = [_fila_vacia()]
                st.session_state.prod_version += 1
                st.rerun()

    if len(lista) > 60:
        st.caption(f"Mostrando 60 de {len(lista)}. Usa el buscador para acotar.")


def _reiniciar():
    st.session_state.prod_seleccionado = None
    st.session_state.prod_presentaciones = [_fila_vacia()]
    st.session_state.prod_version += 1
    st.rerun()


# ============================================================ formulario ===
def _formulario(productos):
    v = st.session_state.prod_version
    existente = next((p for p in productos
                      if p["id_producto"] == st.session_state.prod_seleccionado), None)

    with st.container(border=True):
        datos = {"producto": {}, "presentaciones": [], "unidades_extra": []}
        errores = []

        if existente:
            st.markdown(f"##### Agregar marcas a {existente['producto']}")
            st.caption(f"{existente['categoria'].title()} · ya tiene "
                       f"{existente['marcas']} marca(s)")
            _skus_actuales(existente["id_producto"])
            datos["producto"]["id_producto"] = existente["id_producto"]
            categoria_nombre = existente["categoria"]
            computa = existente["computa_toneladas"]
        else:
            st.markdown("##### Nuevo producto")
            categoria_nombre, computa = _datos_producto(productos, datos, errores, v)

        st.divider()
        _presentaciones(datos, errores, computa, v)
        _extras(categoria_nombre, datos, v)

        st.divider()
        _resumen(datos, existente)

        motivo = errores[0] if errores else None
        if st.button("Crear" if not existente else "Agregar presentaciones",
                     type="primary", width="stretch", disabled=bool(motivo),
                     key=f"btn_crear_{v}"):
            _guardar(datos, existente)
        if motivo:
            st.caption(f":orange[{motivo}]")


def _skus_actuales(id_producto):
    skus = db.skus_de_producto(id_producto)
    if skus:
        texto = ", ".join(f"{s['marca']} ({s['unidad_nombre']})" for s in skus)
        st.caption(f"Hoy: {texto}")


def _datos_producto(productos, datos, errores, v):
    """Nombre y categoría. Avisa si el producto ya existe con otro nombre."""
    col_nombre, col_cat = st.columns([2, 1.2])
    nombre = col_nombre.text_input("Nombre", placeholder='Ej. BC 3/4" x 9m',
                                   key=f"prod_nombre_{v}")

    categorias = db.categorias()
    nombres_cat = [c["nombre"] for c in categorias]
    categoria = col_cat.selectbox("Categoría", nombres_cat + [NUEVA], index=None,
                                  placeholder="Elige", key=f"prod_cat_{v}")

    # --- Aviso de productos parecidos: el paso que evita duplicados
    if nombre.strip():
        existentes = [p["producto"] for p in productos]
        similares = parecidos(nombre, existentes)
        identico = es_identico(nombre, existentes)
        if similares:
            with st.container(border=True):
                if identico:
                    st.warning(f"«{identico}» ya existe. No lo crees de nuevo: "
                               "agrégale la marca.")
                else:
                    st.warning("Ya hay productos con un nombre parecido. "
                               "¿Es alguno de estos?")
                for s in similares:
                    prod = next(p for p in productos if p["producto"] == s)
                    col_n, col_b = st.columns([2, 1], vertical_alignment="center")
                    col_n.caption(f"{s} · {prod['categoria'].title()} · {prod['marcas']} marca(s)")
                    if col_b.button("Agregarle marca", key=f"usar_{prod['id_producto']}_{v}"):
                        st.session_state.prod_seleccionado = prod["id_producto"]
                        st.session_state.prod_version += 1
                        st.rerun()
            if identico:
                errores.append("Ese producto ya existe: usa «Agregarle marca».")

    if not nombre.strip():
        errores.append("Falta el nombre del producto.")
    datos["producto"]["nombre"] = nombre.strip()

    # --- Categoría: existente o nueva
    computa = False
    if categoria == NUEVA:
        with st.container(border=True):
            st.caption("Nueva categoría")
            nueva = st.text_input("Nombre de la categoría", key=f"cat_nueva_{v}")
            computa = st.checkbox(
                "Suma en el indicador de toneladas",
                key=f"cat_ton_{v}",
                help="Hoy solo fierro, alambre y clavos cuentan como toneladas "
                     "de acero. Márcalo solo si esta categoría también es acero.",
            )
            if nueva.strip():
                parecida = parecidos(nueva, nombres_cat)
                if parecida:
                    st.warning(f"Ya existe una categoría parecida: {', '.join(parecida)}.")
                    if es_identico(nueva, nombres_cat):
                        errores.append("Esa categoría ya existe: elígela de la lista.")
            else:
                errores.append("Falta el nombre de la categoría nueva.")
        datos["categoria_nueva"] = {"nombre": nueva.strip(), "computa_toneladas": computa}
        return nueva.strip().upper(), computa

    if categoria:
        elegida = next(c for c in categorias if c["nombre"] == categoria)
        datos["producto"]["id_categoria"] = elegida["id_categoria"]
        computa = bool(elegida.get("computa_toneladas"))
        return categoria, computa

    errores.append("Falta la categoría.")
    return None, False


def _presentaciones(datos, errores, computa, v):
    """Las combinaciones de marca, unidad y peso. Cada una es un SKU."""
    st.markdown("**Presentaciones**")
    st.caption("Cada fila es un SKU: una marca en una unidad de venta.")

    lista_marcas = db.marcas()
    lista_unidades = db.unidades()
    nombres_marca = [m["nombre"] for m in lista_marcas]
    etiquetas_unidad = [u["nombre"] for u in lista_unidades]

    filas = st.session_state.prod_presentaciones
    combinaciones = set()

    for i, fila in enumerate(filas):
        col_m, col_u, col_p, col_x = st.columns([1.4, 1.4, 0.8, 0.3],
                                                vertical_alignment="bottom")
        marca = col_m.selectbox("Marca", nombres_marca + [NUEVA], index=None,
                                placeholder="Elige", key=f"pm_{v}_{i}")
        unidad = col_u.selectbox("Unidad", etiquetas_unidad + [NUEVA], index=None,
                                 placeholder="Elige", key=f"pu_{v}_{i}")
        peso = col_p.number_input("Peso (kg)", min_value=0.0, step=0.1, value=None,
                                  format="%.3f", key=f"pp_{v}_{i}",
                                  placeholder="obligatorio" if computa else "opcional")
        if len(filas) > 1 and col_x.button("🗑", key=f"px_{v}_{i}"):
            filas.pop(i)
            st.session_state.prod_version += 1
            st.rerun()

        item = {}

        # --- Marca
        if marca == NUEVA:
            nueva = st.text_input("Nombre de la marca nueva", key=f"pmn_{v}_{i}")
            if nueva.strip():
                identica = es_identico(nueva, nombres_marca)
                if identica:
                    st.caption(f":orange[«{identica}» ya existe: se usará esa.]")
                    item["id_marca"] = next(m["id_marca"] for m in lista_marcas
                                            if m["nombre"] == identica)
                else:
                    similares = parecidos(nueva, nombres_marca)
                    if similares:
                        st.caption(f":orange[Parecidas: {', '.join(similares)}. "
                                   "¿No es alguna de esas?]")
                    item["marca_nueva"] = nueva.strip()
            else:
                errores.append(f"Fila {i + 1}: falta el nombre de la marca nueva.")
        elif marca:
            item["id_marca"] = next(m["id_marca"] for m in lista_marcas if m["nombre"] == marca)
        else:
            errores.append(f"Fila {i + 1}: elige la marca.")

        # --- Unidad
        if unidad == NUEVA:
            col_c, col_n = st.columns([1, 2])
            codigo = col_c.text_input("Código", placeholder="PAQ", max_chars=6,
                                      key=f"puc_{v}_{i}")
            nombre_u = col_n.text_input("Nombre", placeholder="Paquete de 10 varillas",
                                        key=f"pun_{v}_{i}")
            if codigo.strip() and nombre_u.strip():
                identica = es_identico(nombre_u, etiquetas_unidad)
                if identica:
                    st.caption(f":orange[«{identica}» ya existe: se usará esa.]")
                    item["id_unidad"] = next(u["id_unidad_medida"] for u in lista_unidades
                                             if u["nombre"] == identica)
                else:
                    item["unidad_nueva"] = {"codigo": codigo.strip(),
                                            "nombre": nombre_u.strip()}
                    st.caption("Si la unidad agrupa varias piezas, el peso es el "
                               "del paquete completo.")
            else:
                errores.append(f"Fila {i + 1}: la unidad nueva necesita código y nombre.")
        elif unidad:
            item["id_unidad"] = next(u["id_unidad_medida"] for u in lista_unidades
                                     if u["nombre"] == unidad)
        else:
            errores.append(f"Fila {i + 1}: elige la unidad.")

        # --- Peso
        if peso:
            item["peso_kg"] = float(peso)
        elif computa:
            errores.append(f"Fila {i + 1}: esta categoría suma en toneladas, "
                           "indica el peso. Sin él, no suma en tus KPI.")

        # --- Combinación repetida dentro del mismo formulario
        clave = (marca, unidad)
        if marca and unidad and marca != NUEVA and unidad != NUEVA:
            if clave in combinaciones:
                errores.append(f"Fila {i + 1}: esa marca y unidad ya están en otra fila.")
            combinaciones.add(clave)

        datos["presentaciones"].append(item)

    if st.button("＋ Agregar otra marca o presentación", key=f"padd_{v}"):
        filas.append(_fila_vacia())
        st.session_state.prod_version += 1
        st.rerun()


def _extras(categoria, datos, v):
    """Tonelada para el fierro, millar para el ladrillo."""
    extra = EXTRAS_POR_CATEGORIA.get((categoria or "").upper())
    if not extra:
        return
    codigo, texto = extra
    if st.checkbox(texto, value=True, key=f"pextra_{v}"):
        datos["unidades_extra"].append(codigo)


def _resumen(datos, existente):
    presentaciones = [p for p in datos["presentaciones"] if p]
    if not presentaciones:
        return

    marcas_nuevas = [p["marca_nueva"] for p in presentaciones if p.get("marca_nueva")]
    unidades_nuevas = [p["unidad_nueva"]["nombre"] for p in presentaciones
                       if p.get("unidad_nueva")]
    n_extra = len(presentaciones) * len(datos["unidades_extra"])

    partes = []
    if not existente and datos["producto"].get("nombre"):
        partes.append(f"Producto **{datos['producto']['nombre']}**")
    if datos.get("categoria_nueva", {}).get("nombre"):
        partes.append(f"Categoría nueva **{datos['categoria_nueva']['nombre'].upper()}**")
    if marcas_nuevas:
        partes.append(f"Marca(s) nueva(s): **{', '.join(m.upper() for m in marcas_nuevas)}**")
    if unidades_nuevas:
        partes.append(f"Unidad(es) nueva(s): **{', '.join(unidades_nuevas)}**")
    partes.append(f"**{len(presentaciones) + n_extra} SKU** en total")

    st.caption("Se va a crear:")
    st.markdown("  \n".join(partes))
    st.caption("Quedan sin precio: se cargan desde la pantalla de Precios.")


def _guardar(datos, existente):
    try:
        resultado = db.crear_producto_con_skus(datos)
    except Exception as e:
        detalle = str(e)
        for clave, texto in [
            ("Solo el administrador", "Solo el administrador puede crear productos."),
            ("uq_producto_nombre", "Ya existe un producto con ese nombre."),
            ("uq_categoria_nombre", "Ya existe una categoría con ese nombre."),
            ("suma en toneladas", "Falta el peso en alguna presentación."),
        ]:
            if clave in detalle:
                st.error(texto)
                return
        st.error(f"No se pudo crear: {e}")
        return

    db.limpiar_cache()      # el cotizador y la pantalla de precios lo ven al instante
    nombre = existente["producto"] if existente else datos["producto"]["nombre"]
    st.session_state.prod_mensaje = (
        f"{nombre}: {resultado['skus']} SKU creado(s). "
        "Ahora cárgales precio desde la pantalla de Precios.")
    st.session_state.prod_seleccionado = None
    st.session_state.prod_presentaciones = [_fila_vacia()]
    st.session_state.prod_version += 1
    st.rerun()
