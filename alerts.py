import smtplib
from email.message import EmailMessage
import requests
import config



def build_message(domain, posts, price_result, first_run, last_checked):
    lines = []
    if first_run:
        lines.append("Now monitoring " + domain + ". Latest posts found:")
    else:
        since = last_checked[:10]
        if len(posts) == 1:
            lines.append(domain + " published 1 new post since " + since)
        else:
            lines.append(domain + " published " + str(len(posts)) + " new posts since " + since)

    for post in posts:
        lines.append("")
        lines.append("- " + post["title"])
        lines.append("  " + post["url"])
        published = post["published"]
        if published == "":
            published = "date not found"
        lines.append("  Published: " + published)
        lines.append("  Keyword: " + post["keyword"] + " | " + post["demand_text"])

    if price_result["status"] == "changed":
        lines.append("")
        lines.append("PRICING CHANGED: " + price_result["url"])
        lines.append("  Removed: " + ", ".join(price_result["removed"]))
        lines.append("  Added: " + ", ".join(price_result["added"]))

    return "\n".join(lines)


def send_slack(webhook, text):
    if not webhook.startswith("https://hooks.slack.com/"):
        raise ValueError("Slack webhook must start with https://hooks.slack.com/")
    response = requests.post(webhook, json={"text": text}, timeout=10)
    if response.status_code != 200:
        raise ValueError("Slack answered with HTTP " + str(response.status_code))


def send_email(to_address, subject, text):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.SMTP_USER
    message["To"] = to_address
    message.set_content(text)
    server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
    server.starttls()
    server.login(config.SMTP_USER, config.SMTP_PASSWORD)
    server.send_message(message)
    server.quit()


def send_alerts(subject, text, slack_webhook="", email_to=""):
    """Sends to every channel that is set up. Returns what worked and what failed."""
    sent = []
    errors = []

    webhook = slack_webhook or config.SLACK_WEBHOOK_URL
    address = email_to or config.ALERT_EMAIL_TO

    if webhook != "":
        try:
            send_slack(webhook, text)
            sent.append("slack")
        except (ValueError, requests.RequestException) as error:
            errors.append("Slack: " + str(error))

    if address != "" and config.SMTP_HOST != "":
        try:
            send_email(address, subject, text)
            sent.append("email")
        except (OSError, smtplib.SMTPException) as error:
            errors.append("Email: " + str(error))

    if webhook == "" and (address == "" or config.SMTP_HOST == ""):
        errors.append("No alert channel set up. Add a Slack webhook in .env or on the page.")
    return {"sent": sent, "errors": errors}
