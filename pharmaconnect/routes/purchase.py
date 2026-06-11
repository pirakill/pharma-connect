import json
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Item, PurchaseBill, PurchaseReturn, Supplier
from ..services import inventory as inventory_service
from ..services import audit as audit_service
from ..services import permissions as perm_service
from ..services import purchase as purchase_service

bp = Blueprint("purchase", __name__, url_prefix="/purchase")


@bp.before_request
def _require_purchases():
    denied = perm_service.check_permission("purchases")
    if denied:
        flash("You do not have permission for purchases", "error")
        return denied
    return None


@bp.route("/")
@login_required
def index():
    rows = (
        PurchaseBill.query.filter_by(org_id=current_user.org_id)
        .order_by(PurchaseBill.purchased_on.desc())
        .limit(50)
        .all()
    )
    return render_template("purchase_list.html", rows=rows)


@bp.route("/batch-history")
@login_required
def batch_history():
    batch_no = request.args.get("batch_no", "")
    item_id = request.args.get("item_id", type=int)
    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()
    rows = purchase_service.batch_purchase_history(current_user.org_id, batch_no=batch_no, item_id=item_id)
    return render_template(
        "batch_purchase_history.html",
        rows=rows,
        items=items,
        batch_no=batch_no,
        item_id=item_id,
    )


@bp.route("/returns")
@login_required
def returns_list():
    rows = (
        PurchaseReturn.query.filter_by(org_id=current_user.org_id)
        .order_by(PurchaseReturn.returned_on.desc())
        .limit(50)
        .all()
    )
    return render_template("purchase_returns_list.html", rows=rows)


@bp.route("/return/<int:prid>/challan")
@login_required
def return_challan(prid: int):
    pr = db.session.get(PurchaseReturn, prid)
    if not pr or pr.org_id != current_user.org_id:
        flash("Purchase return not found", "error")
        return redirect(url_for("purchase.returns_list"))
    return render_template("purchase_return_challan.html", doc=pr)


@bp.route("/return/<int:prid>/credit-note")
@login_required
def credit_note(prid: int):
    from ..services.invoice_qr import debit_note_qr_payload

    pr = db.session.get(PurchaseReturn, prid)
    if not pr or pr.org_id != current_user.org_id:
        flash("Purchase return not found", "error")
        return redirect(url_for("purchase.index"))
    return render_template("credit_note_purchase.html", doc=pr, qr_payload=debit_note_qr_payload(pr))


@bp.route("/suppliers", methods=["GET", "POST"])
@login_required
def suppliers():
    org_id = current_user.org_id
    if request.method == "POST":
        try:
            purchase_service.record_supplier_payment(
                org_id,
                int(request.form["supplier_id"]),
                Decimal(request.form.get("amount") or 0),
                note=request.form.get("note", ""),
            )
            db.session.commit()
            flash("Supplier payment recorded", "success")
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("purchase.suppliers"))
    rows = Supplier.query.filter_by(org_id=org_id, is_active=True).order_by(Supplier.name).all()
    return render_template("suppliers.html", rows=rows)


@bp.route("/suppliers/new", methods=["GET", "POST"])
@login_required
def supplier_new():
    if request.method == "POST":
        s = Supplier(
            org_id=current_user.org_id,
            code=request.form["code"].strip(),
            name=request.form["name"].strip(),
            gstin=request.form.get("gstin"),
            phone=request.form.get("phone"),
            address=request.form.get("address"),
            payment_days=int(request.form.get("payment_days") or 30),
        )
        db.session.add(s)
        db.session.commit()
        flash(f"Supplier {s.name} added", "success")
        return redirect(url_for("purchase.suppliers"))
    return render_template("supplier_form.html")


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_csv():
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

            result = purchase_service.import_purchase_csv(current_user.organization, text)
            db.session.commit()
            flash(
                f"Import done: {result['created']} purchase(s), {result['skipped']} rows skipped",
                "success" if not result["errors"] else "error",
            )
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("purchase_import.html", result=result)


@bp.route("/import-template.csv")
@login_required
def import_template():
    return Response(
        purchase_service.export_purchase_csv_template(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=infivita_purchase_template.csv"},
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    suppliers = Supplier.query.filter_by(org_id=current_user.org_id, is_active=True).all()
    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()
    if request.method == "POST":
        try:
            supplier = db.session.get(Supplier, int(request.form["supplier_id"]))
            lines = json.loads(request.form.get("lines_json", "[]"))
            for row in lines:
                row["expiry"] = datetime.strptime(row["expiry"], "%Y-%m-%d").date()
            warehouse_id = int(request.form["warehouse_id"]) if request.form.get("warehouse_id") else None
            pb = purchase_service.create_purchase(
                current_user.organization,
                supplier,
                lines,
                invoice_no=request.form.get("invoice_no", ""),
                warehouse_id=warehouse_id,
            )
            audit_service.log_action(
                current_user.org_id, "PURCHASE_POST", user_id=current_user.id,
                entity_type="PURCHASE", entity_ref=pb.number,
            )
            db.session.commit()
            flash(f"Purchase {pb.number} recorded", "success")
            return redirect(url_for("purchase.view", pid=pb.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
    wh_rows = []
    if current_user.is_distributor:
        wh_rows = inventory_service.warehouses(current_user.org_id) or [
            inventory_service.get_or_create_warehouse(current_user.org_id)
        ]
    return render_template("purchase_new.html", suppliers=suppliers, items=items, warehouses=wh_rows)


@bp.route("/<int:pid>")
@login_required
def view(pid: int):
    pb = db.session.get(PurchaseBill, pid)
    if not pb or pb.org_id != current_user.org_id:
        flash("Purchase not found", "error")
        return redirect(url_for("purchase.index"))
    returns = PurchaseReturn.query.filter_by(purchase_id=pb.id).order_by(PurchaseReturn.returned_on.desc()).all()
    return render_template("purchase_view.html", purchase=pb, returns=returns)


@bp.route("/<int:pid>/return", methods=["GET", "POST"])
@login_required
def return_new(pid: int):
    pb = db.session.get(PurchaseBill, pid)
    if not pb or pb.org_id != current_user.org_id:
        flash("Purchase not found", "error")
        return redirect(url_for("purchase.index"))
    if request.method == "POST":
        try:
            lines = []
            for ln in pb.lines:
                qty = request.form.get(f"qty_{ln.id}", "").strip()
                if qty and Decimal(qty) > 0:
                    lines.append({"purchase_line_id": ln.id, "qty": Decimal(qty)})
            if not lines:
                raise ValueError("Select items to return")
            pr = purchase_service.create_purchase_return(
                current_user.organization, pb, lines, reason=request.form.get("reason", "")
            )
            db.session.commit()
            flash(f"Purchase return {pr.number} posted — stock and supplier balance updated", "success")
            return redirect(url_for("purchase.return_challan", prid=pr.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
    return render_template("purchase_return_new.html", purchase=pb)