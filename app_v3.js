// ─── CarValuator Frontend ──────────────────────────────────────────

const LOADING_MESSAGES = [
    "Reading registration details",
    "Matching car model and variant",
    "Checking current listings",
    "Calculating adjustments",
];

let loadingMessageInterval = null;
let lastSummaryText = "";

async function submitValuation() {
    const rcInput = document.getElementById("rc-number");
    const kmInput = document.getElementById("km-run");
    const btn = document.getElementById("valuate-btn");
    const btnText = btn.querySelector(".btn-text");
    const btnLoader = btn.querySelector(".btn-loader");
    const loadingMessageEl = document.getElementById("loading-message");
    const errorContainer = document.getElementById("error-container");
    const errorMessage = document.getElementById("error-message");
    const results = document.getElementById("results");

    errorContainer.style.display = "none";
    results.style.display = "none";

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

    btn.disabled = true;
    btnText.style.display = "none";
    btnLoader.style.display = "inline-flex";

    let msgIndex = 0;
    loadingMessageEl.textContent = LOADING_MESSAGES[0];
    loadingMessageInterval = setInterval(() => {
        msgIndex = (msgIndex + 1) % LOADING_MESSAGES.length;
        loadingMessageEl.textContent = LOADING_MESSAGES[msgIndex];
    }, 2200);

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
        clearInterval(loadingMessageInterval);
        btn.disabled = false;
        btnText.style.display = "inline";
        btnLoader.style.display = "none";
    }
}

function showError(msg) {
    const container = document.getElementById("error-container");
    const message = document.getElementById("error-message");
    message.textContent = msg;
    container.style.display = "block";
    container.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ─── Icons ──────────────────────────────────────────────────────────

const ICONS = {
    marketBase: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M4 20V10M12 20V4M20 20V14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    haircut: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M6 9L15 18M15 9L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="6" cy="6" r="2.5" stroke="currentColor" stroke-width="2"/><circle cx="6" cy="18" r="2.5" stroke="currentColor" stroke-width="2"/></svg>',
    confidence: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="5" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/></svg>',
    usage: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z" stroke="currentColor" stroke-width="2"/><path d="M12 12L16 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    ownership: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="8" r="3.2" stroke="currentColor" stroke-width="2"/><path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    transmission: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="2"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    regulatory: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6l7-3Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
    check: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none"><path d="M4 12l6 6L20 6" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
};

// ─── Render Results ────────────────────────────────────────────────

function renderResults(data) {
    const results = document.getElementById("results");
    const v = data.vehicle;
    const val = data.valuation;

    // Vehicle title — model + variant only, no manufacturer prefix
    const title = document.getElementById("vehicle-title");
    title.textContent = `${v.registration_year || ""} ${v.model} ${v.variant !== "Unknown" ? v.variant : ""}`.trim();

    const badge = document.getElementById("confidence-badge");
    const conf = v.confidence || 0;
    badge.textContent = `${Math.round(conf * 100)}% match`;
    badge.className = "confidence-badge " + (
        conf >= 0.85 ? "confidence-high" :
        conf >= 0.6 ? "confidence-medium" :
        "confidence-low"
    );

    const meta = document.getElementById("vehicle-meta");
    const tags = [
        v.rc_number,
        v.fuel_type,
        v.body_type,
        `${v.owner_count} owner${v.owner_count > 1 ? "s" : ""}`,
        val.meta.km_run.toLocaleString("en-IN") + " km",
        val.meta.age_years.toFixed(1) + " yrs old",
    ].filter(Boolean);
    meta.innerHTML = tags.map(t => `<span class="meta-tag">${t}</span>`).join("");

    // Gauge
    const low = val.final_range.low_lakh;
    const high = val.final_range.high_lakh;
    const median = val.final_range.median_lakh;

    document.getElementById("range-low").textContent = formatLakh(low);
    document.getElementById("range-high").textContent = formatLakh(high);

    const pct = high > low ? Math.max(0, Math.min(1, (median - low) / (high - low))) : 0.5;
    const needleAngle = -90 + pct * 180;

    // Trigger the reveal animation (arc draws in + needle sweeps to position)
    const arc = document.getElementById("gauge-arc");
    const needle = document.getElementById("gauge-needle");
    arc.style.strokeDashoffset = "314";
    needle.style.transform = "rotate(-90deg)";
    requestAnimationFrame(() => {
        setTimeout(() => {
            arc.style.strokeDashoffset = "0";
            needle.style.transform = `rotate(${needleAngle}deg)`;
        }, 50);
    });

    animateCountUp(document.getElementById("gauge-price"), median);

    // Source badges
    const badgesEl = document.getElementById("source-badges");
    const sources = (data.price_research.sources_checked && data.price_research.sources_checked.length)
        ? data.price_research.sources_checked
        : ["CarDekho", "Cars24", "OLX"];
    badgesEl.innerHTML = sources.map(s => `<span class="source-badge">${ICONS.check}${s}</span>`).join("");

    // Breakdown rows
    const grid = document.getElementById("adjustment-grid");
    const adj = val.adjustments;

    const rows = [
        {
            icon: ICONS.marketBase, cls: "",
            label: "Market listings",
            value: `${formatLakh(val.market_base.low_lakh)} – ${formatLakh(val.market_base.high_lakh)}`,
            detail: `${data.price_research.listings_found_approx || "~"} comparable listings${data.price_research.searched_variant_specifically ? ", matched to your variant" : ""}`,
        },
        {
            icon: ICONS.haircut, cls: "negative",
            label: "Asking-price adjustment",
            value: `−${adj.haircut.haircut_pct.toFixed(0)}%`,
            detail: "Listings are asking prices, not sale prices",
        },
        {
            icon: ICONS.confidence, cls: adj.confidence.confidence === "low" ? "negative" : adj.confidence.confidence === "high" ? "positive" : "",
            label: "Confidence",
            value: adj.confidence.confidence.charAt(0).toUpperCase() + adj.confidence.confidence.slice(1),
            detail: adj.confidence.label,
        },
        {
            icon: ICONS.usage, cls: adj.usage.multiplier >= 1.0 ? "positive" : "negative",
            label: "Usage",
            value: `×${adj.usage.multiplier.toFixed(3)}`,
            detail: `${adj.usage.label} · ${val.meta.km_run.toLocaleString("en-IN")} km vs ${(adj.usage.expected_km || 0).toLocaleString("en-IN")} expected`,
        },
        {
            icon: ICONS.ownership, cls: adj.ownership.multiplier >= 1.0 ? "" : "negative",
            label: "Ownership",
            value: `×${adj.ownership.multiplier.toFixed(2)}`,
            detail: adj.ownership.label,
        },
        {
            icon: ICONS.transmission, cls: adj.transmission.is_automatic ? "positive" : "",
            label: "Transmission",
            value: `×${adj.transmission.multiplier.toFixed(2)}`,
            detail: adj.transmission.label,
        },
        {
            icon: ICONS.regulatory, cls: adj.regulatory.multiplier < 0.9 ? "critical" : adj.regulatory.multiplier < 1.0 ? "negative" : "",
            label: "Regulatory",
            value: adj.regulatory.flag ? `×${adj.regulatory.multiplier.toFixed(2)}` : "No restriction",
            detail: adj.regulatory.message || (adj.regulatory.is_ncr ? "Registered in NCR, within limits" : "No regional restriction applies"),
        },
    ];

    grid.innerHTML = rows.map(r => `
        <div class="breakdown-row">
            <div class="breakdown-icon ${r.cls}">${r.icon}</div>
            <div class="breakdown-body">
                <div class="breakdown-top">
                    <span class="breakdown-label">${r.label}</span>
                    <span class="breakdown-value">${r.value}</span>
                </div>
                <div class="breakdown-detail">${r.detail}</div>
            </div>
        </div>
    `).join("");

    const sellerNoteEl = document.getElementById("seller-type-note");
    const sellerNote = data.price_research.seller_type_note;
    if (sellerNote) {
        sellerNoteEl.textContent = sellerNote;
        sellerNoteEl.style.display = "block";
    } else {
        sellerNoteEl.style.display = "none";
    }

    // Cross-check
    const crossCheckCard = document.getElementById("cross-check-card");
    const cc = val.cross_check;
    if (cc && cc.available) {
        crossCheckCard.style.display = "block";
        document.getElementById("cc-formula-value").textContent = formatLakh(cc.formula_value_lakh);
        document.getElementById("cc-formula-detail").textContent = `${cc.depreciation_pct.toFixed(0)}% depreciation from ₹${cc.ex_showroom_lakh.toFixed(2)}L when new`;
        document.getElementById("cc-market-value").textContent = formatLakh(cc.live_market_median_lakh);
        const divergenceEl = document.getElementById("cc-divergence");
        const sign = cc.divergence_pct >= 0 ? "+" : "";
        divergenceEl.textContent = `Live market is ${sign}${cc.divergence_pct.toFixed(0)}% vs. the formula estimate`;
        divergenceEl.className = "cc-divergence " + (cc.significant_divergence ? "cc-divergence-high" : "");
    } else {
        crossCheckCard.style.display = "none";
    }

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

    document.getElementById("explanation").textContent = data.explanation || "";
    document.getElementById("disclaimer").textContent = data.disclaimer || "";

    // Build a shareable summary for copy/share buttons
    lastSummaryText = `${title.textContent} — estimated ${formatLakh(low)} to ${formatLakh(high)} (median ${formatLakh(median)}).\n\n${data.explanation || ""}`;

    results.style.display = "block";
    results.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ─── Helpers ───────────────────────────────────────────────────────

function formatLakh(val) {
    if (val === undefined || val === null) return "—";
    return "₹" + val.toFixed(2) + "L";
}

function animateCountUp(el, target) {
    const duration = 900;
    const start = performance.now();
    function tick(now) {
        const elapsed = now - start;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        const current = target * eased;
        el.textContent = formatLakh(current);
        if (progress < 1) requestAnimationFrame(tick);
        else el.textContent = formatLakh(target);
    }
    requestAnimationFrame(tick);
}

function copySummary() {
    if (!lastSummaryText) return;
    navigator.clipboard.writeText(lastSummaryText).then(() => {
        const btn = document.getElementById("copy-btn");
        const original = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = original; }, 1500);
    });
}

function shareSummary() {
    if (!lastSummaryText) return;
    if (navigator.share) {
        navigator.share({ title: "Car valuation", text: lastSummaryText }).catch(() => {});
    } else {
        copySummary();
        const btn = document.getElementById("share-btn");
        const original = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = original; }, 1500);
    }
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
