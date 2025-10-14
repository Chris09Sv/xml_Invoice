#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_cxml_to_dfs.py

Lee un archivo cXML (InvoiceDetail) y lo convierte en tres DataFrames (header, items, summary).
Guarda CSVs y opcionalmente imprime un resumen.

Uso:
  python parse_cxml_to_dfs.py --input path/al/archivo.xml --outdir ./salida --print

Requisitos:
  - Python 3.8+
  - pandas (pip install pandas)
"""

from __future__ import annotations

import argparse
import os
import sys
import json
from typing import Dict, Any, List, Tuple, Optional
import xml.etree.ElementTree as ET

import pandas as pd


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def _attr(el: Optional[ET.Element], name: str) -> str:
    return el.get(name, "") if el is not None else ""


def parse_header(root: ET.Element) -> Dict[str, Any]:
    # Top-level attributes
    data: Dict[str, Any] = {
        "payloadID": root.get("payloadID", ""),
        "timestamp": root.get("timestamp", ""),
        "version": root.get("version", ""),
    }

    header = root.find("Header")
    if header is None:
        return data

    # From
    from_el = header.find("From")
    if from_el is not None:
        cred = from_el.find("Credential")
        data["from_credential_domain"] = _attr(cred, "domain")
        data["from_identity"] = _text(cred.find("Identity")) if cred is not None else ""
        corr = from_el.find("Correspondent/Contact/Name")
        data["from_correspondent_name"] = _text(corr)

    # To (puede haber varios Credential)
    to_el = header.find("To")
    if to_el is not None:
        creds = to_el.findall("Credential")
        for i, c in enumerate(creds, start=1):
            data[f"to_credential{i}_domain"] = _attr(c, "domain")
            data[f"to_credential{i}_identity"] = _text(c.find("Identity"))

    # Sender
    sender = header.find("Sender")
    if sender is not None:
        cred = sender.find("Credential")
        data["sender_credential_domain"] = _attr(cred, "domain")
        data["sender_identity"] = _text(cred.find("Identity")) if cred is not None else ""
        data["sender_shared_secret"] = _text(cred.find("SharedSecret")) if cred is not None else ""
        data["user_agent"] = _text(sender.find("UserAgent"))

    # Request basics
    req = root.find("Request")
    if req is not None:
        data["request_id"] = _attr(req, "Id")
        data["request_deploymentMode"] = _attr(req, "deploymentMode")

    # InvoiceDetailRequestHeader
    idr = root.find("Request/InvoiceDetailRequest/InvoiceDetailRequestHeader")
    if idr is not None:
        # attributes
        for att in ("invoiceDate", "invoiceID", "invoiceOrigin", "operation", "purpose"):
            data[f"header_{att}"] = _attr(idr, att)

        # partners
        partners = idr.findall("InvoicePartner")
        for i, p in enumerate(partners, start=1):
            contact = p.find("Contact")
            role = _attr(contact, "role")
            addrid = _attr(contact, "addressID")
            name = _text(contact.find("Name")) if contact is not None else ""
            email_el = contact.find("Email") if contact is not None else None
            email = _text(email_el)
            data[f"partner{i}_role"] = role
            data[f"partner{i}_addressID"] = addrid
            data[f"partner{i}_name"] = name
            data[f"partner{i}_email"] = email

        # payment term + comments
        pterm = idr.find("PaymentTerm")
        data["paymentTerm_days"] = _attr(pterm, "payInNumberOfDays")
        data["comments"] = _text(idr.find("Comments"))

        # Extrinsics -> volcar como columnas extrinsic_<name> = value (o URL si es attachment)
        for ex in idr.findall("Extrinsic"):
            ex_name = _attr(ex, "name").strip() or "unnamed"
            value = _text(ex)
            # Si hay Attachment/URL preferimos ese valor
            url_el = ex.find("Attachment/URL")
            if url_el is not None and _text(url_el):
                value = _text(url_el)
            data[f"extrinsic_{ex_name}"] = value

    return data


def parse_items(root: ET.Element) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    # Puede haber múltiples InvoiceDetailOrder
    for order in root.findall("Request/InvoiceDetailRequest/InvoiceDetailOrder"):
        order_info = order.find("InvoiceDetailOrderInfo/OrderIDInfo")
        order_id = _attr(order_info, "orderID") if order_info is not None else ""

        for it in order.findall("InvoiceDetailItem"):
            row: Dict[str, Any] = {"order_id": order_id}
            row["invoiceLineNumber"] = _attr(it, "invoiceLineNumber")
            row["quantity"] = _attr(it, "quantity")

            row["unitOfMeasure"] = _text(it.find("UnitOfMeasure"))

            m_price = it.find("UnitPrice/Money")
            row["unitPrice"] = _text(m_price)
            row["unitPrice_currency"] = _attr(m_price, "currency") if m_price is not None else ""

            ref = it.find("InvoiceDetailItemReference")
            row["ref_lineNumber"] = _attr(ref, "lineNumber") if ref is not None else ""
            row["description"] = _text(it.find("InvoiceDetailItemReference/Description"))

            m_sub = it.find("SubtotalAmount/Money")
            row["subtotal"] = _text(m_sub)
            row["subtotal_currency"] = _attr(m_sub, "currency") if m_sub is not None else ""

            # Distribution (opcional)
            acc_seg = it.find("Distribution/Accounting/AccountingSegment")
            row["dist_accounting_id"] = _attr(acc_seg, "id") if acc_seg is not None else ""
            row["dist_accounting_name"] = _text(it.find("Distribution/Accounting/AccountingSegment/Name"))
            row["dist_accounting_desc"] = _text(it.find("Distribution/Accounting/AccountingSegment/Description"))
            m_charge = it.find("Distribution/Charge/Money")
            if m_charge is not None:
                row["dist_charge_amount"] = _text(m_charge)
                row["dist_charge_currency"] = _attr(m_charge, "currency")
                row["dist_charge_alt_amount"] = _attr(m_charge, "alternateAmount")
                row["dist_charge_alt_currency"] = _attr(m_charge, "alternateCurrency")

            items.append(row)

    return items


def parse_summary(root: ET.Element) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    s = root.find("Request/InvoiceDetailRequest/InvoiceDetailSummary")
    if s is None:
        return summary

    m_sub = s.find("SubtotalAmount/Money")
    summary["subtotal"] = _text(m_sub)
    summary["subtotal_currency"] = _attr(m_sub, "currency") if m_sub is not None else ""

    tax = s.find("Tax")
    if tax is not None:
        m_tax = tax.find("Money")
        summary["tax_total"] = _text(m_tax)
        summary["tax_currency"] = _attr(m_tax, "currency") if m_tax is not None else ""
        summary["tax_description"] = _text(tax.find("Description"))

        tdet = tax.find("TaxDetail")
        if tdet is not None:
            summary["tax_category"] = _attr(tdet, "category")
            summary["tax_percentageRate"] = _attr(tdet, "percentageRate")

            m_txbl = tdet.find("TaxableAmount/Money")
            summary["tax_taxable_amount"] = _text(m_txbl)
            summary["tax_taxable_currency"] = _attr(m_txbl, "currency") if m_txbl is not None else ""

            m_tamt = tdet.find("TaxAmount/Money")
            summary["tax_amount"] = _text(m_tamt)
            summary["tax_amount_currency"] = _attr(m_tamt, "currency") if m_tamt is not None else ""

    m_net = s.find("NetAmount/Money")
    summary["net_amount"] = _text(m_net)
    summary["net_currency"] = _attr(m_net, "currency") if m_net is not None else ""

    return summary


def parse_cxml(xml_path: str) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve (df_header, df_items, df_summary)."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    header_dict = parse_header(root)
    items_list = parse_items(root)
    summary_dict = parse_summary(root)

    df_header = pd.DataFrame([header_dict])
    df_items = pd.DataFrame(items_list) if items_list else pd.DataFrame(columns=[
        "order_id","invoiceLineNumber","quantity","unitOfMeasure","unitPrice","unitPrice_currency",
        "ref_lineNumber","description","subtotal","subtotal_currency","dist_accounting_id",
        "dist_accounting_name","dist_accounting_desc","dist_charge_amount","dist_charge_currency",
        "dist_charge_alt_amount","dist_charge_alt_currency"
    ])
    df_summary = pd.DataFrame([summary_dict]) if summary_dict else pd.DataFrame()

    return df_header, df_items, df_summary


def main():
    ap = argparse.ArgumentParser(description="Parse cXML InvoiceDetail a DataFrames / CSVs")
    ap.add_argument("--input", required=True, help="Ruta del archivo cXML")
    ap.add_argument("--outdir", default=".", help="Directorio de salida para CSVs")
    ap.add_argument("--print", action="store_true", help="Imprimir preview en consola")
    args = ap.parse_args()

    in_path = args.input
    outdir = args.outdir
    os.makedirs(outdir, exist_ok=True)

    try:
        df_header, df_items, df_summary = parse_cxml(in_path)
    except Exception as e:
        print(f"[ERROR] No se pudo parsear el XML: {e}", file=sys.stderr)
        sys.exit(1)

    # Guardar CSVs
    header_csv = os.path.join(outdir, "cxml_header.csv")
    items_csv = os.path.join(outdir, "cxml_items.csv")
    summary_csv = os.path.join(outdir, "cxml_summary.csv")

    df_header.to_csv(header_csv, index=False)
    df_items.to_csv(items_csv, index=False)
    df_summary.to_csv(summary_csv, index=False)

    if args.print:
        print("== HEADER ==")
        print(df_header.head(1).to_string(index=False))
        print("\n== ITEMS ==")
        print(df_items.to_string(index=False) if not df_items.empty else "(sin líneas)")
        print("\n== SUMMARY ==")
        print(df_summary.head(1).to_string(index=False) if not df_summary.empty else "(sin resumen)")

    print("CSV generados:")
    print(" -", header_csv)
    print(" -", items_csv)
    print(" -", summary_csv)


if __name__ == "__main__":
    main()
