#!/usr/bin/env python3
"""
ALU-GLASS Procurement System - REST API backend (v2)
====================================================
Standard library only (http.server + sqlite3). Run:  python backend_server.py

Environment variables (all optional)
    PROC_HOST             bind address            (default 127.0.0.1 = this machine only)
    PROC_PORT             port                    (default 8000)
    PROC_DB               SQLite file             (default ./procurement_data.db)
    PROC_SECRET           token signing key       (default random; tokens reset on restart)
    PROC_ADMIN_PASSWORD   first-run admin password (default random, printed once)
    PROC_ALLOWED_ORIGINS  comma-separated browser origins allowed by CORS
                          (default none; index.html is served at "/" so same-origin works)
    PROC_TOKEN_TTL        login lifetime in seconds (default 28800 = 8 h)
    PROC_ALLOW_SELF_APPROVAL  set to 1 to switch off the "different people" approval checks
                          (a single person may raise a PR and sign both steps - small teams/testing)
    PROC_PRICE_TOLERANCE_PCT  3-way match: allowed invoice-vs-PO rate difference in %   (default 0)
    PROC_QTY_TOLERANCE_PCT    3-way match: allowed invoice-vs-accepted quantity excess in % (default 0)
    PROC_OVER_RECEIPT_PCT     dock receiving: allowed accepted quantity above the PO in %   (default 0)
    PROC_GRN_UPDATES_STOCK    1 (default): accepted goods increase the material's stock balance; 0 = leave stock alone

Logistics (Phase 3): receive against a PO line by line (Form 04 GRN) -> rejected goods go to quarantine with an NCR
-> QC decides (return / concession / scrap) -> supplier invoice is 3-way matched (PO rate = GRN accepted qty = invoice)
-> Finance releases payment only when matched (admin can override with a reason).

Requisition workflow (server-enforced): create -> Step 1 (engineer/admin) -> Step 2 (finance/admin)
-> convert to PO(s) (purchasing/admin; one PO per vendor, numbers from an atomic counter).

Main changes from v1
    * Authentication (scrypt-hashed passwords, signed expiring tokens) and
      server-side role checks. Revoking a user takes effect on their next request.
    * Binds to localhost by default; CORS is an allow-list instead of "*".
    * Threaded server, request-size limit, JSON/field validation with 400/404/409
      instead of generic 500s; internal error details are no longer leaked.
    * Partial updates: writing one field no longer resets the others
      (v1's INSERT OR REPLACE wiped supplier scorecards and created_at).
    * Derived values are computed, not trusted: stock status from stock levels,
      overdue alerts from due dates, supplier score from its six metrics.
    * Referential checks (material/PO -> supplier) and audit log of every change.
    * Landed cost uses Decimal and rejects qty <= 0, negative costs, discount > 100.
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
import sqlite3
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

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = os.environ.get("PROC_DB", str(BASE_DIR / "procurement_data.db"))
HOST = os.environ.get("PROC_HOST", "127.0.0.1")
PORT = int(os.environ.get("PROC_PORT", "8000"))
ALLOWED_ORIGINS = {o.strip() for o in os.environ.get("PROC_ALLOWED_ORIGINS", "").split(",") if o.strip()}
TOKEN_TTL = int(os.environ.get("PROC_TOKEN_TTL", str(8 * 3600)))
MAX_BODY = 256 * 1024
INDEX_FILE = BASE_DIR / "index.html"
STATIC_TYPES = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
SECRET = os.environ["PROC_SECRET"].encode() if os.environ.get("PROC_SECRET") else secrets.token_bytes(32)

ROLES = ("admin", "purchasing", "engineer", "finance", "warehouse")
PO_STATUSES = ("Order Confirmed", "In Transit", "Arrived at Dock", "Delayed", "Partially Delivered (Open Balance)", "Dock Received", "Received", "Cancelled")
LATE_CAPABLE = {"Order Confirmed", "In Transit", "Delayed", "Partially Delivered (Open Balance)"}   # statuses that can be "overdue"
CLOSED_PO = {"Received", "Cancelled", "Dock Received"}
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
               "engineer": "Production Head / Tech Lead", "finance": "Finance Department Head",
               "warehouse": "Warehouse Clerk"}
ALLOW_SELF_APPROVAL = os.environ.get("PROC_ALLOW_SELF_APPROVAL") == "1"
PRICE_TOL = Decimal(os.environ.get("PROC_PRICE_TOLERANCE_PCT", "0"))
QTY_TOL = Decimal(os.environ.get("PROC_QTY_TOLERANCE_PCT", "0"))
OVER_RECEIPT = Decimal(os.environ.get("PROC_OVER_RECEIPT_PCT", "0"))
GRN_UPDATES_STOCK = os.environ.get("PROC_GRN_UPDATES_STOCK", "1") == "1"
PO_PARTIAL, PO_DOCK_RECEIVED = "Partially Delivered (Open Balance)", "Dock Received"
RECEIVABLE = {"Order Confirmed", "In Transit", "Arrived at Dock", "Delayed", PO_PARTIAL}
DISPOSITIONS = ("Return to Vendor", "Accept under Concession", "Scrap")
NCR_OPEN, NCR_CLOSED = "Open - In Quarantine", "Closed"
GRN_PASSED, GRN_QUARANTINED, GRN_RESOLVED = "Inspected & Passed", "Quarantined / Defect", "Defect Resolved"
INV_MATCHED, INV_HELD = "Matched - Ready for Payment", "Held - Variance"
INV_RELEASED, INV_OVERRIDE = "Released for Payment", "Released (Override)"
RECEIVERS, QC_ROLES, AP_ROLES = {"warehouse", "purchasing", "admin"}, {"engineer", "admin"}, {"finance", "admin"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


# --------------------------------------------------------------------------- database
def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stock_status(current: float, safety: float, reorder: float) -> str:
    """Same rule as the web app: at/below safety stock -> reorder (urgent); at/below reorder point -> low; else safe."""
    if current <= safety:
        return "reorder"
    if current <= reorder:
        return "low"
    return "safe"


def init_database() -> None:
    with closing(connect()) as conn, conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS materials (
            code TEXT PRIMARY KEY, category TEXT NOT NULL, name TEXT NOT NULL, specs TEXT NOT NULL,
            uom TEXT NOT NULL, current_stock REAL DEFAULT 0, safety_stock REAL DEFAULT 0,
            reorder_point REAL DEFAULT 0, std_cost REAL DEFAULT 0, supplier TEXT NOT NULL,
            status TEXT NOT NULL, tolerance TEXT, packaging TEXT, lead_time TEXT, bom_link TEXT,
            usage_rate TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS suppliers (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, tier TEXT NOT NULL,
            score INTEGER DEFAULT 0, price_metric INTEGER, quality_metric INTEGER, delivery_metric INTEGER,
            spec_metric INTEGER, terms_metric INTEGER, service_metric INTEGER,
            payment_terms TEXT NOT NULL, lead_time TEXT NOT NULL, contact TEXT NOT NULL, otif TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_number TEXT PRIMARY KEY, vendor TEXT NOT NULL, items TEXT NOT NULL, amount_usd REAL NOT NULL,
            due_date TEXT NOT NULL, status TEXT NOT NULL, alert TEXT NOT NULL DEFAULT 'On Track',
            progress_pct INTEGER DEFAULT 25, dock_action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, full_name TEXT NOT NULL,
            role TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'allowed',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT NOT NULL,
            action TEXT NOT NULL, resource TEXT NOT NULL, key TEXT, detail TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_suppliers_name ON suppliers(name);
        CREATE TABLE IF NOT EXISTS purchase_requisitions (
            pr_number TEXT PRIMARY KEY, department TEXT NOT NULL, requester TEXT NOT NULL, requested_by TEXT,
            required_date TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL, bom_project TEXT,
            step1_decision TEXT, step1_by TEXT, step1_role TEXT, step1_date TEXT, step1_notes TEXT, step1_user TEXT,
            step2_decision TEXT, step2_by TEXT, step2_role TEXT, step2_date TEXT, step2_notes TEXT, step2_user TEXT,
            revisions TEXT NOT NULL DEFAULT '[]', po_numbers TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pr_items (
            pr_number TEXT NOT NULL REFERENCES purchase_requisitions(pr_number) ON DELETE CASCADE,
            line_no INTEGER NOT NULL, item_code TEXT NOT NULL, item_name TEXT NOT NULL, item_specs TEXT,
            quantity REAL NOT NULL, uom TEXT NOT NULL, unit_rate REAL NOT NULL,
            PRIMARY KEY (pr_number, line_no)
        );
        CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS po_items (
            po_number TEXT NOT NULL REFERENCES purchase_orders(po_number) ON DELETE CASCADE,
            line_no INTEGER NOT NULL, item_code TEXT NOT NULL, item_name TEXT NOT NULL,
            quantity REAL NOT NULL, uom TEXT NOT NULL, unit_rate REAL NOT NULL,
            PRIMARY KEY (po_number, line_no)
        );
        CREATE TABLE IF NOT EXISTS grns (
            grn_number TEXT PRIMARY KEY, po_number TEXT NOT NULL REFERENCES purchase_orders(po_number),
            vendor TEXT NOT NULL, delivery_note TEXT NOT NULL, vehicle_plate TEXT NOT NULL, dock_bay TEXT NOT NULL,
            received_by TEXT NOT NULL, received_by_user TEXT, received_at TEXT NOT NULL, dock_notes TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_grn_delivery_note ON grns(vendor, delivery_note);
        CREATE TABLE IF NOT EXISTS grn_items (
            grn_number TEXT NOT NULL REFERENCES grns(grn_number) ON DELETE CASCADE,
            line_no INTEGER NOT NULL, item_code TEXT NOT NULL, item_name TEXT NOT NULL, uom TEXT NOT NULL,
            unit_rate REAL NOT NULL, ordered_qty REAL NOT NULL, arrived_qty REAL NOT NULL,
            accepted_qty REAL NOT NULL, rejected_qty REAL NOT NULL, rejection_reason TEXT,
            PRIMARY KEY (grn_number, line_no)
        );
        CREATE TABLE IF NOT EXISTS ncrs (
            ncr_number TEXT PRIMARY KEY, grn_number TEXT NOT NULL REFERENCES grns(grn_number),
            po_number TEXT NOT NULL, item_code TEXT NOT NULL, item_name TEXT NOT NULL, quantity REAL NOT NULL,
            uom TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, disposition TEXT, resolution_notes TEXT,
            resolved_by TEXT, resolved_at TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invoices (
            ap_number TEXT PRIMARY KEY, vendor_invoice_no TEXT NOT NULL,
            po_number TEXT NOT NULL REFERENCES purchase_orders(po_number), vendor TEXT NOT NULL,
            invoice_date TEXT NOT NULL, status TEXT NOT NULL, match_report TEXT NOT NULL DEFAULT '{}',
            invoice_total REAL NOT NULL, entered_by TEXT NOT NULL, entered_by_user TEXT, entered_at TEXT NOT NULL,
            released_by TEXT, released_at TEXT, override_reason TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ux_invoice_vendor_no ON invoices(vendor, vendor_invoice_no);
        CREATE TABLE IF NOT EXISTS invoice_items (
            ap_number TEXT NOT NULL REFERENCES invoices(ap_number) ON DELETE CASCADE,
            line_no INTEGER NOT NULL, item_code TEXT NOT NULL, quantity REAL NOT NULL, unit_rate REAL NOT NULL,
            PRIMARY KEY (ap_number, line_no)
        );
        """)
        # migrate databases created by v1
        for table in ("materials", "suppliers", "purchase_orders"):
            _ensure_column(conn, table, "updated_at", "TIMESTAMP")
        _ensure_column(conn, "suppliers", "qc_rate", "TEXT")
        _ensure_column(conn, "materials", "usage_rate", "TEXT")

        if conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0] == 0 and \
           conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0] == 0:
            seed_sample_records(conn)
        seed_po_lines(conn)
        bootstrap_admin(conn)
    print("[DB] SQLite database initialized and verified.")


def seed_sample_records(conn) -> None:
    # (code, category, name, specs, uom, stock, safety, reorder, std_cost, supplier, tolerance, packaging, lead_time, bom_link)
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
    conn.executemany(
        """INSERT INTO materials (code, category, name, specs, uom, current_stock, safety_stock, reorder_point,
           std_cost, supplier, status, tolerance, packaging, lead_time, bom_link, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9],
          stock_status(m[5], m[6], m[7]), m[10], m[11], m[12], m[13], ts) for m in materials])
    usage = {"AL-76-SLD-BLK": "80 KG / day", "AL-50-CSM-SLV": "50 KG / day", "GL-TMP-08-CLR": "20 SQM / day",
             "GL-IGU-24-LOWE": "12 SQM / day", "HD-ROL-TDM-120": "25 Pairs / day", "HD-LCK-MLT-BLK": "15 Sets / day",
             "SL-EPDM-GSK-01": "200 Meters / day", "SL-SIL-STR-BLK": "18 Sausages / day"}
    conn.executemany("UPDATE materials SET usage_rate = ? WHERE code = ?", [(v, k) for k, v in usage.items()])

    # (id, name, category, tier, score, six metrics or None, payment, lead, contact, otif, qc)
    # Scorecard breakdowns were only available for the first three suppliers.
    no_metrics = (None,) * 6
    suppliers = [
        ("VND-ALU-01", "Asia Aluminum Extrusions Co.", "Aluminum Profiles", "Tier 1: Preferred", 92, (23, 24, 19, 14, 8, 4), "Net 45 Days", "7 Days", "Chen Wei (+855 12 889 001)", "97.4%", "99.1%"),
        ("VND-GLS-02", "Crystal Float & Tempered Glass Ltd.", "Architectural Glass", "Tier 1: Preferred", 89, (21, 25, 18, 14, 7, 4), "Net 30 Days", "5 Days", "Sokha Mean (+855 16 445 221)", "95.8%", "99.4%"),
        ("VND-HDW-03", "Kinlong Fenestration Hardware Co.", "Hardware & Accessories", "Tier 1: Preferred", 88, (22, 24, 18, 14, 6, 4), "Net 30 Days", "10 Days", "Li Qiang (+855 92 110 998)", "96.2%", "98.8%"),
        ("VND-RUB-04", "PolyTech Rubber & Polymer Industries", "EPDM Gaskets & Seals", "Tier 2: Conditional", 78, no_metrics, "Net 15 Days", "6 Days", "Rithy Heng (+855 11 332 990)", "88.5%", "96.2%"),
        ("VND-ADH-05", "Sika Architectural Adhesives", "Silicones & Chemicals", "Tier 1: Preferred", 94, no_metrics, "Net 60 Days", "4 Days", "Technical Sourcing Desk (+855 23 881 772)", "99.0%", "99.8%"),
        ("VND-GLS-06", "Mekong Safety Glass Backup Ltd.", "Secondary Glass Sourcing", "Tier 2: Conditional", 74, no_metrics, "Cash in Advance", "8 Days", "Bona Keo (+855 77 554 112)", "89.0%", "95.5%"),
    ]
    conn.executemany(
        """INSERT INTO suppliers (id, name, category, tier, score, price_metric, quality_metric, delivery_metric,
           spec_metric, terms_metric, service_metric, payment_terms, lead_time, contact, otif, qc_rate, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(s[0], s[1], s[2], s[3], s[4], *s[5], s[6], s[7], s[8], s[9], s[10], ts) for s in suppliers])

    orders = [
        ("PO-2026-089", "Asia Aluminum Extrusions Co.", "AL-76 Sliding Frame Outer (2,500 KG)", 6625.00, "2026-09-24", "In Transit", "On Track", 75, "Coordinate crane with Warehouse."),
        ("PO-2026-092", "PolyTech Rubber & Polymer Industries", "SL-EPDM Wedge Gaskets (3,000 M)", 960.00, "2026-09-20", "Delayed", "On Track", 40, "Urgent expediting: factory needs stock."),
        ("PO-2026-094", "Crystal Float & Tempered Glass Ltd.", "GL-TMP-08 8mm Tempered Glass (85 SQM)", 1317.50, "2026-09-22", "Arrived at Dock", "Inspection Today", 90, "Truck unloading at Bay 2. QC checking scratches."),
        ("PO-2026-095", "Kinlong Fenestration Hardware Co.", "HD-ROL-TDM Heavy Duty Rollers (500 Pairs)", 2400.00, "2026-09-28", "Order Confirmed", "On Track", 30, "Vendor acknowledged PO."),
    ]
    conn.executemany(
        """INSERT INTO purchase_orders (po_number, vendor, items, amount_usd, due_date, status, alert,
           progress_pct, dock_action, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [o + (ts,) for o in orders])
    seed_requisitions(conn, ts)


def seed_requisitions(conn, ts) -> None:
    none = (None,) * 5
    prs = [  # number, dept, requester, required, priority, status, project, step1, step2, lines (code, qty)
        ("PR-2026-001", "Production - Fabrication Line A", "Alex Miller", "2026-09-30", "Urgent", PR_PENDING1,
         "SD-100 Sliding Patio Series - Tower A", none, none, [("AL-76-SLD-BLK", 1000), ("SL-EPDM-GSK-01", 500)]),
        ("PR-2026-002", "Production - CNC & Glazing Bay", "Somnang Seng", "2026-10-02", "Routine", PR_PENDING2,
         "CW-50 Commercial Window Glazing",
         ("Approved", "Dara Vuth", "Production Head / Tech Lead", "2026-09-26 14:30", "Tolerances & CNC notch drawings verified with factory line."),
         none, [("GL-TMP-08-CLR", 200)]),
        ("PR-2026-003", "Site Installation Team", "Bunroeun Meas", "2026-09-28", "Critical Line-Stop", PR_APPROVED,
         "SD-100 Heavy Duty Sliding Door",
         ("Approved", "Dara Vuth", "Production Head / Tech Lead", "2026-09-25 09:15", "Hardware specs checked and approved."),
         ("Approved", "Alex Miller", "Master Admin / General Manager", "2026-09-25 11:20", "Budget verified against Project Cost Code #CW-09."),
         [("HD-ROL-TDM-120", 350), ("HD-LCK-MLT-BLK", 120)]),
    ]
    for num, dept, who, due, prio, status, project, s1, s2, lines in prs:
        conn.execute("""INSERT INTO purchase_requisitions (pr_number, department, requester, required_date, priority,
                        status, bom_project, step1_decision, step1_by, step1_role, step1_date, step1_notes,
                        step2_decision, step2_by, step2_role, step2_date, step2_notes, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (num, dept, who, due, prio, status, project, *s1, *s2, ts))
        for n, (code, qty) in enumerate(lines, 1):
            m = conn.execute("SELECT name, specs, uom, std_cost FROM materials WHERE code = ?", (code,)).fetchone()
            conn.execute("""INSERT INTO pr_items (pr_number, line_no, item_code, item_name, item_specs, quantity, uom, unit_rate)
                            VALUES (?,?,?,?,?,?,?,?)""", (num, n, code, m["name"], m["specs"], qty, m["uom"], m["std_cost"]))


def bootstrap_admin(conn) -> None:
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    given = os.environ.get("PROC_ADMIN_PASSWORD")
    password = given or secrets.token_urlsafe(12)
    conn.execute("INSERT INTO users (username, password_hash, full_name, role, status) VALUES (?,?,?,?,?)",
                 ("admin", hash_password(password), "Administrator", "admin", "allowed"))
    if not given:
        print("=" * 60)
        print(f"  First run: created user 'admin' with password:  {password}")
        print("  Shown once - log in and change it (POST /api/users).")
        print("=" * 60)


def audit(conn, user, action: str, resource: str, key=None, detail=None) -> None:
    conn.execute("INSERT INTO audit_log (ts, username, action, resource, key, detail) VALUES (?,?,?,?,?,?)",
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
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2 ** 14, r=8, p=1, dklen=len(expected))
        return hmac.compare_digest(dk, expected)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password("timing-equaliser")   # so unknown usernames cost the same as wrong passwords


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


def ID(maxlen=40):
    """Identifier safe to embed in URLs and page markup (no quotes, slashes, spaces or angle brackets)."""
    def check(name, v):
        s = as_str(name, v, maxlen)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", s):
            raise ApiError(400, f"'{name}' may only contain letters, digits, '.', '_' and '-'")
        return s
    return check


def E(*options):
    def check(name, v):
        if v not in options:
            raise ApiError(400, f"'{name}' must be one of: {', '.join(options)}")
        return v
    return check


# --------------------------------------------------------------------------- resources
def require_supplier(conn, name: str, field: str) -> None:
    if not conn.execute("SELECT 1 FROM suppliers WHERE name = ?", (name,)).fetchone():
        raise ApiError(400, f"Unknown supplier in '{field}': {name!r}. Create the supplier first.")


def fin_materials(conn, m, clean, existing):
    if "supplier" in clean:
        require_supplier(conn, m["supplier"], "supplier")
    m["status"] = stock_status(m["current_stock"], m["safety_stock"], m["reorder_point"])
    return {"status"}


def fin_suppliers(conn, s, clean, existing):
    if existing is not None and "name" in clean and clean["name"] != existing["name"]:
        used = conn.execute("SELECT (SELECT COUNT(*) FROM materials WHERE supplier=?) + "
                            "(SELECT COUNT(*) FROM purchase_orders WHERE vendor=?)",
                            (existing["name"], existing["name"])).fetchone()[0]
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
    if clean.get("status") in (PO_PARTIAL, PO_DOCK_RECEIVED) and (existing is None or existing["status"] != clean["status"]):
        raise ApiError(400, f"'{clean['status']}' is set automatically when goods are received on a Form 04 GRN")
    return set()


RESOURCES = {
    "materials": dict(
        name="materials", table="materials", pk="code", order="code ASC", write_roles={"admin", "purchasing"},
        fields={"code": ID(40), "category": T(40), "name": T(120), "specs": T(300), "uom": T(16),
                "current_stock": N(), "safety_stock": N(), "reorder_point": N(), "std_cost": N(),
                "supplier": T(120), "status": T(16), "tolerance": T(120, True), "packaging": T(120, True),
                "lead_time": T(40, True), "bom_link": T(120, True), "usage_rate": T(40, True)},
        derived={"status"}, required=("code", "category", "name", "specs", "uom", "supplier"),
        defaults={"current_stock": 0.0, "safety_stock": 0.0, "reorder_point": 0.0, "std_cost": 0.0,
                  "tolerance": None, "packaging": None, "lead_time": None, "bom_link": None, "usage_rate": None},
        finalize=fin_materials),
    "suppliers": dict(
        name="suppliers", table="suppliers", pk="id", order="score DESC, name ASC", write_roles={"admin", "purchasing"},
        fields={"id": ID(40), "name": T(120), "category": T(80), "tier": T(40), "score": I(),
                **{k: I() for k in METRIC_KEYS}, "payment_terms": T(40), "lead_time": T(40),
                "contact": T(160), "otif": T(16, True), "qc_rate": T(16, True)},
        derived=set(), required=("id", "name", "category", "tier", "payment_terms", "lead_time", "contact"),
        defaults={"score": 0, **{k: None for k in METRIC_KEYS}, "otif": None, "qc_rate": None},
        finalize=fin_suppliers),
    "orders": dict(
        name="orders", table="purchase_orders", pk="po_number", order="due_date ASC", write_roles={"admin", "purchasing"},
        fields={"po_number": ID(40), "vendor": T(120), "items": T(400), "amount_usd": N(),
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
        return max((date.today() - date.fromisoformat(row["due_date"])).days, 0)
    except ValueError:
        return 0


def decorate(res, row) -> dict:
    d = dict(row)
    if res["name"] == "orders":
        n = days_overdue(row)
        d["days_overdue"] = n
        if n:
            d["alert"] = f"🔴 {n} Day{'s' if n != 1 else ''} Overdue"
    return d


def fetch_one(conn, res, key):
    row = conn.execute(f"SELECT * FROM {res['table']} WHERE {res['pk']} = ?", (key,)).fetchone()
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

    existing = conn.execute(f"SELECT * FROM {res['table']} WHERE {pk} = ?", (key,)).fetchone()
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
    if existing is None:
        cols = [c for c in fields if c in merged] + ["updated_at"]
        conn.execute(f"INSERT INTO {res['table']} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                     [merged[c] for c in cols])
    else:
        cols = [c for c in fields if c != pk and (c in clean or c in written_derived)] + ["updated_at"]
        conn.execute(f"UPDATE {res['table']} SET {', '.join(c + ' = ?' for c in cols)} WHERE {pk} = ?",
                     [merged[c] for c in cols] + [key])
    audit(conn, user, "create" if existing is None else "update", res["name"], key, clean)
    return existing is None, fetch_one(conn, res, key)


def delete_record(conn, res, key, user) -> None:
    row = fetch_one(conn, res, key)
    if res["name"] == "suppliers":
        mats = conn.execute("SELECT COUNT(*) FROM materials WHERE supplier = ?", (row["name"],)).fetchone()[0]
        pos = conn.execute("SELECT COUNT(*) FROM purchase_orders WHERE vendor = ?", (row["name"],)).fetchone()[0]
        if mats or pos:
            raise ApiError(409, f"Supplier is still used by {mats} material(s) and {pos} purchase order(s)")
    if res["name"] == "orders":
        g = conn.execute("SELECT (SELECT COUNT(*) FROM grns WHERE po_number = ?) + (SELECT COUNT(*) FROM invoices WHERE po_number = ?)",
                         (key, key)).fetchone()[0]
        if g:
            raise ApiError(409, "This PO has goods receipts or invoices and cannot be deleted - cancel it instead")
    conn.execute(f"DELETE FROM {res['table']} WHERE {res['pk']} = ?", (key,))
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
    orders = conn.execute("SELECT status, due_date, amount_usd FROM purchase_orders").fetchall()
    open_orders = [o for o in orders if o["status"] not in CLOSED_PO]
    stock = [r["status"] for r in conn.execute("SELECT status FROM materials")]
    prs = [r["status"] for r in conn.execute("SELECT status FROM purchase_requisitions")]
    return {
        "active_skus": len(stock),
        "active_vendors": conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0],
        "open_po_value": round(sum(o["amount_usd"] for o in open_orders), 2),
        "open_po_count": len(open_orders),
        "delayed_shipments": sum(1 for o in open_orders if o["status"] == "Delayed" or days_overdue(o) > 0),
        "low_stock_skus": stock.count("low"),
        "reorder_skus": stock.count("reorder"),
        "prs_pending_step1": prs.count(PR_PENDING1),
        "prs_pending_step2": prs.count(PR_PENDING2),
        "prs_approved_awaiting_po": prs.count(PR_APPROVED),
        "grns_logged": conn.execute("SELECT COUNT(*) FROM grns").fetchone()[0],
        "open_ncrs": conn.execute("SELECT COUNT(*) FROM ncrs WHERE status = ?", (NCR_OPEN,)).fetchone()[0],
        "invoices_held": conn.execute("SELECT COUNT(*) FROM invoices WHERE status = ?", (INV_HELD,)).fetchone()[0],
        "invoices_ready_for_payment": conn.execute("SELECT COUNT(*) FROM invoices WHERE status = ?", (INV_MATCHED,)).fetchone()[0],
    }


# --------------------------------------------------------------------------- requisitions
ITEM_FIELDS = {"item_code", "item_name", "item_specs", "quantity", "uom", "unit_rate"}


def page_args(q) -> tuple[int, int]:
    def num(name, default, lo, hi):
        v = q.get(name, [str(default)])[0]
        return min(max(int(v), lo), hi) if v.isdigit() else default
    return num("limit", 200, 1, 1000), num("offset", 0, 0, 10 ** 9)


def next_number(conn, prefix: str, table: str, col: str) -> str:
    """Atomic, collision-free document numbers such as PO-2026-096 (table/col are internal constants)."""
    year = date.today().year
    name = f"{prefix}-{year}"
    if conn.execute("SELECT 1 FROM counters WHERE name = ?", (name,)).fetchone() is None:
        top = 0
        for (num,) in conn.execute(f"SELECT {col} FROM {table} WHERE {col} LIKE ?", (f"{prefix}-{year}-%",)):
            m = re.fullmatch(rf"{prefix}-{year}-(\d+)", num)
            if m:
                top = max(top, int(m.group(1)))
        conn.execute("INSERT OR IGNORE INTO counters (name, value) VALUES (?, ?)", (name, top))
    while True:
        conn.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (name,))
        n = conn.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()[0]
        candidate = f"{prefix}-{year}-{n:03d}"
        if not conn.execute(f"SELECT 1 FROM {table} WHERE {col} = ?", (candidate,)).fetchone():
            return candidate


def pr_dict(row, items) -> dict:
    d = {k: row[k] for k in ("pr_number", "department", "requester", "required_date", "priority", "status",
                             "bom_project", "created_at", "updated_at")}
    d["items"] = [{"item_code": i["item_code"], "item_name": i["item_name"], "item_specs": i["item_specs"],
                   "quantity": i["quantity"], "uom": i["uom"], "unit_rate": i["unit_rate"],
                   "extended_total": round(i["quantity"] * i["unit_rate"], 2)} for i in items]
    d["estimated_total"] = round(sum(i["extended_total"] for i in d["items"]), 2)
    for n in (1, 2):
        decision = row[f"step{n}_decision"] or ""
        d[f"step{n}"] = {"decision": decision, "approved": decision == "Approved", "rejected": decision == "Rejected",
                         "by": row[f"step{n}_by"] or "", "role": row[f"step{n}_role"] or "",
                         "date": row[f"step{n}_date"] or "", "notes": row[f"step{n}_notes"] or ""}
    d["revisions"] = json.loads(row["revisions"] or "[]")
    d["po_numbers"] = json.loads(row["po_numbers"] or "[]")
    return d


def load_prs(conn, where: str = "", params=(), limit: int = 200, offset: int = 0) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM purchase_requisitions {where} ORDER BY created_at DESC, pr_number DESC "
                        "LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
    by_pr = {r["pr_number"]: [] for r in rows}
    if rows:
        marks = ",".join("?" * len(by_pr))
        for it in conn.execute(f"SELECT * FROM pr_items WHERE pr_number IN ({marks}) ORDER BY pr_number, line_no", list(by_pr)):
            by_pr[it["pr_number"]].append(it)
    return [pr_dict(r, by_pr[r["pr_number"]]) for r in rows]


def get_pr(conn, number: str) -> dict:
    found = load_prs(conn, "WHERE pr_number = ?", (number,), 1, 0)
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
        code = ID(40)(f"items[{i}].item_code", it.get("item_code"))
        mat = conn.execute("SELECT name, specs, uom, std_cost FROM materials WHERE code = ?", (code,)).fetchone()

        def pick(field, check, fallback, i=i, it=it):
            if field in it:
                return check(f"items[{i}].{field}", it[field])
            if fallback is None:
                raise ApiError(400, f"items[{i}].{field} is required (item is not in the materials catalogue)")
            return fallback
        out.append({
            "item_code": code,
            "item_name": pick("item_name", T(120), mat["name"] if mat else None),
            "item_specs": pick("item_specs", T(300, True), mat["specs"] if mat else ""),
            "quantity": pick("quantity", N(1e-6, 1e9), None),
            "uom": pick("uom", T(16), mat["uom"] if mat else None),
            "unit_rate": pick("unit_rate", N(), mat["std_cost"] if mat else None),
        })
    return out


def write_items(conn, number: str, items) -> None:
    conn.execute("DELETE FROM pr_items WHERE pr_number = ?", (number,))
    conn.executemany("""INSERT INTO pr_items (pr_number, line_no, item_code, item_name, item_specs, quantity, uom, unit_rate)
                        VALUES (?,?,?,?,?,?,?,?)""",
                     [(number, n, i["item_code"], i["item_name"], i["item_specs"], i["quantity"], i["uom"], i["unit_rate"])
                      for n, i in enumerate(items, 1)])


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
    conn.execute("""INSERT INTO purchase_requisitions (pr_number, department, requester, requested_by, required_date,
                    priority, status, bom_project, updated_at) VALUES (?,?,?,?,?,?,?,?,?)""",
                 (number, department, user["full_name"], user["username"], required, priority, PR_PENDING1, bom, now_iso()))
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
    row = conn.execute("SELECT * FROM purchase_requisitions WHERE pr_number = ?", (number,)).fetchone()
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
    conn.execute(f"""UPDATE purchase_requisitions SET status = ?, step{step}_decision = ?, step{step}_by = ?,
                     step{step}_role = ?, step{step}_date = ?, step{step}_notes = ?, step{step}_user = ?, updated_at = ?
                     WHERE pr_number = ?""",
                 (status, decision, user["full_name"], ROLE_LABELS[user["role"]], ts, remarks, user["username"], ts, number))
    audit(conn, user, decision.lower(), "requisitions", number, {"step": step, "remarks": remarks})


def revise_pr(conn, user, number, body) -> None:
    reject_unknown(body, {"required_date", "bom_project", "items", "changelog"})
    row = conn.execute("SELECT * FROM purchase_requisitions WHERE pr_number = ?", (number,)).fetchone()
    if row is None:
        raise ApiError(404, f"Requisition {number!r} not found")
    if row["status"] not in PR_REJECTED.values():
        raise ApiError(409, "Only a rejected requisition can be revised and resubmitted")
    changelog = T(500)("changelog", body.get("changelog"))
    required = D()("required_date", body["required_date"]) if "required_date" in body else row["required_date"]
    bom = T(120, True)("bom_project", body["bom_project"]) if "bom_project" in body else row["bom_project"]
    if "items" in body:
        write_items(conn, number, clean_items(conn, body["items"]))
    revisions = json.loads(row["revisions"] or "[]")
    revisions.insert(0, {"revision_date": now_iso(), "revised_by": user["full_name"], "notes": changelog,
                         "previous_state": row["status"]})
    conn.execute("""UPDATE purchase_requisitions SET status = ?, required_date = ?, bom_project = ?, revisions = ?,
                    step1_decision = NULL, step1_by = NULL, step1_role = NULL, step1_date = NULL, step1_notes = NULL, step1_user = NULL,
                    step2_decision = NULL, step2_by = NULL, step2_role = NULL, step2_date = NULL, step2_notes = NULL, step2_user = NULL,
                    updated_at = ? WHERE pr_number = ?""",
                 (PR_PENDING1, required, bom, json.dumps(revisions, ensure_ascii=False), now_iso(), number))
    audit(conn, user, "revise", "requisitions", number, {"notes": changelog})


def cancel_pr(conn, user, number) -> None:
    row = conn.execute("SELECT status FROM purchase_requisitions WHERE pr_number = ?", (number,)).fetchone()
    if row is None:
        raise ApiError(404, f"Requisition {number!r} not found")
    if row["status"] in (PR_CONVERTED, PR_CANCELLED):
        raise ApiError(409, f"A requisition that is '{row['status']}' cannot be cancelled")
    conn.execute("UPDATE purchase_requisitions SET status = ?, updated_at = ? WHERE pr_number = ?",
                 (PR_CANCELLED, now_iso(), number))
    audit(conn, user, "cancel", "requisitions", number)


def convert_pr(conn, user, number, body) -> list[str]:
    """Approved PR -> one PO per vendor (vendor = the item's supplier in the catalogue unless overridden)."""
    reject_unknown(body, {"vendors"})
    vendors = body.get("vendors", {})
    if not isinstance(vendors, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in vendors.items()):
        raise ApiError(400, "'vendors' must map item codes to supplier names")
    row = conn.execute("SELECT * FROM purchase_requisitions WHERE pr_number = ?", (number,)).fetchone()
    if row is None:
        raise ApiError(404, f"Requisition {number!r} not found")
    if row["status"] != PR_APPROVED:
        raise ApiError(409, f"Only an Approved requisition can be converted (current status: {row['status']})")
    groups: dict[str, list] = {}
    missing = []
    for it in conn.execute("SELECT * FROM pr_items WHERE pr_number = ? ORDER BY line_no", (number,)):
        vendor = vendors.get(it["item_code"])
        if vendor is None:
            m = conn.execute("SELECT supplier FROM materials WHERE code = ?", (it["item_code"],)).fetchone()
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
        merged: dict[str, dict] = {}              # one PO line per item; same item twice is only allowed at one rate
        for l in lines:
            if l["item_code"] in merged:
                if merged[l["item_code"]]["unit_rate"] != l["unit_rate"]:
                    raise ApiError(409, f"{l['item_code']} appears twice in {number} with different rates - fix the requisition first")
                merged[l["item_code"]]["quantity"] += l["quantity"]
            else:
                merged[l["item_code"]] = dict(l)
        lines = list(merged.values())
        po = next_number(conn, "PO", "purchase_orders", "po_number")
        summary = ", ".join(f"{l['item_name']} ({l['quantity']:g} {l['uom']})" for l in lines)[:400]
        amount = round(sum(l["quantity"] * l["unit_rate"] for l in lines), 2)
        conn.execute("""INSERT INTO purchase_orders (po_number, vendor, items, amount_usd, due_date, status, alert,
                        progress_pct, dock_action, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (po, vendor, summary, amount, row["required_date"], "Order Confirmed", "On Track", 25,
                      f"Converted from {number} by {user['full_name']}. Vendor notification pending.", ts))
        conn.executemany("""INSERT INTO po_items (po_number, line_no, item_code, item_name, quantity, uom, unit_rate)
                            VALUES (?,?,?,?,?,?,?)""",
                         [(po, n, l["item_code"], l["item_name"], l["quantity"], l["uom"], l["unit_rate"])
                          for n, l in enumerate(lines, 1)])
        created.append(po)
    conn.execute("UPDATE purchase_requisitions SET status = ?, po_numbers = ?, updated_at = ? WHERE pr_number = ?",
                 (PR_CONVERTED, json.dumps(created), ts, number))
    audit(conn, user, "convert", "requisitions", number, {"purchase_orders": created})
    return created


# --------------------------------------------------------------------------- logistics (Phase 3)
SEED_PO_LINES = {"PO-2026-089": [("AL-76-SLD-BLK", 2500)], "PO-2026-092": [("SL-EPDM-GSK-01", 3000)],
                 "PO-2026-094": [("GL-TMP-08-CLR", 85)], "PO-2026-095": [("HD-ROL-TDM-120", 500)]}


def seed_po_lines(conn) -> None:
    """Give the demo POs real line items (idempotent; also upgrades databases created before Phase 3)."""
    for po, lines in SEED_PO_LINES.items():
        if conn.execute("SELECT 1 FROM purchase_orders WHERE po_number = ?", (po,)).fetchone() is None:
            continue
        if conn.execute("SELECT 1 FROM po_items WHERE po_number = ?", (po,)).fetchone():
            continue
        for n, (code, qty) in enumerate(lines, 1):
            m = conn.execute("SELECT name, uom, std_cost FROM materials WHERE code = ?", (code,)).fetchone()
            if m:
                conn.execute("INSERT INTO po_items VALUES (?,?,?,?,?,?,?)", (po, n, code, m["name"], qty, m["uom"], m["std_cost"]))


def D6(x) -> Decimal:
    return Decimal(str(round(float(x), 6)))


def adjust_stock(conn, code: str, delta: float) -> None:
    if not GRN_UPDATES_STOCK or not delta:
        return
    m = conn.execute("SELECT current_stock, safety_stock, reorder_point FROM materials WHERE code = ?", (code,)).fetchone()
    if m is None:
        return
    stock = round(m["current_stock"] + delta, 6)
    conn.execute("UPDATE materials SET current_stock = ?, status = ?, updated_at = ? WHERE code = ?",
                 (stock, stock_status(stock, m["safety_stock"], m["reorder_point"]), now_iso(), code))


def po_receipts(conn, po_number: str) -> dict:
    """item_code -> ordered / arrived / accepted (incl. concessions) / quarantined / open_balance for one PO."""
    out = {l["item_code"]: {"ordered": l["quantity"], "arrived": 0.0, "accepted": 0.0, "quarantined": 0.0}
           for l in conn.execute("SELECT item_code, quantity FROM po_items WHERE po_number = ?", (po_number,))}
    for r in conn.execute("""SELECT gi.item_code, SUM(gi.arrived_qty) a, SUM(gi.accepted_qty) c FROM grn_items gi
                             JOIN grns g ON g.grn_number = gi.grn_number WHERE g.po_number = ? GROUP BY gi.item_code""", (po_number,)):
        if r["item_code"] in out:
            out[r["item_code"]]["arrived"], out[r["item_code"]]["accepted"] = r["a"], r["c"]
    for r in conn.execute("""SELECT item_code, status, disposition, SUM(quantity) q FROM ncrs WHERE po_number = ?
                             GROUP BY item_code, status, disposition""", (po_number,)):
        e = out.get(r["item_code"])
        if e is None:
            continue
        if r["status"] == NCR_OPEN:
            e["quarantined"] += r["q"]
        elif r["disposition"] == "Accept under Concession":
            e["accepted"] += r["q"]
    for e in out.values():
        e["accepted"] = round(e["accepted"], 6)
        e["open_balance"] = round(max(e["ordered"] - e["accepted"], 0.0), 6)
    return out


def po_lines_of(conn, po_number: str) -> list[dict]:
    rec = po_receipts(conn, po_number)
    return [{"line_no": l["line_no"], "item_code": l["item_code"], "item_name": l["item_name"], "uom": l["uom"],
             "unit_rate": l["unit_rate"], "ordered_qty": l["quantity"], "arrived_qty": rec[l["item_code"]]["arrived"],
             "accepted_qty": rec[l["item_code"]]["accepted"], "quarantined_qty": rec[l["item_code"]]["quarantined"],
             "open_balance": rec[l["item_code"]]["open_balance"], "line_total": round(l["quantity"] * l["unit_rate"], 2)}
            for l in conn.execute("SELECT * FROM po_items WHERE po_number = ? ORDER BY line_no", (po_number,))]


def shape(conn, res, row) -> dict:
    d = decorate(res, row)
    if res["name"] == "orders":
        d["lines"] = po_lines_of(conn, d["po_number"])
    return d


def refresh_po_status(conn, po_number: str) -> None:
    po = conn.execute("SELECT status FROM purchase_orders WHERE po_number = ?", (po_number,)).fetchone()
    rec = po_receipts(conn, po_number)
    if po is None or po["status"] in ("Cancelled", "Received") or not rec:
        return
    ordered = sum(e["ordered"] for e in rec.values())
    accepted = sum(min(e["accepted"], e["ordered"]) for e in rec.values())
    open_ncr = conn.execute("SELECT COUNT(*) FROM ncrs WHERE po_number = ? AND status = ?", (po_number, NCR_OPEN)).fetchone()[0]
    quarantine = f" {open_ncr} defect report(s) still in quarantine." if open_ncr else ""
    if all(e["open_balance"] <= 1e-9 for e in rec.values()):
        status, pct, alert = PO_DOCK_RECEIVED, 100, "Full Inward"
        action = "100% of ordered quantity accepted at the dock." + quarantine + " Ready for 3-way match."
    elif any(e["arrived"] > 0 for e in rec.values()):
        status, pct, alert = PO_PARTIAL, min(95, round(accepted / ordered * 100)), f"Partial Delivery ({accepted:g}/{ordered:g})"
        action = f"Balance still to receive: {ordered - accepted:g}." + quarantine
    else:
        return
    conn.execute("UPDATE purchase_orders SET status = ?, progress_pct = ?, alert = ?, dock_action = ?, updated_at = ? WHERE po_number = ?",
                 (status, pct, alert, action.strip(), now_iso(), po_number))


def rematch_open_invoices(conn, po_number: str) -> None:
    for r in conn.execute("SELECT ap_number FROM invoices WHERE po_number = ? AND status IN (?, ?)", (po_number, INV_MATCHED, INV_HELD)).fetchall():
        match_invoice(conn, r["ap_number"])


def grn_dict(row, items, ncrs) -> dict:
    d = {k: row[k] for k in ("grn_number", "po_number", "vendor", "delivery_note", "vehicle_plate", "dock_bay",
                             "received_by", "received_at", "dock_notes")}
    d["lines"] = [{k: i[k] for k in ("item_code", "item_name", "uom", "unit_rate", "ordered_qty", "arrived_qty",
                                     "accepted_qty", "rejected_qty", "rejection_reason")} for i in items]
    d["ncrs"] = [dict(n) for n in ncrs]
    d["status"] = GRN_QUARANTINED if any(n["status"] == NCR_OPEN for n in ncrs) else (GRN_RESOLVED if ncrs else GRN_PASSED)
    d["total_accepted_value"] = round(sum(i["accepted_qty"] * i["unit_rate"] for i in items), 2)
    return d


def load_grns(conn, where: str = "", params=(), limit: int = 200, offset: int = 0) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM grns {where} ORDER BY received_at DESC, grn_number DESC LIMIT ? OFFSET ?",
                        (*params, limit, offset)).fetchall()
    items = {r["grn_number"]: [] for r in rows}
    ncrs = {r["grn_number"]: [] for r in rows}
    if rows:
        marks = ",".join("?" * len(items))
        for i in conn.execute(f"SELECT * FROM grn_items WHERE grn_number IN ({marks}) ORDER BY grn_number, line_no", list(items)):
            items[i["grn_number"]].append(i)
        for n in conn.execute(f"SELECT * FROM ncrs WHERE grn_number IN ({marks}) ORDER BY ncr_number", list(items)):
            ncrs[n["grn_number"]].append(n)
    return [grn_dict(r, items[r["grn_number"]], ncrs[r["grn_number"]]) for r in rows]


def get_grn(conn, number: str) -> dict:
    found = load_grns(conn, "WHERE grn_number = ?", (number,), 1, 0)
    if not found:
        raise ApiError(404, f"GRN {number!r} not found")
    return found[0]


def receive_goods(conn, user, po_number: str, body) -> str:
    reject_unknown(body, {"delivery_note", "vehicle_plate", "dock_bay", "dock_notes", "lines"})
    for f in ("delivery_note", "vehicle_plate", "dock_bay", "lines"):
        if f not in body:
            raise ApiError(400, f"'{f}' is required")
    po = fetch_one(conn, RESOURCES["orders"], po_number)
    if po["status"] not in RECEIVABLE:
        raise ApiError(409, f"{po_number} is '{po['status']}' and cannot receive goods")
    rec = po_receipts(conn, po_number)
    if not rec:
        raise ApiError(409, f"{po_number} has no line items, so goods cannot be checked against it. Add its lines first.")
    note, plate = T(60)("delivery_note", body["delivery_note"]), T(30)("vehicle_plate", body["vehicle_plate"])
    bay, dock_notes = T(60)("dock_bay", body["dock_bay"]), T(500, True)("dock_notes", body.get("dock_notes"))
    dup = conn.execute("SELECT grn_number FROM grns WHERE vendor = ? AND delivery_note = ?", (po["vendor"], note)).fetchone()
    if dup:
        raise ApiError(409, f"Delivery note {note} from {po['vendor']} was already received on {dup['grn_number']}")
    raw = body["lines"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ApiError(400, "'lines' must be a list of 1 to 50 lines")
    lines, seen = [], set()
    for i, ln in enumerate(raw, 1):
        if not isinstance(ln, dict):
            raise ApiError(400, f"lines[{i}] must be an object")
        extra = set(ln) - {"item_code", "arrived_qty", "accepted_qty", "rejected_qty", "rejection_reason"}
        if extra:
            raise ApiError(400, f"lines[{i}] has unknown field(s): " + ", ".join(sorted(extra)))
        code = ID(40)(f"lines[{i}].item_code", ln.get("item_code"))
        if code not in rec:
            raise ApiError(400, f"lines[{i}]: {code} is not on {po_number}")
        if code in seen:
            raise ApiError(400, f"lines[{i}]: {code} is listed twice")
        seen.add(code)
        arrived = as_num(f"lines[{i}].arrived_qty", ln.get("arrived_qty"), 0, 1e9)
        accepted = as_num(f"lines[{i}].accepted_qty", ln.get("accepted_qty", arrived), 0, 1e9)
        rejected = as_num(f"lines[{i}].rejected_qty", ln.get("rejected_qty", 0), 0, 1e9)
        reason = T(300, True)(f"lines[{i}].rejection_reason", ln.get("rejection_reason"))
        if arrived <= 0:
            raise ApiError(400, f"lines[{i}]: arrived_qty must be greater than 0 (leave out lines that did not arrive)")
        if abs(accepted + rejected - arrived) > 1e-6:
            raise ApiError(400, f"lines[{i}]: accepted + rejected must equal the arrived quantity")
        if rejected > 0 and not reason:
            raise ApiError(400, f"lines[{i}]: a rejection reason is required for quarantined goods")
        e = rec[code]
        if accepted > e["open_balance"] + e["ordered"] * float(OVER_RECEIPT) / 100 + 1e-9:
            raise ApiError(409, f"{code}: accepting {accepted:g} would exceed the ordered quantity ({e['ordered']:g}, "
                                f"{e['accepted']:g} already accepted). Reject the excess instead.")
        lines.append((code, arrived, accepted, rejected, reason))
    number = next_number(conn, "GRN", "grns", "grn_number")
    conn.execute("""INSERT INTO grns (grn_number, po_number, vendor, delivery_note, vehicle_plate, dock_bay, received_by,
                    received_by_user, received_at, dock_notes) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                 (number, po_number, po["vendor"], note, plate, bay, user["full_name"], user["username"], now_iso(), dock_notes))
    pol = {l["item_code"]: l for l in conn.execute("SELECT * FROM po_items WHERE po_number = ?", (po_number,))}
    for n, (code, arrived, accepted, rejected, reason) in enumerate(lines, 1):
        l = pol[code]
        conn.execute("INSERT INTO grn_items VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (number, n, code, l["item_name"], l["uom"], l["unit_rate"], l["quantity"], arrived, accepted, rejected, reason))
        adjust_stock(conn, code, accepted)
        if rejected > 0:
            conn.execute("INSERT INTO ncrs (ncr_number, grn_number, po_number, item_code, item_name, quantity, uom, reason, status, created_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (next_number(conn, "NCR", "ncrs", "ncr_number"), number, po_number, code, l["item_name"], rejected,
                          l["uom"], reason, NCR_OPEN, now_iso()))
    refresh_po_status(conn, po_number)
    rematch_open_invoices(conn, po_number)
    audit(conn, user, "receive", "grns", number, {"po": po_number, "lines": len(lines), "rejected": sum(l[3] for l in lines)})
    return number


def resolve_ncr(conn, user, number: str, body) -> None:
    reject_unknown(body, {"disposition", "notes"})
    disposition = E(*DISPOSITIONS)("disposition", body.get("disposition"))
    notes = T(500)("notes", body.get("notes"))
    n = conn.execute("SELECT * FROM ncrs WHERE ncr_number = ?", (number,)).fetchone()
    if n is None:
        raise ApiError(404, f"NCR {number!r} not found")
    if n["status"] != NCR_OPEN:
        raise ApiError(409, f"{number} is already closed")
    if disposition == "Accept under Concession":
        e = po_receipts(conn, n["po_number"]).get(n["item_code"])
        if e is None or e["accepted"] + n["quantity"] > e["ordered"] * (1 + float(OVER_RECEIPT) / 100) + 1e-9:
            raise ApiError(409, "Accepting this quantity would exceed the ordered quantity on the PO")
        adjust_stock(conn, n["item_code"], n["quantity"])
    conn.execute("UPDATE ncrs SET status = ?, disposition = ?, resolution_notes = ?, resolved_by = ?, resolved_at = ? WHERE ncr_number = ?",
                 (NCR_CLOSED, disposition, notes, user["full_name"], now_iso(), number))
    refresh_po_status(conn, n["po_number"])
    rematch_open_invoices(conn, n["po_number"])
    audit(conn, user, "resolve", "ncrs", number, {"disposition": disposition})


def set_po_lines(conn, user, po_number: str, body) -> None:
    reject_unknown(body, {"lines"})
    po = fetch_one(conn, RESOURCES["orders"], po_number)
    if po["status"] in ("Cancelled", "Received"):
        raise ApiError(409, f"{po_number} is '{po['status']}'")
    if conn.execute("SELECT (SELECT COUNT(*) FROM grns WHERE po_number = ?) + (SELECT COUNT(*) FROM invoices WHERE po_number = ?)",
                    (po_number, po_number)).fetchone()[0]:
        raise ApiError(409, "Goods or invoices already exist for this PO, so its lines can no longer change")
    items = clean_items(conn, body.get("lines"))
    codes = [i["item_code"] for i in items]
    if len(set(codes)) != len(codes):
        raise ApiError(400, "Each item may appear only once on a PO")
    conn.execute("DELETE FROM po_items WHERE po_number = ?", (po_number,))
    conn.executemany("INSERT INTO po_items VALUES (?,?,?,?,?,?,?)",
                     [(po_number, n, i["item_code"], i["item_name"], i["quantity"], i["uom"], i["unit_rate"]) for n, i in enumerate(items, 1)])
    summary = ", ".join(f"{i['item_name']} ({i['quantity']:g} {i['uom']})" for i in items)[:400]
    conn.execute("UPDATE purchase_orders SET items = ?, amount_usd = ?, updated_at = ? WHERE po_number = ?",
                 (summary, round(sum(i["quantity"] * i["unit_rate"] for i in items), 2), now_iso(), po_number))
    audit(conn, user, "set-lines", "orders", po_number, {"lines": len(items)})


# ---- invoices and the 3-way match
def inv_dict(row, items) -> dict:
    d = {k: row[k] for k in ("ap_number", "vendor_invoice_no", "po_number", "vendor", "invoice_date", "status", "invoice_total",
                             "entered_by", "entered_at", "released_by", "released_at", "override_reason")}
    d["lines"] = [{"item_code": i["item_code"], "quantity": i["quantity"], "unit_rate": i["unit_rate"],
                   "line_total": round(i["quantity"] * i["unit_rate"], 2)} for i in items]
    d["match"] = json.loads(row["match_report"] or "{}")
    return d


def load_invoices(conn, where: str = "", params=(), limit: int = 200, offset: int = 0) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM invoices {where} ORDER BY entered_at DESC, ap_number DESC LIMIT ? OFFSET ?",
                        (*params, limit, offset)).fetchall()
    items = {r["ap_number"]: [] for r in rows}
    if rows:
        marks = ",".join("?" * len(items))
        for i in conn.execute(f"SELECT * FROM invoice_items WHERE ap_number IN ({marks}) ORDER BY ap_number, line_no", list(items)):
            items[i["ap_number"]].append(i)
    return [inv_dict(r, items[r["ap_number"]]) for r in rows]


def get_invoice(conn, number: str) -> dict:
    found = load_invoices(conn, "WHERE ap_number = ?", (number,), 1, 0)
    if not found:
        raise ApiError(404, f"Invoice {number!r} not found")
    return found[0]


def match_invoice(conn, ap_number: str) -> None:
    """3-way match: PO rate = GRN accepted quantity = supplier invoice (within the configured tolerances)."""
    inv = conn.execute("SELECT * FROM invoices WHERE ap_number = ?", (ap_number,)).fetchone()
    if inv is None or inv["status"] in (INV_RELEASED, INV_OVERRIDE):
        return
    po_lines = {l["item_code"]: l for l in conn.execute("SELECT * FROM po_items WHERE po_number = ?", (inv["po_number"],))}
    rec = po_receipts(conn, inv["po_number"])
    report, issues = [], []
    for it in conn.execute("SELECT * FROM invoice_items WHERE ap_number = ? ORDER BY line_no", (ap_number,)):
        code, n = it["item_code"], it["line_no"]
        pl = po_lines.get(code)
        if pl is None:
            issues.append({"line": n, "item_code": code, "check": "PO line", "message": f"{code} is not on {inv['po_number']}"})
            continue
        e = rec[code]
        qty, rate, po_rate, accepted = D6(it["quantity"]), D6(it["unit_rate"]), D6(pl["unit_rate"]), D6(e["accepted"])
        other = D6(conn.execute("""SELECT COALESCE(SUM(ii.quantity), 0) FROM invoice_items ii JOIN invoices i ON i.ap_number = ii.ap_number
                                   WHERE i.po_number = ? AND ii.item_code = ? AND ii.ap_number != ?""",
                                (inv["po_number"], code, ap_number)).fetchone()[0])
        price_ok = abs(rate - po_rate) <= po_rate * PRICE_TOL / 100
        qty_ok = qty + other <= accepted * (1 + QTY_TOL / 100)
        report.append({"line": n, "item_code": code, "po_rate": float(po_rate), "invoice_rate": float(rate),
                       "price_variance": float(rate - po_rate), "ordered_qty": e["ordered"], "accepted_qty": float(accepted),
                       "already_invoiced_qty": float(other), "invoice_qty": float(qty), "qty_variance": float(qty + other - accepted),
                       "price_ok": price_ok, "qty_ok": qty_ok})
        if not price_ok:
            issues.append({"line": n, "item_code": code, "check": "Price",
                           "message": f"Invoice rate {float(rate):g} differs from PO rate {float(po_rate):g}"})
        if not qty_ok:
            held = f" ({e['quarantined']:g} still in quarantine)" if e["quarantined"] else ""
            issues.append({"line": n, "item_code": code, "check": "Quantity",
                           "message": f"Billing {float(qty + other):g} in total but only {float(accepted):g} accepted at the dock{held}"})
    conn.execute("UPDATE invoices SET status = ?, match_report = ? WHERE ap_number = ?",
                 (INV_HELD if issues else INV_MATCHED, json.dumps({"lines": report, "issues": issues}), ap_number))


def create_invoice(conn, user, body) -> str:
    reject_unknown(body, {"po_number", "vendor_invoice_no", "invoice_date", "lines"})
    for f in ("po_number", "vendor_invoice_no", "invoice_date", "lines"):
        if f not in body:
            raise ApiError(400, f"'{f}' is required")
    po_number = ID(40)("po_number", body["po_number"])
    po = conn.execute("SELECT * FROM purchase_orders WHERE po_number = ?", (po_number,)).fetchone()
    if po is None:
        raise ApiError(400, f"Unknown purchase order {po_number!r}")
    if not po_receipts(conn, po_number):
        raise ApiError(409, f"{po_number} has no line items, so an invoice cannot be matched against it")
    vno, idate = T(60)("vendor_invoice_no", body["vendor_invoice_no"]), D()("invoice_date", body["invoice_date"])
    dup = conn.execute("SELECT ap_number FROM invoices WHERE vendor = ? AND vendor_invoice_no = ?", (po["vendor"], vno)).fetchone()
    if dup:
        raise ApiError(409, f"Invoice {vno} from {po['vendor']} was already entered as {dup['ap_number']}")
    raw = body["lines"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
        raise ApiError(400, "'lines' must be a list of 1 to 50 lines")
    lines, seen = [], set()
    for i, ln in enumerate(raw, 1):
        if not isinstance(ln, dict) or set(ln) - {"item_code", "quantity", "unit_rate"}:
            raise ApiError(400, f"lines[{i}] must be an object with item_code, quantity and unit_rate")
        code = ID(40)(f"lines[{i}].item_code", ln.get("item_code"))
        if code in seen:
            raise ApiError(400, f"lines[{i}]: {code} is listed twice")
        seen.add(code)
        lines.append((code, as_num(f"lines[{i}].quantity", ln.get("quantity"), 1e-6, 1e9), as_num(f"lines[{i}].unit_rate", ln.get("unit_rate"), 0, 1e9)))
    number = next_number(conn, "AP", "invoices", "ap_number")
    conn.execute("""INSERT INTO invoices (ap_number, vendor_invoice_no, po_number, vendor, invoice_date, status, invoice_total,
                    entered_by, entered_by_user, entered_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                 (number, vno, po_number, po["vendor"], idate, INV_HELD, round(sum(q * r for _, q, r in lines), 2),
                  user["full_name"], user["username"], now_iso()))
    conn.executemany("INSERT INTO invoice_items VALUES (?,?,?,?,?)", [(number, n, c, q, r) for n, (c, q, r) in enumerate(lines, 1)])
    match_invoice(conn, number)
    audit(conn, user, "create", "invoices", number, {"po": po_number, "total": round(sum(q * r for _, q, r in lines), 2)})
    return number


def release_invoice(conn, user, number: str, override_reason=None) -> None:
    inv = conn.execute("SELECT * FROM invoices WHERE ap_number = ?", (number,)).fetchone()
    if inv is None:
        raise ApiError(404, f"Invoice {number!r} not found")
    if inv["status"] in (INV_RELEASED, INV_OVERRIDE):
        raise ApiError(409, f"{number} has already been released")
    match_invoice(conn, number)
    status = conn.execute("SELECT status FROM invoices WHERE ap_number = ?", (number,)).fetchone()["status"]
    if not ALLOW_SELF_APPROVAL and inv["entered_by_user"] == user["username"]:
        raise ApiError(409, "The person who entered an invoice cannot release it for payment")
    if override_reason is None:
        if status != INV_MATCHED:
            raise ApiError(409, f"{number} is on hold: the 3-way match found variances. Correct the receipt or invoice, or ask an administrator to override.")
        new = INV_RELEASED
    else:
        if status != INV_HELD:
            raise ApiError(409, "Only an invoice that is on hold needs an override")
        new = INV_OVERRIDE
    conn.execute("UPDATE invoices SET status = ?, released_by = ?, released_at = ?, override_reason = ? WHERE ap_number = ?",
                 (new, user["full_name"], now_iso(), override_reason, number))
    audit(conn, user, "override" if override_reason else "release", "invoices", number, {"reason": override_reason})


# --------------------------------------------------------------------------- HTTP layer
class Handler(BaseHTTPRequestHandler):
    server_version = "ProcurementAPI/2.0"

    # --- plumbing
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
            row = conn.execute("SELECT username, full_name, role, status FROM users WHERE username = ?",
                               (data["u"],)).fetchone()
        if row is None or row["status"] != "allowed":
            raise ApiError(401, "Account is not active")
        if roles and row["role"] not in roles:
            raise ApiError(403, "Your role is not permitted to do this")
        return dict(row)

    # --- dispatch
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
            if method == "GET" and len(parts) == 2 and parts[0] in ("css", "js") and re.fullmatch(r"[\w.-]+\.(css|js)", parts[1]):
                f = find_static(parts[0], parts[1])         # only css/<file> and js/<file>; no sub-folders, no traversal
                if f is None:
                    raise ApiError(404, "File not found")
                return self._send(200, f.read_bytes(), STATIC_TYPES[f.suffix])
            if not parts or parts[0] != "api":
                raise ApiError(404, "Endpoint not found")
            status, payload = self.route(method, parts[1:], parse_qs(url.query))
            self._json(status, payload)
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except sqlite3.IntegrityError:
            self._json(409, {"error": "Conflict: the record violates a uniqueness or integrity rule"})
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
            with closing(connect()) as conn:
                rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 1000),))
                return 200, [dict(r) for r in rows]
        if p and p[0] == "users":
            return self.users(method, p[1:])
        if p[:1] == ["orders"] and len(p) == 3:
            return self.order_actions(method, p[1], p[2])
        if p and p[0] in ("grns", "ncrs", "invoices"):
            return self.logistics(method, p, q)
        if p and p[0] == "prs":
            return self.prs(method, p[1:], q)
        if p and p[0] in RESOURCES:
            return self.resource(method, RESOURCES[p[0]], p[1:], q)
        raise ApiError(404, "Endpoint not found")

    # --- handlers
    def login(self):
        body = self.read_json()
        username, password = str(body.get("username", "")).strip().lower(), body.get("password")
        if not username or not isinstance(password, str):
            raise ApiError(400, "username and password are required")
        key = f"{self.client_address[0]}|{username}"
        if is_throttled(key):
            raise ApiError(429, "Too many failed attempts. Try again in a few minutes.")
        with closing(connect()) as conn:
            row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
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
            with closing(connect()) as conn:
                rows = conn.execute("SELECT username, full_name, role, status, created_at FROM users ORDER BY username")
                return 200, [{**dict(r), "role_label": ROLE_LABELS[r["role"]]} for r in rows]
        if method == "POST" and not rest:
            body = self.read_json()
            username = as_str("username", body.get("username", "")).lower()
            if not re.fullmatch(r"[a-z0-9._-]{3,32}", username):
                raise ApiError(400, "'username' must be 3-32 characters: a-z, 0-9, dot, dash, underscore")
            password = body.get("password")
            if password is not None and (not isinstance(password, str) or len(password) < 8):
                raise ApiError(400, "'password' must be text of at least 8 characters")
            with closing(connect()) as conn, conn:
                row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                if row is None and password is None:
                    raise ApiError(400, "'password' is required for a new user")
                new = {
                    "full_name": T(80)("full_name", body["full_name"]) if "full_name" in body else (row["full_name"] if row else None),
                    "role": E(*ROLES)("role", body["role"]) if "role" in body else (row["role"] if row else None),
                    "status": E("allowed", "revoked")("status", body["status"]) if "status" in body else (row["status"] if row else "allowed"),
                }
                if None in (new["full_name"], new["role"]):
                    raise ApiError(400, "'full_name' and 'role' are required for a new user")
                if row is not None and row["role"] == "admin" and (new["role"] != "admin" or new["status"] != "allowed"):
                    others = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND status='allowed' AND username != ?",
                                          (username,)).fetchone()[0]
                    if others == 0:
                        raise ApiError(409, "Cannot demote or revoke the last active administrator")
                pw_hash = hash_password(password) if password else (row["password_hash"] if row else None)
                conn.execute("INSERT INTO users (username, password_hash, full_name, role, status) VALUES (?,?,?,?,?) "
                             "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, "
                             "full_name=excluded.full_name, role=excluded.role, status=excluded.status",
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
            user = self.current_user()          # the role needed depends on the step, checked inside
            body = self.read_json()
            with closing(connect()) as conn, conn:
                approve_pr(conn, user, number, body)
                return 200, get_pr(conn, number)
        if method == "POST" and action == "convert":
            user = self.current_user({"admin", "purchasing"})
            body = self.read_json()
            with closing(connect()) as conn, conn:
                created = convert_pr(conn, user, number, body)
                orders = [shape(conn, RESOURCES["orders"], fetch_one(conn, RESOURCES["orders"], po)) for po in created]
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
                conn.execute("DELETE FROM purchase_requisitions WHERE pr_number = ?", (number,))
                audit(conn, user, "delete", "requisitions", number, {"status": pr["status"], "total": pr["estimated_total"]})
            return 200, {"deleted": True, "pr_number": number}
        raise ApiError(405, "Method not allowed")

    def order_actions(self, method, po_number, action):
        if method != "POST" or action not in ("receive", "lines"):
            raise ApiError(405, "Method not allowed")
        user = self.current_user(RECEIVERS if action == "receive" else {"admin", "purchasing"})
        body = self.read_json()
        with closing(connect()) as conn, conn:
            if action == "lines":
                set_po_lines(conn, user, po_number, body)
                return 200, shape(conn, RESOURCES["orders"], fetch_one(conn, RESOURCES["orders"], po_number))
            number = receive_goods(conn, user, po_number, body)
            grn = get_grn(conn, number)
            return 201, {"grn": grn, "ncrs": grn["ncrs"],
                         "purchase_order": shape(conn, RESOURCES["orders"], fetch_one(conn, RESOURCES["orders"], po_number))}

    def logistics(self, method, p, q):
        kind, number, action = p[0], (p[1] if len(p) > 1 else None), (p[2] if len(p) > 2 else None)
        if len(p) > 3:
            raise ApiError(404, "Endpoint not found")
        if method == "GET" and action is None:
            self.current_user()
            limit, offset = page_args(q)
            flt = {k: q[k][0] for k in (("po",) if kind == "grns" else ("po", "status")) if k in q}   # a GRN's status is derived, not stored
            where = ("WHERE " + " AND ".join(f"{'po_number' if k == 'po' else 'status'} = ?" for k in flt)) if flt else ""
            with closing(connect()) as conn:
                if kind == "grns":
                    if number:
                        return 200, get_grn(conn, number)
                    return 200, load_grns(conn, where, tuple(flt.values()), limit, offset)
                if kind == "invoices":
                    if number:
                        return 200, get_invoice(conn, number)
                    return 200, load_invoices(conn, where, tuple(flt.values()), limit, offset)
                if number:
                    row = conn.execute("SELECT * FROM ncrs WHERE ncr_number = ?", (number,)).fetchone()
                    if row is None:
                        raise ApiError(404, f"NCR {number!r} not found")
                    return 200, dict(row)
                rows = conn.execute(f"SELECT * FROM ncrs {where} ORDER BY created_at DESC, ncr_number DESC LIMIT ? OFFSET ?",
                                    (*flt.values(), limit, offset)).fetchall()
                return 200, [dict(r) for r in rows]
        if kind == "ncrs" and method == "POST" and action == "resolve" and number:
            user = self.current_user(QC_ROLES)
            body = self.read_json()
            with closing(connect()) as conn, conn:
                resolve_ncr(conn, user, number, body)
                return 200, dict(conn.execute("SELECT * FROM ncrs WHERE ncr_number = ?", (number,)).fetchone())
        if kind == "invoices":
            if method == "POST" and number is None:
                user = self.current_user(AP_ROLES)
                body = self.read_json()
                with closing(connect()) as conn, conn:
                    return 201, get_invoice(conn, create_invoice(conn, user, body))
            if method == "POST" and number and action in ("rematch", "release", "override"):
                user = self.current_user({"admin"} if action == "override" else (AP_ROLES | {"purchasing"} if action == "rematch" else AP_ROLES))
                body = self.read_json()
                reason = None
                if action == "override":
                    reject_unknown(body, {"reason"})
                    reason = T(500)("reason", body.get("reason"))
                with closing(connect()) as conn, conn:
                    get_invoice(conn, number)
                    if action == "rematch":
                        match_invoice(conn, number)
                    else:
                        release_invoice(conn, user, number, reason)
                    return 200, get_invoice(conn, number)
            if method == "DELETE" and number and action is None:
                user = self.current_user({"admin"})
                with closing(connect()) as conn, conn:
                    inv = get_invoice(conn, number)
                    if inv["status"] in (INV_RELEASED, INV_OVERRIDE):
                        raise ApiError(409, "A released invoice cannot be deleted")
                    conn.execute("DELETE FROM invoices WHERE ap_number = ?", (number,))
                    audit(conn, user, "delete", "invoices", number, {"total": inv["invoice_total"]})
                return 200, {"deleted": True, "ap_number": number}
        raise ApiError(405, "Method not allowed")

    def resource(self, method, res, rest, q):
        if method == "GET":
            self.current_user()
            with closing(connect()) as conn:
                if rest:
                    return 200, shape(conn, res, fetch_one(conn, res, rest[0]))
                def num(name, default, lo, hi):
                    v = q.get(name, [str(default)])[0]
                    return min(max(int(v), lo), hi) if v.isdigit() else default
                rows = conn.execute(f"SELECT * FROM {res['table']} ORDER BY {res['order']} LIMIT ? OFFSET ?",
                                    (num("limit", 200, 1, 1000), num("offset", 0, 0, 10 ** 9))).fetchall()
                return 200, [shape(conn, res, r) for r in rows]
        if method in ("POST", "PUT"):
            user = self.current_user(res["write_roles"])
            body = self.read_json()
            with closing(connect()) as conn, conn:
                created, row = upsert(conn, res, body, user, key=rest[0] if rest else None, update_only=(method == "PUT"))
                return (201 if created else 200), shape(conn, res, row)
        if method == "DELETE":
            user = self.current_user({"admin"})
            key = rest[0] if rest else q.get(res["pk"], [None])[0]
            if not key:
                raise ApiError(400, f"Provide the record key: /api/{res['name']}/<{res['pk']}>")
            with closing(connect()) as conn, conn:
                delete_record(conn, res, key, user)
            return 200, {"deleted": True, res["pk"]: key}
        raise ApiError(405, "Method not allowed")


def find_static(kind: str, name: str):
    """css/js file from its sub-folder, or - if the files were saved flat next to this script - from the same folder."""
    for candidate in (BASE_DIR / kind / name, BASE_DIR / name):
        if candidate.is_file():
            return candidate
    return None


def check_assets() -> None:
    if not INDEX_FILE.is_file():
        print("  WARNING: index.html was not found next to backend_server.py - the web page cannot be served.")
        return
    refs = re.findall(r'(?:src|href)="((?:css|js)/([\w.-]+))"', INDEX_FILE.read_text(encoding="utf-8"))
    missing = [ref for ref, name in refs if find_static(ref.split("/")[0], name) is None]
    if missing:
        print(f"  WARNING: {len(missing)} file(s) used by index.html are missing, so the page will look blank/unstyled:")
        print("           " + ", ".join(missing[:6]) + (" ..." if len(missing) > 6 else ""))
        print("           Keep the folder structure: index.html, css/ and js/ next to backend_server.py.")


def main() -> None:
    init_database()
    ThreadingHTTPServer.request_queue_size = 128   # default of 5 resets connections under bursts
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    shown = "localhost" if HOST in ("127.0.0.1", "0.0.0.0", "") else HOST
    print("=" * 60)
    print(f"  Procurement API v2 on http://{HOST}:{PORT}   (app: http://{shown}:{PORT}/)")
    print(f"  Database: {DB_FILE}")
    if not os.environ.get("PROC_SECRET"):
        print("  Note: PROC_SECRET not set - logins reset when the server restarts.")
    if HOST not in ("127.0.0.1", "localhost"):
        print("  Warning: listening beyond this machine without TLS - use a reverse proxy (HTTPS) for anything but a trusted LAN.")
    check_assets()
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Stopping procurement server.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
