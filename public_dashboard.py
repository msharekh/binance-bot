"""Password-protected entry point for the temporary public dashboard."""

import hmac
import os
import runpy
import time
from pathlib import Path

import streamlit as st


password = os.environ.get("PUBLIC_DASHBOARD_PASSWORD", "")
if len(password) < 20:
    st.error("Public dashboard access is not configured.")
    st.stop()

if not st.session_state.get("public_authenticated", False):
    st.title("Dashboard sign in")
    with st.form("public_login"):
        supplied = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if hmac.compare_digest(supplied.encode(), password.encode()):
            st.session_state.public_authenticated = True
            st.rerun()
        else:
            time.sleep(1)
            st.error("Incorrect password.")
    st.stop()

runpy.run_path(str(Path(__file__).with_name("dashboard.py")), run_name="__main__")
