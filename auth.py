from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
from models import User, UserModel, db
from site_settings import setting_bool
from wtforms import Form, StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError

class LoginForm(Form):
    username = StringField('Username or Email', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')

class RegistrationForm(Form):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('This username is already taken.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('This email is already registered.')

auth = Blueprint('auth', __name__)

@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User.query.filter(
            (User.username == form.username.data) | (User.email == form.username.data)
        ).first()

        if user is not None and user.is_locked:
            flash('Too many failed login attempts. Please try again in a few minutes.', 'error')
            return redirect(url_for('auth.login'))

        if user is None or not user.check_password(form.password.data):
            if user is not None:
                user.register_failed_login()
                db.session.commit()
            flash('Invalid username/email or password', 'error')
            return redirect(url_for('auth.login'))

        user.register_successful_login()
        db.session.commit()

        if not login_user(user, remember=form.remember.data):
            # login_user refuses inactive (admin-deactivated) accounts
            flash('This account has been deactivated.', 'error')
            return redirect(url_for('auth.login'))
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('main.index')
        return redirect(next_page)
    
    return render_template('login.html', form=form)

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if not setting_bool('registration_enabled', True):
        flash('Registration is currently disabled.', 'error')
        return redirect(url_for('auth.login'))

    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('register.html', form=form)

@auth.route('/logout', methods=['POST'])
@login_required
def logout():
    # POST-only so logout can't be triggered cross-site via a GET (e.g. an
    # <img src=".../logout"> tag) or by link prefetchers. CSRF-protected.
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

@auth.route('/profile')
@login_required
def profile():
    import app as app_module
    from services.plans import PLAN_CONFIG, plan_limit
    from services.storage_quota import _storage_usage_for, _storage_quota_bytes

    plan = current_user.plan
    plan_display = PLAN_CONFIG.get(plan, {}).get("display_name", plan.title())

    storage_used = _storage_usage_for(current_user.id)
    storage_quota = _storage_quota_bytes(current_user)  # 0 => unlimited
    model_count = (
        db.session.query(db.func.count(UserModel.id))
        .filter(UserModel.user_id == current_user.id, UserModel.deleted_at.is_(None))
        .scalar()
    )
    model_limit = plan_limit(current_user, "max_models")  # None => unlimited
    _, ai_used, ai_limit = app_module._ai_quota_state(current_user.id)

    usage = {
        "storage_used_mb": round(storage_used / (1024 * 1024), 1),
        "storage_quota_mb": round(storage_quota / (1024 * 1024)) if storage_quota else None,
        "model_count": model_count,
        "model_limit": model_limit,
        "ai_used": ai_used,
        "ai_limit": ai_limit,
        "ai_credits": current_user.ai_credit_balance,
    }
    return render_template(
        'profile.html',
        user=current_user,
        plan=plan,
        plan_display=plan_display,
        usage=usage,
    )
