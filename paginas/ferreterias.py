"""
PANTALLA DE FERRETERÍAS
=======================
Tres pasos, de arriba hacia abajo:
  1. Elegir o crear la ferretería.
  2. Sus sedes: elegir una o agregar otra.
  3. La cobertura de la sede elegida: distritos y nivel.

Reglas que impone la base, no esta pantalla:
  - El código de cada sede se genera solo: prefijo de la zona + siguiente
    número libre. No se edita: es la llave de la plantilla de Excel.
  - El distrito sale de las coordenadas.
  - Cada sede cubre su propio distrito como principal.
  - El supervisor crea y edita sedes y cobertura solo en sus zonas.
  - Nada se borra: ferreterías y sedes se desactivan.

El método de cada zona y los distritos sin ferretería principal están en
Seguimiento.
"""
import pandas as pd
import streamlit as st

import db
from logica.catalogo import es_identico, parecidos
from logica.geo import extraer_coordenadas

NIVELES = {1: "Principal", 2: "Secundaria", 3: "Terciaria"}
NIVEL_DE_TEXTO = {v: k for k, v in NIVELES.items()}


def _preparar_memoria():
    for clave, valor in {"fer_seleccionada": None, "fer_sede": None,
                         "fer_modo": None, "fer_version": 0}.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


def _cambiar_modo(modo, seleccionada="sin cambio"):
    """Cambia lo que muestra la pantalla y limpia los formularios abiertos."""
    st.session_state.fer_modo = modo
    if seleccionada != "sin cambio":
        st.session_state.fer_seleccionada = seleccionada
        st.session_state.fer_sede = None
    st.session_state.fer_version += 1
    st.rerun()


def mostrar(usuario: dict):
    if usuario["rol"] not in ("supervisor", "master"):
        st.info("Esta pantalla es para supervisores y administradores.")
        return
    _preparar_memoria()

    mensaje = st.session_state.pop("fer_mensaje", None)
    if mensaje:
        st.success(mensaje)

    ferreterias = db.ferreterias_todas()
    sedes = db.sedes_mapa()

    elegida = _paso_ferreteria(ferreterias, sedes)
    modo = st.session_state.fer_modo

    if modo == "nueva_ferreteria":
        with st.container(border=True):
            _form_nueva_ferreteria(ferreterias)
        return
    if elegida is None:
        return
    if modo == "editar_ferreteria":
        with st.container(border=True):
            _form_editar_ferreteria(elegida, ferreterias)
        return

    propias = [s for s in sedes if s["id_ferreteria"] == elegida["id_ferreteria"]]
    sede = _paso_sedes(usuario, elegida, propias)
    if sede and st.session_state.fer_modo != "nueva_sede":
        _paso_cobertura(usuario, sede)


# =============================================================== paso 1 ===
def _paso_ferreteria(ferreterias, sedes):
    with st.container(border=True):
        st.markdown("**1 · Ferretería**")
        ver_inactivas = st.toggle("Incluir inactivas", key="fer_ver_inactivas",
                                  disabled=not any(not f["activo"] for f in ferreterias))
        lista = [f for f in ferreterias if f["activo"] or ver_inactivas]
        ids = [f["id_ferreteria"] for f in lista]
        por_id = {f["id_ferreteria"]: f for f in lista}

        col_s, col_n = st.columns([3, 1], vertical_alignment="bottom")
        actual = st.session_state.fer_seleccionada
        elegido = col_s.selectbox(
            "Ferretería", [None] + ids,
            index=([None] + ids).index(actual) if actual in ids else 0,
            format_func=lambda i: "Elige una ferretería…" if i is None
            else por_id[i]["nombre"] + ("" if por_id[i]["activo"] else " · inactiva"),
            label_visibility="collapsed", key=f"fer_selector_{st.session_state.fer_version}")
        if col_n.button("＋ Nueva ferretería", width="stretch"):
            _cambiar_modo("nueva_ferreteria", None)

        if elegido != actual:
            st.session_state.fer_seleccionada = elegido
            st.session_state.fer_sede = None
            st.session_state.fer_modo = None
            st.rerun()

        if elegido is None:
            return None
        ferreteria = por_id[elegido]
        activas = sum(1 for s in sedes if s["id_ferreteria"] == elegido and s["activo"])
        col_d, col_e = st.columns([3, 1], vertical_alignment="center")
        detalle = f"{activas} sede{'s' if activas != 1 else ''} activa{'s' if activas != 1 else ''}"
        if ferreteria.get("ruc"):
            detalle = f"RUC {ferreteria['ruc']} · " + detalle
        col_d.caption(detalle)
        if col_e.button("Editar ferretería", width="stretch"):
            _cambiar_modo("editar_ferreteria")
        return ferreteria


# =============================================================== paso 2 ===
def _paso_sedes(usuario, ferreteria, propias):
    with st.container(border=True):
        col_t, col_b = st.columns([3, 1], vertical_alignment="center")
        col_t.markdown(f"**2 · Sedes de {ferreteria['nombre']}**")
        if col_b.button("＋ Nueva sede", width="stretch"):
            _cambiar_modo("nueva_sede")

        if st.session_state.fer_modo == "nueva_sede":
            _form_nueva_sede(usuario, ferreteria)
            return None

        if not propias:
            st.caption("Esta ferretería todavía no tiene sedes.")
            return None

        tabla = pd.DataFrame([{
            "Código": s["codigo"], "Sede": s["sede"],
            "Distrito": (s["distrito"] or "").replace("_", " ").title(),
            "Zona": s["zona"] or "Sin zona",
            "Estado": "Activa" if s["activo"] else "Inactiva",
            "Ubicación": {"coincide": "OK", "sin_coordenadas": "Sin coordenadas",
                          "no_coincide": "Distrito no coincide",
                          "fuera_de_poligonos": "Fuera de los mapas"}.get(s["verificacion"], ""),
        } for s in propias])
        evento = st.dataframe(
            tabla, hide_index=True, width="stretch", on_select="rerun",
            selection_mode="single-row",
            key=f"fer_tabla_sedes_{ferreteria['id_ferreteria']}_{st.session_state.fer_version}")
        filas = evento.selection.rows if evento and evento.selection else []
        if filas:
            st.session_state.fer_sede = propias[filas[0]]["id_sede"]
        elif st.session_state.fer_sede not in {s["id_sede"] for s in propias}:
            st.session_state.fer_sede = None

        if st.session_state.fer_sede is None:
            st.caption("Haz clic en una sede para editarla y ver su cobertura.")
            return None
        return next(s for s in propias if s["id_sede"] == st.session_state.fer_sede)


# =============================================================== paso 3 ===
def _paso_cobertura(usuario, sede):
    mis_zonas = _zonas_del_usuario(usuario)
    solo_lectura = mis_zonas is not None and sede.get("id_zona") not in mis_zonas

    with st.container(border=True):
        st.markdown(f"**3 · Cobertura de {sede['codigo']} · {sede['sede']}**")
        with st.expander("Datos de la sede"):
            _form_editar_sede(sede, usuario)

        actual = db.cobertura_de_sede(sede["id_sede"])
        if solo_lectura:
            st.info(f"Esta sede es de la zona {sede.get('zona') or 'sin zona'}, que no cubres. "
                    "Puedes ver su cobertura, pero no editarla.")
        _tabla_cobertura(sede, actual, solo_lectura)
        if not solo_lectura:
            _agregar_cobertura(sede, actual)


def _tabla_cobertura(sede, actual, solo_lectura):
    """Distritos que cubre la sede. El nivel se cambia en la misma tabla."""
    if not actual:
        st.caption("Esta sede todavía no cubre ningún distrito.")
        return

    propio = sede.get("id_distrito")
    original = pd.DataFrame([{
        "id_distrito": c["id_distrito"],
        "Distrito": (c["distrito"] or "").replace("_", " ").title()
                    + (" · distrito propio" if c["id_distrito"] == propio else ""),
        "Zona": c["zona"] or "Sin zona",
        "Nivel": NIVELES.get(c["nivel"], str(c["nivel"])),
        "Quitar": False,
    } for c in actual])

    v = f"{st.session_state.fer_version}_{sede['id_sede']}"
    editada = st.data_editor(
        original, hide_index=True, width="stretch", disabled=solo_lectura,
        column_order=["Distrito", "Zona", "Nivel", "Quitar"],
        column_config={
            "Distrito": st.column_config.TextColumn(disabled=True),
            "Zona": st.column_config.TextColumn(disabled=True),
            "Nivel": st.column_config.SelectboxColumn(options=list(NIVELES.values()), required=True),
            "Quitar": st.column_config.CheckboxColumn(),
        }, key=f"cob_tabla_{v}")
    if solo_lectura:
        return

    cambios_nivel, quitar, ignorados = {}, [], False
    for antes, despues in zip(original.to_dict("records"), editada.to_dict("records")):
        es_propio = antes["id_distrito"] == propio
        if despues["Quitar"]:
            if es_propio:
                ignorados = True
            else:
                quitar.append(antes["id_distrito"])
        elif despues["Nivel"] != antes["Nivel"]:
            if es_propio and despues["Nivel"] != NIVELES[1]:
                ignorados = True
            else:
                cambios_nivel.setdefault(NIVEL_DE_TEXTO[despues["Nivel"]], []).append(antes["id_distrito"])

    if ignorados:
        st.caption(":orange[El distrito propio de la sede siempre es principal: ese cambio no se guarda.]")

    hay_cambios = bool(cambios_nivel or quitar)
    if st.button("Guardar cambios de cobertura", type="primary", disabled=not hay_cambios,
                 key=f"cob_guardar_{v}"):
        def aplicar():
            for nivel, ids in cambios_nivel.items():
                db.cubrir_distritos(sede["id_sede"], nivel, ids)
            if quitar:
                db.quitar_cobertura(sede["id_sede"], quitar)
        partes = []
        if cambios_nivel:
            partes.append(f"{sum(len(i) for i in cambios_nivel.values())} cambio(s) de nivel")
        if quitar:
            partes.append(f"{len(quitar)} distrito(s) quitados")
        _guardar_cobertura(aplicar, "Cobertura actualizada: " + ", ".join(partes) + ".")


def _agregar_cobertura(sede, actual):
    v = f"{st.session_state.fer_version}_{sede['id_sede']}"
    ya = {c["id_distrito"] for c in actual}
    distritos = [d for d in db.catalogo_distritos() if d["id_distrito"] not in ya]
    nombre = {d["id_distrito"]: _nombre_distrito(d) for d in distritos}

    col_d, col_n, col_b = st.columns([3, 1.2, 1], vertical_alignment="bottom")
    elegidos = col_d.multiselect("Agregar distritos", list(nombre), format_func=nombre.get,
                                 placeholder="Elige uno o varios", key=f"cob_add_{v}")
    nivel = col_n.selectbox("Nivel", [1, 2, 3], format_func=NIVELES.get, key=f"cob_nivel_{v}")
    if col_b.button("Agregar", width="stretch", disabled=not elegidos, key=f"cob_btn_{v}"):
        _guardar_cobertura(lambda: db.cubrir_distritos(sede["id_sede"], nivel, elegidos),
                           f"{len(elegidos)} distrito(s) agregados como {NIVELES[nivel].lower()}.")


# ====================================================== formularios ===


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



def _zonas_del_usuario(usuario) -> set | None:
    """Zonas que cubre el usuario. None = todas (master)."""
    if usuario["rol"] == "master":
        return None
    return {z.get("id_zona") for z in (usuario.get("rel_usuarios_zonas") or [])}


def _nombre_distrito(d) -> str:
    return (f"{(d.get('distrito') or d.get('nombre') or '').replace('_', ' ').title()} · "
            f"{(d.get('provincia') or '').replace('_', ' ').title()}")


def _guardar_cobertura(accion, mensaje):
    try:
        accion()
        db.limpiar_cache()
        st.session_state.fer_mensaje = mensaje
        st.rerun()
    except Exception as e:
        st.error(_error(e))


# ============================================================= errores ===
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
