"""Streamlit viewer for YC India leads CSV.

Run: .venv/bin/streamlit run app.py

- Filters persist across restarts (.app_state.json)
- Edits persist to yc_india_leads_edited.csv (overrides the source CSV when present)
- You can add custom columns (e.g. contact details) and add/edit/delete rows
"""
import ast
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="YC India Leads", layout="wide")

SOURCE_CSV = Path("yc_india_leads.csv")
EDITED_CSV = Path("yc_india_leads_edited.csv")
STATE_FILE = Path(".app_state.json")

# Tracking columns auto-added on first load. (column_name, default_value)
TRACKING_COLS = [
    ("hiring_signal", 0),         # 0-3 — open eng roles
    ("icp_fit", 0),               # 0-3 — B2B SaaS hiring eng = high
    ("reachability", 0),          # 0-2 — eng leader findable on LinkedIn
    ("eng_leader_name", ""),
    ("eng_leader_linkedin", ""),
    ("hiring_signal_note", ""),   # specific JD reference
    ("interview_process", ""),
    ("touch_1_sent", ""),         # date string YYYY-MM-DD
    ("touch_2_sent", ""),
    ("touch_3_sent", ""),
    ("replied", False),
    ("demo_booked", False),
    ("outreach_status", "New"),   # New / Contacted / Replied / Demo / Pilot / Won / Lost / Skip
    ("notes", ""),
]
STATUS_OPTIONS = ["New", "Contacted", "Replied", "Demo", "Pilot", "Won", "Lost", "Skip"]


# ---------- persistence ----------

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state():
    keys = [
        "q", "batch_sel", "status_sel", "industry_sel", "subindustry_sel",
        "tag_sel", "location_sel", "team_range", "hidden_cols",
        "tier_sel", "outreach_sel",
    ]
    data = {k: st.session_state.get(k) for k in keys if k in st.session_state}
    try:
        STATE_FILE.write_text(json.dumps(data, default=list))
    except Exception as e:
        st.warning(f"could not save state: {e}")


# Initialize session_state from disk once.
if "_state_loaded" not in st.session_state:
    for k, v in load_state().items():
        st.session_state.setdefault(k, v)
    st.session_state["_state_loaded"] = True


# ---------- data load ----------

def _to_str(v):
    if pd.isna(v):
        return ""
    if isinstance(v, str) and v.startswith("["):
        try:
            return ", ".join(map(str, ast.literal_eval(v)))
        except Exception:
            return v
    return str(v)


@st.cache_data
def load(path: str, mtime: float) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in ("regions", "all_locations", "tags"):
        if col in df.columns:
            df[col] = df[col].apply(_to_str)
    if "team_size" in df.columns:
        df["team_size"] = pd.to_numeric(df["team_size"], errors="coerce")
    return df


# Sidebar uploader — accept a CSV upload, save it as the source file.
st.sidebar.header("Data")
uploaded = st.sidebar.file_uploader("Upload leads CSV", type=["csv"], key="uploader")
if uploaded is not None:
    SOURCE_CSV.write_bytes(uploaded.getvalue())
    if EDITED_CSV.exists():
        # Merge: keep tracking fields from edited CSV (by name), refresh other fields from upload.
        try:
            new_df = pd.read_csv(SOURCE_CSV)
            old_df = pd.read_csv(EDITED_CSV)
            track_cols = [c for c, _ in TRACKING_COLS if c in old_df.columns]
            if "name" in new_df.columns and "name" in old_df.columns and track_cols:
                merged = new_df.merge(old_df[["name", *track_cols]], on="name", how="left", suffixes=("", "_old"))
                for c in track_cols:
                    if f"{c}_old" in merged.columns:
                        merged[c] = merged[f"{c}_old"].combine_first(merged.get(c))
                        merged.drop(columns=[f"{c}_old"], inplace=True)
                merged.to_csv(EDITED_CSV, index=False)
            else:
                EDITED_CSV.unlink()
        except Exception:
            EDITED_CSV.unlink()
    load.clear()
    st.sidebar.success(f"Loaded {uploaded.name}")
    st.rerun()

# Prefer the edited CSV if it exists; otherwise source; otherwise show empty state.
if EDITED_CSV.exists():
    active_path = EDITED_CSV
elif SOURCE_CSV.exists():
    active_path = SOURCE_CSV
else:
    st.title("YC India Leads")
    st.info("Upload a leads CSV from the sidebar to begin.")
    st.stop()

df = load(str(active_path), os.path.getmtime(active_path))

# Ensure tracking columns exist; persist once so they survive across reloads.
_added = False
for col, default in TRACKING_COLS:
    if col not in df.columns:
        df[col] = default
        _added = True
if _added:
    df.to_csv(EDITED_CSV, index=False)
    load.clear()

# Force correct dtypes for tracking columns (empty CSV cells load as NaN/float).
_str_cols = ["eng_leader_name", "eng_leader_linkedin", "hiring_signal_note",
             "interview_process", "touch_1_sent", "touch_2_sent", "touch_3_sent",
             "outreach_status", "notes"]
for c in _str_cols:
    if c in df.columns:
        df[c] = df[c].fillna("").astype(str).replace({"nan": ""})
for c in ("replied", "demo_booked"):
    if c in df.columns:
        df[c] = df[c].fillna(False).astype(bool)

# Computed total_score (not stored — derived each run).
for c in ("hiring_signal", "icp_fit", "reachability"):
    df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
df["total_score"] = df["hiring_signal"] + df["icp_fit"] + df["reachability"]

def _tier(s):
    if s >= 6: return "Tier 1 (top)"
    if s >= 3: return "Tier 2"
    return "Tier 3 (skip)"
df["tier"] = df["total_score"].apply(_tier)

st.title("YC India Leads")
st.caption(f"{len(df)} companies loaded from `{active_path.name}`")

# ---------- playbook ----------
with st.expander("📋 Playbook — the plan (click to expand)", expanded=False):
    st.markdown("""
### What to do next, in order

**Step 1 — Score them, don't blast them.** Not all 61 are equal. Use the 3 scoring columns and rank:

- **Hiring signal** (0-3): open eng roles on their careers page right now. 3+ roles = hot.
- **ICP fit** (0-3): B2B SaaS hiring backend/full-stack = 3. Fintech with mostly ops/sales hiring = 1.
- **Reachability** (0-2): can you find the eng leader on LinkedIn in 2 min? Yes = 2.

Sort by total score. **Top 20 (Tier 1)** get the full 3-touch sequence. Next 20 (Tier 2) get a single shot. Bottom 21 (Tier 3) — skip for now.

**Step 2 — Enrich the top 20 this week.** For each, you need:
- Eng leader name + LinkedIn URL (fill `eng_leader_name`, `eng_leader_linkedin`)
- One specific hiring signal — e.g. *"saw your JD for Senior Backend on Nov 18"* (`hiring_signal_note`)
- Their current interview process if discoverable — sometimes mentioned in JDs (`interview_process`)

20 × ~5 min = under 2 hours of work. Do it manually. Don't automate — the specificity is your edge.

**Step 3 — Outreach in batches of 5/day, not 20/day.** Why: you need to reply fast when someone bites. Blasting 20 means you'll fumble the 2 who reply. 5/day × 4 days = top 20 covered in a week, with bandwidth to actually convert.

**Step 4 — Track right here.** Use `touch_1_sent` / `touch_2_sent` / `touch_3_sent` (date YYYY-MM-DD), flip `replied` / `demo_booked`, move `outreach_status` through New → Contacted → Replied → Demo → Pilot → Won/Lost. The dashboard strip above gives you the live funnel.

**Step 5 — Offer something irresistible for the first 5.** Pre-revenue means you need logos. Sweeten the deal hard for the first cohort:

> *"Free for 3 months + I personally set up your interview templates + 50% off year 1 if you convert. In exchange: a testimonial and intro to 2 other YC founders if you like it."*

The intro clause is the gold — it turns your first 5 customers into a referral engine.

---

### Realistic numbers from your 61

- 20 high-priority outreach → 5-7 conversations → 3-4 demos → **1-2 pilots → 1 paid customer**
- Cycle 2 (next month): refined messaging, warmer (you'll have a logo) → **2-3 more**
- By month 3, with referrals kicking in → **5-7 total**

You will likely **not** hit 10 from this list alone. To hit 10, plan now to expand to:
- Non-YC Indian Series A/B SaaS (Tracxn, LinkedIn Sales Nav, or Google "Series A India SaaS 2025")
- Indian dev-heavy unicorns' hiring partners
- Staffing firms (your earlier pivot — still valid as a parallel channel)

---

### This week

1. **Today/tomorrow:** score the 61, pick top 20, enrich them.
2. **Day 3:** send Touch 1 to first 5.
3. **Day 4-7:** Touch 1 to remaining 15, Touch 2 starts for first batch.
4. **Weekend:** review reply rate. If <15%, the messaging is off — iterate before continuing.
""")

# ---------- dashboard strip ----------
from datetime import date, timedelta

def _is_recent(s, days=7):
    try:
        d = pd.to_datetime(s, errors="coerce")
        return pd.notna(d) and (date.today() - d.date()) <= timedelta(days=days)
    except Exception:
        return False

scored = int((df["total_score"] > 0).sum())
tier1 = int((df["tier"] == "Tier 1 (top)").sum())
touches_week = int(sum(df[c].apply(_is_recent).sum() for c in ("touch_1_sent","touch_2_sent","touch_3_sent")))
replied = int(df["replied"].astype(bool).sum() if "replied" in df.columns else 0)
demos = int(df["demo_booked"].astype(bool).sum() if "demo_booked" in df.columns else 0)
contacted = int(df["touch_1_sent"].astype(str).str.len().gt(0).sum())
reply_rate = (replied / contacted * 100) if contacted else 0

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Scored", f"{scored}/{len(df)}")
m2.metric("Tier 1", tier1)
m3.metric("Contacted", contacted)
m4.metric("Touches (7d)", touches_week)
m5.metric("Replies", replied, f"{reply_rate:.0f}%")
m6.metric("Demos booked", demos)
st.divider()


# ---------- sidebar filters ----------

st.sidebar.header("Filters")

st.sidebar.text_input("Search (name, one-liner, description, founders)", key="q")


def multiselect_from(col: str, label: str, key: str, split: bool = False):
    if col not in df.columns:
        return []
    if split:
        vals = sorted({v.strip() for row in df[col].dropna() for v in str(row).split(",") if v.strip()})
    else:
        vals = sorted(df[col].dropna().astype(str).unique())
    # Drop any saved values that no longer exist in the data.
    if key in st.session_state:
        st.session_state[key] = [v for v in st.session_state[key] if v in vals]
    return st.sidebar.multiselect(label, vals, key=key)


batch_sel = multiselect_from("batch", "Batch", "batch_sel")
status_sel = multiselect_from("status", "Status", "status_sel")
industry_sel = multiselect_from("industry", "Industry", "industry_sel")
subindustry_sel = multiselect_from("subindustry", "Sub-industry", "subindustry_sel")
tag_sel = multiselect_from("tags", "Tags", "tag_sel", split=True)
location_sel = multiselect_from("all_locations", "Location", "location_sel", split=True)
tier_sel = multiselect_from("tier", "Tier", "tier_sel")
outreach_sel = multiselect_from("outreach_status", "Outreach status", "outreach_sel")

team_range = None
if "team_size" in df.columns and df["team_size"].notna().any():
    lo, hi = int(df["team_size"].min()), int(df["team_size"].max())
    if lo < hi:
        saved = st.session_state.get("team_range")
        default = tuple(saved) if saved and len(saved) == 2 else (lo, hi)
        default = (max(lo, default[0]), min(hi, default[1]))
        team_range = st.sidebar.slider("Team size", lo, hi, default, key="team_range")
    else:
        team_range = (lo, hi)

if st.sidebar.button("Reset filters"):
    for k in ["q", "batch_sel", "status_sel", "industry_sel", "subindustry_sel",
              "tag_sel", "location_sel", "team_range", "hidden_cols"]:
        st.session_state.pop(k, None)
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    st.rerun()


# ---------- apply filters ----------

f = df.copy()

q = st.session_state.get("q", "")
if q:
    ql = q.lower()
    cols = [c for c in ("name", "one_liner", "long_description", "founder_names") if c in f.columns]
    mask = pd.Series(False, index=f.index)
    for c in cols:
        mask = mask | f[c].fillna("").astype(str).str.lower().str.contains(ql)
    f = f[mask]

if batch_sel:
    f = f[f["batch"].isin(batch_sel)]
if status_sel:
    f = f[f["status"].isin(status_sel)]
if industry_sel:
    f = f[f["industry"].isin(industry_sel)]
if subindustry_sel:
    f = f[f["subindustry"].isin(subindustry_sel)]
if tag_sel:
    f = f[f["tags"].fillna("").apply(lambda v: any(t in v for t in tag_sel))]
if location_sel:
    f = f[f["all_locations"].fillna("").apply(lambda v: any(t in v for t in location_sel))]
if tier_sel:
    f = f[f["tier"].isin(tier_sel)]
if outreach_sel:
    f = f[f["outreach_status"].isin(outreach_sel)]
if team_range and "team_size" in f.columns:
    lo, hi = team_range
    f = f[f["team_size"].between(lo, hi) | f["team_size"].isna()]


# ---------- column controls ----------

st.markdown(f"**{len(f)}** matching companies")

default_visible = [c for c in [
    "name", "tier", "total_score", "hiring_signal", "icp_fit", "reachability",
    "outreach_status", "touch_1_sent", "touch_2_sent", "touch_3_sent",
    "replied", "demo_booked",
    "eng_leader_name", "eng_leader_linkedin", "hiring_signal_note",
    "batch", "status", "industry", "one_liner", "website", "yc_url", "notes",
] if c in f.columns]

all_cols = list(f.columns)
# Default-hidden = the heavy ones not in default_visible
if "hidden_cols" not in st.session_state:
    st.session_state["hidden_cols"] = [c for c in all_cols if c not in default_visible]
# Drop stale entries
st.session_state["hidden_cols"] = [c for c in st.session_state["hidden_cols"] if c in all_cols]

col1, col2 = st.columns([2, 1])
with col1:
    hidden = st.multiselect("Hide columns", options=all_cols, key="hidden_cols")
with col2:
    new_col = st.text_input("Add a new column (e.g. email, phone, notes)", key="new_col_name")
    if st.button("Add column", disabled=not new_col):
        name = new_col.strip()
        if name and name not in df.columns:
            df[name] = ""
            df.to_csv(EDITED_CSV, index=False)
            load.clear()
            st.session_state["new_col_name"] = ""
            st.rerun()

display_cols = [c for c in all_cols if c not in hidden]


# ---------- editable table ----------

st.caption("Edit cells, add rows (use the + at the bottom), or delete rows (select + delete key). Click **Save edits** to persist.")

f_edit = f[display_cols].copy()
f_edit["_original_index"] = f.index

edited = st.data_editor(
    f_edit,
    use_container_width=True,
    height=600,
    num_rows="dynamic",
    column_config={
        "_original_index": None,  # Hide mapping index
        "website": st.column_config.LinkColumn("Website"),
        "yc_url": st.column_config.LinkColumn("YC Profile"),
        "eng_leader_linkedin": st.column_config.LinkColumn("Eng leader LI"),
        "one_liner": st.column_config.TextColumn("One-liner", width="large"),
        "hiring_signal": st.column_config.NumberColumn("Hiring (0-3)", min_value=0, max_value=3, step=1),
        "icp_fit": st.column_config.NumberColumn("ICP fit (0-3)", min_value=0, max_value=3, step=1),
        "reachability": st.column_config.NumberColumn("Reach (0-2)", min_value=0, max_value=2, step=1),
        "total_score": st.column_config.NumberColumn("Score", disabled=True),
        "tier": st.column_config.TextColumn("Tier", disabled=True),
        "outreach_status": st.column_config.SelectboxColumn("Outreach", options=STATUS_OPTIONS),
        "replied": st.column_config.CheckboxColumn("Replied"),
        "demo_booked": st.column_config.CheckboxColumn("Demo"),
    },
    hide_index=True,
    key="editor",
)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("💾 Save edits", type="primary"):
        # Merge edits back into full df: edited rows update df, new rows appended.
        base = df.copy()
        
        remaining_indices = set()
        
        for i, row in edited.iterrows():
            orig_idx = row.get("_original_index")
            is_existing = False
            
            if pd.notna(orig_idx) and orig_idx != "":
                try:
                    orig_idx_val = int(float(orig_idx))
                    if orig_idx_val in base.index:
                        orig_idx = orig_idx_val
                        is_existing = True
                except (ValueError, TypeError):
                    pass
            
            if is_existing:
                remaining_indices.add(orig_idx)
                for c in display_cols:
                    if c in base.columns and c in row:
                        base.at[orig_idx, c] = row[c]
            else:
                # New row
                new_row = {c: row.get(c, "") for c in base.columns if c in row.index}
                new_row.pop("_original_index", None)
                base = pd.concat([base, pd.DataFrame([new_row])], ignore_index=True)
        
        # Delete rows that were in f (filtered slice) but are no longer in remaining_indices
        deleted_indices = set(f.index) - remaining_indices
        if deleted_indices:
            base = base.drop(index=deleted_indices)
        
        # Recompute total_score and tier
        for c in ("hiring_signal", "icp_fit", "reachability"):
            base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0).astype(int)
        base["total_score"] = base["hiring_signal"] + base["icp_fit"] + base["reachability"]
        base["tier"] = base["total_score"].apply(_tier)
        
        base.to_csv(EDITED_CSV, index=False)
        load.clear()
        st.success(f"Saved to {EDITED_CSV.name}")
        st.rerun()
with c2:
    st.download_button(
        "⬇ Download filtered CSV",
        edited.drop(columns=["_original_index"], errors="ignore").to_csv(index=False).encode("utf-8"),
        file_name="yc_india_filtered.csv",
        mime="text/csv",
    )
with c3:
    if EDITED_CSV.exists() and st.button("↺ Revert to original scrape"):
        EDITED_CSV.unlink()
        load.clear()
        st.rerun()


with st.expander("View full row detail (all columns)"):
    if len(f):
        idx = st.selectbox("Pick a company", f["name"].tolist())
        row = f[f["name"] == idx].iloc[0].to_dict()
        st.json(row)


# Persist filter state at the end of every run.
save_state()
