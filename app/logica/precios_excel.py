"""
PLANTILLA Y LECTURA DE EXCEL DE PRECIOS
=======================================
Python puro: recibe y devuelve listas y DataFrames, sin Streamlit ni Supabase.

La plantilla se descarga YA LLENA con los productos y precios actuales.
El usuario solo edita la columna de precio de cada sede. Así no hay que
escribir nombres a mano y se evita el problema de "BC 6mm" contra "BC 6 mm".

La columna oculta `id_sku` es la que empareja: por eso NO debe borrarse.
"""
from io import BytesIO

import pandas as pd

# Columnas que la plantilla lleva siempre
COLUMNAS_BASE = ["id_sku", "Producto", "Marca", "Unidad"]


def armar_plantilla(catalogo: list[dict], sedes: list[dict],
                    precios: list[dict]) -> pd.DataFrame:
    """Construye la tabla con una columna de precio por sede.

    catalogo: [{id_sku, producto, marca, unidad}]
    sedes:    [{id_sede, codigo, nombre}]
    precios:  [{id_sede, id_sku, precio, activo}]
    """
    por_sede_sku = {(p["id_sede"], p["id_sku"]): p
                    for p in precios if p.get("activo", True)}

    filas = []
    for sku in catalogo:
        fila = {
            "id_sku": sku["id_sku"],
            "Producto": sku["producto"],
            "Marca": sku["marca"],
            "Unidad": sku.get("unidad") or "",
        }
        for sede in sedes:
            precio = por_sede_sku.get((sede["id_sede"], sku["id_sku"]))
            fila[sede["codigo"]] = precio["precio"] if precio else None
        filas.append(fila)

    tabla = pd.DataFrame(filas)
    # Primero los productos que la ferretería ya vende
    columnas_precio = [s["codigo"] for s in sedes]
    tabla["_tiene"] = tabla[columnas_precio].notna().any(axis=1)
    tabla = tabla.sort_values(["_tiene", "Producto", "Marca"],
                              ascending=[False, True, True]).drop(columns="_tiene")
    return tabla.reset_index(drop=True)


def exportar_excel(tabla: pd.DataFrame, nombre_ferreteria: str) -> bytes:
    """Convierte la plantilla en un archivo .xlsx descargable."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        tabla.to_excel(writer, index=False, sheet_name="Precios")

        hoja = writer.sheets["Precios"]
        # Anchos cómodos para leer
        anchos = {"A": 10, "B": 34, "C": 22, "D": 14}
        for letra, ancho in anchos.items():
            hoja.column_dimensions[letra].width = ancho
        for i in range(len(COLUMNAS_BASE), len(tabla.columns)):
            hoja.column_dimensions[chr(ord("A") + i)].width = 14

        # Encabezados en negrita y fijos al desplazar
        for celda in hoja[1]:
            celda.font = celda.font.copy(bold=True)
        hoja.freeze_panes = "B2"

    return buffer.getvalue()


def leer_excel(archivo, catalogo: list[dict], sedes: list[dict]) -> dict:
    """Lee el archivo cargado y lo compara con lo que hay en la base.

    Devuelve un resumen para mostrar ANTES de aplicar nada:
      precios   -> lo que se va a guardar
      errores   -> filas que se van a ignorar, con el motivo
      resumen   -> conteos para la pantalla
    """
    tabla = pd.read_excel(archivo)

    faltantes = [c for c in ["id_sku"] if c not in tabla.columns]
    if faltantes:
        raise ValueError(
            "El archivo no tiene la columna id_sku. "
            "Usa la plantilla que descargas desde esta pantalla."
        )

    skus_validos = {c["id_sku"] for c in catalogo}
    nombres = {c["id_sku"]: f"{c['producto']} · {c['marca']}" for c in catalogo}
    columnas_sede = {s["codigo"]: s["id_sede"] for s in sedes
                     if s["codigo"] in tabla.columns}

    if not columnas_sede:
        raise ValueError(
            "El archivo no tiene ninguna columna de precio que coincida con "
            f"las sedes de esta ferretería ({', '.join(s['codigo'] for s in sedes)})."
        )

    precios, errores = [], []

    for i, fila in tabla.iterrows():
        numero = i + 2                      # +2: la fila 1 son los encabezados
        id_sku = fila.get("id_sku")

        if pd.isna(id_sku):
            continue                        # fila vacía, se ignora en silencio

        try:
            id_sku = int(id_sku)
        except (TypeError, ValueError):
            errores.append(f"Fila {numero}: el id_sku «{id_sku}» no es válido.")
            continue

        if id_sku not in skus_validos:
            producto = fila.get("Producto", "")
            errores.append(f"Fila {numero}: «{producto}» no está en el catálogo.")
            continue

        for codigo, id_sede in columnas_sede.items():
            valor = fila.get(codigo)
            if pd.isna(valor) or str(valor).strip() == "":
                continue                    # sin precio = esa sede no lo vende

            try:
                precio = float(valor)
            except (TypeError, ValueError):
                errores.append(
                    f"Fila {numero}, columna {codigo}: «{valor}» no es un número.")
                continue

            if precio <= 0:
                errores.append(
                    f"Fila {numero}, columna {codigo}: el precio debe ser mayor a 0.")
                continue

            precios.append({
                "id_sede": id_sede,
                "id_sku": id_sku,
                "precio": round(precio, 4),
                "fuente": "relevamiento",
                "_nombre": nombres.get(id_sku, ""),
                "_sede": codigo,
            })

    return {
        "precios": precios,
        "errores": errores,
        "columnas_sede": list(columnas_sede),
    }


def comparar_con_actuales(precios_nuevos: list[dict],
                          precios_actuales: list[dict]) -> dict:
    """Qué va a pasar si se aplica el archivo. Se muestra antes de guardar."""
    actuales = {(p["id_sede"], p["id_sku"]): p
                for p in precios_actuales if p.get("activo", True)}
    nuevos = {(p["id_sede"], p["id_sku"]) for p in precios_nuevos}

    cambian, iguales, agregados = [], 0, []
    for p in precios_nuevos:
        clave = (p["id_sede"], p["id_sku"])
        actual = actuales.get(clave)
        if actual is None:
            agregados.append(p)
        elif round(float(actual["precio"]), 4) != round(p["precio"], 4):
            cambian.append({**p, "precio_anterior": float(actual["precio"])})
        else:
            iguales += 1

    # Los que están activos hoy pero no vienen en el archivo
    saldrian = [p for clave, p in actuales.items() if clave not in nuevos]

    return {
        "cambian": cambian,
        "agregados": agregados,
        "iguales": iguales,
        "saldrian": saldrian,
    }
