#!/usr/bin/env python3
import os, re, base64
from email import policy
from email.parser import BytesParser

def save_bytes(data: bytes, filename: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path

def email_parse_extract(raw: bytes, out_dir: str):
    saved = []
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:
        return saved
    parts = [msg] if not msg.is_multipart() else [p for p in msg.walk() if not p.is_multipart()]
    idx = 1
    for part in parts:
        if part.get_content_type() == "application/pdf":
            fn = part.get_filename() or part.get("Content-ID", "").strip("<>") or f"attachment_{idx}.pdf"
            if not fn.lower().endswith(".pdf"): fn += ".pdf"
            payload = part.get_payload(decode=True)
            if payload: saved.append(save_bytes(payload, fn, out_dir)); idx += 1
    return saved

def manual_multipart_extract(raw: bytes, out_dir: str):
    saved = []
    text = raw.decode("utf-8", errors="ignore")
    lines = text.splitlines()
    boundary = next((ln.strip() for ln in lines[:5] if ln.startswith("--") and len(ln.strip("-"))>=6), None)
    if not boundary:
        m = re.search(r'boundary="?([^"\r\n;]+)"?', text, re.I)
        if m: boundary = "--" + m.group(1)
    if not boundary: return saved

    parts = text.split(boundary)
    idx = 1
    for p in parts:
        p = p.strip()
        if not p or p == "--": continue
        if "\r\n\r\n" in p: headers, body = p.split("\r\n\r\n", 1)
        elif "\n\n" in p: headers, body = p.split("\n\n", 1)
        else: continue
        if "content-type: application/pdf" not in headers.lower(): continue

        m = re.search(r'filename="?([^"\r\n;]+)"?', headers, re.I)
        fn = (m.group(1).strip() if m else None) or \
             (re.search(r'content-id:\s*<([^>]+)>', headers, re.I).group(1) if re.search(r'content-id:\s*<([^>]+)>', headers, re.I) else None) \
             or f"attachment_{idx}.pdf"
        if not fn.lower().endswith(".pdf"): fn += ".pdf"

        body = body.strip()
        body = re.split(r'\r?\n--', body)[0].strip()
        b64 = re.sub(r'[^A-Za-z0-9+/=\r\n]', '', body)
        try:
            data = base64.b64decode(b64, validate=False)
            if data: saved.append(save_bytes(data, fn, out_dir)); idx += 1
        except Exception:
            pass
    return saved

if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "out"
    with open(src, "rb") as f:
        raw = f.read()
    saved = email_parse_extract(raw, out_dir) or manual_multipart_extract(raw, out_dir)
    print(f"Guardados: {saved}" if saved else "No se encontraron PDFs.")

# Ejemplo de uso:
# python extract_pdf_from_mime.py email.eml output_directory
