from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_user, logout_user

from .. import db
from ..models import User
from ..services import audit as audit_service

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"].strip()).first()
        if user and user.check_password(request.form["password"]) and user.is_active:
            login_user(user)
            audit_service.log_action(
                user.org_id, "LOGIN", user_id=user.id,
                entity_type="USER", entity_ref=user.username,
            )
            db.session.commit()
            if user.role and user.role.code == "LENDER":
                return redirect(url_for("scf.lender_hub"))
            return redirect(url_for("dashboard.home"))
        flash("Invalid credentials", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("auth.login"))