
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import os
import secrets
import sqlite3
import textwrap
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import BadSignature, URLSafeSerializer

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "erp.sqlite3"
UPLOAD_DIR = BASE_DIR / "uploads"
PO_DIR = UPLOAD_DIR / "po"
PACKING_DIR = UPLOAD_DIR / "packing_lists"
ATTACH_DIRS = [UPLOAD_DIR, PO_DIR, PACKING_DIR]

for d in ATTACH_DIRS:
    d.mkdir(parents=True, exist_ok=True)

TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
ASSET_DIR = BASE_DIR / "assets" / "images"

# Ensure mount points and template directories exist before FastAPI mounts them
TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)
ASSET_DIR.mkdir(parents=True, exist_ok=True)

THEMES = {
    "Dark Modern": {"class": "theme-dark-modern", "logo": "arcosa.png"},
    "Light Modern": {"class": "theme-light-modern", "logo": "arcosa.png"},
    "Florida State": {"class": "theme-florida-state", "logo": "florida state.png"},
    "Ohio State": {"class": "theme-ohio-state", "logo": "ohio state.png"},
    "Patriots": {"class": "theme-patriots", "logo": "patriots.png"},
    "Cowboys": {"class": "theme-cowboys", "logo": "cowboys.png"},
    "Cardinals": {"class": "theme-cardinals", "logo": "cardinals.png"},
}

STATUS_FLOW = [
    "Draft",
    "Awaiting First Approver",
    "Awaiting Buyer Price Verification",
    "Awaiting Plant Manager Final Approval",
    "Awaiting Buyer PO Attachment",
    "Ordered",
    "Partially Received",
    "Received",
    "Rejected",
]

ROLES = [
    "admin",
    "requester",
    "first_approver",
    "buyer",
    "plant_manager",
    "receiver",
]

DEFAULT_USERS = [
    ("admin", "admin123", "Administrator", "admin"),
    ("requester", "requester123", "Requester User", "requester"),
    ("approver", "approver123", "Department Manager", "first_approver"),
    ("buyer", "buyer123", "Buyer User", "buyer"),
    ("plant", "plant123", "Plant Manager", "plant_manager"),
    ("receiver", "receiver123", "Receiving Clerk", "receiver"),
]

DEFAULT_THEMES = "Dark Modern"

SECRET_KEY_FILE = BASE_DIR / ".secret_key"
if SECRET_KEY_FILE.exists():
    SECRET_KEY = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    SECRET_KEY_FILE.write_text(SECRET_KEY, encoding="utf-8")

SESSION_SERIALIZER = URLSafeSerializer(SECRET_KEY, salt="wh-enterprise-session")

app = FastAPI(title="Warehouse Enterprise ERP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/assets", StaticFiles(directory=str(BASE_DIR / "assets")), name="assets")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["themes"] = list(THEMES.keys())
templates.env.globals["status_flow"] = STATUS_FLOW
templates.env.globals["now"] = datetime.utcnow


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
        ).hex()
        return hmac.compare_digest(computed, digest)
    except Exception:
        return False


def generate_reference(prefix: str, conn: sqlite3.Connection) -> str:
    date_prefix = datetime.now().strftime("%Y%m%d")
    cur = conn.execute(
        f"SELECT COUNT(*) AS c FROM {('requisitions' if prefix == 'RQ' else 'purchase_orders')} "
        "WHERE created_at LIKE ?",
        (f"{datetime.now().strftime('%Y-%m-%d')}%",),
    )
    count = cur.fetchone()["c"] + 1
    return f"{prefix}-{date_prefix}-{count:04d}"


def init_templates() -> None:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    (TEMPLATE_DIR / "base.html").write_text(BASE_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "login.html").write_text(LOGIN_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "dashboard.html").write_text(DASHBOARD_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "inventory.html").write_text(INVENTORY_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "requisitions.html").write_text(REQUISITIONS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "requisition_new.html").write_text(REQUISITION_NEW_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "requisition_detail.html").write_text(REQUISITION_DETAIL_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "users.html").write_text(USERS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "reports.html").write_text(REPORTS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "purchase_orders.html").write_text(PURCHASE_ORDERS_TEMPLATE, encoding="utf-8")
    (TEMPLATE_DIR / "receiving.html").write_text(RECEIVING_TEMPLATE, encoding="utf-8")


def init_static() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    (STATIC_DIR / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (STATIC_DIR / "app.js").write_text(APP_JS, encoding="utf-8")
    (STATIC_DIR / "manifest.json").write_text(MANIFEST_JSON, encoding="utf-8")
    (STATIC_DIR / "sw.js").write_text(SW_JS, encoding="utf-8")
    (BASE_DIR / "requirements.txt").write_text(REQUIREMENTS_TXT, encoding="utf-8")
    (BASE_DIR / "README.txt").write_text(README_TXT, encoding="utf-8")
    (BASE_DIR / "run.bat").write_text(RUN_BAT, encoding="utf-8")
    # inventory template
    if not (BASE_DIR / "inventory.csv").exists():
        (BASE_DIR / "inventory.csv").write_text(INVENTORY_CSV_TEMPLATE, encoding="utf-8")


def copy_assets() -> None:
    for name in ["arcosa.png", "florida state.png", "ohio state.png", "patriots.png", "cowboys.png", "cardinals.png"]:
        src = Path("/mnt/data") / name
        dst = ASSET_DIR / name
        if src.exists():
            dst.write_bytes(src.read_bytes())


@contextmanager
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def seed_inventory_from_csv(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT COUNT(*) AS c FROM inventory_items")
    if cur.fetchone()["c"] > 0:
        return
    csv_path = BASE_DIR / "inventory.csv"
    if not csv_path.exists():
        return
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            part_no = (row.get("Part #") or row.get("Part") or "").strip()
            if not part_no:
                continue
            desc = (row.get("Description") or "").strip()
            on_hand = int(float(row.get("On Hand") or 0))
            min_level = int(float(row.get("Min Level") or 0))
            reorder_qty = int(float(row.get("Reorder Qty") or 0))
            unit_cost = float(row.get("Unit Cost") or row.get("Cost") or 0)
            vendor = (row.get("Vendor") or "").strip()
            conn.execute(
                """
                INSERT INTO inventory_items (part_no, description, on_hand, min_level, reorder_qty, unit_cost, vendor, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (part_no, desc, on_hand, min_level, reorder_qty, unit_cost, vendor, now_iso()),
            )


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                part_no TEXT UNIQUE NOT NULL,
                description TEXT NOT NULL,
                on_hand INTEGER NOT NULL DEFAULT 0,
                min_level INTEGER NOT NULL DEFAULT 0,
                reorder_qty INTEGER NOT NULL DEFAULT 0,
                unit_cost REAL NOT NULL DEFAULT 0,
                vendor TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee TEXT NOT NULL,
                part_no TEXT NOT NULL,
                description TEXT NOT NULL,
                qty INTEGER NOT NULL,
                unit_cost REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                issued_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS requisitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_no TEXT UNIQUE NOT NULL,
                requester TEXT NOT NULL,
                department TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT DEFAULT '',
                current_step INTEGER NOT NULL DEFAULT 0,
                po_number TEXT DEFAULT '',
                po_file TEXT DEFAULT '',
                packing_list_file TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                received_at TEXT DEFAULT '',
                received_by TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS requisition_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                part_no TEXT NOT NULL,
                description TEXT NOT NULL,
                qty INTEGER NOT NULL,
                unit_cost REAL NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                received_qty INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS approval_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                step_name TEXT NOT NULL,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                comment TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS purchase_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                po_number TEXT UNIQUE NOT NULL,
                vendor TEXT DEFAULT '',
                attachment TEXT DEFAULT '',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                requisition_id INTEGER NOT NULL,
                received_by TEXT NOT NULL,
                packing_list_file TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                received_at TEXT NOT NULL,
                FOREIGN KEY (requisition_id) REFERENCES requisitions(id) ON DELETE CASCADE
            );
            """
        )
        seed_inventory_from_csv(conn)
        cur = conn.execute("SELECT COUNT(*) AS c FROM users")
        if cur.fetchone()["c"] == 0:
            for username, pw, full_name, role in DEFAULT_USERS:
                conn.execute(
                    """
                    INSERT INTO users (username, password_hash, full_name, role, active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (username, hash_password(pw), full_name, role, now_iso()),
                )


def get_theme_name(request: Request) -> str:
    theme = request.cookies.get("theme", DEFAULT_THEMES)
    return theme if theme in THEMES else DEFAULT_THEMES


def get_user_from_session(request: Request) -> Optional[dict[str, Any]]:
    raw = request.cookies.get("session")
    if not raw:
        return None
    try:
        data = SESSION_SERIALIZER.loads(raw)
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND active = 1",
                (data.get("username"),),
            ).fetchone()
            if row:
                return dict(row)
    except BadSignature:
        return None
    except Exception:
        return None
    return None


def auth_context(request: Request) -> dict[str, Any]:
    user = get_user_from_session(request)
    theme_name = get_theme_name(request)
    return {
        "user": user,
        "theme_name": theme_name,
        "theme_class": THEMES[theme_name]["class"],
        "logo_name": THEMES[theme_name]["logo"],
        "current_year": datetime.now().year,
    }


def require_login(request: Request) -> dict[str, Any]:
    user = get_user_from_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(user: dict[str, Any], roles: list[str]) -> None:
    if user["role"] not in roles and user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")


def redirect_with_msg(path: str, msg: str = "", kind: str = "success") -> RedirectResponse:
    from urllib.parse import quote
    url = path
    if msg:
        sep = "&" if "?" in path else "?"
        url = f"{path}{sep}msg={quote(msg)}&kind={quote(kind)}"
    return RedirectResponse(url, status_code=303)


def money(value: float | int | None) -> str:
    try:
        return f"${float(value or 0):,.2f}"
    except Exception:
        return "$0.00"


templates.env.globals["money"] = money


def requisition_total(req_id: int) -> float:
    with db() as conn:
        row = conn.execute("SELECT COALESCE(SUM(total_cost),0) AS t FROM requisition_lines WHERE requisition_id = ?", (req_id,)).fetchone()
        return float(row["t"] or 0)

def dashboard_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    low_stock = conn.execute(
        "SELECT * FROM inventory_items WHERE on_hand <= min_level ORDER BY (on_hand - min_level) ASC, description ASC"
    ).fetchall()

    pending = conn.execute(
        """
        SELECT * FROM requisitions
        WHERE status IN (
            'Awaiting First Approver',
            'Awaiting Buyer Price Verification',
            'Awaiting Plant Manager Final Approval',
            'Awaiting Buyer PO Attachment',
            'Ordered'
        )
        ORDER BY datetime(updated_at) DESC
        LIMIT 10
        """
    ).fetchall()

    open_req = conn.execute(
        "SELECT COUNT(*) AS c FROM requisitions WHERE status NOT IN ('Received','Rejected')"
    ).fetchone()["c"]

    received = conn.execute(
        "SELECT COUNT(*) AS c FROM requisitions WHERE status = 'Received'"
    ).fetchone()["c"]

    total_items = conn.execute("SELECT COUNT(*) AS c FROM inventory_items").fetchone()["c"]
    total_value = conn.execute("SELECT COALESCE(SUM(on_hand * unit_cost),0) AS v FROM inventory_items").fetchone()["v"]

    top_items = conn.execute(
        """
        SELECT description, SUM(qty) AS total_qty
        FROM usage_log
        GROUP BY description
        ORDER BY total_qty DESC, description ASC
        LIMIT 10
        """
    ).fetchall()

    trip_rows = conn.execute("SELECT employee, issued_at FROM usage_log ORDER BY employee, datetime(issued_at)").fetchall()
    trips = compute_trips(trip_rows)

    return {
        "low_stock": low_stock,
        "pending": pending,
        "open_req": open_req,
        "received": received,
        "total_items": total_items,
        "total_value": total_value,
        "top_items": top_items,
        "trips": trips,
    }


def compute_trips(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    by_emp: dict[str, list[datetime]] = defaultdict(list)
    for row in rows:
        by_emp[row["employee"]].append(datetime.fromisoformat(row["issued_at"]))
    result = []
    for emp, times in by_emp.items():
        times.sort()
        trip_count = 0
        last = None
        for t in times:
            if last is None or (t - last).total_seconds() > 60:
                trip_count += 1
            last = t
        result.append({"employee": emp, "trips": trip_count})
    result.sort(key=lambda x: x["trips"], reverse=True)
    return result


def current_step_name(status: str) -> str:
    return status


def next_status_for(action: str, current: str) -> str:
    mapping = {
        ("submit", "Draft"): "Awaiting First Approver",
        ("approve_first", "Awaiting First Approver"): "Awaiting Buyer Price Verification",
        ("approve_buyer", "Awaiting Buyer Price Verification"): "Awaiting Plant Manager Final Approval",
        ("approve_final", "Awaiting Plant Manager Final Approval"): "Awaiting Buyer PO Attachment",
        ("attach_po", "Awaiting Buyer PO Attachment"): "Ordered",
    }
    return mapping.get((action, current), current)


@app.on_event("startup")
def startup() -> None:
    templates.env.globals["requisition_total"] = requisition_total
    templates.env.globals["money"] = money
    init_templates()
    init_static()
    copy_assets()
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        stats = dashboard_stats(conn)
        requisitions = conn.execute(
            "SELECT * FROM requisitions ORDER BY datetime(updated_at) DESC LIMIT 10"
        ).fetchall()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            **auth_context(request),
            "stats": stats,
            "requisitions": requisitions,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if get_user_from_session(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            **auth_context(request),
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), theme: str = Form(DEFAULT_THEMES)):
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ? AND active = 1", (username.strip(),)).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return redirect_with_msg("/login", "Invalid username or password.", "error")
    token = SESSION_SERIALIZER.dumps({"username": row["username"]})
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("session", token, httponly=True, samesite="lax")
    if theme in THEMES:
        resp.set_cookie("theme", theme, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session")
    return resp


@app.post("/theme")
def set_theme(request: Request, theme: str = Form(DEFAULT_THEMES)):
    resp = RedirectResponse(request.headers.get("referer", "/"), status_code=303)
    resp.set_cookie("theme", theme if theme in THEMES else DEFAULT_THEMES, samesite="lax")
    return resp


@app.get("/inventory", response_class=HTMLResponse)
def inventory_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        items = conn.execute("SELECT * FROM inventory_items ORDER BY on_hand ASC, description ASC").fetchall()
        users = conn.execute("SELECT full_name, role FROM users WHERE active = 1 ORDER BY full_name ASC").fetchall()
    return templates.TemplateResponse(
        "inventory.html",
        {
            "request": request,
            **auth_context(request),
            "items": items,
            "users": users,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/inventory/add")
def add_inventory_item(
    request: Request,
    part_no: str = Form(...),
    description: str = Form(...),
    on_hand: int = Form(0),
    min_level: int = Form(0),
    reorder_qty: int = Form(0),
    unit_cost: float = Form(0),
    vendor: str = Form(""),
):
    user = require_login(request)
    require_role(user, ["admin", "plant_manager", "buyer"])
    with db() as conn:
        conn.execute(
            """
            INSERT INTO inventory_items (part_no, description, on_hand, min_level, reorder_qty, unit_cost, vendor, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(part_no) DO UPDATE SET
                description=excluded.description,
                on_hand=excluded.on_hand,
                min_level=excluded.min_level,
                reorder_qty=excluded.reorder_qty,
                unit_cost=excluded.unit_cost,
                vendor=excluded.vendor,
                updated_at=excluded.updated_at
            """,
            (part_no.strip(), description.strip(), on_hand, min_level, reorder_qty, unit_cost, vendor.strip(), now_iso()),
        )
    return redirect_with_msg("/inventory", "Inventory item saved.")


@app.post("/inventory/{item_id}/update")
def update_inventory_item(
    request: Request,
    item_id: int,
    description: str = Form(...),
    on_hand: int = Form(0),
    min_level: int = Form(0),
    reorder_qty: int = Form(0),
    unit_cost: float = Form(0),
    vendor: str = Form(""),
):
    user = require_login(request)
    require_role(user, ["admin", "plant_manager", "buyer"])
    with db() as conn:
        conn.execute(
            """
            UPDATE inventory_items
            SET description=?, on_hand=?, min_level=?, reorder_qty=?, unit_cost=?, vendor=?, updated_at=?
            WHERE id=?
            """,
            (description.strip(), on_hand, min_level, reorder_qty, unit_cost, vendor.strip(), now_iso(), item_id),
        )
    return redirect_with_msg("/inventory", "Inventory item updated.")


@app.post("/inventory/issue")
def issue_inventory(
    request: Request,
    employee: str = Form(...),
    part_no: str = Form(...),
    qty: int = Form(...),
):
    user = require_login(request)
    require_role(user, ["admin", "requester", "buyer", "plant_manager", "receiver", "first_approver"])
    if qty <= 0:
        return redirect_with_msg("/inventory", "Quantity must be greater than zero.", "error")
    with db() as conn:
        item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (part_no.strip(),)).fetchone()
        if not item:
            return redirect_with_msg("/inventory", "Item not found.", "error")
        if item["on_hand"] < qty:
            return redirect_with_msg("/inventory", "Not enough on hand to issue.", "error")
        new_on_hand = item["on_hand"] - qty
        total_cost = qty * float(item["unit_cost"] or 0)
        conn.execute(
            "UPDATE inventory_items SET on_hand=?, updated_at=? WHERE id=?",
            (new_on_hand, now_iso(), item["id"]),
        )
        conn.execute(
            """
            INSERT INTO usage_log (employee, part_no, description, qty, unit_cost, total_cost, issued_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (employee.strip(), item["part_no"], item["description"], qty, float(item["unit_cost"] or 0), total_cost, now_iso()),
        )
    return redirect_with_msg("/inventory", "Item issued and inventory updated.")


@app.get("/api/items/{part_no}")
def api_item(part_no: str):
    with db() as conn:
        item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (part_no.strip(),)).fetchone()
        if not item:
            return JSONResponse({"found": False})
        return JSONResponse(
            {
                "found": True,
                "part_no": item["part_no"],
                "description": item["description"],
                "unit_cost": item["unit_cost"],
                "on_hand": item["on_hand"],
                "min_level": item["min_level"],
                "reorder_qty": item["reorder_qty"],
                "vendor": item["vendor"],
            }
        )


@app.get("/requisitions", response_class=HTMLResponse)
def requisitions_page(request: Request, status: str = ""):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        if status:
            rows = conn.execute("SELECT * FROM requisitions WHERE status = ? ORDER BY datetime(created_at) DESC", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM requisitions ORDER BY datetime(created_at) DESC").fetchall()
    return templates.TemplateResponse(
        "requisitions.html",
        {
            "request": request,
            **auth_context(request),
            "requisitions": rows,
            "selected_status": status,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/requisitions/new", response_class=HTMLResponse)
def requisition_new(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        items = conn.execute("SELECT * FROM inventory_items ORDER BY description ASC").fetchall()
    return templates.TemplateResponse(
        "requisition_new.html",
        {
            "request": request,
            **auth_context(request),
            "items": items,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/requisitions/new")
async def create_requisition(
    request: Request,
    requester: str = Form(...),
    department: str = Form(...),
    notes: str = Form(""),
    part_no: list[str] = Form(default=[]),
    description: list[str] = Form(default=[]),
    qty: list[int] = Form(default=[]),
    unit_cost: list[float] = Form(default=[]),
):
    user = require_login(request)
    require_role(user, ["admin", "requester", "buyer", "plant_manager", "first_approver"])
    lines = []
    with db() as conn:
        for i in range(max(len(part_no), len(description), len(qty), len(unit_cost))):
            pn = (part_no[i].strip() if i < len(part_no) else "")
            desc = (description[i].strip() if i < len(description) else "")
            q = int(qty[i]) if i < len(qty) and str(qty[i]).strip() else 0
            cost = float(unit_cost[i]) if i < len(unit_cost) and str(unit_cost[i]).strip() else 0.0
            if not pn and not desc and q <= 0:
                continue
            if pn and not desc:
                item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (pn,)).fetchone()
                if item:
                    desc = item["description"]
                    if cost <= 0:
                        cost = float(item["unit_cost"] or 0)
            if q <= 0:
                continue
            if not pn:
                pn = f"MANUAL-{len(lines)+1}"
            lines.append((pn, desc, q, cost))
        if not lines:
            return redirect_with_msg("/requisitions/new", "Add at least one line item.", "error")
        req_no = generate_reference("RQ", conn)
        conn.execute(
            """
            INSERT INTO requisitions (req_no, requester, department, status, notes, current_step, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (req_no, requester.strip(), department.strip(), "Draft", notes.strip(), now_iso(), now_iso()),
        )
        req_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        for pn, desc, q, cost in lines:
            conn.execute(
                """
                INSERT INTO requisition_lines (requisition_id, part_no, description, qty, unit_cost, total_cost, received_qty)
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (req_id, pn, desc, q, cost, q * cost),
            )
        conn.execute(
            """
            INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
            VALUES (?, 'Draft', ?, 'Created', ?, ?)
            """,
            (req_id, user["full_name"], notes.strip(), now_iso()),
        )
    return redirect_with_msg(f"/requisitions/{req_id}", f"Requisition {req_no} created.")


@app.get("/requisitions/{req_id}", response_class=HTMLResponse)
def requisition_detail(request: Request, req_id: int):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        lines = conn.execute("SELECT * FROM requisition_lines WHERE requisition_id = ? ORDER BY id", (req_id,)).fetchall()
        history = conn.execute(
            "SELECT * FROM approval_history WHERE requisition_id = ? ORDER BY datetime(created_at) ASC, id ASC",
            (req_id,),
        ).fetchall()
        po = conn.execute("SELECT * FROM purchase_orders WHERE requisition_id = ?", (req_id,)).fetchone()
        receipt = conn.execute("SELECT * FROM receipts WHERE requisition_id = ? ORDER BY datetime(received_at) DESC LIMIT 1", (req_id,)).fetchone()
        items = conn.execute("SELECT * FROM inventory_items ORDER BY description ASC").fetchall()
    return templates.TemplateResponse(
        "requisition_detail.html",
        {
            "request": request,
            **auth_context(request),
            "req": req,
            "lines": lines,
            "history": history,
            "po": po,
            "receipt": receipt,
            "items": items,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/requisitions/{req_id}/action")
async def requisition_action(
    request: Request,
    req_id: int,
    action: str = Form(...),
    comment: str = Form(""),
    po_number: str = Form(""),
    vendor: str = Form(""),
    packing_list: UploadFile | None = File(default=None),
):
    user = require_login(request)
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        current_status = req["status"]

        def log(step: str, action_text: str, comment_text: str = "") -> None:
            conn.execute(
                """
                INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (req_id, step, user["full_name"], action_text, comment_text, now_iso()),
            )

        if action == "submit":
            require_role(user, ["admin", "requester", "buyer", "plant_manager", "first_approver"])
            if current_status != "Draft":
                return redirect_with_msg(f"/requisitions/{req_id}", "Only draft requisitions can be submitted.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting First Approver", 1, now_iso(), req_id),
            )
            log("Submission", "Submitted", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Sent to first approver.")

        if action == "approve_first":
            require_role(user, ["admin", "first_approver"])
            if current_status != "Awaiting First Approver":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for first approver.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting Buyer Price Verification", 2, now_iso(), req_id),
            )
            log("First Approver", "Approved", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Approved and sent to buyer for price verification.")

        if action == "approve_buyer":
            require_role(user, ["admin", "buyer"])
            if current_status != "Awaiting Buyer Price Verification":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for buyer verification.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting Plant Manager Final Approval", 3, now_iso(), req_id),
            )
            log("Buyer Verification", "Approved", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Approved and sent to plant manager.")

        if action == "approve_final":
            require_role(user, ["admin", "plant_manager"])
            if current_status != "Awaiting Plant Manager Final Approval":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for final approval.", "error")
            conn.execute(
                "UPDATE requisitions SET status=?, current_step=?, updated_at=? WHERE id=?",
                ("Awaiting Buyer PO Attachment", 4, now_iso(), req_id),
            )
            log("Plant Manager Final", "Approved", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Final approved. Buyer may attach PO.")

        if action == "attach_po":
            require_role(user, ["admin", "buyer"])
            if current_status != "Awaiting Buyer PO Attachment":
                return redirect_with_msg(f"/requisitions/{req_id}", "Not waiting for PO attachment.", "error")
            po_file_path = ""
            po_upload = None
            return redirect_with_msg(f"/requisitions/{req_id}", "Use the PO attachment form on the requisition page.", "error")

        if action == "receive":
            require_role(user, ["admin", "receiver", "buyer", "plant_manager"])
            if current_status not in ("Ordered", "Partially Received"):
                return redirect_with_msg(f"/requisitions/{req_id}", "Requisition is not ready to receive.", "error")

            form = await request.form()
            received_total = 0
            any_partial = False
            rows = conn.execute("SELECT * FROM requisition_lines WHERE requisition_id = ?", (req_id,)).fetchall()
            for line in rows:
                key = f"received_qty_{line['id']}"
                raw = form.get(key, "")
                recv_qty = int(raw) if str(raw).strip() else line["qty"] - line["received_qty"]
                recv_qty = max(0, min(recv_qty, line["qty"] - line["received_qty"]))
                if recv_qty:
                    item = conn.execute("SELECT * FROM inventory_items WHERE part_no = ?", (line["part_no"],)).fetchone()
                    if item:
                        conn.execute(
                            "UPDATE inventory_items SET on_hand = on_hand + ?, updated_at = ? WHERE part_no = ?",
                            (recv_qty, now_iso(), line["part_no"]),
                        )
                    conn.execute(
                        "UPDATE requisition_lines SET received_qty = received_qty + ? WHERE id = ?",
                        (recv_qty, line["id"]),
                    )
                    received_total += recv_qty
                    if line["received_qty"] + recv_qty < line["qty"]:
                        any_partial = True

            packing_file_path = ""
            if "packing_file" in form:
                # file fields won't be in request.form
                pass

            upload = None
            # use request.stream handled by multipart, rely on form field names in the template
            # The template posts one file input named packing_file; read via request.form isn't enough,
            # so the route is dual purpose: file is handled in a separate receiving endpoint on POST from the template.
            # The actual upload is processed below using request._form won't work, so we load from the request scope.
            # To keep this route robust, we accept receipt without the file if not available here.
            if any_partial:
                new_status = "Partially Received"
            else:
                remaining = conn.execute(
                    "SELECT SUM(qty - received_qty) AS r FROM requisition_lines WHERE requisition_id = ?",
                    (req_id,),
                ).fetchone()["r"] or 0
                new_status = "Received" if remaining == 0 else "Partially Received"

            conn.execute(
                "UPDATE requisitions SET status=?, updated_at=?, received_at=?, received_by=? WHERE id=?",
                (new_status, now_iso(), now_iso(), user["full_name"], req_id),
            )
            log("Receiving", "Received", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Receipt saved and inventory updated.")

        if action == "reject":
            require_role(user, ["admin", "first_approver", "buyer", "plant_manager"])
            conn.execute("UPDATE requisitions SET status=?, updated_at=? WHERE id=?", ("Rejected", now_iso(), req_id))
            log("Rejection", "Rejected", comment)
            return redirect_with_msg(f"/requisitions/{req_id}", "Requisition rejected.", "error")

    return redirect_with_msg(f"/requisitions/{req_id}", "Action not processed.", "error")


@app.post("/requisitions/{req_id}/attach-po")
async def attach_po(
    request: Request,
    req_id: int,
    po_number: str = Form(...),
    vendor: str = Form(""),
    po_file: UploadFile | None = File(default=None),
):
    user = require_login(request)
    require_role(user, ["admin", "buyer"])
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        if req["status"] != "Awaiting Buyer PO Attachment":
            return redirect_with_msg(f"/requisitions/{req_id}", "This requisition is not ready for PO attachment.", "error")
        file_path = ""
        if po_file and po_file.filename:
            ext = Path(po_file.filename).suffix.lower()
            safe_name = f"PO_{po_number}_{secrets.token_hex(4)}{ext}"
            dest = PO_DIR / safe_name
            content = await po_file.read()
            dest.write_bytes(content)
            file_path = str(dest.relative_to(BASE_DIR))
        conn.execute(
            """
            INSERT INTO purchase_orders (requisition_id, po_number, vendor, attachment, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(po_number) DO UPDATE SET
                vendor=excluded.vendor,
                attachment=excluded.attachment
            """,
            (req_id, po_number.strip(), vendor.strip(), file_path, user["full_name"], now_iso()),
        )
        conn.execute(
            "UPDATE requisitions SET po_number=?, status=?, updated_at=? WHERE id=?",
            (po_number.strip(), "Ordered", now_iso(), req_id),
        )
        conn.execute(
            """
            INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
            VALUES (?, 'Buyer PO Attachment', ?, 'PO Attached', ?, ?)
            """,
            (req_id, user["full_name"], vendor.strip(), now_iso()),
        )
    return redirect_with_msg(f"/requisitions/{req_id}", "PO attached and requisition marked Ordered.")


@app.post("/requisitions/{req_id}/receive")
async def receive_requisition(
    request: Request,
    req_id: int,
    packing_file: UploadFile | None = File(default=None),
    notes: str = Form(""),
):
    user = require_login(request)
    require_role(user, ["admin", "receiver", "buyer", "plant_manager"])
    form = await request.form()
    with db() as conn:
        req = conn.execute("SELECT * FROM requisitions WHERE id = ?", (req_id,)).fetchone()
        if not req:
            raise HTTPException(status_code=404, detail="Requisition not found")
        if req["status"] not in ("Ordered", "Partially Received"):
            return redirect_with_msg(f"/requisitions/{req_id}", "Requisition is not ready to receive.", "error")
        file_path = ""
        if packing_file and packing_file.filename:
            ext = Path(packing_file.filename).suffix.lower()
            safe_name = f"Packing_{req['req_no']}_{secrets.token_hex(4)}{ext}"
            dest = PACKING_DIR / safe_name
            content = await packing_file.read()
            dest.write_bytes(content)
            file_path = str(dest.relative_to(BASE_DIR))

        rows = conn.execute("SELECT * FROM requisition_lines WHERE requisition_id = ?", (req_id,)).fetchall()
        any_partial = False
        for line in rows:
            key = f"received_qty_{line['id']}"
            raw = form.get(key, "")
            recv_qty = int(raw) if str(raw).strip() else (line["qty"] - line["received_qty"])
            recv_qty = max(0, min(recv_qty, line["qty"] - line["received_qty"]))
            if recv_qty:
                conn.execute(
                    "UPDATE inventory_items SET on_hand = on_hand + ?, updated_at = ? WHERE part_no = ?",
                    (recv_qty, now_iso(), line["part_no"]),
                )
                conn.execute(
                    "UPDATE requisition_lines SET received_qty = received_qty + ? WHERE id = ?",
                    (recv_qty, line["id"]),
                )
            if (line["received_qty"] + recv_qty) < line["qty"]:
                any_partial = True

        remaining = conn.execute(
            "SELECT SUM(qty - received_qty) AS r FROM requisition_lines WHERE requisition_id = ?",
            (req_id,),
        ).fetchone()["r"] or 0

        new_status = "Partially Received" if remaining > 0 else "Received"
        conn.execute(
            """
            INSERT INTO receipts (requisition_id, received_by, packing_list_file, notes, received_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (req_id, user["full_name"], file_path, notes.strip(), now_iso()),
        )
        conn.execute(
            """
            UPDATE requisitions
            SET status=?, updated_at=?, received_at=?, received_by=?, packing_list_file=?
            WHERE id=?
            """,
            (new_status, now_iso(), now_iso(), user["full_name"], file_path, req_id),
        )
        conn.execute(
            """
            INSERT INTO approval_history (requisition_id, step_name, actor, action, comment, created_at)
            VALUES (?, 'Receiving', ?, ?, ?, ?)
            """,
            (req_id, user["full_name"], "Received", notes.strip(), now_iso()),
        )
    return redirect_with_msg(f"/requisitions/{req_id}", "Receiving complete and inventory updated.")


@app.get("/purchase-orders", response_class=HTMLResponse)
def purchase_orders_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        pos = conn.execute(
            """
            SELECT po.*, r.req_no, r.requester, r.status
            FROM purchase_orders po
            JOIN requisitions r ON r.id = po.requisition_id
            ORDER BY datetime(po.created_at) DESC
            """
        ).fetchall()
    return templates.TemplateResponse(
        "purchase_orders.html",
        {
            "request": request,
            **auth_context(request),
            "pos": pos,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/receiving", response_class=HTMLResponse)
def receiving_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM requisitions WHERE status IN ('Ordered','Partially Received') ORDER BY datetime(updated_at) DESC"
        ).fetchall()
    return templates.TemplateResponse(
        "receiving.html",
        {
            "request": request,
            **auth_context(request),
            "rows": rows,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    with db() as conn:
        top_items = conn.execute(
            """
            SELECT description, SUM(qty) AS total_qty, SUM(total_cost) AS total_cost
            FROM usage_log
            GROUP BY description
            ORDER BY total_qty DESC, description ASC
            LIMIT 20
            """
        ).fetchall()
        trips = compute_trips(conn.execute("SELECT employee, issued_at FROM usage_log ORDER BY employee, datetime(issued_at)").fetchall())
        low_stock = conn.execute("SELECT * FROM inventory_items WHERE on_hand <= min_level ORDER BY on_hand ASC").fetchall()
    return templates.TemplateResponse(
        "reports.html",
        {
            "request": request,
            **auth_context(request),
            "top_items": top_items,
            "trips": trips,
            "low_stock": low_stock,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user = get_user_from_session(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    require_role(user, ["admin"])
    with db() as conn:
        users = conn.execute("SELECT * FROM users ORDER BY username ASC").fetchall()
    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            **auth_context(request),
            "users": users,
            "roles": ROLES,
            "message": request.query_params.get("msg", ""),
            "kind": request.query_params.get("kind", "success"),
        },
    )


@app.post("/users/add")
def add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
):
    user = require_login(request)
    require_role(user, ["admin"])
    if role not in ROLES:
        return redirect_with_msg("/users", "Invalid role.", "error")
    with db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, full_name, role, active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (username.strip(), hash_password(password), full_name.strip(), role, now_iso()),
            )
        except sqlite3.IntegrityError:
            return redirect_with_msg("/users", "Username already exists.", "error")
    return redirect_with_msg("/users", "User added.")


@app.post("/users/{user_id}/toggle")
def toggle_user(request: Request, user_id: int):
    user = require_login(request)
    require_role(user, ["admin"])
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return redirect_with_msg("/users", "User not found.", "error")
        new_active = 0 if row["active"] else 1
        conn.execute("UPDATE users SET active = ? WHERE id = ?", (new_active, user_id))
    return redirect_with_msg("/users", "User status updated.")


@app.post("/delete/cleanup")
def cleanup_test_data(request: Request):
    user = require_login(request)
    require_role(user, ["admin"])
    return redirect_with_msg("/", "Cleanup unavailable in this build.")


def file_link(path: str) -> str:
    return f"/file/{path.replace(os.sep, '/')}"


@app.get("/file/{file_path:path}")
def serve_file(file_path: str):
    abs_path = (BASE_DIR / file_path).resolve()
    if not str(abs_path).startswith(str(BASE_DIR.resolve())) or not abs_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(abs_path))


if __name__ == "__main__":
    uvicorn.run("WH_ENTERPRISE_WEB:app", host="0.0.0.0", port=8000, reload=False)
