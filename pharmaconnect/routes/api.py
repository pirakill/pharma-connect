from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from .. import db
from ..models import Item, Organization, RetailCustomer
from ..services import alerts as alerts_service
from ..services import customers as customer_service
from ..services import integrations as integration_service
from ..services import inventory as inventory_service
from ..services import permissions as perm_service

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.before_request
def _api_permissions():
    return perm_service.check_api_permission(request.endpoint)


@bp.route("/stock/live")
@login_required
def live_stock():
    org = current_user.organization
    if current_user.is_distributor:
        rows = inventory_service.stock_with_limits(distributor_id=org.id)
        facilities = inventory_service.facility_stock_summary(org.id)
        alerts = inventory_service.restock_alerts(org.id)
        return jsonify({"facilities": facilities, "stock": rows, "restock_alerts": alerts})
    rows = inventory_service.stock_with_limits(facility_id=org.id)
    alerts = inventory_service.restock_alerts(org.parent_id, facility_id=org.id)
    return jsonify({"facilities": [], "stock": rows, "restock_alerts": alerts})


@bp.route("/items/search")
@login_required
def search_items():
    q = request.args.get("q", "").strip()
    facility_id = current_user.org_id if not current_user.is_distributor else int(request.args.get("facility_id", 0))
    qry = Item.query.filter_by(is_active=True)
    if q:
        qry = qry.filter(Item.name.ilike(f"%{q}%"))
    rows = qry.limit(30).all()
    return jsonify([
        {
            "id": i.id,
            "code": i.code,
            "name": i.name,
            "mrp": float(i.mrp or 0),
            "ptr": float(i.ptr or 0),
            "barcode": i.barcode,
            "in_stock": float(inventory_service.stock_on_hand(i.id, facility_id)) if facility_id else 0,
        }
        for i in rows
    ])


@bp.route("/items/barcode/<code>")
@login_required
def barcode_lookup(code: str):
    facility_id = current_user.org_id if not current_user.is_distributor else int(request.args.get("facility_id", 0))
    item = Item.query.filter_by(barcode=code, is_active=True).first()
    if not item:
        item = Item.query.filter(Item.code == code, Item.is_active.is_(True)).first()
    if not item:
        return jsonify({"error": "not found"}), 404
    if item.ptr:
        cost = float((Decimal(str(item.ptr)) * Decimal("0.85")).quantize(Decimal("0.01")))
    else:
        cost = float(Decimal(str(item.mrp or 0)) * Decimal("0.85"))
    return jsonify({
        "id": item.id,
        "code": item.code,
        "name": item.name,
        "barcode": item.barcode,
        "mrp": float(item.mrp or 0),
        "ptr": float(item.ptr or 0),
        "rate": cost,
        "in_stock": float(inventory_service.stock_on_hand(item.id, facility_id)) if facility_id else 0,
    })


@bp.route("/warehouses/<int:wh_id>/batches")
@login_required
def warehouse_batches(wh_id: int):
    wh = db.session.get(Organization, wh_id)
    if not wh or wh.kind != "WAREHOUSE":
        return jsonify({"error": "not found"}), 404
    if current_user.is_distributor:
        if wh.parent_id != current_user.org_id:
            return jsonify({"error": "forbidden"}), 403
    elif wh.parent_id != current_user.org_id:
        return jsonify({"error": "forbidden"}), 403
    return jsonify(inventory_service.warehouse_batches(wh_id))


@bp.route("/customers/<int:cid>/billing-context")
@login_required
def customer_billing_context(cid: int):
    c = db.session.get(RetailCustomer, cid)
    if not c:
        return jsonify({"error": "not found"}), 404
    from ..services.credit import retail_credit_status

    credit = retail_credit_status(cid)
    return jsonify({
        "id": c.id, "name": c.name, "gstin": c.gstin,
        "outstanding": float(c.outstanding or 0),
        "credit_days": int(c.credit_days or 0),
        "credit_limit": float(c.credit_limit or 0),
        "overdue": credit.get("overdue", 0),
        "oldest_due": credit.get("oldest_due"),
        "loyalty_points": int(c.loyalty_points or 0),
        "regular": [{"item_id": r.item_id, "name": r.item.name, "qty": float(r.typical_qty)} for r in customer_service.regular_meds_list(cid)],
        "frequent": customer_service.frequent_items(cid),
        "history": customer_service.customer_history(cid, limit=5),
        "open_invoices": credit.get("open_invoices", []),
    })


@bp.route("/payments/verify", methods=["POST"])
@login_required
def verify_payment():
    data = request.get_json(silent=True) or {}
    gateway = (data.get("gateway") or "").lower()
    org_id = current_user.org_id
    try:
        if gateway == "razorpay":
            ok = integration_service.verify_razorpay_payment(
                org_id, data.get("payment_id", ""), data.get("signature", ""),
            )
        elif gateway == "phonepe":
            ok = integration_service.verify_phonepe_payment(
                org_id, data.get("merchant_txn_id", ""), data.get("checksum", ""),
            )
        else:
            return jsonify({"error": "gateway must be razorpay or phonepe"}), 400
        return jsonify({"verified": ok})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/health")
def health():
    return jsonify({"status": "ok", "app": "Infivita PharmaConnect"})


@bp.route("/ready")
def ready():
    try:
        db.session.execute(db.text("SELECT 1"))
        return jsonify({"status": "ready", "database": "ok"})
    except Exception as exc:
        return jsonify({"status": "not_ready", "database": str(exc)}), 503


@bp.route("/scf/webhook/<lender_code>", methods=["POST"])
def scf_webhook(lender_code: str):
    from ..services import scf as scf_service

    secret = request.headers.get("X-Webhook-Secret") or request.args.get("secret", "")
    payload = request.get_json(silent=True) or {}
    try:
        result = scf_service.process_lender_webhook(lender_code, payload, secret or None)
        db.session.commit()
        return jsonify({"ok": True, **result})
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(exc)}), 400


@bp.route("/cron/alerts", methods=["POST"])
def cron_alerts():
    secret = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    expected = current_app.config.get("CRON_SECRET") or ""
    if not expected or secret != expected:
        return jsonify({"error": "unauthorized"}), 401
    force = request.args.get("force") == "1" or (request.get_json(silent=True) or {}).get("force")
    result = alerts_service.run_scheduled_alerts(force=bool(force))
    return jsonify(result)