"""Org-scoped user management."""
from __future__ import annotations

from .. import db
from ..models import Organization, Role, User

FACILITY_ROLES = ("FACILITY_ADMIN", "CASHIER")
DISTRIBUTOR_ROLES = ("DISTRIBUTOR_ADMIN",)


def assignable_roles(org: Organization) -> list[Role]:
    codes = DISTRIBUTOR_ROLES if org.kind == "DISTRIBUTOR" else FACILITY_ROLES
    return Role.query.filter(Role.code.in_(codes)).order_by(Role.name).all()


def org_users(org_id: int) -> list[User]:
    return User.query.filter_by(org_id=org_id).order_by(User.username).all()


def create_user(
    org: Organization,
    *,
    username: str,
    full_name: str,
    role_code: str,
    password: str,
) -> User:
    username = username.strip().lower()
    full_name = full_name.strip()
    if not username or not full_name or not password:
        raise ValueError("Username, full name, and password are required")
    if len(password) < 4:
        raise ValueError("Password must be at least 4 characters")
    if User.query.filter_by(username=username).first():
        raise ValueError(f"Username '{username}' is already taken")

    allowed = {r.code for r in assignable_roles(org)}
    if role_code not in allowed:
        raise ValueError("Role not allowed for this organization")

    role = Role.query.filter_by(code=role_code).first()
    if not role:
        raise ValueError("Invalid role")

    user = User(username=username, full_name=full_name, role_id=role.id, org_id=org.id)
    user.set_password(password)
    db.session.add(user)
    return user


def toggle_user_active(user_id: int, org_id: int, *, actor_id: int) -> User:
    user = db.session.get(User, user_id)
    if not user or user.org_id != org_id:
        raise ValueError("User not found")
    if user.id == actor_id:
        raise ValueError("You cannot deactivate your own account")
    user.is_active_flag = not user.is_active_flag
    return user


def reset_user_password(user_id: int, org_id: int, password: str) -> User:
    if len(password) < 4:
        raise ValueError("Password must be at least 4 characters")
    user = db.session.get(User, user_id)
    if not user or user.org_id != org_id:
        raise ValueError("User not found")
    user.set_password(password)
    return user


def change_own_password(user: User, current_password: str, new_password: str) -> None:
    if not user.check_password(current_password):
        raise ValueError("Current password is incorrect")
    if len(new_password) < 4:
        raise ValueError("New password must be at least 4 characters")
    user.set_password(new_password)