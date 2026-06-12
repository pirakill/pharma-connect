import json
from datetime import date

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..services import gst_export as gst_export_service
from ..services import permissions as perm_service
from ..services import reports as report_service

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.before_request
def _require_reports():
    return perm_service.check_permission("reports")


def _period_args():
    today = date.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    return year, month


def _json_download(payload: dict, filename: str) -> Response:
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _csv_download(content: str, filename: str) -> Response:
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.route("/")
@login_required
def hub():
    org = current_user.organization
    if current_user.is_distributor:
        expiry = report_service.expiry_report(org.id)
        slow = report_service.slow_moving(org.id)
        kpis = report_service.distributor_kpis(org.id)
        return render_template(
            "reports_hub.html",
            is_distributor=True,
            kpis=kpis,
            expiry=expiry[:20],
            slow=slow[:15],
        )
    daily = report_service.daily_sales(org.id)
    pnl = report_service.pnl_report(org.id)
    return render_template("reports_hub.html", is_distributor=False, daily=daily, pnl=pnl)


@bp.route("/gstr1/portal-export")
@login_required
def gstr1_portal_export():
    year, month = _period_args()
    org = current_user.organization
    network = current_user.is_distributor
    payload = gst_export_service.export_gstr1_portal_json(org, year, month, network=network)
    gstin = (org.gstin or org.code).replace(" ", "")
    scope = "network" if network else "facility"
    filename = f"GSTR1_PORTAL_{gstin}_{year}-{month:02d}_{scope}.json"
    return _json_download(payload, filename)


@bp.route("/gstr1/export")
@login_required
def gstr1_export():
    year, month = _period_args()
    org = current_user.organization
    network = current_user.is_distributor
    fmt = request.args.get("format", "json").lower()
    sections = request.args.get("sections")
    gstin = (org.gstin or org.code).replace(" ", "")
    scope = "network" if network else "facility"
    if fmt == "csv":
        content = gst_export_service.export_gstr1_csv(org, year, month, network=network, sections=sections)
        suffix = f"_{sections.replace(',', '-')}" if sections else ""
        filename = f"GSTR1_{gstin}_{year}-{month:02d}_{scope}{suffix}.csv"
        return _csv_download(content, filename)
    payload = gst_export_service.export_gstr1_json(org, year, month, network=network)
    if sections:
        allowed = {s.strip().lower() for s in sections.split(",") if s.strip()}
        if "invoices" not in allowed:
            payload["invoices"] = []
        if "credit_notes" not in allowed:
            payload["credit_notes"] = []
    filename = f"GSTR1_{gstin}_{year}-{month:02d}_{scope}.json"
    return _json_download(payload, filename)


@bp.route("/gstr2/export")
@login_required
def gstr2_export():
    year, month = _period_args()
    org = current_user.organization
    fmt = request.args.get("format", "json").lower()
    gstin = (org.gstin or org.code).replace(" ", "")
    if fmt == "csv":
        content = gst_export_service.export_gstr2_csv(org, year, month)
        filename = f"GSTR2_{gstin}_{year}-{month:02d}.csv"
        return _csv_download(content, filename)
    payload = gst_export_service.export_gstr2_json(org, year, month)
    filename = f"GSTR2_{gstin}_{year}-{month:02d}.json"
    return _json_download(payload, filename)


@bp.route("/gstr3b/export")
@login_required
def gstr3b_export():
    year, month = _period_args()
    org = current_user.organization
    network = current_user.is_distributor
    fmt = request.args.get("format", "json").lower()
    gstin = (org.gstin or org.code).replace(" ", "")
    scope = "network" if network else "facility"
    if fmt == "csv":
        content = gst_export_service.export_gstr3b_csv(org, year, month, network=network)
        filename = f"GSTR3B_{gstin}_{year}-{month:02d}_{scope}.csv"
        return _csv_download(content, filename)
    payload = gst_export_service.export_gstr3b_json(org, year, month, network=network)
    filename = f"GSTR3B_{gstin}_{year}-{month:02d}_{scope}.json"
    return _json_download(payload, filename)


@bp.route("/gstr1")
@login_required
def gstr1():
    year, month = _period_args()
    if current_user.is_distributor:
        summary = report_service.distributor_gstr1_summary(current_user.org_id, year, month)
        return render_template("gstr1_distributor.html", summary=summary, year=year, month=month)
    summary = report_service.gstr1_summary(current_user.org_id, year, month)
    return render_template("gstr1.html", summary=summary, year=year, month=month)


@bp.route("/gstr2")
@login_required
def gstr2():
    year, month = _period_args()
    summary = report_service.gstr2_summary(current_user.org_id, year, month)
    return render_template("gstr2.html", summary=summary, year=year, month=month)


@bp.route("/gstr3b")
@login_required
def gstr3b():
    year, month = _period_args()
    org = current_user.organization
    if current_user.is_distributor:
        payload = gst_export_service.export_gstr3b_json(org, year, month, network=True)
        return render_template("gstr3b_distributor.html", summary=payload["summary"], year=year, month=month)
    summary = report_service.gstr3b_summary(org.id, year, month)
    return render_template("gstr3b.html", summary=summary, year=year, month=month)


@bp.route("/expiry")
@login_required
def expiry():
    org = current_user.organization
    dist_id = org.id if current_user.is_distributor else org.parent_id
    rows = report_service.expiry_report(dist_id, within_days=int(request.args.get("days", 90)))
    return render_template("expiry_report.html", rows=rows)


@bp.route("/sale-register")
@login_required
def sale_register():
    if current_user.is_distributor:
        flash("Sale register is at facility level", "error")
        return redirect(url_for("reports.hub"))
    days = int(request.args.get("days", 30))
    rows = report_service.sale_register(current_user.org_id, days=days)
    return render_template("sale_register.html", rows=rows, days=days)


@bp.route("/purchase-register")
@login_required
def purchase_register():
    days = int(request.args.get("days", 30))
    rows = report_service.purchase_register(current_user.org_id, days=days)
    return render_template("purchase_register.html", rows=rows, days=days)


@bp.route("/outstanding")
@login_required
def outstanding():
    data = report_service.outstanding_report(current_user.org_id)
    return render_template("outstanding_report.html", data=data)


@bp.route("/credit-aging")
@login_required
def credit_aging():
    if current_user.is_distributor:
        flash("Credit aging is available at facility level", "error")
        return redirect(url_for("reports.hub"))
    from ..services.credit import credit_aging_report

    data = credit_aging_report(current_user.org_id)
    return render_template("credit_aging_report.html", data=data)


@bp.route("/network")
@login_required
def network():
    if not current_user.is_distributor:
        flash("Network dashboard is for distributor", "error")
        return redirect(url_for("reports.hub"))
    days = int(request.args.get("days", 30))
    data = report_service.network_summary(current_user.org_id, days=days)
    return render_template("network_dashboard.html", data=data, days=days)


@bp.route("/payments")
@login_required
def payments():
    if current_user.is_distributor:
        flash("Payment register is at facility level", "error")
        return redirect(url_for("reports.hub"))
    days = int(request.args.get("days", 30))
    rows = report_service.payment_register(current_user.org_id, days=days)
    total = sum(r["amount"] for r in rows)
    return render_template("payment_register.html", rows=rows, days=days, total=total)


@bp.route("/margin")
@login_required
def margin():
    if current_user.is_distributor:
        flash("Margin report is at facility level", "error")
        return redirect(url_for("reports.hub"))
    days = int(request.args.get("days", 30))
    data = report_service.margin_report(current_user.org_id, days=days)
    return render_template("margin_report.html", data=data, days=days)


@bp.route("/item-ledger")
@login_required
def item_ledger():
    from ..models import Item, Organization
    from ..services import permissions as perm_service

    items = Item.query.filter_by(is_active=True).order_by(Item.name).all()
    item_id = request.args.get("item_id", type=int)
    days = int(request.args.get("days", 90))
    facilities: list[Organization] = []
    facility_id = request.args.get("facility_id", type=int)
    rows = []
    ledger_org_id = current_user.org_id
    if current_user.is_distributor:
        facilities = (
            Organization.query.filter_by(parent_id=current_user.org_id, is_active=True)
            .order_by(Organization.name)
            .all()
        )
        if facility_id and perm_service.can_access_facility(current_user, facility_id):
            ledger_org_id = facility_id
        elif facilities:
            ledger_org_id = facilities[0].id
            facility_id = ledger_org_id
    if item_id:
        rows = report_service.item_ledger(ledger_org_id, item_id, days=days)
    return render_template(
        "item_ledger.html",
        items=items,
        item_id=item_id,
        days=days,
        rows=rows,
        facilities=facilities,
        facility_id=facility_id,
        is_distributor=current_user.is_distributor,
    )
