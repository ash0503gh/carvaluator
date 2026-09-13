# CarValuator

AI-powered Maruti Suzuki used car valuation tool. Enter a registration number and odometer reading to get an estimated market value range.

## How It Works

1. **RC Decode** — Fetches vehicle identity (model, year, fuel, ownership count) from government VAHAN database via RapidAPI
2. **AI Price Research** — Gemini Flash searches live listings on CarDekho, Cars24, OLX, and OrangeBookValue to find current market prices
3. **Deterministic Adjustments** — Python applies KM usage, ownership count, and regulatory (NCR diesel ban) multipliers
4. **AI Explanation** — Gemini generates a human-readable valuation summary

## Setup

### 1. API Keys (both free tier)

**Gemini API:**
- Go to [Google AI Studio](https://aistudio.google.com/apikey)
- Create a free API key

**RapidAPI (Vehicle RC Verification):**
- Sign up at [RapidAPI](https://rapidapi.com)
- Subscribe to [Vehicle RC Verification](https://rapidapi.com/zapfintek/api/vehicle-rc-verification1) by zapfintek (free tier: 500,000 requests/month, 1000/hour rate limit)
- Copy your API key
- Synchronous single-call API — sends `rc_number` as form-urlencoded, returns vehicle data directly (no task/poll flow)

### 2. Local Development

```bash
cp .env.example .env
# Edit .env with your API keys

pip install -r requirements.txt
uvicorn main_v3:app --reload --port 8000
```

Open `http://localhost:8000`

### 3. Deploy to Render

- Push to GitHub
- Create a new **Web Service** on Render
- Set environment variables: `GEMINI_API_KEY`, `RAPIDAPI_KEY`
- Start command: `uvicorn main_v3:app --host 0.0.0.0 --port $PORT`

## Valuation Logic

```
Market Price (from live listings, already reflects age depreciation)
  × KM Usage Adjustment (over/under-driven vs expected for age)
  × Ownership Multiplier (1st: 1.0, 2nd: 0.94, 3rd: 0.88, 4th+: 0.80)
  × Regulatory Adjustment (NCR diesel 10yr / petrol 15yr ban)
  = Estimated Range [low — median — high]
```

Condition-based deductions are applied manually by the user after seeing the result.

## File Structure

```
main_v3.py              FastAPI backend
valuation_v1.py         Deterministic valuation math
maruti_catalog_v1.json  Model/generation/variant catalog (2010+)
index.html              Frontend
style.css               Styling
app_v1.js               Frontend JavaScript
requirements.txt        Python dependencies
Procfile                Render deployment
.env.example            Environment variable template
```
