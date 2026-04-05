"""
Canada Tech Deal Tracker
========================
Track deals on laptops, desktops, RAM, and other tech components
across Canadian retailers. Features automated price monitoring,
customizable alerts, and email notifications.

Originally: Better Appraisal Laptop Lab / Best Buy Deal Finder
"""

import streamlit as st
import json
import re

from spec_parser import extract_specs, extract_condition, parse_size, categorize_product, RESOLUTION_RANK
from config import (
    SUPPORTED_CATEGORIES, SUPPORTED_RETAILERS, RETAILER_DISPLAY_NAMES,
    get_serpapi_key,
)
from database import Database
from scrapers import identify_retailer

# Page config
st.set_page_config(
    page_title="Canada Tech Deal Tracker",
    page_icon="🍁",
    layout="wide"
)

# Custom CSS for tabs
st.markdown("""
<style>
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        height: 60px; padding: 12px 24px; font-size: 1.2rem;
        font-weight: 600; border-radius: 8px 8px 0 0; background-color: #262730;
    }
    .stTabs [data-baseweb="tab"]:hover { background-color: #3d3d4d; }
    .stTabs [aria-selected="true"] {
        background-color: #d32f2f !important; color: white !important;
    }
    .stTabs [data-baseweb="tab-panel"] { padding-top: 20px; }
</style>
""", unsafe_allow_html=True)

# Initialize database
db = Database()


# ── Helper functions (kept from original for Best Buy CA parsing) ──

def extract_products_from_html(content):
    """Extract product data from Best Buy Canada saved HTML page."""
    state_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*\{', content)
    if state_match:
        start_pos = state_match.end() - 1
        brace_count = 0
        end_pos = start_pos

        for i, char in enumerate(content[start_pos:], start_pos):
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_pos = i + 1
                    break

        if end_pos > start_pos:
            json_str = content[start_pos:end_pos]
            try:
                data = json.loads(json_str)
                products = []

                if 'productList' in data and 'data' in data['productList']:
                    p_data = data['productList']['data']
                    if p_data:
                        products = p_data.get('products', p_data.get('results', []))

                if not products and 'search' in data:
                    search = data['search']
                    if 'searchResult' in search:
                        sr = search['searchResult']
                        products = sr.get('results', sr.get('products', []))
                    elif 'results' in search:
                        products = search['results']

                if products:
                    return products, None
            except json.JSONDecodeError:
                pass

    return None, "Could not find product data. Make sure you saved a Best Buy Canada product listing page."


def analyze_deals(products, current_specs, show_all=False, filter_incomplete=True):
    """Analyze products and compare against current specs."""
    base_url = "https://www.bestbuy.ca"
    deals = []
    skipped_incomplete = 0

    for p in products:
        name = p.get('name', '')
        price = p.get('priceWithoutEhf') or p.get('customerPrice') or p.get('price', 0)
        if isinstance(price, dict):
            price = price.get('customerPrice', 0)

        saving = p.get('saving', 0)
        sku = p.get('sku') or p.get('skuId', '')

        specs = extract_specs(name)
        condition = extract_condition(name)

        if filter_incomplete and specs['ram'] == 0:
            skipped_incomplete += 1
            continue

        seo_url = p.get('seoUrl', '')
        if seo_url and seo_url.startswith('http'):
            url = seo_url
        elif seo_url:
            url = base_url + seo_url
        else:
            url = f"{base_url}/en-ca/product/{sku}" if sku else "#"

        better_cpu = specs['cpu_gen'] > current_specs['cpu_gen']
        better_ram = specs['ram'] > current_specs['ram']
        better_storage = specs['storage'] >= current_specs['storage']
        bigger_screen = specs['screen_size'] > current_specs.get('screen_size', 0) if specs['screen_size'] > 0 else False

        current_res_rank = RESOLUTION_RANK.get(current_specs.get('resolution', 'FHD'), 3)
        product_res_rank = RESOLUTION_RANK.get(specs['resolution'], 0)
        better_resolution = product_res_rank > current_res_rank if product_res_rank > 0 else False

        notes = []
        if better_cpu:
            notes.append(f"CPU+ (Gen {specs['cpu_gen']})")
        if better_ram:
            notes.append(f"RAM+ ({specs['ram']}GB)")
        if better_storage:
            notes.append(f"Storage+ ({specs['storage']}GB)")
        elif specs['storage'] > 0 and specs['storage'] < current_specs['storage']:
            notes.append(f"Storage- ({specs['storage']}GB)")
        if bigger_screen:
            notes.append(f"Screen+ ({specs['screen_size']}\")")
        if better_resolution:
            notes.append(f"Res+ ({specs['resolution']})")

        score = 0
        if better_cpu: score += 2
        if better_ram: score += 2
        if better_storage: score += 1
        if bigger_screen: score += 1
        if better_resolution: score += 1
        if saving > 0: score += 1

        deal = {
            'name': name,
            'price': price,
            'saving': saving,
            'specs': specs,
            'condition': condition,
            'notes': notes,
            'score': score,
            'url': url,
            'sku': sku,
            'source': p.get('source', 'Best Buy Canada'),
            'is_upgrade': better_cpu or better_ram,
            'retailer': 'bestbuy_ca',
        }

        if show_all or deal['is_upgrade']:
            deals.append(deal)

    deals.sort(key=lambda x: (-x['score'], x['price']))
    return deals, skipped_incomplete


def analyze_search_deals(products, current_specs, min_specs=None, show_all=False):
    """Analyze products from SerpApi search with optional min spec filtering."""
    deals = []
    skipped = 0

    for p in products:
        name = p.get('name', '')
        price = p.get('price', 0)
        original_price = p.get('original_price')
        saving = p.get('saving', 0)
        url = p.get('url', '')
        source = p.get('source_display', '')
        retailer = p.get('retailer', 'unknown')
        sku = p.get('retailer_sku', '')

        category = p.get('category', 'laptop')
        specs = p.get('specs', extract_specs(name, category))
        condition = extract_condition(name)

        # Filter by min specs
        if min_specs and not show_all:
            min_ram = min_specs.get('ram', 0)
            # For RAM products, filter by detected capacity
            # If capacity can't be detected, exclude it (ambiguous listing)
            if category == 'ram' and min_ram > 0:
                detected_ram = specs.get('ram', 0)
                if detected_ram == 0 or detected_ram < min_ram:
                    skipped += 1
                    continue
            # For laptops/desktops, full spec filtering
            if category in ('laptop', 'desktop'):
                if specs.get('ram', 0) == 0:
                    skipped += 1
                    continue
                if specs.get('ram', 0) < min_ram:
                    skipped += 1
                    continue
                if specs.get('storage', 0) > 0 and specs['storage'] < min_specs.get('storage', 0):
                    skipped += 1
                    continue
                if specs.get('cpu_gen', 0) > 0 and specs['cpu_gen'] < min_specs.get('cpu_gen', 0):
                    skipped += 1
                    continue

        # Scoring depends on category
        notes = []
        score = 0
        is_upgrade = False

        if category in ('laptop', 'desktop'):
            # Laptop/desktop: compare against current specs
            better_cpu = specs.get('cpu_gen', 0) > current_specs.get('cpu_gen', 0) if specs.get('cpu_gen', 0) > 0 else False
            better_ram = specs.get('ram', 0) > current_specs.get('ram', 0)
            better_storage = specs.get('storage', 0) >= current_specs.get('storage', 0) if specs.get('storage', 0) > 0 else False

            if better_cpu:
                notes.append(f"CPU+ (Gen {specs['cpu_gen']})")
                score += 2
            if better_ram:
                notes.append(f"RAM+ ({specs['ram']}GB)")
                score += 2
            if better_storage:
                notes.append(f"Storage+ ({specs['storage']}GB)")
                score += 1
            if saving > 0:
                score += 1
            is_upgrade = better_cpu or better_ram or better_storage
        else:
            # Components (RAM, CPU, GPU, etc.): rank by best price
            # Score is inverted — lower price = better deal
            # We use a large base so sorting by -score still works
            if price > 0:
                score = 10000 - int(price)  # Lower price = higher score
            if saving > 0:
                discount_pct = (saving / (price + saving)) * 100 if (price + saving) > 0 else 0
                notes.append(f"{discount_pct:.0f}% off")

        deal = {
            'name': name,
            'price': price,
            'original_price': original_price,
            'saving': saving,
            'specs': specs,
            'condition': condition,
            'notes': notes,
            'score': score,
            'url': url,
            'sku': sku,
            'source': source,
            'retailer': retailer,
            'category': category,
            'is_upgrade': is_upgrade,
            'thumbnail': p.get('thumbnail', ''),
        }

        if show_all or is_upgrade or category not in ('laptop', 'desktop'):
            deals.append(deal)

    deals.sort(key=lambda x: (-x['score'], x['price']))
    return deals, skipped


def save_deal_to_db(deal):
    """Save a deal to the database and record its price."""
    from spec_parser import extract_specs as _extract_specs
    specs = deal.get('specs', {})

    product_dict = {
        'retailer': deal.get('retailer', 'unknown'),
        'retailer_sku': deal.get('sku', deal.get('name', '')[:50]),
        'name': deal['name'],
        'url': deal.get('url', '#'),
        'category': deal.get('category', categorize_product(deal['name'])),
        'brand': None,
        'cpu_model': specs.get('cpu_model'),
        'cpu_gen': specs.get('cpu_gen'),
        'ram_gb': specs.get('ram'),
        'storage_gb': specs.get('storage'),
        'gpu': specs.get('gpu'),
        'screen_size': specs.get('screen_size'),
        'resolution': specs.get('resolution'),
        'ram_type': specs.get('ram_type'),
        'ram_speed_mhz': specs.get('ram_speed_mhz'),
    }

    product_id = db.upsert_product(product_dict)
    db.record_price(product_id, deal['price'], deal.get('original_price'))
    return product_id


def get_demo_products():
    """Return sample Best Buy Canada product data for demo purposes."""
    return [
        {
            'name': 'Acer Nitro V 15.6" Gaming Laptop - Black (Intel Core i7-13620H/16GB RAM/512GB SSD/GeForce RTX 4050) - Open Box',
            'sku': '17976740',
            'seoUrl': '/en-ca/product/17976740',
            'priceWithoutEhf': 899.99,
            'saving': 400,
        },
        {
            'name': 'ASUS ROG Strix G16 16" Gaming Laptop (Intel Core i7-13650HX/16GB RAM/1TB SSD/GeForce RTX 4060)',
            'sku': '17542889',
            'seoUrl': '/en-ca/product/17542889',
            'priceWithoutEhf': 1599.99,
            'saving': 200,
        },
        {
            'name': 'Lenovo LOQ 15.6" Gaming Laptop - Grey (Intel Core i7-13620H/32GB RAM/512GB SSD/GeForce RTX 4060)',
            'sku': '17654321',
            'seoUrl': '/en-ca/product/17654321',
            'priceWithoutEhf': 1299.99,
            'saving': 300,
        },
        {
            'name': 'HP Victus 15.6" FHD Gaming Laptop (AMD Ryzen 7 7840HS/16GB RAM/512GB SSD/GeForce RTX 4060)',
            'sku': '17789012',
            'seoUrl': '/en-ca/product/17789012',
            'priceWithoutEhf': 1199.99,
            'saving': 150,
        },
        {
            'name': 'MSI Thin 15 15.6" FHD Gaming Laptop (Intel Core i5-12450H/8GB RAM/512GB SSD/GeForce RTX 4050)',
            'sku': '17890123',
            'seoUrl': '/en-ca/product/17890123',
            'priceWithoutEhf': 799.99,
            'saving': 100,
        },
        {
            'name': 'ASUS TUF Gaming A16 16" QHD Gaming Laptop (AMD Ryzen 9 7940HS/32GB RAM/1TB SSD/GeForce RTX 4070)',
            'sku': '17901234',
            'seoUrl': '/en-ca/product/17901234',
            'priceWithoutEhf': 1999.99,
            'saving': 500,
        },
        {
            'name': 'Acer Predator Helios Neo 16" Gaming Laptop (Intel Core i7-14700HX/16GB RAM/1TB SSD/GeForce RTX 4070)',
            'sku': '18012345',
            'seoUrl': '/en-ca/product/18012345',
            'priceWithoutEhf': 1899.99,
            'saving': 400,
        },
        {
            'name': 'Dell G15 15.6" FHD Gaming Laptop (Intel Core i7-13650HX/16GB RAM/512GB SSD/GeForce RTX 4050)',
            'sku': '17123456',
            'seoUrl': '/en-ca/product/17123456',
            'priceWithoutEhf': 999.99,
            'saving': 200,
        },
    ]


# ══════════════════════════════════════════════════════════════════
# Reusable RAM filter panel
# ══════════════════════════════════════════════════════════════════

def render_ram_filters(key_prefix):
    """Render the RAM filter panel with Must/Optional toggles.

    Args:
        key_prefix: Unique prefix for Streamlit widget keys (e.g., 'ca' or 'us')

    Returns:
        dict of filter_name -> (value, mode) tuples
    """
    st.markdown("### 🧠 RAM Filters")
    st.caption("Set each filter's value, then choose **Must** (hard requirement) or **Optional** (prefer but don't exclude)")

    ram_filters = {}

    def _filter_row(label, key, widget_fn):
        c_val, c_mode = st.columns([3, 1])
        with c_val:
            value = widget_fn()
        with c_mode:
            mode = st.selectbox("", options=["Must", "Optional", "Off"],
                                key=f"{key_prefix}_rf_mode_{key}", label_visibility="collapsed")
        return value, mode

    col_left, col_right = st.columns(2)

    with col_left:
        f_cap, f_cap_mode = _filter_row("Capacity", "cap",
            lambda: st.selectbox("Total Capacity",
                options=["Any", "8GB", "16GB", "32GB", "48GB", "64GB", "96GB", "128GB"],
                index=3, key=f"{key_prefix}_rf_cap", help="Total capacity (e.g., 2x16GB = 32GB total)"))
        ram_filters['capacity'] = (0 if f_cap == "Any" else int(f_cap.replace("GB", "")), f_cap_mode)

        f_kit, f_kit_mode = _filter_row("Kit Config", "kit",
            lambda: st.selectbox("Kit Configuration",
                options=["Any", "Single Stick (1x)", "2-Stick Kit (2x)", "4-Stick Kit (4x)"],
                key=f"{key_prefix}_rf_kit", help="Single stick for easy upgrade, kits for dual-channel"))
        ram_filters['kit_config'] = (f_kit, f_kit_mode)

        f_type, f_type_mode = _filter_row("DDR Type", "type",
            lambda: st.selectbox("DDR Type", options=["Any", "DDR4", "DDR5"], key=f"{key_prefix}_rf_type"))
        ram_filters['ddr_type'] = (f_type, f_type_mode)

        f_form, f_form_mode = _filter_row("Form Factor", "form",
            lambda: st.selectbox("Form Factor", options=["Any", "SO-DIMM (Laptop)", "DIMM (Desktop)"],
                                 key=f"{key_prefix}_rf_form"))
        ram_filters['form_factor'] = (f_form, f_form_mode)

    with col_right:
        brand_options = ["Any", "ADATA", "Corsair", "Crucial", "G.Skill", "HP",
                         "Kingston", "Micron", "Mushkin", "Patriot", "PNY",
                         "Samsung", "SK Hynix", "TeamGroup"]
        f_brand, f_brand_mode = _filter_row("Brand", "brand",
            lambda: st.selectbox("Brand", options=brand_options, key=f"{key_prefix}_rf_brand"))
        ram_filters['brand'] = (f_brand, f_brand_mode)

        speed_options = ["Any", "2133", "2400", "2666", "3000", "3200", "3600",
                         "4000", "4800", "5200", "5600", "6000", "6400", "7200", "8000"]
        f_speed, f_speed_mode = _filter_row("Min Speed", "speed",
            lambda: st.selectbox("Min Speed (MHz)", options=speed_options, key=f"{key_prefix}_rf_speed",
                help="DDR4: typically 2133-3600 | DDR5: typically 4800-8000"))
        ram_filters['min_speed'] = (0 if f_speed == "Any" else int(f_speed), f_speed_mode)

        cl_options = ["Any", "14", "15", "16", "18", "19", "22",
                      "28", "30", "32", "34", "36", "38", "40"]
        f_cl, f_cl_mode = _filter_row("Max CAS Latency", "cl",
            lambda: st.selectbox("Max CAS Latency (CL)", options=cl_options, key=f"{key_prefix}_rf_cl",
                help="Lower = faster. DDR4: CL14-22 | DDR5: CL28-40"))
        ram_filters['max_cl'] = (0 if f_cl == "Any" else int(f_cl), f_cl_mode)

        f_price, f_price_mode = _filter_row("Max Price", "price",
            lambda: st.number_input("Max Price", min_value=0.0, max_value=5000.0, value=0.0,
                                    step=25.0, key=f"{key_prefix}_rf_price", help="0 = no limit"))
        ram_filters['max_price'] = (f_price, f_price_mode)

    return ram_filters


def build_ram_query_from_filters(base_query, ram_filters):
    """Auto-build a search query string from RAM filter values."""
    query_parts = []
    if base_query.strip().lower() not in ('ram', 'memory', 'ddr4', 'ddr5', ''):
        query_parts.append(base_query.strip())

    cap_val, cap_mode = ram_filters.get('capacity', (0, 'Off'))
    if cap_val > 0 and cap_mode != 'Off':
        query_parts.append(f"{cap_val}GB")
    type_val, type_mode = ram_filters.get('ddr_type', ('Any', 'Off'))
    if type_val != 'Any' and type_mode != 'Off':
        query_parts.append(type_val)
    speed_val, speed_mode = ram_filters.get('min_speed', (0, 'Off'))
    if speed_val > 0 and speed_mode != 'Off':
        query_parts.append(f"{speed_val}MHz")
    form_val, form_mode = ram_filters.get('form_factor', ('Any', 'Off'))
    if form_val != 'Any' and form_mode != 'Off':
        query_parts.append("SODIMM" if "SO-DIMM" in form_val else "DIMM desktop")
    brand_val, brand_mode = ram_filters.get('brand', ('Any', 'Off'))
    if brand_val != 'Any' and brand_mode != 'Off':
        query_parts.append(brand_val)
    kit_val, kit_mode = ram_filters.get('kit_config', ('Any', 'Off'))
    if kit_val != 'Any' and kit_mode != 'Off':
        if 'Single' in kit_val:
            query_parts.append("1x single stick")
    if not query_parts:
        query_parts.append("RAM memory")
    return " ".join(query_parts)


def _build_alert_from_ram_filters(ram_filters, search_query=''):
    """Build an alert dict from the current RAM filter panel values."""
    cap_val, cap_mode = ram_filters.get('capacity', (0, 'Off'))
    type_val, type_mode = ram_filters.get('ddr_type', ('Any', 'Off'))
    brand_val, brand_mode = ram_filters.get('brand', ('Any', 'Off'))
    speed_val, speed_mode = ram_filters.get('min_speed', (0, 'Off'))
    price_val, price_mode = ram_filters.get('max_price', (0, 'Off'))
    form_val, form_mode = ram_filters.get('form_factor', ('Any', 'Off'))
    kit_val, kit_mode = ram_filters.get('kit_config', ('Any', 'Off'))
    cl_val, cl_mode = ram_filters.get('max_cl', (0, 'Off'))

    # Build a descriptive name from active filters
    name_parts = []
    if brand_val != 'Any' and brand_mode != 'Off':
        name_parts.append(brand_val)
    if cap_val > 0 and cap_mode != 'Off':
        name_parts.append(f"{cap_val}GB")
    if type_val != 'Any' and type_mode != 'Off':
        name_parts.append(type_val)
    if form_val != 'Any' and form_mode != 'Off':
        ff = 'SO-DIMM' if 'SO-DIMM' in form_val else 'DIMM'
        name_parts.append(ff)
    if speed_val > 0 and speed_mode != 'Off':
        name_parts.append(f"{speed_val}MHz")
    if price_val > 0 and price_mode != 'Off':
        name_parts.append(f"under ${price_val:.0f}")
    name = " ".join(name_parts) if name_parts else f"RAM: {search_query[:30]}"

    # Map form factor display value to stored value
    form_factor = None
    if form_val != 'Any' and form_mode != 'Off':
        form_factor = 'SO-DIMM' if 'SO-DIMM' in form_val else 'DIMM'

    # Map kit config display value to stored value
    kit_config = None
    if kit_val != 'Any' and kit_mode != 'Off':
        if 'Single' in kit_val:
            kit_config = '1x'
        elif '2-Stick' in kit_val:
            kit_config = '2x'
        elif '4-Stick' in kit_val:
            kit_config = '4x'

    return {
        'name': name,
        'category': 'ram',
        'keyword': search_query.strip() if search_query.strip().lower() not in ('ram', 'memory', '') else None,
        'max_price': price_val if price_val > 0 and price_mode != 'Off' else None,
        'min_ram_gb': cap_val if cap_val > 0 and cap_mode != 'Off' else None,
        'ram_type': type_val if type_val != 'Any' and type_mode != 'Off' else None,
        'form_factor': form_factor,
        'kit_config': kit_config,
        'min_speed_mhz': speed_val if speed_val > 0 and speed_mode != 'Off' else None,
        'max_cas_latency': cl_val if cl_val > 0 and cl_mode != 'Off' else None,
        'brand': brand_val if brand_val != 'Any' and brand_mode != 'Off' else None,
        'cooldown_hours': 24,
    }


# ══════════════════════════════════════════════════════════════════
# Product deduplication
# ══════════════════════════════════════════════════════════════════

def _deduplicate_products(products):
    """Remove duplicate products across sources, keeping the cheapest."""
    seen = {}
    for p in products:
        # Create a dedup key from normalized product identifiers
        sku = p.get('retailer_sku', '')
        name = p.get('name', '').lower().strip()
        # Normalize: remove common filler words and extra spaces
        name_key = re.sub(r'[^a-z0-9]', '', name)[:60]
        price = p.get('price', 0)

        key = name_key
        if key in seen:
            # Keep the cheaper one
            if price < seen[key].get('price', float('inf')):
                seen[key] = p
        else:
            seen[key] = p
    return list(seen.values())


# ══════════════════════════════════════════════════════════════════
# RAM filter & display helpers
# ══════════════════════════════════════════════════════════════════

def _apply_ram_filters(products, ram_filters):
    """Apply must/optional RAM filters to products.

    Returns (filtered_products, optional_scores_dict, skipped_count).
    - Must filters: exclude non-matching products
    - Optional filters: boost score for matching products
    """
    filtered = []
    optional_scores = {}
    skipped = 0

    for p in products:
        specs = p.get('specs', {})
        passed = True

        # --- Must filters ---
        # Capacity
        cap_val, cap_mode = ram_filters.get('capacity', (0, 'Off'))
        if cap_mode == 'Must' and cap_val > 0:
            detected = specs.get('ram', 0)
            if detected == 0 or detected != cap_val:
                passed = False

        # DDR Type
        type_val, type_mode = ram_filters.get('ddr_type', ('Any', 'Off'))
        if type_mode == 'Must' and type_val != 'Any':
            detected = specs.get('ram_type', 'Unknown')
            if detected == 'Unknown' or detected != type_val:
                passed = False

        # Form Factor — when Must, exclude unknowns too
        form_val, form_mode = ram_filters.get('form_factor', ('Any', 'Off'))
        if form_mode == 'Must' and form_val != 'Any':
            target_ff = 'SO-DIMM' if 'SO-DIMM' in form_val else 'DIMM'
            detected = specs.get('form_factor', 'Unknown')
            if detected != target_ff:
                passed = False

        # Kit Config
        kit_val, kit_mode = ram_filters.get('kit_config', ('Any', 'Off'))
        if kit_mode == 'Must' and kit_val != 'Any':
            detected_sticks = specs.get('stick_count', 0)
            if detected_sticks > 0:
                if 'Single' in kit_val and detected_sticks != 1:
                    passed = False
                elif '2-Stick' in kit_val and detected_sticks != 2:
                    passed = False
                elif '4-Stick' in kit_val and detected_sticks != 4:
                    passed = False

        # Brand
        brand_val, brand_mode = ram_filters.get('brand', ('Any', 'Off'))
        if brand_mode == 'Must' and brand_val != 'Any':
            detected = specs.get('brand', '')
            if detected and detected.lower() != brand_val.lower():
                passed = False

        # Min Speed
        speed_val, speed_mode = ram_filters.get('min_speed', (0, 'Off'))
        if speed_mode == 'Must' and speed_val > 0:
            detected = specs.get('ram_speed_mhz', 0)
            if detected > 0 and detected < speed_val:
                passed = False

        # Max CAS Latency
        cl_val, cl_mode = ram_filters.get('max_cl', (0, 'Off'))
        if cl_mode == 'Must' and cl_val > 0:
            detected = specs.get('cas_latency', 0)
            if detected > 0 and detected > cl_val:
                passed = False

        # Max Price
        price_val, price_mode = ram_filters.get('max_price', (0, 'Off'))
        if price_mode == 'Must' and price_val > 0:
            if p.get('price', 0) > price_val:
                passed = False

        if not passed:
            skipped += 1
            continue

        # --- Optional scoring ---
        opt_score = 0

        if cap_mode == 'Optional' and cap_val > 0:
            if specs.get('ram', 0) == cap_val:
                opt_score += 3

        if type_mode == 'Optional' and type_val != 'Any':
            if specs.get('ram_type', '') == type_val:
                opt_score += 2

        if form_mode == 'Optional' and form_val != 'Any':
            target_ff = 'SO-DIMM' if 'SO-DIMM' in form_val else 'DIMM'
            if specs.get('form_factor', '') == target_ff:
                opt_score += 2

        if kit_mode == 'Optional' and kit_val != 'Any':
            detected_sticks = specs.get('stick_count', 0)
            if detected_sticks > 0:
                if ('Single' in kit_val and detected_sticks == 1) or \
                   ('2-Stick' in kit_val and detected_sticks == 2) or \
                   ('4-Stick' in kit_val and detected_sticks == 4):
                    opt_score += 1

        if brand_mode == 'Optional' and brand_val != 'Any':
            if specs.get('brand', '').lower() == brand_val.lower():
                opt_score += 1

        if speed_mode == 'Optional' and speed_val > 0:
            if specs.get('ram_speed_mhz', 0) >= speed_val:
                opt_score += 1

        if cl_mode == 'Optional' and cl_val > 0:
            detected_cl = specs.get('cas_latency', 0)
            if 0 < detected_cl <= cl_val:
                opt_score += 1

        if price_mode == 'Optional' and price_val > 0:
            if p.get('price', 0) <= price_val:
                opt_score += 2

        filtered.append(p)
        optional_scores[id(p)] = opt_score

    return filtered, optional_scores, skipped


def _display_ram_specs_compact(specs):
    """Show RAM specs in compact format for Top Deals cards."""
    parts = []
    # Capacity with kit info
    if specs.get('ram', 0) > 0:
        cap_str = f"{specs['ram']}GB"
        if specs.get('kit_config'):
            cap_str += f" ({specs['kit_config']})"
        parts.append(cap_str)
    if specs.get('ram_type', 'Unknown') != 'Unknown':
        type_str = specs['ram_type']
        if specs.get('ram_speed_mhz', 0) > 0:
            type_str += f"-{specs['ram_speed_mhz']}"
        parts.append(type_str)
    if specs.get('cas_latency', 0) > 0:
        parts.append(f"CL{specs['cas_latency']}")
    if specs.get('form_factor', 'Unknown') != 'Unknown':
        parts.append(specs['form_factor'])
    if specs.get('brand'):
        parts.append(specs['brand'])
    if parts:
        st.markdown(f"🔧 {' | '.join(parts)}")


def _display_ram_specs_full(specs):
    """Show all RAM specs in expander detail view."""
    if specs.get('brand'):
        st.markdown(f"**Brand:** {specs['brand']}")
    if specs.get('ram', 0) > 0:
        cap_str = f"{specs['ram']}GB"
        if specs.get('kit_config'):
            cap_str += f" ({specs['kit_config']})"
        elif specs.get('stick_count', 0) == 1:
            cap_str += " (Single Stick)"
        st.markdown(f"**Capacity:** {cap_str}")
    if specs.get('ram_type', 'Unknown') != 'Unknown':
        type_str = specs['ram_type']
        if specs.get('ram_speed_mhz', 0) > 0:
            type_str += f"-{specs['ram_speed_mhz']}"
        st.markdown(f"**Type:** {type_str}")
    if specs.get('form_factor', 'Unknown') != 'Unknown':
        st.markdown(f"**Form Factor:** {specs['form_factor']}")
    if specs.get('cas_latency', 0) > 0:
        st.markdown(f"**CAS Latency:** CL{specs['cas_latency']}")
    if specs.get('voltage', 0) > 0:
        st.markdown(f"**Voltage:** {specs['voltage']}V")


# ══════════════════════════════════════════════════════════════════
# MAIN APP
# ══════════════════════════════════════════════════════════════════

st.title("🍁 Tech Deal Tracker")
st.markdown("*Track deals on laptops, desktops, RAM, and tech components across Canadian and US retailers.*")
st.caption("v2.1.0 | Previously: Better Appraisal Laptop Lab")

# Sidebar
with st.sidebar:
    st.header("📋 How to Use")
    st.markdown("""
    **Search Canada:** Search Canadian retailers. Toggle to include US deals with shipping estimates.

    **Search USA:** Search US retailers for local US shopping.

    **Upload HTML:** Upload a saved Best Buy Canada page for analysis.

    **Tracked / Alerts / Settings:** Track products, set alerts, configure email.
    """)
    st.markdown("---")
    tracked_count = len(db.get_tracked_products())
    alert_count = len(db.get_alerts())
    st.metric("Tracked Products", tracked_count)
    st.metric("Active Alerts", alert_count)
    st.markdown("---")
    st.markdown("Made with ❤️ | [GitHub](https://github.com/PaulERayburn/better-appraisal-laptop-lab)")

# Session state init
for key in ['deals', 'current_specs', 'analyzed', 'search_deals']:
    if key not in st.session_state:
        st.session_state[key] = None if key != 'analyzed' else False

# ── Tabs ──
tab_search_ca, tab_search_us, tab_upload, tab_tracked, tab_alerts, tab_settings = st.tabs([
    "🇨🇦 Search Canada",
    "🇺🇸 Search USA",
    "📁 Upload HTML",
    "📦 Tracked Products",
    "🔔 Alerts",
    "⚙️ Settings",
])


# ═══════════════════════════════════════════
# TAB 1: Search Canada (SerpApi + Best Buy CA)
# ═══════════════════════════════════════════
with tab_search_ca:
    st.subheader("Search Canadian Retailers")

    col_query, col_cat = st.columns([3, 1])
    with col_query:
        search_query = st.text_input(
            "Search for tech deals",
            value="gaming laptop",
            placeholder="e.g., DDR5 RAM 32GB, RTX 4070, gaming laptop"
        )
    with col_cat:
        search_category = st.selectbox(
            "Category",
            options=['auto-detect'] + SUPPORTED_CATEGORIES,
            index=0,
            help="Auto-detect guesses from the product name"
        )

    # ── Category-specific filter panels ──
    ram_filters = {}
    general_filters = {}
    is_ram_search = search_category == 'ram'

    if is_ram_search:
        ram_filters = render_ram_filters("ca")
    else:
        # General filters for laptops/desktops/other
        col_current, col_minimum = st.columns(2)
        with col_current:
            st.markdown("**Your Current Specs** (for upgrade comparison)")
            current_ram_search = st.number_input("Your RAM (GB)", min_value=4, max_value=128, value=16, key="s_ram")
            current_storage_search = st.number_input("Your Storage (GB)", min_value=128, max_value=8000, value=512, key="s_storage")
            current_cpu_search = st.number_input("Your CPU Gen", min_value=1, max_value=20, value=10, key="s_cpu")
        with col_minimum:
            st.markdown("**Minimum Requirements** (filter results)")
            min_ram = st.number_input("Min RAM (GB)", min_value=0, max_value=128, value=16, key="s_min_ram")
            min_storage = st.number_input("Min Storage (GB)", min_value=0, max_value=8000, value=256, key="s_min_storage")
            min_cpu = st.number_input("Min CPU Gen", min_value=0, max_value=20, value=0, key="s_min_cpu")

    col_opts1, col_opts2, col_opts3 = st.columns(3)
    with col_opts1:
        search_show_all = st.checkbox("Show all results (skip filtering)", key="s_show_all")
    with col_opts2:
        include_us = st.checkbox("🇺🇸 Include US deals (with est. shipping)", key="s_include_us")
    with col_opts3:
        trusted_only = st.checkbox("🛡️ Trusted retailers only", value=True, key="s_trusted")
    search_button = st.button("🔍 Search Canada", type="primary")

    if search_button:
        api_key = get_serpapi_key(db)
        if not api_key:
            st.error("SerpApi key not configured. Go to the Settings tab to add it.")
        else:
            if is_ram_search:
                current_specs_search = {'cpu_gen': 0, 'ram': 0, 'storage': 0}
                min_specs = {'ram': 0, 'storage': 0, 'cpu_gen': 0}
                st.session_state['ram_filters'] = ram_filters
                search_query = build_ram_query_from_filters(search_query, ram_filters)
            else:
                current_specs_search = {
                    'cpu_gen': current_cpu_search,
                    'ram': current_ram_search,
                    'storage': current_storage_search,
                }
                min_specs = {
                    'cpu_gen': min_cpu,
                    'ram': min_ram,
                    'storage': min_storage,
                }

            from scrapers.serpapi_shopping import search_products as serpapi_search, build_search_query
            from scrapers.bestbuy_ca import search_products as bestbuy_search
            if is_ram_search:
                enhanced_query = search_query  # Already built from filters above
            else:
                enhanced_query = build_search_query(search_query, min_specs if not search_show_all else None)
            st.info(f"Searching: **{enhanced_query}**")

            cat = None if search_category == 'auto-detect' else search_category

            with st.spinner("Searching Canadian retailers..."):
                # Search both SerpApi (Google Shopping) and Best Buy Canada directly
                products = []
                sources_searched = []

                # Best Buy Canada API (always available, no API key needed)
                bb_products, bb_error = bestbuy_search(enhanced_query, category=cat)
                if bb_products:
                    products.extend(bb_products)
                    sources_searched.append(f"Best Buy CA ({len(bb_products)})")
                elif bb_error:
                    st.warning(f"Best Buy CA: {bb_error}")

                # SerpApi Google Shopping (requires API key)
                if api_key:
                    serp_products, serp_error = serpapi_search(enhanced_query, category=cat, api_key=api_key)
                    if serp_products:
                        products.extend(serp_products)
                        sources_searched.append(f"Google Shopping ({len(serp_products)})")
                    elif serp_error:
                        st.warning(f"Google Shopping: {serp_error}")

                # US products (if cross-border toggle is on)
                if include_us and api_key:
                    us_products, us_error = serpapi_search(enhanced_query, category=cat, api_key=api_key, country='us')
                    if us_products:
                        # Tag US products for cross-border display
                        from cross_border import get_usd_to_cad_rate, estimate_cad_total, ships_to_canada
                        rate = get_usd_to_cad_rate()
                        for p in us_products:
                            p['country'] = 'us'
                            p_cat = p.get('category', cat or 'other')
                            p['cross_border'] = estimate_cad_total(p.get('price', 0), p_cat, rate)
                            p['ships_to_canada'] = ships_to_canada(p.get('source_display', ''))
                        products.extend(us_products)
                        sources_searched.append(f"Google Shopping US ({len(us_products)})")
                    elif us_error:
                        st.warning(f"Google Shopping US: {us_error}")

                # Deduplicate by name similarity (same product from multiple sources)
                products = _deduplicate_products(products)

                # Tag trust status and optionally filter
                from scrapers import is_trusted_retailer
                for p in products:
                    p['trust'] = is_trusted_retailer(p.get('source_display', ''))
                if trusted_only:
                    before = len(products)
                    products = [p for p in products if p.get('trust') != 'suspicious']
                    filtered_untrusted = before - len(products)
                    if filtered_untrusted > 0:
                        st.caption(f"🛡️ {filtered_untrusted} suspicious seller(s) excluded")

                if sources_searched:
                    st.caption(f"Sources: {' + '.join(sources_searched)}")

            if not products:
                st.error("No products found from any source.")
            else:
                if is_ram_search and not search_show_all:
                    # Apply RAM-specific must/optional filtering
                    filtered, optional_scores, skipped = _apply_ram_filters(products, ram_filters)
                    # Sort by optional score (desc), then price (asc)
                    filtered.sort(key=lambda x: (-optional_scores.get(id(x), 0), x.get('price', 0)))
                    # Convert to deal format
                    search_deals = []
                    for p in filtered:
                        specs = p.get('specs', {})
                        saving = p.get('saving', 0)
                        deal = {
                            'name': p.get('name', ''), 'price': p.get('price', 0),
                            'original_price': p.get('original_price'),
                            'saving': saving, 'specs': specs,
                            'condition': extract_condition(p.get('name', '')),
                            'notes': [], 'score': optional_scores.get(id(p), 0),
                            'url': p.get('url', ''), 'sku': p.get('retailer_sku', ''),
                            'source': p.get('source_display', ''),
                            'retailer': p.get('retailer', 'unknown'),
                            'category': 'ram', 'is_upgrade': False,
                            'thumbnail': p.get('thumbnail', ''),
                            'country': p.get('country', 'ca'),
                            'cross_border': p.get('cross_border'),
                            'ships_to_canada': p.get('ships_to_canada'),
                            'trust': p.get('trust', 'unknown'),
                        }
                        if saving > 0:
                            dpct = (saving / (p['price'] + saving)) * 100 if (p['price'] + saving) > 0 else 0
                            deal['notes'].append(f"{dpct:.0f}% off")
                        search_deals.append(deal)
                    st.session_state['search_deals'] = search_deals
                    st.session_state['search_skipped'] = skipped
                else:
                    search_deals, skipped = analyze_search_deals(
                        products, current_specs_search,
                        min_specs if not search_show_all else None,
                        search_show_all
                    )
                    st.session_state['search_deals'] = search_deals
                    st.session_state['search_skipped'] = skipped
                st.session_state['search_current'] = current_specs_search

    # Display search results
    if st.session_state.get('search_deals'):
        search_deals = st.session_state['search_deals']
        skipped = st.session_state.get('search_skipped', 0)

        msg = f"Found {len(search_deals)} products"
        if skipped > 0:
            msg += f" ({skipped} filtered out)"
        st.success(msg)

        if search_deals:
            # Top 3
            st.markdown("---")
            st.header("🏆 Top Deals")
            top_n = min(3, len(search_deals))
            cols = st.columns(top_n)
            medals = ["🥇", "🥈", "🥉"]

            for i, (col, deal) in enumerate(zip(cols, search_deals[:top_n])):
                with col:
                    st.markdown(f"### {medals[i]} #{i+1}")
                    source = deal.get('source', '')
                    is_us = deal.get('country') == 'us'
                    trust = deal.get('trust', 'unknown')
                    trust_icon = {'trusted': '🛡️', 'suspicious': '⚠️', 'unknown': ''}.get(trust, '')
                    if source:
                        flag = " 🇺🇸" if is_us else ""
                        st.markdown(f"🏪 **{source}**{flag} {trust_icon}")
                    condition = deal.get('condition', 'New')
                    if condition != 'New':
                        st.markdown(f"🏷️ **{condition}**")
                    st.markdown(f"**{deal['name'][:55]}...**")

                    # Price display — cross-border vs local
                    if is_us and deal.get('cross_border'):
                        cb = deal['cross_border']
                        st.markdown(f"💰 **${deal['price']:,.2f} USD** (~${cb['cad_price']:,.0f} CAD)")
                        st.caption(f"Est. shipped: ${cb['cad_total_low']:,.0f}-${cb['cad_total_high']:,.0f} CAD")
                        ship_status = deal.get('ships_to_canada', 'Unknown')
                        ship_icon = {'Likely': '🟢', 'Unlikely': '🔴', 'Unknown': '🟡'}.get(ship_status, '⚪')
                        st.markdown(f"📦 {ship_icon} Ships to Canada: **{ship_status}**")
                    else:
                        st.markdown(f"💰 **${deal['price']:,.2f}**")
                        if deal.get('saving', 0) > 0:
                            st.markdown(f"🏷️ Save ${deal['saving']:.0f}")

                    cat = deal.get('category', 'laptop')
                    specs = deal.get('specs', {})
                    if cat in ('laptop', 'desktop'):
                        if specs.get('cpu_gen', 0) > 0:
                            st.markdown(f"🔧 CPU Gen {specs['cpu_gen']} | {specs.get('ram', '?')}GB RAM")
                    elif cat == 'ram':
                        _display_ram_specs_compact(specs)

                    if deal.get('url'):
                        st.link_button("View Deal", deal['url'])

                    if st.button(f"💾 Track", key=f"save_search_{i}"):
                        save_deal_to_db(deal)
                        st.success("Saved!")

            # Create alert from current search
            st.markdown("---")
            if is_ram_search and ram_filters:
                if st.button("🔔 Create Alert from This Search", key="ca_alert_from_search"):
                    alert_dict = _build_alert_from_ram_filters(ram_filters, search_query)
                    aid = db.create_alert(alert_dict)
                    st.success(f"Alert '{alert_dict['name']}' created! Go to the Alerts tab to manage it.")
            else:
                if st.button("🔔 Create Alert from This Search", key="ca_alert_from_search_gen"):
                    alert_dict = {
                        'name': f"Search: {search_query[:40]}",
                        'category': search_category if search_category != 'auto-detect' else 'other',
                        'keyword': search_query,
                        'max_price': None,
                        'min_ram_gb': min_ram if not is_ram_search else None,
                        'min_storage_gb': min_storage if not is_ram_search else None,
                        'min_cpu_gen': min_cpu if not is_ram_search else None,
                        'cooldown_hours': 24,
                    }
                    db.create_alert(alert_dict)
                    st.success(f"Alert '{alert_dict['name']}' created! Go to the Alerts tab to manage it.")

            # All results
            st.markdown("---")
            st.header(f"📊 All Results ({len(search_deals)})")
            for i, deal in enumerate(search_deals):
                source = deal.get('source', '')
                condition = deal.get('condition', 'New')
                is_us = deal.get('country') == 'us'
                flag = " 🇺🇸" if is_us else ""
                source_badge = f" @ {source}{flag}" if source else flag
                condition_badge = "" if condition == "New" else f" [{condition}]"
                price_str = f"${deal['price']:,.2f}" + (" USD" if is_us else "")
                with st.expander(f"**{i+1}. {deal['name'][:60]}...**{condition_badge}{source_badge} — {price_str}"):
                    if source:
                        st.markdown(f"**Store:** {source}{flag}")

                    # Cross-border info
                    if is_us and deal.get('cross_border'):
                        cb = deal['cross_border']
                        st.markdown(f"**Price:** ${deal['price']:,.2f} USD (~${cb['cad_price']:,.2f} CAD @ {cb['exchange_rate']:.4f})")
                        st.markdown(f"**Est. shipping:** ${cb['shipping_usd_low']}-${cb['shipping_usd_high']} USD")
                        st.markdown(f"**Est. CAD total:** ${cb['cad_total_low']:,.2f} - ${cb['cad_total_high']:,.2f}")
                        ship_status = deal.get('ships_to_canada', 'Unknown')
                        ship_icon = {'Likely': '🟢', 'Unlikely': '🔴', 'Unknown': '🟡'}.get(ship_status, '⚪')
                        st.markdown(f"**Ships to Canada:** {ship_icon} {ship_status}")

                    cat = deal.get('category', 'laptop')
                    specs = deal.get('specs', {})
                    if cat in ('laptop', 'desktop'):
                        st.markdown(f"**CPU:** {specs.get('cpu_model', '?')} (Gen {specs.get('cpu_gen', '?')})")
                        st.markdown(f"**RAM:** {specs.get('ram', '?')}GB | **Storage:** {specs.get('storage', '?')}GB")
                        st.markdown(f"**GPU:** {specs.get('gpu', 'Integrated')}")
                    elif cat == 'ram':
                        _display_ram_specs_full(specs)
                    elif cat == 'cpu':
                        st.markdown(f"**Model:** {specs.get('cpu_model', '?')}")
                        if specs.get('core_count', 0) > 0:
                            st.markdown(f"**Cores:** {specs['core_count']}")
                    elif cat == 'gpu':
                        st.markdown(f"**GPU:** {specs.get('gpu', '?')}")
                        if specs.get('vram_gb', 0) > 0:
                            st.markdown(f"**VRAM:** {specs['vram_gb']}GB")

                    if deal.get('notes'):
                        st.markdown(f"**{', '.join(deal['notes'])}**")

                    col_link, col_save = st.columns([1, 1])
                    with col_link:
                        if deal.get('url'):
                            st.link_button("🔗 View Deal", deal['url'])
                    with col_save:
                        if st.button(f"💾 Track This Product", key=f"save_all_{i}"):
                            save_deal_to_db(deal)
                            st.success("Saved to tracked products!")


# ═══════════════════════════════════════════
# TAB 2: Search USA
# ═══════════════════════════════════════════
with tab_search_us:
    st.subheader("🇺🇸 Search US Retailers")
    st.caption("For US-based shopping. Prices in USD.")

    us_query = st.text_input("Search for tech deals", value="DDR4 32GB", key="us_query",
                             placeholder="e.g., DDR5 RAM 32GB, RTX 4070, gaming laptop")
    us_category = st.selectbox("Category", options=['auto-detect'] + SUPPORTED_CATEGORIES,
                               index=0, key="us_cat")

    # Show RAM filters when category is ram
    us_ram_filters = {}
    us_is_ram = us_category == 'ram'
    if us_is_ram:
        us_ram_filters = render_ram_filters("us")
    else:
        col_us_cur, col_us_min = st.columns(2)
        with col_us_cur:
            st.markdown("**Your Current Specs** (for upgrade comparison)")
            us_cur_ram = st.number_input("Your RAM (GB)", min_value=4, max_value=128, value=16, key="us_cur_ram")
            us_cur_storage = st.number_input("Your Storage (GB)", min_value=128, max_value=8000, value=512, key="us_cur_storage")
            us_cur_cpu = st.number_input("Your CPU Gen", min_value=1, max_value=20, value=10, key="us_cur_cpu")
        with col_us_min:
            st.markdown("**Minimum Requirements** (filter results)")
            us_min_ram = st.number_input("Min RAM (GB)", min_value=0, max_value=128, value=16, key="us_min_ram")
            us_min_storage = st.number_input("Min Storage (GB)", min_value=0, max_value=8000, value=256, key="us_min_storage")
            us_min_cpu = st.number_input("Min CPU Gen", min_value=0, max_value=20, value=0, key="us_min_cpu")

    us_col1, us_col2 = st.columns(2)
    with us_col1:
        us_show_all = st.checkbox("Show all results (skip filtering)", key="us_show_all")
    with us_col2:
        us_trusted_only = st.checkbox("🛡️ Trusted retailers only", value=True, key="us_trusted")
    us_search_btn = st.button("🔍 Search USA", type="primary", key="us_search_btn")

    if us_search_btn:
        api_key = get_serpapi_key(db)
        if not api_key:
            st.error("SerpApi key not configured. Go to the Settings tab to add it.")
        else:
            from scrapers.serpapi_shopping import search_products as serpapi_search

            if us_is_ram:
                us_search_q = build_ram_query_from_filters(us_query, us_ram_filters)
            else:
                from scrapers.serpapi_shopping import build_search_query
                us_min_specs = {'cpu_gen': us_min_cpu, 'ram': us_min_ram, 'storage': us_min_storage}
                us_search_q = build_search_query(us_query, us_min_specs if not us_show_all else None)

            st.info(f"Searching: **{us_search_q}**")
            us_cat = None if us_category == 'auto-detect' else us_category

            with st.spinner("Searching US retailers..."):
                us_products, us_error = serpapi_search(us_search_q, category=us_cat, api_key=api_key, country='us')

            if us_error:
                st.error(us_error)
            elif us_products:
                # Tag trust status and filter
                from scrapers import is_trusted_retailer
                for p in us_products:
                    p['trust'] = is_trusted_retailer(p.get('source_display', ''))
                if us_trusted_only:
                    before = len(us_products)
                    us_products = [p for p in us_products if p.get('trust') != 'suspicious']
                    removed = before - len(us_products)
                    if removed > 0:
                        st.caption(f"🛡️ {removed} suspicious seller(s) excluded")

                if us_is_ram and not us_show_all:
                    filtered, opt_scores, skipped = _apply_ram_filters(us_products, us_ram_filters)
                    filtered.sort(key=lambda x: (-opt_scores.get(id(x), 0), x.get('price', 0)))
                    us_deals = []
                    for p in filtered:
                        specs = p.get('specs', {})
                        saving = p.get('saving', 0)
                        deal = {
                            'name': p.get('name', ''), 'price': p.get('price', 0),
                            'original_price': p.get('original_price'),
                            'saving': saving, 'specs': specs,
                            'condition': extract_condition(p.get('name', '')),
                            'notes': [], 'score': opt_scores.get(id(p), 0),
                            'url': p.get('url', ''), 'sku': p.get('retailer_sku', ''),
                            'source': p.get('source_display', ''),
                            'retailer': p.get('retailer', 'unknown'),
                            'category': 'ram', 'is_upgrade': False,
                            'thumbnail': p.get('thumbnail', ''),
                        }
                        if saving > 0:
                            dpct = (saving / (p['price'] + saving)) * 100 if (p['price'] + saving) > 0 else 0
                            deal['notes'].append(f"{dpct:.0f}% off")
                        us_deals.append(deal)
                    st.session_state['us_deals'] = us_deals
                    st.session_state['us_skipped'] = skipped
                else:
                    us_cur_specs = {'cpu_gen': 0, 'ram': 0, 'storage': 0}
                    if not us_is_ram:
                        us_cur_specs = {'cpu_gen': us_cur_cpu, 'ram': us_cur_ram, 'storage': us_cur_storage}
                    us_deals, us_skipped = analyze_search_deals(
                        us_products, us_cur_specs,
                        us_min_specs if not us_is_ram and not us_show_all else None,
                        us_show_all
                    )
                    st.session_state['us_deals'] = us_deals
                    st.session_state['us_skipped'] = us_skipped

    # Display US results
    if st.session_state.get('us_deals'):
        us_deals = st.session_state['us_deals']
        us_skipped = st.session_state.get('us_skipped', 0)

        msg = f"Found {len(us_deals)} US products"
        if us_skipped > 0:
            msg += f" ({us_skipped} filtered out)"
        st.success(msg)

        if us_deals:
            st.markdown("---")
            st.header("🏆 Top US Deals")
            top_n = min(3, len(us_deals))
            cols = st.columns(top_n)
            medals = ["🥇", "🥈", "🥉"]

            for i, (col, deal) in enumerate(zip(cols, us_deals[:top_n])):
                with col:
                    st.markdown(f"### {medals[i]} #{i+1}")
                    source = deal.get('source', '')
                    if source:
                        st.markdown(f"🏪 **{source}**")
                    st.markdown(f"**{deal['name'][:55]}...**")
                    st.markdown(f"💰 **${deal['price']:,.2f} USD**")
                    if deal.get('saving', 0) > 0:
                        st.markdown(f"🏷️ Save ${deal['saving']:.0f}")

                    cat = deal.get('category', 'laptop')
                    specs = deal.get('specs', {})
                    if cat in ('laptop', 'desktop') and specs.get('cpu_gen', 0) > 0:
                        st.markdown(f"🔧 CPU Gen {specs['cpu_gen']} | {specs.get('ram', '?')}GB RAM")
                    elif cat == 'ram':
                        _display_ram_specs_compact(specs)

                    if deal.get('url'):
                        st.link_button("View Deal", deal['url'])
                    if st.button(f"💾 Track", key=f"save_us_{i}"):
                        save_deal_to_db(deal)
                        st.success("Saved!")

            # Create alert from US search
            st.markdown("---")
            if us_is_ram and us_ram_filters:
                if st.button("🔔 Create Alert from This Search", key="us_alert_from_search"):
                    alert_dict = _build_alert_from_ram_filters(us_ram_filters, us_query)
                    db.create_alert(alert_dict)
                    st.success(f"Alert '{alert_dict['name']}' created! Go to the Alerts tab to manage it.")
            else:
                if st.button("🔔 Create Alert from This Search", key="us_alert_from_search_gen"):
                    alert_dict = {
                        'name': f"US: {us_query[:40]}",
                        'category': us_category if us_category != 'auto-detect' else 'other',
                        'keyword': us_query,
                        'cooldown_hours': 24,
                    }
                    db.create_alert(alert_dict)
                    st.success(f"Alert '{alert_dict['name']}' created! Go to the Alerts tab to manage it.")

            st.markdown("---")
            st.header(f"📊 All US Results ({len(us_deals)})")
            for i, deal in enumerate(us_deals):
                source = deal.get('source', '')
                source_badge = f" @ {source}" if source else ""
                with st.expander(f"**{i+1}. {deal['name'][:60]}...**{source_badge} — ${deal['price']:,.2f} USD"):
                    if source:
                        st.markdown(f"**Store:** {source}")

                    cat = deal.get('category', 'laptop')
                    specs = deal.get('specs', {})
                    if cat in ('laptop', 'desktop'):
                        st.markdown(f"**CPU:** {specs.get('cpu_model', '?')} (Gen {specs.get('cpu_gen', '?')})")
                        st.markdown(f"**RAM:** {specs.get('ram', '?')}GB | **Storage:** {specs.get('storage', '?')}GB")
                        st.markdown(f"**GPU:** {specs.get('gpu', 'Integrated')}")
                    elif cat == 'ram':
                        _display_ram_specs_full(specs)

                    col_link, col_save = st.columns([1, 1])
                    with col_link:
                        if deal.get('url'):
                            st.link_button("🔗 View Deal", deal['url'])
                    with col_save:
                        if st.button(f"💾 Track", key=f"save_us_all_{i}"):
                            save_deal_to_db(deal)
                            st.success("Saved!")


# ═══════════════════════════════════════════
# TAB 3: Upload HTML (Best Buy Canada)
# ═══════════════════════════════════════════
with tab_upload:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📁 Upload Best Buy Canada Page")

        st.markdown("**New here?** Try the demo first!")
        if st.button("🎮 Try Demo Data", key="demo_btn"):
            st.session_state['use_demo'] = True
            st.rerun()

        st.markdown("---")
        st.markdown("**Or upload your own:**")
        uploaded_file = st.file_uploader(
            "Choose the saved HTML file",
            type=['html', 'htm'],
            help="Upload the HTML file you saved from Best Buy Canada"
        )

    with col2:
        st.header("⚙️ Your Current Specs")
        current_ram = st.number_input("RAM (GB)", min_value=1, max_value=128, value=16, key="upload_ram")
        current_storage = st.number_input("Storage (GB)", min_value=64, max_value=8000, value=512, key="upload_storage")
        current_cpu_gen = st.number_input("CPU Generation", min_value=1, max_value=20, value=10, key="upload_cpu")
        current_screen_size = st.number_input("Screen Size (inches)", min_value=10.0, max_value=20.0, value=15.6, step=0.1, key="upload_screen")
        current_resolution = st.selectbox("Screen Resolution",
                                          options=["HD", "HD+", "FHD", "FHD+", "QHD", "QHD+", "4K UHD"],
                                          index=2, key="upload_res")
        show_all = st.checkbox("Show all products (not just upgrades)", key="upload_show_all")

    # Handle demo
    if st.session_state.get('use_demo', False):
        products = get_demo_products()
        current_specs = {
            'cpu_gen': current_cpu_gen, 'ram': current_ram,
            'storage': current_storage, 'screen_size': current_screen_size,
            'resolution': current_resolution
        }
        deals, skipped = analyze_deals(products, current_specs, show_all, filter_incomplete=False)
        st.session_state['deals'] = deals
        st.session_state['current_specs'] = current_specs
        st.session_state['analyzed'] = True
        st.session_state['product_count'] = len(products)
        st.session_state['is_demo'] = True
        st.session_state['use_demo'] = False

    if uploaded_file is not None:
        if st.button("🔍 Analyze Deals", type="primary", key="upload_analyze"):
            with st.spinner("Analyzing products..."):
                try:
                    content = uploaded_file.read().decode('utf-8')
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    content = uploaded_file.read().decode('latin-1')

                products, error = extract_products_from_html(content)

                if error:
                    st.error(error)
                    st.session_state['analyzed'] = False
                else:
                    current_specs = {
                        'cpu_gen': current_cpu_gen, 'ram': current_ram,
                        'storage': current_storage, 'screen_size': current_screen_size,
                        'resolution': current_resolution
                    }
                    deals, skipped = analyze_deals(products, current_specs, show_all, filter_incomplete=False)
                    st.session_state['deals'] = deals
                    st.session_state['current_specs'] = current_specs
                    st.session_state['analyzed'] = True
                    st.session_state['product_count'] = len(products)
                    st.session_state['is_demo'] = False

    # Display upload results
    if st.session_state.get('analyzed') and st.session_state.get('deals') is not None:
        deals = st.session_state['deals']
        current_specs = st.session_state['current_specs']
        is_demo = st.session_state.get('is_demo', False)

        if is_demo:
            st.success(f"🎮 **Demo Mode:** Showing {st.session_state.get('product_count', 0)} sample products")
            st.info("This is sample data. Upload your own Best Buy Canada HTML file for real deals!")
        else:
            st.success(f"🇨🇦 Found {st.session_state.get('product_count', 0)} products from Best Buy Canada!")

        if not deals:
            st.warning("No upgrades found. Try checking 'Show all products' or adjust your specs.")
        else:
            # Top 3
            st.markdown("---")
            st.header("🏆 Top 3 Best Deals")
            top_3 = deals[:3]
            cols = st.columns(len(top_3))
            medals = ["🥇", "🥈", "🥉"]

            for i, (col, deal) in enumerate(zip(cols, top_3)):
                with col:
                    st.markdown(f"### {medals[i]} #{i+1}")
                    condition = deal.get('condition', 'New')
                    if condition != 'New':
                        st.markdown(f"🏷️ **{condition}**")
                    st.markdown(f"**{deal['name'][:50]}...**")
                    st.markdown(f"💰 **${deal['price']:,.2f}**")
                    if deal['saving'] > 0:
                        st.markdown(f"🏷️ Save ${deal['saving']:.0f}")
                    st.markdown(f"🔧 CPU Gen {deal['specs']['cpu_gen']} | {deal['specs']['ram']}GB RAM")
                    screen_info = []
                    if deal['specs']['screen_size'] > 0:
                        screen_info.append(f"{deal['specs']['screen_size']}\"")
                    if deal['specs']['resolution'] != 'Unknown':
                        screen_info.append(deal['specs']['resolution'])
                    if screen_info:
                        st.markdown(f"🖥️ {' '.join(screen_info)}")
                    st.link_button("View Deal", deal['url'])
                    if st.button(f"💾 Track", key=f"save_upload_{i}"):
                        deal['retailer'] = 'bestbuy_ca'
                        deal['category'] = 'laptop'
                        save_deal_to_db(deal)
                        st.success("Saved!")

            # All deals
            st.markdown("---")
            st.header(f"📊 All {'Products' if show_all else 'Upgrades'} ({len(deals)})")
            for i, deal in enumerate(deals):
                condition = deal.get('condition', 'New')
                condition_badge = "" if condition == "New" else f" [{condition}]"
                with st.expander(f"**{i+1}. {deal['name'][:65]}...**{condition_badge} — ${deal['price']:,.2f}" +
                                (f" (Save ${deal['saving']:.0f})" if deal['saving'] > 0 else "")):
                    dcol1, dcol2 = st.columns([2, 1])
                    with dcol1:
                        if condition != 'New':
                            st.markdown(f"**Condition:** {condition}")
                        st.markdown(f"**CPU:** {deal['specs']['cpu_model']} (Gen {deal['specs']['cpu_gen']})")
                        st.markdown(f"**RAM:** {deal['specs']['ram']}GB")
                        st.markdown(f"**Storage:** {deal['specs']['storage']}GB")
                        st.markdown(f"**GPU:** {deal['specs']['gpu']}")
                        if deal['specs']['screen_size'] > 0:
                            st.markdown(f"**Screen:** {deal['specs']['screen_size']}\"")
                        if deal['specs']['resolution'] != 'Unknown':
                            st.markdown(f"**Resolution:** {deal['specs']['resolution']}")
                        if deal['notes']:
                            st.markdown(f"**Upgrades:** {', '.join(deal['notes'])}")
                    with dcol2:
                        st.link_button("🔗 View on Best Buy", deal['url'])
                        if st.button(f"💾 Track", key=f"save_upload_all_{i}"):
                            deal['retailer'] = 'bestbuy_ca'
                            deal['category'] = 'laptop'
                            save_deal_to_db(deal)
                            st.success("Saved!")

    if not st.session_state.get('analyzed'):
        st.info("👆 Upload a saved Best Buy Canada HTML file or try the demo to get started!")


# ═══════════════════════════════════════════
# TAB 3: Tracked Products
# ═══════════════════════════════════════════
with tab_tracked:
    st.subheader("📦 Tracked Products")

    # Filters
    col_cat_filter, col_ret_filter = st.columns(2)
    with col_cat_filter:
        filter_category = st.selectbox("Filter by Category",
                                       options=['All'] + SUPPORTED_CATEGORIES,
                                       key="track_cat_filter")
    with col_ret_filter:
        filter_retailer = st.selectbox("Filter by Retailer",
                                       options=['All'] + list(RETAILER_DISPLAY_NAMES.values()),
                                       key="track_ret_filter")

    # Map display name back to ID
    retailer_id_filter = None
    if filter_retailer != 'All':
        for rid, rname in RETAILER_DISPLAY_NAMES.items():
            if rname == filter_retailer:
                retailer_id_filter = rid
                break

    products = db.get_tracked_products(
        category=filter_category if filter_category != 'All' else None,
        retailer=retailer_id_filter,
    )

    if not products:
        st.info("No tracked products yet. Use the Search or Upload tabs to find deals, then click 'Track' to save them here.")
    else:
        st.markdown(f"**{len(products)} tracked products**")

        for product in products:
            price_stats = db.get_price_stats(product['id'])
            current_price = price_stats.get('current_price', '?')
            min_price = price_stats.get('min_price', '?')

            retailer_name = RETAILER_DISPLAY_NAMES.get(product['retailer'], product['retailer'])
            cat_emoji = {'laptop': '💻', 'desktop': '🖥️', 'ram': '🧠', 'cpu': '⚡',
                         'gpu': '🎮', 'ssd': '💾'}.get(product['category'], '📦')

            with st.expander(f"{cat_emoji} **{product['name'][:70]}...** — ${current_price:,.2f}" if isinstance(current_price, (int, float)) else f"{cat_emoji} **{product['name'][:70]}...**"):
                col_info, col_price, col_actions = st.columns([3, 2, 1])

                with col_info:
                    st.markdown(f"**Retailer:** {retailer_name}")
                    st.markdown(f"**Category:** {product['category'].title()}")
                    if product.get('cpu_model'):
                        st.markdown(f"**CPU:** {product['cpu_model']}")
                    if product.get('ram_gb'):
                        st.markdown(f"**RAM:** {product['ram_gb']}GB")
                    if product.get('gpu') and product['gpu'] != 'Integrated':
                        st.markdown(f"**GPU:** {product['gpu']}")
                    st.markdown(f"**First seen:** {product['first_seen'][:10]}")

                with col_price:
                    if isinstance(current_price, (int, float)):
                        st.metric("Current Price", f"${current_price:,.2f}")
                    if isinstance(min_price, (int, float)):
                        st.metric("Lowest Recorded", f"${min_price:,.2f}")

                    # Price history chart
                    history = db.get_price_history(product['id'])
                    if len(history) > 1:
                        import pandas as pd
                        df = pd.DataFrame(history)
                        df['checked_at'] = pd.to_datetime(df['checked_at'])
                        df = df.set_index('checked_at')
                        st.line_chart(df['price'], height=150)

                with col_actions:
                    if product.get('url') and product['url'] != '#':
                        st.link_button("🔗 View", product['url'])
                    if st.button("🗑️ Remove", key=f"del_product_{product['id']}"):
                        db.delete_product(product['id'])
                        st.rerun()


# ═══════════════════════════════════════════
# TAB 4: Alerts
# ═══════════════════════════════════════════
with tab_alerts:
    st.subheader("🔔 Deal Alerts")
    st.markdown("Get notified when products match your criteria.")

    # Create new alert
    with st.expander("➕ Create New Alert", expanded=False):
        with st.form("create_alert_form"):
            alert_name = st.text_input("Alert Name", placeholder="e.g., DDR5 RAM under $80")
            alert_category = st.selectbox("Category", options=SUPPORTED_CATEGORIES, key="alert_cat")

            col_a1, col_a2 = st.columns(2)
            with col_a1:
                alert_retailer = st.selectbox("Retailer",
                                              options=['Any'] + list(RETAILER_DISPLAY_NAMES.values()),
                                              key="alert_ret")
                alert_keyword = st.text_input("Keyword (in product name)", placeholder="e.g., DDR5, RTX 4070")
                alert_max_price = st.number_input("Max Price ($CAD)", min_value=0.0, value=0.0, step=10.0,
                                                  help="0 = no limit")
            with col_a2:
                alert_min_ram = st.number_input("Min RAM (GB)", min_value=0, value=0, key="alert_min_ram")
                alert_min_storage = st.number_input("Min Storage (GB)", min_value=0, value=0, key="alert_min_storage")
                alert_min_cpu = st.number_input("Min CPU Gen", min_value=0, value=0, key="alert_min_cpu")
                alert_ram_type = st.selectbox("RAM Type", options=['Any', 'DDR4', 'DDR5'], key="alert_ram_type")

            st.markdown("**Price Drop Triggers** (notify when price drops)")
            col_drop1, col_drop2 = st.columns(2)
            with col_drop1:
                alert_drop_pct = st.number_input("Price drop % threshold", min_value=0.0, value=0.0, step=5.0)
            with col_drop2:
                alert_drop_abs = st.number_input("Price drop $ threshold", min_value=0.0, value=0.0, step=10.0)

            alert_cooldown = st.number_input("Cooldown (hours between notifications)", min_value=1, value=24)

            submitted = st.form_submit_button("Create Alert", type="primary")
            if submitted and alert_name:
                # Map retailer display name to ID
                ret_id = None
                if alert_retailer != 'Any':
                    for rid, rname in RETAILER_DISPLAY_NAMES.items():
                        if rname == alert_retailer:
                            ret_id = rid
                            break

                alert_dict = {
                    'name': alert_name,
                    'category': alert_category,
                    'retailer': ret_id,
                    'keyword': alert_keyword or None,
                    'max_price': alert_max_price if alert_max_price > 0 else None,
                    'min_ram_gb': alert_min_ram if alert_min_ram > 0 else None,
                    'min_storage_gb': alert_min_storage if alert_min_storage > 0 else None,
                    'min_cpu_gen': alert_min_cpu if alert_min_cpu > 0 else None,
                    'ram_type': alert_ram_type if alert_ram_type != 'Any' else None,
                    'price_drop_pct': alert_drop_pct if alert_drop_pct > 0 else None,
                    'price_drop_abs': alert_drop_abs if alert_drop_abs > 0 else None,
                    'cooldown_hours': alert_cooldown,
                }
                db.create_alert(alert_dict)
                st.success(f"Alert '{alert_name}' created!")
                st.rerun()

    # List existing alerts
    alerts = db.get_alerts(active_only=False)
    if not alerts:
        st.info("No alerts yet. Create one above to get notified about deals!")
    else:
        for alert in alerts:
            status_icon = "🟢" if alert['is_active'] else "🔴"
            with st.expander(f"{status_icon} **{alert['name']}** — {alert['category'].title()}"):
                col_details, col_actions = st.columns([3, 1])

                with col_details:
                    if alert.get('retailer'):
                        st.markdown(f"**Retailer:** {RETAILER_DISPLAY_NAMES.get(alert['retailer'], alert['retailer'])}")
                    if alert.get('keyword'):
                        st.markdown(f"**Keyword:** {alert['keyword']}")
                    if alert.get('max_price'):
                        st.markdown(f"**Max Price:** ${alert['max_price']:,.2f}")
                    if alert.get('min_ram_gb'):
                        st.markdown(f"**Min RAM:** {alert['min_ram_gb']}GB")
                    if alert.get('min_storage_gb'):
                        st.markdown(f"**Min Storage:** {alert['min_storage_gb']}GB")
                    if alert.get('min_cpu_gen'):
                        st.markdown(f"**Min CPU Gen:** {alert['min_cpu_gen']}")
                    if alert.get('ram_type'):
                        st.markdown(f"**RAM Type:** {alert['ram_type']}")
                    if alert.get('form_factor'):
                        st.markdown(f"**Form Factor:** {alert['form_factor']}")
                    if alert.get('kit_config'):
                        kit_labels = {'1x': 'Single Stick', '2x': '2-Stick Kit', '4x': '4-Stick Kit'}
                        st.markdown(f"**Kit Config:** {kit_labels.get(alert['kit_config'], alert['kit_config'])}")
                    if alert.get('min_speed_mhz'):
                        st.markdown(f"**Min Speed:** {alert['min_speed_mhz']}MHz")
                    if alert.get('max_cas_latency'):
                        st.markdown(f"**Max CAS Latency:** CL{alert['max_cas_latency']}")
                    if alert.get('brand'):
                        st.markdown(f"**Brand:** {alert['brand']}")
                    if alert.get('price_drop_pct'):
                        st.markdown(f"**Price drop trigger:** {alert['price_drop_pct']}%")
                    if alert.get('price_drop_abs'):
                        st.markdown(f"**Price drop trigger:** ${alert['price_drop_abs']:.0f}")
                    st.markdown(f"**Cooldown:** {alert['cooldown_hours']}h")
                    if alert.get('last_triggered'):
                        st.markdown(f"**Last triggered:** {alert['last_triggered'][:19]}")

                with col_actions:
                    if st.button("Toggle", key=f"toggle_alert_{alert['id']}"):
                        new_status = db.toggle_alert(alert['id'])
                        st.rerun()
                    if st.button("🗑️ Delete", key=f"del_alert_{alert['id']}"):
                        db.delete_alert(alert['id'])
                        st.rerun()

    # Check Now button
    st.markdown("---")
    st.subheader("🔄 Run Alert Check")
    col_check, col_dry = st.columns([1, 1])
    with col_check:
        if st.button("🔍 Check Now (send emails)", type="primary", key="check_now"):
            with st.spinner("Running all active alerts..."):
                try:
                    from deal_checker import run_check
                    run_check(dry_run=False, verbose=True)
                    st.success("Check complete! See results below.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Check failed: {e}")
    with col_dry:
        if st.button("🧪 Dry Run (no emails)", key="check_dry"):
            with st.spinner("Running dry check..."):
                try:
                    from deal_checker import run_check
                    run_check(dry_run=True, verbose=True)
                    st.success("Dry run complete! Check the log at data/checker.log")
                except Exception as e:
                    st.error(f"Check failed: {e}")

    # Recent notifications
    st.markdown("---")
    st.subheader("📬 Recent Notifications")
    notifications = db.get_recent_notifications(limit=20)
    if not notifications:
        st.info("No notifications sent yet.")
    else:
        for n in notifications:
            status = "✅" if n['success'] else "❌"
            st.markdown(f"{status} **{n.get('alert_name', '?')}** — {n.get('product_name', '?')[:50]} — {n['sent_at'][:19]}")


# ═══════════════════════════════════════════
# TAB 5: Settings
# ═══════════════════════════════════════════
with tab_settings:
    st.subheader("⚙️ Settings")

    settings = db.get_all_settings()

    # SerpApi
    st.markdown("### 🔑 SerpApi Configuration")
    st.markdown("Get a free API key at [serpapi.com](https://serpapi.com/) (100 searches/month free)")
    serpapi_key = st.text_input("SerpApi Key", value=settings.get('serpapi_key', ''), type="password", key="set_serpapi")
    if st.button("Save API Key"):
        db.set_setting('serpapi_key', serpapi_key)
        st.success("SerpApi key saved!")

    st.markdown("---")

    # Email
    st.markdown("### 📧 Email Notification Settings")
    st.markdown("For Gmail, use an [App Password](https://myaccount.google.com/apppasswords) (not your regular password)")

    with st.form("email_settings_form"):
        email_smtp = st.text_input("SMTP Server", value=settings.get('email_smtp_server', 'smtp.gmail.com'))
        email_port = st.text_input("SMTP Port", value=settings.get('email_smtp_port', '587'))
        email_from = st.text_input("From Email", value=settings.get('email_from', ''))
        email_to = st.text_input("To Email (notifications sent here)", value=settings.get('email_to', ''))
        email_password = st.text_input("Email Password / App Password", value=settings.get('email_password', ''), type="password")

        save_email = st.form_submit_button("Save Email Settings")
        if save_email:
            db.set_setting('email_smtp_server', email_smtp)
            db.set_setting('email_smtp_port', email_port)
            db.set_setting('email_from', email_from)
            db.set_setting('email_to', email_to)
            db.set_setting('email_password', email_password)
            st.success("Email settings saved!")

    # Test email
    if st.button("📧 Send Test Email"):
        try:
            from notifications import send_test_email
            send_test_email(
                smtp_server=settings.get('email_smtp_server', 'smtp.gmail.com'),
                smtp_port=int(settings.get('email_smtp_port', '587')),
                from_addr=settings.get('email_from', ''),
                password=settings.get('email_password', ''),
                to_addr=settings.get('email_to', ''),
            )
            st.success("Test email sent! Check your inbox.")
        except Exception as e:
            st.error(f"Email failed: {e}")
            if 'Username and Password not accepted' in str(e):
                st.info("This usually means you need a Gmail **App Password**, not your regular password. "
                        "Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) to create one.")
            elif 'Authentication' in str(e) or 'auth' in str(e).lower():
                st.info("Authentication failed. Make sure you're using a Gmail App Password and that 2-Step Verification is enabled.")

    st.markdown("---")
    st.markdown("### ⏰ Automated Checking")
    check_interval = st.number_input(
        "Check interval (minutes)",
        min_value=60, max_value=1440,
        value=int(settings.get('check_interval_minutes', '360')),
        step=60,
        help="How often the scheduled checker runs (configured via Windows Task Scheduler)"
    )
    if st.button("Save Interval"):
        db.set_setting('check_interval_minutes', str(check_interval))
        st.success("Saved!")

    st.info("To enable automated checking, set up `deal_checker.py` in Windows Task Scheduler. See the README for instructions.")
