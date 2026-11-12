"""Open the tracker in Excel, refresh every query, recalculate, and report formula errors.

    python src/check_excel.py [--pdf out.pdf]

Nothing is saved: the workbook is closed without changes. Used before every release.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pythoncom
import win32com.client as win32

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "excel" / "Semiconductor_Materials_Price_Tracker.xlsx"
SHEETS = ["README", "Dashboard", "Reconciliation", "Nowcast", "Quality checks", "Data dictionary", "Discrepancy log"]
HELPER_FROM_COL = 27            # column AA onwards holds chart helpers that use NA() on purpose


def metadata() -> list[str]:
    issues = []
    with zipfile.ZipFile(BOOK) as z:
        core = z.read("docProps/core.xml").decode()
        app = z.read("docProps/app.xml").decode()
        for tag in ("dc:creator", "cp:lastModifiedBy"):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", core)
            if m and m.group(1).strip():
                issues.append(f"{tag} = {m.group(1)}")
        m = re.search(r"<Company>(.*?)</Company>", app)
        if m and m.group(1).strip():
            issues.append(f"Company = {m.group(1)}")
        for n in z.namelist():
            if n.endswith(".xml") or n.endswith(".rels"):
                t = z.read(n).decode("utf-8", "ignore")
                if re.search(r"[A-Za-z]:\\\\?(Users|case-study)", t) or "absPath" in t:
                    issues.append(f"local path in {n}")
    return issues


def main() -> int:
    issues = metadata()
    print("metadata:", "clean" if not issues else issues)
    pythoncom.CoInitialize()
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    errors = 0
    try:
        wb = xl.Workbooks.Open(str(BOOK), UpdateLinks=0, ReadOnly=True)
        wb.RefreshAll()
        xl.CalculateUntilAsyncQueriesDone()
        xl.CalculateFull()
        print("queries:", wb.Queries.Count, "| tables refreshed:",
              sum(ws.ListObjects.Count for ws in wb.Worksheets))
        for name in SHEETS:
            ws = wb.Worksheets(name)
            used = ws.UsedRange
            vals = used.Value
            if not isinstance(vals, tuple):
                continue
            r0, c0 = used.Row, used.Column
            bad = []
            for i, row in enumerate(vals):
                for j, v in enumerate(row):
                    col = c0 + j
                    if isinstance(v, int) and v < -2146826200 and col < HELPER_FROM_COL:
                        bad.append(ws.Cells(r0 + i, col).Address)
            errors += len(bad)
            print(f"  {name:16s} formula errors: {len(bad)} {bad[:8]}")
        d = wb.Worksheets("Dashboard")
        print("Dashboard KPIs:", d.Range("C5").Value, d.Range("B9").Text, d.Range("E9").Text, d.Range("I9").Text, "|", d.Range("I11").Text, "|", d.Range("N9").Text)
        n = wb.Worksheets("Nowcast")
        print("Nowcast:", n.Range("C5").Value, n.Range("C9").Text, n.Range("D9").Text, n.Range("E9").Text, "| backtest MAPE", n.Range("E22").Text)
        print("RootFolder:", wb.Worksheets("README").Range("C8").Text[-30:])
        if "--pdf" in sys.argv:
            out = Path(sys.argv[sys.argv.index("--pdf") + 1])
            for k, s in enumerate(SHEETS):
                ws = wb.Worksheets(s)
                ws.ExportAsFixedFormat(0, str(out.with_name(f"{out.stem}_{k}.pdf")))
            print("preview pdfs:", out.parent)
        wb.Close(False)
    finally:
        xl.Quit()
    return 1 if errors or issues else 0


if __name__ == "__main__":
    sys.exit(main())
