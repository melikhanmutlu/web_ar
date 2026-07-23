from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse


def _safe_next(next_page):
    """Return next_page only if it's a same-origin relative path.

    Rejects absolute URLs and protocol-relative forms (`//host`, `/\\host`)
    which browsers normalize to an off-site redirect (open-redirect / phishing).
    """
    if not next_page or not next_page.startswith('/'):
        return None
    if next_page.startswith('//') or next_page.startswith('/\\'):
        return None
    if urlparse(next_page).netloc:
        return None
    return next_page
from models import User, UserModel, Payment, db
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

class ProfileForm(Form):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email()])

    def __init__(self, current_user_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._current_user_id = current_user_id

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user and user.id != self._current_user_id:
            raise ValidationError('This username is already taken.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user and user.id != self._current_user_id:
            raise ValidationError('This email is already registered.')

class ChangePasswordForm(Form):
    current_password = PasswordField('Current password', validators=[DataRequired()])
    new_password = PasswordField('New password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm new password', validators=[DataRequired(), EqualTo('new_password')])

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

        # Use one generic message for the locked, wrong-password, and
        # unknown-user branches so the response can't be used to enumerate which
        # accounts exist (a distinct "locked" message would reveal existence).
        invalid_msg = ('Invalid username/email or password, or the account is '
                       'temporarily locked after too many failed attempts.')

        if user is not None and user.is_locked:
            flash(invalid_msg, 'error')
            return redirect(url_for('auth.login'))

        if user is None or not user.check_password(form.password.data):
            if user is not None:
                user.register_failed_login()
                db.session.commit()
            flash(invalid_msg, 'error')
            return redirect(url_for('auth.login'))

        user.register_successful_login()
        db.session.commit()

        if not login_user(user, remember=form.remember.data):
            # login_user refuses inactive (admin-deactivated) accounts
            flash('This account has been deactivated.', 'error')
            return redirect(url_for('auth.login'))
        next_page = _safe_next(request.args.get('next')) or url_for('main.index')
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
        # Admin-configurable starting plan for new accounts (settings > users).
        # Validated against the live plan list; anything unknown -> "free".
        from services.plans import assignable_plan_slugs
        from site_settings import get_setting
        default_plan = get_setting('default_new_user_plan', 'free')
        if default_plan not in assignable_plan_slugs():
            default_plan = 'free'
        user = User(username=form.username.data, email=form.email.data, plan=default_plan)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        # Referral (F3.2): reward both sides if a valid ?ref= code came through.
        ref_code = (request.form.get('ref') or request.args.get('ref') or '').strip()[:16]
        if ref_code:
            from services.referrals import apply_referral
            apply_referral(user, ref_code)
            db.session.commit()
        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    ref_code = (request.args.get('ref') or '').strip()[:16]
    return render_template('register.html', form=form, ref_code=ref_code)

@auth.route('/logout', methods=['POST'])
@login_required
def logout():
    # POST-only so logout can't be triggered cross-site via a GET (e.g. an
    # <img src=".../logout"> tag) or by link prefetchers. CSRF-protected.
    logout_user()
    # Drop any residual keys stashed in the session dict, not just Flask-Login's.
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

@auth.route('/profile')
@login_required
def profile():
    profile_form = ProfileForm(current_user.id, username=current_user.username, email=current_user.email)
    password_form = ChangePasswordForm()
    return _render_profile(profile_form, password_form)

@auth.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    profile_form = ProfileForm(current_user.id, request.form)
    if profile_form.validate():
        current_user.username = profile_form.username.data
        current_user.email = profile_form.email.data
        db.session.commit()
        flash('Profile updated.', 'success')
        return redirect(url_for('auth.profile'))

    flash('Please fix the errors below.', 'error')
    return _render_profile(profile_form, ChangePasswordForm())

@auth.route('/profile/password', methods=['POST'])
@login_required
def change_password():
    password_form = ChangePasswordForm(request.form)
    if password_form.validate():
        if not current_user.check_password(password_form.current_password.data):
            password_form.current_password.errors.append('Current password is incorrect.')
        else:
            current_user.set_password(password_form.new_password.data)
            db.session.commit()
            flash('Password changed.', 'success')
            return redirect(url_for('auth.profile'))

    flash('Please fix the errors below.', 'error')
    profile_form = ProfileForm(current_user.id, username=current_user.username, email=current_user.email)
    return _render_profile(profile_form, password_form)

def _render_profile(profile_form, password_form):
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
    payments = (
        Payment.query.filter_by(user_id=current_user.id)
        .order_by(Payment.created_at.desc())
        .all()
    )
    from services.referrals import referral_link, referred_count, INVITEE_CREDITS, REFERRER_CREDITS
    return render_template(
        'profile.html',
        user=current_user,
        plan=plan,
        plan_display=plan_display,
        usage=usage,
        payments=payments,
        profile_form=profile_form,
        password_form=password_form,
        referral_link=referral_link(current_user),
        referred_count=referred_count(current_user),
        referral_referrer_credits=REFERRER_CREDITS,
        referral_invitee_credits=INVITEE_CREDITS,
    )
