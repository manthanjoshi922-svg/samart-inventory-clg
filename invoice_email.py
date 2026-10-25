import os
import smtplib
from email.message import EmailMessage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INVOICE_DIR = os.path.join(
    BASE_DIR,
    "generated_invoices"
)

os.makedirs(INVOICE_DIR, exist_ok=True)


def generate_invoice_pdf(
    invoice_number,
    retailer_name,
    product_name,
    quantity,
    unit_price,
    total_amount,
    invoice_date
):
    invoice_number = str(
        invoice_number or "N/A"
    )

    retailer_name = (
        retailer_name or "Unknown Retailer"
    )

    product_name = (
        product_name or "Unknown Product"
    )

    quantity = int(quantity or 0)
    unit_price = float(unit_price or 0)
    total_amount = float(total_amount or 0)

    filename = os.path.join(
        INVOICE_DIR,
        f"{invoice_number}.pdf"
    )

    pdf = canvas.Canvas(
        filename,
        pagesize=A4
    )

    width, height = A4

    pdf.setFont(
        "Helvetica-Bold",
        22
    )

    pdf.drawString(
        50,
        height - 60,
        "SMART INVENTORY MANAGEMENT"
    )

    pdf.setFont(
        "Helvetica-Bold",
        16
    )

    pdf.drawString(
        50,
        height - 100,
        "INVOICE"
    )

    pdf.setFont(
        "Helvetica",
        11
    )

    y = height - 140

    pdf.drawString(
        50,
        y,
        f"Invoice Number: {invoice_number}"
    )

    y -= 20

    pdf.drawString(
        50,
        y,
        f"Date: {invoice_date or 'N/A'}"
    )

    y -= 40

    pdf.drawString(
        50,
        y,
        f"Retailer: {retailer_name}"
    )

    y -= 30

    pdf.drawString(
        50,
        y,
        f"Product: {product_name}"
    )

    y -= 30

    pdf.drawString(
        50,
        y,
        f"Quantity: {quantity}"
    )

    y -= 30

    pdf.drawString(
        50,
        y,
        f"Unit Price: Rs. {unit_price:,.2f}"
    )

    y -= 30

    pdf.setFont(
        "Helvetica-Bold",
        13
    )

    pdf.drawString(
        50,
        y,
        f"Total Amount: Rs. {total_amount:,.2f}"
    )

    y -= 50

    pdf.setFont(
        "Helvetica",
        10
    )

    pdf.drawString(
        50,
        y,
        "Thank you for your business."
    )

    pdf.save()

    return filename


def send_invoice_email(
    recipient_email,
    invoice_number,
    pdf_path
):
    smtp_host = os.getenv(
        "SMTP_HOST",
        ""
    )

    smtp_port = int(
        os.getenv(
            "SMTP_PORT",
            "587"
        )
    )

    smtp_user = os.getenv(
        "SMTP_USER",
        ""
    )

    smtp_password = os.getenv(
        "SMTP_PASSWORD",
        ""
    )

    if not recipient_email:
        return False, "Retailer email is empty."

    if not smtp_host or not smtp_user or not smtp_password:
        return False, "SMTP settings are not configured."

    message = EmailMessage()

    message["Subject"] = (
        f"Invoice {invoice_number}"
    )

    message["From"] = smtp_user
    message["To"] = recipient_email

    message.set_content(
        f"""
Dear Retailer,

Please find attached invoice {invoice_number}.

Thank you for your business.

Smart Inventory Management
"""
    )

    with open(
        pdf_path,
        "rb"
    ) as file:
        pdf_data = file.read()

    message.add_attachment(
        pdf_data,
        maintype="application",
        subtype="pdf",
        filename=os.path.basename(
            pdf_path
        )
    )

    try:
        with smtplib.SMTP(
            smtp_host,
            smtp_port
        ) as server:

            server.starttls()

            server.login(
                smtp_user,
                smtp_password
            )

            server.send_message(
                message
            )

        return True, "Invoice email sent successfully."

    except Exception as e:
        return False, str(e)