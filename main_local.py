

from xml.dom import minidom
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
# display({k: v.head(3) for k, v in sheets.items()})

# %% [markdown]
# ==== Aliases de columnas por hoja ====
# Ajusta / amplía libremente

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
    "isTaxInLine": ['isTaxInLine']
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

# %% [markdown]
# ==== Generación de cXML por factura ====

# from attr import attrib
import numpy as np


def _filter_by_invoice(df: pd.DataFrame, invoice_id) -> pd.DataFrame:
    print(invoice_id)
    # print(df)
    if df is None or df.empty:
        return df
    col = _find_col(df, ["invoiceid"])
    if not col:
        return pd.DataFrame()
    return df[df[col] == invoice_id].reset_index(drop=True)

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
def build_cxml_for_invoice(inv_id, sheets: Dict[str, pd.DataFrame]) -> ET.ElementTree:
    
    inv_id = str(inv_id)
    env = _filter_by_invoice(sheets["Envelope"], int(inv_id) if inv_id.isdigit() else inv_id)
    hdr = _filter_by_invoice(sheets["Header"], int(inv_id) if inv_id.isdigit() else inv_id)
    prt = _filter_by_invoice(sheets["Partners"], int(inv_id) if inv_id.isdigit() else inv_id)
    idr = _filter_by_invoice(sheets["IdRefs"], inv_id)
    oin = _filter_by_invoice(sheets["OrderInfo"], int(inv_id) if inv_id.isdigit() else inv_id)
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



    


    cxml = ET.Element("cXML", attrib={
        "payloadID": payloadID,
        "signatureVersion": _text_or_none(_first_value(env, ALIAS_ENV["signature_version"], "1.0")),

        "timestamp": timestamp,
        "version":   version,
    })

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
            corr = ET.SubElement(From, "Correspondent", attrib={"preferredLanguage": f_language})
            con  = ET.SubElement(corr, "Contact", attrib={"role": "correspondent"})
            _add_text(con, "Name", f_name, {"xml:lang": f_language})

            
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
    inv_date_raw = _first_value(hdr, ALIAS_HDR["invoice_date"], pd.Timestamp.today())
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
                  attrib={"isTaxInLine": _first_value(hdr,ALIAS_HDR['isTaxInLine'])})

    # PaymentTerm + Comments
    # pay_days = _text_or_none(_first_value(hdr, ALIAS_HDR["payment_days"]))
    # if pay_days:
    #     ET.SubElement(hdr_el, "PaymentTerm", attrib={"payInNumberOfDays": str(pay_days)})
    comm = _text_or_none(_first_value(hdr, ALIAS_HDR["comments"]))


    # Partners
    if not prt.empty:
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
            _add_text(contact, "Name", _text_or_none(prow.get(name_col)) , {"xml:lang": lang if _text_or_none(lang) and lang else {} })
            
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

            # Distribution (si hay algo de contabilidad)
            # if c_acc_id or c_acc_nm or c_acc_ds:
            #     dist = ET.SubElement(item, "Distribution")
            #     acc  = ET.SubElement(dist, "Accounting", attrib={"name": "DistributionCharge"})
            #     seg  = ET.SubElement(acc, "AccountingSegment", attrib={"id": str(row.get(c_acc_id, ""))})
            #     _add_text(seg, "Name", _text_or_none(row.get(c_acc_nm)) or "GeneralLedger", {"xml:lang": "en"})
            #     _add_text(seg, "Description", _text_or_none(row.get(c_acc_ds)) or "ID", {"xml:lang": "en"})

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

            # <TaxAmount>
            #     <Money alternateAmount="1485.00" alternateCurrency="GBP"
            #         currency="GBP">1485.00</Money>
            # </TaxAmount>
            
            t_amt_el = ET.SubElement(tdet, "TaxAmount")
            _add_text(t_amt_el, "Money", str(_first_value(tax, ALIAS_TAX["tax_amount"])),
                       {"alternateAmount": str(_first_value(tax, ALIAS_TAX["alternateAmount"])),
                        "alternateCurrency": str(_first_value(tax, ALIAS_TAX["alternateCurrency"])),
                        "currency": _first_value(tax, ALIAS_TAX["taxAmount_currency"]) })

        _add_text(tdet, "Description", str(_first_value(tax, ALIAS_TAX["description"])), {"xml:lang": "en"})


                    # <NetAmount>
                    #     <Money currency="GBP">8487.91</Money>
                    # </NetAmount>
    # net_el = ET.SubElement(summary, "NetAmount")
    # _add_text(net_el, "Money", str(_first_value(summ,ALIAS_SUM['gross'])), {"currency": sum_cur})    
    

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


        # <ds:SignatureValue>
        #    
        # <ds:KeyInfo Id="KeyInfoId">
        #     <ds:X509Data>
        #         <ds:X509Certificate>
        #             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</ds:X509Certificate>
        #     </ds:X509Data>
        # </ds:KeyInfo>
        # <ds:Object>
        #     <cXMLSignedInfo Id="cXMLSignedInfo" payloadID="UBSRSO20250624T122427658"
        #         signatureVersion="1.0"></cXMLSignedInfo>
        # </ds:Object>

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
    
        #     <ds:Object>
        #     <xades:QualifyingProperties Id="QualifyingPropertiesId" Target="#cXMLSignature"
        #         xmlns:xades="http://uri.etsi.org/01903/v1.3.2#">
        #         <xades:SignedProperties Id="XAdESSignedProps">
        #             <xades:SignedSignatureProperties>
        #                 <xades:SigningTime>2025-06-24T12:24:37Z</xades:SigningTime>
        #                 <xades:SigningCertificate>
        #                     <xades:Cert>
        #                         <xades:CertDigest>
        #                             <ds:DigestMethod
        #                                 Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"></ds:DigestMethod>
        #                             <ds:DigestValue>P3KOuiUp9NUlj5MZzBDtjStxAPXt6s0hwhRZBaBGaWk=</ds:DigestValue>
        #                         </xades:CertDigest>
        #                         <xades:IssuerSerial>
        #                             <ds:X509IssuerName>CN=QuoVadis EU Issuing Certification
        #                                 Authority G4, O=QuoVadis Trustlink B.V.,
        #                                 OID.2.5.4.97=NTRNL-30237459, C=NL</ds:X509IssuerName>
        #                             <ds:X509SerialNumber>
        #                                 398850118330166149807158326000912326027321197577</ds:X509SerialNumber>
        #                         </xades:IssuerSerial>
        #                     </xades:Cert>
        #                 </xades:SigningCertificate>
        #                 <xades:SignaturePolicyIdentifier>
        #                     <xades:SignaturePolicyId>
        #                         <xades:SigPolicyId>
        #                             <xades:Identifier Qualifier="OIDAsURN">
        #                                 urn:oid:1.2.752.76.1.199.699.1.9</xades:Identifier>
        #                         </xades:SigPolicyId>
        #                         <xades:SigPolicyHash>
        #                             <ds:DigestMethod
        #                                 Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"></ds:DigestMethod>
        #                             <ds:DigestValue>ZYs1iyR1AcD5VipwXIw2FR+pt2Q=</ds:DigestValue>
        #                         </xades:SigPolicyHash>
        #                         <xades:SigPolicyQualifiers>
        #                             <xades:SigPolicyQualifier>
        #                                 <xades:SPURI>
        #                                     https://sovos.com/wp-content/uploads/2019/10/TWOD-Signature-Policy.pdf?from=GB&amp;to=GB&amp;authCertThumbprint=33E10601F98830DCDA1B7CB131DE01F7B57ADFE8</xades:SPURI>
        #                             </xades:SigPolicyQualifier>
        #                         </xades:SigPolicyQualifiers>
        #                     </xades:SignaturePolicyId>
        #                 </xades:SignaturePolicyIdentifier>
        #             </xades:SignedSignatureProperties>
        #         </xades:SignedProperties>
        #         <xades:UnsignedProperties>
        #             <xades:UnsignedSignatureProperties>
        #                 <xades:SignatureTimeStamp>
        #                     <xades:EncapsulatedTimeStamp>
        #                         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</xades:EncapsulatedTimeStamp>
        #                 </xades:SignatureTimeStamp>
        #                 <xades:CertificateValues>
        #                     <xades:EncapsulatedX509Certificate>
        #                         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</xades:EncapsulatedX509Certificate>
        #                     <xades:EncapsulatedX509Certificate>
        #                         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</xades:EncapsulatedX509Certificate>
        #                     <xades:EncapsulatedX509Certificate>
        #                         MIIFYDCCA0igAwIBAgIUeFhfLq0sGUvjNwc1NBMotZbUZZMwDQYJKoZIhvcNAQELBQAwSDELMAkGA1UEBhMCQk0xGTAXBgNVBAoTEFF1b1ZhZGlzIExpbWl0ZWQxHjAcBgNVBAMTFVF1b1ZhZGlzIFJvb3QgQ0EgMSBHMzAeFw0xMjAxMTIxNzI3NDRaFw00MjAxMTIxNzI3NDRaMEgxCzAJBgNVBAYTAkJNMRkwFwYDVQQKExBRdW9WYWRpcyBMaW1pdGVkMR4wHAYDVQQDExVRdW9WYWRpcyBSb290IENBIDEgRzMwggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAwggIKAoICAQCgvlAQjunybEC0BJyFuTHK3C3kEakEPBtVwedYMB0ktMPvhd6MLOHBPd+C5k+tR4ds7FtJwUrVu4/sh6x/gpqG7D0DmVIB0jWerNrwU8lmPNSsAgHaJNM7qAJGr6Qc4/hzWHa39g6QDbXwz8z6+cZM5cOGMAqNF34168Xfuw6cwI2H44g4hWf6Pser4BOcBRiYz5P1sZK0/CPTz9XEJ0ngnjybCKOLXSoh4Pw5qlPafX7PGglTvF0FBM+hSo+LdoINofjSxxR3W5A2B4GbPgb6Ul5jxaYA/qXpUhtStZI5cgMJYr2wYBZupt0lwgNm3fME0UDiTouG9G/lg6AnhF4EwfWQvTA9xO+oabw4m6SkltFi2mnAAZauy8RRNOoMqv8hjlmPSlzkYZqn0ukqeI1RPToV7qJZjqlc3sX5kCLliEVx3ZGZbHqfPT2YfF72vhZooF6uCyP8Wg+qInYtyaEQHeTTRCOQiJ/GKubX9ZqzWB4vMIkIG1SitZgj7Ah3HJVdYdHLiZxfokqRmu8hqkkWCKi9YSgxyXSthfbZxbGL0eUQMk1fiyA6PEkfM4VZDdvLCXVDaXP7a3F98N/ETH3Goy7IlXnLc6KOTk0k+17kBL5yG6YnLUlamXrXXAkgt3+UuU/xDRxeiEIbEbfnkduebPRq34wGmAOtzCjvpUfzUwIDAQABo0IwQDAPBgNVHRMBAf8EBTADAQH/MA4GA1UdDwEB/wQEAwIBBjAdBgNVHQ4EFgQUo5fW816iEOGrRZ88F2Q87gFwnMwwDQYJKoZIhvcNAQELBQADggIBABj6W3X8PnrHX3fHyt/PX8MSxEBd1DKquGrX1RUVRpgjpeaQWxiZTOOtQqOCMTaIzen7xASWSIsBx40Bz1szBpZGZnQdT+3Btrm0DWHMY37XLneMlhwqI2hrhVd2cDMT/uFPpiN3GPoajOi9ZcnPP/TJF9zrx7zABC4tRi9pZsMbj/7sPtPKlL92CiUNqXsCHKnQO18LwIE6PWThv6ctTr1NxNgpxiIY0MWscgKCP6o6ojoilzHdCGPDdRS5YCgtW2jgFqlmgiNR9etT2DGbe+m3nUvriBbP+V04ikkwj+3x6xn0dxoxGE1nVGwvb2X52z3sIexe9PSLymBlVNFxZPT5pqOBMzYzcfCkeF9OrYMh3jRJjehZrJ3ydlo28hP0r+AJx2EqbPfgna67hkooby7utHnNkDPDs3b69fBsnQGQ+p6Q9pxyz0fawx/kNSBT8lTR32GDpgLiJTjehTItXnOQUl1CxM49S+H5GYQd1aJQzEH7QRTDvdbJWqNjZgKAvQU6O0ec7AAmTPWIUb+oI38YB7AL7YsmoWTTYUrrXJ/es69nA7Mf3W1daWhpq1467HxpvMc7hU6eFbm0FU/DlXpY18ls6Wy58yljXrQs8C097Vpl4KlbQMJImYFtnh8GKjwStIsPm6Ik8KaN1nrgS7ZklmOVhMJKzRwuJIczYOXD</xades:EncapsulatedX509Certificate>
        #                 </xades:CertificateValues>
        #                 <xades:RevocationValues>
        #                     <xades:CRLValues>
        #                         <xades:EncapsulatedCRLValue>
        #                             MIIFGzCCAwMCAQEwDQYJKoZIhvcNAQELBQAwVDELMAkGA1UEBhMCQk0xGTAXBgNVBAoMEFF1b1ZhZGlzIExpbWl0ZWQxKjAoBgNVBAMMIVF1b1ZhZGlzIEVudGVycHJpc2UgVHJ1c3QgQ0EgMSBHMxcNMjUwMzE0MDY0MjIyWhcNMjUwOTEwMDY0MjIxWjCCAkcwMwIUJJsI4XSuRpF6J5WLSb8s8pyw0tcXDTE2MDYxMzEyMTUwMVowDDAKBgNVHRUEAwoBBDAzAhQXqZyupPASmMb7+E3CprH+jwPrchcNMTYwNjEzMTQyOTA3WjAMMAoGA1UdFQQDCgEEMDMCFCFg3uChlPf55hOB5fwQ4mpQEmgJFw0yMDExMDYxNTM2NTVaMAwwCgYDVR0VBAMKAQQwMwIUOzBEKJjTvhz1XF6l/wTW+3RwHNUXDTIwMTEwNjE1MzYxOVowDDAKBgNVHRUEAwoBBDAzAhQ7DBcoCXpk+qAthRua/7VwXmDsdRcNMjAxMTAyMTU0OTQ1WjAMMAoGA1UdFQQDCgEEMDMCFBWIuxqKtBcTSYiMWW8h458eGM4+Fw0xOTExMjkxODE5MzJaMAwwCgYDVR0VBAMKAQQwMwIUQPYGU0PATLZx6cglDpDr1Y3YblUXDTIwMDEzMTE0MjA1NlowDDAKBgNVHRUEAwoBBDAzAhRkiLP/0sa/s5078FqfwFRQCo13IxcNMTkxMDE1MTkxMjIwWjAMMAoGA1UdFQQDCgEEMDMCFHF41Yc/eQzDv1j54u8S+72dduHcFw0xNjA2MTMxMjE1MDFaMAwwCgYDVR0VBAMKAQQwMwIURXxUdikyIStFjQYkV8VDaVU/4eAXDTE5MTAwNzIwMzk0MlowDDAKBgNVHRUEAwoBBDAzAhQqwYL15SklCzoOCtIOyMb49kMJTRcNMjAxMTAyMTU0OTQ1WjAMMAoGA1UdFQQDCgEEoDAwLjAfBgNVHSMEGDAWgBRsJr1gVSkpTmYyB6D/Y4uDWks0xjALBgNVHRQEBAICElAwDQYJKoZIhvcNAQELBQADggIBAI6MsAmLglsenJo9RN2EWB689ivbOAgvFsohE1b6S1UrHxb5WUgpF80f4098tMrQf+68x5uB9qmc7uCAgV680uFX+Ld5GrRkynEWusiAEui8mjmdX//YoJkpfx+yxJa6xLMQNLh3On8cEgY8Gx0Ioopeb7XnlBzz/+QB8jupcdipKSLVM9AYZjnWZhQ1dwT3GAryIBvXfdo1eAJf7pyG/zbD2mE6q/z5fUmbPi9cMVOWIbtUburiI+o6TqcuI0X0qPupCHFzc/EAOZaHvpzRj0qrQKBxZyrPK+kRVjdj3Um4B4vhd7l6u6yrTdaUApK3BweNFTJRXw56Uoz6UW52G7vpi2ZfKWasG6tWoZEB4o6jUA3qLinhfUYxaFcYi7uxmtcOPqrmhXFiSD8m/ZkSX2KC47WMBpal1j2eLXePJWEUGKOYNtGoMqgMpWqDBNBx4jpNnYp7oC2UgkMQWgbp+qTSqqN9kKg7Dc3VL1Rlyi6mLXFckEiYD/kfNLRZhX+Giq+ZbBuFDUaVp97/WqXEzVqL2JBHHRo235SKERh8CNpvE3MzADoz0xZUiBsDGL4o2K76SDEvj39p4FZ/Va/IpopBNCTjP+uNXObw5Ld7v5aT5zWncY6Y+At/kRbfnXjyGOQRAaCFF6aUF8/fB3n1K+i57fAavClJwpLQTg/nnkjX</xades:EncapsulatedCRLValue>
        #                         <xades:EncapsulatedCRLValue>
        #                             </xades:EncapsulatedCRLValue>
        #                     </xades:CRLValues>
        #                     <xades:OCSPValues>
        #                         <xades:EncapsulatedOCSPValue>
        #                             </xades:EncapsulatedOCSPValue>
        #                     </xades:OCSPValues>
        #                 </xades:RevocationValues>
        #                 <xades:ArchiveTimeStamp>
        #                     <xades:EncapsulatedTimeStamp>
        #                         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</xades:EncapsulatedTimeStamp>
        #                 </xades:ArchiveTimeStamp>
        #             </xades:UnsignedSignatureProperties>
        #         </xades:UnsignedProperties>
        #     </xades:QualifyingProperties>
        # </ds:Object>
    # </ds:Signature>

    # ds_objects = ET.SubElement(cxml, 'xades:QualifyingProperties', attrib={"Id": "QualifyingPropertiesId", "Target": "#cXMLSignature" , "xmlns:xades": "http://uri.etsi.org/01903/v1.3.2#"}) 
    # unsigned_properties = ET.SubElement(ds_objects, 'xades:UnsignedProperties')
    # unsigned_signature_properties = ET.SubElement(unsigned_properties, 'xades:UnsignedSignatureProperties')
    # revocation_values = ET.SubElement(unsigned_signature_properties, 'xades:RevocationValues')
    # crl_values = ET.SubElement(revocation_values, 'xades:CRLValues')
    # encapsulated_crl_value = ET.SubElement(crl_values, 'xades:EncapsulatedCRLValue')
    # encapsulated_crl_value.text = "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"
    # ocsp_values = ET.SubElement(revocation_values, 'xades:OCSPValues')
    # encapsulated_ocsp_value = ET.SubElement(ocsp_values, 'xades:EncapsulatedOCSPValue')
    # encapsulated_ocsp_value.text = "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"

    # timestamp = ET.SubElement(unsigned_signature_properties, 'xades:ArchiveTimeStamp')
    # encapsulated_time_stamp = ET.SubElement(timestamp, 'xades:EncapsulatedTimeStamp')
    # encapsulated_time_stamp.text = "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"
        
    # Registra namespaces (hazlo una sola vez, antes de construir el XML)


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

    dump_xml(cxml, include_doctype=True)       # 👈 imprímelo aquí

    return ET.ElementTree(cxml)


from xml.etree.ElementTree import tostring

DOCTYPE = '<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.066/InvoiceDetail.dtd">'

def generate_all_cxml(sheets: Dict[str, pd.DataFrame], output_prefix="./salida/invoice_"):
    hdr = sheets["Header"]
    inv_col = _find_col(hdr, ["invoiceid", "InvoiceID"])
    if not inv_col:
        raise ValueError("La hoja 'Header' debe contener 'InvoiceID'.")

    invoice_ids = hdr[inv_col].dropna().astype(str).unique().tolist()

    for inv_id in invoice_ids:
        tree_or_root = build_cxml_for_invoice(inv_id, sheets)
        # Soporta si devuelves ElementTree o directamente Element
        root = tree_or_root.getroot() if hasattr(tree_or_root, "getroot") else tree_or_root

        out = f"{output_prefix}{inv_id}.xml"
        xml_body = tostring(root, encoding="utf-8")

        with open(out, "wb") as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write((DOCTYPE + "\n").encode("utf-8"))
            f.write(xml_body)

        print(f"✅ XML generado: {out}")

generate_all_cxml(sheets, output_prefix="./salida/")
import requests
from pathlib import Path

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

# Ejemplo de uso:
response = send_xml_file("./salida/4701265854.xml")

print(response.status_code)

