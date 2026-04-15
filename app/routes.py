import secrets
import string

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.db import get_conn

bp = Blueprint("main", __name__)


def _random_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@bp.route("/")
def dashboard():
    q = (request.args.get("q") or "").strip()
    with get_conn() as conn:
        with conn.cursor() as cur:
            if q:
                cur.execute(
                    """
                    SELECT id, email, name, role
                    FROM users
                    WHERE email ILIKE %s
                    ORDER BY id;
                    """,
                    (f"%{q}%",),
                )
            else:
                cur.execute(
                    """
                    SELECT id, email, name, role
                    FROM users
                    ORDER BY id;
                    """
                )
            users = cur.fetchall()
    return render_template("dashboard.html", users=users, q=q)


@bp.route("/users/new", methods=["GET", "POST"])
def create_user():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip()
        name = (request.form.get("name") or "").strip()
        role = (request.form.get("role") or "user").strip()
        password = (request.form.get("password") or "").strip()
        if not email or not name:
            flash("Email and name are required.", "error")
            return render_template("create_user.html"), 400
        if not password:
            password = _random_password()
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (email, name, role, password)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id;
                        """,
                        (email, name, role, password),
                    )
                    row = cur.fetchone()
                conn.commit()
            uid = row["id"]
            flash(f"User created (id={uid}).", "success")
            return redirect(url_for("main.user_detail", user_id=uid))
        except Exception as e:
            flash(f"Could not create user: {e}", "error")
            return render_template("create_user.html"), 400
    return render_template("create_user.html")


@bp.route("/users/<int:user_id>")
def user_detail(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, email, name, role, password
                FROM users
                WHERE id = %s;
                """,
                (user_id,),
            )
            user = cur.fetchone()
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("main.dashboard"))
    return render_template("user_detail.html", user=user)


@bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
def reset_password(user_id: int):
    new_pw = _random_password()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users SET password = %s WHERE id = %s RETURNING email;
                """,
                (new_pw, user_id),
            )
            row = cur.fetchone()
        conn.commit()
    if not row:
        flash("User not found.", "error")
        return redirect(url_for("main.dashboard"))
    flash(f"Password reset for {row['email']}. New password: {new_pw}", "success")
    return redirect(url_for("main.user_detail", user_id=user_id))
