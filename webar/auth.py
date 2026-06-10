"""Authentication blueprint: register / login / logout."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db, limiter, login_manager
from .forms import LoginForm, RegisterForm
from .models import User

bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip().lower()
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            form.username.errors.append("Bu kullanıcı adı zaten alınmış.")
        elif User.query.filter(db.func.lower(User.email) == email).first():
            form.email.errors.append("Bu e-posta zaten kayıtlı.")
        else:
            user = User(username=username, email=email)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Hesabınız oluşturuldu. Hoş geldiniz!", "success")
            return redirect(url_for("views.dashboard"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        handle = form.username.data.strip()
        user = User.query.filter(
            db.or_(
                db.func.lower(User.username) == handle.lower(),
                db.func.lower(User.email) == handle.lower(),
            )
        ).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True)
            next_url = request.args.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("views.dashboard"))
        flash("Kullanıcı adı veya şifre hatalı.", "error")
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("views.index"))
