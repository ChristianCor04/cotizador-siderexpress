"""
PANTALLA DE PRECIOS
===================
Gira alrededor del estado diario: qué ferreterías ya confirmaron sus precios
hoy y cuáles faltan. Esa es la lista de trabajo de la mañana.

Bloques:
  Arriba     Contadores del día y botones de Excel
  Izquierda  Ferreterías con semáforo de frescura
  Derecha    Tabla de precios, una columna por sede
"""
from datetime import datetime

import pandas as pd
import streamlit as st

import config
import db
from logica.precios_excel import (armar_plantilla, comparar_con_actuales,
                                  exportar_excel, leer_excel)

# Colores del semáforo según hace cuánto se confirmaron los precios
SEMAFORO = {
    "hoy":            ("🟢", "Confirmados hoy"),
    "ayer":           ("🟡", "Ayer"),
    "esta semana":    ("🟡", "Esta semana"),
    "desactualizado": ("🔴", "Más de 7 días"),
}


def _preparar_memoria():
    valores = {
        "precios_ferreteria": None,   # ferretería abierta
        "precios_tabla": None,        # lo que se está editando
        "precios_version": 0,         # fuerza el refresco de la tabla
        "precios_carga": None,        # resultado del Excel cargado
    }
    for clave, valor in valores.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


def mostrar(usuario: dict):
    _preparar_memoria()

    estado = db.estado_precios()
    _encabezado(estado)

    col_lista, col_tabla = st.columns([1, 2.6], gap="medium")
    with col_lista:
        _lista_ferreterias(estado)
    with col_tabla:
        _panel_ferreteria(usuario, estado)


# ---------------------------------------------------------------- encabezado
def _encabezado(estado):
    st.markdown("##### Precios")
    st.caption(datetime.now().strftime("%A %d de %B").capitalize())

    # Una ferretería cuenta como confirmada si TODAS sus sedes lo están
    por_ferreteria = {}
    for fila in estado:
        actual = por_ferreteria.get(fila["ferreteria"])
        peor = {"hoy": 0, "ayer": 1, "esta semana": 2, "desactualizado": 3}
        if actual is None or peor[fila["estado"]] > peor[actual]:
            por_ferreteria[fila["ferreteria"]] = fila["estado"]

    hoy = sum(1 for e in por_ferreteria.values() if e == "hoy")
    viejos = sum(1 for e in por_ferreteria.values() if e == "desactualizado")
    pendientes = len(por_ferreteria) - hoy - viejos

    c1, c2, c3 = st.columns(3)
    c1.metric("Confirmadas hoy", hoy)
    c2.metric("Pendientes", pendientes)
    c3.metric("Más de 7 días", viejos)


# ----------------------------------------------------------------- izquierda
def _lista_ferreterias(estado):
    buscar = st.text_input("Buscar ferretería", label_visibility="collapsed",
                           placeholder="Buscar ferretería")

    solo_pendientes = st.toggle("Solo pendientes", value=False)

    # Agrupar las sedes por ferretería
    ferreterias = {}
    for fila in estado:
        f = ferreterias.setdefault(fila["ferreteria"], {
            "id_ferreteria": fila["id_ferreteria"],
            "nombre": fila["ferreteria"],
            "sedes": [],
            "productos": 0,
        })
        f["sedes"].append(fila)
        f["productos"] += fila["productos"] or 0

    for f in ferreterias.values():
        peor = {"hoy": 0, "ayer": 1, "esta semana": 2, "desactualizado": 3}
        f["estado"] = max((s["estado"] for s in f["sedes"]), key=lambda e: peor[e])
        f["ultima"] = max((s["ultima_confirmacion"] or "" for s in f["sedes"]))

    lista = sorted(ferreterias.values(),
                   key=lambda f: ({"desactualizado": 0, "esta semana": 1,
                                   "ayer": 2, "hoy": 3}[f["estado"]], f["nombre"]))

    if buscar:
        lista = [f for f in lista if buscar.lower() in f["nombre"].lower()]
    if solo_pendientes:
        lista = [f for f in lista if f["estado"] != "hoy"]

    if not lista:
        st.caption("Sin resultados.")
        return

    for f in lista:
        icono, texto = SEMAFORO[f["estado"]]
        abierta = st.session_state.precios_ferreteria == f["id_ferreteria"]

        with st.container(border=True):
            st.markdown(f"**{f['nombre']}**")
            detalle = f"{len(f['sedes'])} sede(s) · {f['productos']} precios"
            st.caption(f"{icono} {texto} · {detalle}")

            if st.button("Abrir" if not abierta else "Abierta",
                         key=f"abrir_fer_{f['id_ferreteria']}", width="stretch",
                         type="primary" if abierta else "secondary", disabled=abierta):
                st.session_state.precios_ferreteria = f["id_ferreteria"]
                st.session_state.precios_tabla = None
                st.session_state.precios_carga = None
                st.session_state.precios_version += 1
                st.rerun()


# ------------------------------------------------------------------ derecha
def _panel_ferreteria(usuario, estado):
    id_ferreteria = st.session_state.precios_ferreteria
    if id_ferreteria is None:
        st.info("Elige una ferretería de la lista para ver y editar sus precios.")
        return

    sedes_estado = [e for e in estado if e["id_ferreteria"] == id_ferreteria]
    if not sedes_estado:
        st.warning("Esa ferretería ya no tiene sedes activas.")
        return

    nombre = sedes_estado[0]["ferreteria"]
    sedes = db.sedes_de_ferreteria(id_ferreteria)
    catalogo = db.catalogo_skus()
    precios = db.precios_de_ferreteria(id_ferreteria)

    with st.container(border=True):
        _cabecera_panel(nombre, sedes_estado, id_ferreteria)
        st.divider()
        _tabla_precios(nombre, sedes, catalogo, precios)
        st.divider()
        _bloque_excel(nombre, sedes, catalogo, precios)


def _cabecera_panel(nombre, sedes_estado, id_ferreteria):
    col_info, col_boton = st.columns([2, 1])

    with col_info:
        st.markdown(f"**{nombre}**")
        peor = max(sedes_estado, key=lambda s: {"hoy": 0, "ayer": 1,
                                                "esta semana": 2, "desactualizado": 3}[s["estado"]])
        icono, texto = SEMAFORO[peor["estado"]]
        quien = peor.get("actualizado_por") or "—"
        st.caption(f"{icono} {texto} · última carga por {quien}")

    with col_boton:
        if st.button("✓ Mantienen precios", width="stretch",
                     help="Registra que la ferretería confirmó hoy sus precios, "
                          "sin cambiar ningún monto."):
            try:
                n = db.confirmar_precios_ferreteria(id_ferreteria)
                db.limpiar_cache()
                st.success(f"{n} precios confirmados hoy.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo confirmar: {e}")


def _tabla_precios(nombre, sedes, catalogo, precios):
    """Una columna de precio por sede. Se editan las celdas que haga falta."""
    if st.session_state.precios_tabla is None:
        st.session_state.precios_tabla = armar_plantilla(catalogo, sedes, precios)

    tabla = st.session_state.precios_tabla
    columnas_sede = [s["codigo"] for s in sedes]

    # Aviso si hay precios distintos entre sedes de la misma ferretería
    if len(sedes) > 1:
        con_precio = tabla[columnas_sede]
        distintos = con_precio.apply(
            lambda fila: fila.dropna().nunique() > 1, axis=1).sum()
        if distintos:
            st.caption(f"⚠ {distintos} producto(s) con precio diferente entre sedes.")

    configuracion = {
        "id_sku": None,     # oculta: es la llave, no debe editarse
        "Producto": st.column_config.TextColumn(disabled=True, width="large"),
        "Marca": st.column_config.TextColumn(disabled=True, width="medium"),
        "Unidad": st.column_config.TextColumn(disabled=True, width="small"),
    }
    for sede in sedes:
        configuracion[sede["codigo"]] = st.column_config.NumberColumn(
            sede["codigo"], min_value=0.01, step=0.10, format="%.2f",
            help=f"{sede['nombre']} · vacío = no lo vende",
        )

    editada = st.data_editor(
        tabla, key=f"tabla_precios_{st.session_state.precios_version}",
        column_config=configuracion, hide_index=True, width="stretch",
        num_rows="fixed", height=360,
    )

    cambios = _detectar_cambios(tabla, editada, sedes)

    col_info, col_botones = st.columns([2, 1])
    col_info.caption(f"{len(cambios)} precio(s) modificado(s) sin guardar"
                     if cambios else "Sin cambios pendientes")

    with col_botones:
        if st.button("Guardar cambios", type="primary", width="stretch",
                     disabled=not cambios):
            try:
                resultado = db.guardar_precios(cambios, modo="actualizar")
                db.limpiar_cache()
                st.session_state.precios_tabla = None
                st.session_state.precios_version += 1
                st.success(f"Guardado: {resultado['actualizados']} actualizados, "
                           f"{resultado['nuevos']} nuevos.")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo guardar: {e}")


def _detectar_cambios(original, editada, sedes) -> list[dict]:
    """Compara la tabla antes y después de editarla."""
    cambios = []
    por_sede = {s["codigo"]: s["id_sede"] for s in sedes}

    for i in range(len(editada)):
        id_sku = int(editada.iloc[i]["id_sku"])
        for codigo, id_sede in por_sede.items():
            antes = original.iloc[i][codigo]
            ahora = editada.iloc[i][codigo]

            if pd.isna(ahora):
                continue                      # vaciar no borra: se hace con reemplazar
            if pd.isna(antes) or round(float(antes), 4) != round(float(ahora), 4):
                cambios.append({
                    "id_sede": id_sede,
                    "id_sku": id_sku,
                    "precio": round(float(ahora), 4),
                    "fuente": "asesor",
                })
    return cambios


# -------------------------------------------------------------------- Excel
def _bloque_excel(nombre, sedes, catalogo, precios):
    st.markdown("**Cargar desde Excel**")

    col_bajar, col_subir = st.columns(2)

    with col_bajar:
        plantilla = armar_plantilla(catalogo, sedes, precios)
        st.download_button(
            "⬇ Descargar plantilla",
            data=exportar_excel(plantilla, nombre),
            file_name=f"precios_{nombre.lower().replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
            help="Viene con los precios actuales. Solo edita las columnas de precio.",
        )

    with col_subir:
        archivo = st.file_uploader("Subir archivo", type=["xlsx"],
                                   label_visibility="collapsed")

    if archivo is None:
        return

    try:
        lectura = leer_excel(archivo, catalogo, sedes)
    except ValueError as e:
        st.error(str(e))
        return
    except Exception as e:
        st.error(f"No se pudo leer el archivo: {e}")
        return

    comparacion = comparar_con_actuales(lectura["precios"], precios)
    _resumen_carga(lectura, comparacion, nombre)


def _resumen_carga(lectura, comparacion, nombre):
    """Muestra qué va a pasar ANTES de tocar la base."""
    st.markdown("**Esto es lo que va a pasar**")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cambian", len(comparacion["cambian"]))
    c2.metric("Nuevos", len(comparacion["agregados"]))
    c3.metric("Iguales", comparacion["iguales"])
    c4.metric("Saldrían", len(comparacion["saldrian"]),
              help="Solo se desactivan si eliges «Reemplazar la lista».")

    if comparacion["cambian"]:
        with st.expander(f"Ver los {len(comparacion['cambian'])} cambios"):
            st.dataframe(pd.DataFrame([{
                "Producto": c["_nombre"],
                "Sede": c["_sede"],
                "Antes": c["precio_anterior"],
                "Ahora": c["precio"],
                "Variación": f"{(c['precio'] / c['precio_anterior'] - 1) * 100:+.1f}%",
            } for c in comparacion["cambian"]]), hide_index=True, width="stretch")

    if lectura["errores"]:
        st.warning(f"**{len(lectura['errores'])} fila(s) se van a ignorar:**\n\n"
                   + "\n".join(f"- {e}" for e in lectura["errores"][:10]))

    if not lectura["precios"]:
        st.error("El archivo no tiene ningún precio válido.")
        return

    st.markdown("**¿Cómo aplicar?**")
    modo = st.radio(
        "Modo", ["actualizar", "reemplazar"], label_visibility="collapsed",
        format_func=lambda m: (
            "Actualizar · solo toca los productos del archivo"
            if m == "actualizar" else
            "Reemplazar la lista · además desactiva los que no aparecen"
        ),
    )

    if modo == "reemplazar":
        st.warning(f"Se desactivarían {len(comparacion['saldrian'])} precios que "
                   "no están en el archivo. No se borran: se pueden reactivar.")
        confirmacion = st.text_input(
            f"Escribe «{nombre}» para confirmar", key="confirmar_reemplazo")
        habilitado = confirmacion.strip().lower() == nombre.strip().lower()
    else:
        habilitado = True

    if st.button("Aplicar cambios", type="primary", width="stretch",
                 disabled=not habilitado):
        try:
            limpios = [{k: v for k, v in p.items() if not k.startswith("_")}
                       for p in lectura["precios"]]
            resultado = db.guardar_precios(limpios, modo=modo)
            db.limpiar_cache()
            st.session_state.precios_tabla = None
            st.session_state.precios_version += 1
            st.success(
                f"Listo: {resultado['actualizados']} actualizados, "
                f"{resultado['nuevos']} nuevos, {resultado['desactivados']} desactivados."
            )
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo aplicar: {e}")
