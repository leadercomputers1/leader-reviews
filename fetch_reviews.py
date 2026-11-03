"""Daily Google reviews feed for the business card.

Reads the rating, the review count and the reviews of the Leader Computers profile through the
Google Business Profile API (free) and writes docs/reviews.json, which the card loads from the
Konimbo field «Автоматические данные (JSON)» (reviews_feed_url).

Only 5-star reviews with text are written. The rating and count are the real totals of all reviews.

Environment (GitHub secrets, never in files):
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
  GBP_LOCATION   optional, e.g. accounts/123/locations/456 (found automatically when empty)

Test without Google: py fetch_reviews.py --sample sample-api-response.json
On any error the script stops with a message and leaves the previous reviews.json as it was.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent / "docs" / "reviews.json"
KEEP = 30          # newest 5-star reviews kept in the file; the card shows as many as Konimbo says
MIN_TEXT = 15      # shorter texts ("👍", "Great") are skipped
STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}


def http_json(url, data=None, token=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = urllib.parse.urlencode(data).encode() if data else None
    request = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        # The error text from Google says what is wrong (no access yet, API not enabled...).
        sys.exit(f"Google ответил {e.code} на {url.split('?')[0]}: {e.read().decode('utf-8', 'replace')[:600]}")


def access_token():
    env = {k: os.environ.get(k, "").strip() for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit("Нет секретов: " + ", ".join(missing))
    answer = http_json("https://oauth2.googleapis.com/token", {
        "client_id": env["GOOGLE_CLIENT_ID"], "client_secret": env["GOOGLE_CLIENT_SECRET"],
        "refresh_token": env["GOOGLE_REFRESH_TOKEN"], "grant_type": "refresh_token",
    })
    return answer["access_token"]


def find_location(token):
    """accounts/…/locations/… of the profile; the only one, or the one named Leader / לידר."""
    found = []
    accounts = http_json("https://mybusinessaccountmanagement.googleapis.com/v1/accounts", token=token)
    for account in accounts.get("accounts", []):
        url = (f"https://mybusinessbusinessinformation.googleapis.com/v1/{account['name']}/locations"
               "?readMask=name,title&pageSize=100")
        for loc in http_json(url, token=token).get("locations", []):
            found.append((f"{account['name']}/{loc['name']}", loc.get("title", "")))
    leader = [f for f in found if "leader" in f[1].lower() or "לידר" in f[1]]
    pick = leader if len(leader) == 1 else found if len(found) == 1 else []
    if not pick:
        sys.exit("Не удалось выбрать карточку. Найдено: " + "; ".join(f"{n} ({t})" for n, t in found)
                 + ". Укажите нужную в секрете GBP_LOCATION.")
    return pick[0][0]


def fetch_pages(token, location):
    pages, page_token = [], ""
    while True:
        url = (f"https://mybusiness.googleapis.com/v4/{location}/reviews?pageSize=50&orderBy=updateTime%20desc"
               + (f"&pageToken={urllib.parse.quote(page_token)}" if page_token else ""))
        page = http_json(url, token=token)
        pages.append(page)
        page_token = page.get("nextPageToken", "")
        if not page_token or len(pages) >= 40:
            return pages


def original_text(comment):
    """Google adds its own translation to some reviews: keep only what the customer wrote."""
    text = comment or ""
    # Two layouts: "(Translated by Google) …translation… (Original) …text…"
    # and "…text… (Translated by Google) …translation…".
    if "(Original)" in text:
        text = text.split("(Original)", 1)[1]
    elif "(Translated by Google)" in text:
        text = text.split("(Translated by Google)", 1)[0]
    return text.strip()


def build_feed(pages):
    first = pages[0] if pages else {}
    reviews = []
    for page in pages:
        for r in page.get("reviews", []):
            text = original_text(r.get("comment"))
            if STARS.get(r.get("starRating")) != 5 or len(text) < MIN_TEXT:
                continue
            who = r.get("reviewer") or {}
            reviews.append({
                "author": ("Google user" if who.get("isAnonymous") else who.get("displayName", "")).strip()[:80] or "Google user",
                "rating": 5,
                "text": text[:1200],
                "date": (r.get("createTime") or "")[:10],
            })
    reviews.sort(key=lambda r: r["date"], reverse=True)
    rating = float(first.get("averageRating") or 0)
    count = int(first.get("totalReviewCount") or 0)
    if not (1 <= rating <= 5 and count > 0):
        sys.exit("Google не вернул рейтинг и число отзывов — файл не изменён.")
    return {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rating": round(rating, 1),
        "count": count,
        "reviews": reviews[:KEEP],
    }


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--sample":
        pages = [json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))]
    else:
        token = access_token()
        location = os.environ.get("GBP_LOCATION", "").strip() or find_location(token)
        pages = fetch_pages(token, location)
    feed = build_feed(pages)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(feed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Рейтинг {feed['rating']}, отзывов {feed['count']}, в файле 5★ с текстом: {len(feed['reviews'])}")


if __name__ == "__main__":
    main()
