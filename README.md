# Competitor Monitor

Enter a competitor's domain. The tool scrapes their blog and pricing page with its
own scraper, saves what it finds, and on every later check reports only what is new.

Live demo: PASTE-LINK-HERE
Demo video: PASTE-LOOM-LINK-HERE

## How it works
1. Scrapes the site: sitemaps, RSS feeds, blog listing pages and homepage links.
2. Saves every URL in a database. New = a URL we have not seen before.
3. Reads each new post: title, publish date, meta description.
4. Finds a target keyword and its demand (free Google autocomplete estimate).
5. Checks the pricing page and reports price changes.
6. Sends a Slack alert (email optional).

## Run locally
    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    (put your Slack webhook in .env)
    python app.py        (open http://127.0.0.1:8000)

## Error handling
- No blog: clear "No blog found" message
- Site blocks bots: "blocks bots" message, nothing crashes
- Invalid API key: posts still found, note shown, free estimate used
- First scan saves a baseline; second scan only reports new posts

## Known limits
- Keyword demand is a free Google autocomplete estimate (0-100), not exact search
  volume. Add a Keywords Everywhere key in .env for real volume.
- Sites that load their blog only with JavaScript are not supported.
- Only the first page of each blog listing is read.
- Prices are compared as a list of price points.