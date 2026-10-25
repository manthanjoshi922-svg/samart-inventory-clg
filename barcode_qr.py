import os
from urllib.parse import urlencode
import qrcode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QR_DIR = os.path.join(BASE_DIR, "generated_qr")
os.makedirs(QR_DIR, exist_ok=True)


def generate_payment_qr(upi_id, amount, invoice_number):
    upi_id = str(upi_id or "").strip()
    amount = float(amount or 0)
    invoice_number = str(invoice_number or "INVOICE")

    if not upi_id or "@" not in upi_id:
        raise ValueError("Please enter a valid UPI ID.")

    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    payment_data = "upi://pay?" + urlencode({
        "pa": upi_id,
        "pn": "Smart Inventory",
        "am": f"{amount:.2f}",
        "cu": "INR",
        "tn": invoice_number
    })

    qr = qrcode.QRCode(
        version=1,
        box_size=10,
        border=4
    )
    qr.add_data(payment_data)
    qr.make(fit=True)

    image = qr.make_image(
        fill_color="black",
        back_color="white"
    )

    safe_invoice = "".join(
        ch for ch in invoice_number
        if ch.isalnum() or ch in "-_"
    ) or "INVOICE"

    path = os.path.join(
        QR_DIR,
        f"payment_{safe_invoice}.png"
    )

    image.save(path)
    return path

import os
import barcode
from barcode.writer import ImageWriter

def generate_barcode(product_code, output_dir="generated_barcodes"):
    os.makedirs(output_dir, exist_ok=True)
    code = barcode.get("code128", str(product_code), writer=ImageWriter())
    filename = os.path.join(output_dir, str(product_code))
    return code.save(filename)