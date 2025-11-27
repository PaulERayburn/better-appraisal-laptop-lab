"""
Best Buy Deal Finder - Web App
==============================
A Streamlit web app to find laptop upgrade deals from Best Buy Canada.
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


def extract_products_from_html(content):
    """Extract product data from Best Buy Canada's saved HTML page."""
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', content, re.DOTALL)
    if not match:
        return None, "Could not find product data in HTML file. Make sure you saved a Best Buy Canada product listing page."

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        return None, f"Failed to parse product data: {e}"

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

    if not products:
        return None, "No products found in the HTML file. Make sure you saved a page with laptop listings."

    return products, None


def analyze_deals(products, current_specs, show_all=False):
    """Analyze products and compare against current specs."""
    base_url = "https://www.bestbuy.ca"
    deals = []

    for p in products:
        name = p.get('name', '')
        price = p.get('priceWithoutEhf', 0)
        saving = p.get('saving', 0)
        sku = p.get('sku', '')

        specs = extract_specs(name)

        seo_url = p.get('seoUrl', '')
        if seo_url:
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


# Main App
st.title("💻 Best Buy Deal Finder")
st.markdown("*Find laptop upgrade deals from Best Buy Canada*")

# Sidebar - Instructions
with st.sidebar:
    st.header("📋 How to Use")
    st.markdown("""
    **Step 1:** Go to [Best Buy Canada Laptops](https://www.bestbuy.ca/en-ca/category/laptops-macbooks/20352)

    **Step 2:** Use filters to refine your search

    **Step 3:** Click **"Show More"** to load all products

    **Step 4:** Save the page:
    - **Chrome:** ⋮ menu → Cast, save, and share → Save page as...
    - **Firefox:** ≡ menu → Save Page As...
    - **Edge:** ... menu → Save page as
    - Or press `Ctrl+S` / `Cmd+S`

    **Step 5:** Upload the saved HTML file here

    **Step 6:** Enter your current specs and click Analyze!
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
        help="Upload the HTML file you saved from Best Buy Canada"
    )

with col2:
    st.header("⚙️ Your Current Specs")
    current_ram = st.number_input("RAM (GB)", min_value=1, max_value=128, value=16)
    current_storage = st.number_input("Storage (GB)", min_value=64, max_value=8000, value=512)
    current_cpu_gen = st.number_input("CPU Generation", min_value=1, max_value=20, value=10,
                                       help="e.g., 10 for Intel 10th gen i7-10750H")
    show_all = st.checkbox("Show all products (not just upgrades)")

# Process
if uploaded_file is not None:
    if st.button("🔍 Analyze Deals", type="primary"):
        with st.spinner("Analyzing products..."):
            try:
                content = uploaded_file.read().decode('utf-8')
            except UnicodeDecodeError:
                content = uploaded_file.read().decode('latin-1')

            products, error = extract_products_from_html(content)

            if error:
                st.error(error)
            else:
                st.success(f"Found {len(products)} products!")

                current_specs = {
                    'cpu_gen': current_cpu_gen,
                    'ram': current_ram,
                    'storage': current_storage
                }

                deals = analyze_deals(products, current_specs, show_all)

                if not deals:
                    st.warning("No upgrades found matching your criteria. Try checking 'Show all products' or adjust your specs.")
                else:
                    # Best Deal Highlight
                    best = deals[0]
                    st.markdown("---")
                    st.header("🏆 Best Upgrade Deal")

                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.markdown(f"### [{best['name'][:80]}...]({best['url']})")
                        st.markdown(f"**CPU:** {best['specs']['cpu_model']} (Gen {best['specs']['cpu_gen']}) | "
                                   f"**RAM:** {best['specs']['ram']}GB | "
                                   f"**Storage:** {best['specs']['storage']}GB | "
                                   f"**GPU:** {best['specs']['gpu']}")
                    with col_b:
                        st.metric("Price", f"${best['price']:,.2f}")
                        if best['saving'] > 0:
                            st.metric("You Save", f"${best['saving']:.0f}")

                    # All Deals Table
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

        **No accounts needed. No data stored. Everything runs in your browser!**
        """)
