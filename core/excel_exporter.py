"""
core/excel_exporter.py
-----------------------
Tách logic xuất Excel ra module riêng để app.py và main.py cùng dùng.
Hai sheet:
  • "Test Cases"  – id, title, type, priority, precondition, steps,
                    expected_result, actual_result (trống), status (trống),
                    db_query, db_expected, test_data_ref
  • "Test Data"   – id, description, data (flattened thành key: value)
"""

from __future__ import annotations
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side


# ─────────────────────────────────────────────
# STYLE HELPERS
# ─────────────────────────────────────────────


def _header_style() -> tuple:
    fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    font = Font(bold=True, color="FFFFFF", size=11)
    align = Alignment(vertical="top", wrap_text=True, horizontal="left")
    return fill, font, align


def _thin_border() -> Border:
    thin = Side(style="thin", color="CCCCCC")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


_PRIORITY_FILLS = {
    "High": PatternFill(start_color="FFE0E0", end_color="FFE0E0", fill_type="solid"),
    "Medium": PatternFill(start_color="FFF9E0", end_color="FFF9E0", fill_type="solid"),
    "Low": PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid"),
}

_BODY_ALIGN = Alignment(vertical="top", wrap_text=True, horizontal="left")
_BODY_FONT = Font(size=10)
_STATUS_FILL = PatternFill(
    start_color="F0F0F0", end_color="F0F0F0", fill_type="solid"
)  # actual/status cols


def _write_headers(ws, headers: list[str]) -> None:
    hdr_fill, hdr_font, hdr_align = _header_style()
    border = _thin_border()
    ws.append(headers)
    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = hdr_align
        cell.border = border
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 22


def _apply_body_style(cell, priority_fill, border) -> None:
    cell.font = _BODY_FONT
    cell.alignment = _BODY_ALIGN
    cell.border = border
    cell.fill = priority_fill


# ─────────────────────────────────────────────
# SHEET 1: TEST CASES
# ─────────────────────────────────────────────

# Mapping key → Excel header | column width
_TC_COLUMNS: list[tuple[str, str, int]] = [
    ("id", "ID", 10),
    ("title", "Title", 35),
    ("coverage_type", "Type", 14),
    ("priority", "Priority", 12),
    ("precondition", "Precondition", 32),
    ("steps_text", "Steps", 45),
    ("expected_result", "Expected Result", 42),
    ("actual_result", "Actual Result", 30),  # để trống
    ("status_result", "Status", 12),  # để trống
    ("db_query", "DB Query", 35),
    ("db_expected", "DB Expected", 25),
    ("test_data_ref", "Test Data Ref", 14),
]

# Column indices (1-based) cho actual_result và status_result → tô màu khác
_EMPTY_COLS = {8, 9}  # actual_result, status_result


def _build_tc_sheet(ws, test_cases: list[dict]) -> None:
    headers = [col[1] for col in _TC_COLUMNS]
    keys = [col[0] for col in _TC_COLUMNS]
    widths = {col[1]: col[2] for col in _TC_COLUMNS}
    border = _thin_border()

    _write_headers(ws, headers)

    for row_idx, tc in enumerate(test_cases, start=2):
        row_data = [tc.get(k, "") for k in keys]
        ws.append(row_data)

        p_fill = _PRIORITY_FILLS.get(
            tc.get("priority", "Medium"), _PRIORITY_FILLS["Medium"]
        )
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            fill = _STATUS_FILL if col_idx in _EMPTY_COLS else p_fill
            _apply_body_style(cell, fill, border)

    for col in ws.columns:
        hdr_val = ws.cell(row=1, column=col[0].column).value
        ws.column_dimensions[col[0].column_letter].width = widths.get(hdr_val, 20)

    ws.auto_filter.ref = ws.dimensions


# ─────────────────────────────────────────────
# SHEET 2: TEST DATA
# ─────────────────────────────────────────────

_TD_COLUMNS: list[tuple[str, str, int]] = [
    ("id", "TD ID", 12),
    ("description", "Description", 40),
    ("data_text", "Data (key: value)", 60),
]


def _build_td_sheet(ws, test_data_set: list[dict]) -> None:
    headers = [col[1] for col in _TD_COLUMNS]
    keys = [col[0] for col in _TD_COLUMNS]
    widths = {col[1]: col[2] for col in _TD_COLUMNS}
    border = _thin_border()

    _write_headers(ws, headers)

    td_fill = PatternFill(start_color="EAF4FB", end_color="EAF4FB", fill_type="solid")

    for row_idx, td in enumerate(test_data_set, start=2):
        row_data = [td.get(k, "") for k in keys]
        ws.append(row_data)
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            _apply_body_style(cell, td_fill, border)

    for col in ws.columns:
        hdr_val = ws.cell(row=1, column=col[0].column).value
        ws.column_dimensions[col[0].column_letter].width = widths.get(hdr_val, 20)

    ws.auto_filter.ref = ws.dimensions


# ─────────────────────────────────────────────
# PUBLIC
# ─────────────────────────────────────────────


def to_excel(test_cases: list[dict], test_data_set: list[dict]) -> bytes:
    """
    Tạo file .xlsx với 2 sheet.

    Parameters
    ----------
    test_cases    : list[dict] từ run_pipeline()["test_cases"]
    test_data_set : list[dict] từ run_pipeline()["test_data_set"]

    Returns
    -------
    bytes — nội dung file .xlsx, sẵn sàng để ghi ra disk hoặc stream qua HTTP.
    """
    wb = Workbook()

    ws_tc = wb.active
    ws_tc.title = "Test Cases"
    _build_tc_sheet(ws_tc, test_cases)

    ws_td = wb.create_sheet("Test Data")
    _build_td_sheet(ws_td, test_data_set)

    output = BytesIO()
    wb.save(output)
    return output.getvalue()
