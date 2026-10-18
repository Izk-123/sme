"""
Service layer for the Reports app.

Three jobs:

  1. Data fetchers (get_current_stock, get_low_stock) that annotate
     both cost and retail value on each product.

  2. PDF/Excel generation. The PDF path escapes every user-supplied
     string (product names, supplier names, notes) via xml.sax.saxutils
     before passing it to reportlab's Paragraph — otherwise a product
     literally named "<B>" would break the layout or, worse, run as
     reportlab markup.

     The Excel path prefixes any text starting with = + - or @ with an
     apostrophe, or Excel would treat it as a formula and run it.
     Between them, these two guard against a supplier or product
     name being used as an injection vector.

  3. Brand constants. The exports used to say "SME Business OS" with
     the old blue. Now "ChumaFlow" and the teal brand colours, to
     match the app shell.
"""
import io
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import escape

from django.db.models import F
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from sales.models import Product


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------

COMPANY_NAME = "ChumaFlow"
BRAND_HEX = "12A5A0"
BRAND_DARK_HEX = "0A2F35"

BRAND_COLOR = colors.HexColor(f"#{BRAND_HEX}")
BRAND_DARK = colors.HexColor(f"#{BRAND_DARK_HEX}")
TEXT_MUTED = colors.HexColor("#6c757d")
ROW_ALT = colors.HexColor("#f4f6fc")
BORDER_LIGHT = colors.HexColor("#e3e6f0")
KPI_BG = colors.HexColor("#f4f6fc")


# A cell starting with one of these is treated as a formula by Excel.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _safe_cell(value):
    """Neutralise formula injection from user-supplied strings."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def get_current_stock(org):
    """
    Return products annotated with both `retail_value` and `cost_value`.

    `cost_value` is NULL when `cost_price` is NULL, so templates can
    distinguish "zero-value stock" from "unknown-cost stock". This
    shadows the same-named model property; iterating a queryset sets
    the annotation on each instance.
    """
    return (
        Product.objects.filter(organization=org)
        .annotate(
            retail_value=F("price") * F("stock_quantity"),
            cost_value=F("cost_price") * F("stock_quantity"),
        )
        .order_by("name")
    )


def get_low_stock(org):
    return Product.objects.filter(
        organization=org, stock_quantity__lte=F("low_stock_threshold"),
    )


# ---------------------------------------------------------------------------
# PDF header / footer band
# ---------------------------------------------------------------------------

def _pdf_header_footer(canvas_obj, doc, subtitle_text):
    canvas_obj.saveState()
    page_width, page_height = A4
    band_height = 0.55 * inch

    canvas_obj.setFillColor(BRAND_COLOR)
    canvas_obj.rect(
        0, page_height - band_height, page_width, band_height,
        stroke=0, fill=1,
    )

    canvas_obj.setFillColor(colors.whitesmoke)
    canvas_obj.setFont("Helvetica-Bold", 11)
    canvas_obj.drawString(30, page_height - band_height + 18, COMPANY_NAME)

    canvas_obj.setFont("Helvetica", 9)
    canvas_obj.drawRightString(
        page_width - 30, page_height - band_height + 18, subtitle_text or "",
    )

    canvas_obj.setFillColor(TEXT_MUTED)
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.drawString(
        30, 22,
        f"Generated on {datetime.now().strftime('%d %b %Y, %H:%M')}",
    )
    canvas_obj.drawRightString(page_width - 30, 22, f"Page {doc.page}")
    canvas_obj.setStrokeColor(BORDER_LIGHT)
    canvas_obj.line(30, 34, page_width - 30, 34)
    canvas_obj.restoreState()


# ---------------------------------------------------------------------------
# PDF generator
# ---------------------------------------------------------------------------

def generate_pdf_response(filename, title, subtitle, headers, rows, summary_dict=None):
    """
    Build a stylised PDF report and return an HttpResponse.

    Every string from the caller (title, subtitle, headers, row cells,
    summary keys/values) is escaped before it reaches reportlab's
    Paragraph. Without this, a product named "<Widget>" or an owner
    note containing "&" would either break the layout or be
    interpreted as markup.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=30, leftMargin=30,
        topMargin=0.55 * inch + 24, bottomMargin=45,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        name="ReportTitle", parent=styles["Heading1"], alignment=TA_LEFT,
        fontSize=19, leading=23, spaceAfter=2,
        textColor=colors.HexColor("#212529"), fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        name="Subtitle", parent=styles["Normal"], alignment=TA_LEFT,
        fontSize=10.5, textColor=TEXT_MUTED, spaceAfter=18,
    )
    section_style = ParagraphStyle(
        name="Section", parent=styles["Heading2"], fontSize=11,
        textColor=colors.HexColor("#212529"), fontName="Helvetica-Bold",
        spaceBefore=6, spaceAfter=8,
    )
    body_style = ParagraphStyle(
        name="Body", parent=styles["Normal"], fontSize=10,
        alignment=TA_LEFT, textColor=TEXT_MUTED,
    )
    kpi_value_style = ParagraphStyle(
        name="KPIValue", parent=styles["Normal"], fontSize=15, leading=18,
        fontName="Helvetica-Bold", textColor=BRAND_DARK, alignment=TA_LEFT,
    )
    kpi_label_style = ParagraphStyle(
        name="KPILabel", parent=styles["Normal"], fontSize=8.5,
        textColor=TEXT_MUTED, alignment=TA_LEFT,
    )

    story = [Paragraph(escape(title), title_style)]
    if subtitle:
        story.append(Paragraph(escape(subtitle), subtitle_style))

    if summary_dict:
        story.append(Paragraph("SUMMARY", section_style))
        card_cells = [
            [
                Paragraph(escape(str(value)), kpi_value_style),
                Paragraph(escape(str(label).upper()), kpi_label_style),
            ]
            for label, value in summary_dict.items()
        ]
        usable_width = A4[0] - 60
        col_width = usable_width / len(card_cells)
        kpi_table = Table([card_cells], colWidths=[col_width] * len(card_cells))
        kpi_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), KPI_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, BORDER_LIGHT),
            ("INNERGRID", (0, 0), (-1, -1), 0.75, colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 14),
            ("RIGHTPADDING", (0, 0), (-1, -1), 14),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(kpi_table)
        story.append(Spacer(1, 0.28 * inch))

    if rows:
        story.append(Paragraph("DETAIL", section_style))

        header_row = [
            Paragraph(f"<b>{escape(str(h))}</b>", ParagraphStyle(
                name="TH", parent=styles["Normal"], fontSize=9.5,
                textColor=colors.whitesmoke,
                alignment=TA_LEFT if i == 0 else 2,
            ))
            for i, h in enumerate(headers)
        ]
        cell_left = ParagraphStyle(
            name="TDLeft", parent=styles["Normal"], fontSize=9.5,
            textColor=colors.HexColor("#212529"),
        )
        cell_right = ParagraphStyle(
            name="TDRight", parent=styles["Normal"], fontSize=9.5,
            textColor=colors.HexColor("#212529"), alignment=2,
        )
        data_rows = [
            [
                Paragraph(
                    escape(str(val)),
                    cell_left if i == 0 else cell_right,
                )
                for i, val in enumerate(row)
            ]
            for row in rows
        ]
        table_data = [header_row] + data_rows
        col_widths = [(A4[0] - 60) / len(headers)] * len(headers)
        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_COLOR),
            ("TOPPADDING", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 9),
            ("TOPPADDING", (0, 1), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("LINEBELOW", (0, 0), (-1, 0), 0.75, BRAND_DARK),
            ("LINEBELOW", (0, 1), (-1, -2), 0.5, BORDER_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.75, BORDER_LIGHT),
        ]
        for row_idx in range(1, len(table_data)):
            if row_idx % 2 == 0:
                style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), ROW_ALT))
        t.setStyle(TableStyle(style))
        story.append(t)
    else:
        story.append(Paragraph("No data available for this period.", body_style))

    def _draw(canvas_obj, doc_obj):
        _pdf_header_footer(canvas_obj, doc_obj, subtitle)

    doc.build(story, onFirstPage=_draw, onLaterPages=_draw)
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}.pdf"'
    response.write(pdf)
    return response


# ---------------------------------------------------------------------------
# Excel generator
# ---------------------------------------------------------------------------

def generate_excel_response(filename, title, headers, rows, summary_dict=None):
    """
    Build an Excel file and return an HttpResponse.

    Every string goes through _safe_cell() so a supplier named
    "@SUM(A1:A999)" or a note starting with "=" can't be interpreted
    as a formula.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]  # Excel sheet name max 31 chars

    bold_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(
        start_color=BRAND_HEX, end_color=BRAND_HEX, fill_type="solid",
    )
    kpi_font = Font(bold=True, size=12, color=BRAND_HEX)
    border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    current_row = 1

    ws.merge_cells(
        start_row=current_row, start_column=1,
        end_row=current_row, end_column=len(headers),
    )
    title_cell = ws.cell(row=current_row, column=1, value=title)
    title_cell.font = Font(bold=True, size=16, color=BRAND_HEX)
    title_cell.alignment = Alignment(horizontal="center")
    current_row += 1

    subtitle = f"Generated on {datetime.now().strftime('%d %b %Y, %H:%M')}"
    ws.merge_cells(
        start_row=current_row, start_column=1,
        end_row=current_row, end_column=len(headers),
    )
    sub_cell = ws.cell(row=current_row, column=1, value=subtitle)
    sub_cell.font = Font(size=10, color="808080")
    sub_cell.alignment = Alignment(horizontal="center")
    current_row += 2

    if summary_dict:
        for label, value in summary_dict.items():
            ws.cell(row=current_row, column=1, value=_safe_cell(str(label)))
            val_cell = ws.cell(row=current_row, column=2, value=_safe_cell(value))
            val_cell.font = kpi_font
            current_row += 1
        current_row += 1

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=current_row, column=col_idx, value=_safe_cell(str(header)))
        cell.font = bold_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    current_row += 1

    for row_data in rows:
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=_safe_cell(value))
            if isinstance(value, (int, float, Decimal)):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            else:
                cell.number_format = "@"
                cell.alignment = Alignment(horizontal="left")
            cell.border = border
        current_row += 1

    for col in ws.columns:
        max_length = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_length + 2, 40)

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response