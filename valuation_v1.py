"""
CarValuator - Deterministic Valuation Engine
Applies adjustments on top of AI-researched market prices.
All math here is reproducible, auditable, and LLM-free.
"""

from datetime import datetime, date
import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_catalog():
    with open(os.path.join(BASE_DIR, "maruti_catalog_v1.json"), "r") as f:
        return json.load(f)

CATALOG = load_catalog()

# ─── KM Usage Adjustment ───────────────────────────────────────────
# Compare actual KM to expected KM for the car's age.
# Diesel owners in India historically drive more per year.

EXPECTED_KM_PER_YEAR = {
    "Petrol": 12000,
    "CNG":    10000,
    "Diesel": 15000,
    "Hybrid": 12000,
}

def calc_age_years(reg_date_str: str) -> float:
    """Calculate age in years from registration date string (DD-MMM-YYYY or YYYY-MM-DD)."""
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            reg_date = datetime.strptime(reg_date_str, fmt).date()
            delta = date.today() - reg_date
            return round(delta.days / 365.25, 2)
        except ValueError:
            continue
    return 0.0

def calc_usage_adjustment(km_run: int, age_years: float, fuel_type: str) -> dict:
    """
    Returns a multiplier based on how the car's KM compares to expected usage.
    Over-driven cars get a deduction; under-driven get a small premium.
    """
    if age_years < 0.25:
        return {"multiplier": 1.0, "ratio": 1.0, "label": "Too new to assess usage"}

    expected_km_yr = EXPECTED_KM_PER_YEAR.get(fuel_type, 12000)
    expected_km = expected_km_yr * age_years
    ratio = km_run / expected_km if expected_km > 0 else 1.0

    if ratio > 1.5:
        multiplier = 0.88  # heavily over-driven
        label = "Heavily over-driven"
    elif ratio > 1.2:
        # -1% per 10% over expected, starting from 1.2
        over_pct = (ratio - 1.0) * 100
        deduction = min(over_pct * 0.1, 12)  # cap at 12%
        multiplier = 1.0 - (deduction / 100)
        label = "Over-driven"
    elif ratio < 0.5:
        multiplier = 1.05  # very low usage premium, capped
        label = "Very low usage"
    elif ratio < 0.8:
        under_pct = (1.0 - ratio) * 100
        premium = min(under_pct * 0.08, 5)  # cap at 5%
        multiplier = 1.0 + (premium / 100)
        label = "Below-average usage"
    else:
        multiplier = 1.0
        label = "Normal usage"

    return {
        "multiplier": round(multiplier, 4),
        "ratio": round(ratio, 2),
        "expected_km": round(expected_km),
        "label": label,
    }


# ─── Ownership Multiplier ──────────────────────────────────────────

def calc_ownership_multiplier(owner_sr: int) -> dict:
    """
    Each additional owner beyond the first reduces value.
    Based on Indian used-car market norms (~5-8% per owner).
    """
    table = {
        1: {"multiplier": 1.00, "label": "1st Owner"},
        2: {"multiplier": 0.94, "label": "2nd Owner (−6%)"},
        3: {"multiplier": 0.88, "label": "3rd Owner (−12%)"},
    }
    if owner_sr in table:
        return table[owner_sr]
    return {"multiplier": 0.80, "label": f"{owner_sr}th Owner (−20%)"}


# ─── Regulatory / NCR Diesel Ban ───────────────────────────────────

def check_regulatory(fuel_type: str, age_years: float, rto_code: str) -> dict:
    """
    Check Delhi-NCR age-based vehicle restrictions.
    Diesel: 10-year ban. Petrol: 15-year ban. CNG: exempt.
    """
    ncr_prefixes = CATALOG.get("ncr_rto_prefixes", [])
    is_ncr = any(rto_code.upper().startswith(p) for p in ncr_prefixes)

    if not is_ncr:
        return {"multiplier": 1.0, "flag": None, "message": None, "is_ncr": False}

    if fuel_type.lower() == "cng":
        return {"multiplier": 1.0, "flag": None, "message": "CNG vehicles exempt from NCR age ban", "is_ncr": True}

    if fuel_type.lower() == "diesel":
        max_age = 10
    else:
        max_age = 15

    years_remaining = max_age - age_years

    if years_remaining <= 0:
        return {
            "multiplier": 0.15,
            "flag": "OVER_AGE_LIMIT",
            "message": f"⛔ Vehicle has CROSSED the {max_age}-year {fuel_type} age limit in Delhi-NCR. Cannot be driven or re-registered. Value is essentially scrap/relocation only.",
            "is_ncr": True,
        }
    elif years_remaining <= 1:
        return {
            "multiplier": 0.60,
            "flag": "NEARING_LIMIT",
            "message": f"⚠️ Less than 1 year remaining before the {max_age}-year {fuel_type} ban in Delhi-NCR. Significant resale impact.",
            "is_ncr": True,
        }
    elif years_remaining <= 2:
        return {
            "multiplier": 0.85,
            "flag": "APPROACHING_LIMIT",
            "message": f"⚠️ ~{years_remaining:.0f} years remaining before the {max_age}-year {fuel_type} limit in Delhi-NCR.",
            "is_ncr": True,
        }
    else:
        return {"multiplier": 1.0, "flag": None, "message": None, "is_ncr": True}


# ─── City Tier ──────────────────────────────────────────────────────

def get_city_tier(rto_code: str) -> str:
    tier_map = CATALOG.get("city_tier_map", {})
    rto_upper = rto_code.upper()
    for tier, prefixes in tier_map.items():
        if isinstance(prefixes, list):
            if any(rto_upper.startswith(p) for p in prefixes):
                return tier
    return "tier3"


# ─── Final Valuation Composer ───────────────────────────────────────

def compute_valuation(
    market_low: float,
    market_high: float,
    market_median: float,
    km_run: int,
    age_years: float,
    fuel_type: str,
    owner_sr: int,
    rto_code: str,
) -> dict:
    """
    Apply all deterministic adjustments on top of AI-researched market prices.
    Market prices already reflect age-based depreciation, so we only adjust
    for user-specific factors: KM usage, ownership count, regulatory risk.

    Returns the final adjusted range + full breakdown.
    """
    usage = calc_usage_adjustment(km_run, age_years, fuel_type)
    ownership = calc_ownership_multiplier(owner_sr)
    regulatory = check_regulatory(fuel_type, age_years, rto_code)
    city_tier = get_city_tier(rto_code)

    combined_multiplier = (
        usage["multiplier"]
        * ownership["multiplier"]
        * regulatory["multiplier"]
    )

    adjusted_low = round(market_low * combined_multiplier, 2)
    adjusted_high = round(market_high * combined_multiplier, 2)
    adjusted_median = round(market_median * combined_multiplier, 2)

    # Ensure low <= median <= high
    adjusted_low = min(adjusted_low, adjusted_median)
    adjusted_high = max(adjusted_high, adjusted_median)

    return {
        "final_range": {
            "low_lakh": adjusted_low,
            "high_lakh": adjusted_high,
            "median_lakh": adjusted_median,
        },
        "market_base": {
            "low_lakh": market_low,
            "high_lakh": market_high,
            "median_lakh": market_median,
        },
        "adjustments": {
            "usage": usage,
            "ownership": ownership,
            "regulatory": regulatory,
            "combined_multiplier": round(combined_multiplier, 4),
        },
        "meta": {
            "age_years": age_years,
            "km_run": km_run,
            "fuel_type": fuel_type,
            "owner_sr": owner_sr,
            "rto_code": rto_code,
            "city_tier": city_tier,
        },
    }
