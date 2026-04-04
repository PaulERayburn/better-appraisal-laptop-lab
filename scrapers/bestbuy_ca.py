"""
Best Buy Canada direct scraper.

Uses Best Buy Canada's internal search API with curl_cffi for
TLS fingerprint impersonation. This catches listings that Google
Shopping doesn't index, including Marketplace sellers.
"""

import re
import json

from scrapers import make_product
from spec_parser import extract_specs, extract_ram_specs, categorize_product, extract_condition


BESTBUY_API_URL = "https://www.bestbuy.ca/api/v2/json/search"
BESTBUY_BASE_URL = "https://www.bestbuy.ca"

API_HEADERS = {
    "Accept": "application/json",
    "Referer": "https://www.bestbuy.ca/en-ca/search",
}


def search_products(query, category=None, max_results=48, page=1, sort_by="relevance"):
    """Search Best Buy Canada's API directly.

    Args:
        query: Search string (e.g., "Crucial 32GB DDR4 SODIMM")
        category: Product category hint for spec parsing
        max_results: Max products to return (API max per page is 48)
        page: Page number for pagination
        sort_by: "relevance" or "price"

    Returns:
        (products_list, error_string_or_None)
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        return None, "Best Buy Canada scraper requires curl_cffi. Install with: pip install curl_cffi"

    params = {
        "query": query,
        "lang": "en-CA",
        "currentRegion": "ON",
        "page": page,
        "pageSize": min(max_results, 48),
        "sortBy": sort_by,
        "sortDir": "asc" if sort_by == "price" else "desc",
    }

    try:
        response = cffi_requests.get(
            BESTBUY_API_URL,
            params=params,
            headers=API_HEADERS,
            impersonate="chrome",
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()

        raw_products = data.get("products", [])
        if not raw_products:
            return None, f"No products found on Best Buy Canada for '{query}'."

        products = []
        for item in raw_products[:max_results]:
            product = _parse_bestbuy_product(item, category)
            if product:
                products.append(product)

        return products, None

    except Exception as e:
        return None, f"Best Buy Canada search failed: {str(e)}"


def _parse_bestbuy_product(item, category_hint=None):
    """Parse a single product from the Best Buy Canada API response."""
    name = item.get("name", "")
    if not name:
        return None

    sku = str(item.get("sku", ""))
    sale_price = float(item.get("salePrice", 0) or 0)
    regular_price = float(item.get("regularPrice", 0) or 0)

    original_price = regular_price if regular_price > sale_price else None
    saving = (regular_price - sale_price) if regular_price > sale_price else 0

    product_url = item.get("productUrl", "")
    url = BESTBUY_BASE_URL + product_url if product_url else ""

    # Use shortDescription for richer spec parsing
    short_desc = item.get("shortDescription", "")
    parse_text = f"{name} {short_desc}"

    # Determine category
    bb_category = item.get("categoryName", "")
    if category_hint:
        product_category = category_hint
    elif "Memory (RAM)" in bb_category or "ddr" in name.lower():
        product_category = "ram"
    else:
        product_category = categorize_product(name)

    # Parse specs
    if product_category == "ram":
        specs = extract_ram_specs(parse_text)
        _enrich_ram_specs_from_description(specs, short_desc)
    else:
        specs = extract_specs(parse_text, product_category)

    condition = extract_condition(name)
    brand = _extract_brand_from_name(name)

    product = make_product(
        retailer="bestbuy_ca",
        retailer_sku=sku,
        name=name,
        url=url,
        category=product_category,
        price=sale_price,
        original_price=original_price,
        brand=brand,
        specs=specs,
    )
    product["source_display"] = "Best Buy Canada"
    product["saving"] = saving
    product["thumbnail"] = item.get("thumbnailImage", "")
    product["condition"] = condition

    seller = item.get("seller", {})
    if isinstance(seller, dict):
        product["seller"] = seller.get("name", "Best Buy")
        product["is_marketplace"] = item.get("isMarketplace", False)
    else:
        product["seller"] = "Best Buy"
        product["is_marketplace"] = False

    product["customer_rating"] = item.get("customerRating", 0)
    product["rating_count"] = item.get("customerRatingCount", 0)

    return product


def _enrich_ram_specs_from_description(specs, description):
    """Extract additional RAM specs from Best Buy's shortDescription."""
    if not description:
        return

    desc_lower = description.lower()

    if specs.get("form_factor", "Unknown") == "Unknown":
        if "sodimm" in desc_lower or "so-dimm" in desc_lower:
            specs["form_factor"] = "SO-DIMM"
        elif "dimm" in desc_lower and "so" not in desc_lower.split("dimm")[0][-4:]:
            specs["form_factor"] = "DIMM"

    if specs.get("cas_latency", 0) == 0:
        cl_match = re.search(r"CL(\d+)", description, re.IGNORECASE)
        if cl_match:
            specs["cas_latency"] = int(cl_match.group(1))

    if specs.get("voltage", 0) == 0:
        volt_match = re.search(r"(\d+\.\d+)\s*V", description)
        if volt_match:
            v = float(volt_match.group(1))
            if 0.9 <= v <= 1.6:
                specs["voltage"] = v

    if not specs.get("kit_config"):
        kit_match = re.search(r"(\d+)\s*x\s*(\d+)\s*GB", description, re.IGNORECASE)
        if kit_match:
            stick_count = int(kit_match.group(1))
            per_stick = int(kit_match.group(2))
            specs["kit_config"] = f"{stick_count}x{per_stick}GB"
            specs["stick_count"] = stick_count
            specs["per_stick_gb"] = per_stick
            specs["ram"] = stick_count * per_stick

    if specs.get("ram_speed_mhz", 0) == 0:
        speed_match = re.search(r"(\d{4,5})\s*MHz", description)
        if speed_match:
            specs["ram_speed_mhz"] = int(speed_match.group(1))

    if specs.get("ram_type", "Unknown") == "Unknown":
        ddr_match = re.search(r"(DDR[45])", description, re.IGNORECASE)
        if ddr_match:
            specs["ram_type"] = ddr_match.group(1).upper()


def _extract_brand_from_name(name):
    """Extract brand from the beginning of a Best Buy product name."""
    known_brands = [
        "crucial", "corsair", "kingston", "g.skill", "samsung", "sk hynix",
        "micron", "adata", "patriot", "pny", "teamgroup", "team group",
        "axiom", "owc", "dell", "hp", "lenovo", "asus", "msi",
    ]
    name_lower = name.lower()
    for brand in known_brands:
        if name_lower.startswith(brand):
            return brand.title().replace("G.skill", "G.Skill").replace("Sk Hynix", "SK Hynix")
    return None
