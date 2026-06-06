"""
Vehicle photo gallery helpers for the dealership marketing pilot.

This module extracts and stores multiple vehicle photo URLs from dealership
listing/detail pages. It is intentionally dependency-free and uses the same
SQLite database path as dealer_marketing.py.
"""

from __future__ import annotations

import os
import re
import sqlite3
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import List, Optional
from urllib.parse import urlparse


DB_PATH = os.getenv("DEALER_MARKETING_DB_PATH", "dealer_marketing.sqlite3")
USER_AGENT = "Mozilla/5.0 (compatible; JarvisDealerPhotos/1.0)"
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_photo_table() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicle_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_key TEXT NOT NULL,
                photo_url TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                source_url TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(vehicle_key, photo_url)
            )
            """
        )
        conn.commit()


def absolute_url(base_url: str, maybe_url: Optional[str]) -> Optional[str]:
    if not maybe_url:
        return None
    value = unescape(str(maybe_url).strip())
    if value.startswith("data:"):
        return None
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://") or value.startswith("https://"):
        return value
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if value.startswith("/"):
        return root + value
    return root + "/" + value


def is_image_url(url: str) -> bool:
    lowered = url.lower().split("?")[0]
    return any(lowered.endswith(ext) for ext in IMAGE_EXTENSIONS)


def normalize_image_url(base_url: str, raw_url: Optional[str]) -> Optional[str]:
    url = absolute_url(base_url, raw_url)
    if not url or not is_image_url(url):
        return None
    lowered = url.lower()
    blocked_terms = ["logo", "sprite", "favicon", "icon", "blank", "placeholder", "transparent"]
    if any(term in lowered for term in blocked_terms):
        return None
    return url


def fetch_page(url: str) -> str:
    timeout = int(os.getenv("DEALER_SYNC_TIMEOUT_SECONDS", "20"))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def extract_photo_urls(html: str, base_url: str) -> List[str]:
    candidates: List[str] = []

    attr_pattern = re.compile(
        r"(?:src|data-src|data-original|data-full|data-large|data-zoom-image)=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    )
    candidates.extend(match.group(1) for match in attr_pattern.finditer(html))

    srcset_pattern = re.compile(r"srcset=[\"']([^\"']+)[\"']", re.IGNORECASE)
    for match in srcset_pattern.finditer(html):
        for part in match.group(1).split(","):
            url = part.strip().split(" ")[0]
            if url:
                candidates.append(url)

    embedded_pattern = re.compile(
        r"https?:\\?/\\?/[^\"'\\]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\"'\\]*)?",
        re.IGNORECASE,
    )
    for match in embedded_pattern.finditer(html):
        candidates.append(match.group(0).replace("\\/", "/"))

    output: List[str] = []
    seen = set()
    for raw_url in candidates:
        normalized = normalize_image_url(base_url, raw_url)
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(normalized)
    return output


def save_vehicle_photos(vehicle_key: str, source_url: str, photo_urls: List[str]) -> int:
    init_photo_table()
    max_photos = int(os.getenv("DEALER_MAX_PHOTOS_PER_VEHICLE", "12"))
    saved = 0
    with get_db_connection() as conn:
        for sort_order, photo_url in enumerate(photo_urls[:max_photos]):
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO vehicle_photos (vehicle_key, photo_url, sort_order, source_url, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (vehicle_key, photo_url, sort_order, source_url, now_iso()),
            )
            if cursor.rowcount:
                saved += 1
        conn.commit()
    return saved


def get_vehicle_photos(vehicle_key: str, limit: int = 12) -> List[str]:
    init_photo_table()
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT photo_url FROM vehicle_photos
            WHERE vehicle_key = ?
            ORDER BY sort_order ASC, id ASC
            LIMIT ?
            """,
            (vehicle_key, max(1, min(limit, 50))),
        ).fetchall()
    return [row["photo_url"] for row in rows]


def sync_vehicle_detail_photos(vehicle_key: str, vehicle_url: str) -> dict:
    html = fetch_page(vehicle_url)
    photo_urls = extract_photo_urls(html, vehicle_url)
    saved = save_vehicle_photos(vehicle_key, vehicle_url, photo_urls)
    return {
        "ok": True,
        "vehicle_key": vehicle_key,
        "vehicle_url": vehicle_url,
        "photos_found": len(photo_urls),
        "photos_saved": saved,
        "photos": photo_urls,
    }
