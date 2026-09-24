"""
GENERACIÓN DEL PDF
==================
Python puro: recibe diccionarios y devuelve los bytes del PDF.
No sabe nada de Streamlit ni de Supabase.

Para cambiar cómo se ve el PDF, este es el único archivo que tocas.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

ROJO = colors.HexColor("#E63946")
GRIS = colors.HexColor("#F5F7FA")


def _soles(valor) -> str:
    return f"S/ {float(valor or 0):,.2f}"


def generar_pdf(datos: dict) -> bytes:
    """Arma el PDF de la cotización.

    datos espera:
      cotizacion  {codigo, fecha, vence}
      cliente     {nombre, telefono, documento}
      ferreteria  {nombre, sede, direccion, distrito}
      productos   [{descripcion, marca, cantidad, precio, subtotal}]
      totales     {subtotal, descuento, total, devolucion}
      asesor      texto
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Cotización {datos['cotizacion']['codigo']}",
    )

    estilos = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=estilos["Normal"], fontSize=9, leading=13)
    titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=18,
                            textColor=ROJO, alignment=0, spaceAfter=2)

    partes = []

    # El logo va arriba. Si el archivo no está, se usa el texto como respaldo
    # para que el PDF nunca deje de generarse.
    logo = datos.get("logo")
    if logo:
        try:
            imagen = Image(logo, width=52 * mm, height=52 * mm * 293 / 1049)
            imagen.hAlign = "LEFT"
            partes.append(imagen)
            partes.append(Spacer(1, 4))
        except Exception:
            partes.append(Paragraph("SIDEREXPRESS", titulo))
    else:
        partes.append(Paragraph("SIDEREXPRESS", titulo))

    partes.append(Paragraph("Cotización de materiales de construcción", normal))
    partes.append(Spacer(1, 10))

    # ------------------------------------------------ datos de la cotización
    cot, cli, fer = datos["cotizacion"], datos["cliente"], datos["ferreteria"]
    encabezado = [
        [Paragraph(f"<b>N° {escape(cot['codigo'])}</b>", normal),
         Paragraph(f"<b>Cliente</b><br/>{escape(cli['nombre'] or '—')}", normal)],
        [Paragraph(f"Fecha: {escape(cot['fecha'])}<br/>"
                   f"Válida hasta: {escape(cot['vence'])}", normal),
         Paragraph(f"{escape(cli.get('telefono') or '')}<br/>"
                   f"{escape(cli.get('documento') or '')}", normal)],
    ]
    tabla_enc = Table(encabezado, colWidths=[85 * mm, 85 * mm])
    tabla_enc.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    partes += [tabla_enc, Spacer(1, 8)]

    # ------------------------------------------------------------- ferretería
    direccion = " · ".join(x for x in [fer.get("sede"), fer.get("distrito")] if x)
    partes.append(Paragraph(
        f"<b>Ferretería:</b> {escape(fer['nombre'])}"
        + (f"<br/>{escape(direccion)}" if direccion else ""), normal))
    partes.append(Spacer(1, 10))

    # ---------------------------------------------------------------- productos
    # Marca y unidad van como Paragraph para que el texto largo ajuste solo
    # en vez de desbordarse sobre la columna siguiente.
    chico = ParagraphStyle("c", parent=normal, fontSize=8, leading=10)

    filas = [["Producto", "Marca", "Unidad", "Cant.", "P. unitario", "Subtotal"]]
    for p in datos["productos"]:
        filas.append([
            Paragraph(escape(str(p["descripcion"])), normal),
            Paragraph(escape(str(p.get("marca") or "")), chico),
            Paragraph(escape(str(p.get("unidad") or "")), chico),
            f"{float(p['cantidad']):,.0f}",
            _soles(p["precio"]),
            _soles(p["subtotal"]),
        ])

    tabla = Table(filas,
                  colWidths=[48 * mm, 27 * mm, 32 * mm, 15 * mm, 26 * mm, 26 * mm],
                  repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ROJO),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRIS]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D2DC")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    partes += [tabla, Spacer(1, 10)]

    # ------------------------------------------------------------------ totales
    t = datos["totales"]
    resumen = [["Subtotal", _soles(t["subtotal"])]]
    if t.get("descuento"):
        resumen.append(["Descuento SIDEREXPRESS", "− " + _soles(t["descuento"])])
    if t.get("flete"):
        etiqueta = "Flete"
        if t.get("motivo_flete"):
            etiqueta += f" ({t['motivo_flete']})"
        resumen.append([etiqueta, _soles(t["flete"])])
    resumen.append(["TOTAL A PAGAR", _soles(t["total"])])

    tabla_tot = Table(resumen, colWidths=[75 * mm, 40 * mm], hAlign="RIGHT")
    tabla_tot.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    partes.append(tabla_tot)

    # Los bonos se muestran aparte: el cliente los recibe después de comprar
    if t.get("devolucion"):
        partes.append(Spacer(1, 8))
        partes.append(Paragraph(
            f"<b>Además recibirás {_soles(t['devolucion'])}</b> de bono "
            f"después de tu compra, por comprar con SIDEREXPRESS.", normal))

    partes.append(Spacer(1, 14))
    pie = ParagraphStyle("p", parent=normal, fontSize=8,
                         textColor=colors.HexColor("#5B6B7F"))
    partes.append(Paragraph(
        f"Atendido por {escape(datos.get('asesor') or 'SIDEREXPRESS')}. "
        f"Precios sujetos a disponibilidad de la ferretería. "
        f"Esta cotización vence el {escape(cot['vence'])}.", pie))

    doc.build(partes)
    return buffer.getvalue()
