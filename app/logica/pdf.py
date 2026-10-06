"""
GENERACIÓN DEL PDF
==================
Python puro: recibe diccionarios y devuelve los bytes del PDF.
No sabe nada de Streamlit ni de Supabase.

Para cambiar cómo se ve el PDF, este es el único archivo que tocas.
"""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

ROJO = colors.HexColor("#E63946")

# ============================================================================
# TEXTOS DEL FINAL DE LA COTIZACIÓN
# Para cambiar las condiciones, el contacto o el pie, edita solo esta parte.
# En CONDICIONES, {vence} se reemplaza por la fecha de vencimiento.
# ============================================================================

CONDICIONES = [
    "<b>Validez:</b> La presente cotización tiene validez hasta el día {vence}",
    "<b>Disponibilidad:</b> Sujeta a stock del proveedor.",
    "<b>Formas de pago:</b> El pago se realiza directamente a la ferretería "
    "mencionada en la cotización mediante:",
    "<b>Tiempo de entrega:</b> Sujeto a coordinación con el proveedor.",
    "<b>Condiciones de entrega:</b> Los productos serán entregados en la dirección "
    "proporcionada por el cliente, bajo condiciones del proveedor.",
]

# Van debajo de la condición 3, «Formas de pago»
FORMAS_DE_PAGO = [
    "Transferencia bancaria",
    "Pago con tarjeta",
    "Contraentrega (disponible solo en Trujillo)",
]

NOTA = ("Nuestra empresa actúa como intermediaria entre ferreterías y clientes "
        "finales. No contamos con almacén propio.")

CONTACTO = {
    "nombre": "Sider Express - Canal oficial",
    "telefono": "943 529 146",
    "correo": "siderexpress@sider.com.pe",
    "web": "www.siderexpress.com",
}

DESPEDIDA = ("¡Gracias por confiar en nosotros! Esperamos su confirmación "
             "para proceder con el pedido.")

# Imágenes del pie. Se buscan junto a la app, en la carpeta assets.
_ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICONO_WHATSAPP = str(_ASSETS / "icono_whatsapp.png")
LOGO_BLANCO = str(_ASSETS / "logo_blanco.png")

# Rojo de la franja del pie, el mismo de la marca
ROJO_PIE = colors.HexColor("#D0021B")
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
        topMargin=16 * mm, bottomMargin=34 * mm,
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
                   f"Válida hasta: {escape(_vence_legible(cot['vence']))}", normal),
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

    partes.append(Spacer(1, 6))
    gris = ParagraphStyle("g", parent=normal, fontSize=8,
                          textColor=colors.HexColor("#5B6B7F"))
    partes.append(Paragraph(
        f"Atendido por {escape(datos.get('asesor') or 'SIDEREXPRESS')}.", gris))

    partes.append(Spacer(1, 16))
    partes.append(_bloque_condiciones(_vence_legible(cot["vence"]), normal))

    logo_blanco = datos.get("logo_blanco") or LOGO_BLANCO
    doc.build(partes,
              onFirstPage=lambda c, d: _pie(c, d, logo_blanco),
              onLaterPages=lambda c, d: _pie(c, d, logo_blanco))
    return buffer.getvalue()


def _vence_legible(vence: str) -> str:
    """«30/09/2026 23:59» → «30/09/2026 a las 11:59 p. m.».

    La cotización vale hasta el final del mismo día en que se emite.
    """
    fecha = (vence or "").split(" ")[0]
    return f"{fecha} a las 11:59 p. m." if fecha and fecha != "—" else "—"


def _bloque_condiciones(vence: str, normal) -> KeepTogether:
    """Condiciones, nota, contacto y despedida.

    Va en un KeepTogether: si no entra completo en la página, pasa entero a la
    siguiente en vez de partirse a la mitad.
    """
    titulo = ParagraphStyle("ct", parent=normal, fontSize=10, leading=14,
                            fontName="Helvetica-Bold", spaceAfter=6)
    item = ParagraphStyle("ci", parent=normal, fontSize=9, leading=13,
                          leftIndent=14, firstLineIndent=-10)
    sub = ParagraphStyle("cs", parent=normal, fontSize=8.5, leading=12,
                         leftIndent=34)
    destacado = ParagraphStyle("cd", parent=normal, fontSize=9, leading=13,
                               fontName="Helvetica-Bold")

    bloque = [Paragraph("CONDICIONES DE LA COTIZACIÓN", titulo)]
    for i, texto in enumerate(CONDICIONES, start=1):
        bloque.append(Paragraph(f"{i}) {texto.format(vence=escape(vence))}", item))
        if "Formas de pago" in texto:
            for forma in FORMAS_DE_PAGO:
                bloque.append(Paragraph(f"– {escape(forma)}", sub))

    bloque += [
        Spacer(1, 8),
        Paragraph(f"<b>Nota:</b> {escape(NOTA)}", destacado),
        Spacer(1, 10),
        Paragraph("Contacto para pedidos y consultas:", destacado),
        Spacer(1, 3),
        Paragraph(escape(CONTACTO["nombre"]), normal),
        Paragraph(f"Teléfono: {escape(CONTACTO['telefono'])}", normal),
        Paragraph(f"Correo: {escape(CONTACTO['correo'])}", normal),
        Spacer(1, 8),
        Paragraph(escape(DESPEDIDA), normal),
    ]
    return KeepTogether(bloque)


def _pie(canvas, doc, logo_blanco=None):
    """Franja roja al pie de cada página: WhatsApp, logo y web.

    Los íconos se dibujan con figuras simples para no depender de archivos de
    imagen ni de fuentes especiales.
    """
    ancho, _ = A4
    x, y = 14 * mm, 8 * mm
    w, h = ancho - 28 * mm, 17 * mm

    canvas.saveState()
    canvas.setFillColor(ROJO_PIE)
    canvas.roundRect(x, y, w, h, 4 * mm, stroke=0, fill=1)

    blanco = colors.white
    canvas.setFillColor(blanco)
    canvas.setStrokeColor(blanco)
    centro_y = y + h / 2

    # --- WhatsApp: imagen en alta resolución. Dibujado con trazos finos,
    # algunos visores de PDF lo mostraban cortado.
    cx = x + 11 * mm
    lado = 8 * mm
    canvas.drawImage(ICONO_WHATSAPP, cx - lado / 2, centro_y - lado / 2,
                     width=lado, height=lado, mask="auto")
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(cx + 6 * mm, centro_y - 1.5 * mm, CONTACTO["telefono"])

    # --- Logo al centro
    if logo_blanco:
        alto_logo = 9 * mm
        ancho_logo = alto_logo * 1049 / 293
        canvas.drawImage(logo_blanco, ancho / 2 - ancho_logo / 2, centro_y - alto_logo / 2,
                         width=ancho_logo, height=alto_logo, mask="auto")
    else:
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawCentredString(ancho / 2, centro_y - 1.5 * mm, "SIDER EXPRESS")

    # --- Web: un globo terráqueo con meridianos
    canvas.setFont("Helvetica-Bold", 12)
    texto_web = CONTACTO["web"]
    ancho_texto = canvas.stringWidth(texto_web, "Helvetica-Bold", 12)
    tx = x + w - 6 * mm - ancho_texto
    gx = tx - 6 * mm
    r = 3.4 * mm
    canvas.setLineWidth(1)
    canvas.circle(gx, centro_y, r, stroke=1, fill=0)
    canvas.ellipse(gx - r * 0.45, centro_y - r, gx + r * 0.45, centro_y + r, stroke=1, fill=0)
    canvas.line(gx - r, centro_y, gx + r, centro_y)
    canvas.line(gx - r * 0.85, centro_y + r * 0.5, gx + r * 0.85, centro_y + r * 0.5)
    canvas.line(gx - r * 0.85, centro_y - r * 0.5, gx + r * 0.85, centro_y - r * 0.5)
    canvas.drawString(tx, centro_y - 1.5 * mm, texto_web)

    canvas.restoreState()
