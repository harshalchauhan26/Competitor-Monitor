import time
from datetime import datetime,timedelta
import alerts
import config
import database
import keywords
import scraper

def is_old(published):
    if published == "":
        return False
    try:
        date = datetime.strptime(published, "%Y-%m-%d")
    except ValueError:
        return False
    return datetime.now() - date > timedelta(days=config.NEW_POST_MAX_AGE_DAYS)


def check_pricing(domain, pricing_page):
    """Compares today's prices with the ones we saved last time."""
    result = {"status": "not_found", "url": pricing_page["url"], "prices": pricing_page["prices"],
              "added": [], "removed": []}

    if not pricing_page["found"]:
        return result
    if len(pricing_page["prices"]) == 0:
        result["status"] = "no_static_prices"
        return result

    old_prices = database.get_saved_prices(domain)
    if old_prices is None:
        result["status"] = "first_snapshot"
        database.save_prices(domain, pricing_page["url"], pricing_page["prices"])
        return result

    for price in pricing_page["prices"]:
        if price not in old_prices:
            result["added"].append(price)
    for price in old_prices:
        if price not in pricing_page["prices"]:
            result["removed"].append(price)

    if len(result["added"]) > 0 or len(result["removed"]) > 0:
        result["status"] = "changed"
        database.save_prices(domain, pricing_page["url"], pricing_page["prices"])
    else:
        result["status"] = "unchanged"
    return result


def run_check(domain_input, slack_webhook="", email_to="", send_alert=True):
    start_time = time.time()

    ##CLEANING DOMAIN
    try:
        domain = scraper.clean_domain(domain_input)
    except scraper.ScrapeError as error:
        return {"status": error.code, "message": error.message}

    known_urls = database.get_known_urls(domain)
    first_run = len(known_urls) == 0
    last_checked = database.get_last_checked(domain)

    #GETTING SITE
    try:
        site, soup, home_url = scraper.open_site(domain)
    except scraper.ScrapeError as error:
        return {"status": error.code, "message": error.message, "domain": domain}

    #FINDING ALL POSTS
    candidates = scraper.find_posts(site, soup, home_url)
    pricing_page = scraper.find_pricing(site, soup, home_url)

    result = {"status": "ok", "message": "", "domain": domain, "first_run": first_run,
              "new_posts": [], "total_tracked": 0, "note": "", "pricing": None, "alert": None}

    #KEEP NEW URLS
    new_candidates = []
    for item in candidates:
        if item["url"] not in known_urls:
            new_candidates.append(item)

    to_open = new_candidates[:config.MAX_POSTS_PER_RUN]
    not_opened = new_candidates[config.MAX_POSTS_PER_RUN:]

    urls_to_open = []
    for item in to_open:
        urls_to_open.append(item["url"])
    pages = scraper.fetch_many(site, urls_to_open)

    #OPEN EACH PAGE AND GET TITLE DATE DESC
    rows_to_save = []
    posts_to_report = []
    for index in range(len(to_open)):
        item = to_open[index]
        status, html, final_url = pages[index]

        if status == 0 or status >= 500:
            continue    # temporary problem: do not save, so we try again next run

        row = {"url": item["url"], "title": "", "published": "", "description": "",
               "keyword": "", "volume": None, "demand": None}

        if status == 200:
            info = scraper.parse_post(html, item["url"])
            title = info["title"] or item["title"]
            published = info["published"] or item["date"]
            description = info["description"] or item["description"]
            is_article = info["is_article"] or (item["trusted"] and title != "")

            if is_article and title != "":
                row["title"] = title
                row["published"] = published
                row["description"] = description
                if first_run or not is_old(published):
                    posts_to_report.append(row)
        rows_to_save.append(row)

    for item in not_opened:
        rows_to_save.append({"url": item["url"], "title": "", "published": "", "description": "",
                             "keyword": "", "volume": None, "demand": None})

    if first_run:
        posts_to_report = posts_to_report[:10]

    #KEYWORD DATA
    result["note"] = keywords.add_keyword_data(posts_to_report[:15])

    #SAVING IN DB
    database.save_posts(domain, rows_to_save)
    database.set_last_checked(domain)
    result["total_tracked"] = len(known_urls) + len(rows_to_save)

    # price
    result["pricing"] = check_pricing(domain, pricing_page)

    #prep of result
    for row in posts_to_report:
        result["new_posts"].append({
            "title": row["title"], "url": row["url"], "published": row["published"],
            "description": row["description"], "keyword": row["keyword"],
            "demand_text": keywords.demand_text(row),
        })

    if len(candidates) == 0:
        result["status"] = "no_blog_found"
        result["message"] = ("No blog found on " + domain + ". We checked sitemaps, RSS feeds, "
                             "common blog pages and homepage links. This site probably has no public blog.")
    elif first_run and len(posts_to_report) == 0:
        result["status"] = "no_blog_found"
        result["message"] = "Found some links, but none looked like real blog posts."
    elif first_run:
        result["message"] = ("First scan done: " + str(len(rows_to_save)) + " URLs saved. "
                             "From now on only NEW posts are reported.")
    elif len(posts_to_report) > 0:
        result["message"] = str(len(posts_to_report)) + " new post(s) since the last check."
    else:
        result["message"] = "No new posts since the last check."


#ALERT SETUP
    price_changed = result["pricing"]["status"] == "changed"
    if send_alert and result["status"] == "ok" and (len(posts_to_report) > 0 or price_changed):
        text = alerts.build_message(domain, result["new_posts"], result["pricing"], first_run, last_checked)
        if result["note"] != "":
            text = text + "\n\nNote: " + result["note"]
        result["alert"] = alerts.send_alerts("Competitor alert: " + domain, text, slack_webhook, email_to)
    else:
        result["alert"] = {"sent": [], "errors": [], "skipped": True}

    result["seconds"] = round(time.time() - start_time, 1)
    return result
        










    





