import json
import os
from datetime import datetime
from typing import List, Optional

import requests

API_BASE_URL = os.getenv("WAW_API_BASE_URL", "http://127.0.0.1:8000")
TOKEN_PATH = os.path.join(os.path.dirname(__file__), ".token.json")
BUFFER_PATH = os.path.join(os.path.dirname(__file__), "blink_buffer.json")


class ApiClient:
    def __init__(self):
        self._token: Optional[str] = None
        self._load_token()

    # ---------------- Token management ----------------
    def _load_token(self):
        if os.path.exists(TOKEN_PATH):
            try:
                with open(TOKEN_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._token = data.get("access_token")
            except Exception:
                self._token = None

    def _save_token(self, token: str):
        self._token = token
        try:
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                json.dump({"access_token": token}, f)
        except Exception:
            pass

    @property
    def has_token(self) -> bool:
        return self._token is not None

    # ---------------- Auth ----------------
    def login(self, email: str, password: str) -> bool:
        """Authenticate against backend and store token locally."""
        url = f"{API_BASE_URL}/auth/token"
        data = {"username": email, "password": password}
        try:
            resp = requests.post(url, data=data, timeout=10)
            if resp.status_code != 200:
                print(f"Login failed: HTTP {resp.status_code} - {resp.text}")
                return False
            token = resp.json().get("access_token")
            if not token:
                print("Login failed: No access token in response")
                return False
            self._save_token(token)
            return True
        except Exception as e:
            print(f"Login error: {e}")
            return False

    # ---------------- Local buffer ----------------
    def _load_buffer(self) -> List[dict]:
        if not os.path.exists(BUFFER_PATH):
            return []
        try:
            with open(BUFFER_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_buffer(self, rows: List[dict]):
        try:
            with open(BUFFER_PATH, "w", encoding="utf-8") as f:
                json.dump(rows, f)
        except Exception:
            pass

    def buffer_session(self, started_at: datetime, ended_at: datetime, blink_count: int, avg_cpu: float, avg_mem: float):
        rows = self._load_buffer()
        rows.append(
            {
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "blink_count": blink_count,
                "avg_cpu": avg_cpu,
                "avg_memory_mb": avg_mem,
            }
        )
        self._save_buffer(rows)

    # ---------------- Sync with backend ----------------
    def sync_buffer(self) -> int:
        """Attempt to send any locally buffered sessions.

        Returns number of sessions successfully synced.
        """
        if not self._token:
            print("Sync skipped: No authentication token")
            return 0

        rows = self._load_buffer()
        if not rows:
            print("Sync skipped: No buffered sessions")
            return 0

        print(f"Attempting to sync {len(rows)} buffered sessions")
        headers = {"Authorization": f"Bearer {self._token}"}
        url = f"{API_BASE_URL}/blink-sessions"
        sent = 0
        remaining: List[dict] = []

        for row in rows:
            try:
                resp = requests.post(url, json=row, headers=headers, timeout=10)
                if resp.status_code == 200:
                    sent += 1
                else:
                    print(f"Sync failed for session: HTTP {resp.status_code} - {resp.text}")
                    remaining.append(row)
            except Exception as e:
                print(f"Sync error for session: {e}")
                remaining.append(row)

        self._save_buffer(remaining)
        if sent > 0:
            print(f"Successfully synced {sent} sessions")
        if remaining:
            print(f"{len(remaining)} sessions remain buffered for retry")
        return sent
