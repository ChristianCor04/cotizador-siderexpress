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
from logica.geo import distancia_km, sedes_cercanas


def monto_referencial(lineas: list[dict], precios_ref: dict) -> float:
    """Cuánto vale la canasta a precio promedio de mercado.

    Este monto NO es lo que paga el cliente: solo sirve para decidir qué tan
    amplia es la búsqueda de ferreterías.

    Cada línea se valora con los SKU que realmente pidió: su producto, su
    unidad y su marca, si la eligió. Si no eligió marca, se promedian las
    marcas de esa unidad, pesando por cuántas sedes tienen cada una. Nunca se
    mezclan unidades: la varilla y la tonelada tienen precios incomparables.

    precios_ref: {id_sku: (promedio, sedes)}
    """
    total = 0.0
    for linea in lineas:
        suma, pesos = 0.0, 0
        for id_sku in linea.get("skus_posibles") or []:
            dato = precios_ref.get(id_sku)
            if not dato:
                continue
            promedio, sedes = dato if isinstance(dato, tuple) else (dato, 1)
            peso = max(int(sedes or 0), 1)
            suma += float(promedio) * peso
            pesos += peso
        if pesos:
            total += (suma / pesos) * float(linea["cantidad"])
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
        confirmaciones = []

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
            if elegido.get("fecha_confirmacion"):
                confirmaciones.append(elegido["fecha_confirmacion"])
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
            # Antigüedad del precio MÁS VIEJO de los que se usaron: basta uno
            # desactualizado para que la cotización sea poco confiable.
            "dias_precio": max((_dias_desde(f) for f in confirmaciones), default=None),
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


def _dias_desde(fecha_iso: str) -> int | None:
    """Días calendario, en hora de Lima, desde una fecha hasta hoy."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        lima = ZoneInfo("America/Lima")
        fecha = datetime.fromisoformat(str(fecha_iso).replace("Z", "+00:00")).astimezone(lima)
        return max((datetime.now(lima).date() - fecha.date()).days, 0)
    except (ValueError, TypeError):
        return None


# ===========================================================================
# ASIGNACIÓN POR COBERTURA
# La base entrega la regla y las sedes candidatas (candidatos_cobertura). Aquí
# se decide con qué nivel se cotiza: se empieza por el nivel de la regla y se
# suma el siguiente mientras NINGUNA sede tenga la canasta completa. Si ni con
# la terciaria se completa, se amplía a toda la zona.
#
# Esta función es la única que decide la asignación por cobertura: la usan la
# pantalla y el agente, para que nunca calculen distinto.
# ===========================================================================

NIVELES = {1: "principal", 2: "secundaria", 3: "terciaria"}


def etapas_de_busqueda(regla: dict) -> list[tuple[str, int | None]]:
    """Las etapas en orden: («distrito», nivel) … y al final («zona», None)."""
    if regla["alcance"] == "zona":
        return [("zona", None)]
    inicio = int(regla.get("nivel_inicial") or 1)
    return [("distrito", n) for n in range(inicio, 4)] + [("zona", None)]


def seleccionar_por_cobertura(lineas: list[dict], paquete: dict,
                              precios: list[dict],
                              coordenadas: tuple | None = None) -> tuple[list[dict], dict]:
    """Cotiza por cobertura, escalando por niveles según la canasta completa.

    paquete:  lo que devuelve candidatos_cobertura (zona, regla, sedes)
    precios:  los de todas las sedes candidatas
    coordenadas: las del cliente, solo para mostrar la distancia

    Devuelve (resultados, info). Los resultados traen TODAS las sedes de la
    etapa final, incluidas dos sedes de una misma ferretería, agrupadas.
    """
    regla = paquete.get("regla")
    if not paquete.get("id_zona") or not regla:
        return [], {"motivo": "sin_zona",
                    "mensaje": "La obra no está en ninguna zona que atendamos."}

    sedes = []
    for s in paquete.get("sedes") or []:
        sede = dict(s)
        if coordenadas and s.get("latitud") is not None and s.get("longitud") is not None:
            sede["distancia_km"] = round(distancia_km(coordenadas[0], coordenadas[1],
                                                      s["latitud"], s["longitud"]), 2)
        else:
            sede["distancia_km"] = None
        sedes.append(sede)

    etapas = etapas_de_busqueda(regla)
    resultados, usada = [], None

    for i, (alcance, nivel) in enumerate(etapas):
        if alcance == "zona":
            grupo = sedes
        else:
            grupo = [s for s in sedes if s.get("nivel_en_distrito")
                     and s["nivel_en_distrito"] <= nivel]
        if not grupo:
            continue

        resultados = cotizar_en_sedes(lineas, grupo, precios, una_por_ferreteria=False)
        usada = (i, alcance, nivel)
        if any(r["canasta_completa"] for r in resultados):
            break

    if usada is None:
        return [], {"motivo": "sin_ferreterias", "id_regla_asignacion": regla["id_regla_asignacion"],
                    "mensaje": f"Ninguna ferretería cubre la zona {paquete.get('zona')}."}

    i, alcance, nivel = usada
    por_sede = {s["id_sede"]: s for s in sedes}
    for r in resultados:
        nivel_r = por_sede.get(r["id_sede"], {}).get("nivel_en_distrito")
        r["nivel_en_distrito"] = nivel_r
        r["cobertura"] = (f"Cobertura {NIVELES[nivel_r]}" if nivel_r
                          else "Cubre otra parte de la zona")

    info = {
        "id_regla_asignacion": regla["id_regla_asignacion"],
        "regla": regla.get("descripcion"),
        "alcance": alcance,
        "nivel": nivel,
        "ampliada": i > 0,
        "completa": any(r["canasta_completa"] for r in resultados),
        "mensaje": _mensaje_etapa(alcance, nivel, i > 0, paquete.get("zona")),
    }
    return _agrupar_por_ferreteria(resultados), info


def _mensaje_etapa(alcance, nivel, ampliada, zona) -> str:
    if alcance == "zona":
        base = f"toda la zona {zona}"
    elif nivel == 1:
        base = "cobertura principal del distrito"
    else:
        base = f"cobertura hasta {NIVELES[nivel]} del distrito"
    return (f"Se amplió a {base}: ninguna ferretería del alcance inicial tenía la "
            "canasta completa." if ampliada else f"Se cotizó con {base}.")


def _agrupar_por_ferreteria(resultados: list[dict]) -> list[dict]:
    """Ordena por la mejor sede de cada ferretería y deja juntas sus sedes.

    Así dos sedes de una misma ferretería se leen como dos opciones de ella y
    no como dos competidores separados en la lista.
    """
    def clave(r):
        return (r["n_faltantes"], r["monto"],
                r["distancia_km"] if r["distancia_km"] is not None else 9e9)

    mejor = {}
    for r in resultados:
        if r["ferreteria"] not in mejor or clave(r) < mejor[r["ferreteria"]]:
            mejor[r["ferreteria"]] = clave(r)
    return sorted(resultados, key=lambda r: (mejor[r["ferreteria"]], r["ferreteria"], clave(r)))
