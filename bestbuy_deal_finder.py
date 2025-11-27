#!/usr/bin/env python3
"""
Best Buy Deal Finder
====================
A tool to parse Best Buy Canada "Save Page As" HTML files and find the best
laptop deals compared to your current system specs.

Usage:
    python bestbuy_deal_finder.py [--html FILE] [--ram GB] [--storage GB] [--cpu-gen N]

Example:
    python bestbuy_deal_finder.py --html "bestbuy_laptops.html" --ram 16 --storage 1800 --cpu-gen 10
"""

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
        # Generation is first 1-2 digits (12th gen = 12xxx, 13th gen = 13xxx)
        if len(model_num) == 5:
            specs['cpu_gen'] = int(model_num[:2])
        elif len(model_num) == 4:
            specs['cpu_gen'] = int(model_num[0])

    # Intel Core Ultra (newer chips, treat as gen 14+)
    ultra_match = re.search(r'(?:Core\s+)?Ultra\s*(\d+)', name, re.IGNORECASE)
    if ultra_match:
        specs['cpu_gen'] = 14  # Ultra series is newer than 13th gen
        specs['cpu_model'] = f"Ultra {ultra_match.group(1)}"

    # AMD Ryzen (e.g., Ryzen 7 7840HS)
    amd_match = re.search(r'Ryzen\s*(\d)\s*(\d{4})', name, re.IGNORECASE)
    if amd_match:
        specs['cpu_model'] = f"Ryzen {amd_match.group(1)} {amd_match.group(2)}"
        # Ryzen 7xxx series is comparable to Intel 13th gen
        series = int(amd_match.group(2)[0])
        specs['cpu_gen'] = series + 6  # Rough equivalence (7xxx ~ gen 13)

    # RAM - look for patterns like "16GB RAM" or "16GB DDR5"
    ram_patterns = [
        r'(\d+)\s*GB\s*(?:DDR\d?)?\s*RAM',
        r'(\d+)\s*GB\s*DDR\d',
        r'/\s*(\d+)\s*GB\s*/',  # "/16GB/" format
    ]
    for pattern in ram_patterns:
        ram_match = re.search(pattern, name, re.IGNORECASE)
        if ram_match:
            specs['ram'] = int(ram_match.group(1))
            break

    # Storage - look for SSD sizes
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

    # GPU - NVIDIA RTX/GTX
    gpu_match = re.search(r'(RTX\s*\d{4}(?:\s*Ti)?|GTX\s*\d{4})', name, re.IGNORECASE)
    if gpu_match:
        specs['gpu'] = gpu_match.group(1).upper().replace(" ", " ")

    return specs


def extract_products_from_html(file_path):
    """Extract product data from Best Buy Canada's saved HTML page."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    except UnicodeDecodeError:
        # Try with different encoding
        with open(file_path, 'r', encoding='latin-1') as f:
            content = f.read()

    # Look for the embedded JSON data
    match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', content, re.DOTALL)
    if not match:
        print("Error: Could not find product data in HTML file.")
        print("Make sure you saved the page using 'Save Page As' (Ctrl+S / Cmd+S)")
        sys.exit(1)

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse product data: {e}")
        sys.exit(1)

    # Navigate the JSON structure to find products
    products = []

    # Try different possible paths in the JSON structure
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
        print("Error: No products found in the HTML file.")
        print("Available data keys:", list(data.keys()))
        sys.exit(1)

    return products


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

        # Build product URL
        seo_url = p.get('seoUrl', '')
        if seo_url:
            url = seo_url if seo_url.startswith('http') else base_url + seo_url
        else:
            url = f"{base_url}/en-ca/product/{sku}"

        # Compare to current specs
        better_cpu = specs['cpu_gen'] > current_specs['cpu_gen']
        better_ram = specs['ram'] > current_specs['ram']
        better_storage = specs['storage'] >= current_specs['storage']

        # Build comparison notes
        notes = []
        if better_cpu:
            notes.append(f"CPU+ (Gen {specs['cpu_gen']})")
        if better_ram:
            notes.append(f"RAM+ ({specs['ram']}GB)")
        if better_storage:
            notes.append(f"Storage+ ({specs['storage']}GB)")
        elif specs['storage'] > 0 and specs['storage'] < current_specs['storage']:
            notes.append(f"Storage- ({specs['storage']}GB)")

        # Calculate upgrade score
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
            'name_short': (name[:55] + "...") if len(name) > 55 else name,
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

    # Sort by score (descending), then by price (ascending)
    deals.sort(key=lambda x: (-x['score'], x['price']))

    return deals


def print_deals_table(deals, current_specs):
    """Print deals in a formatted table."""
    if not deals:
        print("\nNo upgrades found matching your criteria.")
        return

    print(f"\n{'='*100}")
    print(f"LAPTOP DEALS - Compared to your specs: CPU Gen {current_specs['cpu_gen']}, "
          f"RAM {current_specs['ram']}GB, Storage {current_specs['storage']}GB")
    print(f"{'='*100}")

    header = f"{'Name':<58} | {'Price':>10} | {'Savings':>10} | {'Notes'}"
    print(header)
    print("-" * 100)

    for d in deals:
        savings_str = f"${d['saving']:.0f}" if d['saving'] > 0 else "-"
        notes_str = ", ".join(d['notes']) if d['notes'] else "-"
        print(f"{d['name_short']:<58} | ${d['price']:>9,.2f} | {savings_str:>10} | {notes_str}")

    # Show best deal
    if deals:
        best = deals[0]
        print(f"\n{'*'*60}")
        print("  BEST UPGRADE DEAL FOUND")
        print(f"{'*'*60}")
        print(f"  Product: {best['name'][:70]}")
        print(f"  Price:   ${best['price']:,.2f}")
        if best['saving'] > 0:
            print(f"  Savings: ${best['saving']:.0f}")
        print(f"  Specs:   CPU Gen {best['specs']['cpu_gen']}, "
              f"RAM {best['specs']['ram']}GB, "
              f"Storage {best['specs']['storage']}GB, "
              f"GPU: {best['specs']['gpu']}")
        print(f"  Link:    {best['url']}")
        print(f"{'*'*60}")


def generate_wishlist_html(deals, output_path="wishlist.html", top_n=3):
    """Generate a nice HTML wishlist page with top deals."""
    top_deals = deals[:top_n]

    items_html = ""
    for i, deal in enumerate(top_deals, 1):
        savings_html = ""
        if deal['saving'] > 0:
            savings_html = f'<div class="savings">Save ${deal["saving"]:.0f}!</div>'

        specs_html = ""
        if deal['specs']['cpu_gen'] > 0:
            specs_html += f"<li><strong>CPU:</strong> {deal['specs']['cpu_model']} (Gen {deal['specs']['cpu_gen']})</li>\n"
        if deal['specs']['ram'] > 0:
            specs_html += f"<li><strong>RAM:</strong> {deal['specs']['ram']}GB</li>\n"
        if deal['specs']['storage'] > 0:
            specs_html += f"<li><strong>Storage:</strong> {deal['specs']['storage']}GB SSD</li>\n"
        if deal['specs']['gpu'] != 'Integrated':
            specs_html += f"<li><strong>GPU:</strong> {deal['specs']['gpu']}</li>\n"

        notes_text = ", ".join(deal['notes']) if deal['notes'] else "Good value"

        items_html += f'''
    <div class="item">
        <h2>{i}. {deal['name'][:60]}{'...' if len(deal['name']) > 60 else ''}</h2>
        <ul class="specs">
            {specs_html}
        </ul>
        <div class="price-tag">${deal['price']:,.2f}</div>
        {savings_html}
        <p class="upgrade-notes">Upgrades: {notes_text}</p>
        <a href="{deal['url']}" class="btn" target="_blank">View Product</a>
    </div>
'''

    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>My Laptop Wishlist</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            margin: 0;
            padding: 20px;
            min-height: 100vh;
        }}
        .container {{
            background-color: #fff;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        h1 {{
            text-align: center;
            color: #4a4a4a;
            margin-bottom: 10px;
        }}
        .subtitle {{
            text-align: center;
            color: #666;
            margin-bottom: 30px;
        }}
        .item {{
            border: 1px solid #e0e0e0;
            border-radius: 10px;
            margin-bottom: 20px;
            padding: 25px;
            background: linear-gradient(to right, #fafafa, #fff);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .item:hover {{
            transform: translateY(-3px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.1);
        }}
        .item h2 {{
            margin-top: 0;
            color: #4a4a4a;
            font-size: 1.2em;
        }}
        .specs {{
            list-style-type: none;
            padding: 0;
            margin: 15px 0;
        }}
        .specs li {{
            margin-bottom: 8px;
            padding-left: 25px;
            position: relative;
            color: #555;
        }}
        .specs li::before {{
            content: "\\2713";
            position: absolute;
            left: 0;
            color: #28a745;
            font-weight: bold;
        }}
        .price-tag {{
            font-size: 1.4em;
            font-weight: bold;
            color: #2c3e50;
        }}
        .savings {{
            font-size: 1em;
            color: #28a745;
            font-weight: bold;
            margin-top: 5px;
        }}
        .upgrade-notes {{
            color: #666;
            font-size: 0.9em;
            font-style: italic;
        }}
        .btn {{
            display: inline-block;
            margin-top: 15px;
            padding: 12px 25px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-decoration: none;
            border-radius: 25px;
            font-weight: bold;
            transition: opacity 0.2s;
        }}
        .btn:hover {{
            opacity: 0.9;
        }}
        .footer {{
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #eee;
            color: #888;
            font-size: 0.85em;
        }}
    </style>
</head>
<body>

<div class="container">
    <h1>My Laptop Wishlist</h1>
    <p class="subtitle">Top {top_n} upgrade options based on my analysis</p>
    {items_html}
    <div class="footer">
        <p>Generated with Best Buy Deal Finder</p>
        <p><a href="https://github.com/YOUR_USERNAME/bestbuy-deal-finder">View on GitHub</a></p>
    </div>
</div>

</body>
</html>
'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"\nWishlist saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Find the best laptop deals from Best Buy Canada",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bestbuy_deal_finder.py --html "saved_page.html"
  python bestbuy_deal_finder.py --html "laptops.html" --ram 16 --storage 1024 --cpu-gen 10
  python bestbuy_deal_finder.py --html "laptops.html" --wishlist --top 5
        """
    )

    parser.add_argument('--html', '-f', type=str, required=True,
                        help='Path to the saved Best Buy HTML file')
    parser.add_argument('--ram', type=int, default=16,
                        help='Your current RAM in GB (default: 16)')
    parser.add_argument('--storage', type=int, default=512,
                        help='Your current storage in GB (default: 512)')
    parser.add_argument('--cpu-gen', type=int, default=10,
                        help='Your current CPU generation (default: 10)')
    parser.add_argument('--all', action='store_true',
                        help='Show all products, not just upgrades')
    parser.add_argument('--wishlist', '-w', action='store_true',
                        help='Generate an HTML wishlist file')
    parser.add_argument('--output', '-o', type=str, default='wishlist.html',
                        help='Output path for wishlist HTML (default: wishlist.html)')
    parser.add_argument('--top', type=int, default=3,
                        help='Number of top deals to include in wishlist (default: 3)')

    args = parser.parse_args()

    current_specs = {
        'cpu_gen': args.cpu_gen,
        'ram': args.ram,
        'storage': args.storage
    }

    print(f"Loading products from: {args.html}")
    products = extract_products_from_html(args.html)
    print(f"Found {len(products)} products")

    print(f"\nYour current specs: CPU Gen {current_specs['cpu_gen']}, "
          f"RAM {current_specs['ram']}GB, Storage {current_specs['storage']}GB")
    print("Finding upgrades...")

    deals = analyze_deals(products, current_specs, show_all=args.all)
    print(f"Found {len(deals)} {'products' if args.all else 'potential upgrades'}")

    print_deals_table(deals, current_specs)

    if args.wishlist and deals:
        generate_wishlist_html(deals, args.output, args.top)


if __name__ == "__main__":
    main()
