from datetime import datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import ConsignmentBatch, ConsignmentShipment, Item, Organization, WarehouseTransfer
from ..services import inventory as inventory_service
from ..services import permissions as perm_service

bp = Blueprint("inventory", __name__, url_prefix="/inventory")

_INVENTORY_VIEW_ENDPOINTS = {
    "inventory.live",
    "inventory.restock",
    "inventory.consignments",
    "inventory.consignment_challan",
    "inventory.transfers",
    "inventory.transfer_challan",
    "inventory.expired",
}


@bp.before_request
def _require_inventory_access():
    if not current_user.is_authenticated:
        return None
    endpoint = request.endpoint or ""
    if endpoint in _INVENTORY_VIEW_ENDPOINTS:
        if perm_service.has_permission(current_user, "inventory") or perm_service.has_permission(current_user, "inventory_view"):
            return None
        flash("You do not have permission to view inventory", "error")
        return redirect(url_for("dashboard.home"))
    if not perm_service.has_permission(current_user, "inventory"):
        flash("You do not have permission for inventory management", "error")
        return redirect(url_for("dashboard.home"))
    return None


@bp.route("/live")
@login_required
def live():
    org = current_user.organization
    if current_user.is_distributor:
        rows = inventory_service.stock_with_limits(distributor_id=org.id)
        facilities = inventory_service.facility_stock_summary(org.id)
        return render_template("live_stock.html", rows=rows, facilities=facilities, is_distributor=True)
    rows = inventory_service.stock_with_limits(facility_id=org.id)
    return render_template("live_stock.html", rows=rows, facilities=[], is_distributor=False)


@bp.route("/limits", methods=["GET", "POST"])
@login_required
def limits():
    if not current_user.is_distributor:
        flash("Only Infivita distributor can set stock limits", "error")
        return redirect(url_for("dashboard.home"))

    facilities = inventory_service.customer_facilities(current_user.org_id, active_only=True)
    facility_id = int(request.args.get("facility_id") or request.form.get("facility_id") or (facilities[0].id if facilities else 0))
    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()

    if request.method == "POST":
        facility = db.session.get(Organization, facility_id)
        if not facility or facility.parent_id != current_user.org_id:
            flash("Invalid facility", "error")
            return redirect(url_for("inventory.limits"))

        try:
            for item in items:
                min_val = request.form.get(f"min_{item.id}", "").strip()
                max_val = request.form.get(f"max_{item.id}", "").strip()
                if not min_val and not max_val:
                    continue
                min_qty = Decimal(min_val or 0)
                max_qty = Decimal(max_val or 0)
                if min_qty == 0 and max_qty == 0:
                    continue
                inventory_service.upsert_stock_limit(facility.id, item.id, min_qty, max_qty)
            db.session.commit()
            flash(f"Stock limits saved for {facility.name}", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("inventory.limits", facility_id=facility_id))

    existing = {lim.item_id: lim for lim in inventory_service.stock_limits_for_facility(facility_id)}
    stock_map = {i.id: float(inventory_service.stock_on_hand(i.id, facility_id)) for i in items}
    return render_template(
        "stock_limits.html",
        facilities=facilities,
        facility_id=facility_id,
        items=items,
        existing=existing,
        stock_map=stock_map,
    )


@bp.route("/restock")
@login_required
def restock():
    org = current_user.organization
    if current_user.is_distributor:
        facility_id = request.args.get("facility_id", type=int)
        alerts = inventory_service.restock_alerts(org.id, facility_id=facility_id)
        facilities = inventory_service.customer_facilities(org.id)
        return render_template("restock_alerts.html", alerts=alerts, facilities=facilities,
                               facility_id=facility_id, is_distributor=True)
    alerts = inventory_service.restock_alerts(org.parent_id, facility_id=org.id)
    return render_template("restock_alerts.html", alerts=alerts, facilities=[], facility_id=org.id,
                           is_distributor=False)


@bp.route("/consignment/new", methods=["GET", "POST"])
@login_required
def consignment_new():
    if not current_user.is_distributor:
        flash("Only distributor users can ship consignment stock", "error")
        return redirect(url_for("dashboard.home"))

    facilities = inventory_service.customer_facilities(current_user.org_id, active_only=True)
    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()
    restock_facility_id = request.args.get("facility_id", type=int)
    from_restock = request.args.get("restock") == "1"
    prefill_lines: list[dict] = []
    if from_restock and restock_facility_id:
        raw_lines = inventory_service.build_restock_shipment_lines(
            current_user.org_id, restock_facility_id
        )
        prefill_lines = [
            {
                **{k: v for k, v in row.items() if not k.startswith("_")},
                "expiry": row["expiry"].isoformat(),
                "mrp": float(row["mrp"]),
                "ptr": float(row["ptr"]),
                "cost_rate": float(row["cost_rate"]),
                "qty": float(row["qty"]),
                "_source_batch_id": row.get("_source_batch_id"),
            }
            for row in raw_lines
        ]

    if request.method == "POST":
        facility_id = int(request.form["facility_id"])
        facility = db.session.get(Organization, facility_id)
        if not facility or facility.parent_id != current_user.org_id or facility.kind == "WAREHOUSE":
            flash("Invalid facility", "error")
            return redirect(url_for("inventory.consignment_new"))

        item_ids = request.form.getlist("item_id")
        lines = []
        source_ids = request.form.getlist("source_batch_id")
        for i, item_id in enumerate(item_ids):
            qty = request.form.getlist("qty")[i]
            if not qty or Decimal(qty) <= 0:
                continue
            line = {
                "item_id": int(item_id),
                "batch_no": request.form.getlist("batch_no")[i],
                "expiry": datetime.strptime(request.form.getlist("expiry")[i], "%Y-%m-%d").date(),
                "mrp": Decimal(request.form.getlist("mrp")[i] or 0),
                "ptr": Decimal(request.form.getlist("ptr")[i] or 0),
                "cost_rate": Decimal(request.form.getlist("cost_rate")[i] or 0),
                "qty": Decimal(qty),
            }
            if i < len(source_ids) and source_ids[i]:
                line["_source_batch_id"] = int(source_ids[i])
            lines.append(line)
        if not lines:
            flash("Add at least one line", "error")
            return redirect(url_for("inventory.consignment_new"))

        from_warehouse = request.form.get("from_warehouse") == "1"
        try:
            shipment = inventory_service.receive_consignment(
                current_user.organization,
                facility,
                lines,
                note=request.form.get("note", ""),
                from_warehouse=from_warehouse,
            )
            db.session.commit()
            flash(f"Consignment {shipment.number} posted to {facility.name}", "success")
            return redirect(url_for("inventory.consignment_challan", sid=shipment.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
            return redirect(url_for("inventory.consignment_new"))

    return render_template(
        "consignment_new.html",
        facilities=facilities,
        items=items,
        prefill_lines=prefill_lines,
        prefill_facility_id=restock_facility_id,
        from_restock=from_restock,
    )


@bp.route("/consignments")
@login_required
def consignments():
    if not current_user.is_distributor:
        flash("Only distributor can view consignment shipments", "error")
        return redirect(url_for("dashboard.home"))
    rows = (
        ConsignmentShipment.query.filter_by(distributor_id=current_user.org_id)
        .order_by(ConsignmentShipment.shipped_on.desc())
        .limit(50)
        .all()
    )
    return render_template("consignments_list.html", rows=rows)


@bp.route("/consignment/<int:sid>/challan")
@login_required
def consignment_challan(sid: int):
    shipment = db.session.get(ConsignmentShipment, sid)
    if not shipment:
        flash("Shipment not found", "error")
        return redirect(url_for("inventory.consignments"))
    if not current_user.is_distributor and shipment.facility_id != current_user.org_id:
        flash("Access denied", "error")
        return redirect(url_for("dashboard.home"))
    if current_user.is_distributor and shipment.distributor_id != current_user.org_id:
        flash("Access denied", "error")
        return redirect(url_for("inventory.consignments"))
    return render_template("consignment_challan.html", shipment=shipment)


@bp.route("/warehouses", methods=["GET", "POST"])
@login_required
def warehouses():
    if not current_user.is_distributor:
        flash("Only distributor can manage warehouses", "error")
        return redirect(url_for("dashboard.home"))

    if request.method == "POST":
        try:
            inventory_service.create_warehouse(
                current_user.org_id,
                code=request.form["code"],
                name=request.form["name"],
                address=request.form.get("address", ""),
            )
            db.session.commit()
            flash("Warehouse added", "success")
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("inventory.warehouses"))

    rows = inventory_service.warehouse_stock_summary(current_user.org_id)
    return render_template("warehouses.html", rows=rows)


@bp.route("/transfers")
@login_required
def transfers():
    if not current_user.is_distributor:
        flash("Only distributor can view warehouse transfers", "error")
        return redirect(url_for("dashboard.home"))
    rows = (
        WarehouseTransfer.query.filter_by(distributor_id=current_user.org_id)
        .order_by(WarehouseTransfer.transferred_on.desc())
        .limit(50)
        .all()
    )
    return render_template("warehouse_transfers_list.html", rows=rows)


@bp.route("/transfer", methods=["GET", "POST"])
@login_required
def transfer():
    if not current_user.is_distributor:
        flash("Only distributor can transfer warehouse stock", "error")
        return redirect(url_for("dashboard.home"))

    wh_list = inventory_service.warehouses(current_user.org_id) or [
        inventory_service.get_or_create_warehouse(current_user.org_id)
    ]
    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()

    if request.method == "POST":
        from_wh_id = int(request.form["from_warehouse_id"])
        to_wh_id = int(request.form["to_warehouse_id"])
        from_wh = db.session.get(Organization, from_wh_id)
        to_wh = db.session.get(Organization, to_wh_id)
        if not from_wh or not to_wh:
            flash("Invalid warehouse", "error")
            return redirect(url_for("inventory.transfer"))

        item_ids = request.form.getlist("item_id")
        lines = []
        for i, item_id in enumerate(item_ids):
            qty = request.form.getlist("qty")[i]
            if not qty or Decimal(qty) <= 0:
                continue
            lines.append({
                "item_id": int(item_id),
                "batch_no": request.form.getlist("batch_no")[i],
                "expiry": datetime.strptime(request.form.getlist("expiry")[i], "%Y-%m-%d").date(),
                "mrp": Decimal(request.form.getlist("mrp")[i] or 0),
                "ptr": Decimal(request.form.getlist("ptr")[i] or 0),
                "cost_rate": Decimal(request.form.getlist("cost_rate")[i] or 0),
                "qty": Decimal(qty),
            })
        if not lines:
            flash("Add at least one line", "error")
            return redirect(url_for("inventory.transfer"))

        try:
            xfer = inventory_service.transfer_warehouse_stock(
                current_user.organization,
                from_wh,
                to_wh,
                lines,
                note=request.form.get("note", ""),
            )
            db.session.commit()
            flash(f"Transfer {xfer.number} posted", "success")
            return redirect(url_for("inventory.transfer_challan", tid=xfer.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")

    return render_template(
        "warehouse_transfer.html",
        warehouses=wh_list,
        items=items,
    )


@bp.route("/transfer/<int:tid>/challan")
@login_required
def transfer_challan(tid: int):
    xfer = db.session.get(WarehouseTransfer, tid)
    if not xfer:
        flash("Transfer not found", "error")
        return redirect(url_for("inventory.transfers"))
    if not current_user.is_distributor or xfer.distributor_id != current_user.org_id:
        flash("Access denied", "error")
        return redirect(url_for("dashboard.home"))
    return render_template("transfer_challan.html", transfer=xfer)


@bp.route("/racks", methods=["GET", "POST"])
@login_required
def racks():
    org = current_user.organization
    if request.method == "POST":
        batch = db.session.get(ConsignmentBatch, int(request.form["batch_id"]))
        if not batch:
            flash("Batch not found", "error")
            return redirect(url_for("inventory.racks"))
        if current_user.is_distributor:
            if batch.distributor_id != org.id:
                flash("Access denied", "error")
                return redirect(url_for("inventory.racks"))
        elif batch.facility_id != org.id:
            flash("Access denied", "error")
            return redirect(url_for("inventory.racks"))
        inventory_service.set_batch_rack(batch, request.form.get("rack", ""))
        db.session.commit()
        flash("Rack updated", "success")
        return redirect(url_for("inventory.racks"))

    if current_user.is_distributor:
        rows = inventory_service.batches_with_racks(org.id, distributor_id=org.id)
    else:
        rows = inventory_service.batches_with_racks(org.id, facility_id=org.id)
    return render_template("racks.html", rows=rows, is_distributor=current_user.is_distributor)


@bp.route("/expired")
@login_required
def expired():
    org = current_user.organization
    if current_user.is_distributor:
        batches = inventory_service.expired_batches(org.id, distributor_id=org.id)
    else:
        batches = inventory_service.expired_batches(org.id)
    return render_template("expired_stock.html", batches=batches)


@bp.route("/batch/<int:bid>/write-off", methods=["POST"])
@login_required
def write_off(bid: int):
    batch = db.session.get(ConsignmentBatch, bid)
    if not batch:
        flash("Batch not found", "error")
        return redirect(url_for("inventory.expired"))
    org = current_user.organization
    if current_user.is_distributor:
        if batch.distributor_id != org.id:
            flash("Access denied", "error")
            return redirect(url_for("inventory.expired"))
    elif batch.facility_id != org.id:
        flash("Access denied", "error")
        return redirect(url_for("inventory.expired"))
    try:
        qty = Decimal(request.form.get("qty") or 0)
        inventory_service.write_off_batch(batch, qty, reason=request.form.get("reason", "Expired/damaged"))
        db.session.commit()
        flash(f"Wrote off {qty} units from batch {batch.batch_no}", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("inventory.expired"))