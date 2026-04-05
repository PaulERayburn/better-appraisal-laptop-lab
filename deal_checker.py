"""
Automated Deal Checker for the Tech Deal Tracker.

Standalone script designed to run via Windows Task Scheduler.
Loads active alerts, searches all scrapers, evaluates matches,
and sends email notifications.

Usage:
    python deal_checker.py                  # Run all active alerts
    python deal_checker.py --alert-id 3     # Run a specific alert
    python deal_checker.py --dry-run        # Check but don't send emails
    python deal_checker.py --verbose        # Detailed console output

Windows Task Scheduler setup:
    1. Open Task Scheduler (search "Task Scheduler" in Start)
    2. Click "Create Basic Task"
    3. Name: "Tech Deal Checker"
    4. Trigger: Daily (or set custom interval)
    5. Action: Start a Program
       Program/script: python
       Add arguments: deal_checker.py
       Start in: C:\\GitRepos\\better-appraisal-laptop-lab
    6. Click Finish
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

from config import DATA_DIR, LOG_PATH, get_serpapi_key
from database import Database
from spec_parser import extract_specs, extract_ram_specs, extract_condition, categorize_product

# Set up logging
LOG_PATH.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_PATH), encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)


def run_check(alert_id=None, dry_run=False, verbose=False):
    """Main check loop.

    1. Load active alerts from database
    2. For each alert, run scrapers with appropriate queries
    3. Upsert products and record prices
    4. Evaluate alert criteria against results
    5. Send email notifications for matches
    """
    db = Database()
    api_key = get_serpapi_key(db)

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=" * 60)
    log.info("Deal Checker starting")
    log.info(f"Time: {datetime.now().isoformat()}")
    log.info(f"Dry run: {dry_run}")

    # Load alerts
    if alert_id:
        alert = db.get_alert_by_id(alert_id)
        if not alert:
            log.error(f"Alert {alert_id} not found")
            return
        alerts = [alert]
    else:
        alerts = db.get_alerts(active_only=True)

    if not alerts:
        log.info("No active alerts to check")
        return

    log.info(f"Processing {len(alerts)} alert(s)")

    # Load email settings
    settings = db.get_all_settings()
    email_configured = all([
        settings.get('email_from'),
        settings.get('email_password'),
        settings.get('email_to'),
    ])
    if not email_configured:
        log.warning("Email not configured — matches will be logged but not emailed")

    total_matches = 0

    for alert in alerts:
        log.info(f"\n--- Alert: {alert['name']} (id={alert['id']}) ---")
        log.info(f"Category: {alert['category']}, Keyword: {alert.get('keyword')}, Max price: {alert.get('max_price')}")

        # Check cooldown
        if alert.get('last_triggered'):
            last = datetime.fromisoformat(alert['last_triggered'])
            cooldown = timedelta(hours=alert.get('cooldown_hours', 24))
            if datetime.utcnow() - last < cooldown:
                log.info(f"Skipping — cooldown active until {(last + cooldown).isoformat()}")
                continue

        # Build search query from alert criteria
        query = _build_query_for_alert(alert)
        log.info(f"Search query: {query}")

        # Run scrapers
        products = []

        # Best Buy Canada (no API key needed)
        try:
            from scrapers.bestbuy_ca import search_products as bestbuy_search
            bb_products, bb_error = bestbuy_search(query, category=alert['category'])
            if bb_products:
                for p in bb_products:
                    p['country'] = 'ca'
                products.extend(bb_products)
                log.info(f"Best Buy CA: {len(bb_products)} products")
            elif bb_error:
                log.warning(f"Best Buy CA: {bb_error}")
        except Exception as e:
            log.warning(f"Best Buy CA scraper error: {e}")

        # SerpApi Google Shopping Canada
        if api_key:
            try:
                from scrapers.serpapi_shopping import search_products as serpapi_search
                serp_products, serp_error = serpapi_search(query, category=alert['category'],
                                                           api_key=api_key, country='ca')
                if serp_products:
                    for p in serp_products:
                        p['country'] = 'ca'
                    products.extend(serp_products)
                    log.info(f"Google Shopping CA: {len(serp_products)} products")
                elif serp_error:
                    log.warning(f"Google Shopping CA: {serp_error}")
            except Exception as e:
                log.warning(f"SerpApi error: {e}")
        else:
            log.warning("SerpApi key not configured — skipping Google Shopping")

        if not products:
            log.info("No products found for this alert")
            continue

        # Filter out suspicious sellers
        from scrapers import is_trusted_retailer
        products = [p for p in products if is_trusted_retailer(p.get('source_display', '')) != 'suspicious']

        # Upsert products and record prices
        for p in products:
            specs = p.get('specs', {})
            product_dict = {
                'retailer': p.get('retailer', 'unknown'),
                'retailer_sku': p.get('retailer_sku', p.get('name', '')[:50]),
                'name': p.get('name', ''),
                'url': p.get('url', '#'),
                'category': p.get('category', alert['category']),
                'brand': p.get('brand'),
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
            db.record_price(product_id, p.get('price', 0), p.get('original_price'))

        # Evaluate alert criteria
        matches = _evaluate_alert(alert, products, db)
        log.info(f"Matches: {len(matches)}")

        if not matches:
            continue

        total_matches += len(matches)

        # Check for price drops
        if alert.get('price_drop_pct') or alert.get('price_drop_abs'):
            drop_matches = []
            for m in matches:
                pid = m.get('_product_id')
                if pid:
                    dropped, current, previous = db.check_price_drop(
                        pid, alert.get('price_drop_pct'), alert.get('price_drop_abs'))
                    if dropped:
                        m['previous_price'] = previous
                        m['current_price'] = current
                        drop_matches.append(m)
            if alert.get('price_drop_pct') or alert.get('price_drop_abs'):
                # Only notify on price drops if that's what the alert is configured for
                matches = drop_matches if drop_matches else []
                log.info(f"Price drop matches: {len(matches)}")

        if not matches:
            continue

        # Log matches
        for m in matches:
            log.info(f"  MATCH: {m.get('name', '?')[:60]} — ${m.get('price', 0):,.2f}")

        # Send notification
        if not dry_run and email_configured:
            try:
                from notifications import send_email_notification
                subject = f"Deal Alert: {alert['name']} — {len(matches)} match(es)"
                success = send_email_notification(
                    smtp_server=settings['email_smtp_server'],
                    smtp_port=int(settings['email_smtp_port']),
                    from_addr=settings['email_from'],
                    password=settings['email_password'],
                    to_addr=settings['email_to'],
                    subject=subject,
                    deals=matches,
                    alert_name=alert['name'],
                )

                if success:
                    log.info(f"Email sent to {settings['email_to']}")
                    db.update_alert(alert['id'], last_triggered=datetime.utcnow().isoformat())
                    for m in matches:
                        pid = m.get('_product_id')
                        if pid:
                            db.log_notification(alert['id'], pid, 'email', subject, True)
                else:
                    log.error("Email send failed")
                    for m in matches:
                        pid = m.get('_product_id')
                        if pid:
                            db.log_notification(alert['id'], pid, 'email', subject, False)
            except Exception as e:
                log.error(f"Email error: {e}")
        elif dry_run:
            log.info("[DRY RUN] Would have sent email notification")

    log.info(f"\nDone. Total matches across all alerts: {total_matches}")
    log.info("=" * 60)


def _build_query_for_alert(alert):
    """Convert an alert's criteria into a search query string."""
    parts = []

    if alert.get('keyword'):
        parts.append(alert['keyword'])

    category = alert.get('category', '')
    if category == 'ram':
        if alert.get('brand'):
            parts.append(alert['brand'])
        if alert.get('min_ram_gb'):
            parts.append(f"{alert['min_ram_gb']}GB")
        if alert.get('ram_type'):
            parts.append(alert['ram_type'])
        if alert.get('min_speed_mhz'):
            parts.append(f"{alert['min_speed_mhz']}MHz")
        if alert.get('form_factor'):
            parts.append("SODIMM" if alert['form_factor'] == 'SO-DIMM' else "DIMM desktop")
        if alert.get('kit_config') == '1x':
            parts.append("single stick")
        if not parts:
            parts.append("RAM memory")
    elif category == 'laptop':
        if not parts:
            parts.append("laptop")
    elif category == 'desktop':
        if not parts:
            parts.append("desktop PC")
    elif category == 'cpu':
        if not parts:
            parts.append("processor CPU")
    elif category == 'gpu':
        if not parts:
            parts.append("graphics card GPU")
    else:
        if not parts:
            parts.append(category)

    return " ".join(parts)


def _evaluate_alert(alert, products, db):
    """Check which products match an alert's criteria. Returns matching products."""
    matches = []

    for p in products:
        specs = p.get('specs', {})
        price = p.get('price', 0)

        # Keyword filter
        if alert.get('keyword'):
            if alert['keyword'].lower() not in p.get('name', '').lower():
                continue

        # Max price
        if alert.get('max_price') and price > 0:
            if price > alert['max_price']:
                continue

        # Category match
        product_cat = p.get('category', categorize_product(p.get('name', '')))
        if product_cat != alert.get('category'):
            continue

        # RAM filters
        if alert.get('min_ram_gb'):
            ram = specs.get('ram', 0)
            if ram > 0 and ram < alert['min_ram_gb']:
                continue
            if ram == 0:
                continue

        if alert.get('ram_type'):
            detected_type = specs.get('ram_type', 'Unknown')
            if detected_type != 'Unknown' and detected_type != alert['ram_type']:
                continue

        # Form factor
        if alert.get('form_factor'):
            detected_ff = specs.get('form_factor', 'Unknown')
            if detected_ff != 'Unknown' and detected_ff != alert['form_factor']:
                continue

        # Kit config
        if alert.get('kit_config'):
            detected_sticks = specs.get('stick_count', 0)
            if detected_sticks > 0:
                target = int(alert['kit_config'].replace('x', ''))
                if detected_sticks != target:
                    continue

        # Min speed
        if alert.get('min_speed_mhz'):
            detected_speed = specs.get('ram_speed_mhz', 0)
            if detected_speed > 0 and detected_speed < alert['min_speed_mhz']:
                continue

        # Max CAS latency
        if alert.get('max_cas_latency'):
            detected_cl = specs.get('cas_latency', 0)
            if detected_cl > 0 and detected_cl > alert['max_cas_latency']:
                continue

        # Brand
        if alert.get('brand'):
            detected_brand = specs.get('brand', '') or p.get('brand', '')
            if detected_brand and detected_brand.lower() != alert['brand'].lower():
                continue

        # CPU/storage filters
        if alert.get('min_cpu_gen'):
            cpu_gen = specs.get('cpu_gen', 0)
            if cpu_gen > 0 and cpu_gen < alert['min_cpu_gen']:
                continue

        if alert.get('min_storage_gb'):
            storage = specs.get('storage', 0)
            if storage > 0 and storage < alert['min_storage_gb']:
                continue

        # Retailer filter
        if alert.get('retailer'):
            if p.get('retailer') != alert['retailer']:
                continue

        # Passed all filters — it's a match
        match = {
            'name': p.get('name', ''),
            'price': price,
            'url': p.get('url', ''),
            'source': p.get('source_display', ''),
            'retailer_name': p.get('source_display', ''),
            'saving': p.get('saving', 0),
            'specs': specs,
        }

        # Try to get product_id for price drop checking
        product_dict = {
            'retailer': p.get('retailer', 'unknown'),
            'retailer_sku': p.get('retailer_sku', p.get('name', '')[:50]),
            'name': p.get('name', ''),
            'url': p.get('url', '#'),
            'category': product_cat,
        }
        pid = db.upsert_product(product_dict)
        match['_product_id'] = pid

        matches.append(match)

    return matches


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Tech Deal Tracker - Automated Checker')
    parser.add_argument('--alert-id', type=int, help='Run a specific alert by ID')
    parser.add_argument('--dry-run', action='store_true', help='Check but don\'t send emails')
    parser.add_argument('--verbose', action='store_true', help='Detailed output')
    args = parser.parse_args()

    run_check(alert_id=args.alert_id, dry_run=args.dry_run, verbose=args.verbose)
