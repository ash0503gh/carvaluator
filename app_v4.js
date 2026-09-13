// ─── CarValuator ───────────────────────────────────────────────────

const STAGES = [
    "Reading registration details",
    "Matching model and variant",
    "Searching current listings",
    "Applying adjustments",
];

let stageTimer = null;
let summaryText = "";

// ─── Icons (20×20, stroke only, clean weight) ──────────────────────

const I = {
    bars:    `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 20V10M12 20V4M20 20V14"/></svg>`,
    cut:     `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><line x1="20" y1="4" x2="8.12" y2="15.88"/><line x1="14.47" y1="14.48" x2="20" y2="20"/><line x1="8.12" y1="8.12" x2="12" y2="12"/></svg>`,
    target:  `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`,
    gauge:   `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 12l4-4"/><path d="M12 8v-2"/></svg>`,
    user:    `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/></svg>`,
    gear:    `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>`,
    shield:  `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>`,
    check:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
};

// ─── Submit ────────────────────────────────────────────────────────

async function submitValuation() {
    const rcInput  = document.getElementById("rc-number");
    const kmInput  = document.getElementById("km-run");
    const btn      = document.getElementById("valuate-btn");
    const btnLabel = btn.querySelector(".cta-label");
    const btnLoad  = btn.querySelector(".cta-loading");
    const loadMsg  = document.getElementById("loading-msg");
    const errBox   = document.getElementById("error-box");
    const results  = document.getElementById("results");

    errBox.style.display = "none";
    results.style.display = "none";

    const rc = rcInput.value.trim().toUpperCase().replace(/[\s\-]/g, "");
    const km = parseInt(kmInput.value, 10);

    if (!rc) { showErr("Enter a registration number."); rcInput.focus(); return; }
    if (isNaN(km) || km < 0) { showErr("Enter a valid odometer reading."); kmInput.focus(); return; }

    btn.disabled = true;
    btnLabel.style.display = "none";
    btnLoad.style.display = "inline-flex";

    let si = 0;
    loadMsg.textContent = STAGES[0];
    stageTimer = setInterval(() => {
        si = (si + 1) % STAGES.length;
        loadMsg.textContent = STAGES[si];
    }, 2500);

    try {
        const resp = await fetch("/api/valuate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rc_number: rc, km_run: km }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Something went wrong.");
        render(data);
    } catch (e) {
        showErr(e.message);
    } finally {
        clearInterval(stageTimer);
        btn.disabled = false;
        btnLabel.style.display = "inline";
        btnLoad.style.display = "none";
    }
}

function showErr(msg) {
    const box = document.getElementById("error-box");
    document.getElementById("error-msg").textContent = msg;
    box.style.display = "block";
    box.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ─── Render ────────────────────────────────────────────────────────

function render(data) {
    const v   = data.vehicle;
    const val = data.valuation;
    const adj = val.adjustments;
    const pr  = data.price_research;
    const cc  = val.cross_check;

    // Vehicle
    document.getElementById("vehicle-title").textContent =
        `${v.registration_year || ""} ${v.model} ${v.variant !== "Unknown" ? v.variant : ""}`.trim();

    const conf = v.confidence || 0;
    const badge = document.getElementById("confidence-badge");
    badge.textContent = `${Math.round(conf * 100)}% match`;
    badge.className = "match-pill " + (conf >= 0.85 ? "match-high" : conf >= 0.6 ? "match-med" : "match-low");

    const metaEl = document.getElementById("vehicle-meta");
    const metaTags = [
        v.rc_number, v.fuel_type, v.body_type,
        `${v.owner_count} owner${v.owner_count > 1 ? "s" : ""}`,
        val.meta.km_run.toLocaleString("en-IN") + " km",
        val.meta.age_years.toFixed(1) + " yrs",
    ];
    if (v.total_challans != null) {
        if (v.total_challans > 0) {
            metaTags.push(`${v.total_challans} Total Challan${v.total_challans > 1 ? "s" : ""} (₹${Math.round(v.total_challan_amount || 0).toLocaleString("en-IN")})`);
        } else {
            metaTags.push("0 Challans");
        }
    }
    metaEl.innerHTML = metaTags.filter(Boolean).map(t => `<span class="tag">${t}</span>`).join("");

    // Price
    const low = val.final_range.low_lakh;
    const high = val.final_range.high_lakh;
    const med = val.final_range.median_lakh;

    animateCount(document.getElementById("price-number"), med);

    document.getElementById("range-low").textContent = fmt(low);
    document.getElementById("range-high").textContent = fmt(high);

    const pct = high > low ? ((med - low) / (high - low)) : 0.5;
    const fill = document.getElementById("range-fill");
    const dot  = document.getElementById("range-dot");

    // Start at 0, then animate to position
    fill.style.left = "0%"; fill.style.width = "0%";
    dot.style.left = "0%";
    requestAnimationFrame(() => {
        setTimeout(() => {
            fill.style.left = "5%";
            fill.style.width = "90%";
            dot.style.left = `${(5 + pct * 90)}%`;
        }, 60);
    });

    // Sources
    const srcEl = document.getElementById("source-badges");
    const sources = pr.sources_checked && pr.sources_checked.length ? pr.sources_checked : ["CarDekho", "Cars24", "OLX"];
    srcEl.innerHTML = sources.map(s => `<span class="source-pill">${I.check} ${s}</span>`).join("");

    // Breakdown
    const grid = document.getElementById("adjustment-grid");
    const rows = [
        { icon: I.bars, cls: "", name: "Market listings",
          val: `${fmt(val.market_base.low_lakh)} – ${fmt(val.market_base.high_lakh)}`,
          note: `${pr.listings_found_approx || "~"} listings${pr.searched_variant_specifically ? ", variant-matched" : ""}` },

        { icon: I.cut, cls: "neg", name: "Asking-price adjustment",
          val: `−${adj.haircut.haircut_pct.toFixed(0)}%`,
          note: "Listings show asking prices, not what cars actually sell for" },

        { icon: I.target, cls: adj.confidence.confidence === "low" ? "neg" : adj.confidence.confidence === "high" ? "pos" : "",
          name: "Confidence",
          val: cap(adj.confidence.confidence),
          note: adj.confidence.label },

        { icon: I.gauge, cls: adj.usage.multiplier >= 1 ? "pos" : "neg",
          name: "Usage",
          val: `×${adj.usage.multiplier.toFixed(3)}`,
          note: `${adj.usage.label} · ${val.meta.km_run.toLocaleString("en-IN")} vs ${(adj.usage.expected_km||0).toLocaleString("en-IN")} expected` },

        { icon: I.user, cls: adj.ownership.multiplier >= 1 ? "" : "neg",
          name: "Ownership",
          val: `×${adj.ownership.multiplier.toFixed(2)}`,
          note: adj.ownership.label },

        { icon: I.gear, cls: adj.transmission.is_automatic ? "pos" : "",
          name: "Transmission",
          val: `×${adj.transmission.multiplier.toFixed(2)}`,
          note: adj.transmission.label },

        { icon: I.shield, cls: adj.regulatory.multiplier < 0.9 ? "crit" : adj.regulatory.multiplier < 1 ? "neg" : "",
          name: "Regulatory",
          val: adj.regulatory.flag ? `×${adj.regulatory.multiplier.toFixed(2)}` : "Clear",
          note: adj.regulatory.message || (adj.regulatory.is_ncr ? "NCR registered, within limits" : "No regional restriction") },
    ];

    grid.innerHTML = rows.map(r => `
        <div class="adj-row">
            <div class="adj-icon ${r.cls}">${r.icon}</div>
            <div class="adj-body">
                <div class="adj-top"><span class="adj-name">${r.name}</span><span class="adj-val">${r.val}</span></div>
                <div class="adj-note">${r.note}</div>
            </div>
        </div>`).join("");

    // Seller note
    const sn = document.getElementById("seller-type-note");
    if (pr.seller_type_note) { sn.textContent = pr.seller_type_note; sn.style.display = "block"; }
    else sn.style.display = "none";

    // Cross-check — only shown when divergence > 25%
    const ccCard = document.getElementById("cross-check-card");
    if (cc && cc.available && cc.significant_divergence) {
        ccCard.style.display = "block";
        document.getElementById("cc-formula-value").textContent = fmt(cc.formula_value_lakh);
        document.getElementById("cc-formula-detail").textContent = `${cc.depreciation_pct.toFixed(0)}% dep. from ${fmt(cc.ex_showroom_lakh)} when new`;
        document.getElementById("cc-market-value").textContent = fmt(cc.live_market_median_lakh);
        const sign = cc.divergence_pct >= 0 ? "+" : "";
        document.getElementById("cc-intro").textContent =
            `The standard depreciation formula and live market differ by ${sign}${cc.divergence_pct.toFixed(0)}%. This usually means the car holds value better (or worse) than average — worth double-checking.`;
    } else {
        ccCard.style.display = "none";
    }

    // Flags
    const flagsCard = document.getElementById("flags-card");
    const flagsList = document.getElementById("flags-list");
    const flags = [...(data.flags || []), ...(adj.regulatory.message ? [adj.regulatory.message] : [])];
    if (flags.length) {
        flagsCard.style.display = "block";
        flagsList.innerHTML = flags.map(f => `<div class="flag-item">${f}</div>`).join("");
    } else flagsCard.style.display = "none";

    // Disclaimer
    const expEl = document.getElementById("explanation");
    if (expEl) expEl.textContent = data.explanation || "";
    document.getElementById("disclaimer").textContent = data.disclaimer || "";

    document.getElementById("results").style.display = "block";
    document.getElementById("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ─── Helpers ───────────────────────────────────────────────────────

function fmt(v) { return v == null ? "—" : "₹" + v.toFixed(2) + "L"; }
function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : ""; }

function animateCount(el, target) {
    const dur = 850;
    const t0 = performance.now();
    (function tick(now) {
        const p = Math.min((now - t0) / dur, 1);
        const e = 1 - Math.pow(1 - p, 3);
        el.textContent = (target * e).toFixed(2);
        if (p < 1) requestAnimationFrame(tick);
        else el.textContent = target.toFixed(2);
    })(t0);
}

function copySummary() {
    if (!summaryText) return;
    navigator.clipboard.writeText(summaryText).then(() => {
        const b = document.getElementById("copy-btn");
        const o = b.innerHTML;
        b.textContent = "Copied";
        setTimeout(() => { b.innerHTML = o; }, 1500);
    });
}

function shareSummary() {
    if (!summaryText) return;
    if (navigator.share) navigator.share({ title: "Car valuation", text: summaryText }).catch(() => {});
    else copySummary();
}

// ─── Input behavior ────────────────────────────────────────────────

document.addEventListener("keydown", e => {
    if (e.key === "Enter" && !document.getElementById("valuate-btn").disabled) submitValuation();
});

document.getElementById("rc-number").addEventListener("input", function () {
    this.value = this.value.toUpperCase().replace(/[^A-Z0-9]/g, "");
});
