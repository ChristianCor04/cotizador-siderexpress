"""
PANTALLA DE FERRETERÍAS
=======================
Crear y editar ferreterías y sedes, con un mapa de todas las ubicaciones.

Reglas que impone la base, no esta pantalla:
  - El código de cada sede se genera solo: prefijo de la zona + siguiente
    número libre (TRUJ014, CIX041). No se edita: es la llave del Excel.
  - El distrito sale de las coordenadas.
  - El supervisor crea sedes solo en sus zonas. Abrir una zona nueva es del
    master.
  - Nada se borra: ferreterías y sedes se desactivan.
"""
import pandas as pd
import pydeck as pdk
import streamlit as st

import db
from logica.catalogo import es_identico, parecidos
from logica.geo import extraer_coordenadas

ROJO = [208, 2, 27, 230]
AZUL = [24, 95, 165, 200]

# Tamaño de los puntos del mapa, en píxeles de pantalla. El punto se ajusta
# al zoom, pero nunca baja del mínimo ni pasa del máximo.
#   Para achicarlos: baja los máximos. Para agrandarlos: súbelos.
PUNTO_OTRAS = {"minimo": 4, "maximo": 7}
PUNTO_ELEGIDA = {"minimo": 6, "maximo": 11}


def _preparar_memoria():
    for clave, valor in {"fer_seleccionada": None, "fer_modo": None,
                         "fer_sede_edicion": None, "fer_version": 0}.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


def mostrar(usuario: dict):
    if usuario["rol"] not in ("supervisor", "master"):
        st.info("Esta pantalla es para supervisores y administradores.")
        return
    _preparar_memoria()

    mensaje = st.session_state.pop("fer_mensaje", None)
    if mensaje:
        st.success(mensaje)

    sedes = db.sedes_mapa()
    ferreterias = db.ferreterias_todas()

    _indicadores(ferreterias, sedes)

    col_lista, col_mapa = st.columns([1, 2.4], gap="medium")
    with col_lista:
        zona = _lista(ferreterias, sedes)
    with col_mapa:
        _mapa(sedes, zona)

    st.divider()
    _formularios(usuario, ferreterias, sedes)


# ========================================================== indicadores ===
def _indicadores(ferreterias, sedes):
    activas = [s for s in sedes if s["activo"]]
    sin_coords = [s for s in activas if s["verificacion"] == "sin_coordenadas"]
    no_coincide = [s for s in activas if s["verificacion"] == "no_coincide"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Ferreterías", sum(1 for f in ferreterias if f["activo"]))
    c2.metric("Sedes activas", len(activas))
    c3.metric("Sin coordenadas", len(sin_coords),
              help="No aparecen en la búsqueda por distancia al cotizar.")
    c4.metric("Distrito no coincide", len(no_coincide),
              help="El distrito cargado no es el que dicen sus coordenadas.")

    problemas = sin_coords + no_coincide
    if problemas:
        with st.expander(f"Revisar {len(problemas)} sede(s) con problemas"):
            for sede in problemas:
                col_t, col_b = st.columns([4, 1], vertical_alignment="center")
                if sede["verificacion"] == "sin_coordenadas":
                    col_t.caption(f"**{sede['codigo']}** · {sede['ferreteria']} · sin coordenadas: "
                                  "agrégalas editando la sede")
                    continue
                col_t.caption(f"**{sede['codigo']}** · {sede['ferreteria']} · cargada en "
                              f"{(sede['distrito'] or '').title()}, pero sus coordenadas son de otro distrito")
                # Reescribir las mismas coordenadas hace que la base recalcule el distrito
                if col_b.button("Corregir", key=f"corregir_{sede['id_sede']}", width="stretch"):
                    try:
                        db.actualizar_sede(sede["id_sede"], {"latitud": sede["latitud"],
                                                             "longitud": sede["longitud"]})
                        db.limpiar_cache()
                        st.session_state.fer_mensaje = f"Distrito de {sede['codigo']} corregido."
                        st.rerun()
                    except Exception as e:
                        st.error(_error(e))


# ================================================================ lista ===
def _lista(ferreterias, sedes):
    buscar = st.text_input("Buscar", placeholder="Buscar ferretería",
                           label_visibility="collapsed")
    zonas = sorted({s["zona"] for s in sedes if s.get("zona")})
    zona = st.segmented_control("Zona", ["Todas"] + zonas, default="Todas",
                                label_visibility="collapsed", key="fer_zona") or "Todas"

    por_ferreteria = {}
    for s in sedes:
        if s["activo"]:
            por_ferreteria.setdefault(s["id_ferreteria"], []).append(s)

    inactivas = sum(1 for f in ferreterias if not f["activo"])
    ver_inactivas = st.toggle(f"Ver inactivas ({inactivas})", key="fer_ver_inactivas",
                              disabled=not inactivas)
    lista = [f for f in ferreterias if f["activo"] or ver_inactivas]
    if buscar:
        lista = [f for f in lista if buscar.lower() in f["nombre"].lower()]
    if zona != "Todas":
        lista = [f for f in lista
                 if any(s["zona"] == zona for s in por_ferreteria.get(f["id_ferreteria"], []))]

    col_f, col_s = st.columns(2)
    if col_f.button("＋ Ferretería", width="stretch"):
        _cambiar_modo("nueva_ferreteria", None)
    if col_s.button("＋ Sede", width="stretch",
                    disabled=st.session_state.fer_seleccionada is None,
                    help="Elige primero una ferretería"):
        _cambiar_modo("nueva_sede")

    with st.container(height=430):
        for f in lista:
            propias = por_ferreteria.get(f["id_ferreteria"], [])
            sin_coords = sum(1 for s in propias if s["verificacion"] == "sin_coordenadas")
            elegida = st.session_state.fer_seleccionada == f["id_ferreteria"]
            with st.container(border=True):
                st.markdown(f"**{f['nombre']}**" + ("" if f["activo"] else " · :gray[inactiva]"))
                detalle = f"{len(propias)} sede{'s' if len(propias) != 1 else ''}"
                if f.get("ruc"):
                    detalle += f" · RUC {f['ruc']}"
                st.caption(detalle)
                if sin_coords:
                    st.caption(f":orange[{sin_coords} sin coordenadas]")
                if st.button("Seleccionada" if elegida else "Ver",
                             key=f"fer_ver_{f['id_ferreteria']}", width="stretch",
                             disabled=elegida):
                    st.session_state.fer_seleccionada = f["id_ferreteria"]
                    _cambiar_modo(None)
        if not lista:
            st.caption("No hay ferreterías con ese filtro.")
    return zona


def _zonas_del_usuario(usuario) -> set | None:
    """Zonas que cubre el usuario. None = todas (master)."""
    if usuario["rol"] == "master":
        return None
    return {z.get("id_zona") for z in (usuario.get("rel_usuarios_zonas") or [])}


def _cambiar_modo(modo, seleccionada="sin cambio"):
    st.session_state.fer_modo = modo
    if seleccionada != "sin cambio":
        st.session_state.fer_seleccionada = seleccionada
    st.session_state.fer_sede_edicion = None
    st.session_state.fer_version += 1
    st.rerun()


# ================================================================= mapa ===
def _mapa(sedes, zona):
    puntos = [s for s in sedes if s["activo"] and s["latitud"] is not None
              and (zona == "Todas" or s["zona"] == zona)]
    if not puntos:
        st.info("No hay sedes con coordenadas para mostrar.")
        return

    tabla = pd.DataFrame(puntos)
    elegida = st.session_state.fer_seleccionada
    tabla["distrito"] = tabla["distrito"].fillna("").str.replace("_", " ").str.title()

    # El mapa se centra en la ferretería elegida si tiene sedes; si no, en todo
    foco = tabla[tabla["id_ferreteria"] == elegida] if elegida in set(tabla["id_ferreteria"]) else tabla
    lat, lon = foco["latitud"].mean(), foco["longitud"].mean()
    extension = max(tabla["latitud"].max() - tabla["latitud"].min(),
                    tabla["longitud"].max() - tabla["longitud"].min())
    zoom = 12 if extension < 0.1 else 11 if extension < 0.3 else 9 if extension < 1 else 7 if extension < 4 else 5

    def capa(datos, color, tamano, id_capa):
        # El radio va en metros, pero lo que manda es el mínimo y el máximo en
        # píxeles: así el punto se ve igual de cerca y de lejos.
        return pdk.Layer(
            "ScatterplotLayer", data=datos, id=id_capa,
            get_position="[longitud, latitud]", get_fill_color=color,
            get_radius=150,
            radius_min_pixels=tamano["minimo"], radius_max_pixels=tamano["maximo"],
            stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1,
            pickable=True,
        )

    # La elegida va en su propia capa, encima, para que se distinga
    capas = [capa(tabla[tabla["id_ferreteria"] != elegida], AZUL, PUNTO_OTRAS, "sedes")]
    propias = tabla[tabla["id_ferreteria"] == elegida]
    if not propias.empty:
        capas.append(capa(propias, ROJO, PUNTO_ELEGIDA, "elegida"))

    mapa = pdk.Deck(
        layers=capas,
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        map_provider="carto", map_style="dark",
        tooltip={"html": "<b>{ferreteria}</b><br/>{sede} · {codigo}<br/>{distrito} · {precios} precios",
                 "style": {"fontSize": "12px"}},
    )

    # Al hacer clic en un pin se selecciona su ferretería
    evento = st.pydeck_chart(mapa, height=480, on_select="rerun",
                             selection_mode="single-object", key="mapa_sedes")
    try:
        objetos = (evento.selection.objects.get("sedes") or
                   evento.selection.objects.get("elegida") or [])
    except AttributeError:
        objetos = []
    _procesar_clic_mapa(objetos)

    st.caption(":red[●] ferretería elegida  ·  :blue[●] las demás  ·  "
               "pasa el mouse sobre un punto para ver el detalle")


def _procesar_clic_mapa(objetos):
    """Cambia de ferretería solo cuando hay un clic NUEVO en el mapa.

    El mapa recuerda el último punto seleccionado y lo devuelve en cada
    recarga de la página. Si se reaccionara siempre, al escribir en cualquier
    formulario la página volvería a la ferretería de ese clic viejo y
    descartaría lo escrito. Por eso se guarda qué clic ya se atendió.
    """
    firma = tuple(sorted(o.get("id_sede") for o in objetos)) if objetos else None
    if firma == st.session_state.get("fer_mapa_atendido"):
        return
    st.session_state.fer_mapa_atendido = firma
    if not objetos:
        return

    id_f = objetos[0]["id_ferreteria"]
    if id_f != st.session_state.fer_seleccionada:
        st.session_state.fer_seleccionada = id_f
        _cambiar_modo(None)


# ========================================================== formularios ===
def _formularios(usuario, ferreterias, sedes):
    modo = st.session_state.fer_modo
    elegida = next((f for f in ferreterias
                    if f["id_ferreteria"] == st.session_state.fer_seleccionada), None)

    if modo == "nueva_ferreteria":
        _form_nueva_ferreteria(ferreterias)
        return
    if elegida is None:
        st.caption("Elige una ferretería en la lista o en el mapa para ver y editar sus sedes.")
        return

    propias = [s for s in sedes if s["id_ferreteria"] == elegida["id_ferreteria"]]
    if modo == "nueva_sede":
        _form_nueva_sede(usuario, elegida)
    elif modo == "editar_ferreteria":
        _form_editar_ferreteria(elegida, ferreterias)
    else:
        _detalle_ferreteria(elegida, propias, usuario)


def _detalle_ferreteria(ferreteria, propias, usuario):
    col_t, col_b = st.columns([3, 1], vertical_alignment="bottom")
    col_t.markdown(f"#### {ferreteria['nombre']}")
    if col_b.button("Editar ferretería", width="stretch"):
        _cambiar_modo("editar_ferreteria")

    if not propias:
        st.caption("Esta ferretería todavía no tiene sedes.")
        return

    st.dataframe(pd.DataFrame([{
        "Código": s["codigo"], "Sede": s["sede"],
        "Distrito": (s["distrito"] or "").replace("_", " ").title(),
        "Zona": s["zona"], "Precios": s["precios"],
        "Estado": "Activa" if s["activo"] else "Inactiva",
        "Ubicación": {"coincide": "OK", "sin_coordenadas": "Sin coordenadas",
                      "no_coincide": "Distrito no coincide",
                      "fuera_de_poligonos": "Fuera de los mapas"}.get(s["verificacion"], ""),
    } for s in propias]), hide_index=True, width="stretch")

    sede = st.selectbox("Editar una sede", [None] + propias, index=0,
                        format_func=lambda s: "Elige una sede…" if s is None
                        else f"{s['codigo']} · {s['sede']}",
                        key=f"fer_editar_sede_{st.session_state.fer_version}")
    if sede:
        _form_editar_sede(sede, usuario)


# ----------------------------------------------------- nueva ferretería ---
def _form_nueva_ferreteria(ferreterias):
    st.markdown("#### Nueva ferretería")
    v = st.session_state.fer_version
    col_n, col_r, col_c = st.columns([2, 1, 1])
    nombre = col_n.text_input("Nombre", key=f"nf_nombre_{v}")
    ruc = col_r.text_input("RUC", max_chars=11, placeholder="Opcional", key=f"nf_ruc_{v}")
    codigo = col_c.text_input("Código de asociado", placeholder="Opcional", key=f"nf_cod_{v}")

    error = None
    nombres = [f["nombre"] for f in ferreterias]
    if nombre.strip():
        identica = es_identico(nombre, nombres)
        similares = parecidos(nombre, nombres)
        if identica:
            error = f"«{identica}» ya existe."
        elif similares:
            st.warning(f"Ya hay ferreterías con un nombre parecido: {', '.join(similares)}. "
                       "Revisa que no sea la misma.")
    else:
        error = "Falta el nombre."
    if ruc.strip() and not (ruc.strip().isdigit() and len(ruc.strip()) == 11):
        error = "El RUC debe tener 11 dígitos."

    col_cancelar, col_crear = st.columns(2)
    if col_cancelar.button("Cancelar", width="stretch", key=f"nf_cancelar_{v}"):
        _cambiar_modo(None)
    if col_crear.button("Crear ferretería", type="primary", width="stretch",
                        disabled=bool(error), key=f"nf_crear_{v}"):
        try:
            nueva = db.crear_ferreteria({
                "nombre": nombre.strip().upper(),
                "ruc": ruc.strip() or None,
                "codigo_asociado": codigo.strip() or None,
            })
            db.limpiar_cache()
            st.session_state.fer_mensaje = (f"{nueva['nombre']} creada. "
                                            "Ahora agrégale su primera sede.")
            _cambiar_modo("nueva_sede", nueva["id_ferreteria"])
        except Exception as e:
            st.error(_error(e))
    if error and nombre.strip():
        st.caption(f":orange[{error}]")


def _form_editar_ferreteria(ferreteria, ferreterias):
    st.markdown(f"#### Editar {ferreteria['nombre']}")
    v = st.session_state.fer_version
    col_n, col_r, col_c = st.columns([2, 1, 1])
    nombre = col_n.text_input("Nombre", value=ferreteria["nombre"], key=f"ef_nombre_{v}")
    ruc = col_r.text_input("RUC", value=ferreteria.get("ruc") or "", max_chars=11, key=f"ef_ruc_{v}")
    codigo = col_c.text_input("Código de asociado", value=ferreteria.get("codigo_asociado") or "",
                              key=f"ef_cod_{v}")
    activa = st.toggle("Activa", value=ferreteria["activo"], key=f"ef_activa_{v}",
                       help="Una ferretería inactiva deja de aparecer al cotizar. "
                            "No se borra: conserva su historial.")

    error = None
    if not nombre.strip():
        error = "Falta el nombre."
    elif ruc.strip() and not (ruc.strip().isdigit() and len(ruc.strip()) == 11):
        error = "El RUC debe tener 11 dígitos."
    else:
        otros = [f["nombre"] for f in ferreterias
                 if f["id_ferreteria"] != ferreteria["id_ferreteria"]]
        identica = es_identico(nombre, otros)
        if identica:
            error = f"Ya existe otra ferretería llamada «{identica}»."

    col_cancelar, col_guardar = st.columns(2)
    if col_cancelar.button("Cancelar", width="stretch", key=f"ef_cancelar_{v}"):
        _cambiar_modo(None)
    if col_guardar.button("Guardar", type="primary", width="stretch",
                          disabled=bool(error), key=f"ef_guardar_{v}"):
        try:
            db.actualizar_ferreteria(ferreteria["id_ferreteria"], {
                "nombre": nombre.strip().upper(), "ruc": ruc.strip() or None,
                "codigo_asociado": codigo.strip() or None, "activo": activa,
            })
            db.limpiar_cache()
            st.session_state.fer_mensaje = "Ferretería actualizada."
            _cambiar_modo(None)
        except Exception as e:
            st.error(_error(e))
    if error:
        st.caption(f":orange[{error}]")


# ---------------------------------------------------------- nueva sede ---
def _form_nueva_sede(usuario, ferreteria):
    st.markdown(f"#### Nueva sede de {ferreteria['nombre']}")
    v = st.session_state.fer_version

    texto = st.text_input("Ubicación", placeholder="Link de Google Maps o -8.0470, -79.0498",
                          key=f"ns_ubic_{v}")
    coords = extraer_coordenadas(texto) if texto else None
    geo = db.distrito_de_coordenadas(coords[0], coords[1]) if coords else None

    error = None
    if texto and not coords:
        error = "No se reconocen las coordenadas. Pega el link completo de Google Maps."
    elif coords and not geo:
        error = ("Las coordenadas no caen en ningún distrito cargado. Revisa el punto, o "
                 "carga los límites distritales de ese departamento.")
    elif not coords:
        error = "Falta la ubicación."

    if geo:
        lugar = " · ".join(x.replace("_", " ").title()
                           for x in (geo["distrito"], geo["provincia"], geo["departamento"]) if x)
        mis_zonas = _zonas_del_usuario(usuario)
        if geo.get("id_zona") and mis_zonas is not None and geo["id_zona"] not in mis_zonas:
            # Se avisa antes de llenar el resto: la base lo rechazaría al guardar
            error = (f"Esta ubicación es de la zona {geo['zona']}, que no cubres. "
                     "Solo puedes crear sedes en tus zonas.")
            st.warning(error)
        elif geo.get("id_zona"):
            codigo = db.siguiente_codigo_sede(geo["id_zona"]) or "—"
            st.success(f"📍 {lugar} · zona {geo['zona']} · código **{codigo}**, "
                       "se confirma al crear")
        else:
            error = f"{geo['provincia'].title()} todavía no es una zona de trabajo."
            _abrir_zona(usuario, geo)

    col_n, col_t, col_e = st.columns(3)
    nombre = col_n.text_input("Nombre de la sede", value=ferreteria["nombre"].title(),
                              key=f"ns_nombre_{v}")
    telefono = col_t.text_input("Teléfono", placeholder="944 123 456", key=f"ns_tel_{v}")
    encargado = col_e.text_input("Encargado", placeholder="Opcional", key=f"ns_enc_{v}")
    direccion = st.text_input("Dirección", placeholder="Opcional", key=f"ns_dir_{v}")
    if not nombre.strip():
        error = error or "Falta el nombre de la sede."

    col_cancelar, col_crear = st.columns(2)
    if col_cancelar.button("Cancelar", width="stretch", key=f"ns_cancelar_{v}"):
        _cambiar_modo(None)
    if col_crear.button("Crear sede", type="primary", width="stretch",
                        disabled=bool(error), key=f"ns_crear_{v}"):
        try:
            nueva = db.crear_sede({
                "id_ferreteria": ferreteria["id_ferreteria"], "nombre": nombre.strip(),
                "latitud": coords[0], "longitud": coords[1],
                "telefono": telefono.strip(), "encargado": encargado.strip(),
                "direccion": direccion.strip(),
            })
            db.limpiar_cache()
            st.session_state.fer_mensaje = (f"Sede {nueva['codigo']} creada. Ya aparece en "
                                            "Precios para cargarle sus precios.")
            _cambiar_modo(None)
        except Exception as e:
            st.error(_error(e))
    if error and texto:
        st.caption(f":orange[{error}]")


def _abrir_zona(usuario, geo):
    """Una ciudad nueva: el master abre la zona ahí mismo."""
    if usuario["rol"] != "master":
        st.warning(f"{geo['provincia'].title()} no pertenece a ninguna zona. Pide al "
                   "administrador que la abra para poder crear sedes ahí.")
        return

    with st.container(border=True):
        st.markdown(f"**Abrir la zona de {geo['provincia'].title()}**")
        st.caption("Se crea la zona y se le asignan todos los distritos de la provincia. "
                   "Las sedes de esta zona llevarán el prefijo que elijas.")
        col_n, col_p, col_b = st.columns([2, 1, 1], vertical_alignment="bottom")
        nombre = col_n.text_input("Nombre de la zona", value=geo["provincia"].title(),
                                  key="az_nombre")
        prefijo = col_p.text_input("Prefijo", max_chars=5, placeholder="PIU",
                                   key="az_prefijo").strip().upper()
        valido = prefijo.isalpha() and 2 <= len(prefijo) <= 5 and nombre.strip()
        if col_b.button("Abrir zona", disabled=not valido, width="stretch"):
            try:
                db.abrir_zona(nombre.strip(), prefijo, geo["id_provincia"])
                db.limpiar_cache()
                st.session_state.fer_mensaje = (f"Zona {nombre.strip()} abierta con el "
                                                f"prefijo {prefijo}.")
                st.rerun()
            except Exception as e:
                st.error(_error(e))


# --------------------------------------------------------- editar sede ---
def _form_editar_sede(sede, usuario):
    v = f"{st.session_state.fer_version}_{sede['id_sede']}"
    mis_zonas = _zonas_del_usuario(usuario)
    solo_lectura = mis_zonas is not None and sede.get("id_zona") not in mis_zonas
    with st.container(border=True):
        if solo_lectura:
            st.info(f"Esta sede es de la zona {sede.get('zona') or 'sin zona'}, que no cubres. "
                    "Puedes verla, pero no editarla.")
        st.caption(f"🔒 Código **{sede['codigo']}**: no se edita, es la llave de la "
                   "plantilla de precios.")
        col_n, col_t, col_e = st.columns(3)
        nombre = col_n.text_input("Nombre", value=sede["sede"], key=f"es_nombre_{v}")
        telefono = col_t.text_input("Teléfono", value=sede.get("telefono") or "",
                                    key=f"es_tel_{v}")
        encargado = col_e.text_input("Encargado", value=sede.get("encargado") or "",
                                     key=f"es_enc_{v}")
        direccion = st.text_input("Dirección", value=sede.get("direccion") or "",
                                  key=f"es_dir_{v}")
        actual = (f"{sede['latitud']}, {sede['longitud']}"
                  if sede["latitud"] is not None else "")
        texto = st.text_input("Ubicación", value=actual, key=f"es_ubic_{v}",
                              help="Si la cambias, el distrito se recalcula solo.")
        activa = st.toggle("Activa", value=sede["activo"], key=f"es_activa_{v}",
                           help="Una sede inactiva no aparece al cotizar. Conserva sus precios "
                                "y su historial.")

        coords = extraer_coordenadas(texto) if texto else None
        error = None
        if texto and not coords:
            error = "No se reconocen las coordenadas."
        elif coords and coords != (sede["latitud"], sede["longitud"]):
            geo = db.distrito_de_coordenadas(coords[0], coords[1])
            if geo:
                destino = geo["distrito"].replace("_", " ").title()
                if geo.get("id_zona") != sede.get("id_zona"):
                    st.warning(f"La nueva ubicación está en {destino}, zona "
                               f"{geo.get('zona') or 'sin zona'}. El código {sede['codigo']} "
                               "se mantiene.")
                else:
                    st.caption(f"Nuevo distrito: {destino}")

        if st.button("Guardar sede", type="primary", width="stretch",
                     disabled=bool(error) or solo_lectura, key=f"es_guardar_{v}"):
            datos = {"nombre": nombre.strip(), "telefono": telefono.strip() or None,
                     "encargado": encargado.strip() or None,
                     "direccion": direccion.strip() or None, "activo": activa}
            if coords:
                datos["latitud"], datos["longitud"] = coords
            try:
                db.actualizar_sede(sede["id_sede"], datos)
                db.limpiar_cache()
                st.session_state.fer_mensaje = f"Sede {sede['codigo']} actualizada."
                _cambiar_modo(None)
            except Exception as e:
                st.error(_error(e))
        if error:
            st.caption(f":orange[{error}]")


# =============================================================== errores ===
def _error(e) -> str:
    detalle = str(e)
    if "uq_ferreteria_nombre" in detalle:
        return "Ya existe una ferretería con ese nombre."
    if "uq_ferreteria_ruc" in detalle:
        return "Ya hay una ferretería con ese RUC."
    if "uq_ferreteria_codigo" in detalle:
        return "Ese código de asociado ya está en uso."
    if "uq_zona_prefijo" in detalle:
        return "Ese prefijo ya lo usa otra zona."
    if "row-level security" in detalle or "permission denied" in detalle:
        return "No tienes permiso: el supervisor solo crea sedes en sus zonas."
    if "ZONA_NUEVA" in detalle:
        return "Esa ubicación no pertenece a ninguna zona. Hay que abrirla primero."
    return f"No se pudo guardar: {detalle}"
