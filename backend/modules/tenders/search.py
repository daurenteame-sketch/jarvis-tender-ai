from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://goszakup.gov.kz"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


def search_tenders(keyword: str, limit: int = 5) -> list[dict]:
    """
    Search tenders on goszakup.gov.kz and return up to `limit` results.

    Returns a list of dicts:
        {"title": str, "url": str, "price": str}
    """
    url = f"{BASE_URL}/ru/search/announce?text={quote(keyword)}"

    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return []
    except Exception:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    for link in soup.find_all("a", href=lambda h: h and "/ru/announce/index/" in h):
        title = link.get_text(strip=True)
        if not title:
            continue

        href = link["href"]
        full_url = href if href.startswith("http") else BASE_URL + href

        # Price is in the last <strong> of the same <tr>
        row = link.find_parent("tr")
        price = ""
        if row:
            strongs = row.find_all("strong")
            if strongs:
                price = strongs[-1].get_text(strip=True)

        results.append({"title": title, "url": full_url, "price": price})

        if len(results) >= limit:
            break

    return results
