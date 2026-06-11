from __future__ import annotations

import csv
import io
from datetime import datetime

from ..models import Organization
from .reports import distributor_gstr1_summary, gstr1_summary, gstr2_summary, gstr3b_summary


def _org_meta(org: Organization) -> dict:
    return {
        "org_id": org.id,
        "org_name": org.name,
        "org_code": org.code,
        "gstin": org.gstin,
        "state_code": org.state_code,
    }


def export_gstr1_json(org: Organization, year: int, month: int, *, network: bool = False) -> dict:
    if network and org.kind == "DISTRIBUTOR":
        summary = distributor_gstr1_summary(org.id, year, month)
        scope = "distributor_network"
    else:
        summary = gstr1_summary(org.id, year, month)
        scope = "facility"
    return {
        "report": "GSTR-1",
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "scope": scope,
        "organization": _org_meta(org),
        "period": summary["period"],
        "summary": {
            "b2c_count": summary["b2c_count"],
            "b2b_count": summary["b2b_count"],
            "credit_note_count": summary["credit_note_count"],
            "taxable": summary["taxable"],
            "cgst": summary["cgst"],
            "sgst": summary["sgst"],
            "igst": summary["igst"],
            "total": summary["total"],
            "credit_taxable": summary["credit_taxable"],
            "credit_total": summary["credit_total"],
            "net_taxable": summary["net_taxable"],
            "net_cgst": summary["net_cgst"],
            "net_sgst": summary["net_sgst"],
            "net_igst": summary["net_igst"],
            "net_total": summary["net_total"],
        },
        "invoices": summary["invoices"],
        "credit_notes": summary["credit_notes"],
    }


def export_gstr2_json(org: Organization, year: int, month: int) -> dict:
    summary = gstr2_summary(org.id, year, month)
    return {
        "report": "GSTR-2",
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "organization": _org_meta(org),
        "period": summary["period"],
        "summary": {
            "purchase_count": summary["purchase_count"],
            "debit_note_count": summary["debit_note_count"],
            "taxable": summary["taxable"],
            "cgst": summary["cgst"],
            "sgst": summary["sgst"],
            "igst": summary["igst"],
            "total": summary["total"],
            "debit_taxable": summary["debit_taxable"],
            "debit_total": summary["debit_total"],
            "net_taxable": summary["net_taxable"],
            "net_cgst": summary["net_cgst"],
            "net_sgst": summary["net_sgst"],
            "net_igst": summary["net_igst"],
            "net_total": summary["net_total"],
        },
        "purchases": summary["purchases"],
        "debit_notes": summary["debit_notes"],
    }


def export_gstr3b_json(org: Organization, year: int, month: int, *, network: bool = False) -> dict:
    if network and org.kind == "DISTRIBUTOR":
        g1 = distributor_gstr1_summary(org.id, year, month)
        summary = {
            "period": g1["period"],
            "outward_taxable": g1["taxable"],
            "outward_cgst": g1["cgst"],
            "outward_sgst": g1["sgst"],
            "outward_igst": g1["igst"],
            "credit_note_count": g1["credit_note_count"],
            "credit_taxable": g1["credit_taxable"],
            "credit_cgst": g1["credit_cgst"],
            "credit_sgst": g1["credit_sgst"],
            "credit_igst": g1["credit_igst"],
            "net_outward_taxable": g1["net_taxable"],
            "net_outward_cgst": g1["net_cgst"],
            "net_outward_sgst": g1["net_sgst"],
            "net_outward_igst": g1["net_igst"],
            "total_tax": g1["cgst"] + g1["sgst"] + g1["igst"],
            "net_total_tax": g1["net_cgst"] + g1["net_sgst"] + g1["net_igst"],
        }
        scope = "distributor_network"
    else:
        summary = gstr3b_summary(org.id, year, month)
        scope = "facility"
    return {
        "report": "GSTR-3B",
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "scope": scope,
        "organization": _org_meta(org),
        "period": summary["period"],
        "summary": summary,
    }


def _parse_sections(sections: str | None) -> set[str] | None:
    if not sections:
        return None
    return {s.strip().lower() for s in sections.split(",") if s.strip()}


def _csv_string(rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def export_gstr1_csv(
    org: Organization,
    year: int,
    month: int,
    *,
    network: bool = False,
    sections: str | None = None,
) -> str:
    data = export_gstr1_json(org, year, month, network=network)
    want = _parse_sections(sections)
    rows: list[list] = [
        ["report", data["report"]],
        ["period", data["period"]],
        ["gstin", data["organization"]["gstin"]],
        ["scope", data["scope"]],
        [],
        ["metric", "value"],
        ["b2c_count", data["summary"]["b2c_count"]],
        ["b2b_count", data["summary"]["b2b_count"]],
        ["credit_note_count", data["summary"]["credit_note_count"]],
        ["net_taxable", data["summary"]["net_taxable"]],
        ["net_cgst", data["summary"]["net_cgst"]],
        ["net_sgst", data["summary"]["net_sgst"]],
        ["net_igst", data["summary"]["net_igst"]],
        ["net_total", data["summary"]["net_total"]],
    ]
    if want is None or "invoices" in want:
        rows.extend([[], ["doc_type", "number", "date", "customer", "gstin", "taxable", "cgst", "sgst", "igst", "total"]])
        for inv in data["invoices"]:
            rows.append([
                inv.get("doc_type", "INV"),
                inv["number"],
                inv["date"],
                inv["customer"],
                inv.get("gstin") or "",
                inv["taxable"],
                inv["cgst"],
                inv["sgst"],
                inv["igst"],
                inv["total"],
            ])
    if want is None or "credit_notes" in want:
        rows.extend([[], ["doc_type", "number", "date", "original_invoice", "customer", "gstin", "taxable", "cgst", "sgst", "igst", "total"]])
        for cn in data["credit_notes"]:
            rows.append([
                cn.get("doc_type", "CRN"),
                cn["number"],
                cn["date"],
                cn.get("original_invoice", ""),
                cn["customer"],
                cn.get("gstin") or "",
                cn["taxable"],
                cn["cgst"],
                cn["sgst"],
                cn["igst"],
                cn["total"],
            ])
    return _csv_string(rows)


def export_gstr2_csv(org: Organization, year: int, month: int) -> str:
    data = export_gstr2_json(org, year, month)
    rows: list[list] = [
        ["report", data["report"]],
        ["period", data["period"]],
        ["gstin", data["organization"]["gstin"]],
        [],
        ["metric", "value"],
        ["purchase_count", data["summary"]["purchase_count"]],
        ["debit_note_count", data["summary"]["debit_note_count"]],
        ["net_taxable", data["summary"]["net_taxable"]],
        ["net_total", data["summary"]["net_total"]],
        [],
        ["doc_type", "number", "date", "supplier", "gstin", "taxable", "cgst", "sgst", "igst", "total"],
    ]
    for p in data["purchases"]:
        rows.append([
            p.get("doc_type", "PUR"),
            p["number"],
            p["date"],
            p["supplier"],
            p.get("gstin") or "",
            p["taxable"],
            p["cgst"],
            p["sgst"],
            p["igst"],
            p["total"],
        ])
    for dn in data["debit_notes"]:
        rows.append([
            dn.get("doc_type", "DN"),
            dn["number"],
            dn["date"],
            dn.get("supplier", ""),
            dn.get("gstin") or "",
            dn["taxable"],
            dn["cgst"],
            dn["sgst"],
            dn["igst"],
            dn["total"],
        ])
    return _csv_string(rows)


def export_gstr3b_csv(
    org: Organization,
    year: int,
    month: int,
    *,
    network: bool = False,
) -> str:
    data = export_gstr3b_json(org, year, month, network=network)
    s = data["summary"]
    rows: list[list] = [
        ["report", data["report"]],
        ["period", data["period"]],
        ["gstin", data["organization"]["gstin"]],
        ["scope", data["scope"]],
        [],
        ["metric", "value"],
        ["outward_taxable", s["outward_taxable"]],
        ["credit_note_count", s["credit_note_count"]],
        ["credit_taxable", s["credit_taxable"]],
        ["net_outward_taxable", s["net_outward_taxable"]],
        ["net_outward_cgst", s["net_outward_cgst"]],
        ["net_outward_sgst", s["net_outward_sgst"]],
        ["net_outward_igst", s["net_outward_igst"]],
        ["net_total_tax", s["net_total_tax"]],
    ]
    return _csv_string(rows)


def _portal_date(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD-MM-YYYY for GST portal style fields."""
    parts = iso_date.split("-")
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    return iso_date


def export_gstr1_portal_json(
    org: Organization,
    year: int,
    month: int,
    *,
    network: bool = False,
) -> dict:
    """GSTR-1 JSON structured for GST portal upload (simplified mapping)."""
    data = export_gstr1_json(org, year, month, network=network)
    fp = f"{month:02d}{year}"

    b2b_map: dict[str, list] = {}
    b2cs: list[dict] = []
    for inv in data["invoices"]:
        inv_row = {
            "inum": inv["number"],
            "idt": _portal_date(inv["date"]),
            "val": inv["total"],
            "pos": org.state_code or "",
            "rchrg": "N",
            "inv_typ": "R",
            "itms": [{
                "num": 1,
                "itm_det": {
                    "txval": inv["taxable"],
                    "rt": 0,
                    "camt": inv["cgst"],
                    "samt": inv["sgst"],
                    "iamt": inv["igst"],
                },
            }],
        }
        if inv.get("gstin"):
            b2b_map.setdefault(inv["gstin"], []).append(inv_row)
        else:
            b2cs.append({
                "sply_ty": "INTRA" if inv["igst"] == 0 else "INTER",
                "typ": "OE",
                "pos": org.state_code or "",
                "rt": 0,
                "txval": inv["taxable"],
                "iamt": inv["igst"],
                "camt": inv["cgst"],
                "samt": inv["sgst"],
            })

    b2b = [{"ctin": ctin, "inv": invs} for ctin, invs in b2b_map.items()]

    cdnr_map: dict[str, list] = {}
    for cn in data["credit_notes"]:
        note_row = {
            "nt_num": cn["number"],
            "nt_dt": _portal_date(cn["date"]),
            "ntty": "C",
            "p_gst": "N",
            "inum": cn.get("original_invoice", ""),
            "val": cn["total"],
            "itms": [{
                "num": 1,
                "itm_det": {
                    "txval": cn["taxable"],
                    "rt": 0,
                    "camt": cn["cgst"],
                    "samt": cn["sgst"],
                    "iamt": cn["igst"],
                },
            }],
        }
        gstin = cn.get("gstin") or "URP"
        cdnr_map.setdefault(gstin, []).append(note_row)

    cdnr = [{"ctin": ctin, "nt": notes} for ctin, notes in cdnr_map.items()]

    return {
        "gstin": org.gstin or "",
        "fp": fp,
        "version": "GST2.0",
        "hash": "hash",
        "b2b": b2b,
        "b2cs": b2cs,
        "cdnr": cdnr,
        "summary": data["summary"],
        "meta": {
            "scope": data["scope"],
            "org_name": org.name,
            "generated_at": data["generated_at"],
        },
    }