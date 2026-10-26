import json
import sqlite3
from datetime import datetime

import config

USING_POSTGRES=config.DATABASE_URL.startswith("postgres")

def get_connection():
    if USING_POSTGRES:
        import psycopg2
        import psycopg2.extras
        return psycopg2.connect(config.DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    connection = sqlite3.connect(config.SQLITE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def run_sql(sql, params=(), fetch=""):
    """Runs one SQL command. fetch can be '', 'one' or 'all'."""
    if USING_POSTGRES:
        sql = sql.replace("?", "%s")   # Postgres uses %s instead of ?
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(sql, params)
    result = None
    if fetch == "one":
        result = cursor.fetchone()
    if fetch == "all":
        result = cursor.fetchall()
    connection.commit()
    cursor.close()
    connection.close()
    return result


def create_tables():
    if USING_POSTGRES:
        id_column = "SERIAL PRIMARY KEY"
    else:
        id_column = "INTEGER PRIMARY KEY AUTOINCREMENT"

    run_sql("CREATE TABLE IF NOT EXISTS sites (domain TEXT PRIMARY KEY, last_checked TEXT)")
    run_sql(
        "CREATE TABLE IF NOT EXISTS posts ("
        "id " + id_column + ", domain TEXT, url TEXT, title TEXT, published TEXT, "
        "description TEXT, keyword TEXT, volume INTEGER, demand INTEGER, first_seen TEXT, "
        "UNIQUE (domain, url))"
    )
    run_sql(
        "CREATE TABLE IF NOT EXISTS pricing ("
        "domain TEXT PRIMARY KEY, url TEXT, prices TEXT, checked TEXT)"
    )


def get_known_urls(domain):
    rows = run_sql("SELECT url FROM posts WHERE domain = ?", (domain,), "all")
    urls = set()
    for row in rows:
        urls.add(row["url"])
    return urls


def save_posts(domain, posts):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for post in posts:
        run_sql(
            "INSERT INTO posts (domain, url, title, published, description, keyword, volume, demand, first_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (domain, url) DO NOTHING",
            (domain, post["url"], post["title"], post["published"], post["description"],
             post["keyword"], post["volume"], post["demand"], now),
        )


def get_last_checked(domain):
    row = run_sql("SELECT last_checked FROM sites WHERE domain = ?", (domain,), "one")
    if row is None:
        return ""
    return row["last_checked"]


def set_last_checked(domain):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_sql(
        "INSERT INTO sites (domain, last_checked) VALUES (?, ?) "
        "ON CONFLICT (domain) DO UPDATE SET last_checked = excluded.last_checked",
        (domain, now),
    )


def get_saved_prices(domain):
    """Returns the saved price list, or None if we never saved one."""
    row = run_sql("SELECT prices FROM pricing WHERE domain = ?", (domain,), "one")
    if row is None:
        return None
    return json.loads(row["prices"])


def save_prices(domain, url, prices):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_sql(
        "INSERT INTO pricing (domain, url, prices, checked) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (domain) DO UPDATE SET url = excluded.url, prices = excluded.prices, checked = excluded.checked",
        (domain, url, json.dumps(prices), now),
    )


def list_sites():
    sites = run_sql("SELECT domain, last_checked FROM sites ORDER BY last_checked DESC", (), "all")
    counts = run_sql("SELECT domain, COUNT(*) AS total FROM posts GROUP BY domain", (), "all")
    count_by_domain = {}
    for row in counts:
        count_by_domain[row["domain"]] = row["total"]

    result = []
    for site in sites:
        result.append({
            "domain": site["domain"],
            "last_checked": site["last_checked"],
            "urls_tracked": count_by_domain.get(site["domain"], 0),
        })
    return result


def reset_site(domain):
    run_sql("DELETE FROM posts WHERE domain = ?", (domain,))
    run_sql("DELETE FROM pricing WHERE domain = ?", (domain,))
    run_sql("DELETE FROM sites WHERE domain = ?", (domain,))

