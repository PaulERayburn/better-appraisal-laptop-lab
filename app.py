"""
Best Buy Deal Finder - Web App
==============================
A Streamlit web app to find laptop upgrade deals from Best Buy (US & Canada).
Upload a saved HTML file and compare against your current specs.
"""

import streamlit as st
import json
import re
import requests
from bs4 import BeautifulSoup

# Page config
st.set_page_config(
    page_title="Best Buy Deal Finder",
    page_icon="💻",
    layout="wide"
)

def parse_size(size_str):
    """Parse storage/RAM strings like '16GB', '1TB', '512GB' into GB as integer."""
    if not size_str:
        return 0
    size_str = str(size_str).upper().replace(" ", "")

    try:
        if "TB" in size_str:
            match = re.search(r'(\d+(?:\.\d+)?)', size_str)
            if match:
                return int(float(match.group(1)) * 1024)
        if "GB" in size_str:
            match = re.search(r'(\d+(?:\.\d+)?)', size_str)
            if match:
                return int(float(match.group(1)))
    except (ValueError, AttributeError):
        pass
    return 0


def extract_condition(name):
    """Extract product condition from name (New, Refurbished, Open Box)."""
    name_lower = name.lower()

    if 'refurbished' in name_lower:
        # Try to get the grade too (Excellent, Good, Fair)
        if '(excellent)' in name_lower or 'excellent' in name_lower:
            return 'Refurbished (Excellent)'
        elif '(good)' in name_lower or 'good' in name_lower:
            return 'Refurbished (Good)'
        elif '(fair)' in name_lower:
            return 'Refurbished (Fair)'
        return 'Refurbished'
    elif 'open box' in name_lower:
        return 'Open Box'
    else:
        return 'New'


def extract_specs(name):
    """Extract CPU, RAM, Storage, GPU, screen size, and resolution from a product name string."""
    specs = {
        'cpu_gen': 0,
        'cpu_model': 'Unknown',
        'ram': 0,
        'storage': 0,
        'gpu': 'Integrated',
        'screen_size': 0,
        'resolution': 'Unknown'
    }

    # Intel Core iX-XXXXX (e.g., i7-13620H, i5-12450H)
    intel_match = re.search(r'(i\d)-(\d{4,5})', name)
    if intel_match:
        specs['cpu_model'] = f"{intel_match.group(1)}-{intel_match.group(2)}"
        model_num = intel_match.group(2)
        if len(model_num) == 5:
            specs['cpu_gen'] = int(model_num[:2])
        elif len(model_num) == 4:
            specs['cpu_gen'] = int(model_num[0])

    # Intel Core Ultra (newer chips, treat as gen 14+)
    ultra_match = re.search(r'(?:Core\s+)?Ultra\s*(\d+)', name, re.IGNORECASE)
    if ultra_match:
        specs['cpu_gen'] = 14
        specs['cpu_model'] = f"Ultra {ultra_match.group(1)}"

    # AMD Ryzen (e.g., Ryzen 7 7840HS)
    amd_match = re.search(r'Ryzen\s*(\d)\s*(\d{4})', name, re.IGNORECASE)
    if amd_match:
        specs['cpu_model'] = f"Ryzen {amd_match.group(1)} {amd_match.group(2)}"
        series = int(amd_match.group(2)[0])
        specs['cpu_gen'] = series + 6

    # RAM
    ram_patterns = [
        r'(\d+)\s*GB\s*(?:DDR\d?)?\s*RAM',
        r'(\d+)\s*GB\s*DDR\d',
        r'/\s*(\d+)\s*GB\s*/',
    ]
    for pattern in ram_patterns:
        ram_match = re.search(pattern, name, re.IGNORECASE)
        if ram_match:
            specs['ram'] = int(ram_match.group(1))
            break

    # Storage
    storage_patterns = [
        r'(\d+(?:\.\d+)?)\s*(TB|GB)\s*SSD',
        r'(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:NVMe|PCIe)',
        r'/\s*(\d+(?:\.\d+)?)\s*(TB|GB)\s*/',
    ]
    for pattern in storage_patterns:
        storage_match = re.search(pattern, name, re.IGNORECASE)
        if storage_match:
            specs['storage'] = parse_size(f"{storage_match.group(1)}{storage_match.group(2)}")
            break

    # GPU
    gpu_match = re.search(r'(RTX\s*\d{4}(?:\s*Ti)?|GTX\s*\d{4})', name, re.IGNORECASE)
    if gpu_match:
        specs['gpu'] = gpu_match.group(1).upper().replace(" ", " ")

    # Screen size (e.g., 15.6", 14", 17.3")
    screen_patterns = [
        r'(\d{1,2}(?:\.\d)?)["\u201d\u2033]\s*(?:FHD|QHD|UHD|HD|OLED|IPS|LED)?',  # 15.6" FHD
        r'(\d{1,2}(?:\.\d)?)\s*(?:inch|in)\b',  # 15.6 inch
        r'(\d{1,2}(?:\.\d)?)\s*(?:FHD|QHD|UHD|HD|OLED)',  # 15.6 FHD (no quote)
    ]
    for pattern in screen_patterns:
        screen_match = re.search(pattern, name, re.IGNORECASE)
        if screen_match:
            size = float(screen_match.group(1))
            if 10 <= size <= 20:  # Valid laptop screen sizes
                specs['screen_size'] = size
                break

    # Resolution (FHD, QHD, UHD/4K, HD, etc.)
    resolution_map = {
        r'\b4K\b': '4K UHD',
        r'\bUHD\b': '4K UHD',
        r'\bQHD\+': 'QHD+',
        r'\bQHD\b': 'QHD',
        r'\bWQXGA\b': 'WQXGA',
        r'\bFHD\+': 'FHD+',
        r'\bFHD\b': 'FHD',
        r'\b1080p\b': 'FHD',
        r'\b1440p\b': 'QHD',
        r'\b2160p\b': '4K UHD',
        r'\bHD\+': 'HD+',
        r'\bHD\b': 'HD',
        r'\bOLED\b': 'OLED',  # Often indicates premium display
    }
    for pattern, resolution in resolution_map.items():
        if re.search(pattern, name, re.IGNORECASE):
            # Special case: if we find OLED, check if there's also a resolution
            if resolution == 'OLED':
                specs['resolution'] = 'OLED'
                # Keep looking for actual resolution
                continue
            specs['resolution'] = resolution
            break

    return specs


def extract_products_from_html(content, country="CA"):
    """Extract product data from Best Buy saved HTML page (US or Canada)."""

    # Try Canada format first (window.__INITIAL_STATE__)
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
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
                return products, None, "CA"
        except json.JSONDecodeError:
            pass

    # Try US format (GraphQL/Apollo style embedded in HTML)
    # US Best Buy embeds product data differently - we need to extract it from the page
    products = extract_us_products(content)
    if products:
        return products, None, "US"

    return None, "Could not find product data. Make sure you saved a Best Buy product listing page (US or Canada).", None


def extract_us_products(content):
    """Extract products from US Best Buy HTML format."""
    products = []

    # US format has product names in "name":{"__typename":"ProductName","short":"..."}
    # and prices in "customerPrice":XXX.XX,"skuId":"..."

    # Build a map of SKU -> price first
    price_pattern = r'"customerPrice":([\d.]+),"skuId":"(\d+)"'
    sku_prices = {}
    for match in re.finditer(price_pattern, content):
        price, sku = match.groups()
        if sku not in sku_prices:
            sku_prices[sku] = float(price)

    # Find all product names
    name_pattern = r'"name":\{"__typename":"ProductName","short":"([^"]+)"'
    name_matches = list(re.finditer(name_pattern, content))

    # Extract products by finding name blocks and nearby SKUs
    seen_skus = set()

    for name_match in name_matches:
        short_name = name_match.group(1)

        # Clean up escaped characters
        short_name = short_name.replace('\\"', '"').replace('\\/', '/')

        # Look for SKU near this name (within ~3000 chars before)
        start_pos = max(0, name_match.start() - 3000)
        context = content[start_pos:name_match.end() + 500]

        # Try to find SKU in context
        sku_match = re.search(r'"sku":"(\d+)"', context)
        if not sku_match:
            sku_match = re.search(r'"skuId":"(\d+)"', context)

        if sku_match:
            sku = sku_match.group(1)

            # Skip if we've already processed this SKU
            if sku in seen_skus:
                continue
            seen_skus.add(sku)

            price = sku_prices.get(sku, 0)

            # Skip products without prices (not fully loaded)
            if price == 0:
                continue

            # Check for savings
            saving = 0
            regular_match = re.search(rf'"skuId":"{sku}"[^}}]*"regularPrice":([\d.]+)', content)
            if regular_match:
                regular = float(regular_match.group(1))
                if regular > price:
                    saving = regular - price

            products.append({
                'name': short_name,
                'sku': sku,
                'skuId': sku,
                'price': price,
                'customerPrice': price,
                'saving': saving,
                'seoUrl': f'/site/{sku}.p?skuId={sku}',
                'country': 'US'
            })

    return products if products else None


def search_bestbuy_us(query, max_results=24):
    """
    Search Best Buy US using their website and BeautifulSoup.
    Note: This is experimental and may break if Best Buy changes their site structure.
    """
    products = []

    # Best Buy US search URL
    search_url = f"https://www.bestbuy.com/site/searchpage.jsp?st={query.replace(' ', '+')}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    try:
        response = requests.get(search_url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        # Try to extract embedded JSON data first
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string and '__INITIAL_STATE__' in script.string:
                match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', script.string, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        # Navigate to products in the JSON structure
                        if 'search' in data and 'searchResult' in data['search']:
                            results = data['search']['searchResult'].get('products', [])
                            for p in results[:max_results]:
                                products.append({
                                    'name': p.get('names', {}).get('short', p.get('name', '')),
                                    'sku': p.get('sku', ''),
                                    'price': p.get('priceWithoutEhf', p.get('regularPrice', 0)),
                                    'saving': p.get('priceDiff', 0),
                                    'seoUrl': p.get('url', ''),
                                    'country': 'US'
                                })
                            return products, None
                    except json.JSONDecodeError:
                        pass

        # Fallback: parse HTML structure directly
        product_items = soup.select('.sku-item')

        for item in product_items[:max_results]:
            try:
                name_elem = item.select_one('.sku-title a')
                price_elem = item.select_one('.priceView-customer-price span')
                sku_elem = item.get('data-sku-id', '')

                if name_elem and price_elem:
                    name = name_elem.get_text(strip=True)
                    price_text = price_elem.get_text(strip=True).replace('$', '').replace(',', '')
                    try:
                        price = float(price_text)
                    except ValueError:
                        price = 0

                    # Try to get savings
                    saving = 0
                    savings_elem = item.select_one('.pricing-price__savings')
                    if savings_elem:
                        savings_text = savings_elem.get_text(strip=True)
                        savings_match = re.search(r'Save\s*\$?([\d,]+)', savings_text)
                        if savings_match:
                            saving = float(savings_match.group(1).replace(',', ''))

                    products.append({
                        'name': name,
                        'sku': sku_elem,
                        'price': price,
                        'saving': saving,
                        'seoUrl': name_elem.get('href', ''),
                        'country': 'US'
                    })
            except Exception:
                continue

        if products:
            return products, None
        else:
            return None, "No products found. Best Buy may have blocked the request or changed their page structure."

    except requests.exceptions.Timeout:
        return None, "Request timed out. Try again later."
    except requests.exceptions.RequestException as e:
        return None, f"Failed to fetch search results: {str(e)}"


def analyze_deals(products, current_specs, show_all=False, country="CA"):
    """Analyze products and compare against current specs."""
    if country == "US":
        base_url = "https://www.bestbuy.com"
    else:
        base_url = "https://www.bestbuy.ca"

    deals = []

    for p in products:
        name = p.get('name', '')

        # Handle different price field names between US and Canada
        price = p.get('priceWithoutEhf') or p.get('customerPrice') or p.get('price', 0)
        if isinstance(price, dict):
            price = price.get('customerPrice', 0)

        saving = p.get('saving', 0)
        sku = p.get('sku') or p.get('skuId', '')

        specs = extract_specs(name)
        condition = extract_condition(name)

        seo_url = p.get('seoUrl', '')
        if country == "US":
            url = f"{base_url}/site/{sku}.p?skuId={sku}"
        elif seo_url:
            url = seo_url if seo_url.startswith('http') else base_url + seo_url
        else:
            url = f"{base_url}/en-ca/product/{sku}"

        better_cpu = specs['cpu_gen'] > current_specs['cpu_gen']
        better_ram = specs['ram'] > current_specs['ram']
        better_storage = specs['storage'] >= current_specs['storage']

        # Screen size comparison
        bigger_screen = specs['screen_size'] > current_specs.get('screen_size', 0) if specs['screen_size'] > 0 else False

        # Resolution comparison (rank: HD < HD+ < FHD < FHD+ < QHD < QHD+ < 4K UHD)
        resolution_rank = {"HD": 1, "HD+": 2, "FHD": 3, "FHD+": 4, "QHD": 5, "WQXGA": 5, "QHD+": 6, "4K UHD": 7, "OLED": 4, "Unknown": 0}
        current_res_rank = resolution_rank.get(current_specs.get('resolution', 'FHD'), 3)
        product_res_rank = resolution_rank.get(specs['resolution'], 0)
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
        if better_cpu:
            score += 2
        if better_ram:
            score += 2
        if better_storage:
            score += 1
        if bigger_screen:
            score += 1
        if better_resolution:
            score += 1
        if saving > 0:
            score += 1

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
            'is_upgrade': better_cpu or better_ram
        }

        if show_all or deal['is_upgrade']:
            deals.append(deal)

    deals.sort(key=lambda x: (-x['score'], x['price']))
    return deals


def generate_santa_wishlist(deals, current_specs, top_n=3):
    """Generate the festive Christmas wishlist HTML."""
    top_deals = deals[:top_n]

    # Generate items HTML
    items_html = ""
    titles = ["The 'Best Value' Upgrade", "The 'Ultimate Power' Beast", "The Premium Choice"]
    descriptions = [
        "This is a great balance of performance and price!",
        "If you're feeling extra generous, this one is top-tier!",
        "A solid choice with excellent specs!"
    ]

    for i, deal in enumerate(top_deals):
        title = titles[i] if i < len(titles) else f"Great Option #{i+1}"
        desc = descriptions[i] if i < len(descriptions) else "Another excellent upgrade option!"

        savings_html = ""
        if deal['saving'] > 0:
            savings_html = f'<div class="savings">Save ~${deal["saving"]:.0f}!</div>'

        # Build comparison text
        comparisons = []
        if deal['specs']['ram'] > current_specs['ram']:
            ratio = deal['specs']['ram'] / current_specs['ram']
            if ratio >= 4:
                comparisons.append(f"{deal['specs']['ram']}GB (Quadruple my current!)")
            elif ratio >= 2:
                comparisons.append(f"{deal['specs']['ram']}GB (Double my current!)")
            else:
                comparisons.append(f"{deal['specs']['ram']}GB (More than mine!)")

        specs_html = ""
        condition = deal.get('condition', 'New')
        if condition != 'New':
            specs_html += f"<li><strong>Condition:</strong> {condition}</li>\n"
        if deal['specs']['cpu_gen'] > 0:
            specs_html += f"<li><strong>CPU:</strong> {deal['specs']['cpu_model']} ({deal['specs']['cpu_gen']}th Gen)</li>\n"
        if deal['specs']['ram'] > 0:
            ram_note = ""
            if deal['specs']['ram'] > current_specs['ram']:
                ratio = deal['specs']['ram'] / current_specs['ram']
                if ratio >= 4:
                    ram_note = " (Quadruple my current!)"
                elif ratio >= 2:
                    ram_note = " (Double my current!)"
                else:
                    ram_note = " (More than mine!)"
            specs_html += f"<li><strong>RAM:</strong> {deal['specs']['ram']}GB{ram_note}</li>\n"
        if deal['specs']['storage'] > 0:
            storage_note = ""
            if deal['specs']['storage'] > current_specs['storage']:
                storage_note = " (More than my current!)"
            specs_html += f"<li><strong>Storage:</strong> {deal['specs']['storage']}GB SSD{storage_note}</li>\n"
        if deal['specs']['gpu'] != 'Integrated':
            specs_html += f"<li><strong>GPU:</strong> {deal['specs']['gpu']}</li>\n"
        if deal['specs']['screen_size'] > 0:
            screen_text = f"{deal['specs']['screen_size']}\""
            if deal['specs']['resolution'] != 'Unknown':
                screen_text += f" {deal['specs']['resolution']}"
            specs_html += f"<li><strong>Screen:</strong> {screen_text}</li>\n"

        # Add condition badge in title if not new
        condition_badge = f" ({condition})" if condition != 'New' else ""

        items_html += f'''
    <div class="item">
        <h2>{i+1}. {title}{condition_badge}</h2>
        <p><strong>{deal['name'][:60]}{'...' if len(deal['name']) > 60 else ''}</strong></p>
        <p>{desc}</p>
        <ul class="specs">
            {specs_html}
        </ul>
        <div class="price-tag">${deal['price']:,.2f}</div>
        {savings_html}
        <a href="{deal['url']}" class="btn" target="_blank">View for Santa</a>
    </div>
'''

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Christmas Laptop Wishlist</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #b3000c;
            color: #333;
            margin: 0;
            padding: 20px;
            display: flex;
            justify-content: center;
        }}
        .container {{
            background-color: #fff;
            max-width: 800px;
            width: 100%;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            border: 5px solid #228b22;
            position: relative;
        }}
        .container::before {{
            content: "❄️";
            position: absolute;
            top: 10px;
            left: 10px;
            font-size: 30px;
        }}
        .container::after {{
            content: "❄️";
            position: absolute;
            top: 10px;
            right: 10px;
            font-size: 30px;
        }}
        h1 {{
            text-align: center;
            color: #b3000c;
            font-family: 'Georgia', serif;
            margin-bottom: 10px;
        }}
        p.intro {{
            text-align: center;
            font-size: 1.1em;
            color: #555;
            margin-bottom: 30px;
        }}
        .item {{
            border: 1px solid #ddd;
            border-radius: 8px;
            margin-bottom: 20px;
            padding: 20px;
            background-color: #f9f9f9;
            transition: transform 0.2s;
        }}
        .item:hover {{
            transform: scale(1.02);
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        .item h2 {{
            margin-top: 0;
            color: #228b22;
        }}
        .specs {{
            list-style-type: none;
            padding: 0;
            margin: 10px 0;
        }}
        .specs li {{
            margin-bottom: 5px;
            padding-left: 20px;
            position: relative;
        }}
        .specs li::before {{
            content: "🎁";
            position: absolute;
            left: 0;
        }}
        .price-tag {{
            font-size: 1.2em;
            font-weight: bold;
            color: #b3000c;
            margin-top: 10px;
        }}
        .savings {{
            font-size: 0.9em;
            color: #2e8b57;
            font-weight: bold;
        }}
        .btn {{
            display: inline-block;
            margin-top: 15px;
            padding: 10px 20px;
            background-color: #b3000c;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
        }}
        .btn:hover {{
            background-color: #8b0000;
        }}
        .footer {{
            text-align: center;
            margin-top: 30px;
            font-size: 0.9em;
            color: #777;
        }}
    </style>
</head>
<body>

<div class="container">
    <h1>🎄 Dear Santa 🎄</h1>
    <p class="intro">I've been very good this year (and my current laptop is getting old).<br>Here are the best deals I found that would be a perfect upgrade!</p>
    {items_html}
    <div class="footer">
        <p>Milk and cookies will be waiting! 🥛🍪</p>
    </div>
</div>

</body>
</html>
'''
    return html_content


# Main App
st.title("💻 Best Buy Deal Finder")
st.markdown("*Find laptop upgrade deals from Best Buy (US & Canada)*")

# Sidebar - Instructions
with st.sidebar:
    st.header("📋 How to Use")
    st.markdown("""
    **Step 1:** Go to [Best Buy Canada Laptops](https://www.bestbuy.ca/en-ca/category/laptops-macbooks/20352)

    **Step 2:** Use filters to refine your search

    **Step 3:** Click **"Show More"** until all products load

    **Step 4:** Save the page:
    - **Chrome:** ⋮ menu → Cast, save, and share → Save page as...
    - **Firefox:** ≡ menu → Save Page As...
    - **Edge:** ... menu → Save page as
    - Or press `Ctrl+S` / `Cmd+S`

    **Step 5:** Upload the saved HTML file here

    **Step 6:** Enter your current specs and click Analyze!
    """)

    st.markdown("---")
    st.markdown("⚠️ **Note:** Best Buy Canada works best. US support is experimental.")

    st.markdown("---")
    st.markdown("### 🔍 Live Search (US)")
    st.markdown("Try the **Live Search** tab to search Best Buy US directly without saving a page!")

    st.markdown("---")
    st.markdown("Made with ❤️ | [GitHub](https://github.com/PaulERayburn/bestbuy-deal-finder)")

# Initialize session state (must be before tabs)
if 'deals' not in st.session_state:
    st.session_state['deals'] = None
if 'current_specs' not in st.session_state:
    st.session_state['current_specs'] = None
if 'analyzed' not in st.session_state:
    st.session_state['analyzed'] = False

# Main content - Tabs for different input methods
tab1, tab2 = st.tabs(["📁 Upload HTML File", "🔍 Live Search (US - Experimental)"])

with tab1:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.header("📁 Upload Your Saved Page")
        uploaded_file = st.file_uploader(
            "Choose the saved HTML file",
            type=['html', 'htm'],
            help="Upload the HTML file you saved from Best Buy (US or Canada)"
        )

    with col2:
        st.header("⚙️ Your Current Specs")
        current_ram = st.number_input("RAM (GB)", min_value=1, max_value=128, value=16, key="upload_ram")
        current_storage = st.number_input("Storage (GB)", min_value=64, max_value=8000, value=512, key="upload_storage")
        current_cpu_gen = st.number_input("CPU Generation", min_value=1, max_value=20, value=10,
                                           help="e.g., 10 for Intel 10th gen i7-10750H", key="upload_cpu")
        current_screen_size = st.number_input("Screen Size (inches)", min_value=10.0, max_value=20.0, value=15.6, step=0.1,
                                              help="e.g., 15.6 for a 15.6\" display", key="upload_screen")
        current_resolution = st.selectbox("Screen Resolution",
                                          options=["HD", "HD+", "FHD", "FHD+", "QHD", "QHD+", "4K UHD"],
                                          index=2,  # Default to FHD
                                          help="HD=1366x768, FHD=1920x1080, QHD=2560x1440, 4K=3840x2160", key="upload_res")
        show_all = st.checkbox("Show all products (not just upgrades)", key="upload_show_all")

with tab2:
    st.header("🔍 Live Search Best Buy US")
    st.warning("⚠️ **Experimental Feature:** This searches Best Buy US directly. Results may be limited due to anti-bot measures.")

    search_col1, search_col2 = st.columns([2, 1])

    with search_col1:
        search_query = st.text_input("Search for laptops", value="gaming laptop", placeholder="e.g., gaming laptop RTX 4060")
        search_button = st.button("🔍 Search Best Buy US", type="primary")

    with search_col2:
        st.subheader("⚙️ Your Current Specs")
        search_ram = st.number_input("RAM (GB)", min_value=1, max_value=128, value=16, key="search_ram")
        search_storage = st.number_input("Storage (GB)", min_value=64, max_value=8000, value=512, key="search_storage")
        search_cpu_gen = st.number_input("CPU Generation", min_value=1, max_value=20, value=10, key="search_cpu")
        search_screen_size = st.number_input("Screen Size (inches)", min_value=10.0, max_value=20.0, value=15.6, step=0.1, key="search_screen")
        search_resolution = st.selectbox("Screen Resolution",
                                         options=["HD", "HD+", "FHD", "FHD+", "QHD", "QHD+", "4K UHD"],
                                         index=2, key="search_res")
        search_show_all = st.checkbox("Show all products (not just upgrades)", key="search_show_all")

    # Handle live search
    if search_button:
        with st.spinner(f"Searching Best Buy US for '{search_query}'..."):
            products, error = search_bestbuy_us(search_query)

            if error:
                st.error(error)
            elif products:
                search_specs = {
                    'cpu_gen': search_cpu_gen,
                    'ram': search_ram,
                    'storage': search_storage,
                    'screen_size': search_screen_size,
                    'resolution': search_resolution
                }
                search_deals = analyze_deals(products, search_specs, search_show_all, "US")

                st.session_state['search_deals'] = search_deals
                st.session_state['search_specs'] = search_specs
                st.session_state['search_count'] = len(products)

    # Display search results
    if 'search_deals' in st.session_state and st.session_state['search_deals']:
        search_deals = st.session_state['search_deals']
        search_specs = st.session_state['search_specs']

        st.success(f"🇺🇸 Found {st.session_state.get('search_count', 0)} products from Best Buy US!")

        if not search_deals:
            st.warning("No upgrades found. Try 'Show all products' or adjust your specs.")
        else:
            # Top 3 deals
            st.markdown("---")
            st.header("🏆 Top 3 Best Deals")

            top_3 = search_deals[:3]
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

            # Santa wishlist for search results
            st.markdown("---")
            st.header("🎄 Create Your Santa Wishlist")
            num_items_search = st.slider("How many items?", 1, min(5, len(search_deals)), 3, key="search_wishlist_num")
            wishlist_html_search = generate_santa_wishlist(search_deals, search_specs, num_items_search)
            st.download_button(
                label="🎅 Download Santa Wishlist",
                data=wishlist_html_search,
                file_name="santa_wishlist_us.html",
                mime="text/html",
                type="primary",
                key="search_wishlist_btn"
            )

            # All deals
            st.markdown("---")
            st.header(f"📊 All Results ({len(search_deals)})")
            for i, deal in enumerate(search_deals):
                condition = deal.get('condition', 'New')
                condition_badge = "" if condition == "New" else f" [{condition}]"
                with st.expander(f"**{i+1}. {deal['name'][:65]}...**{condition_badge} — ${deal['price']:,.2f}"):
                    st.markdown(f"**CPU:** {deal['specs']['cpu_model']} (Gen {deal['specs']['cpu_gen']})")
                    st.markdown(f"**RAM:** {deal['specs']['ram']}GB | **Storage:** {deal['specs']['storage']}GB")
                    st.markdown(f"**GPU:** {deal['specs']['gpu']}")
                    if deal['specs']['screen_size'] > 0:
                        st.markdown(f"**Screen:** {deal['specs']['screen_size']}\" {deal['specs']['resolution']}")
                    st.link_button("🔗 View on Best Buy", deal['url'])

    # Process uploaded file (tab1 content continues)
    if uploaded_file is not None:
        # Analyze button
        if st.button("🔍 Analyze Deals", type="primary", key="upload_analyze"):
            with st.spinner("Analyzing products..."):
                try:
                    content = uploaded_file.read().decode('utf-8')
                except UnicodeDecodeError:
                    uploaded_file.seek(0)
                    content = uploaded_file.read().decode('latin-1')

                products, error, country = extract_products_from_html(content)

                if error:
                    st.error(error)
                    st.session_state['analyzed'] = False
                else:
                    current_specs = {
                        'cpu_gen': current_cpu_gen,
                        'ram': current_ram,
                        'storage': current_storage,
                        'screen_size': current_screen_size,
                        'resolution': current_resolution
                    }

                    deals = analyze_deals(products, current_specs, show_all, country)

                    # Store in session state
                    st.session_state['deals'] = deals
                    st.session_state['current_specs'] = current_specs
                    st.session_state['analyzed'] = True
                    st.session_state['product_count'] = len(products)
                    st.session_state['country'] = country

        # Display results if we have analyzed data
        if st.session_state['analyzed'] and st.session_state['deals'] is not None:
            deals = st.session_state['deals']
            current_specs = st.session_state['current_specs']
            country = st.session_state.get('country', 'CA')

            country_flag = "🇺🇸" if country == "US" else "🇨🇦"
            country_name = "US" if country == "US" else "Canada"
            st.success(f"{country_flag} Found {st.session_state.get('product_count', 0)} products from Best Buy {country_name}!")

            if country == "US":
                st.warning("⚠️ **US Support is Experimental:** Best Buy US uses dynamic loading, so only some products may be captured. For best results, use Best Buy Canada.")

            if not deals:
                st.warning("No upgrades found matching your criteria. Try checking 'Show all products' or adjust your specs.")
            else:
                # TOP 3 DEALS SECTION
                st.markdown("---")
                st.header("🏆 Top 3 Best Deals")

                top_3 = deals[:3]
                cols = st.columns(len(top_3))

                medals = ["🥇", "🥈", "🥉"]

                for i, (col, deal) in enumerate(zip(cols, top_3)):
                    with col:
                        st.markdown(f"### {medals[i]} #{i+1}")
                        # Show condition badge if not New
                        condition = deal.get('condition', 'New')
                        if condition != 'New':
                            st.markdown(f"🏷️ **{condition}**")
                        st.markdown(f"**{deal['name'][:50]}...**")
                        st.markdown(f"💰 **${deal['price']:,.2f}**")
                        if deal['saving'] > 0:
                            st.markdown(f"🏷️ Save ${deal['saving']:.0f}")
                        st.markdown(f"🔧 CPU Gen {deal['specs']['cpu_gen']} | {deal['specs']['ram']}GB RAM")
                        # Screen info
                        screen_info = []
                        if deal['specs']['screen_size'] > 0:
                            screen_info.append(f"{deal['specs']['screen_size']}\"")
                        if deal['specs']['resolution'] != 'Unknown':
                            screen_info.append(deal['specs']['resolution'])
                        if screen_info:
                            st.markdown(f"🖥️ {' '.join(screen_info)}")
                        st.link_button("View Deal", deal['url'])

                # SANTA WISHLIST SECTION
                st.markdown("---")
                st.header("🎄 Create Your Santa Wishlist")
                st.markdown("Generate a festive wishlist to share with family (or Santa)!")

                num_items = st.slider("How many items in your wishlist?", 1, min(5, len(deals)), 3, key="upload_wishlist_num")

                # Generate wishlist HTML
                wishlist_html = generate_santa_wishlist(deals, current_specs, num_items)

                # Download button (doesn't cause rerun issues)
                st.download_button(
                    label="🎅 Download Santa Wishlist",
                    data=wishlist_html,
                    file_name="santa_wishlist.html",
                    mime="text/html",
                    type="primary",
                    key="upload_wishlist_btn"
                )

                # Preview in expander
                with st.expander("👀 Preview Wishlist"):
                    st.components.v1.html(wishlist_html, height=600, scrolling=True)

                # ALL DEALS TABLE
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
                            # Screen specs
                            if deal['specs']['screen_size'] > 0:
                                st.markdown(f"**Screen:** {deal['specs']['screen_size']}\"")
                            if deal['specs']['resolution'] != 'Unknown':
                                st.markdown(f"**Resolution:** {deal['specs']['resolution']}")
                            if deal['notes']:
                                st.markdown(f"**Upgrades:** {', '.join(deal['notes'])}")
                        with dcol2:
                            st.link_button("🔗 View on Best Buy", deal['url'])

    else:
        st.info("👆 Upload a saved Best Buy HTML file to get started!")

        # Demo section
        with st.expander("ℹ️ What does this tool do?"):
            st.markdown("""
            This tool helps you find the best laptop upgrade deals by:

            1. **Parsing** product data from a saved Best Buy webpage
            2. **Extracting** specs (CPU, RAM, Storage, GPU, Screen) from product names
            3. **Comparing** each laptop against your current computer
            4. **Ranking** deals by upgrade value and price
            5. **Creating** a festive wishlist to share with Santa! 🎅

            **No accounts needed. No data stored. Everything runs in your browser!**
            """)
