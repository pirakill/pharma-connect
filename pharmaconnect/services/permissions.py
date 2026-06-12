"""Role-based permission checks for Infivita PharmaConnect."""
from __future__ import annotations

from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user

# None = full access. Otherwise a set of permission codes.
ROLE_PERMISSIONS: dict[str, set[str] | None] = {
    "DISTRIBUTOR_ADMIN": None,
    "FACILITY_ADMIN": {
        "billing", "purchases", "returns", "customers", "schemes", "patients",
        "reports", "inventory", "integrations", "audit", "sms", "accounting",
        "import", "suppliers", "items_view", "users_manage", "scf",
    },
    "CASHIER": {
        "billing", "returns", "customers", "schemes", "reports", "inventory_view",
        "items_view",
    },
    "LENDER": {"scf_lender"},
}


def role_code(user) -> str:
    return user.role.code if user and user.is_authenticated and user.role else ""


def has_permission(user, perm: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    allowed = ROLE_PERMISSIONS.get(role_code(user))
    if allowed is None and role_code(user) == "DISTRIBUTOR_ADMIN":
        return True
    if allowed is None:
        return False
    return perm in allowed


def can_manage_items(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_distributor:
        return True
    return has_permission(user, "items_master")


def has_inventory_read(user) -> bool:
    return has_permission(user, "inventory") or has_permission(user, "inventory_view")


PUBLIC_API_ENDPOINTS = frozenset({"api.health", "api.ready", "api.cron_alerts"})

API_ENDPOINT_PERMISSIONS: dict[str, str] = {
    "api.live_stock": "__inventory_read__",
    "api.search_items": "items_view",
    "api.barcode_lookup": "billing",
    "api.warehouse_batches": "inventory",
    "api.customer_billing_context": "customers",
    "api.verify_payment": "integrations",
    "api.scf_webhook": "__public__",
}

def is_lender_user(user) -> bool:
    return bool(user and user.is_authenticated and role_code(user) == "LENDER")


def distributor_facility_ids(user) -> list[int]:
    from ..models import Organization

    if not user or not user.is_authenticated or not user.is_distributor:
        return []
    return [
        f.id
        for f in Organization.query.filter_by(parent_id=user.org_id, is_active=True).all()
    ]


def can_access_facility(user, facility_id: int) -> bool:
    from ..models import Organization

    if not user or not user.is_authenticated:
        return False
    if user.is_lender:
        return False
    if user.is_distributor:
        fac = Organization.query.get(facility_id)
        return fac is not None and fac.parent_id == user.org_id
    return user.org_id == facility_id


def can_access_org(user, org_id: int) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_lender:
        return False
    if user.is_distributor:
        return org_id == user.org_id or org_id in distributor_facility_ids(user)
    return user.org_id == org_id


def can_access_retail_customer(user, customer) -> bool:
    if not customer or not user or not user.is_authenticated:
        return False
    if user.is_lender:
        return False
    if user.is_distributor:
        return can_access_facility(user, customer.facility_id)
    return customer.facility_id == user.org_id


def check_permission(perm: str, *, api: bool = False):
    """Return a redirect/abort response when denied, else None."""
    if not current_user.is_authenticated:
        return None
    if has_permission(current_user, perm):
        return None
    if api:
        abort(403)
    flash("You do not have permission for this action", "error")
    return redirect(url_for("dashboard.home"))


def check_api_permission(endpoint: str | None):
    if not endpoint or endpoint in PUBLIC_API_ENDPOINTS:
        return None
    if not current_user.is_authenticated:
        return None
    perm = API_ENDPOINT_PERMISSIONS.get(endpoint or "")
    if perm == "__public__":
        return None
    if not perm:
        return None
    if perm == "__inventory_read__":
        if has_inventory_read(current_user):
            return None
    elif has_permission(current_user, perm):
        return None
    abort(403)


def require_permission(perm: str, *, api: bool = False):
    """Decorator — redirect (HTML) or 403 (API) when permission is missing."""

    def decorator(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if not has_permission(current_user, perm):
                if api:
                    abort(403)
                flash("You do not have permission for this action", "error")
                return redirect(url_for("dashboard.home"))
            return fn(*args, **kwargs)

        return wrapped

    return decorator