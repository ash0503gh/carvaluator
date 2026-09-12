// ─── CarValuator Frontend ──────────────────────────────────────────

async function submitValuation() {
    const rcInput = document.getElementById("rc-number");
    const kmInput = document.getElementById("km-run");
    const btn = document.getElementById("valuate-btn");
    const btnText = btn.querySelector(".btn-text");
    const btnLoader = btn.querySelector(".btn-loader");
    const note = document.getElementById("processing-note");
    const errorContainer = document.getElementById("error-container");
    const errorMessage = document.getElementById("error-message");
    const results = document.getElementById("results");

    // Reset
    errorContainer.style.display = "none";
    results.style.display = "none";

    // Validate
    const rc = rcInput.value.trim().toUpperCase().replace(/[\s-]/g, "");
    const km = parseInt(kmInput.value, 10);

    if (!rc) {
        showError("Please enter a registration number.");
        rcInput.focus();
        return;
    }

    if (isNaN(km) || km < 0) {
        showError("Please enter a valid odometer reading.");
        kmInput.focus();
        return;
    }

    // Loading state
    btn.disabled = true;
    btnText.style.display = "none";
    btnLoader.style.display = "inline-flex";
    note.style.display = "block";

    try {
        const resp = await fetch("/api/valuate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rc_number: rc, km_run: km }),
        });

        const data = await resp.json();

        if (!resp.ok) {
            throw new Error(data.detail || "Something went wrong. Please try again.");
        }

        renderResults(data);
    } catch (err) {
        showError(err.message);
    } finally {
        btn.disabled = false;
        btnText.style.display = "inline";
        btnLoader.style.display = "none";
        note.style.display = "none";
    }
}

function showError(msg) {
    const container = document.getElementById("error-container");
    const message = document.getElementById("error-message");
    message.textContent = msg;
    container.style.display = "block";
    container.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ─── Render Results ────────────────────────────────────────────────

function renderResults(data) {
    const results = document.getElementById("results");
    const v = data.vehicle;
    const val = data.valuation;

    // Vehicle title
    const title = document.getElementById("vehicle-title");
    title.textContent = `${v.registration_year || ""} Maruti Suzuki ${v.model} ${v.variant !== "Unknown" ? v.variant : ""}`.trim();

    // Confidence badge
    const badge = document.getElementById("confidence-badge");
    const conf = v.confidence || 0;
    badge.textContent = `${Math.round(conf * 100)}% match`;
    badge.className = "confidence-badge " + (
        conf >= 0.85 ? "confidence-high" :
        conf >= 0.6 ? "confidence-medium" :
        "confidence-low"
    );

    // Vehicle meta tags
    const meta = document.getElementById("vehicle-meta");
    const tags = [
        v.rc_number,
        v.fuel_type,
        v.body_type,
        `${v.owner_count} owner${v.owner_count > 1 ? "s" : ""}`,
        val.meta.km_run.toLocaleString("en-IN") + " km",
        val.meta.age_years.toFixed(1) + " years old",
        v.color,
    ].filter(Boolean);

    if (v.insurance_valid_till) tags.push("Insured till " + v.insurance_valid_till);
    if (v.financer) tags.push("Financed: " + v.financer);

    meta.innerHTML = tags.map(t => `<span class="meta-tag">${t}</span>`).join("");

    // Valuation range
    const low = val.final_range.low_lakh;
    const high = val.final_range.high_lakh;
    const median = val.final_range.median_lakh;

    document.getElementById("range-low").textContent = formatLakh(low);
    document.getElementById("range-high").textContent = formatLakh(high);
    document.getElementById("range-median").textContent = formatLakh(median);

    // Position the marker based on median within low-high range
    const pct = high > low ? ((median - low) / (high - low)) * 80 + 10 : 50;
    document.getElementById("range-marker").style.left = pct + "%";

    // Explanation
    document.getElementById("explanation").textContent = data.explanation || "";

    // Adjustments grid
    const grid = document.getElementById("adjustment-grid");
    const adj = val.adjustments;

    const items = [
        {
            label: "Market Base",
            value: `${formatLakh(val.market_base.low_lakh)} – ${formatLakh(val.market_base.high_lakh)}`,
            detail: `Median: ${formatLakh(val.market_base.median_lakh)} · ${data.price_research.listings_found_approx || "~"} listings found`,
            colorClass: "adj-neutral",
        },
        {
            label: "KM Usage",
            value: `×${adj.usage.multiplier.toFixed(3)}`,
            detail: `${adj.usage.label} · ${val.meta.km_run.toLocaleString("en-IN")} km vs ${(adj.usage.expected_km || 0).toLocaleString("en-IN")} expected (ratio: ${adj.usage.ratio})`,
            colorClass: adj.usage.multiplier >= 1.0 ? "adj-positive" : "adj-negative",
        },
        {
            label: "Ownership",
            value: `×${adj.ownership.multiplier.toFixed(2)}`,
            detail: adj.ownership.label,
            colorClass: adj.ownership.multiplier >= 1.0 ? "adj-neutral" : "adj-negative",
        },
        {
            label: "Regulatory",
            value: adj.regulatory.flag ? `×${adj.regulatory.multiplier.toFixed(2)}` : "No restriction",
            detail: adj.regulatory.message || (adj.regulatory.is_ncr ? "Delhi-NCR registered, within limits" : "Non-NCR registration"),
            colorClass: adj.regulatory.multiplier < 0.9 ? "adj-critical" : adj.regulatory.multiplier < 1.0 ? "adj-negative" : "adj-neutral",
        },
    ];

    grid.innerHTML = items.map(item => `
        <div class="adj-item">
            <div class="adj-label">${item.label}</div>
            <div class="adj-value ${item.colorClass}">${item.value}</div>
            <div class="adj-detail">${item.detail}</div>
        </div>
    `).join("");

    // Flags
    const flagsCard = document.getElementById("flags-card");
    const flagsList = document.getElementById("flags-list");
    const allFlags = [
        ...(data.flags || []),
        ...(adj.regulatory.message ? [adj.regulatory.message] : []),
    ];

    if (allFlags.length > 0) {
        flagsCard.style.display = "block";
        flagsList.innerHTML = allFlags.map(f => `<div class="flag-item">${f}</div>`).join("");
    } else {
        flagsCard.style.display = "none";
    }

    // Disclaimer
    document.getElementById("disclaimer").textContent = data.disclaimer || "";

    // Show results
    results.style.display = "block";
    results.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ─── Helpers ───────────────────────────────────────────────────────

function formatLakh(val) {
    if (val === undefined || val === null) return "—";
    return "₹" + val.toFixed(2) + "L";
}

// Allow Enter key to submit
document.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !document.getElementById("valuate-btn").disabled) {
        submitValuation();
    }
});

// Auto-uppercase RC number input
document.getElementById("rc-number").addEventListener("input", function () {
    this.value = this.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
});
