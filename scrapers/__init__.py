"""
Scrapers package for the Canada Tech Deal Tracker.

All scrapers return normalized Product dicts with a consistent schema.
"""

from config import SUPPORTED_CATEGORIES, SUPPORTED_RETAILERS


def make_product(retailer, retailer_sku, name, url, category, price,
                 original_price=None, brand=None, specs=None):
    """Create a normalized product dict from scraper output.

    This is the canonical format all scrapers should return.
    """
    product = {
        'retailer': retailer,
        'retailer_sku': str(retailer_sku),
        'name': name,
        'url': url,
        'category': category,
        'price': float(price) if price else 0,
        'original_price': float(original_price) if original_price else None,
        'brand': brand,
        'specs': specs or {},
    }
    return product


# Map common SerpApi/Google Shopping source names to our retailer IDs
RETAILER_SOURCE_MAP = {
    'best buy': 'bestbuy_ca',
    'best buy canada': 'bestbuy_ca',
    'bestbuy.ca': 'bestbuy_ca',
    'amazon.ca': 'amazon_ca',
    'amazon': 'amazon_ca',
    'amazon canada': 'amazon_ca',
    'canada computers': 'canada_computers',
    'canadacomputers': 'canada_computers',
    'newegg': 'newegg_ca',
    'newegg canada': 'newegg_ca',
    'newegg.ca': 'newegg_ca',
}


def identify_retailer(source_name):
    """Map a source/store name (e.g., from SerpApi) to our retailer ID.

    Returns retailer ID string or None if unrecognized.
    """
    if not source_name:
        return None
    source_lower = source_name.lower().strip()
    for pattern, retailer_id in RETAILER_SOURCE_MAP.items():
        if pattern in source_lower:
            return retailer_id
    return None
