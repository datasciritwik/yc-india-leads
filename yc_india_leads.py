"""Scrape YC companies filtered by region=India via the Algolia API.

Usage: python yc_india_leads.py
Output: yc_india_leads.csv
"""
import csv
import re
import time
import requests

YC_PAGE = "https://www.ycombinator.com/companies"
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.ycombinator.com/",
    "Origin": "https://www.ycombinator.com",
}


def get_algolia_creds():
    html = requests.get(YC_PAGE, headers={"User-Agent": "Mozilla/5.0"}, timeout=30).text
    m = re.search(r'AlgoliaOpts\s*=\s*\{"app":"([^"]+)","key":"([^"]+)"\}', html)
    if not m:
        raise RuntimeError("could not find AlgoliaOpts in YC page")
    app_id, api_key = m.group(1), m.group(2)
    return app_id, api_key


APP_ID, API_KEY = get_algolia_creds()
ALGOLIA_URL = f"https://{APP_ID.lower()}-dsn.algolia.net/1/indexes/YCCompany_production/query"
PARAMS = {
    "x-algolia-agent": "Algolia for JavaScript (4.14.2); Browser",
    "x-algolia-api-key": API_KEY,
    "x-algolia-application-id": APP_ID,
}

FIELDS = [
    "name", "slug", "website", "one_liner", "long_description",
    "batch", "status", "team_size", "industry", "subindustry",
    "regions", "all_locations", "tags", "founders",
]


def fetch_page(page: int, hits_per_page: int = 1000):
    body = {
        "query": "",
        "page": page,
        "hitsPerPage": hits_per_page,
        "facetFilters": [["regions:India"]],
    }
    r = requests.post(ALGOLIA_URL, params=PARAMS, headers=HEADERS, json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    all_hits = []
    page = 0
    while True:
        data = fetch_page(page)
        hits = data.get("hits", [])
        all_hits.extend(hits)
        print(f"page {page}: +{len(hits)} (total {len(all_hits)} / {data.get('nbHits')})")
        if page + 1 >= data.get("nbPages", 1):
            break
        page += 1
        time.sleep(0.3)

    with open("yc_india_leads.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS + ["founder_names", "founder_linkedins", "yc_url"])
        for h in all_hits:
            founders = h.get("founders") or []
            names = "; ".join(fr.get("full_name", "") for fr in founders)
            lis = "; ".join(fr.get("linkedin_id", "") or "" for fr in founders)
            row = [h.get(f, "") for f in FIELDS]
            row += [names, lis, f"https://www.ycombinator.com/companies/{h.get('slug','')}"]
            w.writerow(row)

    print(f"wrote {len(all_hits)} rows to yc_india_leads.csv")


if __name__ == "__main__":
    main()
