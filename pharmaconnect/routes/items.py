from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, Response, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Item, TaxSlab
from ..services import items as item_service
from ..services import permissions as perm_service

bp = Blueprint("items", __name__, url_prefix="/items")

_MASTER_ROUTES = frozenset({
    "items.new", "items.edit", "items.import_csv", "items.toggle",
})
_VIEW_ROUTES = frozenset({"items.index", "items.labels", "items.download_template"})


@bp.before_request
def _items_permission():
    if not current_user.is_authenticated:
        return None
    ep = request.endpoint or ""
    if ep in _MASTER_ROUTES:
        if not perm_service.can_manage_items(current_user):
            flash("Only distributor admins can manage the medicine master", "error")
            return redirect(url_for("dashboard.home"))
    elif ep in _VIEW_ROUTES:
        if not perm_service.has_permission(current_user, "items_view") and not perm_service.can_manage_items(current_user):
            flash("You do not have permission to view items", "error")
            return redirect(url_for("dashboard.home"))
    return None


def _require_items_master():
    if not perm_service.can_manage_items(current_user):
        flash("Only distributor admins can manage the medicine master", "error")
        return False
    return True


@bp.route("/")
@login_required
def index():
    q = request.args.get("q", "").strip()
    show = request.args.get("show", "active")
    qry = Item.query
    if show == "active":
        qry = qry.filter_by(is_active=True)
    elif show == "inactive":
        qry = qry.filter_by(is_active=False)
    # show == "all" → no filter
    if q:
        like = f"%{q}%"
        qry = qry.filter((Item.name.ilike(like)) | (Item.code.ilike(like)) | (Item.barcode.ilike(like)))
    rows = qry.order_by(Item.name).limit(500).all()
    stats = item_service.item_stats()
    can_edit = perm_service.can_manage_items(current_user)
    return render_template("items.html", rows=rows, q=q, show=show, stats=stats, can_edit=can_edit)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if not _require_items_master():
        return redirect(url_for("items.index"))
    tax_slabs = TaxSlab.query.order_by(TaxSlab.rate).all()
    if request.method == "POST":
        try:
            item_service.upsert_item({
                "code": request.form["code"],
                "name": request.form["name"],
                "barcode": request.form.get("barcode"),
                "manufacturer": request.form.get("manufacturer"),
                "pack": request.form.get("pack"),
                "unit": request.form.get("unit"),
                "schedule": request.form.get("schedule"),
                "hsn": request.form.get("hsn"),
                "gst_rate": request.form.get("gst_rate"),
                "mrp": request.form.get("mrp"),
                "ptr": request.form.get("ptr"),
            })
            db.session.commit()
            flash(f"Item {request.form['code']} saved", "success")
            return redirect(url_for("items.index"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("item_form.html", item=None, tax_slabs=tax_slabs)


@bp.route("/<int:iid>/edit", methods=["GET", "POST"])
@login_required
def edit(iid: int):
    if not _require_items_master():
        return redirect(url_for("items.index"))
    item = db.session.get(Item, iid)
    if not item:
        flash("Item not found", "error")
        return redirect(url_for("items.index"))
    tax_slabs = TaxSlab.query.order_by(TaxSlab.rate).all()
    if request.method == "POST":
        try:
            item_service.upsert_item({
                "code": item.code,
                "name": request.form["name"],
                "barcode": request.form.get("barcode"),
                "manufacturer": request.form.get("manufacturer"),
                "pack": request.form.get("pack"),
                "unit": request.form.get("unit"),
                "schedule": request.form.get("schedule"),
                "hsn": request.form.get("hsn"),
                "gst_rate": request.form.get("gst_rate"),
                "mrp": request.form.get("mrp"),
                "ptr": request.form.get("ptr"),
            })
            db.session.commit()
            flash(f"Item {item.code} updated", "success")
            return redirect(url_for("items.index"))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("item_form.html", item=item, tax_slabs=tax_slabs)


@bp.route("/<int:iid>/toggle", methods=["POST"])
@login_required
def toggle(iid: int):
    if not _require_items_master():
        return redirect(url_for("items.index"))
    item = db.session.get(Item, iid)
    if item:
        item.is_active = not item.is_active
        db.session.commit()
        flash(f"{item.code} {'activated' if item.is_active else 'deactivated'}", "success")
    return redirect(url_for("items.index", show=request.args.get("show", "active")))


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_csv():
    if not _require_items_master():
        return redirect(url_for("items.index"))
    result = None
    if request.method == "POST":
        try:
            text = ""
            if request.files.get("file") and request.files["file"].filename:
                raw = request.files["file"].read()
                for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
                    try:
                        text = raw.decode(encoding)
                        break
                    except UnicodeDecodeError:
                        continue
                if not text:
                    raise ValueError("Could not read file encoding")
            elif request.form.get("csv_text", "").strip():
                text = request.form["csv_text"]
            else:
                raise ValueError("Upload a CSV file or paste CSV text")

            update_existing = bool(request.form.get("update_existing"))
            result = item_service.import_csv(text, update_existing=update_existing)
            db.session.commit()
            flash(
                f"Import done: {result['created']} created, {result['updated']} updated, "
                f"{result['skipped']} skipped",
                "success" if not result["errors"] else "error",
            )
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("items_import.html", result=result)


@bp.route("/labels")
@login_required
def labels():
    ids = request.args.getlist("item_id", type=int)
    qry = Item.query.filter_by(is_active=True).filter(Item.barcode.isnot(None))
    if ids:
        qry = qry.filter(Item.id.in_(ids))
    rows = qry.order_by(Item.name).limit(200).all()
    return render_template("barcode_labels.html", items=rows)


@bp.route("/template.csv")
@login_required
def download_template():
    return Response(
        item_service.export_csv_template(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=infivita_items_template.csv"},
    )