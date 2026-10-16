"""Entry point: python -m streamlit run app.py."""

import streamlit as st

from src.config import configure_provider_environment, local_binding_allowed
from src.ui.dashboard import main

if not local_binding_allowed(st.get_option("server.address")):
    st.error(
        (
            "This single-operator app requires a loopback server address. Start with "
            "--server.address 127.0.0.1. Shared-user hosting requires authentication, "
            "ownership and quota enforcement."
        )
    )
    st.stop()
configure_provider_environment()
main()
