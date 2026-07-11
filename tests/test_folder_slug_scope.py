"""Folder slug namespace: scoped uniqueness instead of a global slug pool."""
import pytest
from sqlalchemy.exc import IntegrityError

from models import Folder, Organization, User, db


def _make_user(name):
    user = User(username=name, email=f"{name}@test.com")
    user.set_password("pw")
    db.session.add(user)
    db.session.flush()
    return user


def test_same_slug_allowed_for_different_users(client):
    alice, bob = _make_user("alice"), _make_user("bob")
    db.session.add_all([
        Folder(name="Projects", slug="projects-aaaa", user_id=alice.id),
        Folder(name="Projects", slug="projects-aaaa", user_id=bob.id),
    ])
    db.session.commit()
    assert Folder.query.filter_by(slug="projects-aaaa").count() == 2


def test_duplicate_slug_in_fully_scoped_namespace_rejected(client):
    """NULL org/parent values are distinct under SQL UNIQUE semantics, so the
    constraint bites only when the whole scope is concrete; personal folders
    rely on the app-level duplicate check plus the random slug suffix."""
    alice = _make_user("alice")
    org = Organization(name="Acme", slug="acme", created_by=alice.id)
    db.session.add(org)
    db.session.flush()
    parent = Folder(name="Root", slug="root-aaaa", user_id=alice.id, organization_id=org.id)
    db.session.add(parent)
    db.session.flush()
    db.session.add(Folder(name="Projects", slug="projects-aaaa", user_id=alice.id,
                          organization_id=org.id, parent_id=parent.id))
    db.session.commit()
    db.session.add(Folder(name="Projects 2", slug="projects-aaaa", user_id=alice.id,
                          organization_id=org.id, parent_id=parent.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_duplicate_folder_name_returns_flash_not_error(client):
    user = _make_user("creator")
    db.session.commit()
    client.post("/login", data={"username": "creator", "password": "pw"})
    assert client.post("/create_folder", data={"folder_name": "Docs"}).status_code == 302
    assert client.post("/create_folder", data={"folder_name": "Docs"}).status_code == 302
    # Second create is rejected by the duplicate-name check, not a 500
    assert Folder.query.filter_by(user_id=user.id, name="Docs").count() == 1
