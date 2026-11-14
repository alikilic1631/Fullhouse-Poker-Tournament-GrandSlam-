# How to submit the bot

This folder always holds the **current best, tournament-ready bot**.

- File to submit: **`submission/bot.py`**
- Current version: **v13** (FINAL — v12 + a failure-mode-driven fix: tightens marginal turn/river call-downs vs value-heavy *non-flagged* opponents, gated off vs flagged bluffers). Beats v12 on field-mix primary (robust +25,008 vs +24,024, fewer punts) and held-out (+2,025, w4/l0). Single self-contained bot.py — no data/, no zip. v10 (LR) and v11 (LP) were evaluated and deliberately not shipped.
- Status: passes the official validator, the fuzzer (0 crashes/timeouts/illegal), and a real 400-hand subprocess match.

---

## Step 1 — (optional but recommended) re-validate locally first

The portal rejects anything that fails `sandbox/validator.py`, so confirm green locally first. Copy-paste this whole block into a terminal:

```bash
source /Users/ismailhakkikilic/anaconda3/etc/profile.d/conda.sh && conda activate fullhouse
cd "/Users/ismailhakkikilic/Desktop/Fullhouse Poker AI/fullhouse-engine"
python sandbox/validator.py ../submission/bot.py
```

You want to see: `✅ PASSED`.

---

## Step 2 — submit at the portal

Go to **https://portal.fullhousehackathon.com** and submit `submission/bot.py`.

Two ways, pick whichever the portal offers:

**A. Upload the file (simplest)**
- Choose/upload this exact file:
  `/Users/ismailhakkikilic/Desktop/Fullhouse Poker AI/submission/bot.py`

**B. Paste the contents**
- Open `submission/bot.py`, select all, copy, and paste into the portal's code box.
- To copy the whole file to your clipboard from a terminal:
  ```bash
  pbcopy < "/Users/ismailhakkikilic/Desktop/Fullhouse Poker AI/submission/bot.py"
  ```

That's it — this bot needs no `data/` folder, so a single `bot.py` is all you upload.

---

## If you ever need a .zip instead

Some later versions will ship a `data/` folder (lookup tables). When that happens, submit a zip with `bot.py` at the root. To build it:

```bash
cd "/Users/ismailhakkikilic/Desktop/Fullhouse Poker AI/submission"
zip -r bot.zip bot.py data 2>/dev/null || zip bot.zip bot.py
```

Then upload `bot.zip`. (For v0 there is no `data/`, so the zip is unnecessary — upload `bot.py` directly.)

---

## Key facts to remember

- **Deadline:** 31 May 2026, 23:59 UTC. Late = not entered.
- **Re-uploads:** allowed any number of times before the deadline; only your most recent successful submission counts. So submitting v0 now and replacing it with v1/v2/... later is the intended workflow.
- **Limits:** `bot.py` ≤ 5 MB, `data/` ≤ 200 MB, total ≤ 250 MB. (v0 is ~4 KB.)
- **Bot ID stays the same** across qualifier → patch window → finals.
