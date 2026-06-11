from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import AccountEntry, Organization
from ..services import accounting as accounting_service
from ..services import permissions as perm_service
from ..services import settlement as settlement_service
from ..seed import DISTRIBUTOR_NAME

bp = Blueprint("accounting", __name__, url_prefix="/accounting")


@bp.before_request
def _require_accounting():
    return perm_service.check_permission("accounting")


@bp.route("/")
@login_required
def index():
    org = current_user.organization
    if current_user.is_distributor:
        receivables = accounting_service.distributor_receivables(org.id)
        settlements = settlement_service.recent_settlements(distributor_id=org.id)
        facilities = Organization.query.filter_by(parent_id=org.id).all()
        return render_template(
            "accounting_distributor.html",
            receivables=receivables,
            settlements=settlements,
            facilities=facilities,
        )

    pnl = accounting_service.pnl_summary(org.id)
    receivables = accounting_service.receivables(org.id)
    distributor = Organization.query.filter_by(id=org.parent_id).first()
    consignment_payable = settlement_service.facility_payable_to_distributor(
        org.id, distributor.name if distributor else DISTRIBUTOR_NAME
    )
    settlements = settlement_service.recent_settlements(facility_id=org.id)
    entries = (
        AccountEntry.query.filter_by(org_id=org.id)
        .order_by(AccountEntry.ts.desc())
        .limit(40)
        .all()
    )
    return render_template(
        "accounting.html",
        pnl=pnl,
        receivables=receivables,
        entries=entries,
        consignment_payable=consignment_payable,
        distributor_name=distributor.name if distributor else DISTRIBUTOR_NAME,
        settlements=settlements,
    )


@bp.route("/payment", methods=["POST"])
@login_required
def payment():
    if current_user.is_distributor:
        flash("Use 'Record Receipt' for facility settlement payments", "error")
        return redirect(url_for("accounting.index"))
    amount = Decimal(request.form.get("amount") or 0)
    party = request.form.get("party_name", "").strip()
    if amount <= 0 or not party:
        flash("Enter party and amount", "error")
        return redirect(url_for("accounting.index"))
    accounting_service.record_payment(current_user.org_id, party, amount, note=request.form.get("note", ""))
    db.session.commit()
    flash("Payment recorded", "success")
    return redirect(url_for("accounting.index"))


@bp.route("/parties", methods=["GET"])
@login_required
def parties():
    if current_user.is_distributor:
        flash("Party management is at facility level", "error")
        return redirect(url_for("accounting.index"))
    rows = accounting_service.list_parties(current_user.org_id)
    return render_template("parties.html", parties=rows)


@bp.route("/parties/new", methods=["POST"])
@login_required
def party_new():
    if current_user.is_distributor:
        flash("Party management is at facility level", "error")
        return redirect(url_for("accounting.index"))
    try:
        accounting_service.create_party(
            current_user.org_id,
            request.form.get("party_name", ""),
            request.form.get("party_gstin") or None,
            credit_days=int(request.form.get("credit_days") or 30),
            credit_limit=Decimal(request.form.get("credit_limit") or 0),
        )
        db.session.commit()
        flash("Party added", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("accounting.parties"))


@bp.route("/settlement/pay", methods=["POST"])
@login_required
def settlement_pay():
    if current_user.is_distributor:
        flash("Facilities pay consignment settlements", "error")
        return redirect(url_for("accounting.index"))
    org = current_user.organization
    distributor = Organization.query.get(org.parent_id)
    if not distributor:
        flash("Distributor not linked", "error")
        return redirect(url_for("accounting.index"))
    amount = Decimal(request.form.get("amount") or 0)
    try:
        settlement_service.record_settlement_payment(org.id, distributor.id, amount, note=request.form.get("note", ""))
        db.session.commit()
        flash(f"₹{amount} paid to {distributor.name}", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("accounting.index"))


@bp.route("/settlement/receive", methods=["POST"])
@login_required
def settlement_receive():
    if not current_user.is_distributor:
        flash("Only distributor can record settlement receipts", "error")
        return redirect(url_for("accounting.index"))
    facility_id = int(request.form.get("facility_id") or 0)
    amount = Decimal(request.form.get("amount") or 0)
    facility = db.session.get(Organization, facility_id)
    if not facility or facility.parent_id != current_user.org_id:
        flash("Invalid facility", "error")
        return redirect(url_for("accounting.index"))
    try:
        settlement_service.record_settlement_payment(facility.id, current_user.org_id, amount, note=request.form.get("note", ""))
        db.session.commit()
        flash(f"₹{amount} received from {facility.name}", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("accounting.index"))