"""
SQLite database layer for the Canada Tech Deal Tracker.

Handles schema creation, CRUD for products/price_history/alerts/settings,
and alert evaluation queries.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from config import DB_PATH, DEFAULT_SETTINGS


class Database:
    """SQLite wrapper for the deal tracker database."""

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS products (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    retailer        TEXT NOT NULL,
                    retailer_sku    TEXT NOT NULL,
                    name            TEXT NOT NULL,
                    url             TEXT NOT NULL,
                    category        TEXT NOT NULL,
                    brand           TEXT,
                    cpu_model       TEXT,
                    cpu_gen         INTEGER,
                    ram_gb          INTEGER,
                    storage_gb      INTEGER,
                    gpu             TEXT,
                    screen_size     REAL,
                    resolution      TEXT,
                    ram_type        TEXT,
                    ram_speed_mhz   INTEGER,
                    first_seen      TEXT NOT NULL,
                    last_seen       TEXT NOT NULL,
                    last_checked    TEXT NOT NULL,
                    is_active       INTEGER DEFAULT 1,
                    UNIQUE(retailer, retailer_sku)
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id      INTEGER NOT NULL REFERENCES products(id),
                    price           REAL NOT NULL,
                    original_price  REAL,
                    checked_at      TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_price_history_product
                    ON price_history(product_id, checked_at);

                CREATE TABLE IF NOT EXISTS alerts (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    name            TEXT NOT NULL,
                    category        TEXT NOT NULL,
                    retailer        TEXT,
                    keyword         TEXT,
                    max_price       REAL,
                    min_ram_gb      INTEGER,
                    min_storage_gb  INTEGER,
                    min_cpu_gen     INTEGER,
                    ram_type        TEXT,
                    form_factor     TEXT,
                    kit_config      TEXT,
                    min_speed_mhz   INTEGER,
                    max_cas_latency INTEGER,
                    brand           TEXT,
                    price_drop_pct  REAL,
                    price_drop_abs  REAL,
                    is_active       INTEGER DEFAULT 1,
                    created_at      TEXT NOT NULL,
                    last_triggered  TEXT,
                    cooldown_hours  INTEGER DEFAULT 24
                );

                CREATE TABLE IF NOT EXISTS notifications_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id        INTEGER REFERENCES alerts(id),
                    product_id      INTEGER REFERENCES products(id),
                    channel         TEXT NOT NULL,
                    subject         TEXT,
                    sent_at         TEXT NOT NULL,
                    success         INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key             TEXT PRIMARY KEY,
                    value           TEXT NOT NULL
                );
            """)
            conn.commit()

            # Migrate existing databases — add new columns if missing
            for col in ['form_factor', 'kit_config', 'brand']:
                try:
                    conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} TEXT")
                except Exception:
                    pass
            for col in ['min_speed_mhz', 'max_cas_latency']:
                try:
                    conn.execute(f"ALTER TABLE alerts ADD COLUMN {col} INTEGER")
                except Exception:
                    pass
            conn.commit()

            # Seed default settings
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value)
                )
            conn.commit()
        finally:
            conn.close()

    # ── Settings ──

    def get_setting(self, key):
        conn = self._connect()
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row['value'] if row else None
        finally:
            conn.close()

    def set_setting(self, key, value):
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value))
            )
            conn.commit()
        finally:
            conn.close()

    def get_all_settings(self):
        conn = self._connect()
        try:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            return {row['key']: row['value'] for row in rows}
        finally:
            conn.close()

    # ── Products ──

    def upsert_product(self, product_dict):
        """Insert or update a product. Returns the product id.

        product_dict should have: retailer, retailer_sku, name, url, category,
        and optionally: brand, cpu_model, cpu_gen, ram_gb, storage_gb, gpu,
        screen_size, resolution, ram_type, ram_speed_mhz
        """
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            # Check if product exists
            existing = conn.execute(
                "SELECT id FROM products WHERE retailer = ? AND retailer_sku = ?",
                (product_dict['retailer'], product_dict['retailer_sku'])
            ).fetchone()

            if existing:
                product_id = existing['id']
                conn.execute("""
                    UPDATE products SET
                        name = ?, url = ?, category = ?, brand = ?,
                        cpu_model = ?, cpu_gen = ?, ram_gb = ?, storage_gb = ?,
                        gpu = ?, screen_size = ?, resolution = ?,
                        ram_type = ?, ram_speed_mhz = ?,
                        last_seen = ?, last_checked = ?, is_active = 1
                    WHERE id = ?
                """, (
                    product_dict['name'], product_dict['url'], product_dict['category'],
                    product_dict.get('brand'),
                    product_dict.get('cpu_model'), product_dict.get('cpu_gen'),
                    product_dict.get('ram_gb'), product_dict.get('storage_gb'),
                    product_dict.get('gpu'), product_dict.get('screen_size'),
                    product_dict.get('resolution'),
                    product_dict.get('ram_type'), product_dict.get('ram_speed_mhz'),
                    now, now, product_id
                ))
            else:
                cursor = conn.execute("""
                    INSERT INTO products (
                        retailer, retailer_sku, name, url, category, brand,
                        cpu_model, cpu_gen, ram_gb, storage_gb, gpu,
                        screen_size, resolution, ram_type, ram_speed_mhz,
                        first_seen, last_seen, last_checked
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    product_dict['retailer'], product_dict['retailer_sku'],
                    product_dict['name'], product_dict['url'], product_dict['category'],
                    product_dict.get('brand'),
                    product_dict.get('cpu_model'), product_dict.get('cpu_gen'),
                    product_dict.get('ram_gb'), product_dict.get('storage_gb'),
                    product_dict.get('gpu'), product_dict.get('screen_size'),
                    product_dict.get('resolution'),
                    product_dict.get('ram_type'), product_dict.get('ram_speed_mhz'),
                    now, now, now
                ))
                product_id = cursor.lastrowid

            conn.commit()
            return product_id
        finally:
            conn.close()

    def record_price(self, product_id, price, original_price=None):
        """Record a price observation for a product."""
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO price_history (product_id, price, original_price, checked_at) "
                "VALUES (?, ?, ?, ?)",
                (product_id, price, original_price, now)
            )
            conn.commit()
        finally:
            conn.close()

    def get_tracked_products(self, category=None, retailer=None, active_only=True):
        """Get all tracked products, optionally filtered."""
        conn = self._connect()
        try:
            query = "SELECT * FROM products WHERE 1=1"
            params = []
            if active_only:
                query += " AND is_active = 1"
            if category:
                query += " AND category = ?"
                params.append(category)
            if retailer:
                query += " AND retailer = ?"
                params.append(retailer)
            query += " ORDER BY last_seen DESC"
            return [dict(row) for row in conn.execute(query, params).fetchall()]
        finally:
            conn.close()

    def get_product_by_id(self, product_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_price_history(self, product_id, days=90):
        """Get price history for a product over the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT price, original_price, checked_at FROM price_history "
                "WHERE product_id = ? AND checked_at >= ? ORDER BY checked_at",
                (product_id, cutoff)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_latest_price(self, product_id):
        """Get the most recent price for a product."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT price, original_price, checked_at FROM price_history "
                "WHERE product_id = ? ORDER BY checked_at DESC LIMIT 1",
                (product_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_price_stats(self, product_id):
        """Get price statistics: min, max, avg, current."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT MIN(price) as min_price, MAX(price) as max_price, "
                "AVG(price) as avg_price FROM price_history WHERE product_id = ?",
                (product_id,)
            ).fetchone()
            stats = dict(row) if row else {}
            latest = self.get_latest_price(product_id)
            if latest:
                stats['current_price'] = latest['price']
                stats['last_checked'] = latest['checked_at']
            return stats
        finally:
            conn.close()

    def delete_product(self, product_id):
        """Remove a product and its price history."""
        conn = self._connect()
        try:
            conn.execute("DELETE FROM price_history WHERE product_id = ?", (product_id,))
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()
        finally:
            conn.close()

    # ── Alerts ──

    def create_alert(self, alert_dict):
        """Create a new alert. Returns the alert id."""
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            cursor = conn.execute("""
                INSERT INTO alerts (
                    name, category, retailer, keyword, max_price,
                    min_ram_gb, min_storage_gb, min_cpu_gen, ram_type,
                    form_factor, kit_config, min_speed_mhz, max_cas_latency, brand,
                    price_drop_pct, price_drop_abs, cooldown_hours, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert_dict['name'], alert_dict['category'],
                alert_dict.get('retailer'), alert_dict.get('keyword'),
                alert_dict.get('max_price'),
                alert_dict.get('min_ram_gb'), alert_dict.get('min_storage_gb'),
                alert_dict.get('min_cpu_gen'), alert_dict.get('ram_type'),
                alert_dict.get('form_factor'), alert_dict.get('kit_config'),
                alert_dict.get('min_speed_mhz'), alert_dict.get('max_cas_latency'),
                alert_dict.get('brand'),
                alert_dict.get('price_drop_pct'), alert_dict.get('price_drop_abs'),
                alert_dict.get('cooldown_hours', 24), now
            ))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_alerts(self, active_only=True):
        conn = self._connect()
        try:
            query = "SELECT * FROM alerts"
            if active_only:
                query += " WHERE is_active = 1"
            query += " ORDER BY created_at DESC"
            return [dict(row) for row in conn.execute(query).fetchall()]
        finally:
            conn.close()

    def get_alert_by_id(self, alert_id):
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_alert(self, alert_id, **kwargs):
        """Update alert fields. Pass field=value pairs."""
        conn = self._connect()
        try:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values()) + [alert_id]
            conn.execute(f"UPDATE alerts SET {sets} WHERE id = ?", vals)
            conn.commit()
        finally:
            conn.close()

    def delete_alert(self, alert_id):
        conn = self._connect()
        try:
            conn.execute("DELETE FROM notifications_log WHERE alert_id = ?", (alert_id,))
            conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
            conn.commit()
        finally:
            conn.close()

    def toggle_alert(self, alert_id):
        """Toggle an alert's active status. Returns new status."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE alerts SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END "
                "WHERE id = ?", (alert_id,)
            )
            conn.commit()
            row = conn.execute("SELECT is_active FROM alerts WHERE id = ?", (alert_id,)).fetchone()
            return bool(row['is_active']) if row else None
        finally:
            conn.close()

    # ── Notifications Log ──

    def log_notification(self, alert_id, product_id, channel, subject, success):
        now = datetime.utcnow().isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO notifications_log (alert_id, product_id, channel, subject, sent_at, success) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (alert_id, product_id, channel, subject, now, int(success))
            )
            conn.commit()
        finally:
            conn.close()

    def get_recent_notifications(self, limit=50):
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT n.*, a.name as alert_name, p.name as product_name "
                "FROM notifications_log n "
                "LEFT JOIN alerts a ON n.alert_id = a.id "
                "LEFT JOIN products p ON n.product_id = p.id "
                "ORDER BY n.sent_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ── Alert Evaluation ──

    def find_products_matching_alert(self, alert):
        """Find products that match an alert's criteria."""
        conn = self._connect()
        try:
            query = "SELECT p.*, ph.price, ph.original_price, ph.checked_at FROM products p "
            query += "LEFT JOIN (SELECT product_id, price, original_price, checked_at FROM price_history "
            query += "WHERE id IN (SELECT MAX(id) FROM price_history GROUP BY product_id)) ph "
            query += "ON p.id = ph.product_id WHERE p.is_active = 1"
            params = []

            if alert.get('category'):
                query += " AND p.category = ?"
                params.append(alert['category'])
            if alert.get('retailer'):
                query += " AND p.retailer = ?"
                params.append(alert['retailer'])
            if alert.get('keyword'):
                query += " AND LOWER(p.name) LIKE ?"
                params.append(f"%{alert['keyword'].lower()}%")
            if alert.get('max_price'):
                query += " AND ph.price <= ?"
                params.append(alert['max_price'])
            if alert.get('min_ram_gb'):
                query += " AND p.ram_gb >= ?"
                params.append(alert['min_ram_gb'])
            if alert.get('min_storage_gb'):
                query += " AND p.storage_gb >= ?"
                params.append(alert['min_storage_gb'])
            if alert.get('min_cpu_gen'):
                query += " AND p.cpu_gen >= ?"
                params.append(alert['min_cpu_gen'])
            if alert.get('ram_type'):
                query += " AND p.ram_type = ?"
                params.append(alert['ram_type'])

            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def check_price_drop(self, product_id, drop_pct=None, drop_abs=None):
        """Check if a product's latest price dropped compared to previous check.

        Returns (dropped, current_price, previous_price) or (False, None, None).
        """
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT price FROM price_history WHERE product_id = ? "
                "ORDER BY checked_at DESC LIMIT 2",
                (product_id,)
            ).fetchall()

            if len(rows) < 2:
                return False, None, None

            current = rows[0]['price']
            previous = rows[1]['price']

            if previous <= 0:
                return False, current, previous

            dropped = False
            if drop_pct and previous > 0:
                pct_change = ((previous - current) / previous) * 100
                if pct_change >= drop_pct:
                    dropped = True
            if drop_abs:
                if (previous - current) >= drop_abs:
                    dropped = True

            return dropped, current, previous
        finally:
            conn.close()
