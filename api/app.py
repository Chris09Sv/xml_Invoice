from flask import Flask, request, Response
from lxml import etree
from datetime import datetime, timezone
import socket
import uuid

# db.py
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pandas as pd
def get_session(db_url: str):
    """Devuelve una sesión de SQLAlchemy para PostgreSQL."""
    engine = create_engine(db_url)  # ej: "postgresql+psycopg://user:pass@host:5432/db"
    return sessionmaker(bind=engine)()

def get_connection(db):
    # if db.empty or db=='':
    database = 'postgresql+psycopg2://postgres:1234@localhost:5432/examin'

    db =database
    return  create_engine(db)


app = Flask(__name__)

# Ruta local al DTD. Descárgalo una vez y colócalo junto al app:
# https://xml.cxml.org/schemas/cXML/1.2.045/InvoiceDetail.dtd
DTD_PATH = "InvoiceDetail.dtd"

def now_iso_with_offset():
    # ISO 8601 con zona local del contenedor/host; usa UTC si prefieres: datetime.now(timezone.utc).isoformat()
    return datetime.now().astimezone().isoformat(timespec="seconds")

def gen_payload_id():
    host = socket.gethostbyname(socket.gethostname())
    return f"{int(datetime.now().timestamp()*1000)}-{uuid.uuid4().int % (10**19)}@{host}"

def make_cxml_status(code: int, text: str, message: str):
    ts = now_iso_with_offset()
    payload_id = gen_payload_id()
    # Construimos cXML minimal para Response/Status
    root = etree.Element("cXML", timestamp=ts, payloadID=payload_id)
    resp = etree.SubElement(root, "Response")
    status = etree.SubElement(resp, "Status", code=str(code), text=text)
    status.text = message
    # Doctype requerido por consumidores cXML
    doc = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    doctype = b'<!DOCTYPE cXML SYSTEM "http://xml.cxml.org/schemas/cXML/1.2.045/InvoiceDetail.dtd">\n'
    return doctype + doc

def update_status(status_code, description, df):
    """
    Uses ONLY values from df:
      - InvoiceID  -> trans_id / WHERE invoice_id
      - invoiceDate -> business_date / trade_date
    On non-200/201, inserts into examin_exception.
    On 200/201, updates good_to_pay to SENT (or whatever 'description' says if you prefer).
    """
    if df is None or not hasattr(df, "empty") or df.empty:
        raise ValueError("update_status: df is empty or invalid")

    # strict columns from df (case-sensitive here because you’ve built df yourself)
    if "InvoiceID" not in df.columns:
        raise ValueError("update_status: 'InvoiceID' column is required in df")
    col_invoice_date = "invoiceDate" if "invoiceDate" in df.columns else None

    # first non-null row
    row = df[df["InvoiceID"].notna()].iloc[0]

    inv_id_raw = row["InvoiceID"]
    try:
        inv_id = int(float(inv_id_raw))
    except Exception:
        inv_id = str(inv_id_raw)  # still from df

    inv_date_iso = None
    if col_invoice_date and pd.notna(row[col_invoice_date]):
        d = pd.to_datetime(row[col_invoice_date], errors="coerce")
        if pd.notna(d):
            inv_date_iso = d.date().isoformat()

    try:
        sc = int(status_code)
    except Exception:
        sc = None

    engine = get_connection('')

    if sc not in (200, 201):
        # --- failure path: insert exception, DO NOT mark as SENT ---
        exception = {
            "exception_type": "goodToPay_Validation",
            # if your table has SERIAL/BIGSERIAL, don't pass exception_id at all
            "exception_id": 115,
            "trans_id":       inv_id,
            "trans_version":  1,
            "business_date":  inv_date_iso,
            "status":         "Pending",
            "trade_date":     inv_date_iso,
            "description":    description,
            "http_code":      sc,
        }
        print(exception)
        with engine.begin() as con:
            con.execute(text("""
                INSERT INTO public.examin_exception
                    (exception_type, trans_id, trans_version, business_date, status, trade_date, description, http_code)
                VALUES (:exception_type, :trans_id, :trans_version, :business_date, :status, :trade_date, :description, :http_code)
            """), exception)
            # Optional: reflect error status in good_to_pay
            con.execute(text("""
                UPDATE public.good_to_pay
                   SET record_status = :status, update_datetime = NOW()
                 WHERE invoice_id = :invoice_id
            """), {"status": "ERROR", "invoice_id": inv_id})

        return {"recorded": "exception", "invoice_id_from_df": inv_id, "http_code": sc}

    # --- success path: mark SENT (or use `description` value if you want) ---
    with engine.begin() as con:
        con.execute(text("""
            UPDATE public.good_to_pay
               SET record_status = :status, update_datetime = NOW()
             WHERE invoice_id = :invoice_id
        """), {"status": "SENT", "invoice_id": inv_id})

    return {"result": "ok", "invoice_id_from_df": inv_id, "http_code": sc}




# app.py (reemplaza la parte del DTD)
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
DTD_PATH = BASE_DIR / "dtd" / "InvoiceDetail.dtd"   # <— ruta absoluta

print("DTD_PATH:", DTD_PATH)
def validate_cxml(xml_bytes: bytes):
    parser = etree.XMLParser(load_dtd=True, no_network=True, resolve_entities=False, huge_tree=False)
    try:
        doc = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as e:
        return False, f"XMLSyntaxError: {e.msg} at line {e.position[0]}, column {e.position[1]}"

    if doc.tag != "cXML":
        return False, 'Invalid Document: root element must be "cXML"'

    try:
        with open(DTD_PATH, "rb") as f:
            dtd = etree.DTD(f)
    except OSError as e:
        return False, f"Server configuration error: cannot read DTD ({e})"

    if not dtd.validate(doc):
        last = dtd.error_log.filter_from_errors()[-1] if len(dtd.error_log) else None
        if last is not None:
            return False, f"{last.message} at line {last.line}, column {last.column}"
        return False, "Document does not conform to DTD"
    return True, None


@app.post("/cxml")
def receive_cxml():
    if not request.data:
        body = make_cxml_status(406, "Not Acceptable", "Empty body: expected cXML")
        return Response(body, status=406, mimetype="application/xml")

    ok, err = validate_cxml(request.data)
    if ok:
        body = make_cxml_status(201, "Accepted", "Acknowledged")
        return Response(body, status=201, mimetype="application/xml")
    else:
        # Formato del mensaje de error similar al ejemplo que compartiste
        msg = f"Invalid Document:{err}"
        body = make_cxml_status(406, "Not Acceptable", msg)
        return Response(body, status=406, mimetype="application/xml")

from flask import request, Response
import pandas as pd

@app.post("/send_status")
def sendStatus():
    data = request.get_json()
    if not data:
        body = make_cxml_status(406, "Not Acceptable", "Missing JSON payload")
        return Response(body, status=406, mimetype="application/xml")

    status_code = data.get("status_code")
    invoice_id = data.get("invoice_id")
    status = data.get("status")

    if not invoice_id or not status_code:
        body = make_cxml_status(406, "Not Acceptable", "Missing required fields: invoice_id or status_code")
        return Response(body, status=406, mimetype="application/xml")

    # Simula un DataFrame con los datos recibidos
    df = pd.DataFrame([{
        "InvoiceID": invoice_id,
        "invoiceDate": datetime.now().date().isoformat()  # puedes ajustar esto si tienes la fecha real
    }])

    try:
        print(df)
        result = update_status(status_code=status_code, description=status, df=df)
        body = make_cxml_status(201, "Accepted", f"Status updated for invoice {invoice_id}")
        return Response(body, status=201, mimetype="application/xml")
    except Exception as e:
        body = make_cxml_status(406, "Not Acceptable", f"Error: {str(e)}")
        return Response(body, status=406, mimetype="application/xml")

if __name__ == "__main__":
    # Para pruebas locales
    app.run(host="0.0.0.0", port=8000)


