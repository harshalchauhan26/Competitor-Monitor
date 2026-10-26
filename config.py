import os
from dotenv import load_dotenv

load_dotenv()

#///DB SETUP///
DATABASE_URL=os.environ.get("DATABASE_URL"," ")
SQLITE_FILE=os.environ.get("SQLITE_FILE","monitor.db")

#//ALERTS//
SLACK_WEBHOOK_URL=os.environ.get("SLACK_WEBHOOK_URL")
SMTP_HOST=os.environ.get("SMTP_HOST"," ")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "")

#//Keywords//
KEYWORDS_EVERYWHERE_API_KEY = os.environ.get("KEYWORDS_EVERYWHERE_API_KEY", "")
KE_URL = os.environ.get("KE_URL", "https://api.keywordseverywhere.com/v1/get_keyword_data")
SUGGEST_URL = os.environ.get("SUGGEST_URL", "https://suggestqueries.google.com/complete/search")

#//Scrapper behavior//
MAX_POSTS_PER_RUN=30
NEW_POST_MAX_AGE_DAYS = 45     # newly found posts older than this are saved but not reported
ALLOW_PRIVATE_HOSTS = os.environ.get("ALLOW_PRIVATE_HOSTS", "false").lower() == "true"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
