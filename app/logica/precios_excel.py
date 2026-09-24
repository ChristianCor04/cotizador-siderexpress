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
from openpyxl.utils import get_column_letter

# Columnas que la plantilla lleva siempre
COLUMNAS_BASE = ["id_sku", "Producto", "Marca", "Unidad"]

# Encabezado que se usa cuando la ferretería cotiza igual en todas sus sedes.
# No puede coincidir con ningún código de sede.
COLUMNA_UNICA = "PRECIO"


def armar_plantilla(catalogo: list[dict], sedes: list[dict],
                    precios: list[dict], precio_unico: bool = False) -> pd.DataFrame:
    """Construye la tabla de precios.

    catalogo: [{id_sku, producto, marca, unidad}]
    sedes:    [{id_sede, codigo, nombre}]
    precios:  [{id_sede, id_sku, precio, activo}]

    Con precio_unico, la tabla trae UNA sola columna de precio en vez de una
    por sede. Sirve para las ferreterías que cotizan igual en todos sus
    locales: se escribe una vez y al guardar se replica a todas las sedes.
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

        if precio_unico:
            # Se muestra el primer precio que exista entre las sedes
            valores = [por_sede_sku[(s["id_sede"], sku["id_sku"])]["precio"]
                       for s in sedes
                       if (s["id_sede"], sku["id_sku"]) in por_sede_sku]
            fila[COLUMNA_UNICA] = valores[0] if valores else None
        else:
            for sede in sedes:
                precio = por_sede_sku.get((sede["id_sede"], sku["id_sku"]))
                fila[sede["codigo"]] = precio["precio"] if precio else None

        filas.append(fila)

    tabla = pd.DataFrame(filas)
    columnas_precio = ([COLUMNA_UNICA] if precio_unico
                       else [s["codigo"] for s in sedes])
    # Primero los productos que la ferretería ya vende
    tabla["_tiene"] = tabla[columnas_precio].notna().any(axis=1)
    tabla = tabla.sort_values(["_tiene", "Producto", "Marca"],
                              ascending=[False, True, True]).drop(columns="_tiene")
    return tabla.reset_index(drop=True)


def precios_iguales_en_sedes(sedes: list[dict], precios: list[dict]) -> bool:
    """¿Esta ferretería cotiza lo mismo en todas sus sedes?

    Se usa para proponer el modo de precio único al abrir la pantalla.
    """
    if len(sedes) <= 1:
        return False

    ids = [s["id_sede"] for s in sedes]
    por_sku = {}
    for p in precios:
        if p.get("activo", True) and p["id_sede"] in ids:
            por_sku.setdefault(p["id_sku"], set()).add(round(float(p["precio"]), 4))

    if not por_sku:
        return True          # sin precios todavía: lo más probable es que sí

    return all(len(valores) == 1 for valores in por_sku.values())


def exportar_excel(tabla: pd.DataFrame, nombre_ferreteria: str) -> bytes:
    """Convierte la plantilla en un archivo .xlsx descargable."""
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        tabla.to_excel(writer, index=False, sheet_name="Precios")

        hoja = writer.sheets["Precios"]

        # get_column_letter maneja cualquier cantidad de columnas. Hacer la
        # cuenta a mano con chr() se rompe pasada la Z: la letra 27 sería "[".
        anchos_base = [10, 34, 22, 14]        # id_sku, Producto, Marca, Unidad
        for i, ancho in enumerate(anchos_base, start=1):
            hoja.column_dimensions[get_column_letter(i)].width = ancho
        for i in range(len(anchos_base) + 1, len(tabla.columns) + 1):
            hoja.column_dimensions[get_column_letter(i)].width = 14

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
    # Dos formatos posibles: una columna por sede, o una sola para todas
    if COLUMNA_UNICA in tabla.columns:
        columnas_sede = {COLUMNA_UNICA: None}     # None = todas las sedes
    else:
        columnas_sede = {s["codigo"]: s["id_sede"] for s in sedes
                         if s["codigo"] in tabla.columns}

    if not columnas_sede:
        raise ValueError(
            "El archivo no tiene ninguna columna de precio que coincida con "
            f"las sedes de esta ferretería ({', '.join(s['codigo'] for s in sedes)}). "
            f"Tampoco tiene la columna «{COLUMNA_UNICA}»."
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

            # Con la columna única, el precio va a todas las sedes
            destinos = ([s["id_sede"] for s in sedes] if id_sede is None
                        else [id_sede])
            for destino in destinos:
                precios.append({
                    "id_sede": destino,
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
