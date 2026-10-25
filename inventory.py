import streamlit as st
from database import (
    get_products,
    add_product,
    update_product,
    delete_product,
    get_product
)


def show_inventory():

    st.title("📦 Inventory Management")

    st.write(
        "Manage products, stock levels, prices and product information."
    )

    st.divider()

    search = st.text_input(
        "🔎 Search Product",
        placeholder="Search by product name, SKU, category or barcode"
    )

    products = get_products(search)

    st.subheader("Product Inventory")

    if products.empty:
        st.info("No products found.")
    else:
        display_products = products[
            [
                "id",
                "name",
                "sku",
                "category",
                "price",
                "stock",
                "reorder_level",
                "stock_status"
            ]
        ].copy()

        display_products.columns = [
            "ID",
            "Product",
            "SKU",
            "Category",
            "Price",
            "Stock",
            "Reorder Level",
            "Status"
        ]

        st.dataframe(
            display_products,
            use_container_width=True,
            hide_index=True
        )

    st.divider()

    add_tab, edit_tab, delete_tab = st.tabs(
        [
            "➕ Add Product",
            "✏️ Edit Product",
            "🗑️ Delete Product"
        ]
    )

    with add_tab:

        st.subheader("Add New Product")

        with st.form("add_product_form"):

            name = st.text_input(
                "Product Name"
            )

            sku = st.text_input(
                "SKU"
            )

            category = st.text_input(
                "Category"
            )

            price = st.number_input(
                "Price",
                min_value=0.0,
                step=1.0
            )

            stock = st.number_input(
                "Stock Quantity",
                min_value=0,
                step=1
            )

            reorder_level = st.number_input(
                "Reorder Level",
                min_value=0,
                value=10,
                step=1
            )

            submit = st.form_submit_button(
                "Add Product",
                use_container_width=True
            )

            if submit:

                if not name.strip():

                    st.error(
                        "Product name is required."
                    )

                elif not sku.strip():

                    st.error(
                        "SKU is required."
                    )

                elif not category.strip():

                    st.error(
                        "Category is required."
                    )

                elif price <= 0:

                    st.error(
                        "Price must be greater than 0."
                    )

                else:

                    try:

                        product_id = add_product(
                            name,
                            sku,
                            category,
                            price,
                            stock,
                            reorder_level
                        )

                        if product_id is None:

                            st.error(
                                "SKU already exists. Please use a different SKU."
                            )

                        else:

                            st.success(
                                f"Product added successfully. Product ID: {product_id}"
                            )

                            st.rerun()

                    except Exception as error:

                        st.error(
                            f"Unable to add product: {error}"
                        )

    with edit_tab:

        st.subheader("Edit Product")

        all_products = get_products("")

        if all_products.empty:

            st.info(
                "No products available."
            )

        else:

            product_options = {
                f"{row['name']} | {row['sku']}": int(row["id"])
                for _, row in all_products.iterrows()
            }

            selected_product = st.selectbox(
                "Select Product",
                list(product_options.keys()),
                key="edit_product_select"
            )

            selected_id = product_options[selected_product]

            product = get_product(selected_id)

            if product:

                with st.form("edit_product_form"):

                    name = st.text_input(
                        "Product Name",
                        value=product["name"]
                    )

                    sku = st.text_input(
                        "SKU",
                        value=product["sku"]
                    )

                    category = st.text_input(
                        "Category",
                        value=product["category"]
                    )

                    price = st.number_input(
                        "Price",
                        min_value=0.0,
                        value=float(product["price"]),
                        step=1.0
                    )

                    stock = st.number_input(
                        "Stock Quantity",
                        min_value=0,
                        value=int(product["stock"]),
                        step=1
                    )

                    reorder_level = st.number_input(
                        "Reorder Level",
                        min_value=0,
                        value=int(product["reorder_level"]),
                        step=1
                    )

                    update_button = st.form_submit_button(
                        "Update Product",
                        use_container_width=True
                    )

                    if update_button:

                        if not name.strip():

                            st.error(
                                "Product name is required."
                            )

                        elif not sku.strip():

                            st.error(
                                "SKU is required."
                            )

                        elif not category.strip():

                            st.error(
                                "Category is required."
                            )

                        elif price <= 0:

                            st.error(
                                "Price must be greater than 0."
                            )

                        else:

                            try:

                                updated = update_product(
                                    selected_id,
                                    name,
                                    sku,
                                    category,
                                    price,
                                    stock,
                                    reorder_level
                                )

                                if not updated:

                                    st.error(
                                        "SKU already exists for another product."
                                    )

                                else:

                                    st.success(
                                        "Product updated successfully."
                                    )

                                    st.rerun()

                            except Exception as error:

                                st.error(
                                    f"Unable to update product: {error}"
                                )

    with delete_tab:

        st.subheader("Delete Product")

        all_products = get_products("")

        if all_products.empty:

            st.info(
                "No products available."
            )

        else:

            product_options = {
                f"{row['name']} | {row['sku']}": int(row["id"])
                for _, row in all_products.iterrows()
            }

            selected_product = st.selectbox(
                "Select Product to Delete",
                list(product_options.keys()),
                key="delete_product_select"
            )

            selected_id = product_options[selected_product]

            st.warning(
                "Deleting a product permanently removes it from the inventory."
            )

            confirm = st.checkbox(
                "I confirm that I want to delete this product.",
                key="delete_confirmation"
            )

            delete_button = st.button(
                "Delete Product",
                type="primary",
                disabled=not confirm,
                use_container_width=True
            )

            if delete_button:

                try:

                    deleted = delete_product(
                        selected_id
                    )

                    if deleted:

                        st.success(
                            "Product deleted successfully."
                        )

                        st.rerun()

                    else:

                        st.error(
                            "Unable to delete product."
                        )

                except Exception as error:

                    st.error(
                        f"Unable to delete product: {error}"
                    )