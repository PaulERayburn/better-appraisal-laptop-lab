"""
SerpApi Google Shopping scraper for Canadian tech deals.

Uses the Google Shopping engine with gl=ca for Canadian results.
This is the primary/universal data source since it aggregates
results from all retailers.
"""

import re
import requests
import json

from scrapers import make_product, identify_retailer
from spec_parser import extract_specs, categorize_product


def search_products(query, category=None, api_key=None, max_results=40):
    """Search Google Shopping Canada via SerpApi.

    Args:
        query: Search string (e.g., "DDR5 RAM 32GB")
        category: Product category hint for spec parsing. If None, auto-detected.
        api_key: SerpApi API key
        max_results: Maximum products to return

    Returns:
        (products_list, error_string_or_None)
    """
    if not api_key:
        return None, "SerpApi key not configured. Set it in Settings."

    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": api_key,
        "num": max_results,
        "gl": "ca",
        "hl": "en",
        "direct_link": "true",
    }

    try:
        response = requests.get("https://serpapi.com/search", params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            return None, f"API Error: {data['error']}"

        shopping_results = data.get("shopping_results", [])
        if not shopping_results:
            return None, "No products found for this search."

        products = []
        for item in shopping_results[:max_results]:
            name = item.get("title", "Unknown Product")

            # Parse price
            price_str = item.get("price", "$0")
            if isinstance(price_str, str):
                price = float(re.sub(r'[^\d.]', '', price_str) or 0)
            else:
                price = float(price_str) if price_str else 0

            # Original/old price
            original_price = None
            old_price_str = item.get("old_price", "")
            if old_price_str:
                original_price = float(re.sub(r'[^\d.]', '', old_price_str) or 0)
                if original_price <= price:
                    original_price = None

            # URL - prefer direct link
            url = item.get("link", "") or item.get("product_link", "")

            # Identify retailer from source
            source = item.get("source", "")
            retailer = identify_retailer(source)

            # Use product_id from Google Shopping as SKU fallback
            retailer_sku = item.get("product_id", "")

            # Determine category
            product_category = category or categorize_product(name)

            # Parse specs
            specs = extract_specs(name, product_category)

            product = make_product(
                retailer=retailer or 'unknown',
                retailer_sku=retailer_sku,
                name=name,
                url=url,
                category=product_category,
                price=price,
                original_price=original_price,
                brand=_extract_brand(name),
                specs=specs,
            )
            # Attach extra metadata
            product['source_display'] = source
            product['thumbnail'] = item.get("thumbnail", "")
            product['saving'] = (original_price - price) if original_price else 0

            products.append(product)

        return products, None

    except requests.exceptions.Timeout:
        return None, "Request timed out. Try again later."
    except requests.exceptions.RequestException as e:
        return None, f"Failed to fetch search results: {str(e)}"
    except json.JSONDecodeError:
        return None, "Invalid response from search API."


def build_search_query(base_query, min_specs=None):
    """Build an enhanced search query based on minimum spec requirements."""
    if not min_specs:
        return base_query

    query_parts = [base_query]

    if min_specs.get('ram', 0) >= 32:
        query_parts.append(f"{min_specs['ram']}GB RAM")
    elif min_specs.get('ram', 0) >= 16:
        query_parts.append("16GB+ RAM")

    if min_specs.get('storage', 0) >= 1024:
        tb = min_specs['storage'] // 1024
        query_parts.append(f"{tb}TB SSD")
    elif min_specs.get('storage', 0) >= 512:
        query_parts.append("512GB+ SSD")

    if min_specs.get('screen_size', 0) >= 17:
        query_parts.append('17"')
    elif min_specs.get('screen_size', 0) >= 15:
        query_parts.append('15.6"')

    resolution = min_specs.get('resolution', 'FHD')
    if resolution in ['4K UHD', 'QHD+', 'QHD']:
        query_parts.append(resolution.replace(' ', ''))

    return " ".join(query_parts)


# Common tech brands for extraction
_BRANDS = [
    'asus', 'acer', 'dell', 'hp', 'lenovo', 'msi', 'razer', 'samsung',
    'lg', 'apple', 'microsoft', 'corsair', 'g.skill', 'gskill', 'kingston',
    'crucial', 'teamgroup', 'team', 'patriot', 'pny', 'amd', 'intel',
    'nvidia', 'evga', 'gigabyte', 'sapphire', 'xfx', 'powercolor', 'zotac',
    'asrock', 'biostar', 'nzxt', 'cooler master', 'be quiet', 'thermaltake',
    'fractal', 'lian li', 'phanteks', 'seasonic', 'noctua', 'arctic',
    'western digital', 'wd', 'seagate', 'sabrent', 'silicon power',
]


def _extract_brand(name):
    """Extract brand from product name."""
    name_lower = name.lower()
    for brand in _BRANDS:
        if brand in name_lower:
            return brand.title()
    return None
