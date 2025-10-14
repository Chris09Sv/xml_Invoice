from flask import Flask, request, Response
from lxml import etree
from datetime import datetime, timezone
import socket
import uuid

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
    return False, None


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

if __name__ == "__main__":
    # Para pruebas locales
    app.run(host="0.0.0.0", port=8000)
