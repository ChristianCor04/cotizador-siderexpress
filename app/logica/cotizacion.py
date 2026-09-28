"""
LÓGICA DE COTIZACIÓN
====================
Aquí vive la regla del negocio: a qué ferreterías se les pide precio y
cuánto sale la canasta en cada una.

Python puro: no sabe de Streamlit ni de Supabase. Recibe listas y
diccionarios, y devuelve listas y diccionarios.

Si quieres cambiar CÓMO se cotiza, este es el archivo.
Si quieres cambiar los MONTOS o RADIOS, eso está en Supabase,
en la tabla m_reglas_cotizacion.
"""
from logica.geo import sedes_cercanas


def monto_referencial(lineas: list[dict], precios_ref: dict[int, float]) -> float:
    """Cuánto vale la canasta a precio promedio de mercado.

    Este monto NO es lo que paga el cliente: solo sirve para decidir
    qué tan lejos se buscan ferreterías.
    """
    total = 0.0
    for linea in lineas:
        promedio = precios_ref.get(linea["id_producto"])
        if promedio:
            total += promedio * linea["cantidad"]
    return round(total, 2)


def elegir_regla(monto: float, hay_coordenadas: bool, reglas: list[dict]) -> dict | None:
    """Qué regla aplica según el monto y si tenemos ubicación exacta."""
    for r in reglas:
        if r["usa_coordenadas"] != hay_coordenadas:
            continue
        desde = float(r["monto_desde"])
        hasta = float(r["monto_hasta"]) if r["monto_hasta"] is not None else None
        if monto >= desde and (hasta is None or monto < hasta):
            return r
    return None


def sedes_candidatas(regla, sedes, coordenadas=None, id_distrito=None,
                     id_provincia=None, top_n=5) -> list[dict]:
    """Las sedes que van a competir por esta cotización."""
    if regla is None:
        return []

    if regla["alcance"] == "radio":
        if coordenadas is None:
            return []
        lat, lon = coordenadas
        cercanas = sedes_cercanas(lat, lon, sedes, top_n=top_n)
        radio = float(regla["radio_km"])
        return [s for s in cercanas if s["distancia_km"] <= radio]

    if regla["alcance"] == "distrito":
        return [s for s in sedes if s["id_distrito"] == id_distrito]

    if regla["alcance"] == "provincia":
        return [s for s in sedes if s["id_provincia"] == id_provincia]

    return []


def _unir_mismo_sku(detalle: list[dict]) -> list[dict]:
    """Junta en una sola línea las que terminaron en el mismo SKU.

    Pasa cuando una fila pide «la marca más barata» y otra pide esa misma
    marca: en pantalla son dos filas distintas, pero en esa ferretería
    resuelven al mismo producto. La base no admite el mismo SKU dos veces en
    una cotización, así que se suman aquí.

    El monto no cambia: se suman los subtotales tal cual, y si las dos filas
    tenían precios distintos, queda como precio negociado el promedio que
    reproduce exactamente ese total.
    """
    unidas = {}
    for d in detalle:
        previa = unidas.get(d["id_sku"])
        if previa is None:
            unidas[d["id_sku"]] = {**d, "filas_unidas": 1}
            continue

        cantidad = previa["cantidad"] + d["cantidad"]
        subtotal = round(previa["subtotal"] + d["subtotal"], 2)
        precio_efectivo = round(subtotal / cantidad, 4)

        previa.update({
            "cantidad": cantidad,
            "subtotal": subtotal,
            "precio_manual": (None if abs(precio_efectivo - previa["precio_lista"]) < 0.0001
                              else precio_efectivo),
            "filas_unidas": previa["filas_unidas"] + 1,
        })
    return list(unidas.values())


def cotizar_en_sedes(lineas: list[dict], sedes: list[dict],
                     precios: list[dict],
                     una_por_ferreteria: bool = True) -> list[dict]:
    """Calcula el monto de la canasta en cada sede.

    Devuelve TODAS las sedes, incluso las que no tienen todo, indicando
    qué les falta. El panel las agrupa después por cantidad de faltantes.

    Cada línea puede pedir una marca concreta (trae id_sku) o dejarla
    abierta (trae id_producto): en ese caso se toma el más barato.
    """
    # Index rápido: precio por (sede, sku)
    por_sede = {}
    for p in precios:
        por_sede.setdefault(p["id_sede"], {})[p["id_sku"]] = p

    resultados = []
    for sede in sedes:
        disponibles = por_sede.get(sede["id_sede"], {})
        detalle, faltantes, total = [], [], 0.0

        for linea in lineas:
            opciones = [
                disponibles[sku]
                for sku in linea["skus_posibles"]
                if sku in disponibles
            ]
            if not opciones:
                faltantes.append(linea["descripcion"])
                continue

            elegido = min(opciones, key=lambda p: p["precio"])
            precio = linea.get("precio_manual") or elegido["precio"]
            subtotal = round(precio * linea["cantidad"], 2)
            total += subtotal

            detalle.append({
                "id_sku": elegido["id_sku"],
                "id_precio": elegido["id_precio"],
                "descripcion": linea["descripcion"],
                "cantidad": linea["cantidad"],
                "precio_lista": elegido["precio"],
                "precio_manual": linea.get("precio_manual"),
                "unidad": linea.get("unidad"),
                "motivo": linea.get("motivo"),
                "autorizado_por": linea.get("autorizado_por"),
                "subtotal": subtotal,
            })

        detalle = _unir_mismo_sku(detalle)

        resultados.append({
            "id_sede": sede["id_sede"],
            "sede": sede["sede"],
            "ferreteria": sede["ferreteria"],
            "distrito": sede.get("distrito"),
            "distancia_km": sede.get("distancia_km"),
            "n_faltantes": len(faltantes),
            "faltantes": faltantes,
            "canasta_completa": len(faltantes) == 0,
            "monto": round(total, 2),
            "detalle": detalle,
        })

    # Primero las más completas; dentro de cada grupo, la más barata; y si
    # dos empatan en monto, la más cercana.
    resultados.sort(key=lambda r: (r["n_faltantes"], r["monto"],
                                   r["distancia_km"] if r["distancia_km"] is not None else 0))

    # Una sola sede por ferretería, elegida DESPUÉS de cotizar: la que le
    # conviene más al cliente. Si no, una cadena con varios locales llenaría
    # la lista con la misma ferretería.
    if una_por_ferreteria:
        vistas, unicos = set(), []
        for r in resultados:
            if r["ferreteria"] not in vistas:
                vistas.add(r["ferreteria"])
                unicos.append(r)
        return unicos

    return resultados
