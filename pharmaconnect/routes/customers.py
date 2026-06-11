from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import CustomerRegularMed, RetailCustomer
from ..services import customers as customer_service
from ..services import permissions as perm_service

bp = Blueprint("customers", __name__, url_prefix="/customers")


@bp.before_request
def _require_customers():
    return perm_service.check_permission("customers")


@bp.route("/")
@login_required
def index():
    if current_user.is_distributor:
        flash("Customer profiles are managed at each facility", "error")
        return redirect(url_for("dashboard.home"))
    rows = RetailCustomer.query.filter_by(facility_id=current_user.org_id).order_by(RetailCustomer.name).all()
    return render_template("customers.html", rows=rows)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if current_user.is_distributor:
        return redirect(url_for("dashboard.home"))
    if request.method == "POST":
        c = RetailCustomer(
            facility_id=current_user.org_id,
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
    return render_template("customer_form.html")


@bp.route("/<int:cid>")
@login_required
def view(cid: int):
    c = db.session.get(RetailCustomer, cid)
    if not c or (not current_user.is_distributor and c.facility_id != current_user.org_id):
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
    if not c or (not current_user.is_distributor and c.facility_id != current_user.org_id):
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