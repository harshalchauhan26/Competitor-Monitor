import ipaddress
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

import config

HEADERS = {"User-Agent": config.USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}

# Words that usually appear in blog URLs, like /blog/my-post
BLOG_WORDS = ["blog", "blogs", "article", "articles", "news", "resources", "resource",
              "insights", "learn", "guides", "guide", "stories", "posts", "journal",
              "magazine", "library", "academy", "updates"]
# Words that mean "this is NOT a post" (category pages, tag pages, page 2 ...)
SKIP_WORDS = ["tag", "tags", "category", "categories", "author", "authors", "page",
              "feed", "topic", "topics", "search", "wp-content", "wp-json", "cart", "login"]
FILE_ENDINGS = [".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".pdf", ".css", ".js", ".xml", ".zip", ".mp4"]
BLOCK_TEXT = ["just a moment", "captcha", "access denied", "verify you are human",
              "attention required", "unusual traffic"]

BLOG_PAGES = ["/blog", "/articles", "/news", "/resources", "/insights", "/learn",
              "/guides", "/stories", "/journal"]
FEED_PAGES = ["/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml",
              "/blog/feed", "/blog/rss.xml", "/blog/feed.xml"]
SITEMAP_PAGES = ["/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/post-sitemap.xml"]
PRICING_PAGES = ["/pricing", "/plans", "/price"]

# Size limits keep memory low (the free server only has 512 MB of RAM)
MAX_PAGE_BYTES = 1500000       # a normal page: 1.5 MB is plenty for title, date and description
MAX_SITEMAP_BYTES = 3000000    # a sitemap file
MAX_SITEMAP_URLS = 5000        # URLs read from one sitemap file

# Sitemap entries are read with these patterns (a lot lighter than building a full XML tree)
SITEMAP_ENTRY = re.compile(r"<(url|sitemap)>(.*?)</\1>", re.S)
LOC_PATTERN = re.compile(r"<loc>(.*?)</loc>", re.S)
LASTMOD_PATTERN = re.compile(r"<lastmod>(.*?)</lastmod>", re.S)

# A price looks like: $29   $1,200   €49.99   £10   ₹999
PRICE_PATTERN = re.compile(r"[$€£₹]\s?\d[\d,]*(?:\.\d+)?")


class ScrapeError(Exception):
    """Raised for problems we can explain to the user (blocked, unreachable, bad domain)."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- small helpers

def clean_domain(text):
    """'https://www.Example.com/blog?x=1' becomes 'example.com'."""
    text = text.strip().lower()
    text = text.replace("https://", "").replace("http://", "")
    text = text.split("/")[0].split("?")[0]
    if text.startswith("www."):
        text = text[4:]
    if "." not in text or " " in text or text == "":
        raise ScrapeError("invalid_domain", "That does not look like a valid domain. Use something like example.com")
    return text


def is_private_host(domain):
    """Safety check: do not let people scan private/internal addresses."""
    if config.ALLOW_PRIVATE_HOSTS:
        return False
    host = domain.split(":")[0]
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror:
        return False
    address = ipaddress.ip_address(ip)
    return address.is_private or address.is_loopback or address.is_link_local


def fetch(url, max_bytes=MAX_PAGE_BYTES):
    """Downloads one page (at most max_bytes). Returns (status_code, text, final_url). Status 0 means it failed."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10, stream=True)
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=65536):
            chunks.append(chunk)
            size = size + len(chunk)
            if size >= max_bytes:
                break
        response.close()
    except requests.RequestException:
        return 0, "", url

    encoding = response.encoding
    if encoding is None or encoding.lower() == "iso-8859-1":
        encoding = "utf-8"
    text = b"".join(chunks).decode(encoding, errors="replace")
    return response.status_code, text, response.url


def looks_blocked(status, text):
    if status in (401, 403, 429):
        return True
    lowered = text[:5000].lower()
    if status == 503 and "cloudflare" in lowered:
        return True
    if status == 200 and len(text) < 20000:
        for phrase in BLOCK_TEXT:
            if phrase in lowered:
                return True
    return False


def host_of(url):
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def same_site(site, url):
    return host_of(url) == site["domain"]


def clean_url(site, url):
    """Removes ?tracking, #fragments and trailing slashes so one post = one URL."""
    path = urlparse(url).path.rstrip("/")
    return site["base"] + path


def can_fetch(site, url):
    """Respects robots.txt."""
    if site["robots"] is None:
        return True
    return site["robots"].can_fetch("*", url)


def fetch_many(site, urls, max_bytes=MAX_PAGE_BYTES):
    """Downloads many pages at the same time (4 at once). Results keep the same order as urls."""
    def get_one(url):
        if not can_fetch(site, url):
            return 0, "", url
        return fetch(url, max_bytes)

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(get_one, urls))


def to_date_string(text):
    """Turns any date text into 'YYYY-MM-DD'. Returns '' if it is not a believable date."""
    if not text:
        return ""
    try:
        parsed = date_parser.parse(str(text))
    except (ValueError, OverflowError, TypeError):
        return ""
    parsed = parsed.replace(tzinfo=None)
    if parsed.year < 1995:
        return ""
    if parsed > datetime.now() + timedelta(days=2):
        return ""
    return parsed.strftime("%Y-%m-%d")


def plain_text(html, limit):
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    return text[:limit]


def path_parts(url):
    parts = []
    for part in urlparse(url).path.lower().split("/"):
        if part != "":
            parts.append(part)
    return parts


def is_bad_path(url):
    path = urlparse(url).path.lower()
    for ending in FILE_ENDINGS:
        if path.endswith(ending):
            return True
    for part in path_parts(url):
        if part in SKIP_WORDS:
            return True
    return False


def looks_like_article_url(url):
    """Guesses from the URL alone: /blog/some-post, /en/news/some-post, /2024/05/some-post"""
    if is_bad_path(url):
        return False
    parts = path_parts(url)
    if len(parts) < 2:
        return False
    if parts[-1].isdigit() and len(parts[-1]) < 4:
        return False
    if re.search(r"/(19|20)\d\d/\d\d?/", urlparse(url).path):
        return True
    for index in range(min(2, len(parts) - 1)):
        if parts[index] in BLOG_WORDS:
            return True
    return False


# ---------------------------------------------------------------- opening the site

def open_site(domain):
    """Opens the homepage. Returns (site, homepage_soup, homepage_url)."""
    if is_private_host(domain):
        raise ScrapeError("invalid_domain", "That address points to a private network and is not allowed.")

    status, text, final_url = 0, "", ""
    for start in ["https://" + domain, "https://www." + domain, "http://" + domain]:
        status, text, final_url = fetch(start + "/")
        if status != 0:
            break

    if status == 0:
        raise ScrapeError("unreachable", "Could not connect to " + domain + ". Check the spelling and that the site is online.")
    if looks_blocked(status, text):
        raise ScrapeError("blocked", domain + " is blocking bots (HTTP " + str(status) + "). Nothing was scraped. Try again later.")
    if status >= 400:
        raise ScrapeError("unreachable", domain + " returned an error (HTTP " + str(status) + ") for its homepage.")

    parts = urlparse(final_url)
    site = {"domain": domain, "base": parts.scheme + "://" + parts.netloc, "robots": None, "sitemaps": []}

    # robots.txt tells us which pages we may visit and where the sitemaps are
    robots_status, robots_text, robots_url = fetch(site["base"] + "/robots.txt")
    if robots_status == 200 and "<html" not in robots_text[:300].lower():
        parser = RobotFileParser()
        parser.parse(robots_text.splitlines())
        site["robots"] = parser
        for line in robots_text.splitlines():
            if line.lower().startswith("sitemap:"):
                site["sitemaps"].append(line.split(":", 1)[1].strip())

    soup = BeautifulSoup(text, "lxml")
    return site, soup, final_url


# ---------------------------------------------------------------- finding posts

def add_candidate(candidates, site, url, title="", date="", description="", trusted=False):
    """Adds a possible post to the candidates dictionary (or fills in missing details)."""
    if not same_site(site, url):
        return
    url = clean_url(site, url)
    if urlparse(url).path == "":
        return
    if url not in candidates:
        candidates[url] = {"url": url, "title": "", "date": "", "description": "", "trusted": False}
    item = candidates[url]
    if item["title"] == "":
        item["title"] = title
    if item["date"] == "":
        item["date"] = date
    if item["description"] == "":
        item["description"] = description
    if trusted:
        item["trusted"] = True


def xml_text(text):
    """Cleans text taken from XML: removes CDATA wrappers and turns &amp; back into &."""
    text = text.strip()
    text = text.replace("<![CDATA[", "").replace("]]>", "")
    return unescape(text).strip()


def read_sitemaps(site, sitemap_urls, candidates):
    """Reads sitemap files. Adds posts to candidates. Returns child sitemaps found inside."""
    children = []
    responses = fetch_many(site, sitemap_urls, MAX_SITEMAP_BYTES)
    for index in range(len(sitemap_urls)):
        status, text, final_url = responses[index]
        if status != 200 or "<" not in text[:100]:
            continue

        # a sitemap called post-sitemap.xml or blog-sitemap.xml only contains posts
        trusted = False
        for word in ["post", "blog", "article", "news"]:
            if word in sitemap_urls[index].lower():
                trusted = True

        url_count = 0
        for match in SITEMAP_ENTRY.finditer(text):
            kind = match.group(1)
            entry = match.group(2)
            loc = LOC_PATTERN.search(entry)
            if loc is None:
                continue
            url = xml_text(loc.group(1))

            if kind == "sitemap":
                children.append(url)
                continue

            url_count = url_count + 1
            if url_count > MAX_SITEMAP_URLS:
                break

            parts = path_parts(url)
            is_hub = len(parts) > 0 and parts[-1] in BLOG_WORDS
            if looks_like_article_url(url) or (trusted and len(parts) > 0 and not is_hub and not is_bad_path(url)):
                date = ""
                lastmod = LASTMOD_PATTERN.search(entry)
                if lastmod is not None:
                    date = to_date_string(xml_text(lastmod.group(1)))
                add_candidate(candidates, site, url, date=date, trusted=trusted)
        text = ""     # let Python free this sitemap before reading the next one
    return children


def find_in_sitemaps(site, candidates):
    start = []
    for url in site["sitemaps"]:
        if url not in start:
            start.append(url)
    for page in SITEMAP_PAGES:
        url = site["base"] + page
        if url not in start:
            start.append(url)

    children = read_sitemaps(site, start, candidates)

    # Big sites have a sitemap of sitemaps. Open up to 10 children, blog-looking ones first.
    first = []
    others = []
    for child in children:
        if child in start:
            continue
        name = child.lower()
        if "post" in name or "blog" in name or "article" in name or "news" in name:
            first.append(child)
        else:
            skip = False
            for word in ["product", "categor", "tag", "author", "image", "video", "page"]:
                if word in name:
                    skip = True
            if not skip:
                others.append(child)
    read_sitemaps(site, (first + others)[:10], candidates)


def find_in_feeds(site, soup, home_url, candidates):
    feed_urls = []
    for link in soup.find_all("link", href=True):
        link_type = (link.get("type") or "").lower()
        if "rss" in link_type or "atom" in link_type:
            feed_urls.append(urljoin(home_url, link["href"]))
    for page in FEED_PAGES:
        url = site["base"] + page
        if url not in feed_urls:
            feed_urls.append(url)

    for status, text, final_url in fetch_many(site, feed_urls):
        if status != 200:
            continue
        start = text[:500].lower()
        if "<rss" not in start and "<feed" not in start and "<rdf" not in start:
            continue

        feed = BeautifulSoup(text, "xml")
        items = feed.find_all("item")
        if len(items) == 0:
            items = feed.find_all("entry")

        for item in items:
            link_tag = item.find("link")
            if link_tag is None:
                continue
            url = link_tag.get("href")
            if not url:
                url = link_tag.get_text().strip()
            if not url:
                continue

            title = ""
            title_tag = item.find("title")
            if title_tag is not None:
                title = title_tag.get_text().strip()

            date = ""
            for name in ["pubDate", "published", "updated"]:
                date_tag = item.find(name)
                if date_tag is not None:
                    date = to_date_string(date_tag.get_text().strip())
                    break

            description = ""
            for name in ["description", "summary"]:
                description_tag = item.find(name)
                if description_tag is not None:
                    description = plain_text(description_tag.get_text(), 300)
                    break

            add_candidate(candidates, site, urljoin(final_url, url), title, date, description, trusted=True)


def find_in_blog_pages(site, soup, home_url, candidates):
    page_urls = []
    for path in BLOG_PAGES:
        page_urls.append(site["base"] + path)

    # also follow homepage links like "Blog" or "Resources"
    for link in soup.find_all("a", href=True):
        url = urljoin(home_url, link["href"])
        if not same_site(site, url):
            continue
        parts = path_parts(url)
        if len(parts) == 1 and parts[0] in BLOG_WORDS:
            url = clean_url(site, url)
            if url not in page_urls:
                page_urls.append(url)

    for status, text, final_url in fetch_many(site, page_urls):
        if status != 200 or "<html" not in text[:2000].lower():
            continue
        hub_path = urlparse(final_url).path.rstrip("/")
        if hub_path == "":
            continue    # this page just redirected to the homepage

        page = BeautifulSoup(text, "lxml")
        for link in page.find_all("a", href=True):
            url = urljoin(final_url, link["href"])
            if not same_site(site, url):
                continue
            path = urlparse(url).path.rstrip("/")
            if path == "" or path == hub_path or is_bad_path(url):
                continue

            card = link.find_parent("article")
            if card is None and not looks_like_article_url(url):
                continue

            title = link.get_text(" ", strip=True)
            date = ""
            if card is not None:
                heading = card.find(["h1", "h2", "h3", "h4"])
                if heading is not None:
                    title = heading.get_text(" ", strip=True)
                time_tag = card.find("time")
                if time_tag is not None:
                    date = to_date_string(time_tag.get("datetime") or time_tag.get_text())
            add_candidate(candidates, site, url, title=title, date=date)


def get_date(item):
    return item["date"]


def find_posts(site, soup, home_url):
    """Returns a list of possible posts, newest first."""
    candidates = {}
    find_in_sitemaps(site, candidates)
    find_in_feeds(site, soup, home_url, candidates)
    find_in_blog_pages(site, soup, home_url, candidates)

    for link in soup.find_all("a", href=True):
        url = urljoin(home_url, link["href"])
        if same_site(site, url) and looks_like_article_url(url):
            add_candidate(candidates, site, url, title=link.get_text(" ", strip=True))

    posts = list(candidates.values())
    posts.sort(key=get_date, reverse=True)
    return posts


# ---------------------------------------------------------------- reading one post

def get_meta(soup, name):
    tag = soup.find("meta", attrs={"property": name})
    if tag is None:
        tag = soup.find("meta", attrs={"name": name})
    if tag is None or not tag.get("content"):
        return ""
    return tag["content"].strip()


def search_json_for_date(data):
    """Looks inside JSON-LD data for 'datePublished'."""
    if isinstance(data, dict):
        if "datePublished" in data:
            return to_date_string(data["datePublished"])
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = search_json_for_date(value)
                if found != "":
                    return found
    if isinstance(data, list):
        for item in data:
            found = search_json_for_date(item)
            if found != "":
                return found
    return ""


def find_published_date(soup, url):
    # 1. JSON-LD data (most reliable)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except ValueError:
            continue
        found = search_json_for_date(data)
        if found != "":
            return found

    # 2. meta tags
    for name in ["article:published_time", "datePublished", "date", "pubdate", "publish-date"]:
        found = to_date_string(get_meta(soup, name))
        if found != "":
            return found

    # 3. a <time> tag
    time_tag = soup.find("time")
    if time_tag is not None:
        found = to_date_string(time_tag.get("datetime") or time_tag.get_text())
        if found != "":
            return found

    # 4. a date inside the URL, like /2024/05/my-post
    match = re.search(r"/((?:19|20)\d\d)/(\d\d?)/", url)
    if match:
        return to_date_string(match.group(1) + "-" + match.group(2) + "-01")
    return ""


def parse_post(html, url):
    """Reads one post page. Returns title, published date, description and is_article."""
    soup = BeautifulSoup(html, "lxml")

    title = get_meta(soup, "og:title")
    if title == "":
        heading = soup.find("h1")
        if heading is not None:
            title = heading.get_text(" ", strip=True)
    if title == "" and soup.title is not None:
        title = soup.title.get_text(strip=True)

    description = get_meta(soup, "description")
    if description == "":
        description = get_meta(soup, "og:description")

    published = find_published_date(soup, url)
    is_article = get_meta(soup, "og:type") == "article" or (published != "" and title != "")

    return {"title": title[:300], "published": published, "description": description[:400], "is_article": is_article}


# ---------------------------------------------------------------- pricing page

def extract_prices(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ")
    prices = []
    for found in PRICE_PATTERN.findall(text):
        price = found.replace(" ", "")
        if price not in prices:
            prices.append(price)
    prices.sort()
    return prices[:40]


def find_pricing(site, soup, home_url):
    urls = []
    for link in soup.find_all("a", href=True):
        href = link["href"].lower()
        if "pricing" in href or "/plans" in href:
            url = urljoin(home_url, link["href"])
            if same_site(site, url) and url not in urls:
                urls.append(url)
    urls = urls[:3]
    for path in PRICING_PAGES:
        url = site["base"] + path
        if url not in urls:
            urls.append(url)

    page_found = False
    page_url = ""
    for status, text, final_url in fetch_many(site, urls):
        if status != 200 or urlparse(final_url).path.strip("/") == "":
            continue
        if not page_found:
            page_found = True
            page_url = final_url
        prices = extract_prices(text)
        if len(prices) > 0:
            return {"found": True, "url": final_url, "prices": prices}
    return {"found": page_found, "url": page_url, "prices": []}