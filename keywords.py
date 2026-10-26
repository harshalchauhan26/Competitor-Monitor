import re
import requests
import config

class KeywordApiError(Exception):
    pass

def trim_words(words):
    """Removes boring words at the start and end, like 'an' or 'of'."""
    words = list(words)
    while len(words) > 0 and words[0] in ["a", "an", "the"]:
        words.pop(0)
    while len(words) > 0 and words[-1] in ["a", "an", "the", "of", "on", "in", "to", "for", "and", "or", "with", "is", "it", "vs"]:
        words.pop()
    return words


def make_keywords(title, url):
    """Turns a post title into up to 2 keyword guesses: the full phrase and a shorter one."""
    text = title
    for separator in [" | ", " - ", " – ", " — ", ":"]:
        if separator in text:
            text = text.split(separator)[0]

    if text.strip() == "":
        text = url.rstrip("/").split("/")[-1].replace("-", " ")

    text = text.lower()
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9 ]", " ", text)

    words = []
    for word in text.split():
        is_year = len(word) == 4 and word.isdigit() and word[:2] in ("19", "20")
        if not is_year:
            words.append(word)
    while len(words) > 0 and words[0].isdigit():
        words.pop(0)

    results = []
    full_phrase = trim_words(words[:6])
    if len(full_phrase) > 0:
        results.append(" ".join(full_phrase))
    short_phrase = trim_words(words[:3])
    if len(short_phrase) >= 2 and " ".join(short_phrase) not in results:
        results.append(" ".join(short_phrase))
    return results


def autocomplete_score(keyword):
    """Asks Google autocomplete. Returns 0-100, or None if Google could not be reached."""
    try:
        response = requests.get(
            config.SUGGEST_URL,
            params={"client": "firefox", "q": keyword},
            timeout=8,
        )
        suggestions = response.json()[1]
    except (requests.RequestException, ValueError, IndexError):
        return None

    if len(suggestions) == 0:
        return 0
    for position in range(len(suggestions)):
        if suggestions[position].lower().strip() == keyword:
            return 90 - position * 3       # people really type this exact phrase
    for suggestion in suggestions:
        if suggestion.lower().startswith(keyword):
            return 50                      # people type longer versions of it
    return 20


def keywords_everywhere_volume(keyword):
    """Real monthly search volume (needs a paid API key)."""
    try:
        response = requests.post(
            config.KE_URL,
            headers={"Authorization": "Bearer " + config.KEYWORDS_EVERYWHERE_API_KEY, "Accept": "application/json"},
            data={"country": "us", "currency": "USD", "dataSource": "gkp", "kw[]": [keyword]},
            timeout=15,
        )
    except requests.RequestException:
        raise KeywordApiError("Keywords Everywhere could not be reached")

    if response.status_code in (401, 403):
        raise KeywordApiError("Keywords Everywhere API key is invalid")
    if response.status_code == 402:
        raise KeywordApiError("Keywords Everywhere has no credits left")
    if response.status_code != 200:
        raise KeywordApiError("Keywords Everywhere error " + str(response.status_code))

    data = response.json().get("data", [])
    if len(data) == 0:
        return 0
    return data[0].get("vol", 0)


def add_keyword_data(posts):
    """Adds keyword, volume and demand to each post. Returns a note if something went wrong."""
    note = ""
    use_paid_api = config.KEYWORDS_EVERYWHERE_API_KEY != ""
    google_failed = False

    for post in posts:
        guesses = make_keywords(post["title"], post["url"])
        if len(guesses) == 0:
            continue
        post["keyword"] = guesses[0]

        if use_paid_api:
            try:
                post["volume"] = keywords_everywhere_volume(guesses[0])
                continue
            except KeywordApiError as error:
                note = str(error) + ". Showing the free Google autocomplete estimate instead."
                use_paid_api = False

        best_score = None
        for guess in guesses:
            score = autocomplete_score(guess)
            if score is None:
                google_failed = True
                break
            if best_score is None or score > best_score:
                best_score = score
                post["keyword"] = guess
        post["demand"] = best_score

    if google_failed and note == "":
        note = "Keyword demand is unavailable right now (Google autocomplete could not be reached)."
    return note


def demand_text(post):
    """Words to show the user."""
    if post.get("volume") is not None:
        return "{:,} searches/month".format(post["volume"])
    if post.get("demand") is not None:
        score = post["demand"]
        if score >= 70:
            level = "High"
        elif score >= 40:
            level = "Medium"
        elif score > 0:
            level = "Low"
        else:
            level = "None found"
        return "Demand: " + level + " (" + str(score) + "/100, free estimate)"
    return "Keyword data unavailable"




    