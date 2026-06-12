from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import CustomerRegularMed, Organization, RetailCustomer
from ..services import customers as customer_service
from ..services import permissions as perm_service

bp = Blueprint("customers", __name__, url_prefix="/customers")


@bp.before_request
def _require_customers():
    return perm_service.check_permission("customers")


def _distributor_facilities() -> list[Organization]:
    return (
        Organization.query.filter_by(parent_id=current_user.org_id, is_active=True)
        .filter(Organization.kind.in_(("RETAIL", "HOSPITAL", "INSTITUTIONAL")))
        .order_by(Organization.name)
        .all()
    )


def _resolve_facility_id(facility_id: int | None = None) -> int:
    if not current_user.is_distributor:
        return current_user.org_id
    facilities = _distributor_facilities()
    if not facilities:
        raise ValueError("No facilities linked to distributor")
    fid = (
        facility_id
        or request.args.get("facility_id", type=int)
        or request.form.get("facility_id", type=int)
    )
    if not fid:
        return facilities[0].id
    if not perm_service.can_access_facility(current_user, fid):
        raise ValueError("Select a valid facility")
    return fid


@bp.route("/")
@login_required
def index():
    facility_id = None
    facilities: list[Organization] = []
    if current_user.is_distributor:
        facilities = _distributor_facilities()
        if not facilities:
            flash("No facilities linked to distributor", "error")
            return redirect(url_for("dashboard.home"))
        try:
            facility_id = _resolve_facility_id()
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("dashboard.home"))
        qry = RetailCustomer.query.filter_by(facility_id=facility_id)
    else:
        qry = RetailCustomer.query.filter_by(facility_id=current_user.org_id)
    rows = qry.order_by(RetailCustomer.name).all()
    return render_template(
        "customers.html",
        rows=rows,
        facilities=facilities,
        facility_id=facility_id,
        is_distributor=current_user.is_distributor,
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    facilities: list[Organization] = []
    facility_id = current_user.org_id
    if current_user.is_distributor:
        facilities = _distributor_facilities()
        if not facilities:
            flash("No facilities linked to distributor", "error")
            return redirect(url_for("dashboard.home"))
        try:
            facility_id = _resolve_facility_id()
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("customers.index"))
    if request.method == "POST":
        if current_user.is_distributor:
            try:
                facility_id = _resolve_facility_id()
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("customers.new"))
        c = RetailCustomer(
            facility_id=facility_id,
            name=request.form["name"].strip(),
            phone=request.form.get("phone"),
            email=request.form.get("email"),
            gstin=request.form.get("gstin"),
            address=request.form.get("address"),
            credit_limit=Decimal(request.form.get("credit_limit") or 0),
            credit_days=int(request.form.get("credit_days") or 30),
        )
        db.session.add(c)
        db.session.commit()
        flash(f"Customer {c.name} created", "success")
        return redirect(url_for("customers.view", cid=c.id))
    return render_template(
        "customer_form.html",
        facilities=facilities,
        facility_id=facility_id,
        is_distributor=current_user.is_distributor,
    )


@bp.route("/<int:cid>")
@login_required
def view(cid: int):
    c = db.session.get(RetailCustomer, cid)
    if not perm_service.can_access_retail_customer(current_user, c):
        flash("Not found", "error")
        return redirect(url_for("customers.index"))
    history = customer_service.customer_history(cid)
    frequent = customer_service.frequent_items(cid)
    regular = customer_service.regular_meds_list(cid)
    credit = customer_service.credit_profile(cid)
    return render_template(
        "customer_view.html",
        c=c,
        history=history,
        frequent=frequent,
        regular=regular,
        credit=credit,
    )


@bp.route("/<int:cid>/payment", methods=["POST"])
@login_required
def payment(cid: int):
    c = db.session.get(RetailCustomer, cid)
    if not perm_service.can_access_retail_customer(current_user, c):
        flash("Not found", "error")
        return redirect(url_for("customers.index"))
    amount = Decimal(request.form.get("amount") or 0)
    try:
        customer_service.record_payment(c, amount, note=request.form.get("note", ""))
        db.session.commit()
        flash(f"₹{amount} collected from {c.name}", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("customers.view", cid=cid))