from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
from werkzeug.datastructures import MultiDict
from models import User, UserModel, db
from services.time_utils import datetime
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
        return redirect(url_for('main.studio'))
    
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
            next_page = url_for('main.studio')
        return redirect(next_page)
    
    return render_template('login.html', form=form)

@auth.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.studio'))

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


def _api_user_payload(user):
    return {"id": user.id, "username": user.username, "email": user.email, "plan": user.plan}


# --- Mobile app auth (Bearer-token, no session/cookie) -----------------
# These mirror login()/register() above exactly (same forms, same User
# methods) but respond with JSON + an ApiToken instead of a session cookie,
# since the native OS AR viewers a mobile client hands files off to can't
# carry a session cookie or CSRF token. See blueprints/api_tokens.py for the
# token model and CLAUDE.md/app.py for why these are csrf.exempt()'d.

@auth.route('/api/v1/auth/register', methods=['POST'])
def api_register():
    from blueprints.api_tokens import MOBILE_TOKEN_SCOPES, _issue_api_token

    if not setting_bool('registration_enabled', True):
        return jsonify({'success': False, 'error': 'Registration is currently disabled.'}), 403

    form = RegistrationForm(MultiDict(request.get_json(silent=True) or {}))
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    user = User(username=form.username.data, email=form.email.data)
    user.set_password(form.password.data)
    db.session.add(user)
    db.session.commit()

    issued = _issue_api_token(user, name='ARVision Mobile', scopes=MOBILE_TOKEN_SCOPES, expires_in_days=365)
    return jsonify({'success': True, 'token': issued['token'], 'user': _api_user_payload(user)}), 201


@auth.route('/api/v1/auth/login', methods=['POST'])
def api_login():
    from blueprints.api_tokens import MOBILE_TOKEN_SCOPES, _issue_api_token

    form = LoginForm(MultiDict(request.get_json(silent=True) or {}))
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    user = User.query.filter(
        (User.username == form.username.data) | (User.email == form.username.data)
    ).first()

    if user is not None and user.is_locked:
        return jsonify({
            'success': False,
            'error': 'Too many failed login attempts. Please try again in a few minutes.',
        }), 423

    if user is None or not user.check_password(form.password.data):
        if user is not None:
            user.register_failed_login()
            db.session.commit()
        return jsonify({'success': False, 'error': 'Invalid username/email or password'}), 401

    if not user.is_active:
        # Mirrors login_user()'s own refusal of deactivated accounts -- there's
        # no login_user() call on this token-only path to do that check for us.
        return jsonify({'success': False, 'error': 'This account has been deactivated.'}), 403

    user.register_successful_login()
    db.session.commit()

    issued = _issue_api_token(user, name='ARVision Mobile', scopes=MOBILE_TOKEN_SCOPES, expires_in_days=365)
    return jsonify({'success': True, 'token': issued['token'], 'user': _api_user_payload(user)})


@auth.route('/api/v1/auth/logout', methods=['POST'])
def api_logout():
    from blueprints.api_tokens import _bearer_token

    token, error = _bearer_token('models:read')
    if error:
        return error
    token.revoked_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True})


@auth.route('/profile')
@login_required
def profile():
    import app as app_module
    from services.plans import get_plan_config, plan_limit
    from services.storage_quota import _storage_usage_for, _storage_quota_bytes

    plan = current_user.plan
    plan_display = get_plan_config(plan).get("display_name", plan.title())

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
