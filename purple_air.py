# -*- coding: utf-8 -*-
"""
Created on Tue Sep  2 15:10:30 2025

@author: hsiu
"""

import os
import math
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import requests
import streamlit as st

# ------------------------------
# App Config
# ------------------------------
st.set_page_config(page_title="PurpleAir – AQI Dashboard", page_icon="🟣", layout="wide")

# Global TTL (cache + auto-refresh cadence)
TTL_SECONDS = 300  # 5 minutes

# ------------------------------
# Lightweight UI polish (CSS) — no heavy libs
# ------------------------------
st.markdown(
    """
    <style>
    .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;}
    .pill.good{background:#e8f5e9;color:#1b5e20}
    .pill.moderate{background:#fffde7;color:#795548}
    .pill.usg{background:#fff3e0;color:#e65100}
    .pill.unhealthy{background:#ffebee;color:#b71c1c}
    .pill.veryunhealthy{background:#f3e5f5;color:#4a148c}
    .pill.hazardous{background:#fbe9e7;color:#4e342e}
    .subtle{opacity:.8}
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------------------
# Helpers
# ------------------------------

def get_api_key() -> str:
    key = None
    if "PURPLEAIR_API_KEY" in st.secrets:
        key = st.secrets["PURPLEAIR_API_KEY"]
    if not key:
        key = os.getenv("PURPLEAIR_API_KEY")
    if not key:
        st.stop()
        raise RuntimeError("Missing PurpleAir API key. Set st.secrets['PURPLEAIR_API_KEY'] or the PURPLEAIR_API_KEY env var.")
    return key


@st.cache_resource
def http_session() -> requests.Session:
    s = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=8)
    s.mount("https://", adapter)
    return s


def epa_aqi_pm25(pm25: Optional[float]) -> Optional[int]:
    if pm25 is None or math.isnan(pm25):
        return None
    # EPA PM2.5 breakpoints mirrored to AQI bands
    bps = [
        (0.0, 12.0, 0, 50),
        (12.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ]
    x = min(max(pm25, 0.0), 500.4)
    for c_lo, c_hi, i_lo, i_hi in bps:
        if c_lo <= x <= c_hi:
            aqi = (i_hi - i_lo) / (c_hi - c_lo) * (x - c_lo) + i_lo
            return int(round(aqi))
    return None


def fmt_ts(ts: Optional[int]) -> str:
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - dt
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hr ago"
    days = hours // 24
    return f"{days} d ago"


def safe_float(val: Any) -> Optional[float]:
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def assess_aqi(aqi: Optional[int]) -> Tuple[str, str, str, str]:
    """Return (label, emoji, guidance, css_class) based on EPA AQI categories."""
    if aqi is None:
        return ("Unknown", "⚪", "No AQI available.", "")
    if 0 <= aqi <= 50:
        return ("Good", "🟢", "Air quality is satisfactory. Outdoor activities are safe.", "good")
    if 51 <= aqi <= 100:
        return ("Moderate", "🟡", "Acceptable; unusually sensitive people should reduce prolonged exertion.", "moderate")
    if 101 <= aqi <= 150:
        return ("Unhealthy for Sensitive Groups", "🟠", "Sensitive groups should reduce prolonged or heavy exertion.", "usg")
    if 151 <= aqi <= 200:
        return ("Unhealthy", "🔴", "Everyone may experience health effects; limit prolonged outdoor exertion.", "unhealthy")
    if 201 <= aqi <= 300:
        return ("Very Unhealthy", "🟣", "Health alert: avoid prolonged or heavy exertion outdoors.", "veryunhealthy")
    return ("Hazardous", "🟤", "Health warnings of emergency conditions: avoid all outdoor exertion.", "hazardous")


def assess_pm25(pm: Optional[float]) -> Tuple[str, str, str]:
    """Return (label, note, css_class) mirroring AQI breakpoints for PM2.5 concentration."""
    if pm is None or math.isnan(pm):
        return ("—", "No PM2.5 data.", "")
    x = pm
    if 0 <= x <= 12.0:
        return ("Good", "Within EPA 24h guideline (0–12 µg/m³).", "good")
    if 12.1 <= x <= 35.4:
        return ("Moderate", "Consider caution for unusually sensitive people.", "moderate")
    if 35.5 <= x <= 55.4:
        return ("USG", "Sensitive groups should reduce prolonged outdoor exertion.", "usg")
    if 55.5 <= x <= 150.4:
        return ("Unhealthy", "Everyone may experience health effects—limit outdoor exertion.", "unhealthy")
    if 150.5 <= x <= 250.4:
        return ("Very Unhealthy", "Avoid outdoor activities; use masks/air purifiers if possible.", "veryunhealthy")
    return ("Hazardous", "Serious risk—stay indoors with clean air if available.", "hazardous")


def assess_temp(value: Optional[float], to_unit: str) -> Tuple[str, str]:
    """Return (display_value, guidance) based on comfort ranges."""
    if value is None or math.isnan(value):
        return ("—", "No temperature data.")
    if to_unit == "Fahrenheit":
        v = value if 40 <= value <= 120 else (value * 9/5 + 32)
        if 68 <= v <= 77:
            return (f"{v:.1f} °F", "Comfort range for many indoors conditions.")
        if v > 86:
            return (f"{v:.1f} °F", "High heat: watch for heat stress; hydrate and rest.")
        if v < 50:
            return (f"{v:.1f} °F", "Cool: consider layering for warmth.")
        return (f"{v:.1f} °F", "—")
    else:
        v = value if -20 <= value <= 50 else ((value - 32) * 5/9)
        if 20 <= v <= 25:
            return (f"{v:.1f} °C", "Comfort range for many indoors conditions.")
        if v > 30:
            return (f"{v:.1f} °C", "High heat: watch for heat stress; hydrate and rest.")
        if v < 10:
            return (f"{v:.1f} °C", "Cool: consider layering for warmth.")
        return (f"{v:.1f} °C", "—")


def assess_humidity(h: Optional[float]) -> Tuple[str, str]:
    if h is None or math.isnan(h):
        return ("—", "No humidity data.")
    if 40 <= h <= 60:
        return (f"{h:.0f}%", "Comfort range (40–60%).")
    if 30 <= h < 40:
        return (f"{h:.0f}%", "Slightly dry: consider humidifier (target ≥40%).")
    if 60 < h <= 70:
        return (f"{h:.0f}%", "Slightly humid: increase ventilation; target ≤60%.")
    if h < 30:
        return (f"{h:.0f}%", "Low humidity: dryness and irritation possible.")
    if h > 70:
        return (f"{h:.0f}%", "High humidity: mold and discomfort possible.")
    return (f"{h:.0f}%", "—")


def assess_pressure(p: Optional[float]) -> Tuple[str, str]:
    if p is None or math.isnan(p):
        return ("—", "No pressure data.")
    if p < 1000:
        return (f"{p:.1f} hPa", "Low pressure: unsettled weather likely.")
    if p > 1025:
        return (f"{p:.1f} hPa", "High pressure: settled/fair weather.")
    return (f"{p:.1f} hPa", "Near average (~1013 hPa).")


@st.cache_data(ttl=TTL_SECONDS, max_entries=128)
def fetch_sensor(sensor_index: int, *, fields: Optional[str] = None) -> Dict[str, Any]:
    """PurpleAir v1 single-sensor call with tiny retry on 429/5xx."""
    api_key = get_api_key()
    base = f"https://api.purpleair.com/v1/sensors/{sensor_index}"
    headers = {"X-API-Key": api_key}
    params = {}
    if fields:
        params["fields"] = fields

    backoffs = [0, 0.6, 1.2]  # seconds
    last_exc = None
    for pause in backoffs:
        try:
            if pause:
                time.sleep(pause)
            resp = http_session().get(base, headers=headers, params=params, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            # retry only for 429/5xx
            if resp.status_code not in (429, 500, 502, 503, 504):
                resp.raise_for_status()
        except Exception as e:
            last_exc = e
            continue
    # if we got here, give best error
    if last_exc:
        raise last_exc
    raise RuntimeError("PurpleAir API request failed.")


def get_field(d: Dict[str, Any], *keys: str) -> Optional[Any]:
    cur = d
    try:
        for k in keys:
            if cur is None:
                return None
            cur = cur.get(k)
        return cur
    except Exception:
        return None


# ------------------------------
# Read shareable URL params (optional, very lightweight)
# ------------------------------
try:
    qp = dict(st.query_params)
except Exception:
    qp = {}

default_sensor = qp.get("sensor", "267927")
unit_from_qp = qp.get("unit", "F")
unit_index = 0 if unit_from_qp.upper() == "F" else 1

# ------------------------------
# Sidebar – Input controls
# ------------------------------
st.title("🟣 PurpleAir – AQI Dashboard")

with st.sidebar:
    st.header("Settings")
    sensor_id = st.text_input("Sensor Index", value=default_sensor, help="Enter the PurpleAir sensor_index (integer)")
    unit_choice = st.radio("Temperature Unit", ["Fahrenheit", "Celsius"], index=unit_index, help="Select preferred unit for temperature display")
    auto_refresh = st.checkbox(f"Auto refresh every {TTL_SECONDS//60} min", value=True)
    show_badges = st.checkbox("Show status badges (color pills)", value=False, help="Lightweight visuals; no extra API calls")
    show_raw = st.checkbox("Show raw data (debug)", value=False)
    if st.button("Refresh now"):
        st.rerun()

# Persist to URL (non-blocking)
try:
    st.query_params.update({
        "sensor": str(sensor_id or ""),
        "unit": "F" if unit_choice == "Fahrenheit" else "C",
    })
except Exception:
    pass

# Validate & fetch
try:
    sensor_index = int(sensor_id)
except ValueError:
    st.error("Sensor Index must be an integer (e.g., 267927)")
    st.stop()

try:
    payload = fetch_sensor(sensor_index)
except Exception as e:
    st.error(f"Failed to fetch sensor: {e}")
    st.stop()

sensor = get_field(payload, "sensor") or {}

# Fields (with safe casting)
name = sensor.get("name") or f"Sensor {sensor_index}"
last_seen = sensor.get("last_seen")
model = sensor.get("model")
firmware = sensor.get("firmware_version")
rssi = sensor.get("rssi")

pm25 = safe_float(sensor.get("pm2.5_atm") or sensor.get("pm2.5") or sensor.get("pm2.5_a"))
pm25_10m = safe_float(sensor.get("pm2.5_10minute"))
pm25_30m = safe_float(sensor.get("pm2.5_30minute"))
pm25_60m = safe_float(sensor.get("pm2.5_60minute"))

humidity = safe_float(sensor.get("humidity"))
raw_temp = safe_float(sensor.get("temperature"))
pressure = safe_float(sensor.get("pressure"))

aqi = epa_aqi_pm25(pm25)

# Header
left, right = st.columns([0.65, 0.35])
with left:
    st.subheader(name)
    st.caption(f"Last seen: {fmt_ts(last_seen)} | Model: {model or '—'} | FW: {firmware or '—'} | RSSI: {rssi if rssi is not None else '—'} dBm")
with right:
    st.write("")
    st.write("")
    st.toggle(f"Auto refresh ({TTL_SECONDS//60} min)", value=auto_refresh, key="auto_refresh_toggle", help=f"When on, the data is cached for {TTL_SECONDS}s and the page auto-reruns.")

# Key metrics
col1, col2, col3, col4, col5 = st.columns(5)

# AQI
with col1:
    st.metric("US AQI (PM2.5)", value=(str(aqi) if aqi is not None else "—"))
    label, emoji, guide, css_class = assess_aqi(aqi)
    st.caption(f"{emoji} {label} – {guide}")
    if show_badges and css_class:
        st.markdown(f"<span class='pill {css_class}'>AQI: {label}</span>", unsafe_allow_html=True)

# PM2.5 with trend delta vs 10m avg (if available)
with col2:
    pm_text = f"{pm25:.1f}" if isinstance(pm25, float) else "—"
    delta_text = None
    if isinstance(pm25, float) and isinstance(pm25_10m, float):
        d = pm25 - pm25_10m
        if abs(d) >= 0.1:
            delta_text = f"{d:+.1f} vs 10m"
    st.metric("PM2.5 (µg/m³)", value=pm_text, delta=delta_text)
    p_label, p_note, p_class = assess_pm25(pm25)
    st.caption(f"{p_label} – {p_note}")
    if show_badges and p_class:
        st.markdown(f"<span class='pill {p_class}'>PM2.5: {p_label}</span>", unsafe_allow_html=True)

# Temperature
with col3:
    t_disp, t_note = assess_temp(raw_temp, unit_choice)
    st.metric("Temperature", value=t_disp)
    st.caption(t_note)

# Humidity
with col4:
    h_disp, h_note = assess_humidity(humidity)
    st.metric("Humidity", value=h_disp)
    st.caption(h_note)

# Pressure
with col5:
    p_disp, p_note = assess_pressure(pressure)
    st.metric("Pressure", value=p_disp)
    st.caption(p_note)

# Rolling averages (optional, zero extra calls)
if any(isinstance(x, float) for x in (pm25_10m, pm25_30m, pm25_60m)):
    st.markdown("### PM2.5 Rolling Averages (if provided by device)")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("10 min avg (µg/m³)", value=(f"{pm25_10m:.1f}" if isinstance(pm25_10m, float) else "—"))
    with c2:
        st.metric("30 min avg (µg/m³)", value=(f"{pm25_30m:.1f}" if isinstance(pm25_30m, float) else "—"))
    with c3:
        st.metric("60 min avg (µg/m³)", value=(f"{pm25_60m:.1f}" if isinstance(pm25_60m, float) else "—"))

# Reference – EPA descriptions
with st.expander("Reference: EPA AQI Categories for PM2.5"):
    st.markdown(
        """
**Good (0–50, 🟢)** – Air quality is satisfactory; little or no risk.  
**Moderate (51–100, 🟡)** – Acceptable; unusually sensitive individuals should consider reducing prolonged or heavy exertion.  
**Unhealthy for Sensitive Groups (101–150, 🟠)** – Sensitive groups should reduce prolonged or heavy exertion.  
**Unhealthy (151–200, 🔴)** – Everyone may begin to experience health effects; limit prolonged outdoors exertion.  
**Very Unhealthy (201–300, 🟣)** – Health alert; everyone should avoid prolonged or heavy exertion outdoors.  
**Hazardous (301–500, 🟤)** – Health warnings of emergency conditions; avoid all outdoor exertion.
        """
    )
    st.caption("Source: U.S. EPA Air Quality Index (AQI) guidance for PM2.5.")

# Raw payload (optional)
if show_raw:
    with st.expander("Raw sensor payload (debug)"):
        st.json(sensor)

# Light auto-refresh (sync with TTL)
if st.session_state.get("auto_refresh_toggle"):
    st.caption(f"Auto-refresh is ON. Data cache TTL = {TTL_SECONDS}s.")
    st.markdown(
        f"""
        <script>
        setTimeout(function(){{window.parent.location.reload()}}, {(TTL_SECONDS + 5) * 1000});
        </script>
        """,
        unsafe_allow_html=True,
    )
