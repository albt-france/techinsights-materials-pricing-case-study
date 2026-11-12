"""Build excel/Semiconductor_Materials_Price_Tracker.xlsx with Excel itself (COM automation).

    python src/build_excel.py

What it creates
- Power Query queries that load the pipeline's CSV files (data/marts, data/clean, seeds). The
  folder is found from the workbook's own location (named cell RootFolder on the README sheet),
  so no local path is stored in the queries: Data > Refresh All works on any computer.
- A dashboard, a reconciliation sheet, a nowcast sheet (FORECAST.ETS / FORECAST.ETS.CONFINT and a
  back-test), quality checks, data dictionary and discrepancy log, all driven by dynamic-array
  formulas (FILTER, SORTBY, XLOOKUP, LET, CHOOSECOLS, TAKE).
- File metadata (author, last modified by, company) and the absolute path Excel stores in the
  file are removed after saving (see scrub()).
Requires Windows + Microsoft Excel 365.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

import pandas as pd
import pythoncom
import win32com.client as win32

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "excel" / "Semiconductor_Materials_Price_Tracker.xlsx"
FOOTER = "Independent case study based on public data · not affiliated with or endorsed by TechInsights"

# palette (same as the report)
INK, INK2, MUTED, GRID = "0B0B0B", "52514E", "898781", "E1E0D9"
BG, CARD, BLUE, BLUE_TINT, RED, RED_TINT = "F4F4F2", "FFFFFF", "2A78D6", "CDE2FB", "D03B3B", "F4C7C6"
FONT = "Segoe UI"


def numfmt(obj, fmt: str) -> None:
    """Set NumberFormat with the en-US locale (LCID 1033). pywin32 otherwise passes the user's
    locale and Excel reads "#,##0.00" with French separators on a French Windows."""
    o = obj._oleobj_
    o.Invoke(o.GetIDsOfNames("NumberFormat"), 1033, pythoncom.DISPATCH_PROPERTYPUT, 0, fmt)


def rgb(hex6: str) -> int:
    """Excel colours are B*65536 + G*256 + R."""
    r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
    return r + g * 256 + b * 65536


# ------------------------------------------------------------------ Power Query
# (query name, file relative to the repository root, sheet, top-left cell, table name)
QUERIES = [
    ("materials", "seeds/materials.csv", "Data dictionary", "F7", "tbl_materials"),
    ("code_concordance", "seeds/code_concordance.csv", "Data dictionary", "F27", "tbl_concordance"),
    ("reconciliation_summary", "data/marts/reconciliation_summary.csv", "Reconciliation", "B8", "tbl_recon"),
    ("quality_summary", "data/clean/quality_summary.csv", "Quality checks", "B8", "tbl_quality"),
    ("discrepancy_log", "data/marts/discrepancy_log.csv", "Discrepancy log", "B6", "tbl_discrepancies"),
    ("monthly_prices", "data/marts/monthly_prices.csv", "data_monthly", "A1", "tbl_monthly"),
    ("reconciliation_detail", "data/marts/reconciliation_detail.csv", "data_recon_detail", "A1", "tbl_recon_detail"),
    ("nowcast", "data/marts/nowcast.csv", "data_nowcast", "A1", "tbl_nowcast"),
    ("nowcast_backtest", "data/marts/nowcast_backtest.csv", "data_backtest", "A1", "tbl_backtest"),
    ("quality_checks", "data/clean/quality_checks.csv", "data_checks", "A1", "tbl_checks"),
    ("annual_prices", "data/marts/annual_prices.csv", "data_annual", "A1", "tbl_annual"),
    ("coverage", "data/marts/coverage.csv", "data_coverage", "A1", "tbl_coverage"),
    ("events", "seeds/events.csv", "data_events", "A1", "tbl_events"),
]
DATE_COLS = {"period", "first_period", "last_period", "event_date", "origin"}


def m_code(rel: str) -> str:
    """Power Query M: read one CSV from RootFolder, empty strings -> null, typed with en-US culture."""
    df = pd.read_csv(ROOT / rel, nrows=2000)
    nums = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    dates = [c for c in df.columns if c in DATE_COLS and c not in nums and df[c].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$").all()]
    q = lambda cols: "{" + ", ".join(f'"{c}"' for c in cols) + "}"
    types = ", ".join([f'{{"{c}", type number}}' for c in nums] + [f'{{"{c}", type date}}' for c in dates])
    path = rel.replace("/", "\\")
    return f'''let
    // RootFolder = repository root, computed in the workbook from its own location (README sheet)
    Root = Excel.CurrentWorkbook(){{[Name="RootFolder"]}}[Content]{{0}}[Column1],
    Source = Csv.Document(File.Contents(Root & "{path}"), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    // empty cells become null before typing, so a blank never turns into an error
    Blanks = Table.ReplaceValue(Promoted, "", null, Replacer.ReplaceValue, {q(nums + dates)}),
    // en-US culture: the CSV uses a dot as decimal separator whatever the Excel locale
    Typed = Table.TransformColumnTypes(Blanks, {{{types}}}, "en-US")
in
    Typed'''


def load_query(wb, name: str, rel: str, sheet: str, cell: str, table: str):
    wb.Queries.Add(name, m_code(rel))
    ws = wb.Worksheets(sheet)
    conn = ("OLEDB;Provider=Microsoft.Mashup.OleDb.1;Data Source=$Workbook$;"
            f"Location={name};Extended Properties=\"\"")
    lo = ws.ListObjects.Add(0, conn, None, 1, ws.Range(cell))      # 0 = xlSrcExternal, 1 = xlYes headers
    qt = lo.QueryTable
    qt.CommandType = 2                                             # xlCmdSql
    qt.CommandText = [f"SELECT * FROM [{name}]"]
    qt.BackgroundQuery = False
    qt.RefreshStyle = 1                                            # xlInsertDeleteCells
    qt.AdjustColumnWidth = False
    qt.PreserveFormatting = True
    qt.Refresh(False)
    lo.Name = table
    lo.TableStyle = "TableStyleLight1"
    return lo


# ------------------------------------------------------------------ formatting helpers
def font(rng, size=10, bold=False, color=INK, italic=False):
    rng.Font.Name = FONT
    rng.Font.Size = size
    rng.Font.Bold = bold
    rng.Font.Italic = italic
    rng.Font.Color = rgb(color)


def page(ws, title: str, subtitle: str, tag: str | None = "PUBLIC DATA", width_cols: str = "B:Q"):
    """Rovio-style page: grey-beige background, bold conclusion title, grey subtitle, tag, footer."""
    ws.Cells.Interior.Color = rgb(BG)
    ws.Cells.Font.Name = FONT
    ws.Columns("A").ColumnWidth = 2
    ws.Range("B2").Value = title
    font(ws.Range("B2"), 18, True)
    ws.Range("B3").Value = subtitle
    font(ws.Range("B3"), 10, color=INK2)
    if tag:
        last = width_cols.split(":")[1]
        ws.Range(f"{last}2").Value = tag
        font(ws.Range(f"{last}2"), 9, True, INK2)
        ws.Range(f"{last}2").HorizontalAlignment = -4152          # right
    ws.Rows(1).RowHeight = 10
    ws.Rows(2).RowHeight = 30


def footer(ws, row: int, text: str = FOOTER):
    ws.Range(f"B{row}").Value = text
    font(ws.Range(f"B{row}"), 8, color=MUTED)


def card(ws, addr: str):
    r = ws.Range(addr)
    r.Interior.Color = rgb(CARD)
    for i in (7, 8, 9, 10):                                         # outer borders
        b = r.Borders(i)
        b.LineStyle = 1
        b.Color = rgb(GRID)
        b.Weight = 2


def label(ws, addr: str, text: str, size=9, bold=True, color=INK2):
    ws.Range(addr).Value = text
    font(ws.Range(addr), size, bold, color)


def fml(ws, addr: str, formula: str, fmt: str | None = None, size=10, bold=False, color=INK, area: str | None = None):
    """Write a (dynamic-array) formula; 'area' = the cells its result spills into, formatted too."""
    ws.Range(addr).Formula2 = formula
    target = ws.Range(area or addr)
    if fmt:
        numfmt(target, fmt)
    font(target, size, bold, color)


def no_gridlines(wb, ws):
    ws.Activate()
    wb.Windows(1).DisplayGridlines = False


def style_table(lo, pct_cols=(), num_cols=(), date_cols=(), wrap_cols=(), widths=None):
    hdr = lo.HeaderRowRange
    hdr.Font.Bold = True
    hdr.Font.Color = rgb(INK2)
    hdr.Interior.Color = rgb(CARD)
    hdr.Borders(9).LineStyle = 1
    hdr.Borders(9).Color = rgb(INK2)
    if lo.DataBodyRange is not None:
        lo.DataBodyRange.Interior.Color = rgb(CARD)
        lo.DataBodyRange.Font.Name = FONT
        lo.DataBodyRange.Font.Size = 9
    for c in pct_cols:
        numfmt(lo.ListColumns(c).DataBodyRange, "+0.0%;-0.0%;0.0%")
    for c in num_cols:
        numfmt(lo.ListColumns(c).DataBodyRange, "#,##0.00")
    for c in date_cols:
        numfmt(lo.ListColumns(c).DataBodyRange, "yyyy-mm")
    for c in wrap_cols:
        lo.ListColumns(c).Range.WrapText = True
    for c, w in (widths or {}).items():
        lo.ListColumns(c).Range.ColumnWidth = w


def add_name(wb, name: str, refers_to: str):
    wb.Names.Add(name, refers_to)


def validation_list(rng, source: str):
    rng.Validation.Delete()
    rng.Validation.Add(3, 1, 1, source)                            # xlValidateList
    rng.Interior.Color = rgb(BLUE_TINT)
    rng.Font.Bold = True


def line_chart(ws, left_cell: str, right_cell: str, title: str, series: list[tuple[str, str, str, str, float]]):
    """series = [(name, x_range, y_range, colour, dash)] ; dash: 0 solid, else msoLineDash."""
    l, r = ws.Range(left_cell), ws.Range(right_cell)
    shp = ws.Shapes.AddChart2(-1, 4, l.Left, l.Top, r.Left + r.Width - l.Left, r.Top + r.Height - l.Top)   # 4 = xlLine
    ch = shp.Chart
    while ch.SeriesCollection().Count:
        ch.SeriesCollection(1).Delete()
    for name, x, y, colour, dash in series:
        s = ch.SeriesCollection().NewSeries()
        s.Name = name
        s.XValues = x
        s.Values = y
        s.Format.Line.ForeColor.RGB = rgb(colour)
        s.Format.Line.Weight = 2.25 if dash == 0 else 1.25
        if dash:
            s.Format.Line.DashStyle = 4                             # msoLineDash
    ch.HasTitle = True
    ch.ChartTitle.Text = title
    ch.ChartTitle.Format.TextFrame2.TextRange.Font.Size = 10
    ch.ChartTitle.Format.TextFrame2.TextRange.Font.Bold = True
    ch.ChartTitle.Format.TextFrame2.TextRange.Font.Fill.ForeColor.RGB = rgb(INK)
    ch.HasLegend = True
    ch.Legend.Position = -4107                                      # bottom
    ch.ChartArea.Format.TextFrame2.TextRange.Font.Name = FONT
    ch.ChartArea.Format.Line.ForeColor.RGB = rgb(GRID)
    try:
        ax = ch.Axes(2)
        ax.MajorGridlines.Format.Line.ForeColor.RGB = rgb(GRID)
        numfmt(ch.Axes(1).TickLabels, "mmm yy")
        ch.Axes(1).CategoryType = 3                                 # time-scale axis
    except Exception:
        pass
    ch.DisplayBlanksAs = 1                                          # gaps (xlNotPlotted)
    return ch


# ------------------------------------------------------------------ sheets
def build_readme(wb, ws):
    page(ws, "Semiconductor materials price tracker",
         "15 fab materials, from raw feedstock to doped wafers: EU import unit values reconciled with exchange prices, "
         "USGS references and mirror statistics, with quality checks and nowcasts.", "README", "B:L")
    ws.Columns("B").ColumnWidth = 24
    ws.Columns("C").ColumnWidth = 110
    rows = [
        ("Purpose", "Track the price of materials used in semiconductor manufacturing from public sources, show where sources disagree and why, and estimate the months not yet published."),
        ("How to refresh", "1) Run `python -m pipeline run` in the repository (downloads public data, rebuilds data/clean and data/marts).  2) Open this file from the repository's excel folder.  3) Data > Refresh All. Every Power Query reads the CSV files relative to this workbook's location (RootFolder below), so no path needs editing."),
        ("RootFolder", None),
        ("Dashboard", "Pick a material: latest validated unit value, 12-month change, nowcast with interval, alerts, history chart; overview of all 15 materials with sparklines."),
        ("Reconciliation", "22 source pairs, expected gap band, latest gap, alert, link to the discrepancy card. Pick a pair to see its gap over time."),
        ("Nowcast", "FORECAST.ETS and FORECAST.ETS.CONFINT for the two missing months, an in-sheet back-test ('if I had forecast 6 months ago'), and the Python back-test of three methods."),
        ("Quality checks", "14 automated checks (sql/03_checks.sql): result per check and per material, and the largest flags."),
        ("Data dictionary", "Standard schema, material dictionary (units, purity, codes, plausible price range) and the customs-code concordance across nomenclature changes."),
        ("Discrepancy log", "Every material discrepancy: root cause, evidence, correction, prevention."),
        ("data_* sheets", "Tables loaded by Power Query. Do not edit: they are overwritten at each refresh."),
        ("Unit value vs price", "A customs unit value is value / kg for everything declared under one code: it mixes grades, purities and contracts. It is a price indicator, not a transaction price."),
        ("Sources", "Eurostat Comext (EU trade, CN8, monthly), UN Comtrade (HS6, annual), USGS Mineral Commodity Summaries 2025-2026, World Bank Pink Sheet (CC BY 4.0), IMF commodity prices and BLS producer price indexes via FRED, ECB exchange rates. Details: data/SOURCES.md."),
        ("Labels", "PUBLIC DATA = real public data. SIMULATED = generated to illustrate a method (survey example only)."),
    ]
    r = 6
    for k, v in rows:
        label(ws, f"B{r}", k, 10, True, INK)
        if k == "RootFolder":
            ws.Range(f"C{r}").Formula2 = '=LEFT(CELL("filename",$A$1),FIND("[",CELL("filename",$A$1))-1)&"..\\"'
            font(ws.Range(f"C{r}"), 9, color=INK2)
            add_name(wb, "RootFolder", f"=README!$C${r}")
            label(ws, f"C{r + 1}", "Computed from this file's location; the queries read RootFolder + data\\marts\\*.csv.", 8, False, MUTED)
            r += 2
            continue
        ws.Range(f"C{r}").Value = v
        ws.Range(f"C{r}").WrapText = True
        font(ws.Range(f"C{r}"), 10, color=INK2)
        r += 1
    ws.Range(f"B6:C{r - 1}").VerticalAlignment = -4160               # top
    footer(ws, r + 1)


def build_dictionary_static(ws):
    page(ws, "One standard schema for every source",
         "Each observation, whatever its source, is stored with the same columns; units, currencies and delivery terms are explicit.",
         "PUBLIC DATA", "B:U")
    label(ws, "B6", "Standard schema (data/clean/observations.csv)", 10, True, INK)
    schema = [("period", "date", "First day of the month (or of the year for annual sources)"),
              ("frequency", "text", "M monthly, A annual"),
              ("material_id", "text", "Key of the material dictionary"),
              ("source / series_id", "text", "Publisher and series code"),
              ("flow", "text", "import, export, price, index"),
              ("reporter / partner", "text", "Who reports, and the counterpart"),
              ("valuation", "text", "CIF, FOB, spot, index, feedstock..."),
              ("product_code", "text", "CN8 or HS6 code(s) summed"),
              ("value_native / currency", "number", "As published"),
              ("quantity_kg", "number", "Net mass in kg (Comext: 100 kg x 100)"),
              ("quantity_supp / supp_unit", "number", "Supplementary unit, e.g. m3 for gases"),
              ("price_native / unit", "number", "Price in the source's unit"),
              ("usd_per_eur", "number", "ECB monthly average (annual mean for annual data)"),
              ("price_eur_kg / price_usd_kg", "number", "Standardised price"),
              ("collected_on", "date", "Collection date of the snapshot")]
    for i, (c, t, d) in enumerate(schema):
        ws.Range(f"B{8 + i}").Value = c
        ws.Range(f"C{8 + i}").Value = t
        ws.Range(f"D{8 + i}").Value = d
    font(ws.Range(f"B8:B{8 + len(schema)}"), 9, True)
    font(ws.Range(f"C8:D{8 + len(schema)}"), 9, color=INK2)
    ws.Columns("B").ColumnWidth = 24
    ws.Columns("C").ColumnWidth = 8
    ws.Columns("D").ColumnWidth = 44
    ws.Columns("E").ColumnWidth = 2
    label(ws, "F6", "Material dictionary (seeds/materials.csv)", 10, True, INK)
    label(ws, "F26", "Customs-code concordance (seeds/code_concordance.csv)", 10, True, INK)


def build_dashboard(wb, ws):
    page(ws, "Fab materials prices at a glance",
         "Validated EU import unit values (EUR/kg, Comext) with exchange benchmarks, reconciliation alerts and nowcasts. "
         "Pick a material in the blue cell.", "PUBLIC DATA", "B:Q")
    widths = {"B": 22, "C": 9, "D": 30, "E": 12, "F": 11, "G": 18, "H": 8, "I": 11, "J": 10, "K": 10, "L": 9,
              "M": 26, "N": 10, "O": 10, "P": 8, "Q": 8}
    for c, w in widths.items():
        ws.Columns(c).ColumnWidth = w
    label(ws, "B5", "Material", 10, True, INK)
    ws.Range("C5").Value = "GE"
    validation_list(ws.Range("C5"), "=MaterialList")
    add_name(wb, "SelMat", "=Dashboard!$C$5")
    fml(ws, "D5", "=XLOOKUP(SelMat,tbl_materials[material_id],tbl_materials[material])", size=12, bold=True)
    fml(ws, "D6", '=XLOOKUP(SelMat,tbl_materials[material_id],tbl_materials[chain_stage])&"  ·  "&XLOOKUP(SelMat,tbl_materials[material_id],tbl_materials[purity_or_grade])', size=9, color=INK2)
    add_name(wb, "LatestMonth", "=MAX(tbl_monthly[period])")

    # KPI cards
    cards = [("B8:D12", "LATEST VALIDATED UNIT VALUE"), ("E8:G12", "CHANGE vs 12 MONTHS EARLIER"),
             ("I8:L12", "NOWCAST NEXT MONTH (80% INTERVAL)"), ("N8:Q12", "ALERTS · OUTLIER MONTHS")]
    for addr, t in cards:
        card(ws, addr)
        label(ws, addr.split(":")[0], t, 8, True, INK2)
        first, last = addr.split(":")
        ws.Range(f"{first[0]}9:{last[0]}10").Merge()               # value cell spans the card width
        ws.Range(f"{first[0]}9").HorizontalAlignment = -4131
        ws.Range(f"{first[0]}9").VerticalAlignment = -4108
    fml(ws, "B9", "=LET(v,FILTER(tbl_monthly[eu_import_uv_eur_kg],tbl_monthly[material_id]=SelMat),INDEX(v,ROWS(v)))", "#,##0.00", 22, True)
    fml(ws, "B11", "=MAXIFS(tbl_monthly[period],tbl_monthly[material_id],SelMat)", "mmm yyyy", 9, color=INK2)
    ws.Range("B11").HorizontalAlignment = -4131
    label(ws, "C11", "EUR/kg", 9, False, INK2)
    fml(ws, "E9", "=LET(p,MAXIFS(tbl_monthly[period],tbl_monthly[material_id],SelMat),"
                  "a,SUMIFS(tbl_monthly[eu_import_uv3_eur_kg],tbl_monthly[material_id],SelMat,tbl_monthly[period],p),"
                  "b,SUMIFS(tbl_monthly[eu_import_uv3_eur_kg],tbl_monthly[material_id],SelMat,tbl_monthly[period],EDATE(p,-12)),"
                  "IF(b=0,NA(),a/b-1))", "+0%;-0%;0%", 22, True)
    ws.Range("E11").Value = "3-month weighted unit value"
    font(ws.Range("E11"), 9, color=INK2)
    nc = "tbl_nowcast[material_id],SelMat,tbl_nowcast[selected],1,tbl_nowcast[horizon],1"
    fml(ws, "I9", f"=SUMIFS(tbl_nowcast[nowcast_eur_kg],{nc})", "#,##0.00", 22, True)
    fml(ws, "I11", f'="from "&FIXED(SUMIFS(tbl_nowcast[lo80_eur_kg],{nc}),2)&" to "&FIXED(SUMIFS(tbl_nowcast[hi80_eur_kg],{nc}),2)&" · method "&'
                   'XLOOKUP(1,(tbl_nowcast[material_id]=SelMat)*(tbl_nowcast[selected]=1)*(tbl_nowcast[horizon]=1),tbl_nowcast[method])', size=9, color=INK2)
    fml(ws, "N9", '=COUNTIFS(tbl_recon[material_key],"*|"&SelMat&"|*",tbl_recon[latest_status],"ALERT")&" · "&'
                  'COUNTIFS(tbl_checks[material_id],SelMat,tbl_checks[check_id],"QC03")', size=22, bold=True, color=RED)
    ws.Range("N11").Value = "source pairs in alert · robust outlier months (QC03)"
    font(ws.Range("N11"), 9, color=INK2)

    # chart helper columns (spilled, far right) and history chart
    h = "tbl_monthly[material_id]=SelMat"
    fml(ws, "AA5", f"=FILTER(tbl_monthly[period],{h})", "yyyy-mm")
    fml(ws, "AB5", f'=FILTER(IF(tbl_monthly[eu_import_uv_eur_kg]="",NA(),tbl_monthly[eu_import_uv_eur_kg]),{h})', "#,##0.00")
    fml(ws, "AC5", f'=FILTER(IF(tbl_monthly[eu_import_uv_raw_eur_kg]="",NA(),tbl_monthly[eu_import_uv_raw_eur_kg]),{h})', "#,##0.00")
    fml(ws, "AD5", f'=FILTER(IF(tbl_monthly[wb_price_eur_kg]="",NA(),tbl_monthly[wb_price_eur_kg]),{h})', "#,##0.00")
    for c, t in zip(["AA4", "AB4", "AC4", "AD4"], ["period", "validated", "published", "LME (World Bank)"]):
        label(ws, c, t, 8, True, MUTED)
    add_name(wb, "ch_x", "=Dashboard!$AA$5#")
    add_name(wb, "ch_valid", "=Dashboard!$AB$5#")
    add_name(wb, "ch_raw", "=Dashboard!$AC$5#")
    add_name(wb, "ch_wb", "=Dashboard!$AD$5#")
    book = OUT.name
    line_chart(ws, "B14", "J31", "EUR per kg: validated (blue), as published (grey), exchange benchmark (dashed)",
               [("Validated unit value", f"='{book}'!ch_x", f"='{book}'!ch_valid", BLUE, 0),
                ("As published", f"='{book}'!ch_x", f"='{book}'!ch_raw", "B4B2AD", 0),
                ("LME via World Bank", f"='{book}'!ch_x", f"='{book}'!ch_wb", INK2, 1)])

    # reconciliation pairs of the selected material
    card(ws, "L14:Q31")
    label(ws, "L14", "SOURCE PAIRS FOR THIS MATERIAL (see Reconciliation)", 8, True, INK2)
    for c, t in zip("LMNOPQ", ["Pair", "Comparison", "Median gap", "Latest gap", "Status", "Card"]):
        label(ws, f"{c}15", t, 8, True, INK2)
    fml(ws, "L16", '=LET(t,FILTER(tbl_recon,ISNUMBER(SEARCH("|"&SelMat&"|",tbl_recon[material_key])),""),'
                   'IF(INDEX(t,1,1)="","No pair",CHOOSECOLS(t,1,3,6,12,13,4)))', size=8, area="L16:Q30")
    numfmt(ws.Range("N16:O30"), "+0%;-0%;0%")
    ws.Range("M16:M30").WrapText = True
    ws.Range("L16:Q30").VerticalAlignment = -4160

    # overview of all materials
    label(ws, "B33", "All materials, by stage of the chain", 11, True, INK)
    heads = ["Stage", "ID", "Material", "Unit value 3m (EUR/kg)", "12-month change", "Last 24 months", "Alerts",
             "Nowcast next month", "80% low", "80% high", "Outlier months"]
    for c, t in zip("BCDEFGHIJKL", heads):
        label(ws, f"{c}34", t, 8, True, INK2)
    ws.Range("B34:L34").WrapText = True
    fml(ws, "C35", "=SORTBY(tbl_materials[material_id],tbl_materials[stage_order],1,tbl_materials[material_id],1)", size=9, bold=True, area="C35:C49")
    fml(ws, "B35", "=XLOOKUP(C35#,tbl_materials[material_id],tbl_materials[chain_stage])", size=9, color=INK2, area="B35:B49")
    fml(ws, "D35", "=XLOOKUP(C35#,tbl_materials[material_id],tbl_materials[material])", size=9, area="D35:D49")
    fml(ws, "E35", "=SUMIFS(tbl_monthly[eu_import_uv3_eur_kg],tbl_monthly[material_id],C35#,tbl_monthly[period],LatestMonth)", "#,##0.00", 9, area="E35:E49")
    fml(ws, "F35", "=IFERROR(E35#/SUMIFS(tbl_monthly[eu_import_uv3_eur_kg],tbl_monthly[material_id],C35#,tbl_monthly[period],EDATE(LatestMonth,-12))-1,NA())", "+0%;-0%;0%", 9, area="F35:F49")
    fml(ws, "H35", '=COUNTIFS(tbl_recon[material_key],"*|"&C35#&"|*",tbl_recon[latest_status],"ALERT")', "0", 9, area="H35:H49")
    nca = "tbl_nowcast[material_id],C35#,tbl_nowcast[selected],1,tbl_nowcast[horizon],1"
    fml(ws, "I35", f"=SUMIFS(tbl_nowcast[nowcast_eur_kg],{nca})", "#,##0.00", 9, area="I35:I49")
    fml(ws, "J35", f"=SUMIFS(tbl_nowcast[lo80_eur_kg],{nca})", "#,##0.00", 9, color=INK2, area="J35:J49")
    fml(ws, "K35", f"=SUMIFS(tbl_nowcast[hi80_eur_kg],{nca})", "#,##0.00", 9, color=INK2, area="K35:K49")
    fml(ws, "L35", '=COUNTIFS(tbl_checks[material_id],C35#,tbl_checks[check_id],"QC03")', "0", 9, area="L35:L49")
    # sparkline source: 15 materials x 24 months, one SUMIFS spilling in two dimensions
    fml(ws, "AF35", "=SUMIFS(tbl_monthly[eu_import_uv3_eur_kg],tbl_monthly[material_id],C35#,tbl_monthly[period],EDATE(LatestMonth,SEQUENCE(1,24,-23)))", "0.00", 8)
    label(ws, "AF34", "sparkline source (24 months x material)", 8, True, MUTED)
    sg = ws.Range("G35:G49").SparklineGroups.Add(1, "Dashboard!AF35:BC49")
    sg.SeriesColor.Color = rgb(BLUE)
    sg.Points.Lowpoint.Visible = False
    for r in range(35, 50):
        ws.Rows(r).RowHeight = 18
    # conditional formats: change sign, alerts
    f = ws.Range("F35:F49").FormatConditions
    f.Add(1, 6, "=0").Font.Color = rgb(RED)                          # xlCellValue, xlLess
    f.Add(1, 5, "=0").Font.Color = rgb(BLUE)                         # xlGreater
    a = ws.Range("H35:H49").FormatConditions.Add(1, 5, "=0")
    a.Interior.Color = rgb(RED_TINT)
    card(ws, "B34:L49")
    ws.Range("B35:L49").Interior.Color = rgb(CARD)
    footer(ws, 51, "Sources: Eurostat Comext, World Bank Pink Sheet (CC BY 4.0), USGS, UN Comtrade, ECB. " + FOOTER)
    ws.Columns("AA:BC").ColumnWidth = 9


def build_reconciliation(wb, ws, lo):
    lo.ListColumns.Add().Name = "card"
    lo.ListColumns("card").DataBodyRange.Formula2 = (
        '=IF([@[discrepancy_id]]="","",HYPERLINK("#\'Discrepancy log\'!B"&(MATCH([@[discrepancy_id]],tbl_discrepancies[discrepancy_id],0)'
        '+ROW(tbl_discrepancies[#Headers])),"open "&[@[discrepancy_id]]))')
    style_table(lo, pct_cols=["median_gap", "min_gap", "max_gap", "latest_gap", "expected_low", "expected_high"],
                date_cols=["first_period", "last_period"],
                widths={"comparison": 46, "pair_id": 7, "material_id": 10, "discrepancy_id": 9, "material_key": 4})
    lo.ListColumns("material_key").Range.EntireColumn.Hidden = True
    body = lo.DataBodyRange
    ws.Activate()
    body.Cells(1, 1).Select()                     # conditional-format formulas are relative to the active cell
    status_cell = lo.ListColumns("latest_status").DataBodyRange.Cells(1, 1).GetAddress(False, True)
    fc = body.FormatConditions.Add(2, None, f'={status_cell}="ALERT"')   # 2 = xlExpression
    fc.Interior.Color = rgb(RED_TINT)
    # pair explorer
    col = "T"
    label(ws, f"{col}5", "Pair", 10, True, INK)
    ws.Range(f"U5").Value = "R01"
    validation_list(ws.Range("U5"), "=PairList")
    add_name(wb, "SelPair", "=Reconciliation!$U$5")
    fml(ws, "V5", "=XLOOKUP(SelPair,tbl_recon[pair_id],tbl_recon[comparison])", size=9, color=INK2)
    p = "tbl_recon_detail[pair_id]=SelPair"
    fml(ws, "AH8", f"=FILTER(tbl_recon_detail[period],{p})", "yyyy-mm", 8)
    fml(ws, "AI8", f"=FILTER(tbl_recon_detail[gap],{p})", "0.0%", 8)
    fml(ws, "AJ8", f'=FILTER(IF(tbl_recon_detail[expected_low]="",NA(),tbl_recon_detail[expected_low]),{p})', "0.0%", 8)
    fml(ws, "AK8", f'=FILTER(IF(tbl_recon_detail[expected_high]="",NA(),tbl_recon_detail[expected_high]),{p})', "0.0%", 8)
    for c, t in zip(["AH7", "AI7", "AJ7", "AK7"], ["period", "gap", "band low", "band high"]):
        label(ws, c, t, 8, True, MUTED)
    for n, c in [("rc_x", "AH"), ("rc_gap", "AI"), ("rc_lo", "AJ"), ("rc_hi", "AK")]:
        add_name(wb, n, f"=Reconciliation!${c}$8#")
    book = OUT.name
    ch = line_chart(ws, "T7", "AE26", "Gap between the two sources (blue) and expected band (dashed)",
                    [("Gap", f"='{book}'!rc_x", f"='{book}'!rc_gap", BLUE, 0),
                     ("Band low", f"='{book}'!rc_x", f"='{book}'!rc_lo", MUTED, 1),
                     ("Band high", f"='{book}'!rc_x", f"='{book}'!rc_hi", MUTED, 1)])
    numfmt(ch.Axes(2).TickLabels, "0%")
    ws.Columns("T:AE").ColumnWidth = 8


def build_nowcast(wb, ws):
    page(ws, "Nowcasting the months Comext has not published yet",
         "Excel's FORECAST.ETS (no seasonality) with an 80% FORECAST.ETS.CONFINT interval, tested on the past; "
         "compared with the Python back-test of three methods.", "PUBLIC DATA", "B:Q")
    for c, w in {"B": 16, "C": 13, "D": 13, "E": 13, "F": 13, "G": 3, "H": 12, "I": 12, "J": 12, "K": 3}.items():
        ws.Columns(c).ColumnWidth = w
    label(ws, "B5", "Material", 10, True, INK)
    ws.Range("C5").Value = "CU"
    validation_list(ws.Range("C5"), "=MaterialList")
    add_name(wb, "SelNow", "=Nowcast!$C$5")
    fml(ws, "D5", "=XLOOKUP(SelNow,tbl_materials[material_id],tbl_materials[material])", size=11, bold=True)
    # history (validated unit value) used by every formula of the sheet
    label(ws, "AA7", "period", 8, True, MUTED)
    label(ws, "AB7", "validated EUR/kg", 8, True, MUTED)
    fml(ws, "AA8", "=FILTER(tbl_monthly[period],tbl_monthly[material_id]=SelNow)", "yyyy-mm", 8)
    fml(ws, "AB8", "=FILTER(tbl_monthly[eu_import_uv_eur_kg],tbl_monthly[material_id]=SelNow)", "#,##0.00", 8)
    add_name(wb, "nc_t", "=Nowcast!$AA$8#")
    add_name(wb, "nc_v", "=Nowcast!$AB$8#")
    fml(ws, "AC8", "=ROWS(AA8#)", "0", 8)
    label(ws, "AC7", "months", 8, True, MUTED)
    add_name(wb, "nc_n", "=Nowcast!$AC$8")

    card(ws, "B7:F12")
    label(ws, "B7", "EXCEL NOWCAST (FORECAST.ETS)", 8, True, INK2)
    for c, t in zip("BCDEF", ["Month", "Nowcast", "80% low", "80% high", "Python (selected)"]):
        label(ws, f"{c}8", t, 8, True, INK2)
    for i, r in enumerate((9, 10), start=1):
        fml(ws, f"B{r}", f"=EDATE(MAX(nc_t),{i})", "mmm yyyy", 10, True)
        fml(ws, f"C{r}", f"=FORECAST.ETS(B{r},nc_v,nc_t,0,1)", "#,##0.00", 11, True, BLUE)
        fml(ws, f"D{r}", f"=C{r}-FORECAST.ETS.CONFINT(B{r},nc_v,nc_t,0.8,0,1)", "#,##0.00", 10, color=INK2)
        fml(ws, f"E{r}", f"=C{r}+FORECAST.ETS.CONFINT(B{r},nc_v,nc_t,0.8,0,1)", "#,##0.00", 10, color=INK2)
        fml(ws, f"F{r}", f"=SUMIFS(tbl_nowcast[nowcast_eur_kg],tbl_nowcast[material_id],SelNow,tbl_nowcast[selected],1,tbl_nowcast[horizon],{i})", "#,##0.00", 10)
    fml(ws, "B11", '="Python selected method: "&XLOOKUP(1,(tbl_nowcast[material_id]=SelNow)*(tbl_nowcast[selected]=1)*(tbl_nowcast[horizon]=1),tbl_nowcast[method])', size=9, color=INK2)

    card(ws, "B14:F23")
    label(ws, "B14", "BACK-TEST: IF I HAD FORECAST 6 MONTHS AGO", 8, True, INK2)
    for c, t in zip("BCDEF", ["Month", "Actual", "Forecast", "Abs. error", ""]):
        label(ws, f"{c}15", t, 8, True, INK2)
    for k in range(1, 7):
        r = 15 + k
        fml(ws, f"B{r}", f"=INDEX(nc_t,nc_n-6+{k})", "mmm yyyy", 9)
        fml(ws, f"C{r}", f"=INDEX(nc_v,nc_n-6+{k})", "#,##0.00", 9)
        fml(ws, f"D{r}", f"=FORECAST.ETS(B{r},INDEX(nc_v,1):INDEX(nc_v,nc_n-6),INDEX(nc_t,1):INDEX(nc_t,nc_n-6),0,1)", "#,##0.00", 9)
        fml(ws, f"E{r}", f"=ABS(C{r}/D{r}-1)", "0.0%", 9)
    label(ws, "B22", "Mean absolute % error", 9, True, INK)
    fml(ws, "E22", "=AVERAGE(E16:E21)", "0.0%", 11, True, RED)

    card(ws, "H7:Q23")
    label(ws, "H7", "PYTHON BACK-TEST, 24 ROLLING ORIGINS (mean absolute % error by horizon)", 8, True, INK2)
    for c, t in zip("HIJ", ["Horizon", "naive", "ets"]):
        label(ws, f"{c}8", t, 8, True, INK2)
    label(ws, "K8", "signal", 8, True, INK2)
    fml(ws, "H9", "=SEQUENCE(6)", "0", 9)
    for c, m in zip("IJK", ["naive", "ets", "signal"]):
        fml(ws, f"{c}9", f'=IFERROR(AVERAGEIFS(tbl_backtest[mape],tbl_backtest[material_id],SelNow,tbl_backtest[method],"{m}",tbl_backtest[horizon],H9#),"-")', "0.0%", 9, area=f"{c}9:{c}14")
    ws.Columns("K").ColumnWidth = 10
    label(ws, "H16", "naive = last value · ets = damped-trend exponential smoothing · signal = regression on the World Bank price "
                     "(metals only, known one month earlier). Intervals = 10th-90th percentile of past errors.", 8, False, INK2)
    ws.Range("H16:Q18").Merge()
    ws.Range("H16").WrapText = True
    ws.Range("H16").VerticalAlignment = -4160

    # chart: last 36 months + nowcast and interval
    fml(ws, "AD8", "=VSTACK(TAKE(nc_t,-36),B9:B10)", "yyyy-mm", 8)
    fml(ws, "AE8", "=VSTACK(TAKE(nc_v,-36),NA()*{1;1})", "#,##0.00", 8)
    fml(ws, "AF8", "=VSTACK(IF(SEQUENCE(35),NA()),INDEX(nc_v,nc_n),C9:C10)", "#,##0.00", 8)
    fml(ws, "AG8", "=VSTACK(IF(SEQUENCE(36),NA()),D9:D10)", "#,##0.00", 8)
    fml(ws, "AH8", "=VSTACK(IF(SEQUENCE(36),NA()),E9:E10)", "#,##0.00", 8)
    for c, t in zip(["AD7", "AE7", "AF7", "AG7", "AH7"], ["chart x", "actual", "nowcast", "low", "high"]):
        label(ws, c, t, 8, True, MUTED)
    line_chart(ws, "B25", "Q42", "Validated EU import unit value, EUR/kg: actual (blue), nowcast (red), 80% interval (dashed)",
               [("Actual", "=Nowcast!$AD$8:$AD$45", "=Nowcast!$AE$8:$AE$45", BLUE, 0),
                ("Nowcast", "=Nowcast!$AD$8:$AD$45", "=Nowcast!$AF$8:$AF$45", RED, 0),
                ("80% low", "=Nowcast!$AD$8:$AD$45", "=Nowcast!$AG$8:$AG$45", MUTED, 1),
                ("80% high", "=Nowcast!$AD$8:$AD$45", "=Nowcast!$AH$8:$AH$45", MUTED, 1)])
    footer(ws, 44)


def build_quality(wb, ws, lo):
    page(ws, "Quality checks run on every refresh",
         "14 rules on completeness, units, outliers, nomenclature, confidentiality and freshness (sql/03_checks.sql). "
         "Implausible flows are excluded from the validated series.", "PUBLIC DATA", "B:Z")
    rules = {"QC01": "Missing month", "QC02": "Value without quantity", "QC03": "Robust outlier (median/MAD)",
             "QC04": "Thin trade", "QC05": "Nomenclature change", "QC06": "Code outside validity", "QC07": "Duplicates",
             "QC08": "kg vs m3 units", "QC09": "Confidential partner", "QC10": "Withheld reference", "QC11": "Freshness",
             "QC12": "Missing FX", "QC13": "Estimated quantity", "QC14": "Implausible flow (excluded)"}
    keys = "{" + ",".join(f'"{k}"' for k in rules) + "}"
    vals = "{" + ",".join(f'"{v}"' for v in rules.values()) + "}"
    style_table(lo, widths={"check_name": 30, "severity": 9, "check_id": 8, "rows_flagged": 11, "materials_affected": 11})
    sev = lo.ListColumns("severity").DataBodyRange
    sev.FormatConditions.Add(1, 3, '="error"').Interior.Color = rgb(RED_TINT)      # xlEqual
    sev.FormatConditions.Add(1, 3, '="warn"').Interior.Color = rgb("FBE7C6")
    # matrix: flags per material and check (two-dimensional COUNTIFS)
    label(ws, "I7", "Rows flagged per material and check", 10, True, INK)
    fml(ws, "J8", "=" + keys, size=8, bold=True, color=INK2)
    fml(ws, "I9", "=SORTBY(tbl_materials[material_id],tbl_materials[stage_order],1)", size=9, bold=True)
    fml(ws, "J9", "=COUNTIFS(tbl_checks[material_id],I9#,tbl_checks[check_id],J8#)", "0;;-", 9)
    ws.Range("J9:W23").FormatConditions.AddColorScale(2)
    cs = ws.Range("J9:W23").FormatConditions(ws.Range("J9:W23").FormatConditions.Count)
    cs.ColorScaleCriteria(1).FormatColor.Color = rgb(CARD)
    cs.ColorScaleCriteria(2).FormatColor.Color = rgb("86B6EF")
    ws.Columns("I").ColumnWidth = 9
    ws.Columns("J:W").ColumnWidth = 6
    label(ws, "I25", "Rule names: " + "; ".join(f"{k} {v}" for k, v in rules.items()), 8, False, INK2)
    ws.Range("I25:W27").Merge()
    ws.Range("I25").WrapText = True
    ws.Range("I25").VerticalAlignment = -4160
    # largest flags
    label(ws, "B30", "Errors and the largest unit-value outliers (QC03)", 10, True, INK)
    for c, t in zip("BCDEF", ["Check", "Severity", "Material", "Period", "Detail"]):
        label(ws, f"{c}31", t, 8, True, INK2)
    fml(ws, "B32", '=LET(f,FILTER(CHOOSECOLS(tbl_checks,1,3,4,6,8,7),(tbl_checks[severity]="error")+(tbl_checks[check_id]="QC03")),'
                   's,SORTBY(f,CHOOSECOLS(f,1),1,ABS(CHOOSECOLS(f,6)),-1),TAKE(CHOOSECOLS(s,1,2,3,4,5),30))', size=9, area="B32:F61")
    numfmt(ws.Range("E32:E61"), "yyyy-mm")
    ws.Columns("F").ColumnWidth = 80
    footer(ws, 63)


def build_discrepancy(ws, lo):
    page(ws, "Discrepancy log: finding, root cause, evidence, correction, prevention",
         "Generated from seeds/discrepancy_register.csv with evidence recomputed from the data at each pipeline run.",
         "PUBLIC DATA", "B:I")
    style_table(lo, wrap_cols=["title", "root_cause", "correction", "prevention", "evidence"],
                widths={"discrepancy_id": 8, "title": 30, "materials": 12, "root_cause": 48, "correction": 34,
                        "prevention": 34, "status": 12, "evidence": 60})
    lo.DataBodyRange.VerticalAlignment = -4160
    footer(ws, lo.Range.Row + lo.Range.Rows.Count + 2)


def scrub(path: Path) -> None:
    """Remove personal / local metadata that Excel writes on save:
    docProps creator/lastModifiedBy/company, the absolute folder path in workbook.xml, and the
    cached value of the RootFolder formula (Excel recalculates it on open)."""
    tmp = Path(tempfile.mkdtemp()) / path.name
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "docProps/core.xml":
                s = data.decode("utf-8")
                for tag in ("dc:creator", "cp:lastModifiedBy", "dc:title", "dc:subject", "cp:keywords", "dc:description"):
                    s = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}></{tag}>", s, flags=re.S)
                data = s.encode("utf-8")
            elif item.filename == "docProps/app.xml":
                s = data.decode("utf-8")
                for tag in ("Company", "Manager"):
                    s = re.sub(rf"<{tag}>.*?</{tag}>", f"<{tag}></{tag}>", s, flags=re.S)
                data = s.encode("utf-8")
            elif item.filename == "xl/workbook.xml":
                s = data.decode("utf-8")
                s = re.sub(r"<mc:AlternateContent[^>]*>\s*<mc:Choice[^>]*>\s*<x15ac:absPath[^>]*/>\s*</mc:Choice>\s*</mc:AlternateContent>", "", s)
                s = re.sub(r"<x15ac:absPath[^>]*/>", "", s)
                s = re.sub(r"<calcPr([^>]*?)/>", lambda m: "<calcPr" + re.sub(r'\s*fullCalcOnLoad="[^"]*"', "", m.group(1)) + ' fullCalcOnLoad="1"/>', s)
                data = s.encode("utf-8")
            elif item.filename.startswith("xl/worksheets/sheet") and item.filename.endswith(".xml"):
                s = data.decode("utf-8")
                # cached text of CELL("filename") formulas = local folder: drop it
                s = re.sub(r'(<f[^>]*>[^<]*CELL\((?:"|&quot;)filename[^<]*</f>)<v>[^<]*</v>', r"\1<v></v>", s)
                data = s.encode("utf-8")
            zout.writestr(item, data)
    shutil.move(str(tmp), path)


def main() -> None:
    pythoncom.CoInitialize()
    OUT.parent.mkdir(exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    xl = win32.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    xl.ScreenUpdating = False
    try:
        wb = xl.Workbooks.Add()
        wb.Styles("Normal").Font.Name = FONT
        wb.Styles("Normal").Font.Size = 10
        names = ["README", "Dashboard", "Reconciliation", "Nowcast", "Quality checks", "Data dictionary", "Discrepancy log",
                 "data_monthly", "data_recon_detail", "data_nowcast", "data_backtest", "data_checks", "data_annual",
                 "data_coverage", "data_events"]
        while wb.Worksheets.Count < len(names):
            wb.Worksheets.Add(After=wb.Worksheets(wb.Worksheets.Count))
        for i, n in enumerate(names, start=1):
            wb.Worksheets(i).Name = n
            wb.Worksheets(i).Tab.Color = rgb(BLUE if not n.startswith("data_") else "B4B2AD")
        build_readme(wb, wb.Worksheets("README"))
        wb.SaveAs(str(OUT), 51)                                     # saved first, so CELL("filename") knows the folder
        xl.Calculate()
        build_dictionary_static(wb.Worksheets("Data dictionary"))
        page(wb.Worksheets("Reconciliation"), "Where sources disagree, and whether the gap is expected",
             "Each pair has an expected band (e.g. CIF import value above the LME price). Red rows = latest gap outside its band. "
             "'card' opens the root-cause card.", "PUBLIC DATA", "B:AE")
        wb.Queries.FastCombine = True                               # queries combine the RootFolder cell with files
        tables = {}
        for q in QUERIES:
            t0 = time.time()
            tables[q[4]] = load_query(wb, *q)
            print(f"  query {q[0]:24s} -> {q[4]:18s} {tables[q[4]].ListRows.Count:>6} rows ({time.time() - t0:.1f}s)")
        add_name(wb, "MaterialList", "=tbl_materials[material_id]")
        add_name(wb, "PairList", "=tbl_recon[pair_id]")
        style_table(tables["tbl_materials"], widths={"material": 26, "fab_use": 30, "purity_or_grade": 30, "notes": 40})
        style_table(tables["tbl_concordance"], widths={"cn8_label": 50, "change_note": 40})
        build_dashboard(wb, wb.Worksheets("Dashboard"))
        build_reconciliation(wb, wb.Worksheets("Reconciliation"), tables["tbl_recon"])
        build_nowcast(wb, wb.Worksheets("Nowcast"))
        build_quality(wb, wb.Worksheets("Quality checks"), tables["tbl_quality"])
        build_discrepancy(wb.Worksheets("Discrepancy log"), tables["tbl_discrepancies"])
        for n in names:
            ws = wb.Worksheets(n)
            if not n.startswith("data_"):
                no_gridlines(wb, ws)
        areas = {"README": "$A$1:$L$25", "Dashboard": "$A$1:$Q$52", "Reconciliation": "$A$1:$AE$33",
                 "Nowcast": "$A$1:$Q$45", "Quality checks": "$A$1:$W$63", "Data dictionary": "$A$1:$U$48",
                 "Discrepancy log": "$A$1:$J$24"}
        for n, a in areas.items():
            ps = wb.Worksheets(n).PageSetup
            ps.PrintArea = a
            ps.Orientation = 2                                       # landscape
            ps.Zoom = False
            ps.FitToPagesWide = 1
            ps.FitToPagesTall = 1
        for prop in ("Author", "Last Author", "Company", "Manager", "Title", "Subject", "Keywords", "Comments"):
            try:
                wb.BuiltinDocumentProperties(prop).Value = ""
            except Exception:
                pass
        xl.ScreenUpdating = True
        wb.Worksheets("Dashboard").Activate()
        xl.CalculateFull()
        wb.Save()
        wb.Close(False)
    except Exception:
        # never leave a half-built, unscrubbed workbook behind (it would carry the Office user name)
        try:
            wb.Close(False)
        except Exception:
            pass
        OUT.unlink(missing_ok=True)
        raise
    finally:
        try:
            xl.Quit()
        except Exception:                                           # Excel already gone
            pass
    scrub(OUT)
    print(f"  saved and scrubbed {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
