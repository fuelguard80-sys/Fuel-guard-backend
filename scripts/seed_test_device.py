"""
One-time script to seed a test station and nozzle for hardware testing.

Usage (from repo root):
    python scripts/seed_test_device.py

Creates:
    stations/STATION001  — Test Fuel Station
    nozzles/NZ001        — Nozzle 1, petrol, linked to STATION001
    prices/petrol_global — PKR 282.76 / litre
"""

import sys, os, glob
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore

# ── Find service account key ───────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
keys = glob.glob(os.path.join(REPO_ROOT, "*adminsdk*.json"))
if not keys:
    print("ERROR: No Firebase service account JSON found in repo root.")
    print("Place the adminsdk key file in:", REPO_ROOT)
    sys.exit(1)

KEY_PATH = keys[0]
print(f"Using key: {KEY_PATH}")

cred = credentials.Certificate(KEY_PATH)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ── Station ────────────────────────────────────────────────────────────────────
station_ref = db.collection("stations").document("STATION001")
if station_ref.get().exists:
    print("Station STATION001 already exists — skipping.")
else:
    station_ref.set({
        "id":           "STATION001",
        "name":         "Test Fuel Station",
        "address":      "123 Test Road",
        "city":         "Karachi",
        "latitude":     24.8607,
        "longitude":    67.0011,
        "is_active":    True,
        "created_at":   datetime.now(timezone.utc),
    })
    print("Created station: STATION001")

# ── Nozzle ─────────────────────────────────────────────────────────────────────
nozzle_ref = db.collection("nozzles").document("NZ001")
if nozzle_ref.get().exists:
    print("Nozzle NZ001 already exists — skipping.")
else:
    nozzle_ref.set({
        "id":                 "NZ001",
        "name":               "Nozzle 1",
        "station_id":         "STATION001",
        "fuel_type":          "petrol",
        "ble_uuid":           "NZ001-BLE-UUID",
        "ble_device_name":    "FuelMonitor",
        "hardware_serial":    "NZ001",
        "flow_meter_model":   "YF-S201",
        "max_flow_rate":      60.0,
        "status":             "idle",
        "is_active":          True,
        "tamper_detected":    False,
        "current_flow_rate":  None,
        "total_litres_today": 0.0,
        "last_seen":          None,
        "created_at":         datetime.now(timezone.utc),
    })
    print("Created nozzle: NZ001")

# ── Fuel price ─────────────────────────────────────────────────────────────────
price_ref = db.collection("prices").document("petrol_global")
if price_ref.get().exists:
    print("Petrol price already exists — skipping.")
else:
    price_ref.set({
        "fuel_type":       "petrol",
        "price_per_litre": 282.76,
        "station_id":      None,
        "effective_from":  datetime.now(timezone.utc).isoformat(),
        "updated_at":      datetime.now(timezone.utc),
    })
    print("Created petrol price: PKR 282.76/L")

print("\nSeed complete. Scan fuelguard://nozzle/NZ001 to test.")
