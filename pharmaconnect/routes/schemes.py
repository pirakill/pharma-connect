from datetime import datetime
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Item, Scheme
from ..services import permissions as perm_service

bp = Blueprint("schemes", __name__, url_prefix="/schemes")


@bp.before_request
def _require_schemes():
    return perm_service.check_permission("schemes")


@bp.route("/")
@login_required
def index():
    if current_user.is_distributor:
        flash("Schemes are managed at facility level", "error")
        return redirect(url_for("dashboard.home"))
    rows = Scheme.query.filter_by(org_id=current_user.org_id).order_by(Scheme.name).all()
    return render_template("schemes.html", rows=rows)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if current_user.is_distributor:
        return redirect(url_for("dashboard.home"))
    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()
    if request.method == "POST":
        vf = request.form.get("valid_from")
        vt = request.form.get("valid_to")
        s = Scheme(
            org_id=current_user.org_id,
            name=request.form["name"].strip(),
            kind=request.form.get("kind", "PERCENT"),
            value=Decimal(request.form.get("value") or 0),
            item_id=int(request.form["item_id"]) if request.form.get("item_id") else None,
            min_qty=int(request.form.get("min_qty") or 1),
            free_qty=int(request.form.get("free_qty") or 0),
            valid_from=datetime.strptime(vf, "%Y-%m-%d").date() if vf else None,
            valid_to=datetime.strptime(vt, "%Y-%m-%d").date() if vt else None,
            is_active=True,
        )
        db.session.add(s)
        db.session.commit()
        flash(f"Scheme {s.name} created", "success")
        return redirect(url_for("schemes.index"))
    return render_template("scheme_form.html", items=items)


@bp.route("/<int:sid>/toggle", methods=["POST"])
@login_required
def toggle(sid: int):
    s = db.session.get(Scheme, sid)
    if not s or s.org_id != current_user.org_id:
        flash("Scheme not found", "error")
        return redirect(url_for("schemes.index"))
    s.is_active = not s.is_active
    db.session.commit()
    flash("Scheme updated", "success")
    return redirect(url_for("schemes.index"))