"""
Purchasing & Procurement System — Standalone REST API Backend
============================================================
A complete, lightweight, production-ready backend service providing 
persistent storage for materials, suppliers, purchase orders, and TCO calculations.

Features:
- Built with Python standard library (http.server / sqlite3) for zero external dependencies.
- Can be run instantly with `python backend_server.py`.
- Includes full CORS support for browser frontends and intranet access.
- SQLite database persistence with automatic table initialization and seed data.
"""

import http.server
import socketserver
import json
import sqlite3
import urllib.parse
from datetime import datetime

DATABASE_FILE = "procurement_data.db"
PORT = 8000

def init_database():
    """Initializes SQLite database schemas for procurement operations."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # 1. Materials Master Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS materials (
        code TEXT PRIMARY KEY,
        category TEXT NOT NULL,
        name TEXT NOT NULL,
        specs TEXT NOT NULL,
        uom TEXT NOT NULL,
        current_stock REAL DEFAULT 0,
        safety_stock REAL DEFAULT 0,
        reorder_point REAL DEFAULT 0,
        std_cost REAL DEFAULT 0.0,
        supplier TEXT NOT NULL,
        status TEXT NOT NULL,
        tolerance TEXT,
        packaging TEXT,
        lead_time TEXT,
        bom_link TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 2. Suppliers Directory Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suppliers (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        tier TEXT NOT NULL,
        score INTEGER DEFAULT 80,
        price_metric INTEGER DEFAULT 20,
        quality_metric INTEGER DEFAULT 20,
        delivery_metric INTEGER DEFAULT 18,
        spec_metric INTEGER DEFAULT 12,
        terms_metric INTEGER DEFAULT 6,
        service_metric INTEGER DEFAULT 4,
        payment_terms TEXT NOT NULL,
        lead_time TEXT NOT NULL,
        contact TEXT NOT NULL,
        otif TEXT DEFAULT '95%',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # 3. Purchase Orders Pipeline Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchase_orders (
        po_number TEXT PRIMARY KEY,
        vendor TEXT NOT NULL,
        items TEXT NOT NULL,
        amount_usd REAL NOT NULL,
        due_date TEXT NOT NULL,
        status TEXT NOT NULL,
        alert TEXT NOT NULL,
        progress_pct INTEGER DEFAULT 25,
        dock_action TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # Seed initial datasets if empty
    cursor.execute("SELECT COUNT(*) FROM materials")
    if cursor.fetchone()[0] == 0:
        seed_sample_records(cursor)

    conn.commit()
    conn.close()
    print("[DB] SQLite database initialized and verified.")

def seed_sample_records(cursor):
    """Seeds master items, initial suppliers, and pipeline POs."""
    materials = [
        ("AL-76-SLD-BLK", "aluminum", "Sliding Frame Outer 76 Series", "Alloy 6063-T5 | 1.4mm | Powder Coated Matte Black RAL9005", "KG", 480, 300, 850, 2.65, "Asia Aluminum Extrusions Co.", "reorder", "± 0.05 mm", "Craft paper bundles of 4 pcs", "7 days", "SD-100 Sliding Window"),
        ("AL-50-CSM-SLV", "aluminum", "Casement Window Sash 50 Series", "Alloy 6063-T5 | 1.4mm | Anodized Natural Silver AA15", "KG", 1200, 400, 900, 2.75, "Asia Aluminum Extrusions Co.", "safe", "± 0.04 mm", "Master bundles with plastic separation", "7 days", "CW-50 Outward Casement"),
        ("GL-TMP-08-CLR", "glass", "8mm Clear Fully Tempered Glass", "Nominal 8mm | Flat polished edge | Arrissed corners", "SQM", 145, 100, 220, 15.50, "Crystal Float & Tempered Glass Ltd.", "low", "± 0.2 mm", "A-frame timber crates with cork pads", "5 days", "Sliding Patio Doors"),
        ("GL-IGU-24-LOWE", "glass", "Double Glazed Unit (6+12A+6)", "6mm Clear Low-E + 12mm Argon + 6mm Clear Tempered", "SQM", 210, 80, 160, 38.00, "Crystal Float & Tempered Glass Ltd.", "safe", "Dual sealed polyisobutylene", "Export wooden crates", "10 days", "Thermal Facades"),
        ("HD-ROL-TDM-120", "hardware", "Heavy Duty Tandem Roller 120KG", "SUS304 Stainless Steel Housing | Dual POM Wheels", "PAIR", 240, 200, 450, 4.80, "Kinlong Fenestration Hardware Co.", "low", "120KG rating / 100,000 cycles", "50 Pairs per carton", "10 days", "SD-100 Patio Door"),
        ("SL-EPDM-GSK-01", "sealant", "EPDM Wedge Gasket Strip", "Peroxide cured EPDM rubber | UV resistant | Shore A 65", "METER", 850, 1000, 2500, 0.32, "PolyTech Rubber & Polymer Industries", "reorder", "-40°C to +120°C", "Spools of 250 Meters", "6 days", "Glazing bead retention")
    ]
    cursor.executemany("""
    INSERT INTO materials (code, category, name, specs, uom, current_stock, safety_stock, reorder_point, std_cost, supplier, status, tolerance, packaging, lead_time, bom_link)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, materials)

    suppliers = [
        ("VND-ALU-01", "Asia Aluminum Extrusions Co.", "Aluminum Profiles", "Tier 1: Preferred", 92, 23, 24, 19, 14, 8, 4, "Net 45 Days", "7 Days", "Chen Wei (+855 12 889 001)", "97.4%"),
        ("VND-GLS-02", "Crystal Float & Tempered Glass Ltd.", "Architectural Glass", "Tier 1: Preferred", 89, 21, 25, 18, 14, 7, 4, "Net 30 Days", "5 Days", "Sokha Mean (+855 16 445 221)", "95.8%"),
        ("VND-HDW-03", "Kinlong Fenestration Hardware Co.", "Hardware & Accessories", "Tier 1: Preferred", 88, 22, 24, 18, 14, 6, 4, "Net 30 Days", "10 Days", "Li Qiang (+855 92 110 998)", "96.2%")
    ]
    cursor.executemany("""
    INSERT INTO suppliers (id, name, category, tier, score, price_metric, quality_metric, delivery_metric, spec_metric, terms_metric, service_metric, payment_terms, lead_time, contact, otif)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, suppliers)

    orders = [
        ("PO-2026-089", "Asia Aluminum Extrusions Co.", "AL-76 Sliding Frame Outer (2,500 KG)", 6625.00, "2026-09-24", "In Transit", "On Track", 75, "ETA in 2 days. Coordinate crane with Warehouse."),
        ("PO-2026-092", "PolyTech Rubber & Polymer Industries", "SL-EPDM Wedge Gaskets (3,000 M)", 960.00, "2026-09-20", "Delayed", "🔴 2 Days Overdue", 40, "Urgent Expediting required."),
        ("PO-2026-094", "Crystal Float & Tempered Glass Ltd.", "GL-TMP-08 8mm Tempered Glass (85 SQM)", 1317.50, "2026-09-22", "Arrived at Dock", "Inspection Today", 90, "Truck unloading at Bay 2.")
    ]
    cursor.executemany("""
    INSERT INTO purchase_orders (po_number, vendor, items, amount_usd, due_date, status, alert, progress_pct, dock_action)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, orders)

class ProcurementAPIHandler(http.server.BaseHTTPRequestHandler):
    """Handles RESTful HTTP requests for the procurement system."""

    def _set_headers(self, status_code=200, content_type="application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        # Enable CORS for browser integration
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        """Pre-flight CORS options handler."""
        self._set_headers(204)

    def do_GET(self):
        """Dispatches GET requests for materials, suppliers, POs, and KPIs."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            if path == "/api/health":
                self._set_headers(200)
                self.wfile.write(json.dumps({"status": "healthy", "service": "Procurement API", "timestamp": str(datetime.now())}).encode())

            elif path == "/api/materials":
                cursor.execute("SELECT * FROM materials ORDER BY code ASC")
                rows = [dict(row) for row in cursor.fetchall()]
                self._set_headers(200)
                self.wfile.write(json.dumps(rows).encode())

            elif path == "/api/suppliers":
                cursor.execute("SELECT * FROM suppliers ORDER BY score DESC")
                rows = [dict(row) for row in cursor.fetchall()]
                self._set_headers(200)
                self.wfile.write(json.dumps(rows).encode())

            elif path == "/api/orders":
                cursor.execute("SELECT * FROM purchase_orders ORDER BY due_date ASC")
                rows = [dict(row) for row in cursor.fetchall()]
                self._set_headers(200)
                self.wfile.write(json.dumps(rows).encode())

            elif path == "/api/kpi-summary":
                # Aggregate executive dashboard metrics
                cursor.execute("SELECT COUNT(*) FROM materials")
                sku_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM suppliers")
                vendor_count = cursor.fetchone()[0]

                cursor.execute("SELECT SUM(amount_usd), COUNT(*) FROM purchase_orders")
                po_agg = cursor.fetchone()
                po_val = po_agg[0] or 0.0
                po_count = po_agg[1] or 0

                cursor.execute("SELECT COUNT(*) FROM purchase_orders WHERE status = 'Delayed'")
                delayed_count = cursor.fetchone()[0]

                summary = {
                    "active_skus": sku_count,
                    "active_vendors": vendor_count,
                    "open_po_value": po_val,
                    "open_po_count": po_count,
                    "delayed_shipments": delayed_count
                }
                self._set_headers(200)
                self.wfile.write(json.dumps(summary).encode())

            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode())

        except Exception as e:
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": str(e)}).encode())
        finally:
            conn.close()

    def do_POST(self):
        """Handles record creation and Landed Cost engine calculations."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        body = json.loads(post_data) if post_data else {}

        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        try:
            if path == "/api/materials":
                cursor.execute("""
                INSERT OR REPLACE INTO materials 
                (code, category, name, specs, uom, current_stock, safety_stock, reorder_point, std_cost, supplier, status, tolerance, packaging, lead_time, bom_link)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get("code"), body.get("category"), body.get("name"), body.get("specs"),
                    body.get("uom"), body.get("current_stock", 0), body.get("safety_stock", 0),
                    body.get("reorder_point", 0), body.get("std_cost", 0.0), body.get("supplier"),
                    body.get("status", "safe"), body.get("tolerance"), body.get("packaging"),
                    body.get("lead_time"), body.get("bom_link")
                ))
                conn.commit()
                self._set_headers(201)
                self.wfile.write(json.dumps({"success": True, "code": body.get("code")}).encode())

            elif path == "/api/suppliers":
                cursor.execute("""
                INSERT OR REPLACE INTO suppliers 
                (id, name, category, tier, score, payment_terms, lead_time, contact, otif)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get("id"), body.get("name"), body.get("category"), body.get("tier"),
                    body.get("score", 85), body.get("payment_terms"), body.get("lead_time"),
                    body.get("contact"), body.get("otif", "95%")
                ))
                conn.commit()
                self._set_headers(201)
                self.wfile.write(json.dumps({"success": True, "id": body.get("id")}).encode())

            elif path == "/api/orders":
                cursor.execute("""
                INSERT OR REPLACE INTO purchase_orders 
                (po_number, vendor, items, amount_usd, due_date, status, alert, progress_pct, dock_action)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    body.get("po_number"), body.get("vendor"), body.get("items"),
                    body.get("amount_usd", 0.0), body.get("due_date"), body.get("status", "Order Confirmed"),
                    body.get("alert", "On Track"), body.get("progress_pct", 25), body.get("dock_action")
                ))
                conn.commit()
                self._set_headers(201)
                self.wfile.write(json.dumps({"success": True, "po_number": body.get("po_number")}).encode())

            elif path == "/api/calculate-landed-cost":
                # TCO Engine calculation
                qty = float(body.get("qty", 1))
                price = float(body.get("unit_price", 0))
                discount_pct = float(body.get("discount_pct", 0))
                freight = float(body.get("freight_cost", 0))
                other = float(body.get("other_cost", 0))

                net_price = price * (1.0 - (discount_pct / 100.0))
                overhead_unit = (freight + other) / max(qty, 1.0)
                true_landed_cost = round(net_price + overhead_unit, 4)

                res = {
                    "base_unit_price": price,
                    "discount_applied": discount_pct,
                    "net_purchase_price": round(net_price, 4),
                    "overhead_per_unit": round(overhead_unit, 4),
                    "true_landed_cost_per_unit": true_landed_cost,
                    "total_shipment_investment": round(true_landed_cost * qty, 2)
                }
                self._set_headers(200)
                self.wfile.write(json.dumps(res).encode())

            else:
                self._set_headers(404)
                self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode())

        except Exception as e:
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": str(e)}).encode())
        finally:
            conn.close()

    def do_DELETE(self):
        """Handles record deletions across collections."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()

        try:
            if path == "/api/materials" and "code" in query:
                code = query["code"][0]
                cursor.execute("DELETE FROM materials WHERE code = ?", (code,))
                conn.commit()
                self._set_headers(200)
                self.wfile.write(json.dumps({"deleted": True, "code": code}).encode())

            elif path == "/api/suppliers" and "id" in query:
                sup_id = query["id"][0]
                cursor.execute("DELETE FROM suppliers WHERE id = ?", (sup_id,))
                conn.commit()
                self._set_headers(200)
                self.wfile.write(json.dumps({"deleted": True, "id": sup_id}).encode())

            elif path == "/api/orders" and "po_number" in query:
                po_num = query["po_number"][0]
                cursor.execute("DELETE FROM purchase_orders WHERE po_number = ?", (po_num,))
                conn.commit()
                self._set_headers(200)
                self.wfile.write(json.dumps({"deleted": True, "po_number": po_num}).encode())

            else:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing key or invalid endpoint"}).encode())

        except Exception as e:
            self._set_headers(500)
            self.wfile.write(json.dumps({"error": str(e)}).encode())
        finally:
            conn.close()

def run_server():
    """Starts the procurement HTTP REST server."""
    init_database()
    with socketserver.TCPServer(("", PORT), ProcurementAPIHandler) as httpd:
        print(f"============================================================")
        print(f"  Procurement REST API Backend running on port {PORT}")
        print(f"  Local URL:   http://localhost:{PORT}")
        print(f"  Health Check: http://localhost:{PORT}/api/health")
        print(f"  Database:    {DATABASE_FILE} (SQLite)")
        print(f"============================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[SHUTDOWN] Stopping procurement server gracefully.")

if __name__ == "__main__":
    run_server()