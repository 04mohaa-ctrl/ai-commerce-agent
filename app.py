"""Entry point: python -m streamlit run app.py."""

from src.config import configure_provider_environment
from src.ui.dashboard import main

configure_provider_environment()
main()
