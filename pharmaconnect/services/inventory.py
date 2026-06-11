from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func

from .. import db
from ..models import (
    ConsignmentBatch,
    ConsignmentShipment,
    ConsignmentShipmentLine,
    FacilityStockLimit,
    Item,
    Organization,
    StockLedger,
    WarehouseTransfer,
    WarehouseTransferLine,
)
from .numbering import next_shipment_number, next_transfer_number


def stock_on_hand(item_id: int, facility_id: int) -> Decimal:
    total = (
        db.session.query(func.coalesce(func.sum(ConsignmentBatch.qty_on_hand), 0))
        .filter_by(item_id=item_id, facility_id=facility_id)
        .scalar()
    )
    return Decimal(str(total or 0))


def fefo_batches(item_id: int, facility_id: int, qty_needed: Decimal) -> list[ConsignmentBatch]:
    today = date.today()
    batches = (
        ConsignmentBatch.query.filter_by(item_id=item_id, facility_id=facility_id)
        .filter(ConsignmentBatch.qty_on_hand > ConsignmentBatch.qty_reserved)
        .filter(ConsignmentBatch.expiry >= today)
        .order_by(ConsignmentBatch.expiry.asc(), ConsignmentBatch.id.asc())
        .all()
    )
    picked: list[ConsignmentBatch] = []
    remaining = qty_needed
    for b in batches:
        if remaining <= 0:
            break
        avail = Decimal(str(b.available_qty))
        if avail <= 0:
            continue
        picked.append(b)
        remaining -= avail
    if remaining > 0:
        raise ValueError(f"Insufficient stock for item {item_id} at facility {facility_id}")
    return picked


def _log_movement(batch: ConsignmentBatch, movement: str, qty_delta: Decimal, reference: str, note: str = "") -> None:
    db.session.add(
        StockLedger(
            batch_id=batch.id,
            facility_id=batch.facility_id,
            movement=movement,
            qty_delta=qty_delta,
            reference=reference,
            note=note,
        )
    )


def receive_return(batch: ConsignmentBatch, qty: Decimal, reference: str, note: str = "") -> None:
    batch.qty_on_hand = Decimal(str(batch.qty_on_hand)) + qty
    _log_movement(batch, "RETURN_IN", qty, reference, note)


def write_off_batch(batch: ConsignmentBatch, qty: Decimal, reason: str = "Expired/damaged") -> None:
    on_hand = Decimal(str(batch.qty_on_hand))
    if qty <= 0 or qty > on_hand:
        raise ValueError("Invalid write-off quantity")
    batch.qty_on_hand = on_hand - qty
    ref = f"WO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    _log_movement(batch, "WRITE_OFF", -qty, ref, reason)


def set_batch_rack(batch: ConsignmentBatch, rack: str) -> None:
    batch.rack = rack.strip().upper() or None


def batches_with_racks(
    org_id: int,
    *,
    distributor_id: int | None = None,
    facility_id: int | None = None,
) -> list[dict]:
    q = ConsignmentBatch.query.filter(ConsignmentBatch.qty_on_hand > 0)
    if distributor_id:
        q = q.filter_by(distributor_id=distributor_id)
    elif facility_id:
        q = q.filter_by(facility_id=facility_id)
    else:
        q = q.filter_by(facility_id=org_id)
    batches = q.order_by(ConsignmentBatch.rack, ConsignmentBatch.item_id).all()
    return [
        {
            "batch_id": b.id,
            "facility": b.facility.name,
            "item_code": b.item.code,
            "item_name": b.item.name,
            "batch_no": b.batch_no,
            "expiry": b.expiry.strftime("%d-%b-%Y"),
            "qty": float(b.qty_on_hand),
            "rack": b.rack or "",
        }
        for b in batches
    ]


def expired_batches(org_id: int, *, distributor_id: int | None = None) -> list[ConsignmentBatch]:
    today = date.today()
    q = ConsignmentBatch.query.filter(
        ConsignmentBatch.expiry < today,
        ConsignmentBatch.qty_on_hand > 0,
    )
    if distributor_id:
        q = q.filter_by(distributor_id=distributor_id)
    else:
        q = q.filter_by(facility_id=org_id)
    return q.order_by(ConsignmentBatch.expiry).all()


def customer_facilities(distributor_id: int, active_only: bool = False) -> list[Organization]:
    q = Organization.query.filter_by(parent_id=distributor_id).filter(
        Organization.kind.notin_(["WAREHOUSE"])
    )
    if active_only:
        q = q.filter_by(is_active=True)
    return q.order_by(Organization.name).all()


def warehouses(distributor_id: int) -> list[Organization]:
    return (
        Organization.query.filter_by(parent_id=distributor_id, kind="WAREHOUSE", is_active=True)
        .order_by(Organization.code)
        .all()
    )


def get_or_create_warehouse(distributor_id: int) -> Organization:
    """Ensure at least one warehouse exists and return the default."""
    existing = warehouses(distributor_id)
    if existing:
        return existing[0]
    dist = db.session.get(Organization, distributor_id)
    wh = Organization(
        code="WH01",
        name=f"{dist.name} — Central Warehouse",
        kind="WAREHOUSE",
        gstin=dist.gstin,
        address=dist.address,
        state_code=dist.state_code,
        parent_id=distributor_id,
    )
    db.session.add(wh)
    db.session.flush()
    return wh


def create_warehouse(distributor_id: int, code: str, name: str, address: str = "") -> Organization:
    code = code.strip().upper()
    if not code or not name.strip():
        raise ValueError("Warehouse code and name are required")
    if Organization.query.filter_by(code=code).first():
        raise ValueError(f"Organization code {code} already exists")
    dist = db.session.get(Organization, distributor_id)
    if not dist:
        raise ValueError("Distributor not found")
    wh = Organization(
        code=code,
        name=name.strip(),
        kind="WAREHOUSE",
        gstin=dist.gstin,
        address=address.strip() or dist.address,
        state_code=dist.state_code,
        parent_id=distributor_id,
    )
    db.session.add(wh)
    db.session.flush()
    return wh


def resolve_warehouse(org: Organization, warehouse_id: int | None = None) -> Organization | None:
    if org.kind == "WAREHOUSE":
        return org
    if org.kind != "DISTRIBUTOR":
        return None
    if warehouse_id:
        wh = db.session.get(Organization, warehouse_id)
        if not wh or wh.parent_id != org.id or wh.kind != "WAREHOUSE":
            raise ValueError("Invalid warehouse")
        return wh
    return get_or_create_warehouse(org.id)


def stock_location_for_org(org: Organization, warehouse_id: int | None = None) -> tuple[int, int]:
    """Return (distributor_id, facility_id) where purchased stock is stored."""
    if org.kind == "DISTRIBUTOR":
        wh = resolve_warehouse(org, warehouse_id)
        return org.id, wh.id
    if org.kind == "WAREHOUSE":
        if not org.parent_id:
            raise ValueError("Warehouse not linked to a distributor")
        return org.parent_id, org.id
    if not org.parent_id:
        raise ValueError("Organization not linked to a distributor")
    return org.parent_id, org.id


def _find_purchase_batch(
    distributor_id: int,
    item_id: int,
    batch_no: str,
    warehouse_id: int | None = None,
) -> ConsignmentBatch | None:
    if warehouse_id:
        return ConsignmentBatch.query.filter_by(
            distributor_id=distributor_id,
            facility_id=warehouse_id,
            item_id=item_id,
            batch_no=batch_no,
        ).first()
    for wh in warehouses(distributor_id) or [get_or_create_warehouse(distributor_id)]:
        batch = ConsignmentBatch.query.filter_by(
            distributor_id=distributor_id,
            facility_id=wh.id,
            item_id=item_id,
            batch_no=batch_no,
        ).first()
        if batch:
            return batch
    return None


def warehouse_stock_summary(distributor_id: int) -> list[dict]:
    rows = []
    for wh in warehouses(distributor_id) or [get_or_create_warehouse(distributor_id)]:
        sku_count = (
            db.session.query(func.count(func.distinct(ConsignmentBatch.item_id)))
            .filter_by(distributor_id=distributor_id, facility_id=wh.id)
            .filter(ConsignmentBatch.qty_on_hand > 0)
            .scalar()
        )
        totals = (
            db.session.query(
                func.coalesce(func.sum(ConsignmentBatch.qty_on_hand), 0),
                func.coalesce(func.sum(ConsignmentBatch.qty_on_hand * ConsignmentBatch.cost_rate), 0),
            )
            .filter_by(distributor_id=distributor_id, facility_id=wh.id)
            .first()
        )
        rows.append({
            "warehouse_id": wh.id,
            "warehouse_code": wh.code,
            "warehouse_name": wh.name,
            "sku_count": int(sku_count or 0),
            "total_qty": float(totals[0] or 0),
            "stock_value": float(totals[1] or 0),
        })
    return rows


def _allocate_from_batches(item_id: int, facility_id: int, qty: Decimal) -> list[tuple[ConsignmentBatch, Decimal]]:
    batches = fefo_batches(item_id, facility_id, qty)
    allocations: list[tuple[ConsignmentBatch, Decimal]] = []
    remaining = qty
    for batch in batches:
        if remaining <= 0:
            break
        take = min(Decimal(str(batch.available_qty)), remaining)
        allocations.append((batch, take))
        remaining -= take
    if remaining > 0:
        raise ValueError(f"Insufficient warehouse stock for item {item_id}")
    return allocations


def receive_purchase_stock(
    org: Organization,
    reference: str,
    lines: list[dict],
    note: str = "",
    warehouse_id: int | None = None,
) -> None:
    """GRN: create/update batches when a purchase bill is posted."""
    distributor_id, facility_id = stock_location_for_org(org, warehouse_id)
    for row in lines:
        item = db.session.get(Item, row["item_id"])
        if not item:
            raise ValueError(f"Item {row['item_id']} not found")
        batch = ConsignmentBatch.query.filter_by(
            distributor_id=distributor_id,
            facility_id=facility_id,
            item_id=item.id,
            batch_no=row["batch_no"],
        ).first()
        qty = Decimal(str(row["qty"]))
        mrp = Decimal(str(row.get("mrp", item.mrp or 0)))
        ptr = Decimal(str(row.get("ptr", item.ptr or 0)))
        cost = Decimal(str(row.get("cost_rate", row.get("rate", ptr * Decimal("0.85")))))
        rack = (row.get("rack") or "").strip().upper() or None
        if batch:
            batch.qty_on_hand = Decimal(str(batch.qty_on_hand)) + qty
            if rack:
                batch.rack = rack
        else:
            batch = ConsignmentBatch(
                distributor_id=distributor_id,
                facility_id=facility_id,
                item_id=item.id,
                batch_no=row["batch_no"],
                expiry=row["expiry"],
                mrp=mrp,
                ptr=ptr,
                cost_rate=cost,
                qty_on_hand=qty,
                rack=rack,
            )
            db.session.add(batch)
            db.session.flush()
        _log_movement(batch, "PURCHASE", qty, reference, note)


def return_purchase_stock(
    org: Organization,
    reference: str,
    lines: list[dict],
    note: str = "",
    warehouse_id: int | None = None,
) -> None:
    """Deduct stock when goods are returned to a supplier."""
    distributor_id, _ = stock_location_for_org(org, warehouse_id)
    for row in lines:
        item = db.session.get(Item, row["item_id"])
        if not item:
            raise ValueError(f"Item {row['item_id']} not found")
        qty = Decimal(str(row["qty"]))
        batch = _find_purchase_batch(distributor_id, item.id, row["batch_no"], warehouse_id)
        if not batch or Decimal(str(batch.qty_on_hand)) < qty:
            raise ValueError(f"Insufficient stock to return {item.name} batch {row['batch_no']}")
        issue_stock(batch, qty, reference, movement="PURCHASE_RETURN")


def issue_stock(batch: ConsignmentBatch, qty: Decimal, reference: str, movement: str = "SALE") -> None:
    if Decimal(str(batch.available_qty)) < qty:
        raise ValueError("Batch stock insufficient")
    batch.qty_on_hand = Decimal(str(batch.qty_on_hand)) - qty
    _log_movement(batch, movement, -qty, reference)


def build_restock_shipment_lines(distributor_id: int, facility_id: int) -> list[dict]:
    """Build consignment lines from restock alerts, sourcing batches from warehouse."""
    alerts = restock_alerts(distributor_id, facility_id=facility_id)
    if not alerts:
        return []
    wh_list = warehouses(distributor_id) or [get_or_create_warehouse(distributor_id)]
    lines: list[dict] = []
    for alert in alerts:
        item = db.session.get(Item, alert["item_id"])
        qty = Decimal(str(alert["suggest_qty"]))
        allocations = None
        for warehouse in wh_list:
            try:
                allocations = _allocate_from_batches(item.id, warehouse.id, qty)
                break
            except ValueError:
                continue
        if not allocations:
            continue
        for batch, take in allocations:
            if take <= 0:
                continue
            lines.append({
                "item_id": item.id,
                "batch_no": batch.batch_no,
                "expiry": batch.expiry,
                "mrp": batch.mrp,
                "ptr": batch.ptr,
                "cost_rate": batch.cost_rate,
                "qty": take,
                "_source_batch_id": batch.id,
            })
    return lines


def receive_consignment(
    distributor: Organization,
    facility: Organization,
    lines: list[dict],
    note: str = "",
    from_warehouse: bool = False,
) -> ConsignmentShipment:
    shipment = ConsignmentShipment(
        number=next_shipment_number(distributor.id),
        distributor_id=distributor.id,
        facility_id=facility.id,
        note=note,
        status="RECEIVED",
    )
    db.session.add(shipment)
    db.session.flush()

    warehouse = get_or_create_warehouse(distributor.id) if from_warehouse else None

    for row in lines:
        item = db.session.get(Item, row["item_id"])
        if not item:
            raise ValueError(f"Item {row['item_id']} not found")
        qty = Decimal(str(row["qty"]))
        mrp = Decimal(str(row["mrp"]))
        ptr = Decimal(str(row["ptr"]))
        cost_rate = Decimal(str(row["cost_rate"]))

        if warehouse:
            source_id = row.get("_source_batch_id")
            if source_id:
                wh_batch = db.session.get(ConsignmentBatch, source_id)
                if not wh_batch or wh_batch.facility_id != warehouse.id:
                    raise ValueError(f"Invalid warehouse batch for item {item.id}")
            else:
                wh_batch = ConsignmentBatch.query.filter_by(
                    distributor_id=distributor.id,
                    facility_id=warehouse.id,
                    item_id=item.id,
                    batch_no=row["batch_no"],
                ).first()
                if not wh_batch:
                    raise ValueError(f"No warehouse stock for {item.name} batch {row['batch_no']}")
            issue_stock(wh_batch, qty, shipment.number, movement="TRANSFER_OUT")

        batch = ConsignmentBatch.query.filter_by(
            distributor_id=distributor.id,
            facility_id=facility.id,
            item_id=item.id,
            batch_no=row["batch_no"],
        ).first()
        if batch:
            batch.qty_on_hand = Decimal(str(batch.qty_on_hand)) + qty
        else:
            batch = ConsignmentBatch(
                distributor_id=distributor.id,
                facility_id=facility.id,
                item_id=item.id,
                batch_no=row["batch_no"],
                expiry=row["expiry"],
                mrp=mrp,
                ptr=ptr,
                cost_rate=cost_rate,
                qty_on_hand=qty,
            )
            db.session.add(batch)
            db.session.flush()
        _log_movement(batch, "CONSIGNMENT_IN", qty, shipment.number, note)
        db.session.add(
            ConsignmentShipmentLine(
                shipment_id=shipment.id,
                item_id=item.id,
                batch_no=row["batch_no"],
                expiry=row["expiry"],
                mrp=mrp,
                ptr=ptr,
                cost_rate=cost_rate,
                qty=qty,
            )
        )
    return shipment


def live_stock_snapshot(distributor_id: int | None = None, facility_id: int | None = None) -> list[dict]:
    q = (
        db.session.query(
            Organization.id.label("facility_id"),
            Organization.name.label("facility_name"),
            Organization.kind.label("facility_kind"),
            Item.id.label("item_id"),
            Item.code.label("item_code"),
            Item.name.label("item_name"),
            func.coalesce(func.sum(ConsignmentBatch.qty_on_hand), 0).label("qty"),
            func.coalesce(func.sum(ConsignmentBatch.qty_on_hand * ConsignmentBatch.cost_rate), 0).label("value"),
        )
        .join(ConsignmentBatch, ConsignmentBatch.facility_id == Organization.id)
        .join(Item, Item.id == ConsignmentBatch.item_id)
        .filter(Organization.kind.notin_(["DISTRIBUTOR", "WAREHOUSE"]))
        .group_by(Organization.id, Organization.name, Organization.kind, Item.id, Item.code, Item.name)
        .having(func.coalesce(func.sum(ConsignmentBatch.qty_on_hand), 0) > 0)
    )
    if distributor_id:
        q = q.filter(ConsignmentBatch.distributor_id == distributor_id)
    if facility_id:
        q = q.filter(ConsignmentBatch.facility_id == facility_id)
    rows = q.order_by(Organization.name, Item.name).all()
    return [
        {
            "facility_id": r.facility_id,
            "facility_name": r.facility_name,
            "facility_kind": r.facility_kind,
            "item_id": r.item_id,
            "item_code": r.item_code,
            "item_name": r.item_name,
            "qty": float(r.qty),
            "value": float(r.value),
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        for r in rows
    ]


def facility_stock_summary(distributor_id: int) -> list[dict]:
    q = (
        db.session.query(
            Organization.id,
            Organization.name,
            Organization.kind,
            func.count(func.distinct(ConsignmentBatch.item_id)).label("sku_count"),
            func.coalesce(func.sum(ConsignmentBatch.qty_on_hand), 0).label("total_qty"),
            func.coalesce(func.sum(ConsignmentBatch.qty_on_hand * ConsignmentBatch.cost_rate), 0).label("stock_value"),
        )
        .join(ConsignmentBatch, ConsignmentBatch.facility_id == Organization.id)
        .filter(ConsignmentBatch.distributor_id == distributor_id)
        .filter(Organization.kind.notin_(["DISTRIBUTOR", "WAREHOUSE"]))
        .group_by(Organization.id, Organization.name, Organization.kind)
        .order_by(Organization.name)
    )
    return [
        {
            "facility_id": r.id,
            "facility_name": r.name,
            "facility_kind": r.kind,
            "sku_count": int(r.sku_count or 0),
            "total_qty": float(r.total_qty or 0),
            "stock_value": float(r.stock_value or 0),
        }
        for r in q.all()
    ]


def upsert_stock_limit(facility_id: int, item_id: int, min_qty: Decimal, max_qty: Decimal) -> FacilityStockLimit:
    if min_qty < 0 or max_qty < 0:
        raise ValueError("Min and max must be non-negative")
    if max_qty > 0 and min_qty > max_qty:
        raise ValueError("Min cannot exceed max")
    row = FacilityStockLimit.query.filter_by(facility_id=facility_id, item_id=item_id).first()
    if row:
        row.min_qty = min_qty
        row.max_qty = max_qty
    else:
        row = FacilityStockLimit(facility_id=facility_id, item_id=item_id, min_qty=min_qty, max_qty=max_qty)
        db.session.add(row)
    return row


def stock_limits_for_facility(facility_id: int) -> list[FacilityStockLimit]:
    return (
        FacilityStockLimit.query.filter_by(facility_id=facility_id)
        .join(Item)
        .order_by(Item.name)
        .all()
    )


def _stock_status(qty: float, min_qty: float, max_qty: float) -> str:
    if min_qty > 0 and qty <= min_qty:
        return "LOW"
    if max_qty > 0 and qty >= max_qty:
        return "FULL"
    return "OK"


def restock_alerts(distributor_id: int, facility_id: int | None = None) -> list[dict]:
    """Items at or below min stock — with suggested restock qty to reach max."""
    facilities = Organization.query.filter_by(parent_id=distributor_id).filter(
        Organization.kind.notin_(["WAREHOUSE"])
    )
    if facility_id:
        facilities = facilities.filter_by(id=facility_id)
    facility_ids = [f.id for f in facilities.all()]
    if not facility_ids:
        return []

    limits = FacilityStockLimit.query.filter(FacilityStockLimit.facility_id.in_(facility_ids)).all()
    alerts: list[dict] = []
    for lim in limits:
        min_q = float(lim.min_qty or 0)
        max_q = float(lim.max_qty or 0)
        if min_q <= 0:
            continue
        qty = float(stock_on_hand(lim.item_id, lim.facility_id))
        if qty <= min_q:
            suggest = max(max_q - qty, 0) if max_q > 0 else min_q - qty + min_q
            if suggest <= 0 and max_q > qty:
                suggest = max_q - qty
            if suggest <= 0:
                suggest = min_q
            alerts.append({
                "facility_id": lim.facility_id,
                "facility_name": lim.facility.name,
                "facility_kind": lim.facility.kind,
                "item_id": lim.item_id,
                "item_code": lim.item.code,
                "item_name": lim.item.name,
                "qty": qty,
                "min_qty": min_q,
                "max_qty": max_q,
                "suggest_qty": round(suggest, 3),
                "status": "LOW",
            })
    alerts.sort(key=lambda r: (r["facility_name"], r["qty"] - r["min_qty"]))
    return alerts


def stock_with_limits(distributor_id: int | None = None, facility_id: int | None = None) -> list[dict]:
    """Live stock enriched with per-facility min/max and status."""
    rows = live_stock_snapshot(distributor_id=distributor_id, facility_id=facility_id)
    limit_map: dict[tuple[int, int], FacilityStockLimit] = {}
    q = FacilityStockLimit.query
    if facility_id:
        q = q.filter_by(facility_id=facility_id)
    elif distributor_id:
        fac_ids = [f.id for f in customer_facilities(distributor_id)]
        if fac_ids:
            q = q.filter(FacilityStockLimit.facility_id.in_(fac_ids))
    for lim in q.all():
        limit_map[(lim.facility_id, lim.item_id)] = lim

    enriched = []
    seen: set[tuple[int, int]] = set()
    for r in rows:
        key = (r["facility_id"], r["item_id"])
        seen.add(key)
        lim = limit_map.get(key)
        min_q = float(lim.min_qty) if lim else None
        max_q = float(lim.max_qty) if lim else None
        status = _stock_status(r["qty"], min_q or 0, max_q or 0) if lim else None
        enriched.append({**r, "min_qty": min_q, "max_qty": max_q, "status": status})

    for (fid, iid), lim in limit_map.items():
        if (fid, iid) in seen:
            continue
        qty = float(stock_on_hand(iid, fid))
        if facility_id and fid != facility_id:
            continue
        if distributor_id and lim.facility.parent_id != distributor_id:
            continue
        enriched.append({
            "facility_id": fid,
            "facility_name": lim.facility.name,
            "facility_kind": lim.facility.kind,
            "item_id": iid,
            "item_code": lim.item.code,
            "item_name": lim.item.name,
            "qty": qty,
            "value": 0.0,
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "min_qty": float(lim.min_qty),
            "max_qty": float(lim.max_qty),
            "status": _stock_status(qty, float(lim.min_qty), float(lim.max_qty)),
        })
    enriched.sort(key=lambda r: (r["facility_name"], r["item_name"]))
    return enriched


def warehouse_batches(warehouse_id: int) -> list[dict]:
    batches = (
        ConsignmentBatch.query.filter_by(facility_id=warehouse_id)
        .filter(ConsignmentBatch.qty_on_hand > 0)
        .order_by(ConsignmentBatch.expiry.asc(), ConsignmentBatch.batch_no.asc())
        .all()
    )
    return [
        {
            "batch_id": b.id,
            "item_id": b.item_id,
            "item_code": b.item.code,
            "item_name": b.item.name,
            "batch_no": b.batch_no,
            "expiry": b.expiry.isoformat(),
            "mrp": float(b.mrp),
            "ptr": float(b.ptr),
            "cost_rate": float(b.cost_rate),
            "qty": float(b.qty_on_hand),
        }
        for b in batches
    ]


def transfer_warehouse_stock(
    distributor: Organization,
    from_warehouse: Organization,
    to_warehouse: Organization,
    lines: list[dict],
    note: str = "",
) -> WarehouseTransfer:
    if from_warehouse.id == to_warehouse.id:
        raise ValueError("Source and destination warehouse must differ")
    if from_warehouse.kind != "WAREHOUSE" or to_warehouse.kind != "WAREHOUSE":
        raise ValueError("Both locations must be warehouses")
    if from_warehouse.parent_id != distributor.id or to_warehouse.parent_id != distributor.id:
        raise ValueError("Invalid warehouse for distributor")

    xfer = WarehouseTransfer(
        number=next_transfer_number(distributor.id),
        distributor_id=distributor.id,
        from_warehouse_id=from_warehouse.id,
        to_warehouse_id=to_warehouse.id,
        note=note,
    )
    db.session.add(xfer)
    db.session.flush()

    for row in lines:
        item = db.session.get(Item, row["item_id"])
        if not item:
            raise ValueError(f"Item {row['item_id']} not found")
        qty = Decimal(str(row["qty"]))
        if qty <= 0:
            continue

        source = ConsignmentBatch.query.filter_by(
            distributor_id=distributor.id,
            facility_id=from_warehouse.id,
            item_id=item.id,
            batch_no=row["batch_no"],
        ).first()
        if not source or Decimal(str(source.qty_on_hand)) < qty:
            raise ValueError(f"Insufficient stock for {item.name} batch {row['batch_no']} at {from_warehouse.code}")

        issue_stock(source, qty, xfer.number, movement="TRANSFER_OUT")

        mrp = Decimal(str(row.get("mrp", source.mrp)))
        ptr = Decimal(str(row.get("ptr", source.ptr)))
        cost_rate = Decimal(str(row.get("cost_rate", source.cost_rate)))
        expiry = row.get("expiry", source.expiry)
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)

        dest = ConsignmentBatch.query.filter_by(
            distributor_id=distributor.id,
            facility_id=to_warehouse.id,
            item_id=item.id,
            batch_no=row["batch_no"],
        ).first()
        if dest:
            dest.qty_on_hand = Decimal(str(dest.qty_on_hand)) + qty
        else:
            dest = ConsignmentBatch(
                distributor_id=distributor.id,
                facility_id=to_warehouse.id,
                item_id=item.id,
                batch_no=row["batch_no"],
                expiry=expiry,
                mrp=mrp,
                ptr=ptr,
                cost_rate=cost_rate,
                qty_on_hand=qty,
            )
            db.session.add(dest)
            db.session.flush()
        _log_movement(dest, "TRANSFER_IN", qty, xfer.number, note)

        db.session.add(
            WarehouseTransferLine(
                transfer_id=xfer.id,
                item_id=item.id,
                batch_no=row["batch_no"],
                expiry=expiry,
                mrp=mrp,
                ptr=ptr,
                cost_rate=cost_rate,
                qty=qty,
            )
        )
    return xfer


def near_expiry_batches(distributor_id: int, within_days: int = 60) -> list[ConsignmentBatch]:
    cutoff = date.today().toordinal() + within_days
    from datetime import date as dt

    limit_date = dt.fromordinal(cutoff)
    return (
        ConsignmentBatch.query.filter_by(distributor_id=distributor_id)
        .filter(ConsignmentBatch.expiry <= limit_date, ConsignmentBatch.qty_on_hand > 0)
        .order_by(ConsignmentBatch.expiry)
        .limit(50)
        .all()
    )