from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Bill, FinancingRequest, LenderPartner
from ..services import permissions as perm_service
from ..services import scf as scf_service

bp = Blueprint("scf", __name__, url_prefix="/scf")


def _facility_org_id() -> int:
    return current_user.org_id


@bp.before_request
def _scf_access():
    if not current_user.is_authenticated:
        return None
    if current_user.is_lender:
        return None
    return perm_service.check_permission("scf")


@bp.route("/")
@login_required
def hub():
    if current_user.is_lender:
        return redirect(url_for("scf.lender_hub"))
    org = current_user.organization
    data = scf_service.scf_dashboard(org.id, is_distributor=current_user.is_distributor)
    lenders = scf_service.active_lenders()
    financing = scf_service.facility_financing_list(org.id) if not current_user.is_distributor else []
    return render_template(
        "scf_hub.html",
        data=data,
        lenders=lenders,
        financing=financing,
        is_distributor=current_user.is_distributor,
    )


@bp.route("/profiles")
@login_required
def profiles():
    if current_user.is_lender:
        return redirect(url_for("scf.lender_hub"))
    org = current_user.organization
    if current_user.is_distributor:
        rows = scf_service.network_profiles(org.id)
    else:
        scf_service.refresh_all_profiles(org.id)
        db.session.commit()
        rows = scf_service.scf_dashboard(org.id)["profiles"]
    return render_template("scf_profiles.html", profiles=rows, is_distributor=current_user.is_distributor)


@bp.route("/profiles/refresh", methods=["POST"])
@login_required
def refresh_profiles():
    if current_user.is_distributor:
        flash("Refresh profiles at each facility", "error")
        return redirect(url_for("scf.profiles"))
    count = scf_service.refresh_all_profiles(_facility_org_id())
    scf_service.scan_credit_alerts(_facility_org_id())
    db.session.commit()
    flash(f"Refreshed {count} credit profile(s)", "success")
    return redirect(url_for("scf.profiles"))


@bp.route("/alerts")
@login_required
def alerts():
    if current_user.is_lender:
        return redirect(url_for("scf.lender_hub"))
    org_id = _facility_org_id()
    if request.args.get("scan") == "1":
        scf_service.scan_credit_alerts(org_id)
        db.session.commit()
        flash("Credit alerts scanned", "success")
    rows = scf_service.list_alerts(org_id, unresolved_only=request.args.get("all") != "1")
    return render_template("scf_alerts.html", alerts=rows)


@bp.route("/alerts/<int:aid>/resolve", methods=["POST"])
@login_required
def resolve_alert(aid: int):
    try:
        scf_service.resolve_alert(aid)
        db.session.commit()
        flash("Alert resolved", "success")
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("scf.alerts"))


@bp.route("/financing")
@login_required
def financing_list():
    if current_user.is_lender:
        return redirect(url_for("scf.lender_hub"))
    rows = scf_service.facility_financing_list(_facility_org_id())
    return render_template("scf_financing_list.html", requests=rows)


@bp.route("/financing/new", methods=["GET", "POST"])
@login_required
def financing_new():
    if current_user.is_distributor:
        flash("Financing is submitted at facility level", "error")
        return redirect(url_for("scf.hub"))
    org_id = _facility_org_id()
    lenders = scf_service.active_lenders()
    bills = (
        Bill.query.filter_by(facility_id=org_id, payment_mode="CREDIT")
        .filter(Bill.balance_due > 0)
        .order_by(Bill.billed_on.desc())
        .limit(30)
        .all()
    )
    if request.method == "POST":
        try:
            req = scf_service.create_financing_request(
                org_id,
                int(request.form["bill_id"]),
                int(request.form["lender_id"]),
                current_user.id,
                notes=request.form.get("notes", ""),
            )
            db.session.commit()
            flash(f"Financing request submitted to {req.lender.name}", "success")
            return redirect(url_for("scf.financing_view", rid=req.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")
    preselect_bill = request.args.get("bill", type=int)
    return render_template(
        "scf_financing_new.html",
        bills=bills,
        lenders=lenders,
        preselect_bill=preselect_bill,
    )


@bp.route("/financing/<int:rid>")
@login_required
def financing_view(rid: int):
    req = db.session.get(FinancingRequest, rid)
    if not req:
        flash("Not found", "error")
        return redirect(url_for("scf.financing_list"))
    if current_user.is_lender:
        if req.lender_partner_id != current_user.lender_partner_id:
            flash("Not found", "error")
            return redirect(url_for("scf.lender_hub"))
    elif not current_user.is_distributor and req.org_id != current_user.org_id:
        flash("Not found", "error")
        return redirect(url_for("scf.financing_list"))
    return render_template("scf_financing_detail.html", req=req, is_lender=current_user.is_lender)


@bp.route("/financing/<int:rid>/from-bill", methods=["POST"])
@login_required
def financing_from_bill(rid: int):
    """Shortcut: submit financing for a bill (bill id in URL as rid)."""
    org_id = _facility_org_id()
    lender_id = int(request.form.get("lender_id") or 0)
    try:
        req = scf_service.create_financing_request(
            org_id, rid, lender_id, current_user.id,
            notes=request.form.get("notes", ""),
        )
        db.session.commit()
        flash(f"Financing request submitted", "success")
        return redirect(url_for("scf.financing_view", rid=req.id))
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("billing.view", bid=rid))


@bp.route("/lender/")
@login_required
def lender_hub():
    if not current_user.is_lender or not current_user.lender_partner_id:
        flash("Lender access only", "error")
        return redirect(url_for("dashboard.home"))
    lender = db.session.get(LenderPartner, current_user.lender_partner_id)
    queue = scf_service.lender_queue(lender.id)
    approved = sum(1 for r in queue if r.status == "APPROVED")
    pending = sum(1 for r in queue if r.status in ("SUBMITTED", "UNDER_REVIEW"))
    disbursed = (
        FinancingRequest.query.filter_by(lender_partner_id=lender.id, status="DISBURSED").count()
    )
    return render_template(
        "scf_lender_hub.html",
        lender=lender,
        queue=queue,
        approved=approved,
        pending=pending,
        disbursed=disbursed,
    )


@bp.route("/lender/<int:rid>/review", methods=["POST"])
@login_required
def lender_review(rid: int):
    if not current_user.is_lender:
        flash("Lender access only", "error")
        return redirect(url_for("dashboard.home"))
    req = db.session.get(FinancingRequest, rid)
    if not req or req.lender_partner_id != current_user.lender_partner_id:
        flash("Not found", "error")
        return redirect(url_for("scf.lender_hub"))
    action = request.form.get("action")
    try:
        if action == "approve":
            scf_service.review_request(rid, approve=True)
            flash("Request approved", "success")
        elif action == "reject":
            scf_service.review_request(rid, approve=False, reason=request.form.get("reason", ""))
            flash("Request rejected", "success")
        elif action == "disburse":
            scf_service.disburse_request(rid)
            flash("Funds disbursed (mock)", "success")
        else:
            raise ValueError("Invalid action")
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return redirect(url_for("scf.financing_view", rid=rid))