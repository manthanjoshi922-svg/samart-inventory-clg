import os
import sys
import shutil
import json
import sqlite3
from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices
from PySide6.QtWidgets import *

import database
from barcode_qr import generate_barcode, generate_payment_qr

BASE = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE, "product_images")
INV = os.path.join(BASE, "generated_invoices")
IMAGE_MAP = os.path.join(BASE, "product_images.json")

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(INV, exist_ok=True)


def conn():
    return database.get_connection()


def cols(table):
    c = conn()
    result = [x["name"] for x in c.execute(f"PRAGMA table_info({table})")]
    c.close()
    return result


def val(row, *names, d=""):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return d


def num(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def integer(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def money(value):
    return f"₹{num(value):,.2f}"


def allrows(table):
    c = conn()
    order = "id DESC" if "id" in cols(table) else "rowid DESC"
    rows = [dict(x) for x in c.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()]
    c.close()
    return rows


def insert(table, data):
    available = cols(table)
    data = {k: v for k, v in data.items() if k in available}
    if not data:
        raise ValueError(f"No compatible fields found for {table}.")
    c = conn()
    try:
        keys = ",".join(data)
        marks = ",".join("?" for _ in data)
        cursor = c.execute(f"INSERT INTO {table} ({keys}) VALUES ({marks})", list(data.values()))
        row_id = getattr(cursor, "lastrowid", None)
        if row_id is None:
            row = c.execute("SELECT LAST_INSERT_ID() AS id").fetchone()
            row_id = row["id"] if isinstance(row, dict) else row[0]
        c.commit()
        return row_id
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def update(table, row_id, data):
    available = cols(table)
    data = {k: v for k, v in data.items() if k in available}
    if not data:
        return
    c = conn()
    try:
        assignments = ",".join(f"{k}=?" for k in data)
        c.execute(f"UPDATE {table} SET {assignments} WHERE id=?", list(data.values()) + [row_id])
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def delete_row(table, row_id):
    c = conn()
    try:
        c.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def load_image_map():
    if not os.path.exists(IMAGE_MAP):
        return {}
    try:
        with open(IMAGE_MAP, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_image_map(data):
    with open(IMAGE_MAP, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def product_image(product_id):
    data = load_image_map()
    path = data.get(str(product_id), "")
    if path and os.path.exists(path):
        return path
    return ""


def set_product_image(product_id, source):
    extension = os.path.splitext(source)[1].lower() or ".png"
    destination = os.path.join(IMAGE_DIR, f"product_{product_id}{extension}")
    shutil.copy2(source, destination)
    data = load_image_map()
    old = data.get(str(product_id), "")
    if old and os.path.abspath(old) != os.path.abspath(destination) and os.path.exists(old):
        try:
            os.remove(old)
        except Exception:
            pass
    data[str(product_id)] = destination
    save_image_map(data)
    return destination


def remove_product_image(product_id):
    data = load_image_map()
    old = data.pop(str(product_id), "")
    if old and os.path.exists(old):
        try:
            os.remove(old)
        except Exception:
            pass
    save_image_map(data)


def products(search=""):
    try:
        fn = getattr(database, "get_products", None)
        result = [dict(x) for x in fn()] if fn else allrows("products")
    except Exception:
        result = allrows("products")
    if search:
        search = search.lower().strip()
        result = [
            x for x in result
            if search in str(val(x, "name", "product_name")).lower()
            or search in str(val(x, "sku", "code", "barcode")).lower()
        ]
    return result


def auth(username, password):
    username = str(username or "").strip()
    password = str(password or "")
    if not username or not password:
        return None
    try:
        result = database.authenticate(username, password)
        if result:
            return dict(result)
    except Exception:
        pass
    try:
        import hashlib
        c = conn()
        row = c.execute("SELECT * FROM users WHERE username=? LIMIT 1", (username,)).fetchone()
        if not row:
            c.close()
            return None
        user = dict(row)
        stored = str(user.get("password") or "")
        hashed = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if stored == password or stored == hashed:
            if stored == password:
                c.execute("UPDATE users SET password=? WHERE id=?", (hashed, user["id"]))
                c.commit()
                user["password"] = hashed
            c.close()
            return user
        c.close()
    except Exception:
        pass
    return None


def retailer_id(user):
    result = integer(val(user, "retailer_id"))
    if result:
        return result
    user_id = integer(val(user, "id", "user_id"))
    if not user_id:
        return 0
    c = conn()
    try:
        row = c.execute(
            "SELECT id FROM retailers WHERE user_id=? LIMIT 1",
            (user_id,)
        ).fetchone()
        if row:
            return integer(row.get("id") if isinstance(row, dict) else row[0])
        username = str(val(user, "username", d=""))
        if username:
            row = c.execute(
                "SELECT id FROM retailers WHERE username=? LIMIT 1",
                (username,)
            ).fetchone()
            if row:
                return integer(row.get("id") if isinstance(row, dict) else row[0])
        return 0
    finally:
        c.close()


def checkout(retailer, cart):
    fn = getattr(database, "checkout_cart", None)
    if fn:
        attempts = [
            lambda: fn(retailer, cart),
            lambda: fn(retailer_id=retailer, cart=cart),
        ]
        for attempt in attempts:
            try:
                return attempt()
            except TypeError:
                pass

    c = conn()
    sales_columns = cols("sales")
    invoice_columns = cols("invoices")
    payment_columns = cols("payments")
    total = 0
    items = []

    for item in cart:
        row = c.execute("SELECT * FROM products WHERE id=?", (integer(item["product_id"]),)).fetchone()
        product = dict(row) if row else None
        if not product:
            raise ValueError("Product not found.")
        quantity = integer(item["quantity"])
        stock = integer(val(product, "stock", "quantity", "stock_quantity"))
        price = num(val(product, "price", "unit_price"))
        if quantity < 1 or quantity > stock:
            raise ValueError(f"Not enough stock for {val(product, 'name', 'product_name')}.")
        total += quantity * price
        items.append((product, quantity, price))

    invoice = "INV-" + datetime.now().strftime("%Y%m%d%H%M%S")
    sale_ids = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for product, quantity, price in items:
        sale_data = {
            "product_id": integer(product["id"]),
            "retailer_id": retailer,
            "quantity": quantity,
            "unit_price": price,
            "total": quantity * price,
            "total_amount": quantity * price,
            "invoice_number": invoice,
            "payment_status": "Pending",
            "status": "Pending",
            "created_at": now,
        }
        sale_data = {k: v for k, v in sale_data.items() if k in sales_columns}
        keys = ",".join(sale_data)
        marks = ",".join("?" for _ in sale_data)
        c.execute(f"INSERT INTO sales ({keys}) VALUES ({marks})", list(sale_data.values()))
        cursor = c.execute("SELECT LAST_INSERT_ID() AS id")
        row = cursor.fetchone()
        sale_id = row["id"] if isinstance(row, dict) else row[0]
        sale_ids.append(sale_id)

        stock_field = "stock" if "stock" in cols("products") else "quantity"
        c.execute(f"UPDATE products SET {stock_field}={stock_field}-? WHERE id=?", (quantity, product["id"]))

        invoice_data = {
            "sale_id": sale_id,
            "retailer_id": retailer,
            "product_id": product["id"],
            "invoice_number": invoice,
            "product_name": val(product, "name", "product_name"),
            "quantity": quantity,
            "unit_price": price,
            "total": quantity * price,
            "total_amount": quantity * price,
            "created_at": now,
        }
        invoice_data = {k: v for k, v in invoice_data.items() if k in invoice_columns}
        keys = ",".join(invoice_data)
        marks = ",".join("?" for _ in invoice_data)
        c.execute(f"INSERT INTO invoices ({keys}) VALUES ({marks})", list(invoice_data.values()))

    payment_data = {
        "sale_id": sale_ids[0],
        "retailer_id": retailer,
        "amount": total,
        "total": total,
        "invoice_number": invoice,
        "status": "Pending",
        "payment_status": "Pending",
        "created_at": now,
    }
    payment_data = {k: v for k, v in payment_data.items() if k in payment_columns}
    keys = ",".join(payment_data)
    marks = ",".join("?" for _ in payment_data)
    c.execute(f"INSERT INTO payments ({keys}) VALUES ({marks})", list(payment_data.values()))
    c.commit()
    c.close()
    return {"invoice_number": invoice, "total": total}


class Login(QDialog):
    def __init__(self):
        super().__init__()
        self.user = None
        self.setWindowTitle("Smart Inventory Management")
        self.resize(450, 420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(45, 35, 45, 35)
        layout.setSpacing(14)

        title = QLabel("SMART INVENTORY")
        title.setObjectName("loginTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Management & Retailer Portal")
        subtitle.setObjectName("loginSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)

        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)

        button = QPushButton("LOGIN")
        button.setObjectName("loginButton")
        button.clicked.connect(self.login)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(20)
        layout.addWidget(self.username)
        layout.addWidget(self.password)
        layout.addWidget(button)
        layout.addSpacing(10)
        demo = QLabel("Management: admin / admin123\nRetailer: retailer1 / retail123")
        demo.setObjectName("demo")
        demo.setAlignment(Qt.AlignCenter)
        layout.addWidget(demo)
        layout.addStretch()

    def login(self):
        self.user = auth(self.username.text().strip(), self.password.text())
        if self.user:
            self.accept()
        else:
            QMessageBox.warning(self, "Login Failed", "Invalid username or password.")


class Main(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.role = str(val(user, "role")).lower()
        self.cart = []
        self.current = "Dashboard"
        self.setWindowTitle("Smart Inventory Management")
        self.resize(1450, 900)
        self.build()
        self.page("Dashboard")

    def build(self):
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(245)
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(18, 24, 18, 18)
        side_layout.setSpacing(7)

        logo = QLabel("SMART\nINVENTORY")
        logo.setObjectName("logo")
        side_layout.addWidget(logo)

        user_name = QLabel(str(val(self.user, "name", "username", d="User")))
        user_name.setObjectName("sideUser")
        side_layout.addWidget(user_name)

        role_label = QLabel("MANAGEMENT" if self.role == "management" else "RETAILER")
        role_label.setObjectName("sideRole")
        side_layout.addWidget(role_label)
        side_layout.addSpacing(20)

        if self.role == "management":
            names = ["Dashboard", "Inventory", "Retailers", "Sales", "Payments", "Invoices", "Analytics", "Settings"]
        else:
            names = ["Dashboard", "Shop", "My Cart", "My Orders", "My Payments", "My Invoices"]

        for name in names:
            button = QPushButton(name)
            button.setObjectName("navButton")
            button.clicked.connect(lambda _, x=name: self.page(x))
            side_layout.addWidget(button)

        side_layout.addStretch()
        refresh = QPushButton("↻  Refresh")
        refresh.setObjectName("bottomButton")
        refresh.clicked.connect(lambda: self.page(self.current))
        side_layout.addWidget(refresh)

        logout = QPushButton("⇦  Logout")
        logout.setObjectName("logoutButton")
        logout.clicked.connect(self.close)
        side_layout.addWidget(logout)

        self.stack = QStackedWidget()
        self.stack.setObjectName("workspace")

        outer.addWidget(sidebar)
        outer.addWidget(self.stack)
        self.setCentralWidget(root)

    def page(self, name):
        self.current = name
        creator = getattr(self, "p_" + name.replace(" ", "_").lower())
        widget = creator()
        while self.stack.count():
            old = self.stack.widget(0)
            self.stack.removeWidget(old)
            old.deleteLater()
        self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)

    def header(self, title, subtitle=""):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 12)
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        layout.addWidget(title_label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("pageSubtitle")
            layout.addWidget(sub)
        return widget

    def card(self, title, value, note=""):
        frame = QFrame()
        frame.setObjectName("statCard")
        layout = QVBoxLayout(frame)
        label = QLabel(title.upper())
        label.setObjectName("cardLabel")
        number = QLabel(str(value))
        number.setObjectName("cardValue")
        layout.addWidget(label)
        layout.addWidget(number)
        if note:
            small = QLabel(note)
            small.setObjectName("cardNote")
            layout.addWidget(small)
        return frame

    def table(self, headers, data, formats=None):
        table = QTableWidget(len(data), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        formats = formats or headers
        for row, item in enumerate(data):
            for col, field in enumerate(formats):
                value = field(item) if callable(field) else val(item, field)
                table.setItem(row, col, QTableWidgetItem(str(value)))
        return table

    def p_dashboard(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        name = str(val(self.user, "name", "username", d="User"))
        if self.role == "management":
            layout.addWidget(self.header(f"Welcome back, {name}", "Inventory overview and business activity"))
            product_data = products()
            low = [x for x in product_data if integer(val(x, "stock", "quantity", "stock_quantity")) <= 5]
            inventory_value = sum(
                num(val(x, "price", "unit_price")) * integer(val(x, "stock", "quantity", "stock_quantity"))
                for x in product_data
            )
            grid = QGridLayout()
            grid.addWidget(self.card("Total Products", len(product_data), "Products in inventory"), 0, 0)
            grid.addWidget(self.card("Low Stock", len(low), "Items needing attention"), 0, 1)
            grid.addWidget(self.card("Inventory Value", money(inventory_value), "Current stock value"), 0, 2)
            layout.addLayout(grid)

            section = QLabel("LOW STOCK ALERTS")
            section.setObjectName("sectionTitle")
            layout.addWidget(section)
            if low:
                layout.addWidget(self.table(["Product", "SKU", "Stock"], low, [
                    lambda x: val(x, "name", "product_name"),
                    lambda x: val(x, "sku", "code", "barcode"),
                    lambda x: val(x, "stock", "quantity", "stock_quantity")
                ]))
            else:
                ok = QLabel("✓  All products currently have healthy stock levels.")
                ok.setObjectName("successText")
                layout.addWidget(ok)
        else:
            rid = retailer_id(self.user)
            sales = [x for x in allrows("sales") if integer(val(x, "retailer_id")) == rid]
            payments = [x for x in allrows("payments") if integer(val(x, "retailer_id")) == rid]
            pending = sum(num(val(x, "amount", "total", "total_amount")) for x in payments if str(val(x, "status", "payment_status", d="Pending")).lower() == "pending")
            layout.addWidget(self.header(f"Welcome, {name}", "Your retailer workspace"))
            grid = QGridLayout()
            grid.addWidget(self.card("Browse Products", len(products()), "Available in shop"), 0, 0)
            grid.addWidget(self.card("Cart Items", sum(x["quantity"] for x in self.cart), "Ready for checkout"), 0, 1)
            grid.addWidget(self.card("My Orders", len(sales), "Orders placed"), 0, 2)
            grid.addWidget(self.card("Pending Payment", money(pending), "Awaiting payment"), 0, 3)
            layout.addLayout(grid)
            section = QLabel("RECENT ORDERS")
            section.setObjectName("sectionTitle")
            layout.addWidget(section)
            layout.addWidget(self.table(["ID", "Invoice", "Total", "Status"], sales[:8], [
                "id",
                lambda x: val(x, "invoice_number", "invoice_id", d="—"),
                lambda x: money(val(x, "total", "total_amount")),
                lambda x: val(x, "payment_status", "status", d="Pending")
            ]))
        layout.addStretch()
        return widget

    def p_inventory(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.header("Inventory", "Manage products, photos, stock and barcodes"))
        toolbar = QHBoxLayout()
        search = QLineEdit()
        search.setPlaceholderText("Search product name, SKU or barcode")
        add = QPushButton("+  Add Product")
        toolbar.addWidget(search, 1)
        toolbar.addWidget(add)
        layout.addLayout(toolbar)

        table = QTableWidget()
        table.setColumnCount(8)
        table.setHorizontalHeaderLabels(["Photo", "Product", "SKU", "Price", "Stock", "Barcode", "Edit", "Delete"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        layout.addWidget(table)

        def load():
            data = products(search.text())
            table.setRowCount(len(data))
            for row, product in enumerate(data):
                pid = integer(val(product, "id", "product_id"))
                name = str(val(product, "name", "product_name", d="Product"))
                sku = str(val(product, "sku", "code", "barcode", d=pid))
                price = money(val(product, "price", "unit_price"))
                stock = str(val(product, "stock", "quantity", "stock_quantity", d=0))

                photo = QLabel()
                photo.setAlignment(Qt.AlignCenter)
                path = product_image(pid)
                if path:
                    pixmap = QPixmap(path)
                    photo.setPixmap(pixmap.scaled(70, 55, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    photo.setText("No Photo")
                    photo.setObjectName("noPhoto")
                table.setCellWidget(row, 0, photo)

                for col, value in enumerate([name, sku, price, stock, sku], start=1):
                    table.setItem(row, col, QTableWidgetItem(value))

                barcode_button = QPushButton("View")
                barcode_button.clicked.connect(lambda _, x=product: self.show_barcode(x))
                table.setCellWidget(row, 5, barcode_button)

                edit_button = QPushButton("Edit")
                edit_button.clicked.connect(lambda _, x=product: self.edit_product(x, load))
                table.setCellWidget(row, 6, edit_button)

                delete_button = QPushButton("Delete")
                delete_button.setObjectName("dangerButton")
                delete_button.clicked.connect(lambda _, x=product: self.delete_product(x, load))
                table.setCellWidget(row, 7, delete_button)

        search.textChanged.connect(load)
        add.clicked.connect(lambda: self.add_product(load))
        load()
        return widget

    def product_dialog(self, product=None, refresh=None):
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Product" if product else "Add Product")
        dialog.resize(520, 650)
        layout = QVBoxLayout(dialog)

        form = QFormLayout()
        name = QLineEdit(str(val(product or {}, "name", "product_name")))
        category = QLineEdit(str(val(product or {}, "category", d="General")))
        if not category.text().strip():
            category.setText("General")
        sku = QLineEdit(str(val(product or {}, "sku", "code", "barcode")))
        price = QDoubleSpinBox()
        price.setMaximum(100000000)
        price.setDecimals(2)
        price.setValue(num(val(product or {}, "price", "unit_price")))
        stock = QSpinBox()
        stock.setMaximum(100000000)
        stock.setValue(integer(val(product or {}, "stock", "quantity", "stock_quantity")))
        form.addRow("Product Name", name)
        form.addRow("Category", category)
        form.addRow("SKU", sku)
        form.addRow("Price", price)
        form.addRow("Stock", stock)
        layout.addLayout(form)

        preview = QLabel()
        preview.setFixedSize(220, 170)
        preview.setAlignment(Qt.AlignCenter)
        preview.setObjectName("photoPreview")
        current_image = product_image(integer(val(product or {}, "id", "product_id"))) if product else ""
        selected = {"path": current_image}

        def show_preview(path):
            if path and os.path.exists(path):
                pixmap = QPixmap(path)
                preview.setPixmap(pixmap.scaled(210, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                preview.setText("Product Photo")

        show_preview(current_image)
        layout.addWidget(preview, alignment=Qt.AlignCenter)

        choose = QPushButton("Choose Product Photo")
        choose.clicked.connect(lambda: self.choose_photo(selected, show_preview))
        layout.addWidget(choose)

        remove = QPushButton("Remove Photo")
        remove.setObjectName("secondaryButton")
        remove.clicked.connect(lambda: self.clear_selected_photo(selected, preview))
        layout.addWidget(remove)

        save = QPushButton("Save Product")
        layout.addWidget(save)

        def save_product():
            product_name = name.text().strip()
            product_sku = sku.text().strip() or "SKU-" + datetime.now().strftime("%Y%m%d%H%M%S")
            if not product_name:
                QMessageBox.warning(dialog, "Product", "Product name is required.")
                return
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data = {
                "name": product_name,
                "product_name": product_name,
                "category": category.text().strip() or "General",
                "sku": product_sku,
                "code": product_sku,
                "barcode": product_sku,
                "price": price.value(),
                "unit_price": price.value(),
                "stock": stock.value(),
                "quantity": stock.value(),
                "stock_quantity": stock.value(),
                "created_at": val(product or {}, "created_at", d=now) if product else now,
                "updated_at": now,
            }
            try:
                last_error = None
                for attempt in range(4):
                    try:
                        if product:
                            pid = integer(val(product, "id", "product_id"))
                            update("products", pid, data)
                        else:
                            pid = insert("products", data)
                        last_error = None
                        break
                    except sqlite3.OperationalError as error:
                        last_error = error
                        if "locked" not in str(error).lower() or attempt == 3:
                            raise
                        import time
                        time.sleep(0.75)
                if last_error:
                    raise last_error
                generate_barcode(product_sku)
                if selected["path"]:
                    if selected["path"] != current_image or not os.path.abspath(selected["path"]).startswith(os.path.abspath(IMAGE_DIR)):
                        set_product_image(pid, selected["path"])
                elif product:
                    remove_product_image(pid)
                dialog.accept()
                if refresh:
                    refresh()
            except sqlite3.OperationalError as e:
                QMessageBox.critical(dialog, "Save Failed", "SQLite could not save the product because the database is busy. Please wait a moment and click Save Product again.\n\n" + str(e))
            except Exception as e:
                QMessageBox.critical(dialog, "Save Failed", str(e))

        save.clicked.connect(save_product)
        dialog.exec()

    def choose_photo(self, selected, preview_callback):
        path, _ = QFileDialog.getOpenFileName(self, "Choose Product Photo", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if path:
            selected["path"] = path
            preview_callback(path)

    def clear_selected_photo(self, selected, preview):
        selected["path"] = ""
        preview.clear()
        preview.setText("Product Photo")

    def add_product(self, refresh):
        self.product_dialog(None, refresh)

    def edit_product(self, product, refresh):
        self.product_dialog(product, refresh)

    def delete_product(self, product, refresh):
        pid = integer(val(product, "id", "product_id"))
        name = str(val(product, "name", "product_name", d="this product"))
        answer = QMessageBox.question(self, "Delete Product", f"Delete {name}?", QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            delete_row("products", pid)
            remove_product_image(pid)
            refresh()
        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", str(e))

    def show_barcode(self, product):
        sku = str(val(product, "sku", "code", "barcode", d=val(product, "id")))
        path = generate_barcode(sku)
        dialog = QDialog(self)
        dialog.setWindowTitle("Product Barcode")
        dialog.resize(650, 420)
        layout = QVBoxLayout(dialog)
        title = QLabel(str(val(product, "name", "product_name", d="Product")))
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignCenter)
        image = QLabel()
        image.setAlignment(Qt.AlignCenter)
        image.setPixmap(QPixmap(path).scaled(570, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(title)
        layout.addWidget(QLabel(f"SKU / Barcode: {sku}"), alignment=Qt.AlignCenter)
        layout.addWidget(image)
        save = QPushButton("Download Barcode")
        save.clicked.connect(lambda: self.save_file(path, "PNG (*.png)"))
        layout.addWidget(save)
        dialog.exec()

    def save_file(self, path, file_filter):
        destination, _ = QFileDialog.getSaveFileName(self, "Save File", os.path.basename(path), file_filter)
        if destination:
            shutil.copy2(path, destination)
            QMessageBox.information(self, "Saved", "File saved successfully.")

    def delete_retailer(self, retailer):
        rid = integer(val(retailer, "id", "retailer_id"))
        name = str(val(retailer, "name", d="this retailer"))
        username = str(val(retailer, "username", d=""))
        if not rid:
            QMessageBox.warning(self, "Delete Retailer", "Retailer ID was not found.")
            return
        answer = QMessageBox.question(
            self,
            "Delete Retailer",
            f"Delete retailer '{name}'?\n\nThis will also remove this retailer's sales, payments and invoices.",
            QMessageBox.Yes | QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        c = conn()
        try:
            user_id = None
            if "user_id" in cols("retailers"):
                row = c.execute("SELECT user_id FROM retailers WHERE id=?", (rid,)).fetchone()
                user_id = integer(row[0]) if row and row[0] is not None else 0

            if "payments" in ["payments"] and "retailer_id" in cols("payments"):
                c.execute("DELETE FROM payments WHERE retailer_id=?", (rid,))
            if "invoices" in ["invoices"] and "retailer_id" in cols("invoices"):
                c.execute("DELETE FROM invoices WHERE retailer_id=?", (rid,))
            if "sales" in ["sales"] and "retailer_id" in cols("sales"):
                c.execute("DELETE FROM sales WHERE retailer_id=?", (rid,))
            c.execute("DELETE FROM retailers WHERE id=?", (rid,))
            if user_id and "id" in cols("users"):
                c.execute("DELETE FROM users WHERE id=?", (user_id,))
            elif username and "username" in cols("users"):
                c.execute("DELETE FROM users WHERE username=? AND role='retailer'", (username,))
            c.commit()
            QMessageBox.information(self, "Retailer Deleted", f"Retailer '{name}' has been deleted.")
            self.page("Retailers")
        except Exception as e:
            c.rollback()
            QMessageBox.critical(self, "Delete Failed", str(e))
        finally:
            c.close()

    def clear_all_orders(self):
        answer = QMessageBox.question(
            self,
            "Clear All Orders",
            "Delete ALL sales, payments and invoices?\n\nThis action cannot be undone. Products will NOT be deleted.",
            QMessageBox.Yes | QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            return
        c = conn()
        try:
            if "payments" in ["payments"]:
                c.execute("DELETE FROM payments")
            if "invoices" in ["invoices"]:
                c.execute("DELETE FROM invoices")
            if "sales" in ["sales"]:
                c.execute("DELETE FROM sales")
            c.commit()
            for filename in os.listdir(INV):
                path = os.path.join(INV, filename)
                if os.path.isfile(path) and filename.lower().endswith(".pdf"):
                    try:
                        os.remove(path)
                    except Exception:
                        pass
            QMessageBox.information(self, "Orders Cleared", "All sales, payments and invoices have been removed.")
            self.page("Sales")
        except Exception as e:
            c.rollback()
            QMessageBox.critical(self, "Clear Failed", str(e))
        finally:
            c.close()

    def add_retailer(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Retailer")
        dialog.resize(520, 520)
        layout = QVBoxLayout(dialog)

        title = QLabel("Create Retailer Account")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        name = QLineEdit()
        name.setPlaceholderText("Retailer / Business Name")
        username = QLineEdit()
        username.setPlaceholderText("Login username")
        password = QLineEdit()
        password.setPlaceholderText("Login password")
        password.setEchoMode(QLineEdit.Password)
        email = QLineEdit()
        email.setPlaceholderText("Email address")
        phone = QLineEdit()
        phone.setPlaceholderText("Phone number")
        address = QLineEdit()
        address.setPlaceholderText("Address")

        form.addRow("Name", name)
        form.addRow("Username", username)
        form.addRow("Password", password)
        form.addRow("Email", email)
        form.addRow("Phone", phone)
        form.addRow("Address", address)
        layout.addLayout(form)

        save_button = QPushButton("Create Retailer")
        layout.addWidget(save_button)

        def save():
            retailer_name = name.text().strip()
            login_name = username.text().strip()
            login_password = password.text()
            email_value = email.text().strip()
            phone_value = phone.text().strip()
            address_value = address.text().strip()

            if not retailer_name or not login_name or not login_password:
                QMessageBox.warning(dialog, "Missing Details", "Name, username and password are required.")
                return

            c = conn()
            try:
                existing = c.execute("SELECT id FROM users WHERE username=? LIMIT 1", (login_name,)).fetchone()
                if existing:
                    QMessageBox.warning(dialog, "Username Exists", "This username is already in use. Please choose another username.")
                    return

                user_columns = cols("users")
                user_data = {
                    "username": login_name,
                    "password": login_password,
                    "name": retailer_name,
                    "role": "retailer",
                    "email": email_value,
                    "phone": phone_value,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                user_data = {k: v for k, v in user_data.items() if k in user_columns}
                keys = ",".join(user_data)
                marks = ",".join("?" for _ in user_data)
                cursor = c.execute(f"INSERT INTO users ({keys}) VALUES ({marks})", list(user_data.values()))
                user_id = cursor.lastrowid

                retailer_columns = cols("retailers")
                retailer_data = {
                    "user_id": user_id,
                    "name": retailer_name,
                    "username": login_name,
                    "email": email_value,
                    "phone": phone_value,
                    "address": address_value,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                retailer_data = {k: v for k, v in retailer_data.items() if k in retailer_columns}
                keys = ",".join(retailer_data)
                marks = ",".join("?" for _ in retailer_data)
                c.execute(f"INSERT INTO retailers ({keys}) VALUES ({marks})", list(retailer_data.values()))
                c.commit()

                QMessageBox.information(
                    dialog,
                    "Retailer Created",
                    f"Retailer created successfully.\n\nUsername: {login_name}\nPassword: {login_password}"
                )
                dialog.accept()
                self.page("Retailers")
            except Exception as e:
                c.rollback()
                QMessageBox.critical(dialog, "Creation Failed", str(e))
            finally:
                c.close()

        save_button.clicked.connect(save)
        dialog.exec()

    def p_retailers(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        top = QHBoxLayout()
        top.addWidget(self.header("Retailers", "Create and manage retailer accounts"), 1)
        add_button = QPushButton("+ Add Retailer")
        add_button.clicked.connect(self.add_retailer)
        top.addWidget(add_button)
        layout.addLayout(top)
        data = allrows("retailers")
        table = QTableWidget(len(data), 6)
        table.setHorizontalHeaderLabels(["ID", "Name", "Email", "Phone", "Username", "Action"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        for row, item in enumerate(data):
            values = [
                val(item, "id"),
                val(item, "name"),
                val(item, "email"),
                val(item, "phone"),
                val(item, "username")
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value)))
            button = QPushButton("Delete")
            button.setObjectName("dangerButton")
            button.clicked.connect(lambda _, x=item: self.delete_retailer(x))
            table.setCellWidget(row, 5, button)
        layout.addWidget(table)
        return widget

    def p_sales(self):
        data = allrows("sales")
        widget = QWidget()
        layout = QVBoxLayout(widget)
        top = QHBoxLayout()
        top.addWidget(self.header("Sales", "Orders and sales history"), 1)
        clear = QPushButton("Clear All Orders")
        clear.setObjectName("dangerButton")
        clear.clicked.connect(self.clear_all_orders)
        top.addWidget(clear)
        layout.addLayout(top)
        layout.addWidget(self.table(["ID", "Product", "Retailer", "Quantity", "Unit Price", "Total", "Status"], data, [
            "id", "product_id", "retailer_id", "quantity",
            lambda x: money(val(x, "unit_price")),
            lambda x: money(val(x, "total", "total_amount")),
            lambda x: val(x, "payment_status", "status", d="Pending")
        ]))
        return widget

    def p_payments(self):
        data = allrows("payments")
        if self.role == "retailer":
            data = [x for x in data if integer(val(x, "retailer_id")) == retailer_id(self.user)]
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.header("My Payments" if self.role == "retailer" else "Payment Verification", "Review payment status and verify payments received"))
        table = QTableWidget(len(data), 6)
        table.setHorizontalHeaderLabels(["ID", "Invoice", "Retailer", "Amount", "Status", "Action"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        for row, item in enumerate(data):
            status = str(val(item, "status", "payment_status", d="Pending"))
            values = [
                val(item, "id", "payment_id"),
                val(item, "invoice_number", "invoice_id", d="—"),
                val(item, "retailer_id", d="—"),
                money(val(item, "amount", "total", "total_amount")),
                status
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                if col == 4:
                    cell.setTextAlignment(Qt.AlignCenter)
                table.setItem(row, col, cell)
            if self.role == "retailer":
                button = QPushButton("Show QR" if status.lower() == "pending" else "View QR")
                button.setEnabled(status.lower() == "pending")
                button.clicked.connect(lambda _, x=item: self.show_payment_qr(x))
                table.setCellWidget(row, 5, button)
            else:
                actions = QWidget()
                action_layout = QHBoxLayout(actions)
                action_layout.setContentsMargins(2, 2, 2, 2)
                verify = QPushButton("Verify Paid")
                reject = QPushButton("Reject")
                verify.setEnabled(status.lower() == "pending")
                reject.setEnabled(status.lower() == "pending")
                verify.clicked.connect(lambda _, x=item: self.set_payment_status(x, "Paid"))
                reject.clicked.connect(lambda _, x=item: self.set_payment_status(x, "Rejected"))
                action_layout.addWidget(verify)
                action_layout.addWidget(reject)
                table.setCellWidget(row, 5, actions)
        layout.addWidget(table)
        return widget

    def set_payment_status(self, payment, status):
        pid = integer(val(payment, "id", "payment_id"))
        invoice = str(val(payment, "invoice_number", "invoice_id", d=""))
        if not pid:
            QMessageBox.warning(self, "Payment", "Could not identify this payment record.")
            return
        if status == "Paid":
            answer = QMessageBox.question(
                self,
                "Confirm Payment",
                "Have you confirmed that the payment was actually received for this invoice?\n\nOnly verify it after checking your payment account.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return
        else:
            answer = QMessageBox.question(
                self,
                "Reject Payment",
                "Mark this payment as Rejected? The retailer will see the updated status.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                return
        data = {}
        payment_columns = cols("payments")
        if "status" in payment_columns:
            data["status"] = status
        if "payment_status" in payment_columns:
            data["payment_status"] = status
        if "updated_at" in payment_columns:
            data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update("payments", pid, data)
        for table_name in ("sales", "invoices"):
            try:
                table_columns = cols(table_name)
                if "invoice_number" not in table_columns:
                    continue
                fields = {}
                if table_name == "sales":
                    if "payment_status" in table_columns:
                        fields["payment_status"] = status
                    if "status" in table_columns:
                        fields["status"] = status
                else:
                    if "payment_status" in table_columns:
                        fields["payment_status"] = status
                    if "status" in table_columns:
                        fields["status"] = status
                if fields and invoice:
                    c = conn()
                    assignments = ",".join(f"{key}=?" for key in fields)
                    c.execute(f"UPDATE {table_name} SET {assignments} WHERE invoice_number=?", list(fields.values()) + [invoice])
                    c.commit()
                    c.close()
            except Exception:
                pass
        QMessageBox.information(self, "Payment Status Updated", f"Invoice {invoice or '—'} is now marked {status}.")
        self.page("Payments")

    def mark_paid(self, payment):
        self.set_payment_status(payment, "Paid")

    def p_settings(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(30, 25, 30, 30)
        layout.setSpacing(14)
        layout.addWidget(self.header("Payment Settings", "Set the UPI ID used to create retailer payment QR codes."))

        form = QFrame()
        form.setObjectName("statCard")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(22, 22, 22, 22)
        label = QLabel("Your UPI ID")
        label.setObjectName("sectionTitle")
        upi_input = QLineEdit()
        upi_input.setPlaceholderText("example@oksbi")
        upi_input.setText(database.get_upi_id() if hasattr(database, "get_upi_id") else "")
        help_text = QLabel("Example: name@oksbi, mobile@upi, or name@okaxis. Enter the UPI ID that belongs to you.")
        help_text.setWordWrap(True)
        help_text.setObjectName("pageSubtitle")
        save_button = QPushButton("Save UPI ID")

        def save_upi():
            upi = upi_input.text().strip()
            if not upi or "@" not in upi or " " in upi:
                QMessageBox.warning(self, "Invalid UPI ID", "Enter a valid UPI ID, for example name@oksbi.")
                return
            try:
                if not hasattr(database, "set_upi_id"):
                    raise RuntimeError("Your database.py does not include set_upi_id(). Update database.py first.")
                database.set_upi_id(upi)
                QMessageBox.information(self, "Saved", "Your UPI ID has been saved. New payment QR codes will use this ID.")
            except Exception as exc:
                QMessageBox.critical(self, "Could Not Save UPI ID", str(exc))

        save_button.clicked.connect(save_upi)
        form_layout.addWidget(label)
        form_layout.addWidget(upi_input)
        form_layout.addWidget(help_text)
        form_layout.addWidget(save_button)
        layout.addWidget(form)
        layout.addStretch()
        return widget

    def show_payment_qr(self, payment):
        amount = num(val(payment, "amount", "total", "total_amount"))
        invoice = str(val(payment, "invoice_number", "invoice_id", d="INVOICE"))
        try:
            upi_id = database.get_upi_id() if hasattr(database, "get_upi_id") else ""
        except Exception as exc:
            QMessageBox.critical(self, "UPI Settings Error", f"Could not read the saved UPI ID.\n{exc}")
            return
        if not upi_id:
            QMessageBox.warning(self, "UPI ID Not Set", "Ask Management to open Settings and save your UPI ID before generating a payment QR.")
            return
        if amount <= 0:
            QMessageBox.warning(self, "Invalid Amount", "This payment does not have a valid amount, so a QR code cannot be generated.")
            return
        try:
            path = generate_payment_qr(upi_id, amount, invoice)
        except Exception as exc:
            QMessageBox.critical(self, "QR Generation Failed", f"Could not generate the payment QR code.\n{exc}")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Payment QR")
        dialog.resize(460, 620)
        layout = QVBoxLayout(dialog)
        title = QLabel("PAYMENT PENDING")
        title.setObjectName("pendingTitle")
        title.setAlignment(Qt.AlignCenter)
        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.critical(self, "QR Generation Failed", "The QR image file could not be opened.")
            return
        qr.setPixmap(pixmap.scaled(330, 330, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(title)
        layout.addWidget(QLabel(f"Invoice: {invoice}"), alignment=Qt.AlignCenter)
        layout.addWidget(QLabel(f"Amount: {money(amount)}"), alignment=Qt.AlignCenter)
        layout.addWidget(QLabel(f"UPI ID: {upi_id}"), alignment=Qt.AlignCenter)
        layout.addWidget(qr)
        layout.addWidget(QLabel("Scan with your UPI app. Verify the recipient and amount before paying."), alignment=Qt.AlignCenter)
        save_button = QPushButton("Save QR Image")
        def save_qr():
            destination, _ = QFileDialog.getSaveFileName(dialog, "Save Payment QR", f"payment_{invoice}.png", "PNG Image (*.png)")
            if destination:
                try:
                    shutil.copy2(path, destination)
                    QMessageBox.information(dialog, "Saved", f"QR image saved to:\n{destination}")
                except Exception as exc:
                    QMessageBox.critical(dialog, "Save Failed", str(exc))
        save_button.clicked.connect(save_qr)
        layout.addWidget(save_button)
        dialog.exec()

    def p_invoices(self):
        data = allrows("invoices")
        if self.role == "retailer":
            data = [x for x in data if integer(val(x, "retailer_id")) == retailer_id(self.user)]
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.header("My Invoices" if self.role == "retailer" else "Invoices", "Open generated PDF invoices"))
        table = QTableWidget(len(data), 6)
        table.setHorizontalHeaderLabels(["ID", "Invoice", "Retailer", "Product", "Total", "Action"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        for row, item in enumerate(data):
            invoice = str(val(item, "invoice_number", "invoice_id", d=f"Invoice-{val(item, 'id')}"))
            values = [
                val(item, "id"),
                invoice,
                val(item, "retailer_id"),
                val(item, "product_name", "product_id", d="Multiple Products"),
                money(val(item, "total", "total_amount"))
            ]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value)))
            button = QPushButton("Open PDF")
            button.clicked.connect(lambda _, x=item, i=invoice: self.open_invoice(i, x))
            table.setCellWidget(row, 5, button)
        layout.addWidget(table)
        return widget

    def open_invoice(self, invoice, item):
        path = os.path.join(INV, invoice + ".pdf")
        if not os.path.exists(path):
            try:
                from invoice_email import generate_invoice_pdf
                path = generate_invoice_pdf(
                    invoice,
                    str(val(item, "retailer_id", d="Retailer")),
                    str(val(item, "product_name", "product_id", d="Multiple Products")),
                    integer(val(item, "quantity", d=1)),
                    num(val(item, "unit_price")),
                    num(val(item, "total", "total_amount")),
                    str(val(item, "invoice_date", "created_at", d=datetime.now().date()))
                )
            except Exception as e:
                QMessageBox.warning(self, "Invoice", str(e))
                return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def p_analytics(self):
        sales = allrows("sales")
        products = allrows("products")
        if self.role == "retailer":
            rid = retailer_id(self.user)
            sales = [x for x in sales if integer(val(x, "retailer_id")) == rid]

        def sale_date(row):
            return str(val(row, "sale_date", "created_at", d=""))[:10]

        def sale_total(row):
            return num(val(row, "total_amount", "total")) or num(val(row, "total"))

        today = datetime.now().date()
        last_seven = [(today.fromordinal(today.toordinal() - offset)).isoformat() for offset in range(6, -1, -1)]
        weekly = []
        for day in last_seven:
            day_sales = [row for row in sales if sale_date(row) == day]
            weekly.append({"date": day, "orders": len(day_sales), "amount": sum(sale_total(row) for row in day_sales)})

        product_names = {integer(val(p, "id")): str(val(p, "name", d=f"Product {val(p, 'id')}")) for p in products}
        product_stats = {}
        for row in sales:
            pid = integer(val(row, "product_id"))
            if not pid:
                continue
            entry = product_stats.setdefault(pid, {"name": product_names.get(pid, f"Product {pid}"), "units": 0, "revenue": 0.0})
            entry["units"] += integer(val(row, "quantity", "qty", d=1))
            entry["revenue"] += sale_total(row)
        best_sellers = sorted(product_stats.values(), key=lambda x: (x["units"], x["revenue"]), reverse=True)[:5]
        low_stock = sorted([p for p in products if integer(val(p, "quantity")) <= integer(val(p, "reorder_level", d=5))], key=lambda x: integer(val(x, "quantity")))[:8]
        total_revenue = sum(sale_total(row) for row in sales)
        total_units = sum(integer(val(row, "quantity", "qty", d=1)) for row in sales)

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(self.header("Sales Analytics", "Weekly performance, best sellers and stock alerts"))

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(self.card("Total Revenue", money(total_revenue), "Recorded sales"), 0, 0)
        grid.addWidget(self.card("Total Orders", len(sales), "Recorded sale rows"), 0, 1)
        grid.addWidget(self.card("Units Sold", total_units, "Across recorded sales"), 0, 2)
        grid.addWidget(self.card("Products", len(products), "In inventory"), 0, 3)
        layout.addLayout(grid)

        weekly_box = QFrame()
        weekly_box.setObjectName("panel")
        weekly_layout = QVBoxLayout(weekly_box)
        weekly_layout.addWidget(QLabel("WEEKLY SALES — LAST 7 DAYS"))
        max_amount = max([x["amount"] for x in weekly] + [1])
        for item in weekly:
            row = QHBoxLayout()
            date_label = QLabel(datetime.strptime(item["date"], "%Y-%m-%d").strftime("%a, %d %b"))
            date_label.setMinimumWidth(90)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(item["amount"] / max_amount * 100))
            bar.setTextVisible(False)
            bar.setMinimumHeight(18)
            amount_label = QLabel(money(item["amount"]))
            amount_label.setMinimumWidth(105)
            amount_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(date_label)
            row.addWidget(bar, 1)
            row.addWidget(amount_label)
            weekly_layout.addLayout(row)
        layout.addWidget(weekly_box)

        lower = QHBoxLayout()
        best_box = QFrame()
        best_box.setObjectName("panel")
        best_layout = QVBoxLayout(best_box)
        best_layout.addWidget(QLabel("BEST-SELLING PRODUCTS"))
        if best_sellers:
            best_layout.addWidget(self.table(["Product", "Units", "Revenue"], best_sellers, ["name", "units", lambda x: money(x["revenue"])]))
        else:
            best_layout.addWidget(QLabel("No product-level sales recorded yet."))
        stock_box = QFrame()
        stock_box.setObjectName("panel")
        stock_layout = QVBoxLayout(stock_box)
        stock_layout.addWidget(QLabel("LOW-STOCK ALERTS"))
        if low_stock:
            stock_layout.addWidget(self.table(["Product", "In Stock", "Reorder At"], low_stock, ["name", "quantity", "reorder_level"]))
        else:
            stock_layout.addWidget(QLabel("No low-stock products. Inventory levels look good."))
        lower.addWidget(best_box, 3)
        lower.addWidget(stock_box, 2)
        layout.addLayout(lower)

        recent_box = QFrame()
        recent_box.setObjectName("panel")
        recent_layout = QVBoxLayout(recent_box)
        recent_layout.addWidget(QLabel("RECENT SALES"))
        recent = sorted(sales, key=lambda x: sale_date(x), reverse=True)[:10]
        recent_layout.addWidget(self.table(["Sale ID", "Date", "Product", "Quantity", "Amount", "Payment"], recent, ["id", lambda x: sale_date(x) or "—", lambda x: product_names.get(integer(val(x, "product_id")), str(val(x, "product_name", d="Multiple items"))), lambda x: integer(val(x, "quantity", "qty", d=1)), lambda x: money(sale_total(x)), lambda x: str(val(x, "payment_status", d="Pending"))]))
        layout.addWidget(recent_box)
        layout.addStretch()
        return widget

    def p_shop(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.header("Shop", "Browse products and add them to your cart"))
        search = QLineEdit()
        search.setPlaceholderText("Search products")
        layout.addWidget(search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(18)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        def load():
            while grid.count():
                item = grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            data = products(search.text())
            for index, product in enumerate(data):
                frame = QFrame()
                frame.setObjectName("productCard")
                box = QVBoxLayout(frame)
                pid = integer(val(product, "id", "product_id"))
                image = QLabel()
                image.setFixedHeight(155)
                image.setAlignment(Qt.AlignCenter)
                path = product_image(pid)
                if path:
                    image.setPixmap(QPixmap(path).scaled(230, 145, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    image.setText("NO PRODUCT PHOTO")
                    image.setObjectName("noPhoto")
                box.addWidget(image)

                name = QLabel(str(val(product, "name", "product_name", d="Product")))
                name.setObjectName("productName")
                box.addWidget(name)
                price = QLabel(money(val(product, "price", "unit_price")))
                price.setObjectName("productPrice")
                box.addWidget(price)
                stock = integer(val(product, "stock", "quantity", "stock_quantity"))
                box.addWidget(QLabel(f"Stock available: {stock}"))
                quantity = QSpinBox()
                quantity.setMinimum(1)
                quantity.setMaximum(max(1, stock))
                quantity.setEnabled(stock > 0)
                add = QPushButton("Add to Cart")
                add.setEnabled(stock > 0)
                add.clicked.connect(lambda _, x=product, q=quantity: self.add_to_cart(x, q.value()))
                box.addWidget(quantity)
                box.addWidget(add)
                grid.addWidget(frame, index // 3, index % 3)

        search.textChanged.connect(load)
        load()
        return widget

    def add_to_cart(self, product, quantity):
        pid = integer(val(product, "id", "product_id"))
        for item in self.cart:
            if item["product_id"] == pid:
                item["quantity"] += quantity
                QMessageBox.information(self, "Cart", "Product quantity updated in cart.")
                return
        self.cart.append({
            "product_id": pid,
            "product_name": val(product, "name", "product_name"),
            "quantity": quantity,
            "unit_price": num(val(product, "price", "unit_price"))
        })
        QMessageBox.information(self, "Cart", "Product added to cart.")

    def p_my_cart(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.header("My Cart", "Review products before checkout"))
        table = QTableWidget(len(self.cart), 5)
        table.setHorizontalHeaderLabels(["Product", "Quantity", "Price", "Total", "Action"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        total = 0
        for row, item in enumerate(self.cart):
            line_total = item["quantity"] * item["unit_price"]
            total += line_total
            values = [item["product_name"], item["quantity"], money(item["unit_price"]), money(line_total)]
            for col, value in enumerate(values):
                table.setItem(row, col, QTableWidgetItem(str(value)))
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda _, index=row: self.remove_from_cart(index))
            table.setCellWidget(row, 4, remove)
        layout.addWidget(table)
        total_label = QLabel(f"Cart Total: {money(total)}")
        total_label.setObjectName("cartTotal")
        layout.addWidget(total_label)
        checkout_button = QPushButton("CHECKOUT")
        checkout_button.setObjectName("checkoutButton")
        checkout_button.clicked.connect(self.do_checkout)
        checkout_button.setEnabled(bool(self.cart))
        layout.addWidget(checkout_button)
        return widget

    def remove_from_cart(self, index):
        if 0 <= index < len(self.cart):
            self.cart.pop(index)
        self.page("My Cart")

    def do_checkout(self):
        if not self.cart:
            QMessageBox.warning(self, "Checkout", "Your cart is empty.")
            return
        try:
            result = checkout(retailer_id(self.user), self.cart)
            invoice = str(val(result, "invoice_number", "invoice_id", d="N/A"))
            total = num(val(result, "total", "total_amount", "amount"))
            self.cart = []
            QMessageBox.information(
                self,
                "Order Placed",
                f"Order placed successfully.\n\nInvoice: {invoice}\nTotal: {money(total)}\nPayment: Pending\n\nYour payment QR code will open next."
            )

            payment = None
            try:
                payment_rows = allrows("payments")
                for item in payment_rows:
                    item_invoice = str(val(item, "invoice_number", "invoice_id", d=""))
                    item_retailer = integer(val(item, "retailer_id"))
                    if item_invoice == invoice and item_retailer == retailer_id(self.user):
                        payment = item
                        break
            except Exception:
                payment = None

            if payment is None:
                payment = {
                    "invoice_number": invoice,
                    "amount": total,
                    "total": total,
                    "retailer_id": retailer_id(self.user),
                    "status": "Pending",
                    "payment_status": "Pending"
                }

            self.show_payment_qr(payment)
            self.page("My Invoices")
        except Exception as e:
            QMessageBox.critical(self, "Checkout Failed", str(e))

    def p_my_orders(self):
        data = [x for x in allrows("sales") if integer(val(x, "retailer_id")) == retailer_id(self.user)]
        return self.simple_table("My Orders", ["ID", "Product", "Quantity", "Unit Price", "Total", "Status"], data, [
            "id", "product_id", "quantity",
            lambda x: money(val(x, "unit_price")),
            lambda x: money(val(x, "total", "total_amount")),
            lambda x: val(x, "payment_status", "status", d="Pending")
        ])

    def p_my_payments(self):
        return self.p_payments()

    def p_my_invoices(self):
        return self.p_invoices()

    def simple_table(self, title, headers, data, formats):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.header(title))
        layout.addWidget(self.table(headers, data, formats))
        return widget


STYLE = """
QWidget {
    background: #F2F4F1;
    color: #17201D;
    font-family: Segoe UI;
    font-size: 14px;
}
QMainWindow { background: #F2F4F1; }
#sidebar {
    background: #151A19;
}
#logo {
    color: #FFFFFF;
    font-size: 24px;
    font-weight: 900;
    padding: 8px 8px;
}
#sideUser {
    color: #FFFFFF;
    font-size: 15px;
    font-weight: 700;
    padding: 4px 8px;
}
#sideRole {
    color: #38B2AC;
    font-size: 11px;
    font-weight: 900;
    padding: 0 8px;
    letter-spacing: 1px;
}
#dangerButton {
    background: #C53030;
    color: #FFFFFF;
    border: 0;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 700;
}
#dangerButton:hover {
    background: #9B2C2C;
}
#navButton, #bottomButton, #logoutButton {
    background: transparent;
    color: #CBD5D1;
    border: 0;
    border-radius: 9px;
    text-align: left;
    padding: 12px 14px;
    font-weight: 600;
}
#navButton:hover, #bottomButton:hover {
    background: #26302D;
    color: #FFFFFF;
}
#logoutButton:hover {
    background: #3B2525;
    color: #FFFFFF;
}
QPushButton {
    background: #38B2AC;
    color: #FFFFFF;
    border: 0;
    border-radius: 8px;
    padding: 9px 15px;
    font-weight: 700;
}
QPushButton:hover { background: #2C9691; }
QPushButton:disabled { background: #B8C4C0; color: #EEF2F0; }
#secondaryButton { background: #718078; }
#dangerButton { background: #C53030; }
#dangerButton:hover { background: #A82424; }
#checkoutButton { background: #D4A72C; color: #1B1A13; font-size: 15px; padding: 12px; }
#loginButton { background: #38B2AC; padding: 12px; font-size: 15px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #FFFFFF;
    color: #17201D;
    border: 1px solid #CBD6D1;
    border-radius: 8px;
    padding: 9px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 2px solid #38B2AC; }
QTableWidget {
    background: #FFFFFF;
    color: #17201D;
    border: 1px solid #D7E0DC;
    border-radius: 10px;
    gridline-color: #E6ECE9;
    alternate-background-color: #F8FAF8;
}
QTableWidget::item:selected { background: #D9F1EE; color: #17201D; }
QHeaderView::section {
    background: #E4EBE7;
    color: #17201D;
    padding: 10px;
    border: 0;
    font-weight: 800;
}
#pageTitle { font-size: 30px; font-weight: 900; color: #151A19; }
#pageSubtitle { color: #718078; font-size: 14px; }
#sectionTitle { font-size: 16px; font-weight: 900; color: #151A19; padding-top: 10px; }
#statCard {
    background: #FFFFFF;
    border: 1px solid #D9E1DD;
    border-radius: 14px;
    padding: 8px;
}
#cardLabel { color: #718078; font-size: 11px; font-weight: 900; }
#cardValue { color: #151A19; font-size: 25px; font-weight: 900; }
#cardNote { color: #8A9690; font-size: 12px; }
#productCard {
    background: #FFFFFF;
    border: 1px solid #D9E1DD;
    border-radius: 15px;
    padding: 8px;
}
#productCard:hover { border: 2px solid #38B2AC; }
#productName { font-size: 17px; font-weight: 900; color: #17201D; }
#productPrice { font-size: 20px; font-weight: 900; color: #2F855A; }
#photoPreview {
    background: #E8EEEB;
    border: 1px dashed #AABAB4;
    border-radius: 12px;
    color: #718078;
}
#noPhoto { color: #9AA6A0; font-size: 11px; }
#cartTotal { font-size: 22px; font-weight: 900; color: #151A19; padding: 8px; }
#successText { color: #2F855A; font-weight: 700; padding: 10px; }
#pendingTitle { color: #D69E2E; font-size: 20px; font-weight: 900; }
#dialogTitle { font-size: 20px; font-weight: 900; color: #151A19; }
#loginTitle { color: #151A19; font-size: 29px; font-weight: 900; }
#loginSubtitle { color: #718078; font-size: 14px; }
#demo { color: #718078; line-height: 1.5; }
QDialog { background: #F2F4F1; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #E6ECE9; width: 10px; border-radius: 5px; }
QScrollBar::handle:vertical { background: #9DB9B2; border-radius: 5px; min-height: 25px; }
QScrollBar::handle:vertical:hover { background: #38B2AC; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    login = Login()
    if login.exec() != QDialog.Accepted:
        return
    window = Main(login.user)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
