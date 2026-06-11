import json
from decimal import Decimal
from urllib.parse import quote

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Bill, Item, Patient, PartyLedger, RetailCustomer
from ..services import billing as billing_service
from ..services import audit as audit_service
from ..services import einvoice as einvoice_service
from ..services import eway as eway_service
from ..services import integrations as integration_service
from ..services.invoice_qr import invoice_qr_payload
from ..services import customers as customer_service
from ..services import inventory as inventory_service
from ..services import permissions as perm_service
from ..services import promotions as promo_service

bp = Blueprint("billing", __name__, url_prefix="/billing")


@bp.before_request
def _require_billing():
    return perm_service.check_permission("billing")


def _default_bill_type(org_kind: str) -> str:
    return {"RETAIL": "RETAIL", "HOSPITAL": "HOSPITAL", "INSTITUTIONAL": "INSTITUTIONAL"}.get(org_kind, "RETAIL")


def _whatsapp_invoice_text(bill: Bill) -> str:
    lines = [
        f"Infivita PharmaConnect — Invoice {bill.number}",
        f"Date: {bill.billed_on.strftime('%d-%b-%Y')}",
        f"Customer: {bill.customer_name}",
        "",
    ]
    for ln in bill.lines:
        lines.append(f"{ln.item.name} x{ln.qty} = ₹{ln.line_total}")
    lines.extend(["", f"Grand Total: ₹{bill.grand_total}", f"Payment: {bill.payment_mode}"])
    return "\n".join(lines)


@bp.route("/")
@login_required
def index():
    org = current_user.organization
    if current_user.is_distributor:
        flash("Billing is done at facility level", "error")
        return redirect(url_for("dashboard.home"))
    bills = Bill.query.filter_by(facility_id=org.id).order_by(Bill.billed_on.desc()).limit(50).all()
    return render_template("billing_list.html", bills=bills)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    org = current_user.organization
    if current_user.is_distributor:
        flash("Login as a facility user to bill", "error")
        return redirect(url_for("dashboard.home"))

    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()
    patients = Patient.query.filter_by(facility_id=org.id).order_by(Patient.name).all()
    bill_type = request.args.get("type") or _default_bill_type(org.kind)

    if request.method == "POST":
        try:
            lines = json.loads(request.form.get("lines_json", "[]"))
            if not lines:
                raise ValueError("Add at least one item")
            bill = billing_service.create_bill(
                org,
                bill_type=request.form.get("bill_type", bill_type),
                lines=lines,
                customer_name=request.form.get("customer_name", "Walk-in"),
                customer_gstin=request.form.get("customer_gstin") or None,
                payment_mode=request.form.get("payment_mode", "CASH"),
                doctor_name=request.form.get("doctor_name") or None,
                patient_id=int(request.form["patient_id"]) if request.form.get("patient_id") else None,
                retail_customer_id=int(request.form["retail_customer_id"]) if request.form.get("retail_customer_id") else None,
                discount=Decimal(request.form.get("discount") or 0),
                order_ref=request.form.get("order_ref") or None,
                loyalty_redeem=int(request.form.get("loyalty_redeem") or 0),
                payment_ref=request.form.get("payment_ref") or None,
            )
            audit_service.log_action(
                org.id, "BILL_POST", user_id=current_user.id,
                entity_type="BILL", entity_ref=bill.number,
                detail=f"{bill.grand_total} {bill.payment_mode}",
            )
            db.session.commit()
            flash(f"Bill {bill.number} posted", "success")
            return redirect(url_for("billing.view", bid=bill.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")

    stock_map = {i.id: float(inventory_service.stock_on_hand(i.id, org.id)) for i in items}
    retail_customers = RetailCustomer.query.filter_by(facility_id=org.id).order_by(RetailCustomer.name).all()
    institutional_parties = (
        PartyLedger.query.filter_by(org_id=org.id)
        .filter(PartyLedger.party_gstin.isnot(None))
        .order_by(PartyLedger.party_name)
        .all()
    )
    favourites = customer_service.facility_favourites(org.id)
    schemes = promo_service.active_schemes(org.id)
    return render_template(
        "billing_new.html",
        items=items,
        patients=patients,
        retail_customers=retail_customers,
        institutional_parties=institutional_parties,
        favourites=favourites,
        schemes=schemes,
        bill_type=bill_type,
        stock_map=stock_map,
        org=org,
    )


@bp.route("/<int:bid>")
@login_required
def view(bid: int):
    bill = db.session.get(Bill, bid)
    if not bill:
        flash("Bill not found", "error")
        return redirect(url_for("billing.index"))
    if not current_user.is_distributor and bill.facility_id != current_user.org_id:
        flash("Access denied", "error")
        return redirect(url_for("billing.index"))
    wa_text = _whatsapp_invoice_text(bill)
    return render_template(
        "billing_view.html",
        bill=bill,
        can_return=not current_user.is_distributor,
        qr_payload=invoice_qr_payload(bill),
        whatsapp_url=f"https://wa.me/?text={quote(wa_text)}",
        eway_required=eway_service.eway_required(bill),
    )


@bp.route("/<int:bid>/eway", methods=["POST"])
@login_required
def set_eway(bid: int):
    bill = db.session.get(Bill, bid)
    if not bill or bill.facility_id != current_user.org_id:
        flash("Bill not found", "error")
        return redirect(url_for("billing.index"))
    bill.eway_no = request.form.get("eway_no", "").strip() or None
    db.session.commit()
    flash("E-way number saved", "success")
    return redirect(url_for("billing.view", bid=bid))


@bp.route("/<int:bid>/generate-irn", methods=["POST"])
@login_required
def generate_irn(bid: int):
    bill = db.session.get(Bill, bid)
    if not bill or bill.facility_id != current_user.org_id:
        flash("Bill not found", "error")
        return redirect(url_for("billing.index"))
    try:
        irn = integration_service.generate_irn(bill)
        audit_service.log_action(
            bill.facility_id, "IRN_GENERATE", user_id=current_user.id,
            entity_type="BILL", entity_ref=bill.number, detail=irn,
        )
        db.session.commit()
        flash(f"IRN generated: {irn}", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("billing.view", bid=bid))


@bp.route("/<int:bid>/einvoice-export")
@login_required
def einvoice_export(bid: int):
    bill = db.session.get(Bill, bid)
    if not bill or (not current_user.is_distributor and bill.facility_id != current_user.org_id):
        flash("Bill not found", "error")
        return redirect(url_for("billing.index"))
    content = einvoice_service.einvoice_json(bill)
    filename = f"EINV_{bill.number.replace('/', '-')}.json"
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/<int:bid>/eway-export")
@login_required
def eway_export(bid: int):
    bill = db.session.get(Bill, bid)
    if not bill or (not current_user.is_distributor and bill.facility_id != current_user.org_id):
        flash("Bill not found", "error")
        return redirect(url_for("billing.index"))
    content = eway_service.eway_json(bill)
    filename = f"EWAY_{bill.number.replace('/', '-')}.json"
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/pos")
@login_required
def pos():
    """Mobile-friendly POS shortcut."""
    return redirect(url_for("billing.new", type="RETAIL"))