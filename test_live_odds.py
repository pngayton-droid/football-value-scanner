

import os
import json
import requests

BASE = "https://api.thestatsapi.com/api/football/matches"
KEY = os.environ["STATS_API_KEY"]

headers = {"Authorization": f"Bearer {KEY}"}

response = requests.get(
    BASE,
    headers=headers,
    params={"status": "live", "per_page": 100, "page": 1},
    timeout=25,
)
response.raise_for_status()

matches = response.json().get("data", [])
print("Live matches found:", len(matches))

tested = 0

for match in matches:
    if not match.get("live_odds_available"):
        continue

    match_id = match.get("id")
    if not match_id:
        continue

    odds = requests.get(
        f"{BASE}/{match_id}/odds/live",
        headers=headers,
        timeout=25,
    )

    print("\nMatch ID:", match_id)
    print("HTTP status:", odds.status_code)

    if odds.ok:
        data = odds.json().get("data", {})

        for book in data.get("bookmakers", []):
            print("\nBookmaker:", book.get("bookmaker"))

            markets = book.get("markets", {})

            for market in [
                "match_odds",
                "second_half_result",
                "btts_second_half",
                "team_total_goals",
                "correct_score",
            ]:
                prices = markets.get(market)

                if prices:
                    print(
                        market,
                        json.dumps(prices)[:1500]
                    )
    else:
        print("Response:", odds.text[:300])

    tested += 1

    if tested >= 3:
        break

if tested == 0:
    print("No matches currently flagged with live odds.")
