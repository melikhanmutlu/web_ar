"""WTForms definitions (CSRF comes from Flask-WTF)."""

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp


class RegisterForm(FlaskForm):
    username = StringField(
        "Kullanıcı adı",
        validators=[
            DataRequired(message="Kullanıcı adı gerekli."),
            Length(min=3, max=80, message="3–80 karakter olmalı."),
            Regexp(r"^[a-zA-Z0-9_.-]+$", message="Sadece harf, rakam, _ . - kullanın."),
        ],
    )
    email = StringField(
        "E-posta",
        validators=[DataRequired(message="E-posta gerekli."),
                    Email(message="Geçerli bir e-posta girin.")],
    )
    password = PasswordField(
        "Şifre",
        validators=[DataRequired(message="Şifre gerekli."),
                    Length(min=8, message="Şifre en az 8 karakter olmalı.")],
    )
    confirm = PasswordField(
        "Şifre (tekrar)",
        validators=[DataRequired(message="Şifreyi tekrar girin."),
                    EqualTo("password", message="Şifreler eşleşmiyor.")],
    )


class LoginForm(FlaskForm):
    username = StringField("Kullanıcı adı veya e-posta",
                           validators=[DataRequired(message="Bu alan gerekli.")])
    password = PasswordField("Şifre", validators=[DataRequired(message="Şifre gerekli.")])


class FolderForm(FlaskForm):
    name = StringField(
        "Klasör adı",
        validators=[DataRequired(message="Klasör adı gerekli."),
                    Length(min=1, max=100)],
    )
