"""Actual V5 UI against the dedicated acceptance DB, with no demo catalog seeding.

Requires COMMERCE_OFFLINE=1: live capture runs separately, only after explicit approval.
"""

import os
from pathlib import Path

import streamlit as st

from scripts.v5_live_acceptance import _scope
from src.config import load_settings, local_binding_allowed, offline_mode
from src.ui.dashboard import main

if not offline_mode() or not local_binding_allowed(st.get_option("server.address")):
    st.error("Acceptance UI requires COMMERCE_OFFLINE=1 and a loopback server address.")
    st.stop()

folder = Path(os.environ.get("V5_ACCEPTANCE_FOLDER", "artifacts/v5-live-acceptance-20261016"))
_scope(load_settings().database_path, folder)
if "results" not in st.session_state:
    st.session_state["results"] = []
    st.session_state["last_query"] = "Dedicated CJ acceptance workspace — no demo catalog loaded"
st.session_state["v5_capture_only"] = True
main()
