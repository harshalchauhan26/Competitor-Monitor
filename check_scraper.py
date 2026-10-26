# check_scraper.py - checks that the 5 memory fixes are in scraper.py
text = open("scraper.py", encoding="utf-8").read()

checks = {
    "1. import unescape": "from html import unescape" in text,
    "2. constants block": "MAX_PAGE_BYTES = 1500000" in text and "SITEMAP_ENTRY = re.compile" in text,
    "3. new fetch (stream)": "stream=True" in text,
    "4. new fetch_many (4 workers)": "max_workers=4" in text and "def fetch_many(site, urls, max_bytes=MAX_PAGE_BYTES)" in text,
    "5. new read_sitemaps": "def xml_text(text):" in text and 'find_all("url")' not in text,
}
for name, ok in checks.items():
    print(("OK      " if ok else "MISSING ") + name)