"""
Best Buy Deal Finder - Web App
==============================
A Streamlit web app to find laptop upgrade deals from Best Buy (US & Canada).
Upload a saved HTML file and compare against your current specs.
"""

import streamlit as st
import json
import re

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


def extract_specs(name):
    """Extract CPU, RAM, Storage, and GPU specs from a product name string."""
    specs = {
        'cpu_gen': 0,
        'cpu_model': 'Unknown',
        'ram': 0,
        'storage': 0,
        'gpu': 'Integrated'
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

        notes = []
        if better_cpu:
            notes.append(f"CPU+ (Gen {specs['cpu_gen']})")
        if better_ram:
            notes.append(f"RAM+ ({specs['ram']}GB)")
        if better_storage:
            notes.append(f"Storage+ ({specs['storage']}GB)")
        elif specs['storage'] > 0 and specs['storage'] < current_specs['storage']:
            notes.append(f"Storage- ({specs['storage']}GB)")

        score = 0
        if better_cpu:
            score += 2
        if better_ram:
            score += 2
        if better_storage:
            score += 1
        if saving > 0:
            score += 1

        deal = {
            'name': name,
            'price': price,
            'saving': saving,
            'specs': specs,
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

        items_html += f'''
    <div class="item">
        <h2>{i+1}. {title}</h2>
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
    **Step 1:** Go to Best Buy Laptops:
    - 🇨🇦 [Best Buy Canada](https://www.bestbuy.ca/en-ca/category/laptops-macbooks/20352)
    - 🇺🇸 [Best Buy US](https://www.bestbuy.com/site/laptop-computers/all-laptops/pcmcat138500050001.c)

    **Step 2:** Use filters to refine your search

    **Step 3:** Click **"Show More"** to load all products

    **Step 4:** Save the page:
    - **Chrome:** ⋮ menu → Cast, save, and share → Save page as...
    - **Firefox:** ≡ menu → Save Page As...
    - **Edge:** ... menu → Save page as
    - Or press `Ctrl+S` / `Cmd+S`

    **Step 5:** Upload the saved HTML file here

    **Step 6:** Enter your current specs and click Analyze!

    *The app auto-detects US vs Canada format!*
    """)

    st.markdown("---")
    st.markdown("Made with ❤️ | [GitHub](https://github.com/PaulERayburn/bestbuy-deal-finder)")

# Main content
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
    current_ram = st.number_input("RAM (GB)", min_value=1, max_value=128, value=16)
    current_storage = st.number_input("Storage (GB)", min_value=64, max_value=8000, value=512)
    current_cpu_gen = st.number_input("CPU Generation", min_value=1, max_value=20, value=10,
                                       help="e.g., 10 for Intel 10th gen i7-10750H")
    show_all = st.checkbox("Show all products (not just upgrades)")

# Initialize session state
if 'deals' not in st.session_state:
    st.session_state['deals'] = None
if 'current_specs' not in st.session_state:
    st.session_state['current_specs'] = None
if 'analyzed' not in st.session_state:
    st.session_state['analyzed'] = False

# Process
if uploaded_file is not None:
    # Analyze button
    if st.button("🔍 Analyze Deals", type="primary"):
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
                    'storage': current_storage
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
                    st.markdown(f"**{deal['name'][:50]}...**")
                    st.markdown(f"💰 **${deal['price']:,.2f}**")
                    if deal['saving'] > 0:
                        st.markdown(f"🏷️ Save ${deal['saving']:.0f}")
                    st.markdown(f"🔧 CPU Gen {deal['specs']['cpu_gen']} | {deal['specs']['ram']}GB RAM")
                    st.link_button("View Deal", deal['url'])

            # SANTA WISHLIST SECTION
            st.markdown("---")
            st.header("🎄 Create Your Santa Wishlist")
            st.markdown("Generate a festive wishlist to share with family (or Santa)!")

            num_items = st.slider("How many items in your wishlist?", 1, min(5, len(deals)), 3)

            # Generate wishlist HTML
            wishlist_html = generate_santa_wishlist(deals, current_specs, num_items)

            # Download button (doesn't cause rerun issues)
            st.download_button(
                label="🎅 Download Santa Wishlist",
                data=wishlist_html,
                file_name="santa_wishlist.html",
                mime="text/html",
                type="primary"
            )

            # Preview in expander
            with st.expander("👀 Preview Wishlist"):
                st.components.v1.html(wishlist_html, height=600, scrolling=True)

            # ALL DEALS TABLE
            st.markdown("---")
            st.header(f"📊 All {'Products' if show_all else 'Upgrades'} ({len(deals)})")

            for i, deal in enumerate(deals):
                with st.expander(f"**{i+1}. {deal['name'][:70]}...** — ${deal['price']:,.2f}" +
                                (f" (Save ${deal['saving']:.0f})" if deal['saving'] > 0 else "")):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.markdown(f"**CPU:** {deal['specs']['cpu_model']} (Gen {deal['specs']['cpu_gen']})")
                        st.markdown(f"**RAM:** {deal['specs']['ram']}GB")
                        st.markdown(f"**Storage:** {deal['specs']['storage']}GB")
                        st.markdown(f"**GPU:** {deal['specs']['gpu']}")
                        if deal['notes']:
                            st.markdown(f"**Upgrades:** {', '.join(deal['notes'])}")
                    with col2:
                        st.link_button("🔗 View on Best Buy", deal['url'])

else:
    st.info("👆 Upload a saved Best Buy HTML file to get started!")

    # Demo section
    with st.expander("ℹ️ What does this tool do?"):
        st.markdown("""
        This tool helps you find the best laptop upgrade deals by:

        1. **Parsing** product data from a saved Best Buy Canada webpage
        2. **Extracting** specs (CPU, RAM, Storage, GPU) from product names
        3. **Comparing** each laptop against your current computer
        4. **Ranking** deals by upgrade value and price
        5. **Creating** a festive wishlist to share with Santa! 🎅

        **No accounts needed. No data stored. Everything runs in your browser!**
        """)
