

import pandas as pd
import xml.etree.ElementTree as ET
import unicodedata
from typing import Dict, Optional
from db import get_connection


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


import re
from typing import Dict
import pandas as pd

# --- Utilidades ---
_TABLE_NAME_RE = re.compile(r"^[A-Za-z0-9_\.]+$")  # permite schema.table también

def _sanitize_table_name(table: str) -> str:
    """
    Verifica que el nombre de tabla solo contenga caracteres permitidos.
    Lanza ValueError si no es seguro.
    """
    if not isinstance(table, str) or not table:
        raise ValueError("Nombre de tabla inválido.")
    if not _TABLE_NAME_RE.match(table):
        raise ValueError(f"Nombre de tabla no permitido: {table!r}")
    return table

def _normalize_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normaliza nombres de columnas: strip() + lower() por defecto.
    Si ya tienes otra implementación, reemplaza esta función.
    """
    if df is None or df.empty:
        return df
    df = df.copy()
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df
def _ensure_invoiceid(df):
    norm = dict(zip(df.columns, _normalize_cols(df.columns)))
    if 'invoiceid' in norm.values():
        return df
    # casos frecuentes
    if 'invoice_id' in df.columns:
        df = df.rename(columns={'invoice_id': 'InvoiceID'})
        return df
    if 'invoice' in norm.values():  # último recurso si alguien puso "Invoice Id"
        # busca la primera columna cuyo normalizado sea "invoice"
        for original, n in norm.items():
            if n == 'invoice':
                df = df.rename(columns={original: 'InvoiceID'})
                return df
    # si no hay forma, que falle con mensaje claro
    raise ValueError("No se encontró columna de factura (InvoiceID / invoice_id).")

# --- Lectura desde DB ---
def load_data(table: str, schema: str = None) -> pd.DataFrame:
    """
    Lee todos los registros de la tabla indicada desde la DB.
    `table` puede ser 'mytable' o 'schema.mytable' (si tu DB lo soporta).
    Devuelve un DataFrame.
    """
    table = table.strip()
    schema='public'
    if schema:
        full_name = f"{schema}.{table}"
    else:
        full_name = table

    # sanitizar para evitar inyección accidental
    _sanitize_table_name(full_name)

    query = f"SELECT * FROM {full_name};"
    # logging mínimo para depuración
    print(f"[load_data] Ejecutando query: {query}")
    con = get_connection('')
    # print(pd.read_sql(query,con))

    try:
        
        df2 = pd.read_sql(query, con=con)
        # df = _ensure_invoiceid(df2)
        return df2
    finally:
        # intentar cerrar si el objeto tiene close()
        try:
            if con is not None and hasattr(con, "close"):
                con.close()
        except Exception:
            pass

def _load_sheet(table_name: str) -> pd.DataFrame:
    """
    Reemplazo de la antigua función que venía del Excel.
    Intenta leer la tabla y normalizar columnas; si falla, devuelve DataFrame vacío.
    """
    df = load_data(table_name,'public')
    # print('-----------')
    try:
        df = load_data(table_name,'public')

        return _normalize_cols(df)
    except Exception as e:
        # Puedes cambiar print por logging si lo prefieres
        print(f"[WARN] No se pudo cargar tabla '{table_name}': {e}")
        return pd.DataFrame()

def load_workbook_from_db(table_map: Dict[str, str], schema: str = None) -> Dict[str, pd.DataFrame]:
    """
    table_map: mapping entre el nombre 'lógico' que usaba la UI/presentación y el nombre de tabla en la BD.
      Ej: {"Envelope": "envelope", "Header": "header", ...}
    schema: opcional, si todas las tablas están en un schema
    Devuelve dict con los mismos keys que table_map y DataFrames como valores.
    """
    sheets: Dict[str, pd.DataFrame] = {}
    for friendly_name, db_table in table_map.items():
        print(f"[load_workbook_from_db] Cargando '{friendly_name}' <- tabla '{db_table}'")
        df = _load_sheet(db_table if schema is None else f"{schema}.{db_table}")
        # print(df)
        sheets[friendly_name] = df

    # Validación: todas las que no estén vacías deben incluir 'invoiceid' (normalizado)
    for nm, df in sheets.items():
        print(f"[DEBUG] Hoja '{nm}' filas={len(df)} cols={list(df.columns) if not df.empty else 'EMPTY'}")
        if not df.empty and "invoice_id" not in [c.lower() for c in df.columns]:
            raise ValueError(f"La hoja '{nm}' no contiene la columna 'InvoiceID' (normalizada a 'invoiceid').")

    return sheets
TABLE_MAP = {
    "Envelope": "envelope",
    "Header": "header",
    "Partners": "partners",
    # "IdRefs": "idreferences",
    # "OrderInfo": "orderinfo",
    "Items": "items",
    "Taxes": "taxes",
    "Summary": "summary",
    "Extrinsics": "extrinsics",
}

sheets = load_workbook_from_db(TABLE_MAP, schema=None)  
print(sheets)