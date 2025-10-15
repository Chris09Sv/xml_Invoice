import requests
from pathlib import Path
from xml.dom import minidom
import pandas as pd
import xml.etree.ElementTree as ET
import unicodedata
from typing import Dict, Optional
from db import get_connection
import re
import numpy as np


def _attrib_if_not_none(**kwargs):
    """Devuelve solo los pares cuyo valor no sea None."""
    return {k: str(v) for k, v in kwargs.items() if v is not None}

def _add_el(parent, tag, **attrib):
    """Crea SubElement omitiendo atributos None."""
    return ET.SubElement(parent, tag, attrib=_attrib_if_not_none(**attrib))

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

def _first_value(df, cols, default=None):
    """
    Devuelve el primer valor no-nulo de la(s) columna(s) `cols` en `df`.
    `cols` puede ser str o lista/tupla de posibles nombres.
    Tolera df=None, dicts, y DataFrames; normaliza nombres (strip/lower).
    """
    import pandas as pd

    # Normaliza lista de candidatos
    if isinstance(cols, (list, tuple)):
        candidates = [c for c in cols if c is not None and c != ""]
    else:
        candidates = [cols]

    # Caso DataFrame
    if isinstance(df, pd.DataFrame) and not df.empty:
        # Mapa lower->nombre_real para tolerar mayúsculas/espacios
        colmap = {str(c).strip().lower(): c for c in df.columns}
        for name in candidates:
            key = str(name).strip().lower()
            if key in colmap:
                serie = df[colmap[key]]
                if len(serie) > 0:
                    val = serie.iloc[0]
                    if pd.isna(val) or val == "":
                        continue
                    return val
        return default

    # Caso dict (por si el "header" ya viene materializado)
    if isinstance(df, dict):
        # Probar en orden de aliases
        for name in candidates:
            key = str(name)
            if key in df:
                val = df.get(key, default)
                if val not in (None, ""):
                    return val
        return default

    # Cualquier otro caso
    return default


def _nonempty_df(df):
    import pandas as pd
    return isinstance(df, pd.DataFrame) and not df.empty

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


EXCEL_PATH = "C:/Users/crist/Downloads/cxml_template_extended.xlsx" 



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

def load_data(
    table: str,
    schema: str = "public",
    where: str = None,          # e.g. "COALESCE(record_active_ind,'Y')='Y'"
    columns: list = None        # e.g. ["gtp_id", "invoice_id", "invoice_curr"]
) -> pd.DataFrame:
    """
    Lee registros de la DB y devuelve un DataFrame.
    - `table`: nombre de tabla (con o sin schema)
    - `schema`: por defecto 'public'; si pasas None y table ya viene con schema, lo respetamos
    - `columns`: lista de columnas (si None => *)
    - `where`: condición SIN la palabra WHERE (se agrega automáticamente si viene)
    """
    table = table.strip()

    # Si el usuario pasó table con schema (p.ej. "otro.good_to_pay"), lo respetamos.
    if "." in table or not schema:
        full_name = table
    else:
        full_name = f"{schema}.{table}"

    _sanitize_table_name(full_name)  # asumes que ya existe

    cols = "*"
    if columns and len(columns) > 0:
        cols = ",".join(columns)

    query = f"SELECT {cols} FROM {full_name}"
    if where:
        query += f" WHERE {where}"

    print(f"[load_data] Ejecutando query: {query}")

    con = get_connection('')
    try:
        df = pd.read_sql(query, con=con)
        # Normaliza fechas útiles
        for col in ("invoice_date","receipt_date","business_date","add_datetime","update_datetime","verify_datetime"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        # Normaliza nombres
        df.columns = [c.strip().lower() for c in df.columns]
        return df
    finally:
        try:
            if con is not None and hasattr(con, "close"):
                con.close()
        except Exception:
            pass

def build_sheets_from_snapshot(snapshot: pd.DataFrame, invoice_id) -> dict:
    import pandas as pd

    # Helpers chiquitos
    def _blank_if_none(v):
        if v is None:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
        return v

    def _num_or_0(v):
        v = _blank_if_none(v)
        try:
            return float(v)
        except Exception:
            return 0.0

    g = snapshot[snapshot["invoice_id"] == invoice_id]
    if g.empty:
        raise ValueError(f"No hay registros en good_to_pay para invoice_id={invoice_id}")

    head = g.iloc[0].to_dict()
    now = pd.Timestamp.now()

    # =========================
    # Envelope 
    # =========================
    env = pd.DataFrame([{
        "payload_id": f"auto_{now.timestamp()}",
        "timestamp": now.isoformat(),
        "version": "1.2.045",
        "signature_version": "1.0",
        "deployment_mode": "production",
        "preferred_language": "en",
        "street": "", "city": "", "postalcode": "", "country": "", "isocountry": "",
        "from_domain": "NetworkId", "from_identity": "AN11183544707",
        "from_domain2": "VendorId", "from_identity2": "0001000585",
        "from_domain3": "PrivateID", "from_identity3": "0001000585",
        "to_cred1_domain": "", "to_cred1_identity": "",
        "to_cred2_domain": "", "to_cred2_identity": "",
        "sender_domain": "x", "sender_identity": "c",
        "sender_secret": "", "user_agent": "", "request_id": "",
        "from_corr_name":"London Stock Exchange Plc",
    }])

    # =========================
    # Header 
    # =========================
    hdr = pd.DataFrame([{
        "InvoiceID":               _blank_if_none(head.get("invoice_id")),
        "invoiceDate":             _blank_if_none(head.get("invoice_date")),
        "invoiceOrigin":           "supplier",   # no existe en GTP
        "operation":               "new",   # no existe en GTP
        "purpose":                 "",   # no existe en GTP
        "comments":                _blank_if_none(head.get("party_invoice_ref_no")),
        "paymentTerm_days":        "standard",   # no existe en GTP
        "isTaxInLine":             "yes",   # no existe en GTP
        "isAccountingInLine":      "",   # no existe en GTP
        "isShippingInLine":        "",   # no existe en GTP
        "isSpecialHandlingInLine": "",   # no existe en GTP
        "isDiscountInLine":        "",   # no existe en GTP
        "isPriceAdjustmentInLine": ""    # no existe en GTP
    }])

    # =========================
    # Partners 
    # =========================
    inv_id    = _blank_if_none(head.get("invoice_id"))
    name      = _blank_if_none(head.get("party_invoice_name"))
    addressID = _blank_if_none(head.get("trading_account_id"))
    vendor_id = _blank_if_none(head.get("vendor_id"))

    domain     = "accountID"
    identifier = vendor_id if vendor_id != "" else addressID

    partners = pd.DataFrame([{
        "InvoiceID":  inv_id,
        "partner_id": "P1",
        "role":       "remitTo",
        "addressID":  addressID,
        "name":       name,
        "email":      "",
        "lang":       "",
        "domain":     domain,
        "identifier": identifier,
    }])

    # =========================
    # Items (nombres exactos de tu layout)
    # =========================
    net   = _blank_if_none(head.get("net_invoice_amount"))
    gross = _blank_if_none(head.get("gross_invoice_amount"))
    curr  = _blank_if_none(head.get("invoice_curr"))

    # monto base: neto si existe; si no, gross; si no, 0
    line_subtotal = _num_or_0(net) if net != "" else (_num_or_0(gross) if gross != "" else 0.0)

    product_type = _blank_if_none(head.get("product_type"))
    product_sub  = _blank_if_none(head.get("product_sub_type"))
    default_desc = f"Charges for {product_type}/{product_sub}".strip().strip("/")
    description  = _blank_if_none(head.get("party_invoice_ref_no")) or default_desc or "Charges"

    items = pd.DataFrame([{
        "invoiceid":            inv_id,
        "order_id":             "",
        "invoiceLineNumber":    1,
        "quantity":             1,
        "unitOfMeasure":        "EA",
        "unitPrice":            line_subtotal,
        "unitPrice_currency":   curr,
        "ref_lineNumber":       "1",
        "description":          description,
        "subtotal":             line_subtotal,
        "subtotal_currency":    curr,
        "dist_accounting_id":   "",
        "dist_accounting_name": "",
        "dist_accounting_desc": "",
        "charge_amount":        "",
        "charge_currency":      "",
    }])

    # =========================
    # Taxes (nombres exactos de tu layout)
    # =========================
    tax_amt = _blank_if_none(head.get("tax_amount"))

    # taxable: primero neto; si no, gross - tax; si no se puede, ""
    if net != "":
        taxable = _num_or_0(net)
    elif gross != "" and tax_amt != "":
        taxable = max(_num_or_0(gross) - _num_or_0(tax_amt), 0.0)
    else:
        taxable = ""

    # porcentaje si es calculable
    if isinstance(taxable, (int, float)) and taxable not in ("", 0) and tax_amt != "":
        rate = round((_num_or_0(tax_amt) / taxable) * 100, 4)
    else:
        rate = ""

    # taxPointDate (dd/mm/YYYY)
    tax_point = ""
    inv_date = head.get("invoice_date")
    if inv_date not in (None, ""):
        try:
            tax_point = pd.to_datetime(inv_date).strftime("%d/%m/%Y")
        except Exception:
            tax_point = ""

    taxes = pd.DataFrame([{
        "invoiceid":              inv_id,
        "category":               "vat",
        "percentageRate":         rate,
        "taxableAmount":          taxable if taxable != "" else "",
        "taxableAmount_currency": curr,
        "taxAmount":              _blank_if_none(tax_amt),
        "taxAmount_currency":     curr,
        "description":            "Summary Tax",
        "alternateAmount":        _blank_if_none(tax_amt) if _blank_if_none(tax_amt) != "" else "",
        "xml:lang":               "",
        "alternateCurrency":      curr if curr != "" else "",
        "taxPointDate":           tax_point,
        "currency":               curr,
    }])

    # =========================
    # Summary (nombres exactos de tu layout)
    # =========================
    tax_total = _blank_if_none(tax_amt)
    net_num   = _num_or_0(net)   if net   != "" else None
    gross_num = _num_or_0(gross) if gross != "" else None
    tax_num   = _num_or_0(tax_amt) if tax_amt != "" else None

    # Si no hay net y hay gross/tax, calcúlalo
    if net == "" and (gross_num is not None or tax_num is not None):
        net_num = (_num_or_0(gross) if gross != "" else 0.0) - (_num_or_0(tax_amt) if tax_amt != "" else 0.0)

    subtotal_val = net_num if net_num is not None else ""
    if gross == "":
        gross_calc = (_num_or_0(net) if net != "" else 0.0) + (_num_or_0(tax_amt) if tax_amt != "" else 0.0)
        gross_val = gross_calc if (net != "" or tax_amt != "") else ""
    else:
        gross_val = gross_num

    summary = pd.DataFrame([{
        "InvoiceID":           inv_id,
        "subtotal":            subtotal_val if subtotal_val != "" else "",
        "subtotal_currency":   curr,
        "tax_total":           tax_total if tax_total != "" else "",
        "net_amount":          net_num if net_num is not None else "",
        "net_amount_currency": curr,
        "grossAmount":         gross_val if gross_val is not None else "",
    }])

    # =========================
    # Extrinsics (nombres exactos)
    # =========================
    cid = f"cid:{_blank_if_none(head.get('attachment_id'))}" if _blank_if_none(head.get("attachment_id")) != "" else ""
    extrinsics_rows = [
        {"InvoiceID": inv_id, "name": "invoicePeriod",     "value": _blank_if_none(head.get("invoice_period")),   "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "paymentId",         "value": _blank_if_none(head.get("payment_id")),       "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "productType",       "value": _blank_if_none(head.get("product_type")),     "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "productSubType",    "value": _blank_if_none(head.get("product_sub_type")), "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "businessDate",      "value": _blank_if_none(head.get("business_date")),    "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "recordStatus",      "value": _blank_if_none(head.get("record_status")),    "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "recordActiveInd",   "value": _blank_if_none(head.get("record_active_ind")),"attachment_url": ""},
        # adicionales de tu layout
        {"InvoiceID": inv_id, "name": "buyerVatID",              "value": "", "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "supplierVatID",           "value": "", "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "invoicePDF",              "value": "", "attachment_url": cid},
        {"InvoiceID": inv_id, "name": "IBAN",                    "value": "", "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "Bank Account Number",     "value": "", "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "CompanyCode",             "value": "", "attachment_url": ""},
        {"InvoiceID": inv_id, "name": "invoiceSubmissionMethod", "value": "", "attachment_url": ""},
    ]
    extrinsics = pd.DataFrame(extrinsics_rows)[["InvoiceID","name","value","attachment_url"]]

    return {
        "Envelope":   env,
        "Header":     hdr,
        "Partners":   partners,
        "Items":      items,
        "Taxes":      taxes,
        "Summary":    summary,
        "Extrinsics": extrinsics
    }




def build_cxml_from_snapshot(snapshot: pd.DataFrame, invoice_id):
    sheets = build_sheets_from_snapshot(snapshot, invoice_id)
    return build_cxml_for_invoice(str(invoice_id), sheets)


    





ALIAS_ENV = {
    "payload_id":      ["payloadid"],
    "timestamp":       ["timestamp"],
    "version":         ["version"],
    "signature_version" : ['signatureVersion','signatureversion'],
    # From
    "from_domain":     ["from_credential_domain", "from_domain"],
    "from_identity":   ["from_identity"],
    "from_corr_name":  ["from_correspondent_name"],
    "from_domain2":     ["from_credential_domain2"],
    "from_identity2":   ["from_identity2"],
    "from_domain3":     ["from_credential_domain3"],
    "from_identity3":   ["from_identity3"],

    # To (puede haber varias filas con credential1/2 en tu plantilla; aquí usamos 1..n básicos)
    "to_cred1_domain": ["to_credential1_domain"],
    "to_cred1_identity":["to_credential1_identity"],
    "to_cred2_domain": ["to_credential2_domain"],
    "to_cred2_identity":["to_credential2_identity"],
    # Sender
    "sender_domain":   ["sender_credential_domain","sender_domain"],
    "sender_identity": ["sender_identity"],
    "sender_secret":   ["sender_shared_secret"],
    "user_agent":      ["user_agent"],
    # Request
    "request_id":      ["request_id"],
    "deployment_mode": ["request_deploymentmode","deploymentmode"],
    "preferred_language": ["preferred_language"],
    "street": ["street"],
    "city": ["city"],
    "postalcode": ["postalcode"],
    "country": ["country"],
    "isocountry": ["isocountry"]
}




ALIAS_HDR = {
    "invoice_id":     ["invoiceid","header_invoiceid","invoice_id"],
    "invoice_date":   ["header_invoicedate","invoicedate","invoice_date"],
    "invoice_origin": ["header_invoiceorigin","invoiceorigin"],
    "operation":      ["header_operation","operation"],
    "purpose":        ["header_purpose","purpose"],
    "payment_days":   ["paymentterm_days","payment_days","paymentterm"],
    "comments":       ["comments","comentarios"],
    "isTaxInLine": ['isTaxInLine','is_tax_in_line']
}

# Partners: 1 fila por partner (con PartnerKey opcional)
ALIAS_PART = {
    "partner_key": ["partnerkey","partner_id","partner"],
    "role":        ["role","partner_role"],
    "address_id":  ["addressid","address_id"],
    "name":        ["name"],
    "email":       ["email"],
    "lang":        ["lang"],
# domain	identifier
    "domain": ["domain"],
    "identifier": ["identifier"],

}

# IdReferences: 1 fila por idRef (vinculada a PartnerKey opcional)
ALIAS_IDR = {
    "partner_key": ["partnerkey","partner_id","partner"],
    "domain":      ["domain"],
    "identifier":  ["identifier","id","value"],
}

# OrderInfo (opcional)
ALIAS_OI = {
    "order_id": ["order_id","orderid","po","po_number"],
}

# Items
ALIAS_IT = {
    "line_no":      ["invoicelinenumber","line","line_no","lineno"],
    "quantity":     ["quantity","qty"],
    "uom":          ["unitofmeasure","uom"],
    "unit_price":   ["unitprice","price"],
    "price_curr":   ["unitprice_currency","price_currency","currency"],
    "ref_line":     ["ref_linenumber","ref_line","reflinenumber","line_ref","line_refnumber"],
    "description":  ["description","itemdescription","desc"],
    "subtotal":     ["subtotal","lineamount","linetotal","importe_linea"],
    "subtotal_curr":["subtotal_currency","currency_subtotal","currency"],
    # distribución contable básica
    "dist_acc_id":  ["dist_accounting_id","accounting_id"],
    "dist_acc_name":["dist_accounting_name","accounting_name"],
    "dist_acc_desc":["dist_accounting_desc","accounting_desc"],
}

# Taxes (nivel línea o resumen)
ALIAS_TAX = {
    "level":     ["level"],           # "line" / "summary"
    "line_no":   ["line","line_no","lineno","invoicelinenumber"],
    "category":  ["category"],
    "rate":      ["rate","percentage","percentagerate"],
    "tax_amount":["taxamount","amount"],
    "currency":  ["currency","tax_currency"],
    "alternateAmount": ["alternateamount","alternate_amount","alternate"],
    "alternateCurrency": ["alternatecurrency","alternate_currency","alternate"],
    "description"  :['Description','description'],
    "taxPointDate": ['taxpointdate','tax_point_date'],
    "taxAmount_currency": ['taxamount_currency','tax_amount_currency'],
    "taxableAmount": ['taxableamount','taxable_amount']
}

# Summary
ALIAS_SUM = {
    "subtotal": ["subtotal_amount","subtotal","amount_subtotal"],
    "tax":      ["tax_total","tax","amount_tax"],
    "net":      ["net_amount"],
    "currency": ["net_amount_currency"],
    "gross":    ["grossAmount","gross","amount_gross"]
    # "alternateAmount": ["alternateamount","alternate_amount","alternate"]
}

# Extrinsics
ALIAS_EXT = {
    "name":  ["name","key"],
    "value": ["value"],
}







def _add_text(parent, tag, text: Optional[str], attrib: dict = None):
    if text is None and not attrib:
        return None
    el = ET.SubElement(parent, tag, attrib=attrib or {})
    if text is not None:
        el.text = text
    return el

def _add_money(parent, tag, amount, currency: Optional[str]):
    el = ET.SubElement(parent, tag)
    m_attrib = {}
    if currency: 
        m_attrib["currency"] = str(currency)
    _add_text(el, "Money", str(amount) if amount is not None else "0", m_attrib)
    return el

DOCTYPE = '<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.066/InvoiceDetail.dtd">'

CXML_DTD = '<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.045/InvoiceDetail.dtd">'

def dump_xml(elem, include_doctype=True):
    # serializa
    raw = ET.tostring(elem, encoding="utf-8", xml_declaration=True)
    # pretty print (si falla, seguimos con raw)
    try:
        pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")
    except Exception:
        pretty = raw

    if include_doctype:
        # evita duplicar la declaración XML, ya viene en `pretty`
        # insertamos el DOCTYPE justo después de la 1ª línea
        lines = pretty.splitlines()
        if lines and lines[0].startswith(b'<?xml'):
            output = b'\n'.join([lines[0], CXML_DTD.encode('utf-8')] + lines[1:])
        else:
            output = CXML_DTD.encode('utf-8') + b'\n' + pretty
    else:
        output = pretty

    print(output.decode('utf-8'))         # ▶ lo ves en consola
    return output   


def _filter_by_invoice(df: pd.DataFrame, invoice_id) -> pd.DataFrame:
    import pandas as pd
    if df is None or (isinstance(df, pd.DataFrame) and df.empty):
        return df
    if not isinstance(df, pd.DataFrame):
        # si llegó algo raro, mejor no romper
        return pd.DataFrame()

    col = _find_col(df, ["invoice_id", "invoiceid"])
    if not col:
        # No hay columna: devolvemos sin filtrar (para hojas “globales”)
        return df.reset_index(drop=True)
    return df[df[col] == invoice_id].reset_index(drop=True)


def build_cxml_for_invoice(inv_id, sheets: Dict[str, pd.DataFrame]) -> ET.ElementTree:
    
    inv_id = str(inv_id)
    env = _filter_by_invoice(sheets["Envelope"], int(inv_id) if inv_id.isdigit() else inv_id)
    hdr = _filter_by_invoice(sheets["Header"], int(inv_id) if inv_id.isdigit() else inv_id)
    prt = _filter_by_invoice(sheets["Partners"], int(inv_id) if inv_id.isdigit() else inv_id)
    # idr = _filter_by_invoice(sheets["IdRefs"], inv_id)
    # oin = _filter_by_invoice(sheets["OrderInfo"], int(inv_id) if inv_id.isdigit() else inv_id)
    oin = pd.DataFrame()
    it  = _filter_by_invoice(sheets["Items"], int(inv_id) if inv_id.isdigit() else inv_id)
    tax = _filter_by_invoice(sheets["Taxes"], int(inv_id) if inv_id.isdigit() else inv_id)
    summ= _filter_by_invoice(sheets["Summary"],int(inv_id) if inv_id.isdigit() else inv_id)
    ext = _filter_by_invoice(sheets["Extrinsics"],  int(inv_id) if inv_id.isdigit() else inv_id)

    print(f"Generando cXML para InvoiceID={inv_id} ")


    payloadID = _text_or_none(_first_value(env, ALIAS_ENV["payload_id"], f"auto_{pd.Timestamp.now().timestamp()}"))
    timestamp = _text_or_none(_first_value(env, ALIAS_ENV["timestamp"], pd.Timestamp.now().isoformat()))
    version   = _text_or_none(_first_value(env, ALIAS_ENV["version"], "1.2.045"))

    # cXML Root
 
   # payloadID, timestamp y version se toman del envelope o se autogeneran .



    


    cxml = ET.Element("cXML", attrib=_attrib_if_not_none(
        payloadID=_text_or_none(_first_value(env, ALIAS_ENV["payload_id"], f"auto_{pd.Timestamp.now().timestamp()}")),
        signatureVersion=_text_or_none(_first_value(env, ALIAS_ENV["signature_version"], "1.0")),
        timestamp=_text_or_none(_first_value(env, ALIAS_ENV["timestamp"], pd.Timestamp.now().isoformat())),
        version=_text_or_none(_first_value(env, ALIAS_ENV["version"], "1.2.045")),
    ))

    # Header (From/To/Sender)
    header = ET.SubElement(cxml, "Header")

    # From
    f_dom = _text_or_none(_first_value(env, ALIAS_ENV["from_domain"]))
    f_id  = _text_or_none(_first_value(env, ALIAS_ENV["from_identity"]))
    f_dom2 = _text_or_none(_first_value(env, ALIAS_ENV["from_domain2"]))
    f_id2  = _text_or_none(_first_value(env, ALIAS_ENV["from_identity2"]))
    f_dom3 = _text_or_none(_first_value(env, ALIAS_ENV["from_domain3"]))
    f_id3  = _text_or_none(_first_value(env, ALIAS_ENV["from_identity3"]))
    f_name= _text_or_none(_first_value(env, ALIAS_ENV["from_corr_name"]))
    f_street = _text_or_none(_first_value(env, ALIAS_ENV["street"]))
    f_city = _text_or_none(_first_value(env, ALIAS_ENV["city"]))
    f_postalcode = _text_or_none(_first_value(env, ALIAS_ENV["postalcode"]))
    f_country = _text_or_none(_first_value(env, ALIAS_ENV["country"]))
    f_isocountry = _text_or_none(_first_value(env, ALIAS_ENV["isocountry"]))
    f_language = _text_or_none(_first_value(env, ALIAS_ENV["preferred_language"]))

    if f_dom or f_id or f_name:
        From = ET.SubElement(header, "From")
        if f_dom or f_id:
            cred = ET.SubElement(From, "Credential", attrib={"domain": f_dom or ""})
            _add_text(cred, "Identity", f_id)

            cred = ET.SubElement(From, "Credential", attrib={"domain": f_dom2 or ""})
            _add_text(cred, "Identity", f_id2)
            cred = ET.SubElement(From, "Credential", attrib={"domain": f_dom3 or ""})
            _add_text(cred, "Identity", f_id3)

        if f_name:
            corr = ET.SubElement(From, "Correspondent", attrib=_attrib_if_not_none(preferredLanguage=f_language))
            con  = ET.SubElement(corr, "Contact", attrib=_attrib_if_not_none(role="correspondent"))
            _add_text(con, "Name", f_name, _attrib_if_not_none(**({"xml:lang": f_language} if f_language else {})))


            
            if f_street or f_city or f_postalcode or f_country or f_isocountry:
                PostalAddress = ET.SubElement(con, "PostalAddress")
                if f_street:
                    _add_text(PostalAddress, "Street", f_street)
                if f_city:
                    _add_text(PostalAddress, "City", f_city)
                if f_postalcode:
                    _add_text(PostalAddress, "PostalCode", f_postalcode)
                if f_country or f_isocountry:
                    country_attrib = {}
                    if f_isocountry:
                        country_attrib["isoCountryCode"] = f_isocountry
                    _add_text(PostalAddress, "Country", f_country, country_attrib)

    # To (básico 1 y 2 si existen)
    to_dom1 = _text_or_none(_first_value(env, ALIAS_ENV["to_cred1_domain"]))
    to_id1  = _text_or_none(_first_value(env, ALIAS_ENV["to_cred1_identity"]))
    to_dom2 = _text_or_none(_first_value(env, ALIAS_ENV["to_cred2_domain"]))
    to_id2  = _text_or_none(_first_value(env, ALIAS_ENV["to_cred2_identity"]))

    if to_dom1 or to_dom2:
        To = ET.SubElement(header, "To")
        if to_dom1:
            cred = ET.SubElement(To, "Credential", attrib={"domain": to_dom1})
            _add_text(cred, "Identity", to_id1)
        if to_dom2:
            cred = ET.SubElement(To, "Credential", attrib={"domain": to_dom2})
            _add_text(cred, "Identity", to_id2)

    # Sender
    s_dom = _text_or_none(_first_value(env, ALIAS_ENV["sender_domain"]))
    s_id  = _text_or_none(_first_value(env, ALIAS_ENV["sender_identity"]))
    s_sec = _text_or_none(_first_value(env, ALIAS_ENV["sender_secret"]))
    ua    = _text_or_none(_first_value(env, ALIAS_ENV["user_agent"], "Notebook cXML Builder"))

    if s_dom or s_id or s_sec or ua:
        Sender = ET.SubElement(header, "Sender")
        if s_dom or s_id or s_sec:
            cred = ET.SubElement(Sender, "Credential", attrib={"domain": s_dom or ""})
            _add_text(cred, "Identity", s_id)
            if s_sec:
                _add_text(cred, "SharedSecret", s_sec)
        _add_text(Sender, "UserAgent", ua)

    # Request
    request_id = _text_or_none(_first_value(env, ALIAS_ENV["request_id"], "cXMLData"))
    dep_mode   = _text_or_none(_first_value(env, ALIAS_ENV["deployment_mode"], "test"))
    Request = ET.SubElement(cxml, "Request", attrib={"Id": request_id, "deploymentMode": dep_mode})

    inv_req = ET.SubElement(Request, "InvoiceDetailRequest")

    # ---- Header de la factura
    inv_date_raw =  _first_value(hdr, ALIAS_HDR["invoice_date"], pd.Timestamp.today())
    inv_date     = _iso_dt(inv_date_raw, pd.Timestamp.today().isoformat())
    inv_id_text  = _text_or_none(_first_value(hdr, ALIAS_HDR["invoice_id"], inv_id))
    inv_origin   = _text_or_none(_first_value(hdr, ALIAS_HDR["invoice_origin"], "supplier"))
    operation    = _text_or_none(_first_value(hdr, ALIAS_HDR["operation"], "new"))
    purpose      = _text_or_none(_first_value(hdr, ALIAS_HDR["purpose"], "standard"))

    hdr_el = ET.SubElement(inv_req, "InvoiceDetailRequestHeader", attrib={
        "invoiceDate": inv_date,
        "invoiceID":   inv_id_text or str(inv_id),
        "invoiceOrigin": inv_origin or "supplier",
        "operation":   operation or "new",
        "purpose":     purpose or "standard",
    })


    # Indicadores de línea (opcionales; aquí solo ejemplo de tax inline si hay impuestos por línea)
    has_line_tax = False
    if not tax.empty:
        lvl_col = _find_col(tax, ALIAS_TAX["level"])
        if lvl_col is not None and "line" in set(tax[lvl_col].astype(str).str.lower()):
            has_line_tax = True
    ET.SubElement(hdr_el, "InvoiceDetailHeaderIndicator")
    ET.SubElement(hdr_el, "InvoiceDetailLineIndicator",
              attrib={"isTaxInLine": str(_first_value(hdr, ALIAS_HDR['isTaxInLine'], "false")).lower()})


    # PaymentTerm + Comments
    # pay_days = _text_or_none(_first_value(hdr, ALIAS_HDR["payment_days"]))
    # if pay_days:
    #     ET.SubElement(hdr_el, "PaymentTerm", attrib={"payInNumberOfDays": str(pay_days)})
    comm = _text_or_none(_first_value(hdr, ALIAS_HDR["comments"]))


    # Partners
    if _nonempty_df(prt):
        role_col = _find_col(prt, ALIAS_PART["role"])
        addr_col = _find_col(prt, ALIAS_PART["address_id"])
        name_col = _find_col(prt, ALIAS_PART["name"])
        email_col= _find_col(prt, ALIAS_PART["email"])
        lang = _find_col(prt, ALIAS_PART["lang"])
        domain = _find_col(prt,ALIAS_PART['domain'])
        identifier = _find_col(prt,ALIAS_PART['identifier'])
          # para vincular IdRefs

        for _, prow in prt.iterrows():
            print(prow)
            role = str(prow.get(role_col, "")) if role_col else ""

            inv_partner = ET.SubElement(hdr_el, "InvoicePartner")
            role = str(prow.get(role_col, "")) if role_col else ""
            addr = str(prow.get(addr_col)) if addr_col !="" and addr_col!='nan' and addr_col is not None and addr_col is not np.nan else None
            lang = str(prow.get(lang,""))
                

            safe_str = lambda x: "" if (x is None or pd.isna(x)) else str(x)

            dom_col = safe_str(prow.get(domain)) if domain else ""
            ide     = safe_str(prow.get(identifier)) if identifier else ""





            contact = ET.SubElement(inv_partner, "Contact",
                                    attrib=  ({"addressID": addr} if _text_or_none(addr) and addr else {}) | {"role": role} )
            _add_text(contact, "Name", _text_or_none(prow.get(name_col)) , {"xml:lang": lang if _text_or_none(lang) and lang else '' })
            
            if email_col and _text_or_none(prow.get(email_col)):
                ET.SubElement(contact, "Email").text = str(prow[email_col])




            if dom_col or identifier:
                ET.SubElement(contact, "IdReference",
                            attrib={"domain": dom_col if not dom_col is None else "", "identifier": ide if not ide is None else "" })


    if comm:
        _add_text(hdr_el, "Comments", comm)

    # Extrinsics (en header)
    if not ext.empty:
        ncol = _find_col(ext, ALIAS_EXT["name"])
        # attachment_ulkr
        vcol = _find_col(ext, ALIAS_EXT["value"])
        for _, ex in ext.iterrows():
            # print()
            nm = _text_or_none(ex.get(ncol)) if ncol else None
            val= _text_or_none(ex.get(vcol)) if vcol else None
            if nm:
                ex_el = ET.SubElement(hdr_el, "Extrinsic", attrib={"name": nm})
                if nm == "invoicePDF":
                    print("Adding invoicePDF attachment")
                    # if val:
                    Attachment = ET.SubElement(ex_el, "Attachment")
                    url = ET.SubElement(Attachment, "URL").text = _text_or_none(ex.get('attachment_url')) if 'attachment_url' else None
                        # _add_text(ET.SubElement(ex_el, "Attachment"), "URL", val)   
                        # ex_el.text = val
                if val:
                    ex_el.text = val

    # ---- Order + Items
    order_el = ET.SubElement(inv_req, "InvoiceDetailOrder")
    # OrderInfo (opcional)
    if not oin.empty:
        oid_col = _find_col(oin, ALIAS_OI["order_id"])
        # if oid_col:

    oi = ET.SubElement(order_el, "InvoiceDetailOrderInfo")
    ET.SubElement(oi, "OrderIDInfo", attrib={"orderID": str(_first_value(oin, ALIAS_OI["order_id"], ""))})

    # Items


    if not it.empty:
        # columnas
        c_line   = _find_col(it, ALIAS_IT["line_no"])
        c_qty    = _find_col(it, ALIAS_IT["quantity"])
        c_uom    = _find_col(it, ALIAS_IT["uom"])
        c_price  = _find_col(it, ALIAS_IT["unit_price"])
        c_pcur   = _find_col(it, ALIAS_IT["price_curr"])
        c_ref    = _find_col(it, ALIAS_IT["ref_line"])
        c_desc   = _find_col(it, ALIAS_IT["description"])
        c_sub    = _find_col(it, ALIAS_IT["subtotal"])
        c_scur   = _find_col(it, ALIAS_IT["subtotal_curr"])
        c_acc_id = _find_col(it, ALIAS_IT["dist_acc_id"])
        c_acc_nm = _find_col(it, ALIAS_IT["dist_acc_name"])
        c_acc_ds = _find_col(it, ALIAS_IT["dist_acc_desc"])

        for _, row in it.iterrows():
            line_no = str(row.get(c_line)) if c_line else None
            qty     = row.get(c_qty, 1) if c_qty else 1
            uom     = _text_or_none(row.get(c_uom)) if c_uom else "EA"
            price   = row.get(c_price, 0) if c_price else 0
            pcur    = _text_or_none(row.get(c_pcur)) if c_pcur else None
            ref_ln  = str(row.get(c_ref)) if c_ref else None
            desc    = _text_or_none(row.get(c_desc)) if c_desc else None
            sub_val = row.get(c_sub, 0) if c_sub else 0
            scur    = _text_or_none(row.get(c_scur)) if c_scur else pcur

            item = ET.SubElement(order_el, "InvoiceDetailItem",
                                 attrib={"invoiceLineNumber": line_no or str(len(order_el)+1),
                                         "quantity": str(qty)})
            _add_text(item, "UnitOfMeasure", uom)

            unit_price = ET.SubElement(item, "UnitPrice")
            _add_text(unit_price, "Money", str(price), {"currency": pcur or scur or ""})

            if ref_ln or desc:
                ref = ET.SubElement(item, "InvoiceDetailItemReference",
                                    attrib={"lineNumber": ref_ln or (line_no or "1")})
                _add_text(ref, "Description", desc, {"xml:lang": "en"})

            sub_el = ET.SubElement(item, "SubtotalAmount")
            _add_text(sub_el, "Money", str(sub_val), {"currency": scur or pcur or ""})


    # ---- Taxes
    if not tax.empty:
        # lvl = _find_col(tax, ALIAS_TAX["level"])
        # ln  = _find_col(tax, ALIAS_TAX["line_no"])
        # alter = _find_col(tax, ALIAS_TAX["alternateAmount"])
        cat = _find_col(tax, ALIAS_TAX["category"])
        rte = _find_col(tax, ALIAS_TAX["rate"])
        tam = _find_col(tax, ALIAS_TAX["tax_amount"])
        tcu = _find_col(tax, ALIAS_TAX["currency"])
        

        # impuestos summary (secciones separadas del summary real)
        # aquí los insertamos dentro de InvoiceDetailSummary como <Tax> si level == summary
        pass  # los añadimos en el bloque de Summary para centralizar la moneda



    # montos
    sub_total = _first_value(summ, ALIAS_SUM["subtotal"], 0) or 0
    tax_total = _first_value(summ, ALIAS_SUM["subtotal"], 0) or 0
    net_total = _first_value(summ, ALIAS_SUM["net"], (sub_total or 0) + (tax_total or 0)) or 0

    # _add_money(summary, "SubtotalAmount", sub_total, sum_cur)
    # Tax summary (si viene en hoja Taxes con nivel summary, añadimos detalle)
    if not tax.empty:
        tax_block = ET.SubElement(item, "Tax")
        # monto agregado (si se proporcionó explícito en Summary, usamos ese)
        _add_text(tax_block, "Money",  str( _first_value(tax, ALIAS_TAX["alternateAmount"])),
                   {"alternateAmount": str( _first_value(tax, ALIAS_TAX["alternateAmount"]))  ,
                                                       "alternateCurrency":  str( _first_value(tax, ALIAS_TAX["alternateCurrency"]) ),
                                                        "currency": str(_first_value(tax,ALIAS_TAX['currency'],'')) })
        # Description
        _add_text(tax_block, "Description", str(_first_value(tax, ALIAS_TAX["description"])), {"xml:lang": "en"})
        # Detalles
        for _, r in tax.iterrows():
            cat = _text_or_none(r.get(_find_col(tax, ALIAS_TAX["category"])))
            rate= r.get(_find_col(tax, ALIAS_TAX["rate"]))
            tcur= _text_or_none(r.get(_find_col(tax, ALIAS_TAX["currency"]))) 
            # cXML típico incluye TaxDetail con TaxableAmount/TaxAmount; aquí solo mapeamos TaxAmount si está
            t_amt = r.get(_find_col(tax, ALIAS_TAX["taxableAmount"]), 0)
            tdet = ET.SubElement(tax_block, "TaxDetail", attrib={"category": cat or "SalesTax",
                                                                    "percentageRate": str(rate or 0),"taxPointDate": str(_iso_dt(r.get(_find_col(tax, ALIAS_TAX["taxPointDate"])), inv_date))})
            # # opcionalmente podrías incluir TaxableAmount si lo tienes en el Excel
            TaxableAmount = ET.SubElement(tdet, "TaxableAmount")
            _add_text(TaxableAmount, "Money", str(t_amt), {"currency": str(_first_value(tax,ALIAS_TAX["taxAmount_currency"]))})

            
            t_amt_el = ET.SubElement(tdet, "TaxAmount")
            _add_text(t_amt_el, "Money", str(_first_value(tax, ALIAS_TAX["tax_amount"])),
                       {"alternateAmount": str(_first_value(tax, ALIAS_TAX["alternateAmount"])),
                        "alternateCurrency": str(_first_value(tax, ALIAS_TAX["alternateCurrency"])),
                        "currency": _first_value(tax, ALIAS_TAX["taxAmount_currency"]) })

        _add_text(tdet, "Description", str(_first_value(tax, ALIAS_TAX["description"])), {"xml:lang": "en"})

  
    

        net_amount = ET.SubElement(item,'NetAmount')
        _add_text(net_amount, "Money", str(_first_value(summ,ALIAS_SUM["net"])), {"currency": tcur})

    # ---- Summary
    summary = ET.SubElement(inv_req, "InvoiceDetailSummary")
    sum_cur = (_first_value(summ, ALIAS_SUM["currency"]))

    sub_el = ET.SubElement(summary, "SubtotalAmount")
    _add_text(sub_el, "Money", str(_first_value(summ,ALIAS_SUM['subtotal'])), {"currency": sum_cur})

    tax_el = ET.SubElement(summary, "Tax")
    _add_text(tax_el, "Money", str(_first_value(summ,ALIAS_SUM['tax'])), {"currency": sum_cur})
    _add_text(tax_el, "Description", str(_first_value(tax, ALIAS_TAX["description"])), {"xml:lang": "en"})

    TaxDetail = ET.SubElement(tax_el, "TaxDetail", attrib={"category": str(_first_value(tax, ALIAS_TAX["category"], "SalesTax")),
                                                            "percentageRate": str(_first_value(tax, ALIAS_TAX["rate"], 0))})
    TaxableAmount = ET.SubElement(TaxDetail, "TaxableAmount")
    _add_text(TaxableAmount, "Money", str(_first_value(tax, ALIAS_TAX["taxableAmount"], 0)), {"currency": str(_first_value(tax, ALIAS_TAX["taxAmount_currency"]))})
    TaxAmount = ET.SubElement(TaxDetail, "TaxAmount")
    _add_text(TaxAmount, "Money", str(_first_value(tax, ALIAS_TAX["tax_amount"], 0)),
               {
                "currency": str(_first_value(tax, ALIAS_TAX["taxAmount_currency"]))
               })
    _add_text(TaxDetail, "Description", str(_first_value(tax, ALIAS_TAX["description"])), {"xml:lang": "en"})


    gross_el = ET.SubElement(summary, "GrossAmount")
    _add_text(gross_el, "Money", str(_first_value(summ,ALIAS_SUM['gross'])), {"currency": sum_cur})
    net_el = ET.SubElement(summary, "NetAmount")
    _add_text(net_el, "Money", str(_first_value(summ,ALIAS_SUM['gross'])), {"currency": sum_cur})    
    


    ds_signature = ET.SubElement(cxml,'ds:Signature', attrib={'Id':'cxMLData','xmlns:xades':'http://uri.etsi.org/01903/v1.3.2#','xmlns:ds':'http://www.w3.org/2000/09/xmldsig#'})
    # ET.indent(cxml, space="  ")


    # tree = ET.ElementTree(cxml)
    # tree.write("output.xml", encoding="utf-8", xml_declaration=True)
    ds_signature_info = ET.SubElement(ds_signature,'ds:SignedInfo')
    ds_canonicalization_text = {'Algorithm':'http://www.w3.org/TR/2001/REC-xml-c14n-20010315'}
    ds_canonicalization = ET.SubElement(ds_signature_info,'ds:CanonicalizationMethod', attrib=ds_canonicalization_text)

    ds_signature_method_text = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
    ds_signature_method = ET.SubElement(ds_signature_info,'ds:SignatureMethod', attrib={'Algorithm':ds_signature_method_text})



    ds_reference = ET.SubElement(ds_signature_info,'ds:Reference', attrib={'URI':'#cXMLSignedInfo'})
    ds_digest_method = ET.SubElement(ds_reference,'ds:DigestMethod', attrib={'Algorithm':'http://www.w3.org/2001/04/xmlenc#sha256'})
    
    DigestValue_text = "0opEEXCsU2BrSLBj+3RXOrYxwmyA/jmMudS4ug1MeCk="
    ds_digest_value = ET.SubElement(ds_reference,'ds:DigestValue').text = DigestValue_text

    ds_reference2 = ET.SubElement(ds_signature_info,'ds:Reference', attrib={'URI':'#cXMLData'})
    ds_digest_method2_text = 'http://www.w3.org/2001/04/xmlenc#sha256'
    ds_digest_method2 = ET.SubElement(ds_reference2,'ds:DigestMethod', attrib={'Algorithm': ds_digest_method2_text})
    DigestValue2_text = "+G52GpooH0fhOqf65yXngrAva31NfZVTaE33z/1DJJU="
    ds_digest_value2 = ET.SubElement(ds_reference2,'ds:DigestValue').text = DigestValue2_text


    ds_reference3_text =   '#XAdESSignedProps'
    ds_reference3 = ET.SubElement(ds_signature_info,'ds:Reference', attrib={'URI': ds_reference3_text})
    ds_digest_method3_text = 'http://www.w3.org/2001/04/xmlenc#sha256'
    ds_digest_method3 = ET.SubElement(ds_reference3,'ds:DigestMethod', attrib={'Algorithm':ds_digest_method3_text})
    ds_digest_value3_text = "rsnTyo1J6jBaGI4aE90srfSGdcUz/5hXe/C6YmQMQww="
    ds_digest_value3 = ET.SubElement(ds_reference3,'ds:DigestValue').text = ds_digest_value3_text




    SignatureValue = ET.SubElement(ds_signature,'ds:SignatureValue')
    SignatureValue.text= "/0yS3G2sFfwXEPyTXWihmHkSSMWdzaYXQexqmWCJgSHEp+hOPAarFaz3se9k0Nf60OPLQxre2RGWOktzfDFRfs8V+Om3jVEmICRdrT8PdFZrm8JiX+il3+k67Epx/aBOIU4u5VH4KB3hOn2hZxq/ihIy2HEWgmAcCa6GSEphw=="
    KeyInfo = ET.SubElement(ds_signature,'ds:KeyInfo', attrib={'Id':'KeyInfoId'})

    X509Data = ET.SubElement(KeyInfo,'ds:X509Data')
    X509Certificate = ET.SubElement(X509Data,'ds:X509Certificate')
    X509Certificate.text= "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"
    
    ds_signature_inf = ET.SubElement(ds_signature,'ds:Object')

    cXMLSignedInfo = ET.SubElement(ds_signature_inf,'cXMLSignedInfo', attrib={'Id':'cXMLSignedInfo', 'payloadID': payloadID,
                                                                    'signatureVersion':'1.0'})



    ds_signature_info2 = ET.SubElement(ds_signature,'ds:Object')
    Extrinsic1 = ET.SubElement(ds_signature_info2,'Extrinsic', attrib={'name':'ValidationPolicyId'})
    Identifier = ET.SubElement(Extrinsic1,'xades:Identifier', attrib={'Qualifier':'OIDAsURN'})
    Identifier.text= "urn:oid:1.2.752.76.1.199.699.1.10"


    ds_signature_info3 = ET.SubElement(ds_signature,'ds:Object')
    Extrinsic2 = ET.SubElement(ds_signature_info3,'Extrinsic', attrib={'name':'ValidationPolicyQualifier'})
    SPURI = ET.SubElement(Extrinsic2,'xades:SPURI')
    SPURI.text= "https://sovos.com/policies/?from=GB&amp;to=GB&amp;authCertThumbprint=33E10601F98830DCDA1B7CB131DE01F7B57ADFE8"
    


    NS_DS    = "http://www.w3.org/2000/09/xmldsig#"
    NS_XADES = "http://uri.etsi.org/01903/v1.3.2#"
    ET.register_namespace("ds", NS_DS)
    ET.register_namespace("xades", NS_XADES)
    Object = ET.SubElement(ds_signature,'ds:Object')


    # ---- BLOBS de ejemplo (pon aquí los que ya tienes) ----
    SIGNED_TIME = "2025-06-24T12:24:37Z"

    CERT_DIGEST_ALG = "http://www.w3.org/2001/04/xmlenc#sha256"
    CERT_DIGEST_VAL = "P3KOuiUp9NUlj5MZzBDtjStxAPXt6s0hwhRZBaBGaWk="
    ISSUER_NAME     = ("CN=QuoVadis EU Issuing Certification Authority G4, "
                    "O=QuoVadis Trustlink B.V., OID.2.5.4.97=NTRNL-30237459, C=NL")
    ISSUER_SERIAL   = "398850118330166149807158326000912326027321197577"

    POLICY_ID_OIDAS = "urn:oid:1.2.752.76.1.199.699.1.9"
    POLICY_HASH_ALG = "http://www.w3.org/2000/09/xmldsig#sha1"
    POLICY_HASH_VAL = "ZYs1iyR1AcD5VipwXIw2FR+pt2Q="
    POLICY_SPURI    = ("https://sovos.com/wp-content/uploads/2019/10/"
                    "TWOD-Signature-Policy.pdf?from=GB&to=GB&authCertThumbprint=33E10601F98830DCDA1B7CB131DE01F7B57ADFE8")

    # Timestamps / Certs / CRLs / OCSP (usa los largos que pegaste)
    ENCAPSULATED_SIGNATURE_TIMESTAMP = "..."  # <xades:SignatureTimeStamp><xades:EncapsulatedTimeStamp>...</>
    ENCAPSULATED_ARCHIVE_TIMESTAMP   = "..."  # el muy largo que ya pusiste
    X509_CERTS = [
        "MIIGwzCCBKugAwIBAgIUEn+L...",   # 1er EncapsulatedX509Certificate
        "MIIGjzCCBHegAwIBAgIUCthv...",   # 2º
        "MIIFYDCCA0igAwIBAgIUeFhf...",    # 3º
    ]


    # Si ya tienes creado 'cXML' y tu <ds:Signature> (no mostrado), añade QualifyingProperties:
    ds_objects = ET.SubElement(
        Object, 'xades:QualifyingProperties',
        attrib={
            "Id": "QualifyingPropertiesId",
            "Target": "#cXMLSignature",
            "xmlns:xades": NS_XADES
        }
    )

    # ---------- SignedProperties (FALTABA) ----------
    signed_properties = ET.SubElement(ds_objects, 'xades:SignedProperties', attrib={"Id": "XAdESSignedProps"})
    ssp = ET.SubElement(signed_properties, 'xades:SignedSignatureProperties')

    ET.SubElement(ssp, 'xades:SigningTime').text = SIGNED_TIME

    # SigningCertificate
    sc = ET.SubElement(ssp, 'xades:SigningCertificate')
    cert = ET.SubElement(sc, 'xades:Cert')
    cd  = ET.SubElement(cert, 'xades:CertDigest')
    ET.SubElement(cd, 'ds:DigestMethod', attrib={"Algorithm": CERT_DIGEST_ALG}).text=""
    ET.SubElement(cd, 'ds:DigestValue').text = CERT_DIGEST_VAL
    isr = ET.SubElement(cert, 'xades:IssuerSerial')
    ET.SubElement(isr, 'ds:X509IssuerName').text   = ISSUER_NAME
    ET.SubElement(isr, 'ds:X509SerialNumber').text = ISSUER_SERIAL

    # SignaturePolicyIdentifier
    spi  = ET.SubElement(ssp, 'xades:SignaturePolicyIdentifier')
    spid = ET.SubElement(spi, 'xades:SignaturePolicyId')
    spid_id = ET.SubElement(spid, 'xades:SigPolicyId')
    ET.SubElement(spid_id, 'xades:Identifier', attrib={"Qualifier": "OIDAsURN"}).text = POLICY_ID_OIDAS
    sph = ET.SubElement(spid, 'xades:SigPolicyHash')
    ET.SubElement(sph, 'ds:DigestMethod', attrib={"Algorithm": POLICY_HASH_ALG})
    ET.SubElement(sph, 'ds:DigestValue').text = POLICY_HASH_VAL
    spq = ET.SubElement(spid, 'xades:SigPolicyQualifiers')
    ET.SubElement(ET.SubElement(spq, 'xades:SigPolicyQualifier'), 'xades:SPURI').text = POLICY_SPURI

    # ---------- UnsignedProperties (lo tuyo + faltantes) ----------
    unsigned_properties = ET.SubElement(ds_objects, 'xades:UnsignedProperties')
    usp = ET.SubElement(unsigned_properties, 'xades:UnsignedSignatureProperties')

    # SignatureTimeStamp (FALTABA)
    sig_ts = ET.SubElement(usp, 'xades:SignatureTimeStamp')
    ET.SubElement(sig_ts, 'xades:EncapsulatedTimeStamp').text = ENCAPSULATED_SIGNATURE_TIMESTAMP

    # CertificateValues (FALTABA)
    cert_values = ET.SubElement(usp, 'xades:CertificateValues')
    for blob in X509_CERTS:
        ET.SubElement(cert_values, 'xades:EncapsulatedX509Certificate').text = blob

    # RevocationValues (YA TENÍAS)
    revocation_values = ET.SubElement(usp, 'xades:RevocationValues')
    crl_values = ET.SubElement(revocation_values, 'xades:CRLValues')
    ET.SubElement(crl_values, 'xades:EncapsulatedCRLValue').text = "..."  # tu gran CRL

    ocsp_values = ET.SubElement(revocation_values, 'xades:OCSPValues')
    ET.SubElement(ocsp_values, 'xades:EncapsulatedOCSPValue').text = "..."  # tu OCSP

    # ArchiveTimeStamp (YA TENÍAS)
    arch_ts = ET.SubElement(usp, 'xades:ArchiveTimeStamp')
    ET.SubElement(arch_ts, 'xades:EncapsulatedTimeStamp').text = ENCAPSULATED_ARCHIVE_TIMESTAMP

    # dump_xml(cxml, include_doctype=True)       # 👈 imprímelo aquí

    return ET.ElementTree(cxml)

from xml.etree.ElementTree import tostring

DOCTYPE = '<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.066/InvoiceDetail.dtd">'

def generate_all_cxml(sheets: Dict[str, pd.DataFrame], output_prefix="./salida/invoice_"):
    hdr = sheets["Header"]
    print(hdr)
    inv_col = _find_col(hdr, ['invoice_id',"invoiceid", "InvoiceID",'invoice_id'])
    if not inv_col:
        raise ValueError("La hoja 'Header' debe contener 'InvoiceID'")

    invoice_ids = hdr[inv_col].dropna().astype(str).unique().tolist()

    for inv_id in invoice_ids:
        tree_or_root = build_cxml_for_invoice(inv_id, sheets)
        # Soporta si devuelves ElementTree o directamente Element
        root = tree_or_root.getroot() if hasattr(tree_or_root, "getroot") else tree_or_root
        print(inv_id)
        out = f"{output_prefix}{inv_id}.xml"
        xml_body = tostring(root, encoding="utf-8")

        with open(out, "wb") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write((DOCTYPE + "\n").encode("utf-8"))
            f.write(xml_body)
        print(f"✅ XML generado: {out}")




def send_xml_file(xml_path: str, url: str = "http://localhost:8000/cxml"):
    p = Path(xml_path)
    if not p.is_file():
        raise FileNotFoundError(f"No existe el archivo: {p}")

    headers = {
        "Accept": "*/*",
        "User-Agent": "Python requests",
        "Content-Type": "application/xml",
    }

    # Envía el contenido del archivo sin modificar
    with p.open("rb") as f:
        resp = requests.post(url, data=f, headers=headers, timeout=60)

    print(f"HTTP {resp.status_code}")
    print(resp.text)
    return resp



snapshot = load_data(
    table="good_to_pay",
    where="COALESCE(record_active_ind,'Y')='Y'"
)



# EXCEL_PATH = "C:/Users/crist/Downloads/cxml_template_extended.xlsx"  # <-- cambia a tu ruta real

# def _load_sheet(xls: pd.ExcelFile, name: str) -> pd.DataFrame:
#     try:
#         df = pd.read_excel(xls, sheet_name=name)
#         return _normalize_cols(df)
#     except Exception:
#         return pd.DataFrame()
# def load_workbook(path: str) -> Dict[str, pd.DataFrame]:
#     xls = pd.ExcelFile(path)
#     sheets = {
#         "Envelope":   _load_sheet(xls, "envelope"),
#         "Header":     _load_sheet(xls, "header"),
#         "Partners":   _load_sheet(xls, "partners"),
#         "IdRefs":     _load_sheet(xls, "idreferences"),
#         "OrderInfo":  _load_sheet(xls, "orderinfo"),
#         "Items":      _load_sheet(xls, "items"),
#         "Taxes":      _load_sheet(xls, "taxes"),
#         "Summary":    _load_sheet(xls, "summary"),
#         "Extrinsics": _load_sheet(xls, "extrinsics"),
#     }
#     # Validación: todas con InvoiceID
#     for nm, df in sheets.items():
#         if not df.empty and "invoiceid" not in [c.lower() for c in df.columns]:
#             raise ValueError(f"La hoja '{nm}' no contiene la columna 'InvoiceID'.")
#     return sheets

# sheets = load_workbook(EXCEL_PATH)
# generate_all_cxml(sheets, output_prefix="./salida/")

invoice_ids = sorted(snapshot["invoice_id"].dropna().unique().tolist())
sheets =None
for invoice in invoice_ids:
    sheets = build_sheets_from_snapshot(snapshot=snapshot,invoice_id=invoice)


    generate_all_cxml(sheets, output_prefix="./salida/")
    response = send_xml_file(f"./salida/{invoice}.xml")    
    if response.status_code  in [406]:
        print('needs to update the goodtopay table')




