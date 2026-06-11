from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation

from .. import db
from ..models import Item, TaxSlab

REQUIRED_COLUMNS = {"code", "name"}
OPTIONAL_COLUMNS = {
    "barcode", "manufacturer", "pack", "unit", "schedule",
    "hsn", "gst_rate", "mrp", "ptr",
}
ALL_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

HEADER_ALIASES = {
    "item_code": "code",
    "sku": "code",
    "product_code": "code",
    "item_name": "name",
    "medicine": "name",
    "product_name": "name",
    "gst": "gst_rate",
    "gst%": "gst_rate",
    "tax_rate": "gst_rate",
    "price": "mrp",
    "selling_price": "mrp",
}


def _normalize_header(h: str) -> str:
    key = h.strip().lower().replace(" ", "_")
    return HEADER_ALIASES.get(key, key)


def _tax_slab_for_rate(rate: Decimal) -> TaxSlab | None:
    slab = TaxSlab.query.filter_by(rate=rate).first()
    if slab:
        return slab
    slab = TaxSlab(name=f"GST {rate}%", rate=rate, hsn="3004")
    db.session.add(slab)
    db.session.flush()
    return slab


def _parse_decimal(val: str, default: Decimal = Decimal("0")) -> Decimal:
    if not val or not str(val).strip():
        return default
    return Decimal(str(val).strip())


def upsert_item(data: dict) -> tuple[Item, bool]:
    """Create or update item by code. Returns (item, created)."""
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code or not name:
        raise ValueError("Code and name are required")

    item = Item.query.filter_by(code=code).first()
    created = item is None
    if not item:
        item = Item(code=code, name=name)
        db.session.add(item)

    item.name = name
    item.barcode = (data.get("barcode") or "").strip() or None
    item.manufacturer = (data.get("manufacturer") or "").strip() or None
    item.pack = (data.get("pack") or "1x10").strip() or "1x10"
    item.unit = (data.get("unit") or "strip").strip() or "strip"
    item.schedule = (data.get("schedule") or "").strip() or None
    item.hsn = (data.get("hsn") or "").strip() or None
    item.mrp = _parse_decimal(data.get("mrp", ""))
    item.ptr = _parse_decimal(data.get("ptr", ""))
    item.is_active = data.get("is_active", True) if data.get("is_active") is not None else item.is_active

    gst_rate = data.get("gst_rate")
    if gst_rate not in (None, ""):
        rate = _parse_decimal(str(gst_rate))
        if rate > 0:
            slab = _tax_slab_for_rate(rate)
            item.tax_slab_id = slab.id
            if not item.hsn and slab.hsn:
                item.hsn = slab.hsn

    return item, created


def import_csv(text: str, update_existing: bool = True) -> dict:
    """Import items from CSV text. Returns summary with counts and errors."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV is empty or has no header row")

    field_map = {_normalize_header(h): h for h in reader.fieldnames if h}
    mapped = set(field_map.keys())
    if not REQUIRED_COLUMNS.issubset(mapped):
        missing = REQUIRED_COLUMNS - mapped
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    created = updated = skipped = 0
    errors: list[str] = []

    for line_no, row in enumerate(reader, start=2):
        try:
            data = {}
            for norm, orig in field_map.items():
                if norm in ALL_COLUMNS:
                    data[norm] = row.get(orig, "")
            code = (data.get("code") or "").strip()
            if not code:
                skipped += 1
                continue

            existing = Item.query.filter_by(code=code).first()
            if existing and not update_existing:
                skipped += 1
                continue

            _, was_created = upsert_item(data)
            if was_created:
                created += 1
            else:
                updated += 1
        except (ValueError, InvalidOperation) as exc:
            errors.append(f"Row {line_no}: {exc}")

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total_processed": created + updated + skipped,
    }


def export_csv_template() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["code", "name", "barcode", "manufacturer", "pack", "unit",
                     "schedule", "hsn", "gst_rate", "mrp", "ptr"])
    writer.writerow(["PCM500", "Paracetamol 500mg", "890101001001", "Cipla", "1x15",
                     "strip", "", "3004", "12", "35", "28"])
    writer.writerow(["AMX500", "Amoxicillin 500mg", "890101001002", "Sun Pharma", "1x10",
                     "strip", "H", "3004", "12", "120", "95"])
    return buf.getvalue()


def item_stats() -> dict:
    total = Item.query.count()
    active = Item.query.filter_by(is_active=True).count()
    return {"total": total, "active": active, "inactive": total - active}