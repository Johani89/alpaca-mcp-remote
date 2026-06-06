"""
Dealership inventory marketing pilot module.

This module syncs vehicle inventory from configured dealership inventory URLs,
keeps live pricing as the source of truth, generates marketplace-ready post kits,
and tracks lead events for monthly reporting.

Environment variables:
- DEALER_INVENTORY_URLS: semicolon-separated inventory URLs.
- DEALER_NAMES: optional semicolon-separated names matching DEALER_INVENTORY_URLS.
- DEALER_SYNC_TIMEOUT_SECONDS: optional request timeout, default 20.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


DB_PATH = os.getenv("DEALER_MARKETING_DB_PATH", "dealer_marketing.sqlite3")
USER_AGENT = "Mozilla/5.0 (compatible; JarvisDealerMarketing/1.0)"


@dataclass
class Vehicle:
    source_name: str
    source_url: str
    vehicle_url: str
    vin: Optional[str] = None
    stock_number: Optional[str] = None
    year: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    trim: Optional[str] = None
    mileage: Optional[int] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    status: str = "available"

    @property
    def key(self) -> str:
        if self.vin:
            return self.vin.upper()
        if self.stock_number:
            return f"stock:{self.stock_number.upper()}"
        return f"url:{self.vehicle_url}"

    @property
    def title(self) -> str:
        parts = [self.year, self.make, self.model, self.trim]
        return " ".join(str(part).strip() for part in parts if part).strip() or "Vehicle"


@dataclass
class PostKit:
    vehicle_key: str
    title: str
    price: Optional[float]
    vehicle_url: str
    image_url: Optional[str]
    marketplace_title: str
    caption: str
    disclosure: str
    tracking_url: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicles (
                vehicle_key TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                vehicle_url TEXT NOT NULL,
                vin TEXT,
                stock_number TEXT,
                year TEXT,
                make TEXT,
                model TEXT,
                trim TEXT,
                mileage INTEGER,
                price REAL,
                image_url TEXT,
                status TEXT NOT NULL DEFAULT 'available',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicle_price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_key TEXT NOT NULL,
                old_price REAL,
                new_price REAL,
                changed_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_key TEXT,
                source TEXT,
                salesperson TEXT,
                event_type TEXT NOT NULL,
                event_value TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def configured_sources() -> List[Dict[str, str]]:
    urls = [u.strip() for u in os.getenv("DEALER_INVENTORY_URLS", "").split(";") if u.strip()]
    names = [n.strip() for n in os.getenv("DEALER_NAMES", "").split(";") if n.strip()]
    sources = []
    for index, url in enumerate(urls):
        parsed = urlparse(url)
        fallback = parsed.netloc.replace("www.", "") or f"dealer-{index + 1}"
        name = names[index] if index < len(names) else fallback
        sources.append({"name": name, "url": url})
    return sources


def fetch_html(url: str) -> str:
    timeout = int(os.getenv("DEALER_SYNC_TIMEOUT_SECONDS", "20"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _safe_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip()
    return unescape(text) if text else None


def _parse_price(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = re.search(r"[0-9][0-9,]*(?:\.[0-9]{2})?", text)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def _parse_mileage(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    match = re.search(r"[0-9][0-9,]*", text)
    if not match:
        return None
    return int(match.group(0).replace(",", ""))


def _first_value(data: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _absolute_url(base_url: str, maybe_url: Optional[str]) -> str:
    if not maybe_url:
        return base_url
    if maybe_url.startswith("http://") or maybe_url.startswith("https://"):
        return maybe_url
    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    if maybe_url.startswith("/"):
        return root + maybe_url
    return root + "/" + maybe_url


def parse_json_ld_inventory(html: str, source_name: str, source_url: str) -> List[Vehicle]:
    vehicles: List[Vehicle] = []
    script_pattern = re.compile(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in script_pattern.finditer(html):
        raw = match.group(1).strip()
        try:
            payload = json.loads(unescape(raw))
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            vehicles.extend(_vehicles_from_json_node(item, source_name, source_url))
    return vehicles


def _vehicles_from_json_node(node: Any, source_name: str, source_url: str) -> List[Vehicle]:
    vehicles: List[Vehicle] = []
    if isinstance(node, list):
        for child in node:
            vehicles.extend(_vehicles_from_json_node(child, source_name, source_url))
        return vehicles
    if not isinstance(node, dict):
        return vehicles

    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else [node_type]
    if any(str(t).lower() in {"vehicle", "car", "automobile"} for t in types if t):
        offers = node.get("offers") if isinstance(node.get("offers"), dict) else {}
        image = node.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        url = _first_value(node, ["url", "sameAs"])
        vehicle = Vehicle(
            source_name=source_name,
            source_url=source_url,
            vehicle_url=_absolute_url(source_url, _safe_text(url)),
            vin=_safe_text(_first_value(node, ["vehicleIdentificationNumber", "vin", "VIN"])),
            stock_number=_safe_text(_first_value(node, ["sku", "stockNumber", "stock_number"])),
            year=_safe_text(_first_value(node, ["vehicleModelDate", "modelDate", "year"])),
            make=_safe_text(_first_value(node, ["manufacturer", "brand", "make"])),
            model=_safe_text(_first_value(node, ["model", "name"])),
            trim=_safe_text(_first_value(node, ["vehicleConfiguration", "trim"])),
            mileage=_parse_mileage(_first_value(node, ["mileageFromOdometer", "mileage"])),
            price=_parse_price(_first_value(offers, ["price", "lowPrice"])),
            image_url=_absolute_url(source_url, _safe_text(image)) if image else None,
        )
        if vehicle.price or vehicle.vin or vehicle.stock_number:
            vehicles.append(vehicle)

    for value in node.values():
        if isinstance(value, (dict, list)):
            vehicles.extend(_vehicles_from_json_node(value, source_name, source_url))
    return vehicles


def parse_embedded_inventory(html: str, source_name: str, source_url: str) -> List[Vehicle]:
    vehicles: Dict[str, Vehicle] = {}
    vin_pattern = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
    for vin_match in vin_pattern.finditer(html):
        start = max(0, vin_match.start() - 2500)
        end = min(len(html), vin_match.end() + 2500)
        chunk = html[start:end]
        vin = vin_match.group(0)
        price = _parse_price(_find_nearby(chunk, [r"\$\s*[0-9][0-9,]*(?:\.[0-9]{2})?"]))
        url_match = re.search(r"href=[\"']([^\"']+)[\"']", chunk, re.IGNORECASE)
        image_match = re.search(r"(?:src|data-src)=[\"']([^\"']+\.(?:jpg|jpeg|png|webp)[^\"']*)[\"']", chunk, re.IGNORECASE)
        title_text = _strip_tags(chunk)
        year_match = re.search(r"\b(20[0-9]{2}|19[8-9][0-9])\b", title_text)
        vehicle_url = _absolute_url(source_url, url_match.group(1)) if url_match else source_url
        vehicle = Vehicle(
            source_name=source_name,
            source_url=source_url,
            vehicle_url=vehicle_url,
            vin=vin,
            year=year_match.group(1) if year_match else None,
            price=price,
            image_url=_absolute_url(source_url, image_match.group(1)) if image_match else None,
        )
        vehicles[vehicle.key] = vehicle
    return list(vehicles.values())


def _find_nearby(text: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def dedupe_vehicles(vehicles: List[Vehicle]) -> List[Vehicle]:
    output: Dict[str, Vehicle] = {}
    for vehicle in vehicles:
        existing = output.get(vehicle.key)
        if existing is None:
            output[vehicle.key] = vehicle
            continue
        if not existing.price and vehicle.price:
            existing.price = vehicle.price
        if not existing.image_url and vehicle.image_url:
            existing.image_url = vehicle.image_url
        if existing.vehicle_url == existing.source_url and vehicle.vehicle_url != vehicle.source_url:
            existing.vehicle_url = vehicle.vehicle_url
    return list(output.values())


def sync_source(source_name: str, source_url: str) -> Dict[str, Any]:
    init_db()
    started = now_iso()
    try:
        html = fetch_html(source_url)
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"source_name": source_name, "source_url": source_url, "ok": False, "error": str(exc)}

    vehicles = dedupe_vehicles(
        parse_json_ld_inventory(html, source_name, source_url)
        + parse_embedded_inventory(html, source_name, source_url)
    )
    upserted = 0
    price_changes = 0
    seen_keys = set()
    with get_db_connection() as conn:
        for vehicle in vehicles:
            seen_keys.add(vehicle.key)
            existing = conn.execute(
                "SELECT price FROM vehicles WHERE vehicle_key = ?",
                (vehicle.key,),
            ).fetchone()
            if existing and existing["price"] != vehicle.price:
                conn.execute(
                    "INSERT INTO vehicle_price_history (vehicle_key, old_price, new_price, changed_at) VALUES (?, ?, ?, ?)",
                    (vehicle.key, existing["price"], vehicle.price, now_iso()),
                )
                price_changes += 1
            conn.execute(
                """
                INSERT INTO vehicles (
                    vehicle_key, source_name, source_url, vehicle_url, vin, stock_number,
                    year, make, model, trim, mileage, price, image_url, status,
                    first_seen_at, last_seen_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(vehicle_key) DO UPDATE SET
                    source_name=excluded.source_name,
                    source_url=excluded.source_url,
                    vehicle_url=excluded.vehicle_url,
                    vin=excluded.vin,
                    stock_number=excluded.stock_number,
                    year=excluded.year,
                    make=excluded.make,
                    model=excluded.model,
                    trim=excluded.trim,
                    mileage=excluded.mileage,
                    price=excluded.price,
                    image_url=excluded.image_url,
                    status='available',
                    last_seen_at=excluded.last_seen_at,
                    updated_at=excluded.updated_at
                """,
                (
                    vehicle.key,
                    vehicle.source_name,
                    vehicle.source_url,
                    vehicle.vehicle_url,
                    vehicle.vin,
                    vehicle.stock_number,
                    vehicle.year,
                    vehicle.make,
                    vehicle.model,
                    vehicle.trim,
                    vehicle.mileage,
                    vehicle.price,
                    vehicle.image_url,
                    vehicle.status,
                    started,
                    started,
                    started,
                ),
            )
            upserted += 1
        conn.commit()
    return {
        "source_name": source_name,
        "source_url": source_url,
        "ok": True,
        "vehicles_found": len(vehicles),
        "vehicles_upserted": upserted,
        "price_changes": price_changes,
    }


def sync_all_sources() -> Dict[str, Any]:
    sources = configured_sources()
    if not sources:
        return {"ok": False, "error": "No DEALER_INVENTORY_URLS configured.", "results": []}
    results = [sync_source(source["name"], source["url"]) for source in sources]
    return {"ok": all(item.get("ok") for item in results), "sources": len(sources), "results": results}


def list_vehicles(limit: int = 50, source_name: Optional[str] = None) -> List[Dict[str, Any]]:
    init_db()
    limit = max(1, min(limit, 500))
    query = "SELECT * FROM vehicles WHERE status = 'available'"
    params: List[Any] = []
    if source_name:
        query += " AND source_name = ?"
        params.append(source_name)
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    with get_db_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_vehicle(vehicle_key: str) -> Optional[Dict[str, Any]]:
    init_db()
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM vehicles WHERE vehicle_key = ?", (vehicle_key,)).fetchone()
    return dict(row) if row else None


def make_tracking_url(base_url: str, vehicle_key: str, source: str, salesperson: Optional[str]) -> str:
    base = base_url.rstrip("/")
    salesperson_part = f"&salesperson={salesperson}" if salesperson else ""
    return f"{base}/dealer/leads/track?vehicle_key={vehicle_key}&source={source}{salesperson_part}"


def generate_post_kit(vehicle_key: str, source: str = "facebook", salesperson: Optional[str] = None) -> Optional[Dict[str, Any]]:
    vehicle = get_vehicle(vehicle_key)
    if not vehicle:
        return None
    public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip() or os.getenv("TRACKING_BASE_URL", "").strip()
    if not public_base_url:
        public_base_url = "https://example.com"
    price = vehicle.get("price")
    title = " ".join(str(vehicle.get(key) or "").strip() for key in ["year", "make", "model", "trim"]).strip()
    if not title:
        title = "Vehicle"
    price_line = f"Price verified today: ${price:,.0f}" if price else "Price available on dealer website"
    mileage = vehicle.get("mileage")
    mileage_line = f"Mileage: {mileage:,}" if mileage else "Mileage: see dealer listing"
    tracking_url = make_tracking_url(public_base_url, vehicle_key, source, salesperson)
    disclosure = f"Available at {vehicle.get('source_name')}. Pricing and availability should be verified on the dealer website."
    caption = (
        f"{title}\n"
        f"{price_line}\n"
        f"{mileage_line}\n\n"
        f"View live details: {tracking_url}\n\n"
        f"{disclosure}"
    )
    post_kit = PostKit(
        vehicle_key=vehicle_key,
        title=title,
        price=price,
        vehicle_url=vehicle.get("vehicle_url"),
        image_url=vehicle.get("image_url"),
        marketplace_title=title[:95],
        caption=caption,
        disclosure=disclosure,
        tracking_url=tracking_url,
    )
    return asdict(post_kit)


def track_lead(vehicle_key: Optional[str], source: str, salesperson: Optional[str], event_type: str, event_value: Optional[str]) -> Dict[str, Any]:
    init_db()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT INTO lead_events (vehicle_key, source, salesperson, event_type, event_value, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (vehicle_key, source, salesperson, event_type, event_value, now_iso()),
        )
        conn.commit()
    return {"ok": True, "vehicle_key": vehicle_key, "source": source, "salesperson": salesperson, "event_type": event_type}


def monthly_report() -> Dict[str, Any]:
    init_db()
    with get_db_connection() as conn:
        vehicles_count = conn.execute("SELECT COUNT(*) AS count FROM vehicles WHERE status = 'available'").fetchone()["count"]
        price_changes = conn.execute("SELECT COUNT(*) AS count FROM vehicle_price_history").fetchone()["count"]
        leads = conn.execute(
            """
            SELECT source, salesperson, COUNT(*) AS count
            FROM lead_events
            GROUP BY source, salesperson
            ORDER BY count DESC
            """
        ).fetchall()
    return {
        "vehicles_available": vehicles_count,
        "price_changes_tracked": price_changes,
        "lead_summary": [dict(row) for row in leads],
        "generated_at": now_iso(),
    }
