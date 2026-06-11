from flask import Blueprint, Response, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..services import audit as audit_service
from ..services import integrations as integration_service
from ..services import permissions as perm_service
from ..services import sms as sms_service
from ..services import users as user_service

bp = Blueprint("settings", __name__, url_prefix="/settings")


@bp.route("/integrations", methods=["GET", "POST"])
@login_required
@perm_service.require_permission("integrations")
def integrations():
    org_id = current_user.org_id
    if request.method == "POST":
        try:
            integration_service.update_settings(org_id, {
                "irp_client_id": request.form.get("irp_client_id", "").strip(),
                "irp_client_secret": request.form.get("irp_client_secret", "").strip(),
                "irp_enabled": request.form.get("irp_enabled") == "1",
                "eway_username": request.form.get("eway_username", "").strip(),
                "eway_password": request.form.get("eway_password", "").strip(),
                "eway_enabled": request.form.get("eway_enabled") == "1",
                "razorpay_key_id": request.form.get("razorpay_key_id", "").strip(),
                "razorpay_key_secret": request.form.get("razorpay_key_secret", "").strip(),
                "razorpay_enabled": request.form.get("razorpay_enabled") == "1",
                "phonepe_merchant_id": request.form.get("phonepe_merchant_id", "").strip(),
                "phonepe_salt_key": request.form.get("phonepe_salt_key", "").strip(),
                "phonepe_enabled": request.form.get("phonepe_enabled") == "1",
                "sms_api_key": request.form.get("sms_api_key", "").strip(),
                "sms_sender_id": request.form.get("sms_sender_id", "").strip(),
                "sms_enabled": request.form.get("sms_enabled") == "1",
                "alert_expiry_days": request.form.get("alert_expiry_days") or 30,
                "alert_low_stock": request.form.get("alert_low_stock") == "1",
                "alert_schedule_enabled": request.form.get("alert_schedule_enabled") == "1",
                "alert_schedule_hour": request.form.get("alert_schedule_hour") or 9,
            })
            audit_service.log_action(
                org_id, "SETTINGS_UPDATE", user_id=current_user.id,
                entity_type="INTEGRATIONS", detail="Integration settings saved",
            )
            db.session.commit()
            flash("Integration settings saved", "success")
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("settings.integrations"))

    settings = integration_service.get_settings(org_id)
    status = integration_service.integration_status(org_id)
    return render_template("integrations.html", settings=settings, status=status)


@bp.route("/audit")
@login_required
@perm_service.require_permission("audit")
def audit():
    rows = audit_service.recent_logs(current_user.org_id)
    return render_template("audit_log.html", rows=rows)


@bp.route("/audit/export.csv")
@login_required
@perm_service.require_permission("audit")
def audit_export():
    csv_text = audit_service.export_csv(current_user.org_id)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=infivita_audit_trail.csv"},
    )


@bp.route("/sms", methods=["GET", "POST"])
@login_required
@perm_service.require_permission("sms")
def sms():
    org = current_user.organization
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "send_test":
                phone = request.form.get("phone", "").strip() or org.phone
                if not phone:
                    raise ValueError("Enter a phone number or set org phone")
                sms_service.send_sms(org.id, phone, "Infivita PharmaConnect test SMS — alerts are working.")
                flash("Test SMS queued", "success")
            elif action == "expiry_alerts" and current_user.is_distributor:
                n = sms_service.run_expiry_alerts(org.id)
                flash(f"Expiry alerts sent to {n} facility(s)", "success")
            elif action == "restock_alerts" and current_user.is_distributor:
                n = sms_service.run_restock_alerts(org.id)
                flash(f"Low-stock alerts sent to {n} facility(s)", "success")
            audit_service.log_action(
                org.id, "SMS_ALERT", user_id=current_user.id,
                detail=action,
            )
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("settings.sms"))

    rows = sms_service.recent_sms(org.id)
    return render_template("sms_log.html", rows=rows, is_distributor=current_user.is_distributor)


@bp.route("/users", methods=["GET", "POST"])
@login_required
@perm_service.require_permission("users_manage")
def users():
    org = current_user.organization
    if request.method == "POST":
        action = request.form.get("action")
        try:
            if action == "create":
                user_service.create_user(
                    org,
                    username=request.form.get("username", ""),
                    full_name=request.form.get("full_name", ""),
                    role_code=request.form.get("role_code", ""),
                    password=request.form.get("password", ""),
                )
                audit_service.log_action(
                    org.id, "USER_CREATE", user_id=current_user.id,
                    entity_type="USER", entity_ref=request.form.get("username", "").strip(),
                )
                flash("User created", "success")
            elif action == "toggle":
                user_service.toggle_user_active(
                    int(request.form["user_id"]), org.id, actor_id=current_user.id,
                )
                audit_service.log_action(
                    org.id, "USER_TOGGLE", user_id=current_user.id,
                    entity_ref=request.form.get("user_id"),
                )
                flash("User status updated", "success")
            elif action == "reset_password":
                user_service.reset_user_password(
                    int(request.form["user_id"]), org.id, request.form.get("password", ""),
                )
                audit_service.log_action(
                    org.id, "USER_RESET_PWD", user_id=current_user.id,
                    entity_ref=request.form.get("user_id"),
                )
                flash("Password reset", "success")
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("settings.users"))

    rows = user_service.org_users(org.id)
    roles = user_service.assignable_roles(org)
    return render_template("users.html", rows=rows, roles=roles)


@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        new_pw = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if new_pw != confirm:
            flash("New passwords do not match", "error")
            return redirect(url_for("settings.profile"))
        try:
            user_service.change_own_password(
                current_user,
                request.form.get("current_password", ""),
                new_pw,
            )
            audit_service.log_action(
                current_user.org_id, "PASSWORD_CHANGE", user_id=current_user.id,
            )
            db.session.commit()
            flash("Password updated", "success")
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "error")
        return redirect(url_for("settings.profile"))
    return render_template("profile.html")