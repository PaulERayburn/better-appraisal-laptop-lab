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


# ── Trusted Retailers ──
# Known legitimate retailers in Canada and USA.
# Products from unlisted sellers get flagged as unverified.

TRUSTED_RETAILERS = {
    # Canadian
    'amazon.ca', 'amazon ca', 'amazon canada',
    'best buy canada', 'best buy', 'bestbuy.ca', 'best buy canada marketplace',
    'canada computers', 'canadacomputers',
    'newegg.ca', 'newegg canada',
    'memory express', 'memoryexpress',
    'staples', 'staples canada',
    'the source',
    'london drugs',
    'walmart.ca', 'walmart canada',
    # US
    'amazon.com', 'amazon',
    'newegg.com', 'newegg',
    'best buy', 'bestbuy.com',
    'walmart', 'walmart.com',
    'b&h photo', 'b&h', 'bhphotovideo',
    'adorama',
    'micro center', 'microcenter',
    'gamestop',
    'costco',
    'target', 'target.com',
    'cdw', 'cdw.com',
    'dell', 'dell.com',
    'hp', 'hp.com',
    'lenovo', 'lenovo.com',
    'crucial.com', 'crucial',
    'corsair', 'corsair.com',
    'kingston', 'kingston.com',
}


def is_trusted_retailer(source_name):
    """Check if a source/store name is a known trusted retailer.

    Returns: 'trusted', 'unknown', or 'suspicious'
    """
    if not source_name:
        return 'unknown'
    source_lower = source_name.lower().strip()

    # Check against trusted list
    for trusted in TRUSTED_RETAILERS:
        if trusted in source_lower or source_lower in trusted:
            return 'trusted'

    # Flag suspicious patterns — foreign TLDs, eBay sub-sellers, etc.
    suspicious_patterns = [
        '.uy', '.ph', '.cn', '.ru', '.br', '.ar', '.mx',
        'aliexpress', 'alibaba', 'dhgate', 'banggood', 'temu',
        'wish.com',
    ]
    for pattern in suspicious_patterns:
        if pattern in source_lower:
            return 'suspicious'

    # eBay is mixed — main eBay is OK but sub-sellers are unknown
    if 'ebay' in source_lower:
        if source_lower == 'ebay' or source_lower == 'ebay.com' or source_lower == 'ebay.ca':
            return 'trusted'
        return 'unknown'  # eBay sub-sellers

    return 'unknown'
