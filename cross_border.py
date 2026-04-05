"""
Cross-border shopping utilities for Canadian users buying from US retailers.

Provides USD→CAD exchange rates, estimated shipping costs, and
ships-to-Canada likelihood flags per retailer.
"""

import json
import time
import requests
from pathlib import Path

from config import DATA_DIR


# ── Exchange Rate ──

_RATE_CACHE_PATH = DATA_DIR / "exchange_rate_cache.json"
_RATE_CACHE_TTL = 86400  # 24 hours


def get_usd_to_cad_rate():
    """Fetch current USD to CAD exchange rate. Cached for 24 hours.

    Uses the free exchangerate-api.com endpoint (no key needed).
    Falls back to a reasonable default if the API is unavailable.
    """
    # Check cache first
    cached = _read_rate_cache()
    if cached:
        return cached

    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = data.get("rates", {}).get("CAD", 0)
        if rate > 0:
            _write_rate_cache(rate)
            return rate
    except Exception:
        pass

    # Fallback: try Bank of Canada RSS
    try:
        resp = requests.get(
            "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1",
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        obs = data.get("observations", [])
        if obs:
            rate = float(obs[-1].get("FXUSDCAD", {}).get("v", 0))
            if rate > 0:
                _write_rate_cache(rate)
                return rate
    except Exception:
        pass

    # Last resort fallback
    return 1.38


def _read_rate_cache():
    """Read cached exchange rate if still valid."""
    try:
        if _RATE_CACHE_PATH.exists():
            data = json.loads(_RATE_CACHE_PATH.read_text())
            if time.time() - data.get("timestamp", 0) < _RATE_CACHE_TTL:
                return data.get("rate")
    except Exception:
        pass
    return None


def _write_rate_cache(rate):
    """Write exchange rate to cache."""
    try:
        _RATE_CACHE_PATH.write_text(json.dumps({
            "rate": rate,
            "timestamp": time.time(),
        }))
    except Exception:
        pass


# ── Shipping Estimates ──

SHIPPING_ESTIMATES_USD = {
    'ram': (12, 25),
    'ssd': (12, 25),
    'cpu': (15, 30),
    'gpu': (25, 50),
    'laptop': (30, 60),
    'desktop': (50, 120),
    'motherboard': (20, 45),
    'psu': (20, 45),
    'cooler': (20, 40),
    'case': (40, 80),
    'other': (20, 50),
}


def estimate_shipping_usd(category):
    """Return (min, max) estimated shipping in USD for a product category."""
    return SHIPPING_ESTIMATES_USD.get(category, SHIPPING_ESTIMATES_USD['other'])


def estimate_cad_total(usd_price, category, rate=None):
    """Calculate estimated CAD total including shipping.

    Returns dict with all cost breakdown fields.
    """
    if rate is None:
        rate = get_usd_to_cad_rate()

    ship_low, ship_high = estimate_shipping_usd(category)
    cad_price = usd_price * rate
    cad_ship_low = ship_low * rate
    cad_ship_high = ship_high * rate

    return {
        'usd_price': usd_price,
        'cad_price': round(cad_price, 2),
        'shipping_usd_low': ship_low,
        'shipping_usd_high': ship_high,
        'cad_total_low': round(cad_price + cad_ship_low, 2),
        'cad_total_high': round(cad_price + cad_ship_high, 2),
        'exchange_rate': rate,
    }


# ── Ships to Canada ──

SHIPS_TO_CANADA_MAP = {
    'amazon': 'Likely',
    'amazon.com': 'Likely',
    'newegg': 'Likely',
    'newegg.com': 'Likely',
    'b&h': 'Likely',
    'b&h photo': 'Likely',
    'bhphotovideo': 'Likely',
    'adorama': 'Likely',
    'best buy': 'Unlikely',
    'bestbuy.com': 'Unlikely',
    'walmart': 'Unlikely',
    'walmart.com': 'Unlikely',
    'target': 'Unlikely',
    'micro center': 'Unlikely',
    'microcenter': 'Unlikely',
    'ebay': 'Unknown',
    'ebay.com': 'Unknown',
    'aliexpress': 'Likely',
}


def ships_to_canada(source_name):
    """Return 'Likely', 'Unlikely', or 'Unknown' based on retailer name."""
    if not source_name:
        return 'Unknown'
    source_lower = source_name.lower().strip()
    for pattern, status in SHIPS_TO_CANADA_MAP.items():
        if pattern in source_lower:
            return status
    return 'Unknown'


def shipping_badge_color(status):
    """Return a color string for the shipping status badge."""
    return {
        'Likely': 'green',
        'Unlikely': 'red',
        'Unknown': 'orange',
    }.get(status, 'gray')
