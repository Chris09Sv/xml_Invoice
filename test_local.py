

import pandas as pd
import xml.etree.ElementTree as ET
import unicodedata
from typing import Dict, Optional


def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    def norm(s):
        s = unicodedata.normalize("NFKC", str(s)).strip()
        return s
    out = df.copy()
    out.columns = [norm(c) for c in out.columns]
    return out

def _find_col(df: pd.DataFrame, candidates):
    """Devuelve el nombre REAL de la primera columna que exista (case-insensitive)."""
    if df is None or df.empty:
        return None
    cmap = {c.lower(): c for c in df.columns}
    for cand in candidates:
        c = str(cand).strip().lower()
        if c in cmap:
            return cmap[c]
    return None

def _first_value(df: pd.DataFrame, candidates, default=None):
    if df is None or df.empty:
        return default
    col = _find_col(df, candidates)
    if not col:
        return default
    s = df[col].dropna()
    return s.iloc[0] if not s.empty else default

def _iso_dt(val, default=None):
    if pd.isna(val):
        return default
    ts = pd.to_datetime(val, dayfirst=True, errors="coerce")
    return default if pd.isna(ts) else ts.isoformat()

def _text_or_none(x) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s if s != "" and s.lower() != "nan" else None

# %% [markdown]
# ==== Carga del Excel con múltiples hojas ====

EXCEL_PATH = "C:/Users/crist/Downloads/cxml_template_extended.xlsx"  # <-- cambia a tu ruta real

def _load_sheet(xls: pd.ExcelFile, name: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(xls, sheet_name=name)
        return _normalize_cols(df)
    except Exception:
        return pd.DataFrame()

def load_workbook(path: str) -> Dict[str, pd.DataFrame]:
    xls = pd.ExcelFile(path)
    sheets = {
        "Envelope":   _load_sheet(xls, "envelope"),
        "Header":     _load_sheet(xls, "header"),
        "Partners":   _load_sheet(xls, "partners"),
        "IdRefs":     _load_sheet(xls, "idreferences"),
        "OrderInfo":  _load_sheet(xls, "orderinfo"),
        "Items":      _load_sheet(xls, "items"),
        "Taxes":      _load_sheet(xls, "taxes"),
        "Summary":    _load_sheet(xls, "summary"),
        "Extrinsics": _load_sheet(xls, "extrinsics"),
    }
    # Validación: todas con InvoiceID
    for nm, df in sheets.items():
        if not df.empty and "invoiceid" not in [c.lower() for c in df.columns]:
            raise ValueError(f"La hoja '{nm}' no contiene la columna 'InvoiceID'.")
    return sheets

sheets = load_workbook(EXCEL_PATH)
print(sheets)