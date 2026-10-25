import streamlit as st


def render_invoices(invoices):
    for invoice in invoices:
        retailer_name = invoice["retailer_name"] or "Unknown Retailer"
        product_name = invoice["product_name"] or "Unknown Product"
        invoice_number = invoice["invoice_number"] or "N/A"
        amount = float(invoice["total_amount"] or 0)
        quantity = int(invoice["quantity"] or 0)
        unit_price = float(invoice["unit_price"] or 0)

        st.markdown(f"### Invoice {invoice['id']}")

        st.write(f"Invoice Number: **{invoice_number}**")
        st.write(f"Retailer: **{retailer_name}**")
        st.write(f"Product: **{product_name}**")
        st.write(f"Quantity: **{quantity}**")
        st.write(f"Unit Price: **₹{unit_price:,.2f}**")
        st.write(f"Amount: **₹{amount:,.2f}**")