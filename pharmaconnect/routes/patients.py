from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import Patient
from ..services import permissions as perm_service

bp = Blueprint("patients", __name__, url_prefix="/patients")


@bp.before_request
def _require_patients():
    return perm_service.check_permission("patients")


@bp.route("/")
@login_required
def index():
    if current_user.is_distributor:
        flash("Patients are managed at hospital facility", "error")
        return redirect(url_for("dashboard.home"))
    if current_user.organization.kind != "HOSPITAL":
        flash("Patient management is for hospital pharmacies", "error")
        return redirect(url_for("dashboard.home"))
    rows = Patient.query.filter_by(facility_id=current_user.org_id).order_by(Patient.name).all()
    return render_template("patients.html", rows=rows)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if current_user.organization.kind != "HOSPITAL":
        return redirect(url_for("dashboard.home"))
    if request.method == "POST":
        p = Patient(
            facility_id=current_user.org_id,
            name=request.form["name"].strip(),
            phone=request.form.get("phone"),
            uhid=request.form.get("uhid"),
            ward=request.form.get("ward"),
        )
        db.session.add(p)
        db.session.commit()
        flash(f"Patient {p.name} added", "success")
        return redirect(url_for("patients.index"))
    return render_template("patient_form.html")