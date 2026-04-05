"""
Notification system for the Tech Deal Tracker.

Handles sending email notifications when deals match alert criteria.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send_email_notification(smtp_server, smtp_port, from_addr, password,
                            to_addr, subject, deals, alert_name):
    """Send an HTML email with matched deals.

    Returns True on success, False on failure.
    """
    if not all([smtp_server, from_addr, password, to_addr]):
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    text_body = format_deals_text(deals, alert_name)
    html_body = format_deals_html(deals, alert_name)

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addr, msg.as_string())
        return True
    except Exception:
        return False


def send_test_email(smtp_server, smtp_port, from_addr, password, to_addr):
    """Send a test email to verify settings.

    Returns True on success, raises Exception with details on failure.
    """
    if not from_addr:
        raise ValueError("From email is empty")
    if not to_addr:
        raise ValueError("To email is empty")
    if not password:
        raise ValueError("Email password is empty")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Tech Deal Tracker - Test Email"
    msg["From"] = from_addr
    msg["To"] = to_addr

    text = "This is a test email from the Tech Deal Tracker. Your email settings are working!"
    html = """
    <html><body style="font-family: Arial, sans-serif; padding: 20px;">
    <h2 style="color: #d32f2f;">💻 Tech Deal Tracker</h2>
    <p>This is a test email. Your notification settings are working correctly!</p>
    <p style="color: #666;">You will receive deal alerts here when products match your alert criteria.</p>
    </body></html>
    """

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    # Let exceptions propagate so the caller can show the actual error
    with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
        server.starttls()
        server.login(from_addr, password)
        server.sendmail(from_addr, to_addr, msg.as_string())
    return True


def format_deals_html(deals, alert_name):
    """Generate HTML email body from matched deals."""
    items = ""
    for deal in deals[:10]:
        saving_html = ""
        if deal.get('saving', 0) > 0:
            saving_html = f'<span style="color: #2e7d32; font-weight: bold;"> (Save ${deal["saving"]:.0f})</span>'

        price_context = ""
        if deal.get('previous_price') and deal.get('current_price'):
            price_context = f'<br><span style="color: #666;">Was: ${deal["previous_price"]:,.2f}</span>'

        retailer = deal.get('retailer_name', deal.get('source', ''))
        retailer_html = f'<span style="color: #666;">@ {retailer}</span>' if retailer else ''

        items += f"""
        <div style="border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin-bottom: 12px; background: #fafafa;">
            <strong>{deal.get('name', 'Unknown')[:80]}</strong> {retailer_html}<br>
            <span style="font-size: 1.2em; color: #d32f2f; font-weight: bold;">${deal.get('price', deal.get('current_price', 0)):,.2f}</span>
            {saving_html}{price_context}<br>
            <a href="{deal.get('url', '#')}" style="color: #1976d2;">View Deal</a>
        </div>
        """

    return f"""
    <html><body style="font-family: Arial, sans-serif; padding: 20px; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #d32f2f;">💻 Deal Alert: {alert_name}</h2>
        <p>The following {len(deals)} product(s) matched your alert criteria:</p>
        {items}
        <hr style="border: 1px solid #eee;">
        <p style="color: #999; font-size: 0.8em;">
            Sent by Tech Deal Tracker. Manage alerts in the app.
        </p>
    </body></html>
    """


def format_deals_text(deals, alert_name):
    """Generate plain-text fallback."""
    lines = [f"Deal Alert: {alert_name}", f"{len(deals)} product(s) matched:", ""]
    for deal in deals[:10]:
        price = deal.get('price', deal.get('current_price', 0))
        lines.append(f"- {deal.get('name', 'Unknown')[:60]}")
        lines.append(f"  ${price:,.2f}")
        if deal.get('url'):
            lines.append(f"  {deal['url']}")
        lines.append("")
    return "\n".join(lines)
