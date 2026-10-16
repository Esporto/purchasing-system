#!/usr/bin/env python3
"""
ALU-GLASS Procurement System - REST API backend (v3, MySQL)
============================================================
Standard library + mysqlclient. Run:  python backend_server.py

Prerequisites
    pip install mysqlclient
    mysql -u root -p < schema.sql

Environment variables (all optional)
    PROC_DB_HOST          MySQL host             (default 127.0.0.1)
    PROC_DB_PORT          MySQL port             (default 3306)
    PROC_DB_USER          MySQL user             (default root)
    PROC_DB_PASS          MySQL password         (default empty)
    PROC_DB_NAME          MySQL database         (default alu_glass_procurement)
    PROC_HOST             bind address           (default 127.0.0.1 = this machine only)
    PROC_PORT             port                   (default 8000)
    PROC_SECRET           token signing key      (default random; tokens reset on restart)
    PROC_ADMIN_PASSWORD   first-run admin password (default random, printed once)
    PROC_ALLOWED_ORIGINS  comma-separated browser origins allowed by CORS
    PROC_TOKEN_TTL        login lifetime in seconds (default 28800 = 8 h)
    PROC_ALLOW_SELF_APPROVAL  set to 1 to switch off the "different people" checks

Requisition workflow (server-enforced): create -> Step 1 (engineer/admin)
-> Step 2 (finance/admin) -> convert to PO(s) (purchasing/admin; one PO per vendor,
numbers from an atomic counter).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sys
import threading
import time
import traceback
from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import MySQLdb
import MySQLdb.cursors
from MySQLdb.constants import ER

BASE_DIR = Path(__file__).resolve().parent
DB_HOST = os.environ.get("PROC_DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("PROC_DB_PORT", "3306"))
DB_USER = os.environ.get("PROC_DB_USER", "root")
DB_PASS = os.environ.get("PROC_DB_PASS", "")
DB_NAME = os.environ.get("PROC_DB_NAME", "alu_glass_procurement")

HOST = os.environ.get("PROC_HOST", "127.0.0.1")
PORT = int(os.environ.get("PROC_PORT", "8000"))
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("PROC_ALLOWED_ORIGINS", "").split(",") if o.strip()}
TOKEN_TTL = int(os.environ.get("PROC_TOKEN_TTL", str(8 * 3600)))
MAX_BODY = 256 * 1024
INDEX_FILE = BASE_DIR / "index.html"
SECRET = os.environ["PROC_SECRET"].encode() if os.environ.get("PROC_SECRET") else secrets.token_bytes(32)

ROLES = ("admin", "purchasing", "engineer", "finance")
PO_STATUSES = ("Order Confirmed", "In Transit", "Arrived at Dock", "Delayed", "Received", "Cancelled")
LATE_CAPABLE = {"Order Confirmed", "In Transit", "Delayed"}
CLOSED_PO = {"Received", "Cancelled"}
METRIC_KEYS = ("price_metric", "quality_metric", "delivery_metric", "spec_metric", "terms_metric", "service_metric")
PRIORITIES = ("Routine", "Urgent", "Critical Line-Stop")
PR_PENDING1 = "Pending Step 1: Technical Review"
PR_PENDING2 = "Pending Step 2: Finance Authorization"
PR_APPROVED = "Approved"
PR_REJECTED = {1: "Rejected at Step 1: Technical Review", 2: "Rejected at Step 2: Finance Review"}
PR_CONVERTED = "Converted to PO"
PR_CANCELLED = "Cancelled"
PR_WRITERS = {"admin", "purchasing", "engineer"}
ROLE_LABELS = {"admin": "Master Admin / General Manager", "purchasing": "Purchasing Officer",
               "engineer": "Production Head / Tech Lead", "finance": "Finance Department Head"}
ALLOW_SELF_APPROVAL = os.environ.get("PROC_ALLOW_SELF_APPROVAL") == "1"


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# --------------------------------------------------------------------------- database
def connect() -> MySQLdb.Connection:
    return MySQLdb.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, passwd=DB_PASS,
        db=DB_NAME, charset="utf8mb4",
        cursorclass=MySQLdb.cursors.DictCursor,
        autocommit=False,
    )


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
            (DB_NAME, table, column))
        if cur.fetchone()["n"] == 0:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def stock_status(current: float, safety: float, reorder: float) -> str:
    if current < safety:
        return "low"
    if current <= reorder:
        return "reorder"
    return "safe"


def init_database() -> None:
    with closing(connect()) as conn, conn:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            tables = {list(r.values())[0] for r in cur.fetchall()}
        required = {"materials", "suppliers", "purchase_orders", "users",
                    "audit_log", "purchase_requisitions", "pr_items", "counters"}
        missing = required - tables
        if missing:
            raise SystemExit(
                f"Missing tables: {', '.join(sorted(missing))}. "
                f"Run schema.sql first:\n  mysql -u {DB_USER} -p < schema.sql"
            )

        # Forward-compat columns for databases seeded by older schemas
        _ensure_column(conn, "suppliers", "qc_rate", "VARCHAR(16) NULL")
        _ensure_column(conn, "materials", "usage_rate", "VARCHAR(40) NULL")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM materials")
            have_mat = cur.fetchone()["n"] > 0
            cur.execute("SELECT COUNT(*) AS n FROM suppliers")
            have_sup = cur.fetchone()["n"] > 0
        if not have_mat and not have_sup:
            seed_sample_records(conn)
        bootstrap_admin(conn)
    print(f"[DB] MySQL '{DB_NAME}' connected and verified.")


def seed_sample_records(conn) -> None:
    materials = [
        ("AL-76-SLD-BLK", "aluminum", "Sliding Frame Outer 76 Series", "Alloy 6063-T5 | 1.4mm | Powder Coated Matte Black RAL9005", "KG", 480, 300, 850, 2.65, "Asia Aluminum Extrusions Co.", "± 0.05 mm", "Craft paper bundles of 4 pcs", "7 days", "SD-100 Sliding Window"),
        ("AL-50-CSM-SLV", "aluminum", "Casement Window Sash 50 Series", "Alloy 6063-T5 | 1.4mm | Anodized Natural Silver AA15", "KG", 1200, 400, 900, 2.75, "Asia Aluminum Extrusions Co.", "± 0.04 mm", "Master bundles with plastic separation", "7 days", "CW-50 Outward Casement"),
        ("GL-TMP-08-CLR", "glass", "8mm Clear Fully Tempered Glass", "Nominal 8mm | Flat polished edge | Arrissed corners", "SQM", 145, 100, 220, 15.50, "Crystal Float & Tempered Glass Ltd.", "± 0.2 mm", "A-frame timber crates with cork pads", "5 days", "Sliding Patio Doors"),
        ("GL-IGU-24-LOWE", "glass", "Double Glazed Unit (6+12A+6)", "6mm Clear Low-E + 12mm Argon + 6mm Clear Tempered", "SQM", 210, 80, 160, 38.00, "Crystal Float & Tempered Glass Ltd.", "Dual sealed polyisobutylene", "Export wooden crates", "10 days", "Thermal Facades"),
        ("HD-ROL-TDM-120", "hardware", "Heavy Duty Tandem Roller 120KG", "SUS304 Stainless Steel Housing | Dual POM Wheels", "PAIR", 240, 200, 450, 4.80, "Kinlong Fenestration Hardware Co.", "120KG rating / 100,000 cycles", "50 Pairs per carton", "10 days", "SD-100 Patio Door"),
        ("SL-EPDM-GSK-01", "sealant", "EPDM Wedge Gasket Strip", "Peroxide cured EPDM rubber | UV resistant | Shore A 65", "METER", 850, 1000, 2500, 0.32, "PolyTech Rubber & Polymer Industries", "-40°C to +120°C", "Spools of 250 Meters", "6 days", "Glazing bead retention"),
        ("HD-LCK-MLT-BLK", "hardware", "Multipoint Casement Lock Set", "Zinc alloy die-cast handle | Matte black finish | SUS304 transmission bar", "SET", 520, 150, 300, 9.20, "Kinlong Fenestration Hardware Co.", "Backset 22mm | Salt spray resistance 480 hours", "Individually boxed with all strike plates and screws", "10 days", "CW-50 Outward Windows"),
        ("SL-SIL-STR-BLK", "sealant", "Neutral Structural Silicone 590ml", "High tensile structural sealant | Matte Black | Shelf-life: 12 months", "SAUSAGE", 420, 150, 320, 4.90, "Sika Architectural Adhesives", "ASTM C1184 compliant | Shore A 40", "Box of 20 Sausages with nozzles", "4 days", "Structural curtain wall & window perimeter sealing"),
    ]
    ts = now_iso()
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO materials (code, category, name, specs, uom, current_stock, safety_stock,
               reorder_point, std_cost, supplier, status, tolerance, packaging, lead_time, bom_link,
               updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9],
              stock_status(m[5], m[6], m[7]), m[10], m[11], m[12], m[13], ts) for m in materials])

        usage = {"AL-76-SLD-BLK": "80 KG / day", "AL-50-CSM-SLV": "50 KG / day",
                 "GL-TMP-08-CLR": "20 SQM / day", "GL-IGU-24-LOWE": "12 SQM / day",
                 "HD-ROL-TDM-120": "25 Pairs / day", "HD-LCK-MLT-BLK": "15 Sets / day",
                 "SL-EPDM-GSK-01": "200 Meters / day", "SL-SIL-STR-BLK": "18 Sausages / day"}
        cur.executemany("UPDATE materials SET usage_rate = %s WHERE code = %s",
                        [(v, k) for k, v in usage.items()])

        no_metrics = (None,) * 6
        suppliers = [
            ("VND-ALU-01", "Asia Aluminum Extrusions Co.", "Aluminum Profiles", "Tier 1: Preferred", 92, (23, 24, 19, 14, 8, 4), "Net 45 Days", "7 Days", "Chen Wei (+855 12 889 001)", "97.4%", "99.1%"),
            ("VND-GLS-02", "Crystal Float & Tempered Glass Ltd.", "Architectural Glass", "Tier 1: Preferred", 89, (21, 25, 18, 14, 7, 4), "Net 30 Days", "5 Days", "Sokha Mean (+855 16 445 221)", "95.8%", "99.4%"),
            ("VND-HDW-03", "Kinlong Fenestration Hardware Co.", "Hardware & Accessories", "Tier 1: Preferred", 88, (22, 24, 18, 14, 6, 4), "Net 30 Days", "10 Days", "Li Qiang (+855 92 110 998)", "96.2%", "98.8%"),
            ("VND-RUB-04", "PolyTech Rubber & Polymer Industries", "EPDM Gaskets & Seals", "Tier 2: Conditional", 78, no_metrics, "Net 15 Days", "6 Days", "Rithy Heng (+855 11 332 990)", "88.5%", "96.2%"),
            ("VND-ADH-05", "Sika Architectural Adhesives", "Silicones & Chemicals", "Tier 1: Preferred", 94, no_metrics, "Net 60 Days", "4 Days", "Technical Sourcing Desk (+855 23 881 772)", "99.0%", "99.8%"),
            ("VND-GLS-06", "Mekong Safety Glass Backup Ltd.", "Secondary Glass Sourcing", "Tier 2: Conditional", 74, no_metrics, "Cash in Advance", "8 Days", "Bona Keo (+855 77 554 112)", "89.0%", "95.5%"),
        ]
        cur.executemany(
            """INSERT INTO suppliers (id, name, category, tier, score, price_metric, quality_metric,
               delivery_metric, spec_metric, terms_metric, service_metric, payment_terms, lead_time,
               contact, otif, qc_rate, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(s[0], s[1], s[2], s[3], s[4], *s[5], s[6], s[7], s[8], s[9], s[10], ts) for s in suppliers])

        orders = [
            ("PO-2026-089", "Asia Aluminum Extrusions Co.", "AL-76 Sliding Frame Outer (2,500 KG)", 6625.00, "2026-09-24", "In Transit", "On Track", 75, "Coordinate crane with Warehouse."),
            ("PO-2026-092", "PolyTech Rubber & Polymer Industries", "SL-EPDM Wedge Gaskets (3,000 M)", 960.00, "2026-09-20", "Delayed", "On Track", 40, "Urgent expediting: factory needs stock."),
            ("PO-2026-094", "Crystal Float & Tempered Glass Ltd.", "GL-TMP-08 8mm Tempered Glass (85 SQM)", 1317.50, "2026-09-22", "Arrived at Dock", "Inspection Today", 90, "Truck unloading at Bay 2. QC checking scratches."),
            ("PO-2026-095", "Kinlong Fenestration Hardware Co.", "HD-ROL-TDM Heavy Duty Rollers (500 Pairs)", 2400.00, "2026-09-28", "Order Confirmed", "On Track", 30, "Vendor acknowledged PO."),
        ]
        cur.executemany(
            """INSERT INTO purchase_orders (po_number, vendor, items, amount_usd, due_date, status,
               alert, progress_pct, dock_action, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [o + (ts,) for o in orders])
    seed_requisitions(conn, ts)


def seed_requisitions(conn, ts) -> None:
    none5 = (None,) * 5
    prs = [
        ("PR-2026-001", "Production - Fabrication Line A", "Alex Miller", "2026-09-30", "Urgent", PR_PENDING1,
         "SD-100 Sliding Patio Series - Tower A", none5, none5, [("AL-76-SLD-BLK", 1000), ("SL-EPDM-GSK-01", 500)]),
        ("PR-2026-002", "Production - CNC & Glazing Bay", "Somnang Seng", "2026-10-02", "Routine", PR_PENDING2,
         "CW-50 Commercial Window Glazing",
         ("Approved", "Dara Vuth", "Production Head / Tech Lead", "2026-09-26 14:30", "Tolerances & CNC notch drawings verified with factory line."),
         none5, [("GL-TMP-08-CLR", 200)]),
        ("PR-2026-003", "Site Installation Team", "Bunroeun Meas", "2026-09-28", "Critical Line-Stop", PR_APPROVED,
         "SD-100 Heavy Duty Sliding Door",
         ("Approved", "Dara Vuth", "Production Head / Tech Lead", "2026-09-25 09:15", "Hardware specs checked and approved."),
         ("Approved", "Alex Miller", "Master Admin / General Manager", "2026-09-25 11:20", "Budget verified against Project Cost Code #CW-09."),
         [("HD-ROL-TDM-120", 350), ("HD-LCK-MLT-BLK", 120)]),
    ]
    with conn.cursor() as cur:
        for num, dept, who, due, prio, status, project, s1, s2, lines in prs:
            cur.execute(
                """INSERT INTO purchase_requisitions (pr_number, department, requester, required_date,
                   priority, status, bom_project, step1_decision, step1_by, step1_role, step1_date,
                   step1_notes, step2_decision, step2_by, step2_role, step2_date, step2_notes,
                   revisions, po_numbers, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (num, dept, who, due, prio, status, project, *s1, *s2, "[]", "[]", ts))
            for n, (code, qty) in enumerate(lines, 1):
                cur.execute("SELECT name, specs, uom, std_cost FROM materials WHERE code = %s", (code,))
                m = cur.fetchone()
                cur.execute(
                    """INSERT INTO pr_items (pr_number, line_no, item_code, item_name, item_specs,
                       quantity, uom, unit_rate) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (num, n, code, m["name"], m["specs"], qty, m["uom"], m["std_cost"]))


def bootstrap_admin(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM users")
        if cur.fetchone()["n"]:
            return
    given = os.environ.get("PROC_ADMIN_PASSWORD")
    password = given or secrets.token_urlsafe(12)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, full_name, role, status) VALUES (%s,%s,%s,%s,%s)",
            ("admin", hash_password(password), "Administrator", "admin", "allowed"))
    if not given:
        print("=" * 60)
        print(f"  First run: created user 'admin' with password:  {password}")
        print("  Shown once - log in and change it (POST /api/users).")
        print("=" * 60)


def audit(conn, user, action: str, resource: str, key=None, detail=None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_log (ts, username, action, resource, `key`, detail) VALUES (%s,%s,%s,%s,%s,%s)",
            (now_iso(), user["username"] if user else "system", action, resource, key,
             json.dumps(detail, ensure_ascii=False)[:1000] if detail is not None else None))


# --------------------------------------------------------------------------- security
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, hash_b64 = stored.split("$")
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64),
                            n=2 ** 14, r=8, p=1, dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("timing-equaliser")


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_token(username: str) -> str:
    payload = _b64u(json.dumps({"u": username, "exp": int(time.time()) + TOKEN_TTL}).encode())
    return f"{payload}.{_b64u(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())}"


def read_token(token: str):
    try:
        payload, sig = token.split(".")
        if not hmac.compare_digest(sig, _b64u(hmac.new(SECRET, payload.encode(), hashlib.sha256).digest())):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return data if data["exp"] >= time.time() else None
    except (ValueError, KeyError, TypeError):
        return None


LOCK_WINDOW, LOCK_MAX = 300, 5
_failures: dict[str, list[float]] = {}
_fail_lock = threading.Lock()


def is_throttled(key: str) -> bool:
    with _fail_lock:
        now = time.time()
        recent = [t for t in _failures.get(key, []) if now - t < LOCK_WINDOW]
        if recent:
            _failures[key] = recent
        else:
            _failures.pop(key, None)
        return len(recent) >= LOCK_MAX


def record_failure(key: str) -> None:
    with _fail_lock:
        _failures.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    with _fail_lock:
        _failures.pop(key, None)


# --------------------------------------------------------------------------- validation
def as_str(name, v, maxlen=300) -> str:
    if not isinstance(v, str):
        raise ApiError(400, f"'{name}' must be text")
    v = v.strip()
    if len(v) > maxlen:
        raise ApiError(400, f"'{name}' is longer than {maxlen} characters")
    return v


def as_num(name, v, lo=0.0, hi=1e9) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ApiError(400, f"'{name}' must be a number")
    try:
        n = float(v)
    except ValueError:
        raise ApiError(400, f"'{name}' must be a number") from None
    if not math.isfinite(n) or n < lo or n > hi:
        raise ApiError(400, f"'{name}' must be between {lo:g} and {hi:g}")
    return n


def T(maxlen=200, optional=False):
    def check(name, v):
        if v is None and optional:
            return None
        s = as_str(name, v, maxlen)
        if not s and not optional:
            raise ApiError(400, f"'{name}' cannot be empty")
        return s or None
    return check


def N(lo=0.0, hi=1e9):
    return lambda name, v: as_num(name, v, lo, hi)


def I(lo=0, hi=100):
    def check(name, v):
        n = as_num(name, v, lo, hi)
        if n != int(n):
            raise ApiError(400, f"'{name}' must be a whole number")
        return int(n)
    return check


def D():
    def check(name, v):
        try:
            return date.fromisoformat(as_str(name, v, 10)).isoformat()
        except ValueError:
            raise ApiError(400, f"'{name}' must be a date like 2026-09-24") from None
    return check


def E(*options):
    def check(name, v):
        if v not in options:
            raise ApiError(400, f"'{name}' must be one of: {', '.join(options)}")
        return v
    return check


# --------------------------------------------------------------------------- resources
def require_supplier(conn, name: str, field: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM suppliers WHERE name = %s", (name,))
        if cur.fetchone() is None:
            raise ApiError(400, f"Unknown supplier in '{field}': {name!r}. Create the supplier first.")


def fin_materials(conn, m, clean, existing):
    if "supplier" in clean:
        require_supplier(conn, m["supplier"], "supplier")
    m["status"] = stock_status(m["current_stock"], m["safety_stock"], m["reorder_point"])
    return {"status"}


def fin_suppliers(conn, s, clean, existing):
    if existing is not None and "name" in clean and clean["name"] != existing["name"]:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM materials WHERE supplier = %s", (existing["name"],))
            used = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM purchase_orders WHERE vendor = %s", (existing["name"],))
            used += cur.fetchone()["n"]
        if used:
            raise ApiError(409, "Supplier is referenced by materials/POs and cannot be renamed")
    metrics = [s.get(k) for k in METRIC_KEYS]
    if set(METRIC_KEYS) & set(clean) and all(m is not None for m in metrics):
        if sum(metrics) > 100:
            raise ApiError(400, "Scorecard metrics add up to more than 100")
        s["score"] = sum(metrics)
        return {"score"}
    return set()


def fin_orders(conn, o, clean, existing):
    if "vendor" in clean:
        require_supplier(conn, o["vendor"], "vendor")
    return set()


RESOURCES = {
    "materials": dict(
        name="materials", table="materials", pk="code", order="code ASC", write_roles={"admin", "purchasing"},
        fields={"code": T(40), "category": T(40), "name": T(120), "specs": T(300), "uom": T(16),
                "current_stock": N(), "safety_stock": N(), "reorder_point": N(), "std_cost": N(),
                "supplier": T(120), "status": T(16), "tolerance": T(120, True), "packaging": T(120, True),
                "lead_time": T(40, True), "bom_link": T(120, True), "usage_rate": T(40, True)},
        derived={"status"}, required=("code", "category", "name", "specs", "uom", "supplier"),
        defaults={"current_stock": 0.0, "safety_stock": 0.0, "reorder_point": 0.0, "std_cost": 0.0,
                  "tolerance": None, "packaging": None, "lead_time": None, "bom_link": None, "usage_rate": None},
        finalize=fin_materials),
    "suppliers": dict(
        name="suppliers", table="suppliers", pk="id", order="score DESC, name ASC", write_roles={"admin", "purchasing"},
        fields={"id": T(40), "name": T(120), "category": T(80), "tier": T(40), "score": I(),
                **{k: I() for k in METRIC_KEYS}, "payment_terms": T(40), "lead_time": T(40),
                "contact": T(160), "otif": T(16, True), "qc_rate": T(16, True)},
        derived=set(), required=("id", "name", "category", "tier", "payment_terms", "lead_time", "contact"),
        defaults={"score": 0, **{k: None for k in METRIC_KEYS}, "otif": None, "qc_rate": None},
        finalize=fin_suppliers),
    "orders": dict(
        name="orders", table="purchase_orders", pk="po_number", order="due_date ASC", write_roles={"admin", "purchasing"},
        fields={"po_number": T(40), "vendor": T(120), "items": T(400), "amount_usd": N(),
                "due_date": D(), "status": E(*PO_STATUSES), "alert": T(80, True), "progress_pct": I(),
                "dock_action": T(300, True)},
        derived=set(), required=("po_number", "vendor", "items", "amount_usd", "due_date"),
        defaults={"status": "Order Confirmed", "alert": "On Track", "progress_pct": 25, "dock_action": None},
        finalize=fin_orders),
}
IGNORED_INPUT = {"created_at", "updated_at", "days_overdue"}


def days_overdue(row) -> int:
    if row["status"] not in LATE_CAPABLE:
        return 0
    try:
        return max((date.today() - date.fromisoformat(str(row["due_date"]))).days, 0)
    except (ValueError, TypeError):
        return 0


def decorate(res, row) -> dict:
    d = dict(row)
    # JSON columns come back as strings from mysqlclient — parse them for the client
    for k in ("revisions", "po_numbers", "detail"):
        if k in d and isinstance(d[k], (str, bytes)):
            try:
                d[k] = json.loads(d[k])
            except (ValueError, TypeError):
                d[k] = [] if k in ("revisions", "po_numbers") else None
    # Decimal -> float for JSON serialisation
    for k, v in list(d.items()):
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    if res["name"] == "orders":
        n = days_overdue(row)
        d["days_overdue"] = n
        if n:
            d["alert"] = f"🔴 {n} Day{'s' if n != 1 else ''} Overdue"
    return d


def fetch_one(conn, res, key):
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {res['table']} WHERE {res['pk']} = %s", (key,))
        row = cur.fetchone()
    if row is None:
        raise ApiError(404, f"{res['name']} record {key!r} not found")
    return row


def upsert(conn, res, body, user, key=None, update_only=False):
    fields, derived, pk = res["fields"], res["derived"], res["pk"]
    unknown = set(body) - set(fields) - IGNORED_INPUT
    if unknown:
        raise ApiError(400, "Unknown field(s): " + ", ".join(sorted(unknown)))
    clean = {k: fields[k](k, v) for k, v in body.items() if k in fields and k not in derived}
    if key is not None:
        if pk in clean and clean[pk] != key:
            raise ApiError(400, f"'{pk}' in the body does not match the URL")
        clean[pk] = key
    if not clean.get(pk):
        raise ApiError(400, f"'{pk}' is required")
    key = clean[pk]

    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {res['table']} WHERE {pk} = %s", (key,))
        existing = cur.fetchone()

    if existing is None:
        if update_only:
            raise ApiError(404, f"{res['name']} record {key!r} not found")
        missing = [f for f in res["required"] if clean.get(f) in (None, "")]
        if missing:
            raise ApiError(400, "Missing required field(s): " + ", ".join(missing))
        merged = {**res["defaults"], **clean}
    else:
        merged = {**dict(existing), **clean}

    written_derived = res["finalize"](conn, merged, clean, existing)
    merged["updated_at"] = now_iso()
    with conn.cursor() as cur:
        if existing is None:
            cols = [c for c in fields if c in merged] + ["updated_at"]
            placeholders = ", ".join(["%s"] * len(cols))
            cur.execute(
                f"INSERT INTO {res['table']} ({', '.join(cols)}) VALUES ({placeholders})",
                [merged[c] for c in cols])
        else:
            cols = [c for c in fields if c != pk and (c in clean or c in written_derived)] + ["updated_at"]
            set_clause = ", ".join(f"{c} = %s" for c in cols)
            cur.execute(
                f"UPDATE {res['table']} SET {set_clause} WHERE {pk} = %s",
                [merged[c] for c in cols] + [key])
    audit(conn, user, "create" if existing is None else "update", res["name"], key, clean)
    return existing is None, fetch_one(conn, res, key)


def delete_record(conn, res, key, user) -> None:
    row = fetch_one(conn, res, key)
    if res["name"] == "suppliers":
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM materials WHERE supplier = %s", (row["name"],))
            mats = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM purchase_orders WHERE vendor = %s", (row["name"],))
            pos = cur.fetchone()["n"]
        if mats or pos:
            raise ApiError(409, f"Supplier is still used by {mats} material(s) and {pos} purchase order(s)")
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {res['table']} WHERE {res['pk']} = %s", (key,))
    audit(conn, user, "delete", res["name"], key, dict(row))


def landed_cost(body) -> dict:
    def dec(name, default, lo=Decimal(0), hi=None) -> Decimal:
        try:
            d = Decimal(str(body.get(name, default)))
        except InvalidOperation:
            raise ApiError(400, f"'{name}' must be a number") from None
        if not d.is_finite() or d < lo or (hi is not None and d > hi):
            raise ApiError(400, f"'{name}' is out of range")
        return d

    qty, price = dec("qty", 1), dec("unit_price", 0)
    discount = dec("discount_pct", 0, hi=Decimal(100))
    freight, other = dec("freight_cost", 0), dec("other_cost", 0)
    if qty <= 0:
        raise ApiError(400, "'qty' must be greater than zero")
    net = price * (1 - discount / 100)
    overhead = (freight + other) / qty
    q4, q2 = Decimal("0.0001"), Decimal("0.01")
    return {
        "base_unit_price": float(price), "discount_applied": float(discount),
        "net_purchase_price": float(net.quantize(q4, ROUND_HALF_UP)),
        "overhead_per_unit": float(overhead.quantize(q4, ROUND_HALF_UP)),
        "true_landed_cost_per_unit": float((net + overhead).quantize(q4, ROUND_HALF_UP)),
        "total_shipment_investment": float((net * qty + freight + other).quantize(q2, ROUND_HALF_UP)),
    }


def kpi_summary(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT status, due_date, amount_usd FROM purchase_orders")
        orders = cur.fetchall()
        cur.execute("SELECT status FROM materials")
        stock = [r["status"] for r in cur.fetchall()]
        cur.execute("SELECT status FROM purchase_requisitions")
        prs = [r["status"] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) AS n FROM suppliers")
        vendors = cur.fetchone()["n"]
    open_orders = [o for o in orders if o["status"] not in CLOSED_PO]
    return {
        "active_skus": len(stock),
        "active_vendors": vendors,
        "open_po_value": round(sum(float(o["amount_usd"]) for o in open_orders), 2),
        "open_po_count": len(open_orders),
        "delayed_shipments": sum(1 for o in open_orders if o["status"] == "Delayed" or days_overdue(o) > 0),
        "low_stock_skus": stock.count("low"),
        "reorder_skus": stock.count("reorder"),
        "prs_pending_step1": prs.count(PR_PENDING1),
        "prs_pending_step2": prs.count(PR_PENDING2),
        "prs_approved_awaiting_po": prs.count(PR_APPROVED),
    }


# --------------------------------------------------------------------------- requisitions
ITEM_FIELDS = {"item_code", "item_name", "item_specs", "quantity", "uom", "unit_rate"}


def page_args(q) -> tuple[int, int]:
    def num(name, default, lo, hi):
        v = q.get(name, [str(default)])[0]
        return min(max(int(v), lo), hi) if v.isdigit() else default
    return num("limit", 200, 1, 1000), num("offset", 0, 0, 10 ** 9)


def next_number(conn, prefix: str, table: str, col: str) -> str:
    year = date.today().year
    name = f"{prefix}-{year}"
    with conn.cursor() as cur:
        cur.execute("SELECT value FROM counters WHERE name = %s", (name,))
        row = cur.fetchone()
        if row is None:
            top = 0
            cur.execute(f"SELECT {col} FROM {table} WHERE {col} LIKE %s", (f"{prefix}-{year}-%",))
            for r in cur.fetchall():
                m = re.fullmatch(rf"{prefix}-{year}-(\d+)", r[col])
                if m:
                    top = max(top, int(m.group(1)))
            cur.execute("INSERT INTO counters (name, value) VALUES (%s, %s)", (name, top))
        while True:
            cur.execute("UPDATE counters SET value = value + 1 WHERE name = %s", (name,))
            cur.execute("SELECT value FROM counters WHERE name = %s", (name,))
            n = cur.fetchone()["value"]
            candidate = f"{prefix}-{year}-{n:03d}"
            cur.execute(f"SELECT 1 FROM {table} WHERE {col} = %s LIMIT 1", (candidate,))
            if cur.fetchone() is None:
                return candidate


def pr_dict(row, items) -> dict:
    d = {k: row[k] for k in ("pr_number", "department", "requester", "required_date", "priority",
                             "status", "bom_project", "created_at", "updated_at")}
    for k, v in list(d.items()):
        if isinstance(v, (date, datetime)):
            d[k] = v.isoformat()
    d["items"] = [{"item_code": i["item_code"], "item_name": i["item_name"],
                   "item_specs": i["item_specs"], "quantity": float(i["quantity"]),
                   "uom": i["uom"], "unit_rate": float(i["unit_rate"]),
                   "extended_total": round(float(i["quantity"]) * float(i["unit_rate"]), 2)}
                  for i in items]
    d["estimated_total"] = round(sum(i["extended_total"] for i in d["items"]), 2)
    for n in (1, 2):
        decision = row[f"step{n}_decision"] or ""
        d[f"step{n}"] = {"decision": decision, "approved": decision == "Approved",
                         "rejected": decision == "Rejected",
                         "by": row[f"step{n}_by"] or "", "role": row[f"step{n}_role"] or "",
                         "date": row[f"step{n}_date"] or "", "notes": row[f"step{n}_notes"] or ""}
    # mysqlclient returns JSON columns as strings
    for json_col, target in (("revisions", "revisions"), ("po_numbers", "po_numbers")):
        raw = row[json_col]
        if isinstance(raw, (str, bytes)):
            try:
                d[target] = json.loads(raw)
            except (ValueError, TypeError):
                d[target] = []
        else:
            d[target] = raw or []
    return d


def load_prs(conn, where: str = "", params=(), limit: int = 200, offset: int = 0) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM purchase_requisitions {where} "
            "ORDER BY created_at DESC, pr_number DESC LIMIT %s OFFSET %s",
            (*params, limit, offset))
        rows = cur.fetchall()
        by_pr: dict[str, list] = {r["pr_number"]: [] for r in rows}
        if rows:
            marks = ",".join(["%s"] * len(by_pr))
            cur.execute(
                f"SELECT * FROM pr_items WHERE pr_number IN ({marks}) "
                "ORDER BY pr_number, line_no",
                list(by_pr.keys()))
            for it in cur.fetchall():
                by_pr[it["pr_number"]].append(it)
    return [pr_dict(r, by_pr[r["pr_number"]]) for r in rows]


def get_pr(conn, number: str) -> dict:
    found = load_prs(conn, "WHERE pr_number = %s", (number,), 1, 0)
    if not found:
        raise ApiError(404, f"Requisition {number!r} not found")
    return found[0]


def clean_items(conn, raw) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ApiError(400, "'items' must be a list of 1 to 50 lines")
    out = []
    for i, it in enumerate(raw, 1):
        if not isinstance(it, dict):
            raise ApiError(400, f"items[{i}] must be an object")
        extra = set(it) - ITEM_FIELDS - {"extended_total"}
        if extra:
            raise ApiError(400, f"items[{i}] has unknown field(s): " + ", ".join(sorted(extra)))
        code = T(40)(f"items[{i}].item_code", it.get("item_code"))
        with conn.cursor() as cur:
            cur.execute("SELECT name, specs, uom, std_cost FROM materials WHERE code = %s", (code,))
            mat = cur.fetchone()

        def pick(field, check, fallback, i=i, it=it):
            if field in it:
                return check(f"items[{i}].{field}", it[field])
            if fallback is None:
                raise ApiError(400, f"items[{i}].{field} is required (item not in catalogue)")
            return fallback

        out.append({
            "item_code": code,
            "item_name": pick("item_name", T(120), mat["name"] if mat else None),
            "item_specs": pick("item_specs", T(300, True), mat["specs"] if mat else ""),
            "quantity": pick("quantity", N(1e-6, 1e9), None),
            "uom": pick("uom", T(16), mat["uom"] if mat else None),
            "unit_rate": pick("unit_rate", N(), float(mat["std_cost"]) if mat else None),
        })
    return out


def write_items(conn, number: str, items) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pr_items WHERE pr_number = %s", (number,))
        cur.executemany(
            """INSERT INTO pr_items (pr_number, line_no, item_code, item_name, item_specs,
               quantity, uom, unit_rate) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(number, n, i["item_code"], i["item_name"], i["item_specs"],
              i["quantity"], i["uom"], i["unit_rate"]) for n, i in enumerate(items, 1)])


def reject_unknown(body, allowed) -> None:
    extra = set(body) - set(allowed)
    if extra:
        raise ApiError(400, "Unknown field(s): " + ", ".join(sorted(extra)))


def create_pr(conn, user, body) -> str:
    reject_unknown(body, {"department", "priority", "required_date", "bom_project", "items"})
    for f in ("department", "priority", "required_date", "items"):
        if f not in body:
            raise ApiError(400, f"'{f}' is required")
    department = T(80)("department", body["department"])
    priority = E(*PRIORITIES)("priority", body["priority"])
    required = D()("required_date", body["required_date"])
    bom = T(120, True)("bom_project", body.get("bom_project"))
    items = clean_items(conn, body["items"])
    number = next_number(conn, "PR", "purchase_requisitions", "pr_number")
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO purchase_requisitions (pr_number, department, requester, requested_by,
               required_date, priority, status, bom_project, revisions, po_numbers, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (number, department, user["full_name"], user["username"], required, priority,
             PR_PENDING1, bom, "[]", "[]", now_iso()))
    write_items(conn, number, items)
    audit(conn, user, "create", "requisitions", number, {"lines": len(items), "priority": priority})
    return number


def approve_pr(conn, user, number, body) -> None:
    reject_unknown(body, {"step", "decision", "remarks"})
    step = body.get("step")
    if type(step) is not int or step not in (1, 2):
        raise ApiError(400, "'step' must be 1 or 2")
    decision = E("Approved", "Rejected")("decision", body.get("decision"))
    remarks = T(500, True)("remarks", body.get("remarks"))
    if decision == "Rejected" and not remarks:
        raise ApiError(400, "A reason ('remarks') is required when rejecting a requisition")
    if user["role"] not in ({"engineer", "admin"} if step == 1 else {"finance", "admin"}):
        raise ApiError(403, "Step 1 needs the Production/Tech Lead (or admin); Step 2 needs the Finance Head (or admin)")
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM purchase_requisitions WHERE pr_number = %s", (number,))
        row = cur.fetchone()
    if row is None:
        raise ApiError(404, f"Requisition {number!r} not found")
    if row["status"] != (PR_PENDING1 if step == 1 else PR_PENDING2):
        raise ApiError(409, f"{number} is not awaiting Step {step} (current status: {row['status']})")
    if not ALLOW_SELF_APPROVAL:
        if row["requested_by"] == user["username"]:
            raise ApiError(409, "You cannot approve a requisition you raised yourself")
        if step == 2 and row["step1_user"] == user["username"]:
            raise ApiError(409, "Step 1 and Step 2 must be signed by different people")
    status = PR_REJECTED[step] if decision == "Rejected" else (PR_PENDING2 if step == 1 else PR_APPROVED)
    ts = now_iso()
    with conn.cursor() as cur:
        cur.execute(
            f"""UPDATE purchase_requisitions SET status = %s, step{step}_decision = %s, step{step}_by = %s,
                step{step}_role = %s, step{step}_date = %s, step{step}_notes = %s, step{step}_user = %s,
                updated_at = %s WHERE pr_number = %s""",
            (status, decision, user["full_name"], ROLE_LABELS[user["role"]], ts, remarks,
             user["username"], ts, number))
    audit(conn, user, decision.lower(), "requisitions", number, {"step": step, "remarks": remarks})


def revise_pr(conn, user, number, body) -> None:
    reject_unknown(body, {"required_date", "bom_project", "items", "changelog"})
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM purchase_requisitions WHERE pr_number = %s", (number,))
        row = cur.fetchone()
    if row is None:
        raise ApiError(404, f"Requisition {number!r} not found")
    if row["status"] not in PR_REJECTED.values():
        raise ApiError(409, "Only a rejected requisition can be revised and resubmitted")
    changelog = T(500)("changelog", body.get("changelog"))
    required = D()("required_date", body["required_date"]) if "required_date" in body else row["required_date"]
    bom = T(120, True)("bom_project", body["bom_project"]) if "bom_project" in body else row["bom_project"]
    if "items" in body:
        write_items(conn, number, clean_items(conn, body["items"]))
    raw_rev = row["revisions"]
    revisions = json.loads(raw_rev) if isinstance(raw_rev, (str, bytes)) else (raw_rev or [])
    revisions.insert(0, {"revision_date": now_iso(), "revised_by": user["full_name"],
                         "notes": changelog, "previous_state": row["status"]})
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE purchase_requisitions SET status = %s, required_date = %s, bom_project = %s,
               revisions = %s, step1_decision = NULL, step1_by = NULL, step1_role = NULL,
               step1_date = NULL, step1_notes = NULL, step1_user = NULL,
               step2_decision = NULL, step2_by = NULL, step2_role = NULL,
               step2_date = NULL, step2_notes = NULL, step2_user = NULL, updated_at = %s
               WHERE pr_number = %s""",
            (PR_PENDING1, required, bom, json.dumps(revisions, ensure_ascii=False), now_iso(), number))
    audit(conn, user, "revise", "requisitions", number, {"notes": changelog})


def cancel_pr(conn, user, number) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM purchase_requisitions WHERE pr_number = %s", (number,))
        row = cur.fetchone()
    if row is None:
        raise ApiError(404, f"Requisition {number!r} not found")
    if row["status"] in (PR_CONVERTED, PR_CANCELLED):
        raise ApiError(409, f"A requisition that is '{row['status']}' cannot be cancelled")
    with conn.cursor() as cur:
        cur.execute("UPDATE purchase_requisitions SET status = %s, updated_at = %s WHERE pr_number = %s",
                    (PR_CANCELLED, now_iso(), number))
    audit(conn, user, "cancel", "requisitions", number)


def convert_pr(conn, user, number, body) -> list[str]:
    reject_unknown(body, {"vendors"})
    vendors = body.get("vendors", {})
    if not isinstance(vendors, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in vendors.items()):
        raise ApiError(400, "'vendors' must map item codes to supplier names")
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM purchase_requisitions WHERE pr_number = %s", (number,))
        row = cur.fetchone()
    if row is None:
        raise ApiError(404, f"Requisition {number!r} not found")
    if row["status"] != PR_APPROVED:
        raise ApiError(409, f"Only an Approved requisition can be converted (current status: {row['status']})")
    groups: dict[str, list] = {}
    missing = []
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM pr_items WHERE pr_number = %s ORDER BY line_no", (number,))
        items = cur.fetchall()
        for it in items:
            vendor = vendors.get(it["item_code"])
            if vendor is None:
                cur.execute("SELECT supplier FROM materials WHERE code = %s", (it["item_code"],))
                m = cur.fetchone()
                vendor = m["supplier"] if m else None
            if not vendor:
                missing.append(it["item_code"])
                continue
            require_supplier(conn, vendor, f"vendors[{it['item_code']}]")
            groups.setdefault(vendor, []).append(it)
    if missing:
        raise ApiError(400, "No supplier known for: " + ", ".join(missing) + " - pass them in 'vendors'")
    ts, created = now_iso(), []
    for vendor, lines in groups.items():
        po = next_number(conn, "PO", "purchase_orders", "po_number")
        summary = ", ".join(
            f"{l['item_name']} ({float(l['quantity']):g} {l['uom']})" for l in lines)[:400]
        amount = round(sum(float(l["quantity"]) * float(l["unit_rate"]) for l in lines), 2)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO purchase_orders (po_number, vendor, items, amount_usd, due_date,
                   status, alert, progress_pct, dock_action, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (po, vendor, summary, amount, row["required_date"], "Order Confirmed", "On Track",
                 25, f"Converted from {number} by {user['full_name']}. Vendor notification pending.", ts))
        created.append(po)
    with conn.cursor() as cur:
        cur.execute("UPDATE purchase_requisitions SET status = %s, po_numbers = %s, updated_at = %s "
                    "WHERE pr_number = %s",
                    (PR_CONVERTED, json.dumps(created), ts, number))
    audit(conn, user, "convert", "requisitions", number, {"purchase_orders": created})
    return created


# --------------------------------------------------------------------------- HTTP layer
class Handler(BaseHTTPRequestHandler):
    server_version = "ProcurementAPI/3.0"

    def _cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Max-Age", "600")

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode())

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ApiError(400, "Invalid Content-Length") from None
        if length < 0:
            raise ApiError(400, "Invalid Content-Length")
        if length > MAX_BODY:
            raise ApiError(413, "Request body too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "Body must be valid JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "JSON body must be an object")
        return data

    def current_user(self, roles=None) -> dict:
        auth = self.headers.get("Authorization", "")
        data = read_token(auth[7:]) if auth.startswith("Bearer ") else None
        if not data:
            raise ApiError(401, "Authentication required (missing, invalid or expired token)")
        with closing(connect()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username, full_name, role, status FROM users WHERE username = %s",
                            (data["u"],))
                row = cur.fetchone()
        if row is None or row["status"] != "allowed":
            raise ApiError(401, "Account is not active")
        if roles and row["role"] not in roles:
            raise ApiError(403, "Your role is not permitted to do this")
        return dict(row)

    def _dispatch(self, method: str) -> None:
        try:
            if method == "OPTIONS":
                return self._send(204, b"")
            url = urlparse(self.path)
            parts = [unquote(p) for p in url.path.split("/") if p]
            if method == "GET" and parts in ([], ["index.html"]):
                if not INDEX_FILE.is_file():
                    raise ApiError(404, "index.html not found next to backend_server.py")
                return self._send(200, INDEX_FILE.read_bytes(), "text/html; charset=utf-8")
            if not parts or parts[0] != "api":
                raise ApiError(404, "Endpoint not found")
            status, payload = self.route(method, parts[1:], parse_qs(url.query))
            self._json(status, payload)
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except MySQLdb.IntegrityError:
            self._json(409, {"error": "Conflict: the record violates a uniqueness or integrity rule"})
        except MySQLdb.OperationalError:
            traceback.print_exc()
            self._json(503, {"error": "Database temporarily unavailable"})
        except Exception:
            traceback.print_exc()
            self._json(500, {"error": "Internal server error"})

    do_GET = lambda self: self._dispatch("GET")
    do_POST = lambda self: self._dispatch("POST")
    do_PUT = lambda self: self._dispatch("PUT")
    do_DELETE = lambda self: self._dispatch("DELETE")
    do_OPTIONS = lambda self: self._dispatch("OPTIONS")

    def route(self, method, p, q):
        if p == ["health"] and method == "GET":
            return 200, {"status": "ok"}
        if p == ["login"] and method == "POST":
            return self.login()
        if p == ["me"] and method == "GET":
            u = self.current_user()
            return 200, {"username": u["username"], "full_name": u["full_name"], "role": u["role"],
                         "role_label": ROLE_LABELS[u["role"]]}
        if p == ["kpi-summary"] and method == "GET":
            self.current_user()
            with closing(connect()) as conn:
                return 200, kpi_summary(conn)
        if p == ["calculate-landed-cost"] and method == "POST":
            self.current_user()
            return 200, landed_cost(self.read_json())
        if p == ["audit"] and method == "GET":
            self.current_user({"admin"})
            limit = int(q.get("limit", ["100"])[0]) if q.get("limit", ["100"])[0].isdigit() else 100
            with closing(connect()) as conn, conn.cursor() as cur:
                cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s",
                            (min(max(limit, 1), 1000),))
                rows = cur.fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("detail"), (str, bytes)):
                    try:
                        d["detail"] = json.loads(d["detail"])
                    except (ValueError, TypeError):
                        pass
                out.append(d)
            return 200, out
        if p and p[0] == "users":
            return self.users(method, p[1:])
        if p and p[0] == "prs":
            return self.prs(method, p[1:], q)
        if p and p[0] in RESOURCES:
            return self.resource(method, RESOURCES[p[0]], p[1:], q)
        raise ApiError(404, "Endpoint not found")

    def login(self):
        body = self.read_json()
        username = str(body.get("username", "")).strip().lower()
        password = body.get("password")
        if not username or not isinstance(password, str):
            raise ApiError(400, "username and password are required")
        key = f"{self.client_address[0]}|{username}"
        if is_throttled(key):
            raise ApiError(429, "Too many failed attempts. Try again in a few minutes.")
        with closing(connect()) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cur.fetchone()
        ok = verify_password(password, row["password_hash"] if row else DUMMY_HASH) and row is not None
        if not ok:
            record_failure(key)
            raise ApiError(401, "Invalid credentials")
        if row["status"] != "allowed":
            raise ApiError(403, "This account has been revoked. Contact an administrator.")
        clear_failures(key)
        with closing(connect()) as conn, conn:
            audit(conn, {"username": username}, "login", "users", username)
        return 200, {"token": make_token(username), "expires_in": TOKEN_TTL,
                     "user": {"username": username, "full_name": row["full_name"], "role": row["role"],
                              "role_label": ROLE_LABELS[row["role"]]}}

    def users(self, method, rest):
        admin = self.current_user({"admin"})
        if method == "GET" and not rest:
            with closing(connect()) as conn, conn.cursor() as cur:
                cur.execute("SELECT username, full_name, role, status, created_at "
                            "FROM users ORDER BY username")
                rows = cur.fetchall()
            return 200, [{**dict(r), "role_label": ROLE_LABELS[r["role"]]} for r in rows]
        if method == "POST" and not rest:
            body = self.read_json()
            username = as_str("username", body.get("username", "")).lower()
            if not re.fullmatch(r"[a-z0-9._-]{3,32}", username):
                raise ApiError(400, "'username' must be 3-32 chars: a-z, 0-9, dot, dash, underscore")
            password = body.get("password")
            if password is not None and (not isinstance(password, str) or len(password) < 8):
                raise ApiError(400, "'password' must be text of at least 8 characters")
            with closing(connect()) as conn, conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                    row = cur.fetchone()
                if row is None and password is None:
                    raise ApiError(400, "'password' is required for a new user")
                new = {
                    "full_name": T(80)("full_name", body["full_name"]) if "full_name" in body
                                 else (row["full_name"] if row else None),
                    "role": E(*ROLES)("role", body["role"]) if "role" in body
                            else (row["role"] if row else None),
                    "status": E("allowed", "revoked")("status", body["status"]) if "status" in body
                              else (row["status"] if row else "allowed"),
                }
                if None in (new["full_name"], new["role"]):
                    raise ApiError(400, "'full_name' and 'role' are required for a new user")
                if row is not None and row["role"] == "admin" and (new["role"] != "admin" or new["status"] != "allowed"):
                    with conn.cursor() as cur:
                        cur.execute("SELECT COUNT(*) AS n FROM users "
                                    "WHERE role='admin' AND status='allowed' AND username <> %s",
                                    (username,))
                        others = cur.fetchone()["n"]
                    if others == 0:
                        raise ApiError(409, "Cannot demote or revoke the last active administrator")
                pw_hash = hash_password(password) if password else (row["password_hash"] if row else None)
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO users (username, password_hash, full_name, role, status)
                           VALUES (%s,%s,%s,%s,%s) AS new
                           ON DUPLICATE KEY UPDATE password_hash = new.password_hash,
                             full_name = new.full_name, role = new.role, status = new.status""",
                        (username, pw_hash, new["full_name"], new["role"], new["status"]))
                audit(conn, admin, "create" if row is None else "update", "users", username,
                      {**new, "password_changed": password is not None})
            return (201 if row is None else 200), {"username": username, **new}
        raise ApiError(405, "Method not allowed")

    def prs(self, method, rest, q):
        number = rest[0] if rest else None
        action = rest[1] if len(rest) == 2 else None
        if len(rest) > 2:
            raise ApiError(404, "Endpoint not found")
        if method == "GET" and action is None:
            self.current_user()
            with closing(connect()) as conn:
                if number:
                    return 200, get_pr(conn, number)
                limit, offset = page_args(q)
                return 200, load_prs(conn, "", (), limit, offset)
        if method == "POST" and number is None:
            user = self.current_user(PR_WRITERS)
            body = self.read_json()
            with closing(connect()) as conn, conn:
                created = create_pr(conn, user, body)
                return 201, get_pr(conn, created)
        if number is None:
            raise ApiError(405, "Method not allowed")
        if method == "POST" and action == "approve":
            user = self.current_user()
            body = self.read_json()
            with closing(connect()) as conn, conn:
                approve_pr(conn, user, number, body)
                return 200, get_pr(conn, number)
        if method == "POST" and action == "convert":
            user = self.current_user({"admin", "purchasing"})
            body = self.read_json()
            with closing(connect()) as conn, conn:
                created = convert_pr(conn, user, number, body)
                orders = [decorate(RESOURCES["orders"], fetch_one(conn, RESOURCES["orders"], po))
                          for po in created]
                return 200, {"requisition": get_pr(conn, number), "purchase_orders": orders}
        if method == "POST" and action == "cancel":
            user = self.current_user(PR_WRITERS)
            with closing(connect()) as conn, conn:
                cancel_pr(conn, user, number)
                return 200, get_pr(conn, number)
        if method == "PUT" and action is None:
            user = self.current_user(PR_WRITERS)
            body = self.read_json()
            with closing(connect()) as conn, conn:
                revise_pr(conn, user, number, body)
                return 200, get_pr(conn, number)
        if method == "DELETE" and action is None:
            user = self.current_user({"admin"})
            with closing(connect()) as conn, conn:
                pr = get_pr(conn, number)
                if pr["status"] == PR_CONVERTED:
                    raise ApiError(409, "A requisition converted to PO(s) cannot be deleted")
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM purchase_requisitions WHERE pr_number = %s", (number,))
                audit(conn, user, "delete", "requisitions", number,
                      {"status": pr["status"], "total": pr["estimated_total"]})
            return 200, {"deleted": True, "pr_number": number}
        raise ApiError(405, "Method not allowed")

    def resource(self, method, res, rest, q):
        if method == "GET":
            self.current_user()
            with closing(connect()) as conn:
                if rest:
                    return 200, decorate(res, fetch_one(conn, res, rest[0]))

                def num(name, default, lo, hi):
                    v = q.get(name, [str(default)])[0]
                    return min(max(int(v), lo), hi) if v.isdigit() else default

                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT * FROM {res['table']} ORDER BY {res['order']} LIMIT %s OFFSET %s",
                        (num("limit", 200, 1, 1000), num("offset", 0, 0, 10 ** 9)))
                    rows = cur.fetchall()
                return 200, [decorate(res, r) for r in rows]
        if method in ("POST", "PUT"):
            user = self.current_user(res["write_roles"])
            body = self.read_json()
            with closing(connect()) as conn, conn:
                created, row = upsert(conn, res, body, user,
                                      key=rest[0] if rest else None,
                                      update_only=(method == "PUT"))
            return (201 if created else 200), decorate(res, row)
        if method == "DELETE":
            user = self.current_user({"admin"})
            key = rest[0] if rest else q.get(res["pk"], [None])[0]
            if not key:
                raise ApiError(400, f"Provide the record key: /api/{res['name']}/<{res['pk']}>")
            with closing(connect()) as conn, conn:
                delete_record(conn, res, key, user)
            return 200, {"deleted": True, res["pk"]: key}
        raise ApiError(405, "Method not allowed")


def main() -> None:
    init_database()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0", "") else HOST
    print("=" * 60)
    print(f"  Procurement API v3 on http://{HOST}:{PORT}   (app: http://{shown}:{PORT}/)")
    print(f"  MySQL: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    if not os.environ.get("PROC_SECRET"):
        print("  Note: PROC_SECRET not set - logins reset when the server restarts.")
    if HOST not in ("127.0.0.1", "localhost"):
        print("  Warning: listening beyond this machine without TLS - use HTTPS for anything but a trusted LAN.")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping procurement server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()