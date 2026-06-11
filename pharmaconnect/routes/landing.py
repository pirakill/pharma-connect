from flask import Blueprint, render_template
from flask_login import current_user

bp = Blueprint("landing", __name__)


@bp.route("/welcome")
def welcome():
    if current_user.is_authenticated:
        from flask import redirect, url_for
        return redirect(url_for("dashboard.home"))
    return render_template("landing.html")


@bp.route("/features")
def features():
    return render_template("features.html")