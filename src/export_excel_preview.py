"""Export the Excel tracker's sheets to a PDF and PNG images that GitHub displays without download.

    python src/export_excel_preview.py

Writes docs/Excel_Tracker_Preview.pdf and zoomed crops docs/img/excel_<sheet>_<part>.png. The README sheet is left out on
purpose: its RootFolder cell shows the folder of whoever opens the file.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pypdfium2 as pdfium
import pythoncom
import win32com.client as win32
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "excel" / "Semiconductor_Materials_Price_Tracker.xlsx"
OUT_PDF = ROOT / "docs" / "Excel_Tracker_Preview.pdf"
IMG = ROOT / "docs" / "img"
SHEETS = {"Dashboard": "excel_dashboard", "Reconciliation": "excel_reconciliation", "Nowcast": "excel_nowcast",
          "Quality checks": "excel_quality", "Data dictionary": "excel_dictionary", "Discrepancy log": "excel_discrepancy_log"}


CROPS = {
    "excel_dashboard": {"top": (0.06, 0.09, 0.875, 0.56), "table": (0.06, 0.565, 0.64, 0.905)},
    "excel_reconciliation": {"table": (0.055, 0.105, 0.625, 0.43), "chart": (0.64, 0.12, 0.925, 0.4)},
    "excel_nowcast": {"top": (0.06, 0.085, 0.94, 0.53), "chart": (0.06, 0.53, 0.94, 0.895)},
    "excel_quality": {"matrix": (0.58, 0.15, 0.93, 0.47)},
}


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    pythoncom.CoInitialize()
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    # English separators for the export only (the user's setting is restored in 'finally')
    saved = (xl.UseSystemSeparators, xl.DecimalSeparator, xl.ThousandsSeparator)
    try:
        xl.UseSystemSeparators = False
        xl.DecimalSeparator = "."
        xl.ThousandsSeparator = ","
        wb = xl.Workbooks.Open(str(BOOK), UpdateLinks=0, ReadOnly=True)
        wb.RefreshAll()
        xl.CalculateUntilAsyncQueriesDone()
        xl.CalculateFull()
        for i, sheet in enumerate(SHEETS):
            wb.Worksheets(sheet).ExportAsFixedFormat(0, str(tmp / f"{i}.pdf"))
        wb.Close(False)
    finally:
        xl.DecimalSeparator, xl.ThousandsSeparator = saved[1], saved[2]
        xl.UseSystemSeparators = saved[0]
        try:
            xl.Quit()
        except Exception:
            pass
    writer = PdfWriter()
    for i in range(len(SHEETS)):
        for page in PdfReader(str(tmp / f"{i}.pdf")).pages:
            writer.add_page(page)
    writer.add_metadata({"/Title": "Semiconductor materials price tracker - Excel preview", "/Author": "", "/Creator": "", "/Producer": ""})
    with open(OUT_PDF, "wb") as f:
        writer.write(f)
    doc = pdfium.PdfDocument(str(OUT_PDF))
    for i, name in enumerate(SHEETS.values()):
        page = doc[i].render(scale=3.2).to_pil().convert("RGB")
        # zoomed crops (fractions of the page) so the README stays readable on GitHub
        for suffix, (x0, y0, x1, y1) in CROPS.get(name, {}).items():
            w, h = page.size
            page.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h))).save(IMG / f"{name}_{suffix}.png", optimize=True)
    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"  {OUT_PDF.relative_to(ROOT)} ({len(SHEETS)} pages) and docs/img/excel_*.png")


if __name__ == "__main__":
    main()
