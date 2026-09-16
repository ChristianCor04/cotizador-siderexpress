"""
LÓGICA GEOGRÁFICA
=================
Python puro: no sabe nada de Streamlit ni de Supabase.
Eso permite probarla sola y reutilizarla en el futuro.
"""
import re
from math import atan2, cos, radians, sin, sqrt


def distancia_km(lat1, lon1, lat2, lon2) -> float:
    """Distancia en línea recta entre dos puntos, en kilómetros."""
    R = 6371  # radio de la Tierra en km
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


# Formas en que puede venir una ubicación, de la más confiable a la menos
_PIN = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")          # el pin del lugar
_QUERY = re.compile(r"[?&](?:q|query|ll)=(-?\d+\.\d+),\s*(-?\d+\.\d+)")
_CENTRO = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")           # centro del mapa
_TEXTO = re.compile(r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*[,;\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def extraer_coordenadas(texto: str):
    """Saca (latitud, longitud) de un link de Google Maps o de un texto.

    Devuelve None si no encuentra nada válido.
    El pin del lugar tiene prioridad sobre el centro del mapa, porque el
    centro se mueve con el zoom y da una ubicación aproximada.
    """
    if not texto:
        return None

    pines = _PIN.findall(texto)
    candidato = (
        (pines[-1] if pines else None)
        or (m.groups() if (m := _QUERY.search(texto)) else None)
        or (m.groups() if (m := _CENTRO.search(texto)) else None)
        or (m.groups() if (m := _TEXTO.match(texto)) else None)
    )
    if candidato is None:
        return None

    lat, lon = float(candidato[0]), float(candidato[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def sedes_cercanas(lat, lon, sedes: list[dict], top_n: int = 5) -> list[dict]:
    """Las sedes más cercanas a un punto, una por ferretería.

    Se toma solo la sede más cercana de cada ferretería: si no, una cadena
    con tres locales cerca ocuparía todos los puestos y quedaría sin
    competencia.
    """
    con_distancia = []
    for s in sedes:
        if s.get("latitud") is None or s.get("longitud") is None:
            continue
        con_distancia.append({**s, "distancia_km": round(
            distancia_km(lat, lon, s["latitud"], s["longitud"]), 2)})

    con_distancia.sort(key=lambda s: s["distancia_km"])

    mejor_por_ferreteria = {}
    for s in con_distancia:
        if s["ferreteria"] not in mejor_por_ferreteria:
            mejor_por_ferreteria[s["ferreteria"]] = s

    return list(mejor_por_ferreteria.values())[:top_n]
