"""
Configuration for the Canada Tech Deal Tracker.

Provides project paths, default settings, and helpers for reading
configuration from the SQLite database with fallbacks.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "deals.db"
LOG_PATH = DATA_DIR / "checker.log"

# Ensure data directory exists
DATA_DIR.mkdir(exist_ok=True)

SUPPORTED_CATEGORIES = [
    'laptop', 'desktop', 'ram', 'cpu', 'gpu',
    'motherboard', 'psu', 'cooler', 'case', 'ssd', 'other'
]

SUPPORTED_RETAILERS = [
    'bestbuy_ca', 'amazon_ca', 'canada_computers', 'newegg_ca'
]

RETAILER_DISPLAY_NAMES = {
    'bestbuy_ca': 'Best Buy Canada',
    'amazon_ca': 'Amazon.ca',
    'canada_computers': 'Canada Computers',
    'newegg_ca': 'Newegg.ca',
}

# Default settings seeded into the settings table on first run
DEFAULT_SETTINGS = {
    'email_smtp_server': 'smtp.gmail.com',
    'email_smtp_port': '587',
    'email_from': '',
    'email_to': '',
    'email_password': '',
    'serpapi_key': '',
    'check_interval_minutes': '360',
}


def get_serpapi_key(db=None):
    """Get SerpApi key from DB -> Streamlit secrets -> env var -> empty string."""
    # Try database first
    if db:
        val = db.get_setting('serpapi_key')
        if val:
            return val

    # Try Streamlit secrets
    try:
        import streamlit as st
        val = st.secrets.get("SERPAPI_KEY", "")
        if val:
            return val
    except Exception:
        pass

    # Fallback to environment variable
    return os.environ.get("SERPAPI_KEY", "")
