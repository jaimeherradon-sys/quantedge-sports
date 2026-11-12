"""Official documented third-party endpoints, no NBA.com scraping.

Each request is explicit; credentials never logged. HTTP and schema errors fail loudly.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any, Iterator
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class DataSourceError(RuntimeError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class APIClient:
    def __init__(self, base_url: str, key: str, key_header: str, session=None):
        if not key:
            raise DataSourceError(f"Missing API credential for {base_url}")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({key_header: key, "Accept": "application/json"})
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
                      allowed_methods=frozenset(["GET"]), respect_retry_after_header=True)
        if hasattr(self.session, "mount"):
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def get(self, path: str, params=None) -> dict | list:
        try:
            response = self.session.get(f"{self.base_url}/{path.lstrip('/')}", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            # Do not emit request URLs (may contain API keys in other clients).
            raise DataSourceError(f"Remote data request failed for {path}: {type(exc).__name__}") from exc
        if not isinstance(data, (dict, list)):
            raise DataSourceError(f"Unexpected JSON type for {path}")
        return data


class BallDontLie(APIClient):
    """Paid player game stats; free tier supports games but not /v1/stats."""
    def __init__(self, key=None, session=None):
        super().__init__("https://api.balldontlie.io", key or os.getenv("BDL_API_KEY", ""),
                         "Authorization", session)

    def paged(self, path: str, params: dict | None = None, max_pages=500) -> Iterator[dict]:
        params = dict(params or {})
        params.setdefault("per_page", 100)
        seen = set()
        for _ in range(max_pages):
            page = self.get(path, params=params)
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                raise DataSourceError("Expected 'data' array in BALLDONTLIE response")
            yield from page["data"]
            cursor = page.get("meta", {}).get("next_cursor")
            if cursor is None:
                return
            if str(cursor) in seen:
                raise DataSourceError("Repeated API cursor, rejecting loop")
            seen.add(str(cursor))
            params["cursor"] = cursor
        raise DataSourceError("Pagination limit reached; import incomplete")

    def games(self, start: str, end: str) -> Iterator[dict]:
        return self.paged("/v1/games", {"start_date": start, "end_date": end})

    def player_stats(self, start: str, end: str) -> Iterator[dict]:
        return self.paged("/v1/stats", {"start_date": start, "end_date": end, "period": 0})

    def injuries(self) -> Iterator[dict]:
        return self.paged("/v1/player_injuries")

    def check(self) -> dict:
        data = self.get("/v1/teams", {"per_page": 1})
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise DataSourceError("Invalid teams response")
        return {"provider": "balldontlie", "endpoint": "/v1/teams", "reachable": True,
                "stats_access_verified": False, "checked_at": utcnow()}

    def check_stats(self) -> dict:
        data = self.get("/v1/stats", {"per_page": 1})
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise DataSourceError("Invalid stats response")
        return {"provider": "balldontlie", "endpoint": "/v1/stats", "stats_access_verified": True,
                "checked_at": utcnow()}


class TheOddsAPI(APIClient):
    """Market snapshots: never infer historical odds from current price."""
    def __init__(self, key=None, session=None):
        super().__init__("https://api.the-odds-api.com", key or os.getenv("ODDS_API_KEY", ""),
                         "x-api-key", session)

    def check(self) -> dict:
        data = self.get("/v4/sports")
        if not isinstance(data, list):
            raise DataSourceError("Invalid sports response")
        return {"provider": "the-odds-api", "endpoint": "/v4/sports", "reachable": True,
                "checked_at": utcnow()}

    def events(self) -> list[dict]:
        data = self.get("/v4/sports/basketball_nba/events")
        if not isinstance(data, list):
            raise DataSourceError("Invalid events response")
        return data

    def event_props(self, event_id: str, regions="us") -> dict:
        data = self.get(f"/v4/sports/basketball_nba/events/{event_id}/odds",
                        {"regions": regions, "markets": "player_points,player_rebounds,player_assists",
                         "oddsFormat": "decimal"})
        if not isinstance(data, dict) or not isinstance(data.get("bookmakers"), list):
            raise DataSourceError("Missing bookmaker market data")
        return data


class FootballDataOrg(APIClient):
    """football-data.org v4; only competitions available on subscription plan."""
    def __init__(self, key=None, session=None):
        super().__init__("https://api.football-data.org", key or os.getenv("FOOTBALL_DATA_TOKEN", ""),
                         "X-Auth-Token", session)

    def check(self) -> dict:
        payload = self.get("/v4/competitions")
        if not isinstance(payload, dict) or not isinstance(payload.get("competitions"), list):
            raise DataSourceError("Invalid football competitions response")
        return {"provider":"football-data.org", "reachable":True,
                "endpoint":"/v4/competitions", "checked_at":utcnow()}

    def matches(self, competition: str, season: int) -> list[dict]:
        if not competition.isalnum() or not 2000 <= season <= 2100:
            raise ValueError("Invalid competition code or season")
        payload = self.get(f"/v4/competitions/{competition}/matches", {"season":season})
        if not isinstance(payload,dict) or not isinstance(payload.get("matches"), list):
            raise DataSourceError("Invalid football matches response")
        return payload["matches"]
