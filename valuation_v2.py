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

def calc_city_tier_adjustment(city_tier: str) -> dict:
    """Tier 2/3 regional markets typically trade at a 3-5% discount compared to metro Tier 1 dealer hubs."""
    if city_tier == "tier1":
        return {"multiplier": 1.00, "label": "Tier-1 Metro market"}
    elif city_tier == "tier2":
        return {"multiplier": 0.97, "label": "Tier-2 regional market (−3%)"}
    return {"multiplier": 0.95, "label": "Tier-3 / Non-metro market (−5%)"}


# ─── Transmission Premium ───────────────────────────────────────────

def calc_transmission_adjustment(variant: str, transmission_type: str = "", searched_variant_specifically: bool = False) -> dict:
    """
    Automatic variants (AT/AMT/CVT/DCT/Strong Hybrid) command a resale premium over manual.
    If the market search was already specifically conducted for an automatic/hybrid trim
    (e.g., 'Strong Hybrid Alpha+', 'AT', 'CVT'), the market price ALREADY accounts for the
    transmission. We only add +6% when comparing against general or base model listings.
    """
    variant_upper = (variant or "").upper()
    trans_upper = (transmission_type or "").upper()
    auto_markers = ("AMT", "AT", "CVT", "DCT", "AUTOMATIC", "AGS")
    tokens = variant_upper.replace("+", " ").split()
    is_automatic = (
        "AUTOMATIC" in trans_upper
        or "STRONG HYBRID" in variant_upper
        or "E-CVT" in variant_upper
        or any(marker in tokens for marker in auto_markers)
        or "AUTOMATIC" in variant_upper
    )

    if is_automatic:
        if searched_variant_specifically:
            # The search already queried and priced this specific automatic variant.
            # Avoid duplicate markup.
            return {"multiplier": 1.00, "label": "Automatic (variant-priced)", "is_automatic": True}
        return {"multiplier": 1.06, "label": "Automatic transmission (+6%)", "is_automatic": True}
    return {"multiplier": 1.00, "label": "Manual transmission", "is_automatic": False}


# ─── Asking-Price Haircut ────────────────────────────────────────────

ASKING_PRICE_HAIRCUT = 0.10  # Indian listings are asking prices; actual transactions reflect ~10% negotiation & dealer markup

def apply_asking_price_haircut(low: float, high: float, median: float) -> dict:
    """
    Online listings are sellers' asking prices, not what cars actually sell
    for — Indian used-car negotiation norms mean the real transaction price
    is typically 8-12% below the listed price. Applied uniformly before any
    other adjustment.
    """
    factor = 1 - ASKING_PRICE_HAIRCUT
    return {
        "low_lakh": round(low * factor, 2),
        "high_lakh": round(high * factor, 2),
        "median_lakh": round(median * factor, 2),
        "haircut_pct": ASKING_PRICE_HAIRCUT * 100,
    }


# ─── Confidence Band (sample size) ──────────────────────────────────

def calc_confidence_band(listings_count) -> dict:
    """
    Widen the range when few comparables were found (low confidence),
    tighten it slightly when many were found (high confidence). Adjusts
    the SPREAD around the median, not the median itself.
    """
    try:
        n = int(listings_count)
    except (TypeError, ValueError):
        n = 0

    if n < 5:
        return {"band_multiplier": 1.15, "confidence": "low", "listings_count": n,
                "label": f"Low confidence ({n} comparable listing{'s' if n != 1 else ''} found) — range widened"}
    elif n < 15:
        return {"band_multiplier": 1.0, "confidence": "medium", "listings_count": n,
                "label": f"Medium confidence ({n} comparable listings found)"}
    else:
        return {"band_multiplier": 0.9, "confidence": "high", "listings_count": n,
                "label": f"High confidence ({n} comparable listings found) — range tightened"}


def apply_confidence_band(low: float, high: float, median: float, band_multiplier: float) -> dict:
    """Widen/tighten low-high spread around the median by band_multiplier."""
    new_low = median - (median - low) * band_multiplier
    new_high = median + (high - median) * band_multiplier
    return {"low_lakh": round(new_low, 2), "high_lakh": round(new_high, 2), "median_lakh": round(median, 2)}


# ─── Depreciation-Formula Cross-Check ────────────────────────────────
# Independent estimate from ex-showroom price + a fixed depreciation curve
# (loosely IRDAI-style). Not used to compute the final number — shown
# alongside the live-listing estimate as a sanity-check / second opinion.

def calc_depreciation_formula_value(ex_showroom_lakh: float, age_years: float) -> dict:
    if age_years <= 0.5:
        dep_pct = 5 + (age_years / 0.5) * 10       # 5% -> 15%
    elif age_years <= 1:
        dep_pct = 15 + (age_years - 0.5) / 0.5 * 5  # 15% -> 20%
    elif age_years <= 2:
        dep_pct = 20 + (age_years - 1) * 10         # 20% -> 30%
    elif age_years <= 3:
        dep_pct = 30 + (age_years - 2) * 10         # 30% -> 40%
    elif age_years <= 4:
        dep_pct = 40 + (age_years - 3) * 10         # 40% -> 50%
    elif age_years <= 5:
        dep_pct = min(50 + (age_years - 4) * 10, 55)  # 50% -> 55% (capped)
    else:
        dep_pct = 55 + min((age_years - 5) * 8, 30)  # +8%/yr beyond 5yr, capped

    dep_pct = min(dep_pct, 85)  # floor value: never depreciate below 15% of ex-showroom
    value = ex_showroom_lakh * (1 - dep_pct / 100)
    return {"formula_value_lakh": round(value, 2), "depreciation_pct": round(dep_pct, 1)}


def get_ex_showroom_price(catalog: dict, model: str, generation: str) -> float:
    """Look up ex_showroom_base_lakh for a model+generation from the catalog. Returns 0 if not found."""
    for m in catalog.get("models", []):
        if m.get("model", "").strip().lower() == (model or "").strip().lower():
            for g in m.get("generations", []):
                if g.get("gen", "").strip().lower() == (generation or "").strip().lower():
                    return g.get("ex_showroom_base_lakh", 0)
            # generation not matched — fall back to the first generation's price as a rough anchor
            if m.get("generations"):
                return m["generations"][0].get("ex_showroom_base_lakh", 0)
    return 0


def calc_cross_check(catalog: dict, model: str, generation: str, age_years: float, live_median_lakh: float, ex_showroom_override: float = 0.0) -> dict:
    """
    Compare the depreciation-formula estimate against the live-listing median.
    Always returned (per product decision) — not just when they diverge.
    """
    ex_showroom = ex_showroom_override or get_ex_showroom_price(catalog, model, generation)
    if not ex_showroom:
        return {"available": False}

    formula = calc_depreciation_formula_value(ex_showroom, age_years)
    formula_value = formula["formula_value_lakh"]

    if live_median_lakh > 0:
        divergence_pct = round(((live_median_lakh - formula_value) / live_median_lakh) * 100, 1)
    else:
        divergence_pct = 0.0

    return {
        "available": True,
        "ex_showroom_lakh": ex_showroom,
        "formula_value_lakh": formula_value,
        "depreciation_pct": formula["depreciation_pct"],
        "live_market_median_lakh": live_median_lakh,
        "divergence_pct": divergence_pct,
        "significant_divergence": abs(divergence_pct) > 25,
    }


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
    variant: str = "",
    listings_count = None,
    model: str = "",
    generation: str = "",
    transmission_type: str = "",
    ex_showroom_override: float = 0.0,
    searched_variant_specifically: bool = False,
) -> dict:
    """
    Apply all deterministic adjustments on top of AI-researched market prices.

    Order of operations:
      1. Asking-price haircut (listings are asking prices, not sale prices)
      2. Confidence-band widening/tightening (based on comparable count)
      3. Car-specific multipliers: usage, ownership, transmission, regulatory
    The depreciation-formula cross-check is computed independently and never
    feeds into the final number — it's a second opinion shown alongside it.
    """
    # Step 1: haircut on the raw market figures
    haircut = apply_asking_price_haircut(market_low, market_high, market_median)

    # Step 2: confidence-based band adjustment around the (haircut) median
    confidence = calc_confidence_band(listings_count)
    banded = apply_confidence_band(
        haircut["low_lakh"], haircut["high_lakh"], haircut["median_lakh"],
        confidence["band_multiplier"],
    )

    # Step 3: car-specific multipliers
    usage = calc_usage_adjustment(km_run, age_years, fuel_type)
    ownership = calc_ownership_multiplier(owner_sr)
    transmission = calc_transmission_adjustment(
        variant, transmission_type, searched_variant_specifically=searched_variant_specifically
    )
    regulatory = check_regulatory(fuel_type, age_years, rto_code)
    city_tier = get_city_tier(rto_code)
    location = calc_city_tier_adjustment(city_tier)

    combined_multiplier = (
        usage["multiplier"]
        * ownership["multiplier"]
        * transmission["multiplier"]
        * regulatory["multiplier"]
        * location["multiplier"]
    )

    adjusted_low = round(banded["low_lakh"] * combined_multiplier, 2)
    adjusted_high = round(banded["high_lakh"] * combined_multiplier, 2)
    adjusted_median = round(banded["median_lakh"] * combined_multiplier, 2)

    # Ensure low <= median <= high
    adjusted_low = min(adjusted_low, adjusted_median)
    adjusted_high = max(adjusted_high, adjusted_median)

    # Depreciation-formula cross-check — independent, always computed, never
    # feeds back into the number above
    cross_check = calc_cross_check(CATALOG, model, generation, age_years, market_median, ex_showroom_override=ex_showroom_override)

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
            "haircut": haircut,
            "confidence": confidence,
            "usage": usage,
            "ownership": ownership,
            "transmission": transmission,
            "regulatory": regulatory,
            "location": location,
            "combined_multiplier": round(combined_multiplier, 4),
        },
        "cross_check": cross_check,
        "meta": {
            "age_years": age_years,
            "km_run": km_run,
            "fuel_type": fuel_type,
            "owner_sr": owner_sr,
            "rto_code": rto_code,
            "city_tier": city_tier,
            "variant": variant,
        },
    }
