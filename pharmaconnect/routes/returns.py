from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Bill, SaleReturn
from ..services import permissions as perm_service
from ..services import returns as return_service

bp = Blueprint("returns", __name__, url_prefix="/returns")


@bp.before_request
def _require_returns():
    return perm_service.check_permission("returns")


@bp.route("/")
@login_required
def index():
    if current_user.is_distributor:
        return redirect(url_for("dashboard.home"))
    rows = SaleReturn.query.filter_by(facility_id=current_user.org_id).order_by(SaleReturn.returned_on.desc()).limit(50).all()
    return render_template("returns_list.html", rows=rows)


@bp.route("/new/<int:bid>", methods=["GET", "POST"])
@login_required
def new(bid: int):
    bill = db.session.get(Bill, bid)
    if not bill or bill.facility_id != current_user.org_id:
        flash("Bill not found", "error")
        return redirect(url_for("billing.index"))
    if request.method == "POST":
        try:
            lines = []
            for ln in bill.lines:
                qty = request.form.get(f"qty_{ln.id}", "").strip()
                if qty and Decimal(qty) > 0:
                    lines.append({"bill_line_id": ln.id, "qty": Decimal(qty)})
            if not lines:
                raise ValueError("Select items to return")
            sr = return_service.create_sale_return(bill, lines, reason=request.form.get("reason", ""))
            db.session.commit()
            flash(f"Return {sr.number} posted — GST reversed", "success")
            return redirect(url_for("returns.credit_note", rid=sr.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("return_new.html", bill=bill)


@bp.route("/<int:rid>/credit-note")
@login_required
def credit_note(rid: int):
    sr = db.session.get(SaleReturn, rid)
    if not sr:
        flash("Return not found", "error")
        return redirect(url_for("returns.index"))
    if not current_user.is_distributor and sr.facility_id != current_user.org_id:
        flash("Access denied", "error")
        return redirect(url_for("returns.index"))
    from ..services.invoice_qr import credit_note_qr_payload

    return render_template("credit_note_sale.html", doc=sr, qr_payload=credit_note_qr_payload(sr))