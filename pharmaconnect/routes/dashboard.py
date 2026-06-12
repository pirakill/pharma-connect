from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..models import Organization
from ..services import accounting as accounting_service
from ..services import inventory as inventory_service
from ..services import permissions as perm_service
from ..services import reports as report_service

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.route("/")
@login_required
def home():
    if current_user.is_lender:
        return redirect(url_for("scf.lender_hub"))
    org = current_user.organization
    if current_user.is_distributor:
        kpis = report_service.distributor_kpis(org.id)
        facilities = inventory_service.facility_stock_summary(org.id)
        live = inventory_service.stock_with_limits(distributor_id=org.id)[:20]
        receivables = accounting_service.distributor_receivables(org.id)
        near = inventory_service.near_expiry_batches(org.id)[:8]
        restock = inventory_service.restock_alerts(org.id)[:10]
        return render_template(
            "distributor_dashboard.html",
            kpis=kpis,
            facilities=facilities,
            live_stock=live,
            receivables=receivables,
            near_expiry=near,
            restock_alerts=restock,
        )

    if perm_service.role_code(current_user) == "CASHIER":
        summary = report_service.cashier_summary(org.id)
        restock = inventory_service.restock_alerts(org.parent_id, facility_id=org.id)[:5]
        return render_template(
            "cashier_dashboard.html",
            org=org,
            summary=summary,
            restock_alerts=restock,
        )

    pnl = accounting_service.pnl_summary(org.id)
    receivables = accounting_service.receivables(org.id)
    stock = inventory_service.stock_with_limits(facility_id=org.id)[:15]
    restock = inventory_service.restock_alerts(org.parent_id, facility_id=org.id)
    return render_template(
        "facility_dashboard.html",
        org=org,
        pnl=pnl,
        receivables=receivables,
        stock=stock,
        restock_alerts=restock,
    )