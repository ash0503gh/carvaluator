"""
CarValuator - Main FastAPI Application
Maruti Suzuki used car valuation powered by Gemini AI + deterministic math.
"""

import os
import json
import re
import requests
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from valuation_v2 import compute_valuation, calc_age_years, load_catalog

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="CarValuator", version="1.0")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

CATALOG = load_catalog()


# ─── Request / Response Models ──────────────────────────────────────

class ValuationRequest(BaseModel):
    rc_number: str
    km_run: int


# ─── Vehicle Data Extraction ──────────────────────────────────────────
# Uses vehicle_details.py (Cars24 + Spinny fallback + CarInfo challans).
# No paid API needed — zero cost per lookup.

from vehicle_details import scrape_vehicle

def decode_rc(rc_number: str) -> dict:
    """
    Wrapper around vehicle_details.scrape_vehicle() that maps its
    LookupResult dataclass into the flat dict the rest of the app expects.
    """
    result = scrape_vehicle(rc_number)

    if not result.success or not result.vehicle:
        raise HTTPException(
            status_code=404,
            detail=result.error_message or f"Could not find vehicle data for {rc_number}.",
        )

    v = result.vehicle

    # Parse owner count safely
    owner_sr = v.owner_count or 1
    if isinstance(owner_sr, str) and owner_sr.isdigit():
        owner_sr = int(owner_sr)
    elif not isinstance(owner_sr, int):
        owner_sr = 1

    # RTO code from the dataclass or from the plate itself
    rto_code = ""
    if v.rto and v.rto.code:
        rto_code = v.rto.code.replace("-", "")
    if not rto_code:
        rto_code = re.sub(r"[^A-Z0-9]", "", rc_number.upper())[:4]

    reg_date = (v.additional_attributes.get("registration_date") if v.additional_attributes else None) or ""
    if not reg_date and v.manufacture_year:
        reg_date = f"{v.manufacture_year}-01-01"

    return {
        "rc_number": v.registration_number,
        "reg_date": reg_date,
        "owner_name": v.owner_name_masked or "",
        "fuel_type": (v.fuel_type or "Petrol").title(),
        "vehicle_manufacturer": v.make_and_model.split()[0] if v.make_and_model else "",
        "vehicle_model": v.make_and_model or "",
        "variant": v.variant or "",
        "transmission": v.transmission or "Manual",
        "owner_sr": owner_sr,
        "rto_code": rto_code,
        "vehicle_class": v.vehicle_category or "LMV",
        "insurance_validity": (v.insurance.expiry_date if v.insurance else "") or "",
        "fitness_upto": "",
        "financer": "",
        "color": v.color or "",
        "rc_status": "Active",
        "body_type": v.body_type or "",
        "is_commercial": False,
        "blacklist_status": "Not Blacklisted",
        "blacklist_reason": "",
        "pending_challan": bool(v.total_challans and v.total_challans > 0),
        "challan_amount": str(v.total_challan_amount) if v.total_challan_amount else "",
        "total_challans": v.total_challans or 0,
        "total_challan_amount": v.total_challan_amount or 0.0,
        "manufacture_year": v.manufacture_year,
        "city": v.city or "",
        "provider": result.provider or "",
        "lookup_time_ms": result.lookup_time_ms,
    }


# ─── Gemini AI (Normalize + Price Research) ─────────────────────────

def call_gemini(rc_data: dict, km_run: int) -> dict:
    """
    Single Gemini call with Google Search grounding to:
    1. Normalize messy RC model string → clean catalog match
    2. Research current market prices from CarDekho, Cars24, OLX, OrangeBookValue
    3. Return structured JSON
    """
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")

    # Build a compact catalog summary for the prompt.
    # Full variant list (not truncated) so uncommon trims — e.g. "Strong Hybrid
    # Alpha+" — aren't missed just because they weren't in the first 5 listed.
    catalog_summary = []
    for m in CATALOG["models"]:
        for g in m["generations"]:
            catalog_summary.append(
                f"{m['model']} | {g['gen']} | {g['years'][0]}-{g['years'][1]} | {', '.join(g['fuel_types'])} | {', '.join(g['variants'])}"
            )

    age_years = calc_age_years(rc_data["reg_date"]) if rc_data["reg_date"] else 0

    prompt = f"""You are a used car valuation expert for the Indian market, specifically Maruti Suzuki vehicles.

VEHICLE DATA FROM GOVERNMENT RC DATABASE:
- Registration Number: {rc_data['rc_number']}
- Raw Manufacturer: {rc_data['vehicle_manufacturer']}
- Raw Model String: {rc_data['vehicle_model']}
- Registration Date: {rc_data['reg_date']}
- Fuel Type (from RC): {rc_data['fuel_type']}
- Owner Serial Number: {rc_data['owner_sr']}
- RTO Code: {rc_data['rto_code']}
- Vehicle Class: {rc_data['vehicle_class']}
- Color: {rc_data['color']}
- KM Run (user input): {km_run}
- Approximate Age: {age_years:.1f} years

MARUTI SUZUKI MODEL CATALOG:
{chr(10).join(catalog_summary)}

YOUR TASKS:

1. NORMALIZE: Match the raw RC manufacturer/model string to the correct Maruti model, generation, and variant from the catalog above. Use registration year + fuel type to determine the correct generation. The raw model string sometimes includes the variant/trim directly (e.g. "GRAND VITARA STRONG HYBRID ALPHA+") — extract it if present. If variant genuinely cannot be determined, set it to "Unknown".

2. PRICE RESEARCH: Search for the current used car market price for this specific Maruti model in India. IMPORTANT: if you identified a specific variant/trim in step 1 (not "Unknown"), search for listings of THAT SPECIFIC VARIANT (e.g. "Swift VXI 2019", not just "Swift 2019") — different trims of the same model can differ by ₹0.5-1.5 lakh, so variant-specific search materially improves accuracy. Only fall back to model-only search (ignoring variant) if variant is "Unknown" or if variant-specific search returns too few results. Look at CarDekho, Cars24, OLX, Spinny, and Orange Book Value listings. Find what similar cars (same model, same variant if known, similar year, similar km range) are currently listed at.

3. SEGMENT BY SELLER TYPE: Among the listings you found, note whether prices differ between private-party sellers (OLX, individual CarDekho/Cars24 listings) versus dealer-certified listings (Cars24 Assured, Spinny Assured, Maruti True Value) — certified listings typically run 5-10% higher. Report this as a brief note, not a separate numeric range.

4. Return your response as ONLY a valid JSON object (no markdown formatting, no backticks, no explanation outside JSON):

{{
  "model": "Swift",
  "generation": "4th Gen",
  "variant": "VXI",
  "fuel_type": "Petrol",
  "body_type": "Hatchback",
  "confidence": 0.95,
  "registration_year": 2018,
  "ex_showroom_price_when_new_lakh": 7.5,
  "market_price_research": {{
    "low_lakh": 4.2,
    "high_lakh": 5.8,
    "median_lakh": 5.0,
    "sources_checked": ["CarDekho", "Cars24", "OLX"],
    "listings_found_approx": 15,
    "searched_variant_specifically": true,
    "price_basis": "Brief explanation of how you arrived at this range",
    "seller_type_note": "Brief note on private-party vs dealer-certified price difference, if observed"
  }},
  "flags": ["any warnings or observations"],
  "match_notes": "explanation of how you matched the model"
}}

IMPORTANT:
- The market prices must reflect CURRENT used car asking prices in India for this specific model+year+fuel combination
- If you find very few or no comparable listings, widen the year range by ±1 year and note this
- All prices in lakhs (₹)
- Do NOT include condition-based adjustments — the backend handles those separately
- Be conservative with the range — better to be slightly wide than confidently wrong"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
            # Gemini 2.5's internal "thinking" tokens count against maxOutputTokens.
            # With search grounding active, thinking can consume most of a small
            # budget before the final JSON is written, truncating it. This task
            # is extraction + light reasoning, not deep multi-step thought, so
            # disabling thinking leaves the full budget for the actual answer.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=45)
        data = resp.json()

        if resp.status_code != 200:
            error_msg = data.get("error", {}).get("message", "Unknown Gemini API error")
            raise HTTPException(status_code=502, detail=f"Gemini API error: {error_msg}")

        # Extract text from response - handle multiple content parts
        text_parts = []
        candidates = data.get("candidates", [])
        if not candidates:
            raise HTTPException(status_code=502, detail="No response from Gemini")

        finish_reason = candidates[0].get("finishReason", "")

        for part in candidates[0].get("content", {}).get("parts", []):
            if "text" in part:
                text_parts.append(part["text"])

        raw_text = "\n".join(text_parts).strip()

        # Clean up JSON from potential markdown fences
        raw_text = re.sub(r"^```json\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)
        raw_text = raw_text.strip()

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError:
            if finish_reason == "MAX_TOKENS":
                raise HTTPException(
                    status_code=502,
                    detail=(
                        "Gemini's response was cut off before finishing (hit the token limit). "
                        f"Raw (truncated): {raw_text[:500]}"
                    ),
                )
            raise  # re-raise to be caught by the outer handler below with full context

    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini returned non-JSON response. Raw: {raw_text[:500]}",
        )
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Gemini API call failed: {str(e)}")


# ─── Generate Explanation (Gemini) ──────────────────────────────────

def generate_explanation(rc_data: dict, gemini_result: dict, valuation: dict, price_research: dict) -> str:
    """Ask Gemini to write a human-readable valuation summary."""
    if not GEMINI_API_KEY:
        return _fallback_explanation(rc_data, gemini_result, valuation)

    cross_check = valuation.get("cross_check", {})
    cross_check_line = ""
    if cross_check.get("available"):
        cross_check_line = (
            f"DEPRECIATION-FORMULA CROSS-CHECK: A standard depreciation formula (based on the "
            f"original ex-showroom price of ₹{cross_check['ex_showroom_lakh']:.2f}L and the car's age) "
            f"independently estimates ₹{cross_check['formula_value_lakh']:.2f}L, versus the live-market "
            f"estimate above. Mention both figures and briefly note the difference between them "
            f"({cross_check['divergence_pct']:+.0f}%) — if it's large, suggest a plausible reason "
            f"(e.g. strong resale demand, fuel type trends, or model reputation)."
        )

    seller_note = price_research.get("seller_type_note", "")

    prompt = f"""Write a concise, professional 4-5 sentence valuation summary for a used car buyer/seller in India.

VEHICLE: {gemini_result.get('registration_year', '')} Maruti Suzuki {gemini_result.get('model', '')} {gemini_result.get('variant', '')} ({gemini_result.get('fuel_type', '')})
REGISTRATION: {rc_data['rc_number']} | {rc_data['owner_sr']} owner(s)
KM RUN: {valuation['meta']['km_run']:,} km | Age: {valuation['meta']['age_years']:.1f} years

MARKET BASE RANGE (before haircut): ₹{valuation['market_base']['low_lakh']:.2f}L – ₹{valuation['market_base']['high_lakh']:.2f}L
ADJUSTMENTS APPLIED:
- Asking-price haircut: listings are asking prices, not sale prices, so {valuation['adjustments']['haircut']['haircut_pct']:.0f}% was deducted first
- Confidence: {valuation['adjustments']['confidence']['label']}
- Usage: {valuation['adjustments']['usage']['label']} (ratio: {valuation['adjustments']['usage']['ratio']})
- Ownership: {valuation['adjustments']['ownership']['label']}
- Transmission: {valuation['adjustments']['transmission']['label']}
- Regulatory: {valuation['adjustments']['regulatory'].get('message') or 'No restrictions'}

FINAL ESTIMATED RANGE: ₹{valuation['final_range']['low_lakh']:.2f}L – ₹{valuation['final_range']['high_lakh']:.2f}L

{f"SELLER TYPE NOTE (private-party vs dealer-certified pricing): {seller_note}" if seller_note else ""}

{cross_check_line}

Write naturally, in flowing prose (not bullet points). Refer to the car only by its model and variant (e.g. "your Swift VXI") — do NOT say "Maruti Suzuki", "Maruti", or mention that this analysis involves AI. Mention the haircut, ownership, and transmission factors briefly. If a seller type note is given above, weave in a brief mention that private-party sales and dealer-certified sales may differ in price. End with a note that condition-based deductions are not included and should be assessed separately. Do NOT use markdown formatting. Keep it under 130 words."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 768, "thinkingConfig": {"thinkingBudget": 0}},
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        data = resp.json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        return parts[0].get("text", "").strip() if parts else _fallback_explanation(rc_data, gemini_result, valuation)
    except Exception:
        return _fallback_explanation(rc_data, gemini_result, valuation)


def _fallback_explanation(rc_data, gemini_result, valuation):
    """Plain text fallback if Gemini explanation call fails."""
    v = valuation
    model_name = f"{gemini_result.get('registration_year', '')} {gemini_result.get('model', '')} {gemini_result.get('variant', '')} ({gemini_result.get('fuel_type', '')})"
    return (
        f"Your {model_name} with {v['meta']['km_run']:,} km is estimated at "
        f"₹{v['final_range']['low_lakh']:.2f}L – ₹{v['final_range']['high_lakh']:.2f}L, after a "
        f"{v['adjustments']['haircut']['haircut_pct']:.0f}% haircut on listing prices (asking price vs sale price). "
        f"Usage is {v['adjustments']['usage']['label'].lower()}, ownership is "
        f"{v['adjustments']['ownership']['label'].lower()}, and transmission is "
        f"{v['adjustments']['transmission']['label'].lower()}. "
        f"Condition-based deductions are not included and should be assessed separately."
    )


# ─── Main Valuation Endpoint ───────────────────────────────────────

@app.post("/api/valuate")
async def valuate(req: ValuationRequest):
    rc_number = req.rc_number.upper().replace(" ", "").replace("-", "")

    # Validate inputs
    if not re.match(r"^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}$", rc_number):
        raise HTTPException(status_code=400, detail="Invalid RC number format. Example: KA01AB1234")
    if req.km_run < 0 or req.km_run > 999999:
        raise HTTPException(status_code=400, detail="KM run must be between 0 and 999,999")

    # Step 1: Decode RC via scraper
    rc_data = decode_rc(rc_number)

    # Check manufacturer
    make = (rc_data.get("vehicle_manufacturer") or "").strip().lower()
    model_str = (rc_data.get("vehicle_model") or "").strip().lower()
    is_maruti = any(k in make or k in model_str for k in ["maruti", "suzuki"])
    if not is_maruti:
        raise HTTPException(
            status_code=400,
            detail=f"CarValuator currently supports Maruti Suzuki vehicles only. Detected vehicle: {rc_data.get('vehicle_model') or make.title()}."
        )

    # Step 2: Gemini AI — normalize model + research market prices
    gemini_result = call_gemini(rc_data, req.km_run)

    # Step 3: Extract price research from Gemini
    price_research = gemini_result.get("market_price_research", {})
    # Use `or 0` instead of .get(key, 0) — Gemini can return an explicit `null`
    # for a field it's still present in the JSON, and .get()'s default only
    # applies when the key is missing entirely, not when its value is None.
    market_low = price_research.get("low_lakh") or 0
    market_high = price_research.get("high_lakh") or 0
    market_median = price_research.get("median_lakh") or 0

    if not market_low or not market_high or not market_median:
        raise HTTPException(
            status_code=422,
            detail=(
                "Could not determine a complete market price range for this vehicle. "
                f"Gemini returned: low={market_low}, high={market_high}, median={market_median}. "
                "The model may be too rare or comparable listings weren't found."
            ),
        )

    # Step 4: Calculate age
    age_years = calc_age_years(rc_data["reg_date"]) if rc_data["reg_date"] else 0

    # Determine fuel type (prefer Gemini's normalized version)
    fuel_type = gemini_result.get("fuel_type", rc_data.get("fuel_type", "Petrol"))

    # Step 5: Deterministic valuation adjustments
    valuation = compute_valuation(
        market_low=market_low,
        market_high=market_high,
        market_median=market_median,
        km_run=req.km_run,
        age_years=age_years,
        fuel_type=fuel_type,
        owner_sr=rc_data.get("owner_sr", 1),
        rto_code=rc_data.get("rto_code", ""),
        variant=gemini_result.get("variant", ""),
        listings_count=price_research.get("listings_found_approx", 0),
        model=gemini_result.get("model", ""),
        generation=gemini_result.get("generation", ""),
    )

    # Step 6: AI-generated explanation
    explanation = generate_explanation(rc_data, gemini_result, valuation, price_research)

    # Surface blacklist/challan warnings from the RC data alongside Gemini's own flags
    flags = list(gemini_result.get("flags", []))
    if rc_data.get("blacklist_status", "").strip().lower() == "blacklisted":
        reason = rc_data.get("blacklist_reason", "")
        flags.append(f"⛔ Vehicle is BLACKLISTED{f' — {reason}' if reason else ''}. Verify carefully before proceeding.")
    if rc_data.get("pending_challan"):
        ch_count = rc_data.get("total_challans", 0)
        ch_amt = rc_data.get("total_challan_amount", 0)
        parts = []
        if ch_count:
            parts.append(f"{ch_count} pending challan{'s' if ch_count > 1 else ''}")
        if ch_amt:
            parts.append(f"totalling ₹{ch_amt:,.0f}")
        flags.append(f"⚠️ {' '.join(parts) or 'Pending traffic challans'} on this vehicle.")
    if rc_data.get("is_commercial"):
        flags.append("ℹ️ Registered as a commercial vehicle — resale dynamics differ from private vehicles.")

    # Build response
    return {
        "vehicle": {
            "rc_number": rc_data["rc_number"],
            "model": gemini_result.get("model", "Unknown"),
            "generation": gemini_result.get("generation", "Unknown"),
            "variant": gemini_result.get("variant", "Unknown"),
            "fuel_type": fuel_type,
            "body_type": gemini_result.get("body_type", ""),
            "registration_year": gemini_result.get("registration_year", ""),
            "color": rc_data.get("color", ""),
            "owner_count": rc_data.get("owner_sr", 1),
            "insurance_valid_till": rc_data.get("insurance_validity", ""),
            "financer": rc_data.get("financer", ""),
            "confidence": gemini_result.get("confidence", 0),
        },
        "valuation": valuation,
        "price_research": price_research,
        "explanation": explanation,
        "flags": flags,
        "disclaimer": "This is an estimated market range based on current listings. Actual value depends on physical condition, service history, and negotiation. Condition-based deductions are NOT included.",
    }


# ─── Serve Frontend ────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))

@app.get("/{filename}")
async def serve_static(filename: str):
    filepath = os.path.join(BASE_DIR, filename)
    if os.path.isfile(filepath) and filename in ["style.css", "app_v4.js", "favicon.ico"]:
        return FileResponse(filepath)
    raise HTTPException(status_code=404)
