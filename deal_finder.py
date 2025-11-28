#!/usr/bin/env python3
"""
Laptop Deal Finder
==================
A tool to parse Best Buy Canada and Amazon.ca "Save Page As" HTML files and find
the best laptop deals compared to your current system specs.

Supports:
    - Best Buy Canada (bestbuy.ca)
    - Amazon Canada (amazon.ca)

Usage:
    python deal_finder.py [--html FILE] [--ram GB] [--storage GB] [--cpu-gen N]

Examples:
    python deal_finder.py --html "bestbuy_laptops.html" --ram 16 --storage 1800 --cpu-gen 10
    python deal_finder.py --html "amazon_laptops.html" --ram 32 --storage 1024 --cpu-gen 12

License: AGPL-3.0 - Contributions welcome! See CONTRIBUTING.md for details.
"""

import html as html_module
import json
import re
import argparse
import sys
from pathlib import Path


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
    specs = {'cpu_gen': 0, 'cpu_model': 'Unknown', 'ram': 0, 'storage': 0, 'gpu': 'Integrated'}

    # Intel Core iX-XXXXX
    intel_match = re.search(r'(i\d)-(\d{4,5})', name)
    if intel_match:
        specs['cpu_model'] = f"{intel_match.group(1)}-{intel_match.group(2)}"
        model_num = intel_match.group(2)
        specs['cpu_gen'] = int(model_num[:2]) if len(model_num) == 5 else int(model_num[0])

    # Intel Core Ultra
    ultra_match = re.search(r'(?:Core\s+)?Ultra\s*(\d+)', name, re.IGNORECASE)
    if ultra_match:
        specs['cpu_gen'] = 14
        specs['cpu_model'] = f"Ultra {ultra_match.group(1)}"

    # AMD Ryzen (including AI variants)
    amd_match = re.search(r'Ryzen\s*(?:AI\s*)?(\d)\s*(\d{3,4})', name, re.IGNORECASE)
    if amd_match:
        specs['cpu_model'] = f"Ryzen {amd_match.group(1)} {amd_match.group(2)}"
        specs['cpu_gen'] = int(amd_match.group(2)[0]) + 6

    # Qualcomm Snapdragon X
    snapdragon_match = re.search(r'Snapdragon\s*X\s*(Plus|Elite)?', name, re.IGNORECASE)
    if snapdragon_match:
        specs['cpu_gen'] = 14
        specs['cpu_model'] = f"Snapdragon X {snapdragon_match.group(1) or ''}".strip()

    # RAM patterns
    for pattern in [r'(\d+)\s*GB\s*(?:LP)?DDR\d?\s*RAM', r'(\d+)\s*GB\s*(?:LP)?DDR\d',
                    r'(\d+)\s*GB\s+RAM', r',\s*(\d+)\s*GB\s+RAM']:
        ram_match = re.search(pattern, name, re.IGNORECASE)
        if ram_match:
            specs['ram'] = int(ram_match.group(1))
            break

    # Storage patterns
    for pattern in [r'(\d+(?:\.\d+)?)\s*(TB|GB)\s*SSD', r'(\d+(?:\.\d+)?)\s*(TB|GB)\s*(?:NVMe|PCIe)']:
        storage_match = re.search(pattern, name, re.IGNORECASE)
        if storage_match:
            specs['storage'] = parse_size(f"{storage_match.group(1)}{storage_match.group(2)}")
            break

    # GPU
    gpu_match = re.search(r'(RTX\s*\d{4}(?:\s*Ti)?|GTX\s*\d{4})', name, re.IGNORECASE)
    if gpu_match:
        specs['gpu'] = gpu_match.group(1).upper()

    return specs


def detect_source(content):
    """Detect whether the HTML is from Best Buy or Amazon."""
    if 'amazon.ca' in content.lower() or 'amazon.com' in content.lower() or 'data-asin=' in content:
        return 'amazon'
    elif 'bestbuy.ca' in content.lower() or '__INITIAL_STATE__' in content:
        return 'bestbuy'
    return 'unknown'


def extract_products_from_amazon_html(content):
    """Extract product data from Amazon.ca saved HTML page."""
    products = []
    seen_asins = set()

    asin_pattern = re.compile(r'data-asin="([A-Z0-9]{10})"[^>]*data-component-type="s-search-result"', re.IGNORECASE)
    asins = asin_pattern.findall(content)

    for asin in asins:
        if asin in seen_asins or not asin:
            continue
        seen_asins.add(asin)

        block_pattern = re.compile(
            rf'data-asin="{asin}".*?<h2[^>]*aria-label="([^"]+)"[^>]*>.*?<span class="a-offscreen">([^<]+)</span>',
            re.DOTALL | re.IGNORECASE
        )
        match = block_pattern.search(content)
        if match:
            name = html_module.unescape(match.group(1))
            price_str = match.group(2)
            price_match = re.search(r'\$?([\d,]+(?:\.\d{2})?)', price_str)
            price = float(price_match.group(1).replace(',', '')) if price_match else 0

            # Check for original price
            was_pattern = re.compile(rf'data-asin="{asin}".*?Was:.*?<span class="a-offscreen">([^<]+)</span>', re.DOTALL | re.IGNORECASE)
            was_match = was_pattern.search(content)
            original_price = 0
            if was_match:
                orig_match = re.search(r'\$?([\d,]+(?:\.\d{2})?)', was_match.group(1))
                if orig_match:
                    original_price = float(orig_match.group(1).replace(',', ''))

            products.append({
                'name': name, 'price': price, 'saving': max(0, original_price - price),
                'sku': asin, 'asin': asin, 'url': f"https://www.amazon.ca/dp/{asin}", 'source': 'amazon'
            })
    return products


def extract_products_from_bestbuy_html(content):
    """Extract product data from Best Buy Canada's saved HTML page."""
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', content, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    products = []
    if 'productList' in data and 'data' in data['productList']:
        p_data = data['productList']['data']
        if p_data:
            products = p_data.get('products', p_data.get('results', []))
    if not products and 'search' in data:
        search = data['search']
        if 'searchResult' in search:
            products = search['searchResult'].get('results', search['searchResult'].get('products', []))
        elif 'results' in search:
            products = search['results']

    for p in products:
        p['source'] = 'bestbuy'
    return products


def extract_products_from_html(file_path):
    """Extract product data from saved HTML page (auto-detects source)."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    except UnicodeDecodeError:
        with open(file_path, 'r', encoding='latin-1') as f:
            content = f.read()

    source = detect_source(content)
    print(f"Detected source: {source.upper()}")

    if source == 'amazon':
        products = extract_products_from_amazon_html(content)
        if not products:
            print("Error: No products found in Amazon HTML. Save search results page as HTML only.")
            sys.exit(1)
        return products
    elif source == 'bestbuy':
        products = extract_products_from_bestbuy_html(content)
        if not products:
            print("Error: Could not find product data in Best Buy HTML.")
            sys.exit(1)
        return products
    else:
        print("Error: Could not detect source (Best Buy or Amazon).")
        sys.exit(1)


def analyze_deals(products, current_specs, show_all=False):
    """Analyze products and compare against current specs."""
    deals = []
    for p in products:
        source = p.get('source', 'bestbuy')
        name = p.get('name', '')

        if source == 'amazon':
            price, saving, sku = p.get('price', 0), p.get('saving', 0), p.get('asin', '')
            url = p.get('url', f"https://www.amazon.ca/dp/{sku}")
        else:
            price, saving, sku = p.get('priceWithoutEhf', 0), p.get('saving', 0), p.get('sku', '')
            seo_url = p.get('seoUrl', '')
            url = (seo_url if seo_url.startswith('http') else f"https://www.bestbuy.ca{seo_url}") if seo_url else f"https://www.bestbuy.ca/en-ca/product/{sku}"

        specs = extract_specs(name)
        better_cpu = specs['cpu_gen'] > current_specs['cpu_gen']
        better_ram = specs['ram'] > current_specs['ram']
        better_storage = specs['storage'] >= current_specs['storage']

        notes = []
        if better_cpu: notes.append(f"CPU+ (Gen {specs['cpu_gen']})")
        if better_ram: notes.append(f"RAM+ ({specs['ram']}GB)")
        if better_storage: notes.append(f"Storage+ ({specs['storage']}GB)")
        elif specs['storage'] > 0 and specs['storage'] < current_specs['storage']:
            notes.append(f"Storage- ({specs['storage']}GB)")

        score = (2 if better_cpu else 0) + (2 if better_ram else 0) + (1 if better_storage else 0) + (1 if saving > 0 else 0)

        deal = {
            'name': name, 'name_short': (name[:55] + "...") if len(name) > 55 else name,
            'price': price, 'saving': saving, 'specs': specs, 'notes': notes,
            'score': score, 'url': url, 'sku': sku, 'source': source,
            'is_upgrade': better_cpu or better_ram
        }
        if show_all or deal['is_upgrade']:
            deals.append(deal)

    deals.sort(key=lambda x: (-x['score'], x['price']))
    return deals


def print_deals_table(deals, current_specs):
    """Print deals in a formatted table."""
    if not deals:
        print("\nNo upgrades found matching your criteria.")
        return

    print(f"\n{'='*100}")
    print(f"LAPTOP DEALS - Compared to: CPU Gen {current_specs['cpu_gen']}, RAM {current_specs['ram']}GB, Storage {current_specs['storage']}GB")
    print(f"{'='*100}")
    print(f"{'Name':<58} | {'Price':>10} | {'Savings':>10} | {'Notes'}")
    print("-" * 100)

    for d in deals:
        savings_str = f"${d['saving']:.0f}" if d['saving'] > 0 else "-"
        notes_str = ", ".join(d['notes']) if d['notes'] else "-"
        print(f"{d['name_short']:<58} | ${d['price']:>9,.2f} | {savings_str:>10} | {notes_str}")

    if deals:
        best = deals[0]
        print(f"\n{'*'*60}\n  BEST UPGRADE DEAL FOUND\n{'*'*60}")
        print(f"  Source:  {best['source'].upper()}")
        print(f"  Product: {best['name'][:70]}")
        print(f"  Price:   ${best['price']:,.2f}")
        if best['saving'] > 0: print(f"  Savings: ${best['saving']:.0f}")
        print(f"  Specs:   CPU Gen {best['specs']['cpu_gen']}, RAM {best['specs']['ram']}GB, Storage {best['specs']['storage']}GB, GPU: {best['specs']['gpu']}")
        print(f"  Link:    {best['url']}\n{'*'*60}")


def main():
    parser = argparse.ArgumentParser(
        description="Find the best laptop deals from Best Buy Canada or Amazon.ca",
        epilog="Note: Amazon.com (US) has filtering issues. For US support, see CONTRIBUTING.md for API options."
    )
    parser.add_argument('--html', '-f', type=str, required=True, help='Path to saved HTML file')
    parser.add_argument('--ram', type=int, default=16, help='Your current RAM in GB')
    parser.add_argument('--storage', type=int, default=512, help='Your current storage in GB')
    parser.add_argument('--cpu-gen', type=int, default=10, help='Your current CPU generation')
    parser.add_argument('--all', action='store_true', help='Show all products')
    args = parser.parse_args()

    current_specs = {'cpu_gen': args.cpu_gen, 'ram': args.ram, 'storage': args.storage}
    print(f"Loading products from: {args.html}")
    products = extract_products_from_html(args.html)
    print(f"Found {len(products)} products")
    print(f"\nYour specs: CPU Gen {current_specs['cpu_gen']}, RAM {current_specs['ram']}GB, Storage {current_specs['storage']}GB")

    deals = analyze_deals(products, current_specs, show_all=args.all)
    print(f"Found {len(deals)} {'products' if args.all else 'potential upgrades'}")
    print_deals_table(deals, current_specs)


if __name__ == "__main__":
    main()
