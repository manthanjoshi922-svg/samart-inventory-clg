import os
import re
import hashlib
import mysql.connector
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "YOUR_MYSQL_PASSWORD")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "smart_inventory")


class MySQLCursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class MySQLConnectionAdapter:
    def __init__(self):
        self.connection = mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE
        )

    def execute(self, sql, params=()):
        statement = sql.strip()
        upper = statement.upper()

        pragma_match = re.match(
            r"PRAGMA\\s+TABLE_INFO\\(([^)]+)\\)",
            statement,
            re.IGNORECASE
        )
        if pragma_match:
            table_name = pragma_match.group(1).strip().strip('"`')
            cursor = self.connection.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT
                    ORDINAL_POSITION AS cid,
                    COLUMN_NAME AS name,
                    COLUMN_TYPE AS type,
                    IS_NULLABLE AS notnull,
                    COLUMN_DEFAULT AS dflt_value,
                    '' AS pk
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (MYSQL_DATABASE, table_name)
            )
            return MySQLCursorAdapter(cursor)

        sql = sql.replace("?", "%s")
        cursor = self.connection.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        return MySQLCursorAdapter(cursor)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        if self.connection.is_connected():
            self.connection.close()


def get_connection():
    return MySQLConnectionAdapter()


def hash_password(password):
    return hashlib.sha256(
        str(password).encode("utf-8")
    ).hexdigest()


def column_exists(conn, table_name, column_name):
    row = conn.execute(
        """
        SELECT COUNT(*) AS value
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
          AND COLUMN_NAME = ?
        """,
        (MYSQL_DATABASE, table_name, column_name)
    ).fetchone()
    return bool(row and row["value"])


def add_column_if_missing(
    conn,
    table_name,
    column_name,
    definition
):
    if not column_exists(conn, table_name, column_name):
        conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN {column_name} {definition}
            """
        )


def initialize_database():
    conn = get_connection()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                name VARCHAR(150),
                role VARCHAR(50) NOT NULL DEFAULT 'retailer',
                email VARCHAR(255),
                phone VARCHAR(50),
                created_at DATETIME
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS retailers (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id INT,
                name VARCHAR(150),
                username VARCHAR(100),
                email VARCHAR(255),
                phone VARCHAR(50),
                address TEXT,
                created_at DATETIME
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(200) NOT NULL,
                sku VARCHAR(100),
                category VARCHAR(100),
                quantity INT DEFAULT 0,
                price DECIMAL(12,2) DEFAULT 0,
                reorder_level INT DEFAULT 5,
                barcode VARCHAR(100),
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sales (
                id INT AUTO_INCREMENT PRIMARY KEY,
                product_id INT,
                retailer_id INT,
                quantity INT DEFAULT 1,
                unit_price DECIMAL(12,2) DEFAULT 0,
                total_amount DECIMAL(12,2) DEFAULT 0,
                total DECIMAL(12,2) DEFAULT 0,
                invoice_number VARCHAR(100),
                sale_date DATETIME,
                created_at DATETIME,
                payment_status VARCHAR(50) NOT NULL DEFAULT 'Pending'
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sale_id INT,
                retailer_id INT,
                amount DECIMAL(12,2) DEFAULT 0,
                invoice_number VARCHAR(100),
                status VARCHAR(50) DEFAULT 'Pending',
                payment_status VARCHAR(50) DEFAULT 'Pending',
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices (
                id INT AUTO_INCREMENT PRIMARY KEY,
                sale_id INT,
                invoice_number VARCHAR(100),
                retailer_id INT,
                product_id INT,
                product_name VARCHAR(200),
                quantity INT DEFAULT 1,
                unit_price DECIMAL(12,2) DEFAULT 0,
                total_amount DECIMAL(12,2) DEFAULT 0,
                total DECIMAL(12,2) DEFAULT 0,
                invoice_date DATETIME,
                email_status VARCHAR(50) DEFAULT 'Not Sent',
                created_at DATETIME
            )
            """
        )

        add_column_if_missing(conn, "users", "email", "VARCHAR(255)")
        add_column_if_missing(conn, "users", "phone", "VARCHAR(50)")
        add_column_if_missing(conn, "users", "created_at", "DATETIME")

        add_column_if_missing(conn, "retailers", "user_id", "INT")
        add_column_if_missing(conn, "retailers", "name", "VARCHAR(150)")
        add_column_if_missing(conn, "retailers", "username", "VARCHAR(100)")
        add_column_if_missing(conn, "retailers", "email", "VARCHAR(255)")
        add_column_if_missing(conn, "retailers", "phone", "VARCHAR(50)")
        add_column_if_missing(conn, "retailers", "address", "TEXT")
        add_column_if_missing(conn, "retailers", "created_at", "DATETIME")

        add_column_if_missing(conn, "products", "sku", "VARCHAR(100)")
        add_column_if_missing(conn, "products", "category", "VARCHAR(100)")
        add_column_if_missing(conn, "products", "quantity", "INT DEFAULT 0")
        add_column_if_missing(conn, "products", "price", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "products", "reorder_level", "INT DEFAULT 5")
        add_column_if_missing(conn, "products", "barcode", "VARCHAR(100)")
        add_column_if_missing(conn, "products", "created_at", "DATETIME")
        add_column_if_missing(conn, "products", "updated_at", "DATETIME")

        add_column_if_missing(conn, "sales", "product_id", "INT")
        add_column_if_missing(conn, "sales", "retailer_id", "INT")
        add_column_if_missing(conn, "sales", "quantity", "INT DEFAULT 1")
        add_column_if_missing(conn, "sales", "unit_price", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "sales", "total_amount", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "sales", "total", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "sales", "invoice_number", "VARCHAR(100)")
        add_column_if_missing(conn, "sales", "sale_date", "DATETIME")
        add_column_if_missing(conn, "sales", "created_at", "DATETIME")
        add_column_if_missing(conn, "sales", "payment_status", "VARCHAR(50) DEFAULT 'Pending'")

        add_column_if_missing(conn, "payments", "sale_id", "INT")
        add_column_if_missing(conn, "payments", "retailer_id", "INT")
        add_column_if_missing(conn, "payments", "amount", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "payments", "invoice_number", "VARCHAR(100)")
        add_column_if_missing(conn, "payments", "status", "VARCHAR(50) DEFAULT 'Pending'")
        add_column_if_missing(conn, "payments", "payment_status", "VARCHAR(50) DEFAULT 'Pending'")
        add_column_if_missing(conn, "payments", "created_at", "DATETIME")
        add_column_if_missing(conn, "payments", "updated_at", "DATETIME")

        add_column_if_missing(conn, "invoices", "sale_id", "INT")
        add_column_if_missing(conn, "invoices", "invoice_number", "VARCHAR(100)")
        add_column_if_missing(conn, "invoices", "retailer_id", "INT")
        add_column_if_missing(conn, "invoices", "product_id", "INT")
        add_column_if_missing(conn, "invoices", "product_name", "VARCHAR(200)")
        add_column_if_missing(conn, "invoices", "quantity", "INT DEFAULT 1")
        add_column_if_missing(conn, "invoices", "unit_price", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "invoices", "total_amount", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "invoices", "total", "DECIMAL(12,2) DEFAULT 0")
        add_column_if_missing(conn, "invoices", "invoice_date", "DATETIME")
        add_column_if_missing(conn, "invoices", "email_status", "VARCHAR(50) DEFAULT 'Not Sent'")
        add_column_if_missing(conn, "invoices", "created_at", "DATETIME")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            """
            UPDATE products
            SET sku = CONCAT('SKU-', id)
            WHERE sku IS NULL OR TRIM(sku) = ''
            """
        )

        conn.execute(
            """
            UPDATE products
            SET quantity = 0
            WHERE quantity IS NULL
            """
        )

        conn.execute(
            """
            UPDATE products
            SET price = 0
            WHERE price IS NULL
            """
        )

        conn.execute(
            """
            UPDATE products
            SET reorder_level = 5
            WHERE reorder_level IS NULL
            """
        )

        conn.execute(
            """
            UPDATE products
            SET barcode = sku
            WHERE barcode IS NULL OR TRIM(barcode) = ''
            """
        )

        conn.execute(
            """
            UPDATE sales
            SET total_amount = total
            WHERE (total_amount IS NULL OR total_amount = 0)
              AND total IS NOT NULL
            """
        )

        conn.execute(
            """
            UPDATE sales
            SET total = total_amount
            WHERE (total IS NULL OR total = 0)
              AND total_amount IS NOT NULL
            """
        )

        conn.execute(
            """
            UPDATE sales
            SET payment_status = 'Pending'
            WHERE payment_status IS NULL OR TRIM(payment_status) = ''
            """
        )

        conn.execute(
            """
            UPDATE users
            SET created_at = ?
            WHERE created_at IS NULL
            """,
            (now,)
        )

        conn.execute(
            """
            UPDATE products
            SET created_at = ?
            WHERE created_at IS NULL
            """,
            (now,)
        )

        create_default_users(conn)
        sync_retailers(conn)
        conn.commit()

    finally:
        conn.close()


def create_default_users(conn):
    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    admin_password = hash_password(
        "admin123"
    )

    retailer_password = hash_password(
        "retail123"
    )

    existing_admin = conn.execute(
        """
        SELECT id
        FROM users
        WHERE username = 'admin'
        LIMIT 1
        """
    ).fetchone()

    if existing_admin:
        conn.execute(
            """
            UPDATE users
            SET password = ?,
                name = ?,
                role = ?,
                created_at = COALESCE(
                    created_at,
                    ?
                )
            WHERE username = 'admin'
            """,
            (
                admin_password,
                "System Manager",
                "management",
                now
            )
        )
    else:
        conn.execute(
            """
            INSERT INTO users
            (
                username,
                password,
                name,
                role,
                created_at
            )
            VALUES (?,?,?,?,?)
            """,
            (
                "admin",
                admin_password,
                "System Manager",
                "management",
                now
            )
        )

    existing_retailer = conn.execute(
        """
        SELECT id
        FROM users
        WHERE username = 'retailer1'
        LIMIT 1
        """
    ).fetchone()

    if existing_retailer:
        conn.execute(
            """
            UPDATE users
            SET password = ?,
                name = ?,
                role = ?,
                created_at = COALESCE(
                    created_at,
                    ?
                )
            WHERE username = 'retailer1'
            """,
            (
                retailer_password,
                "Demo Retailer",
                "retailer",
                now
            )
        )
    else:
        conn.execute(
            """
            INSERT INTO users
            (
                username,
                password,
                name,
                role,
                created_at
            )
            VALUES (?,?,?,?,?)
            """,
            (
                "retailer1",
                retailer_password,
                "Demo Retailer",
                "retailer",
                now
            )
        )


def sync_retailers(conn):
    users = conn.execute(
        """
        SELECT *
        FROM users
        WHERE role = 'retailer'
        """
    ).fetchall()

    for user in users:
        existing = conn.execute(
            """
            SELECT id
            FROM retailers
            WHERE user_id = ?
            LIMIT 1
            """,
            (user["id"],)
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE retailers
                SET name = ?,
                    username = ?,
                    email = ?,
                    phone = ?
                WHERE user_id = ?
                """,
                (
                    user["name"],
                    user["username"],
                    user["email"],
                    user["phone"],
                    user["id"]
                )
            )
        else:
            conn.execute(
                """
                INSERT INTO retailers
                (
                    user_id,
                    name,
                    username,
                    email,
                    phone,
                    created_at
                )
                VALUES (?,?,?,?,?,?)
                """,
                (
                    user["id"],
                    user["name"],
                    user["username"],
                    user["email"],
                    user["phone"],
                    datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )
            )


def authenticate(username, password):
    if not username or not password:
        return None

    conn = get_connection()

    try:
        login_name = str(username).strip()
        raw_password = str(password)
        hashed = hash_password(raw_password)

        user = conn.execute(
            """
            SELECT *
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (login_name,)
        ).fetchone()

        if not user:
            return None

        stored = str(user["password"] or "")

        if stored == hashed:
            return dict(user)

        if stored == raw_password:
            conn.execute(
                "UPDATE users SET password = ? WHERE id = ?",
                (hashed, user["id"])
            )
            conn.commit()
            updated = dict(user)
            updated["password"] = hashed
            return updated

        return None

    finally:
        conn.close()


def get_users():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM users
            ORDER BY id DESC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def get_products():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM products
            ORDER BY id DESC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def get_product(product_id):
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM products
            WHERE id = ?
            LIMIT 1
            """,
            (int(product_id),)
        ).fetchone()

        if row:
            return dict(row)

        return None

    finally:
        conn.close()


def search_products(search_text):
    conn = get_connection()

    try:
        search_text = str(
            search_text or ""
        ).strip()

        if not search_text:
            rows = conn.execute(
                """
                SELECT *
                FROM products
                ORDER BY id DESC
                """
            ).fetchall()
        else:
            pattern = "%" + search_text + "%"

            rows = conn.execute(
                """
                SELECT *
                FROM products
                WHERE name LIKE ?
                   OR sku LIKE ?
                   OR category LIKE ?
                   OR barcode LIKE ?
                ORDER BY id DESC
                """,
                (
                    pattern,
                    pattern,
                    pattern,
                    pattern
                )
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def add_product(
    name,
    sku,
    category,
    quantity,
    price,
    reorder_level=5
):
    conn = get_connection()

    try:
        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        sku = str(
            sku or ""
        ).strip()

        if not sku:
            sku = (
                "SKU-"
                + datetime.now().strftime(
                    "%Y%m%d%H%M%S%f"
                )
            )

        cursor = conn.execute(
            """
            INSERT INTO products
            (
                name,
                sku,
                category,
                quantity,
                price,
                reorder_level,
                barcode,
                created_at,
                updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                str(name or "").strip(),
                sku,
                str(category or "").strip(),
                int(quantity or 0),
                float(price or 0),
                int(reorder_level or 5),
                sku,
                now,
                now
            )
        )

        conn.commit()

        return cursor.lastrowid

    finally:
        conn.close()


def update_product(
    product_id,
    name,
    sku,
    category,
    quantity,
    price,
    reorder_level
):
    conn = get_connection()

    try:
        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        conn.execute(
            """
            UPDATE products
            SET name = ?,
                sku = ?,
                category = ?,
                quantity = ?,
                price = ?,
                reorder_level = ?,
                barcode = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                str(name or "").strip(),
                str(sku or "").strip(),
                str(category or "").strip(),
                int(quantity or 0),
                float(price or 0),
                int(reorder_level or 5),
                str(sku or "").strip(),
                now,
                int(product_id)
            )
        )

        conn.commit()

        return True

    finally:
        conn.close()


def delete_product(product_id):
    conn = get_connection()

    try:
        conn.execute(
            """
            DELETE FROM products
            WHERE id = ?
            """,
            (int(product_id),)
        )

        conn.commit()

        return True

    finally:
        conn.close()


def get_retailers():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT
                r.id,
                r.user_id,
                r.name,
                r.username,
                r.email,
                r.phone,
                r.address,
                r.created_at
            FROM retailers r
            ORDER BY r.id DESC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def get_retailer_by_user_id(user_id):
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM retailers
            WHERE user_id = ?
            LIMIT 1
            """,
            (int(user_id),)
        ).fetchone()

        if row:
            return dict(row)

        return None

    finally:
        conn.close()


def resolve_retailer_id(retailer_id):
    conn = get_connection()

    try:
        retailer_id = int(
            retailer_id
        )

        row = conn.execute(
            """
            SELECT id
            FROM retailers
            WHERE id = ?
            LIMIT 1
            """,
            (retailer_id,)
        ).fetchone()

        if row:
            return int(row["id"])

        row = conn.execute(
            """
            SELECT id
            FROM retailers
            WHERE user_id = ?
            LIMIT 1
            """,
            (retailer_id,)
        ).fetchone()

        if row:
            return int(row["id"])

        return retailer_id

    finally:
        conn.close()


def add_retailer(
    retailer_name,
    username,
    password,
    email="",
    phone="",
    address=""
):
    conn = get_connection()

    try:
        existing = conn.execute(
            """
            SELECT id
            FROM users
            WHERE username = ?
            LIMIT 1
            """,
            (
                str(username).strip(),
            )
        ).fetchone()

        if existing:
            raise Exception(
                "Username already exists."
            )

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        cursor = conn.execute(
            """
            INSERT INTO users
            (
                username,
                password,
                name,
                role,
                email,
                phone,
                created_at
            )
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                str(username).strip(),
                hash_password(password),
                str(retailer_name).strip(),
                "retailer",
                str(email or "").strip(),
                str(phone or "").strip(),
                now
            )
        )

        user_id = cursor.lastrowid

        cursor = conn.execute(
            """
            INSERT INTO retailers
            (
                user_id,
                name,
                username,
                email,
                phone,
                address,
                created_at
            )
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                user_id,
                str(retailer_name).strip(),
                str(username).strip(),
                str(email or "").strip(),
                str(phone or "").strip(),
                str(address or "").strip(),
                now
            )
        )

        retailer_id = cursor.lastrowid

        conn.commit()

        return retailer_id

    finally:
        conn.close()


def update_retailer(
    retailer_id,
    name,
    email="",
    phone="",
    address=""
):
    conn = get_connection()

    try:
        retailer_id = int(
            retailer_id
        )

        row = conn.execute(
            """
            SELECT *
            FROM retailers
            WHERE id = ?
            LIMIT 1
            """,
            (retailer_id,)
        ).fetchone()

        if not row:
            return False

        conn.execute(
            """
            UPDATE retailers
            SET name = ?,
                email = ?,
                phone = ?,
                address = ?
            WHERE id = ?
            """,
            (
                name,
                email,
                phone,
                address,
                retailer_id
            )
        )

        if row["user_id"]:
            conn.execute(
                """
                UPDATE users
                SET name = ?,
                    email = ?,
                    phone = ?
                WHERE id = ?
                """,
                (
                    name,
                    email,
                    phone,
                    row["user_id"]
                )
            )

        conn.commit()

        return True

    finally:
        conn.close()


def delete_retailer(retailer_id):
    conn = get_connection()

    try:
        retailer_id = int(
            retailer_id
        )

        row = conn.execute(
            """
            SELECT user_id
            FROM retailers
            WHERE id = ?
            LIMIT 1
            """,
            (retailer_id,)
        ).fetchone()

        conn.execute(
            """
            DELETE FROM retailers
            WHERE id = ?
            """,
            (retailer_id,)
        )

        if row and row["user_id"]:
            conn.execute(
                """
                DELETE FROM users
                WHERE id = ?
                  AND role = 'retailer'
                """,
                (row["user_id"],)
            )

        conn.commit()

        return True

    finally:
        conn.close()


def get_dashboard_stats():
    conn = get_connection()

    try:
        total_products = conn.execute(
            """
            SELECT COUNT(*) AS value
            FROM products
            """
        ).fetchone()["value"]

        total_stock = conn.execute(
            """
            SELECT COALESCE(
                SUM(quantity),
                0
            ) AS value
            FROM products
            """
        ).fetchone()["value"]

        total_retailers = conn.execute(
            """
            SELECT COUNT(*) AS value
            FROM retailers
            """
        ).fetchone()["value"]

        total_sales = conn.execute(
            """
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN total_amount IS NOT NULL
                        THEN total_amount
                        ELSE total
                    END
                ),
                0
            ) AS value
            FROM sales
            """
        ).fetchone()["value"]

        return {
            "total_products":
                int(total_products or 0),

            "total_stock":
                int(total_stock or 0),

            "total_retailers":
                int(total_retailers or 0),

            "total_sales":
                float(total_sales or 0)
        }

    finally:
        conn.close()


def get_dashboard_statistics():
    return get_dashboard_stats()


def add_sale(
    product_id,
    retailer_id,
    quantity,
    unit_price=None,
    invoice_number=None
):
    conn = get_connection()

    try:
        product = conn.execute(
            """
            SELECT *
            FROM products
            WHERE id = ?
            LIMIT 1
            """,
            (int(product_id),)
        ).fetchone()

        if not product:
            raise Exception(
                "Product not found."
            )

        quantity = int(quantity)

        if quantity <= 0:
            raise Exception(
                "Quantity must be greater than zero."
            )

        available = int(
            product["quantity"] or 0
        )

        if quantity > available:
            raise Exception(
                f"Insufficient stock. "
                f"Available: {available}"
            )

        if unit_price is None:
            unit_price = float(
                product["price"] or 0
            )

        unit_price = float(
            unit_price
        )

        total_amount = (
            quantity * unit_price
        )

        if not invoice_number:
            invoice_number = (
                "INV-"
                + datetime.now().strftime(
                    "%Y%m%d%H%M%S%f"
                )
            )

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        actual_retailer_id = resolve_retailer_id(
            retailer_id
        )

        cursor = conn.execute(
            """
            INSERT INTO sales
            (
                product_id,
                retailer_id,
                quantity,
                unit_price,
                total_amount,
                total,
                invoice_number,
                sale_date,
                created_at,
                payment_status
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                int(product_id),
                actual_retailer_id,
                quantity,
                unit_price,
                total_amount,
                total_amount,
                invoice_number,
                now,
                now,
                "Pending"
            )
        )

        conn.execute(
            """
            UPDATE products
            SET quantity = quantity - ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                quantity,
                now,
                int(product_id)
            )
        )

        conn.commit()

        return cursor.lastrowid

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def get_sales(retailer_id=None):
    conn = get_connection()

    try:
        query = """
            SELECT
                s.*,
                p.name AS product_name,
                p.sku AS sku,
                r.name AS retailer_name,
                r.username AS retailer_username,
                r.email AS retailer_email
            FROM sales s
            LEFT JOIN products p
                ON s.product_id = p.id
            LEFT JOIN retailers r
                ON s.retailer_id = r.id
        """

        params = []

        if retailer_id is not None:
            actual_retailer_id = resolve_retailer_id(
                retailer_id
            )

            query += """
                WHERE s.retailer_id = ?
            """

            params.append(
                actual_retailer_id
            )

        query += """
            ORDER BY s.id DESC
        """

        rows = conn.execute(
            query,
            params
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def create_invoice(
    invoice_number,
    retailer_id,
    product_id,
    quantity,
    unit_price,
    total_amount=None,
    invoice_date=None,
    sale_id=None
):
    conn = get_connection()

    try:
        quantity = int(
            quantity or 0
        )

        unit_price = float(
            unit_price or 0
        )

        if total_amount is None:
            total_amount = (
                quantity * unit_price
            )

        total_amount = float(
            total_amount or 0
        )

        if not invoice_date:
            invoice_date = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        actual_retailer_id = resolve_retailer_id(
            retailer_id
        )

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        if sale_id is None:
            existing_sale = conn.execute(
                """
                SELECT id
                FROM sales
                WHERE invoice_number = ?
                  AND product_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (
                    invoice_number,
                    int(product_id)
                )
            ).fetchone()

            if existing_sale:
                sale_id = existing_sale["id"]

        cursor = conn.execute(
            """
            INSERT INTO invoices
            (
                sale_id,
                invoice_number,
                retailer_id,
                product_id,
                quantity,
                unit_price,
                total_amount,
                invoice_date,
                email_status,
                created_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sale_id,
                invoice_number,
                actual_retailer_id,
                int(product_id),
                quantity,
                unit_price,
                total_amount,
                invoice_date,
                "Not Sent",
                now
            )
        )

        conn.commit()

        return cursor.lastrowid

    finally:
        conn.close()


def get_invoices(retailer_id=None):
    conn = get_connection()

    try:
        query = """
            SELECT
                i.*,
                p.name AS product_name,
                p.sku AS sku,
                r.name AS retailer_name,
                r.username AS retailer_username,
                r.email AS email
            FROM invoices i
            LEFT JOIN products p
                ON i.product_id = p.id
            LEFT JOIN retailers r
                ON i.retailer_id = r.id
        """

        params = []

        if retailer_id is not None:
            actual_retailer_id = resolve_retailer_id(
                retailer_id
            )

            query += """
                WHERE i.retailer_id = ?
            """

            params.append(
                actual_retailer_id
            )

        query += """
            ORDER BY i.id DESC
        """

        rows = conn.execute(
            query,
            params
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def update_invoice_email_status(
    invoice_number,
    status
):
    conn = get_connection()

    try:
        conn.execute(
            """
            UPDATE invoices
            SET email_status = ?
            WHERE invoice_number = ?
            """,
            (
                status,
                invoice_number
            )
        )

        conn.commit()

        return True

    finally:
        conn.close()


def get_pending_payments():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT
                pay.*,
                r.name AS retailer_name,
                r.username AS retailer_username,
                r.email AS retailer_email
            FROM payments pay
            LEFT JOIN retailers r
                ON pay.retailer_id = r.id
            WHERE LOWER(
                COALESCE(
                    pay.status,
                    'Pending'
                )
            ) != 'paid'
            ORDER BY pay.id DESC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def get_all_payments():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT
                pay.*,
                r.name AS retailer_name,
                r.username AS retailer_username,
                r.email AS retailer_email
            FROM payments pay
            LEFT JOIN retailers r
                ON pay.retailer_id = r.id
            ORDER BY pay.id DESC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def update_payment(
    payment_id,
    status
):
    conn = get_connection()

    try:
        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        payment = conn.execute(
            """
            SELECT invoice_number
            FROM payments
            WHERE id = ?
            LIMIT 1
            """,
            (int(payment_id),)
        ).fetchone()

        conn.execute(
            """
            UPDATE payments
            SET status = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                now,
                int(payment_id)
            )
        )

        if payment:
            conn.execute(
                """
                UPDATE sales
                SET payment_status = ?
                WHERE invoice_number = ?
                """,
                (
                    status,
                    payment["invoice_number"]
                )
            )

        conn.commit()

        return True

    finally:
        conn.close()


def create_payment(
    retailer_id,
    amount,
    invoice_number,
    status="Pending"
):
    conn = get_connection()

    try:
        actual_retailer_id = resolve_retailer_id(
            retailer_id
        )

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        cursor = conn.execute(
            """
            INSERT INTO payments
            (
                retailer_id,
                amount,
                invoice_number,
                status,
                created_at,
                updated_at
            )
            VALUES (?,?,?,?,?,?)
            """,
            (
                actual_retailer_id,
                float(amount or 0),
                invoice_number,
                status,
                now,
                now
            )
        )

        conn.commit()

        return cursor.lastrowid

    finally:
        conn.close()


def get_low_stock_products():
    conn = get_connection()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM products
            WHERE quantity <= reorder_level
            ORDER BY quantity ASC
            """
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    finally:
        conn.close()


def get_weekly_sales():
    conn = get_connection()

    try:
        start_date = (
            datetime.now()
            - timedelta(days=6)
        ).strftime(
            "%Y-%m-%d 00:00:00"
        )

        rows = conn.execute(
            """
            SELECT
                DATE(sale_date) AS sale_day,
                COALESCE(
                    SUM(
                        CASE
                            WHEN total_amount IS NOT NULL
                            THEN total_amount
                            ELSE total
                        END
                    ),
                    0
                ) AS total_sales,
                COALESCE(
                    SUM(quantity),
                    0
                ) AS total_quantity
            FROM sales
            WHERE sale_date >= ?
            GROUP BY DATE(sale_date)
            ORDER BY DATE(sale_date)
            """,
            (start_date,)
        ).fetchall()

        return [
            {
                "date": row["sale_day"],
                "total_sales": float(
                    row["total_sales"] or 0
                ),
                "total_quantity": int(
                    row["total_quantity"] or 0
                )
            }
            for row in rows
        ]

    finally:
        conn.close()


def _foreign_key_reference(conn, table_name, column_name):
    references = {
        ("sales", "retailer_id"): ("retailers", "id"),
        ("invoices", "retailer_id"): ("retailers", "id"),
        ("payments", "retailer_id"): ("retailers", "id"),
    }
    return references.get((table_name, column_name), (None, None))


def _resolve_checkout_retailer(conn, supplied_id):
    supplied_id = int(supplied_id or 0)
    user_id = None
    retailer_id = None

    row = conn.execute(
        "SELECT id, user_id FROM retailers WHERE id = ? LIMIT 1",
        (supplied_id,)
    ).fetchone()
    if row:
        retailer_id = int(row["id"])
        user_id = int(row["user_id"]) if row["user_id"] else None
    else:
        row = conn.execute(
            "SELECT id, user_id FROM retailers WHERE user_id = ? LIMIT 1",
            (supplied_id,)
        ).fetchone()
        if row:
            retailer_id = int(row["id"])
            user_id = int(row["user_id"]) if row["user_id"] else supplied_id

    if retailer_id is None:
        user = conn.execute(
            "SELECT id, username, name, email, phone FROM users WHERE id = ? AND role = 'retailer' LIMIT 1",
            (supplied_id,)
        ).fetchone()
        if user:
            user_id = int(user["id"])
            conn.execute(
                """
                INSERT INTO retailers
                (user_id, name, username, email, phone, created_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    user["id"], user["name"], user["username"],
                    user["email"] or "", user["phone"] or "",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
            )
            retailer_id = conn.execute(
                "SELECT id FROM retailers WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,)
            ).fetchone()[0]

    if retailer_id is None:
        raise Exception("Retailer account is not linked correctly. Please log out and log in again.")

    return retailer_id, user_id


def _value_for_fk(conn, table_name, column_name, retailer_id, user_id):
    ref_table, ref_column = _foreign_key_reference(conn, table_name, column_name)
    if not ref_table:
        return retailer_id

    if ref_table == "retailers":
        row = conn.execute(
            f"SELECT {ref_column} FROM retailers WHERE id = ? LIMIT 1",
            (retailer_id,)
        ).fetchone()
        if row:
            return row[ref_column]

    if ref_table == "users":
        row = conn.execute(
            f"SELECT {ref_column} FROM users WHERE id = ? LIMIT 1",
            (user_id,)
        ).fetchone() if user_id else None
        if row:
            return row[ref_column]

    return retailer_id


def checkout_cart(retailer_id, cart_items):
    if not cart_items:
        raise Exception("Cart is empty.")

    conn = get_connection()

    try:
        actual_retailer_id, user_id = _resolve_checkout_retailer(conn, retailer_id)

        normalized_items = []
        total_order_amount = 0.0

        for item in cart_items:
            product_id = int(item["product_id"])
            quantity = int(item["quantity"])

            if quantity <= 0:
                raise Exception("Invalid product quantity.")

            product = conn.execute(
                "SELECT * FROM products WHERE id = ? LIMIT 1",
                (product_id,)
            ).fetchone()

            if not product:
                raise Exception(f"Product {product_id} not found.")

            available = int(product["quantity"] or 0)
            if quantity > available:
                raise Exception(
                    f"Insufficient stock for {product['name']}. Available: {available}"
                )

            unit_price = float(product["price"] or 0)
            line_total = quantity * unit_price
            total_order_amount += line_total

            normalized_items.append({
                "product_id": product_id,
                "product_name": product["name"],
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total
            })

        invoice_number = "INV-" + datetime.now().strftime("%Y%m%d%H%M%S%f")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sale_ids = []

        sales_columns = {
            row["name"]
            for row in conn.execute(
                """
                SELECT COLUMN_NAME AS name
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'sales'
                """,
                (MYSQL_DATABASE,)
            ).fetchall()
        }
        invoice_columns = {
            row["name"]
            for row in conn.execute(
                """
                SELECT COLUMN_NAME AS name
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'invoices'
                """,
                (MYSQL_DATABASE,)
            ).fetchall()
        }
        payment_columns = {
            row["name"]
            for row in conn.execute(
                """
                SELECT COLUMN_NAME AS name
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ? AND TABLE_NAME = 'payments'
                """,
                (MYSQL_DATABASE,)
            ).fetchall()
        }

        sales_retailer = _value_for_fk(conn, "sales", "retailer_id", actual_retailer_id, user_id)
        invoice_retailer = _value_for_fk(conn, "invoices", "retailer_id", actual_retailer_id, user_id)
        payment_retailer = _value_for_fk(conn, "payments", "retailer_id", actual_retailer_id, user_id)

        for item in normalized_items:
            sale_data = {
                "product_id": item["product_id"],
                "retailer_id": sales_retailer,
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
                "total_amount": item["line_total"],
                "total": item["line_total"],
                "invoice_number": invoice_number,
                "sale_date": now,
                "created_at": now,
                "payment_status": "Pending"
            }
            sale_data = {k: v for k, v in sale_data.items() if k in sales_columns}

            keys = ",".join(sale_data.keys())
            placeholders = ",".join("?" for _ in sale_data)
            sale_cursor = conn.execute(
                f"INSERT INTO sales ({keys}) VALUES ({placeholders})",
                list(sale_data.values())
            )
            sale_id = sale_cursor.lastrowid
            sale_ids.append(sale_id)

            conn.execute(
                "UPDATE products SET quantity = quantity - ?, updated_at = ? WHERE id = ?",
                (item["quantity"], now, item["product_id"])
            )

            invoice_data = {
                "sale_id": sale_id,
                "invoice_number": invoice_number,
                "retailer_id": invoice_retailer,
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
                "total_amount": item["line_total"],
                "total": item["line_total"],
                "invoice_date": now,
                "email_status": "Not Sent",
                "created_at": now
            }
            invoice_data = {k: v for k, v in invoice_data.items() if k in invoice_columns}
            keys = ",".join(invoice_data.keys())
            placeholders = ",".join("?" for _ in invoice_data)
            conn.execute(
                f"INSERT INTO invoices ({keys}) VALUES ({placeholders})",
                list(invoice_data.values())
            )

        if not sale_ids:
            raise Exception("No sale was created.")

        payment_data = {
            "sale_id": sale_ids[0],
            "retailer_id": payment_retailer,
            "amount": total_order_amount,
            "total": total_order_amount,
            "invoice_number": invoice_number,
            "status": "Pending",
            "payment_status": "Pending",
            "created_at": now,
            "updated_at": now
        }
        payment_data = {k: v for k, v in payment_data.items() if k in payment_columns}

        keys = ",".join(payment_data.keys())
        placeholders = ",".join("?" for _ in payment_data)
        conn.execute(
            f"INSERT INTO payments ({keys}) VALUES ({placeholders})",
            list(payment_data.values())
        )

        conn.commit()

        return {
            "invoice_number": invoice_number,
            "total_amount": total_order_amount,
            "total": total_order_amount,
            "items": normalized_items,
            "sale_ids": sale_ids,
            "payment_status": "Pending"
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    return initialize_database()
