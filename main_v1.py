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
from valuation_v1 import compute_valuation, calc_age_years, load_catalog

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


# ─── RC Decode (Vehicle Details PRO - RapidAPI) ─────────────────────
# Confirmed against a live test response (10 free calls/month on Basic).
# Simple GET + query param, no request signing needed — unlike Eko's HMAC flow.

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")

def decode_rc(rc_number: str) -> dict:
    """
    Call "Vehicle Details PRO" (abhiyanpa7) on RapidAPI.
    Free tier: 10 requests/month. Pro: $9.99/mo for 2,500 requests.
    Response envelope is double-nested: {"success", "source", "data": {"data": {...}}}.
    """
    if not RAPIDAPI_KEY:
        raise HTTPException(status_code=500, detail="RAPIDAPI_KEY not configured")

    url = "https://vehicle-details-pro.p.rapidapi.com/"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": "vehicle-details-pro.p.rapidapi.com",
        "Content-Type": "application/json",
    }
    params = {"reg_number": rc_number.upper().replace(" ", "")}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"RC API call failed: {str(e)}")

    if resp.status_code == 401 or resp.status_code == 403:
        raise HTTPException(
            status_code=502,
            detail=f"RapidAPI authentication failed (HTTP {resp.status_code}). Check RAPIDAPI_KEY in Render's environment variables. Response: {resp.text[:300]}",
        )
    if resp.status_code == 429:
        raise HTTPException(
            status_code=502,
            detail="RapidAPI rate limit or monthly quota exceeded (free tier is 10 requests/month). Check your plan usage on RapidAPI dashboard.",
        )

    try:
        envelope = resp.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail=f"RC API returned non-JSON response (status {resp.status_code}): {resp.text[:300]}",
        )

    if resp.status_code != 200 or not envelope.get("success"):
        raise HTTPException(
            status_code=404,
            detail=f"Could not find vehicle data for {rc_number}. API response (status {resp.status_code}): {json.dumps(envelope)[:400]}",
        )

    # Envelope is double-nested: envelope["data"]["data"] holds the actual fields
    outer = envelope.get("data") or {}
    data = outer.get("data") if isinstance(outer.get("data"), dict) else outer
    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Could not find vehicle data for {rc_number}. Response: {json.dumps(envelope)[:400]}",
        )

    blacklist_status = data.get("blacklistStatus", "") or ""
    blacklist_details = data.get("blacklistDetails") or []
    # Provider uses "NA" (string) as a sentinel for "no blacklist", not an empty value
    is_blacklisted = blacklist_status.strip().upper() not in ("", "NA", "NOT BLACKLISTED")
    blacklist_reason = ""
    if is_blacklisted and isinstance(blacklist_details, list) and blacklist_details:
        first = blacklist_details[0]
        if isinstance(first, str) and first.upper() != "NA":
            blacklist_reason = first
        elif isinstance(first, dict):
            blacklist_reason = first.get("reason", "")

    owner_count_raw = data.get("ownerCount", "1")
    try:
        owner_sr = int(str(owner_count_raw).strip() or "1")
    except ValueError:
        owner_sr = 1

    return {
        "rc_number": data.get("regNo", rc_number),
        "reg_date": data.get("regDate", ""),
        "owner_name": data.get("owner", ""),
        "fuel_type": (data.get("type", "") or "").title(),
        "vehicle_manufacturer": data.get("vehicleManufacturerName", ""),
        "vehicle_model": data.get("model", ""),
        "owner_sr": owner_sr,
        "rto_code": data.get("rtoCode", rc_number[:4].upper()),
        "vehicle_class": data.get("vehicleClass", ""),
        "insurance_validity": data.get("vehicleInsuranceUpto", ""),
        "fitness_upto": data.get("rcExpiryDate", ""),
        "financer": data.get("rcFinancer", "") or "",
        "color": data.get("vehicleColour", ""),
        "rc_status": data.get("status", ""),
        "body_type": data.get("bodyType", ""),
        "is_commercial": bool(data.get("isCommercial", False)),
        "blacklist_status": "Blacklisted" if is_blacklisted else "Not Blacklisted",
        "blacklist_reason": blacklist_reason,
        # This provider doesn't return challan data — default to no pending challan
        "pending_challan": False,
        "challan_amount": "",
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

    # Build a compact catalog summary for the prompt
    catalog_summary = []
    for m in CATALOG["models"]:
        for g in m["generations"]:
            catalog_summary.append(
                f"{m['model']} | {g['gen']} | {g['years'][0]}-{g['years'][1]} | {', '.join(g['fuel_types'])} | {', '.join(g['variants'][:5])}..."
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

1. NORMALIZE: Match the raw RC manufacturer/model string to the correct Maruti model, generation, and variant from the catalog above. Use registration year + fuel type to determine the correct generation. If variant cannot be determined from the RC string, set it to "Unknown".

2. PRICE RESEARCH: Search for the current used car market price for this specific Maruti model, approximate year ({rc_data['reg_date'][:4] if rc_data['reg_date'] else 'unknown'}), and fuel type in India. Look at CarDekho, Cars24, OLX, Spinny, and Orange Book Value listings. Find what similar cars (same model, similar year, similar km range) are currently listed at.

3. Return your response as ONLY a valid JSON object (no markdown formatting, no backticks, no explanation outside JSON):

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
    "price_basis": "Brief explanation of how you arrived at this range"
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

def generate_explanation(rc_data: dict, gemini_result: dict, valuation: dict) -> str:
    """Ask Gemini to write a human-readable valuation summary."""
    if not GEMINI_API_KEY:
        return _fallback_explanation(rc_data, gemini_result, valuation)

    prompt = f"""Write a concise, professional 3-4 sentence valuation summary for a used car buyer/seller in India.

VEHICLE: {gemini_result.get('registration_year', '')} Maruti Suzuki {gemini_result.get('model', '')} {gemini_result.get('variant', '')} ({gemini_result.get('fuel_type', '')})
REGISTRATION: {rc_data['rc_number']} | {rc_data['owner_sr']} owner(s)
KM RUN: {valuation['meta']['km_run']:,} km | Age: {valuation['meta']['age_years']:.1f} years

MARKET BASE RANGE: ₹{valuation['market_base']['low_lakh']:.2f}L – ₹{valuation['market_base']['high_lakh']:.2f}L
ADJUSTMENTS APPLIED:
- Usage: {valuation['adjustments']['usage']['label']} (ratio: {valuation['adjustments']['usage']['ratio']})
- Ownership: {valuation['adjustments']['ownership']['label']}
- Regulatory: {valuation['adjustments']['regulatory'].get('message') or 'No restrictions'}

FINAL ESTIMATED RANGE: ₹{valuation['final_range']['low_lakh']:.2f}L – ₹{valuation['final_range']['high_lakh']:.2f}L

Write naturally. Mention each adjustment factor briefly. End with a note that condition-based deductions are not included and should be assessed separately. Do NOT use markdown formatting. Keep it under 100 words."""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
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
        f"₹{v['final_range']['low_lakh']:.2f}L – ₹{v['final_range']['high_lakh']:.2f}L. "
        f"Usage is {v['adjustments']['usage']['label'].lower()} and ownership is "
        f"{v['adjustments']['ownership']['label'].lower()}. "
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

    # Step 1: Decode RC via RapidAPI
    rc_data = decode_rc(rc_number)

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
    )

    # Step 6: AI-generated explanation
    explanation = generate_explanation(rc_data, gemini_result, valuation)

    # Surface blacklist/challan warnings from the RC data alongside Gemini's own flags
    flags = list(gemini_result.get("flags", []))
    if rc_data.get("blacklist_status", "").strip().lower() == "blacklisted":
        reason = rc_data.get("blacklist_reason", "")
        flags.append(f"⛔ Vehicle is BLACKLISTED{f' — {reason}' if reason else ''}. Verify carefully before proceeding.")
    if rc_data.get("pending_challan"):
        amount = rc_data.get("challan_amount", "")
        flags.append(f"⚠️ Pending traffic challan{f' of ₹{amount}' if amount else ''} on this vehicle.")
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
    if os.path.isfile(filepath) and filename in ["style.css", "app_v1.js", "favicon.ico"]:
        return FileResponse(filepath)
    raise HTTPException(status_code=404)
