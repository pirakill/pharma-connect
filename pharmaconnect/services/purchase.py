from __future__ import annotations

import csv
import io
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from .. import db
from ..models import (
    AccountEntry,
    Item,
    Organization,
    PurchaseBill,
    PurchaseLine,
    PurchaseReturn,
    PurchaseReturnLine,
    Supplier,
)
from .gst import line_tax
from .inventory import receive_purchase_stock, return_purchase_stock

TWO = Decimal("0.01")


def next_purchase_number(org_id: int) -> str:
    count = PurchaseBill.query.filter_by(org_id=org_id).count()
    return f"PB{org_id:03d}-{count + 1:06d}"


def create_purchase(
    org: Organization,
    supplier: Supplier,
    lines: list[dict],
    invoice_no: str = "",
    warehouse_id: int | None = None,
) -> PurchaseBill:
    from .inventory import resolve_warehouse

    wh = resolve_warehouse(org, warehouse_id) if org.kind == "DISTRIBUTOR" else None
    pb = PurchaseBill(
        number=next_purchase_number(org.id),
        org_id=org.id,
        warehouse_id=wh.id if wh else None,
        supplier_id=supplier.id,
        invoice_no=invoice_no,
    )
    db.session.add(pb)
    db.session.flush()

    taxable = cgst = sgst = igst = Decimal("0")
    stock_lines: list[dict] = []
    for row in lines:
        item = db.session.get(Item, row["item_id"])
        qty = Decimal(str(row["qty"]))
        rate = Decimal(str(row["rate"]))
        line_taxable = (qty * rate).quantize(TWO, ROUND_HALF_UP)
        gst_rate = Decimal(str(item.tax_slab.rate if item and item.tax_slab else 0))
        tax = line_tax(line_taxable, gst_rate, supplier.gstin[:2] if supplier.gstin and len(supplier.gstin) >= 2 else org.state_code, org.state_code)
        db.session.add(
            PurchaseLine(
                purchase_id=pb.id,
                item_id=item.id,
                batch_no=row["batch_no"],
                expiry=row["expiry"],
                qty=qty,
                rate=rate,
                mrp=row.get("mrp", rate),
                taxable=line_taxable,
                cgst=tax["cgst"],
                sgst=tax["sgst"],
                igst=tax["igst"],
            )
        )
        taxable += line_taxable
        cgst += tax["cgst"]
        sgst += tax["sgst"]
        igst += tax["igst"]
        stock_lines.append({
            "item_id": item.id,
            "batch_no": row["batch_no"],
            "expiry": row["expiry"],
            "qty": qty,
            "rate": rate,
            "mrp": row.get("mrp", item.mrp),
            "ptr": item.ptr,
            "cost_rate": rate,
            "rack": row.get("rack"),
        })

    receive_purchase_stock(
        org,
        pb.number,
        stock_lines,
        note=f"Purchase from {supplier.name}",
        warehouse_id=pb.warehouse_id,
    )

    pb.taxable = taxable
    pb.cgst = cgst
    pb.sgst = sgst
    pb.igst = igst
    pb.grand_total = taxable + cgst + sgst + igst
    supplier.outstanding = Decimal(str(supplier.outstanding or 0)) + pb.grand_total

    db.session.add(
        AccountEntry(
            org_id=org.id,
            entry_type="PURCHASE",
            reference=pb.number,
            party_name=supplier.name,
            debit=pb.grand_total,
            credit=Decimal("0"),
            note=invoice_no,
        )
    )
    return pb


def next_purchase_return_number(org_id: int) -> str:
    count = PurchaseReturn.query.filter_by(org_id=org_id).count()
    return f"PR{org_id:03d}-{count + 1:06d}"


def create_purchase_return(
    org: Organization,
    purchase: PurchaseBill,
    lines: list[dict],
    reason: str = "",
) -> PurchaseReturn:
    pr = PurchaseReturn(
        number=next_purchase_return_number(org.id),
        org_id=org.id,
        purchase_id=purchase.id,
        supplier_id=purchase.supplier_id,
        reason=reason,
    )
    db.session.add(pr)
    db.session.flush()

    taxable = cgst = sgst = igst = Decimal("0")
    stock_lines: list[dict] = []
    for row in lines:
        pl = db.session.get(PurchaseLine, row["purchase_line_id"])
        if not pl or pl.purchase_id != purchase.id:
            raise ValueError("Invalid purchase line")
        qty = Decimal(str(row["qty"]))
        if qty > Decimal(str(pl.qty)):
            raise ValueError("Return qty exceeds purchased qty")
        portion = qty / Decimal(str(pl.qty))
        line_taxable = (Decimal(str(pl.taxable)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_cgst = (Decimal(str(pl.cgst)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_sgst = (Decimal(str(pl.sgst)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_igst = (Decimal(str(pl.igst)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_total = line_taxable + line_cgst + line_sgst + line_igst

        db.session.add(
            PurchaseReturnLine(
                return_id=pr.id,
                purchase_line_id=pl.id,
                item_id=pl.item_id,
                batch_no=pl.batch_no,
                qty=qty,
                rate=pl.rate,
                taxable=line_taxable,
                cgst=line_cgst,
                sgst=line_sgst,
                igst=line_igst,
                line_total=line_total,
            )
        )
        stock_lines.append({
            "item_id": pl.item_id,
            "batch_no": pl.batch_no,
            "qty": qty,
        })
        taxable += line_taxable
        cgst += line_cgst
        sgst += line_sgst
        igst += line_igst

    return_purchase_stock(
        org,
        pr.number,
        stock_lines,
        note=reason or f"Return to {purchase.supplier.name}",
        warehouse_id=purchase.warehouse_id,
    )

    pr.taxable = taxable
    pr.cgst = cgst
    pr.sgst = sgst
    pr.igst = igst
    pr.grand_total = taxable + cgst + sgst + igst

    supplier = purchase.supplier
    supplier.outstanding = max(
        Decimal(str(supplier.outstanding or 0)) - pr.grand_total,
        Decimal("0"),
    )

    db.session.add(
        AccountEntry(
            org_id=org.id,
            entry_type="PURCHASE_RETURN",
            reference=pr.number,
            party_name=supplier.name,
            debit=Decimal("0"),
            credit=pr.grand_total,
            note=reason or purchase.invoice_no,
        )
    )
    return pr


def batch_purchase_history(
    org_id: int,
    batch_no: str = "",
    item_id: int | None = None,
) -> list[dict]:
    q = (
        db.session.query(PurchaseLine, PurchaseBill, Item, Supplier)
        .join(PurchaseBill, PurchaseLine.purchase_id == PurchaseBill.id)
        .join(Item, PurchaseLine.item_id == Item.id)
        .join(Supplier, PurchaseBill.supplier_id == Supplier.id)
        .filter(PurchaseBill.org_id == org_id)
        .order_by(PurchaseBill.purchased_on.desc(), PurchaseLine.batch_no)
    )
    if batch_no.strip():
        q = q.filter(PurchaseLine.batch_no.ilike(f"%{batch_no.strip()}%"))
    if item_id:
        q = q.filter(PurchaseLine.item_id == item_id)

    rows: list[dict] = []
    for pl, pb, item, supplier in q.limit(250).all():
        returned = (
            db.session.query(func.coalesce(func.sum(PurchaseReturnLine.qty), 0))
            .join(PurchaseReturn, PurchaseReturnLine.return_id == PurchaseReturn.id)
            .filter(PurchaseReturnLine.purchase_line_id == pl.id)
            .scalar()
        )
        ret_qty = float(returned or 0)
        rows.append({
            "purchase_number": pb.number,
            "purchase_date": pb.purchased_on.strftime("%d-%b-%Y"),
            "supplier": supplier.name,
            "warehouse": pb.warehouse.name if pb.warehouse else "—",
            "item_code": item.code,
            "item_name": item.name,
            "batch_no": pl.batch_no,
            "expiry": pl.expiry.strftime("%d-%b-%Y"),
            "qty_purchased": float(pl.qty),
            "qty_returned": ret_qty,
            "qty_net": float(pl.qty) - ret_qty,
            "rate": float(pl.rate),
            "value_net": (float(pl.qty) - ret_qty) * float(pl.rate),
        })
    return rows


def record_supplier_payment(org_id: int, supplier_id: int, amount: Decimal, note: str = "") -> None:
    if amount <= 0:
        raise ValueError("Amount must be positive")
    supplier = db.session.get(Supplier, supplier_id)
    if not supplier or supplier.org_id != org_id:
        raise ValueError("Supplier not found")
    outstanding = Decimal(str(supplier.outstanding or 0))
    if amount > outstanding:
        raise ValueError("Payment exceeds supplier outstanding")
    supplier.outstanding = outstanding - amount
    ref = f"PAY-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    db.session.add(
        AccountEntry(
            org_id=org_id,
            entry_type="PAYMENT",
            reference=ref,
            party_name=supplier.name,
            debit=Decimal("0"),
            credit=amount,
            note=note or f"Payment to {supplier.name}",
        )
    )


PURCHASE_CSV_COLUMNS = (
    "supplier_code", "invoice_no", "item_code", "batch_no", "expiry",
    "qty", "rate", "mrp", "warehouse_code", "rack",
)


def _norm_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def export_purchase_csv_template() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(PURCHASE_CSV_COLUMNS)
    writer.writerow([
        "SUP01", "INV-2026-001", "PCM500", "B-PCM-01", "2027-06-30",
        "100", "23.80", "35", "WH01", "A1",
    ])
    return buf.getvalue()


def import_purchase_csv(org: Organization, csv_text: str) -> dict:
    """Import purchase bills grouped by supplier_code + invoice_no."""
    from .inventory import resolve_warehouse, warehouses

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError("CSV header row is required")

    field_map = {_norm_header(h): h for h in reader.fieldnames}
    required = {"supplier_code", "item_code", "batch_no", "expiry", "qty", "rate"}
    missing = required - set(field_map)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")

    wh_by_code = {w.code.upper(): w.id for w in warehouses(org.id)} if org.kind == "DISTRIBUTOR" else {}

    groups: dict[tuple[str, str], list[dict]] = {}
    errors: list[str] = []
    skipped = 0

    for line_no, row in enumerate(reader, start=2):
        try:
            supplier_code = (row.get(field_map["supplier_code"]) or "").strip().upper()
            if not supplier_code:
                skipped += 1
                continue
            invoice_no = (row.get(field_map["invoice_no"], "") or "").strip() if "invoice_no" in field_map else ""
            item_code = (row.get(field_map["item_code"]) or "").strip().upper()
            item = Item.query.filter_by(code=item_code).first()
            if not item:
                raise ValueError(f"Unknown item code {item_code}")

            expiry_raw = (row.get(field_map["expiry"]) or "").strip()
            if "-" in expiry_raw and len(expiry_raw) >= 8:
                expiry = date.fromisoformat(expiry_raw[:10])
            else:
                expiry = datetime.strptime(expiry_raw, "%d-%m-%Y").date()

            wh_code = (row.get(field_map["warehouse_code"], "") or "").strip().upper() if "warehouse_code" in field_map else ""
            warehouse_id = wh_by_code.get(wh_code) if wh_code else None
            rack = (row.get(field_map["rack"], "") or "").strip() if "rack" in field_map else ""

            line = {
                "item_id": item.id,
                "batch_no": (row.get(field_map["batch_no"]) or "").strip(),
                "expiry": expiry,
                "qty": Decimal(str(row.get(field_map["qty"]) or 0)),
                "rate": Decimal(str(row.get(field_map["rate"]) or 0)),
                "mrp": Decimal(str(row.get(field_map["mrp"]) or item.mrp or 0)) if "mrp" in field_map else item.mrp,
                "rack": rack or None,
            }
            if line["qty"] <= 0 or line["rate"] <= 0:
                raise ValueError("qty and rate must be positive")

            key = (supplier_code, invoice_no)
            groups.setdefault(key, []).append({"line": line, "warehouse_id": warehouse_id})
        except (ValueError, KeyError) as exc:
            errors.append(f"Row {line_no}: {exc}")

    created = 0
    for (supplier_code, invoice_no), entries in groups.items():
        try:
            supplier = Supplier.query.filter_by(org_id=org.id, code=supplier_code).first()
            if not supplier:
                raise ValueError(f"Supplier {supplier_code} not found")

            lines = [e["line"] for e in entries]
            warehouse_id = next((e["warehouse_id"] for e in entries if e["warehouse_id"]), None)
            if org.kind == "DISTRIBUTOR" and not warehouse_id:
                warehouse_id = resolve_warehouse(org).id

            create_purchase(org, supplier, lines, invoice_no=invoice_no, warehouse_id=warehouse_id)
            created += 1
        except ValueError as exc:
            errors.append(f"{supplier_code}/{invoice_no or '—'}: {exc}")

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "total_processed": created + skipped,
    }