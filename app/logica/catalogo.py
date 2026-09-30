"""
DETECCIÓN DE NOMBRES PARECIDOS
==============================
Python puro. Evita el problema que ya costó 102 precios: productos casi
iguales con nombres distintos, como «BC 6mm» y «BC 6 mm».

Sirve igual para productos, marcas, unidades y categorías.
"""
import re
import unicodedata
from difflib import SequenceMatcher


def normalizar(texto: str) -> str:
    """Deja el nombre en su forma comparable.

    Mayúsculas, sin tildes, sin espacios ni signos. Así «BC 6 mm», «bc 6mm»
    y «BC-6MM» quedan iguales: «BC6MM».
    """
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = texto.encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def parecidos(nombre: str, existentes: list[str], umbral: float = 0.85,
              maximo: int = 3) -> list[str]:
    """Nombres existentes que probablemente sean el mismo.

    Primero los idénticos al normalizar (el caso seguro), después los que se
    parecen mucho. El umbral de 0.85 atrapa diferencias de una o dos letras
    sin confundir productos distintos como «BC 1/2"» y «BC 3/8"».
    """
    buscado = normalizar(nombre)
    if len(buscado) < 2:
        return []

    iguales, similares = [], []
    for existente in existentes:
        clave = normalizar(existente)
        if clave == buscado:
            iguales.append(existente)
        elif SequenceMatcher(None, buscado, clave).ratio() >= umbral:
            similares.append(existente)

    return (iguales + similares)[:maximo]


def es_identico(nombre: str, existentes: list[str]) -> str | None:
    """El existente que es exactamente el mismo al normalizar, si lo hay."""
    buscado = normalizar(nombre)
    return next((e for e in existentes if normalizar(e) == buscado), None)
