import streamlit as st
from database import authenticate_user

def show_login_page():
    st.markdown(
        """
        <style>
        .main {
            background-color: #f5f7fa;
        }

        .login-title {
            text-align: center;
            font-size: 42px;
            font-weight: 700;
            margin-top: 50px;
        }

        .login-subtitle {
            text-align: center;
            font-size: 18px;
            margin-bottom: 30px;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="login-title">📦 Smart Inventory</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="login-subtitle">Management & Retailer Portal</div>',
        unsafe_allow_html=True
    )

    left, center, right = st.columns([1, 2, 1])

    with center:
        st.markdown("### 🔐 Login")

        role = st.selectbox(
            "Login Type",
            ["Management", "Retailer"]
        )

        username = st.text_input(
            "Username",
            placeholder="Enter your username"
        )

        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password"
        )

        login_button = st.button(
            "LOGIN",
            use_container_width=True
        )

        if login_button:
            selected_role = role.lower()

            user = authenticate_user(
                username,
                password,
                selected_role
            )

            if user:
                st.session_state.user = user
                st.success("Login successful!")
                st.rerun()
            else:
                st.error(
                    "Invalid username, password, or login type."
                )

        st.markdown("---")

        st.caption(
            "Smart Inventory Management System"
        )