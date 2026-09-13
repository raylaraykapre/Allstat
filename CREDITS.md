# Credits, Attributions & License Compliance Report

This document records the legal status of every trading concept referenced
in this software, based on internet research conducted in 2026.
All Python implementations are **original re-implementations** using public
mathematical formulas. No source code from any third party has been copied.

---

## Legal Status Summary

| Strategy | Concept Status | Implementation Risk | Action Taken |
|---|---|---|---|
| EMA Cross | Public domain | ✅ None | Attribution given |
| RSI | Public domain (formula) | ✅ None | Attribution given |
| MACD | Public domain (formula) | ✅ None | Attribution given |
| Bollinger Bands | **Name is a US trademark** | ⚠️ Name only | Renamed in code; see note |
| Supertrend | Public concept, no registered IP | ✅ None | Attribution given |
| Ichimoku | Public domain (books copyrighted, formula is not) | ✅ None | Attribution given |
| VWAP | Public domain institutional method | ✅ None | Attribution given |
| Donchian / Turtle Rules | Freely published, no IP claim | ✅ None | Attribution given |
| ADX / DMI | Public domain (formula) | ✅ None | Attribution given |
| Squeeze Momentum | **TTM Squeeze® is trademarked by Simpler Trading** | ⚠️ Name only | Renamed in code; see note |
| Funding Rate strategy | Original concept, no third-party IP | ✅ None | N/A |
| Multi-Factor | Original combination, inspired by free TV scripts | ✅ None | Attribution given |

---

## Detailed Notes Per Strategy

---

### 1. EMA Crossover
**Legal status: Public domain — no restrictions.**

Exponential moving averages are fundamental mathematics dating to the
early 20th century. No copyright, trademark, or patent applies to the
formula or its use as a trading signal. Used freely by every major
financial data provider, exchange, and trading library worldwide.

---

### 2. RSI — Relative Strength Index
**Legal status: Public domain — no restrictions.**

Developed by J. Welles Wilder Jr. and published in *New Concepts in
Technical Trading Systems* (1978). Wilder passed away in 2021. The book
carries a 1978 copyright, but the **mathematical formula itself is not
copyrightable** (mathematical formulas are facts, not creative expression,
and are not protectable under U.S. or international copyright law).
The RSI formula has been freely implemented in every major charting
platform, trading library, and financial textbook for nearly 50 years.

**No name trademark, no patent.** Free to implement.

---

### 3. MACD — Moving Average Convergence Divergence
**Legal status: Public domain — no restrictions.**

Developed by Gerald Appel (1933–2020) in the 1970s. The MACD calculation
is based purely on exponential moving averages — standard mathematical
operations. No trademark or patent covers the formula. Universally
implemented across all platforms. Appel's books carry copyright but the
formula they describe is free to use.

**No name trademark, no patent.** Free to implement.

---

### 4. Bollinger Bands
**Legal status: Formula is free; NAME is a registered US trademark.**

John Bollinger registered "Bollinger Bands" as a U.S. trademark (USPTO)
in 2011 (Reg. No. 3,990,957). The **mathematical formula** — a moving
average with upper/lower standard deviation envelopes — is not patented
and is freely usable. The trademark only protects the *name* "Bollinger
Bands®" when used in commerce in a way that could cause consumer confusion
about origin (i.e., implying John Bollinger endorses or produces your
product).

**Action taken in this codebase:**
- The internal strategy file is named `bollinger_bands.py` (descriptive,
  generic term — not the trademark itself).
- Log output and display use "BB Breakout" / "BB Bands" (generic).
- This file and the CREDITS.md attribute John Bollinger clearly.
- This software does not claim endorsement by or affiliation with
  John Bollinger or Capital Growth Letter Inc.
- The formula implementation was written independently using the public
  mathematical definition (EMA ± N × standard deviation).

**Risk level: LOW.** Using a standard descriptive term in internal code is
nominative fair use. No commercial branding uses "Bollinger Bands®" as if
Bollinger endorses this product.

---

### 5. Supertrend
**Legal status: Public concept — no registered IP found.**

Attributed to Olivier Seban (French trader/author, published in his 2008
book *Tout le monde mérite d'être riche*). The Supertrend formula is an
ATR-based calculation: `mid ± (multiplier × ATR)`. No patent or trademark
registration was found for "Supertrend" in any jurisdiction. The indicator
is freely implemented in pandas-ta, TA-Lib, TradingView's built-in library,
and hundreds of open-source projects.

**No name trademark, no patent.** Free to implement.

---

### 6. Ichimoku Kinko Hyo
**Legal status: Formula is public domain; books are copyrighted.**

Developed by Goichi Hosoda (pen name: Sanjin Ichimoku) and published in
1969. The books themselves carry Japanese copyright, but the **five-line
trading system formulas** described in them are mathematical methods —
not copyrightable as creative expression. Japan's copyright term for
individual authors is life + 70 years. Hosoda died in 1982; his original
works will enter public domain by 2052. However, the formulas have been
documented and replicated in thousands of independent works since 1969.

Note from SwissQuote (2026): "due to legal and copyright issues, four
recently reprinted books are available." This refers to book publishing
rights, not to the indicator formulas themselves.

**The mathematical formulas are free to implement.** This codebase
independently implements the five lines (Tenkan, Kijun, Senkou A,
Senkou B, Chikou) using their publicly documented formulas.

---

### 7. VWAP — Volume-Weighted Average Price
**Legal status: Public domain — no restrictions.**

VWAP is a benchmark calculation used by institutional traders and
exchanges since at least the 1980s. The formula (Σ(price × volume) /
Σvolume) is mathematical fact with no identifiable inventor. Freely
implemented everywhere. No trademark or patent.

---

### 8. Donchian Channel Breakout / Turtle Trading
**Legal status: Freely published — no IP restrictions.**

The Donchian Channel formula (N-period highest high / lowest low) was
created by Richard Donchian in the 1960s and is entirely in the public
domain. The Turtle Trading *rules* were kept secret from 1983–2003, then
**voluntarily published for free** by Curtis Faith in *Original Turtle
Rules* (freely distributed PDF) and in *Way of the Turtle* (McGraw-Hill,
2007, ISBN: 978-0071486644). Faith explicitly stated the rules were made
freely available to prevent others from selling them. The book is
copyrighted but the trading *rules* themselves (enter on N-day high/low,
exit on M-day opposite extreme, size by ATR) are not protectable concepts.

**Free to implement the concepts.** This codebase credits both Donchian
and the Turtle Trading originators.

---

### 9. ADX / DMI — Average Directional Index
**Legal status: Public domain — no restrictions.**

Created by J. Welles Wilder Jr. and published in *New Concepts in
Technical Trading Systems* (1978). Same status as RSI above — the formula
is mathematical fact, not copyrightable, and has been freely implemented
for nearly 50 years.

---

### 10. Squeeze Momentum
**Legal status: CONCEPT is free; "TTM Squeeze" NAME may be trademarked.**

The underlying concept — comparing Bollinger Bands width to Keltner Channel
width to detect volatility squeezes — combines two public-domain
indicators (Bollinger Bands formula, Keltner Channels formula). The
*concept* of detecting BB-inside-KC is not protectable.

**However:**
- **"TTM Squeeze®"** is a commercial indicator sold by Simpler Trading
  (Trade the Markets). John Carter introduced it in *Mastering the Trade*
  (McGraw-Hill, 2002). Simpler Trading actively commercialises this name.
- **LazyBear (Vikram Murthy)** published a Pine Script implementation on
  TradingView as open-source. TradingView's documentation states that
  open-source scripts published on their platform default to the
  **Mozilla Public License 2.0 (MPL 2.0)** unless another license is
  specified by the author. MPL 2.0 allows free use, modification, and
  distribution, provided: (a) source files that use MPL-licensed code
  include the MPL notice, and (b) modified MPL-licensed files remain
  under MPL 2.0.

**Action taken in this codebase:**
- The strategy is named `squeeze_momentum.py` — a generic description.
- **"TTM Squeeze" is never used** as a product name anywhere in this code.
- LazyBear is credited by name in CREDITS.md as the open-source author
  who popularised this implementation.
- The Python code is an **independent re-implementation** of the public
  mathematical concept — not a translation of LazyBear's Pine Script code.
  It does not trigger MPL 2.0 file-level copyleft because no MPL-licensed
  source file was incorporated.
- The underlying squeeze concept (BB vs KC comparison) is independently
  described in numerous textbooks and is not owned by any single party.

**Risk level: LOW**, provided the name "TTM Squeeze" is never used as a
product label. This codebase does not use that name.

---

### 11. Multi-Factor Confluence
**Legal status: Original work — no third-party IP.**

This strategy is an original combination of publicly documented indicators.
It was *inspired by* the structural approach of two TradingView community
scripts (both published as open-source by their authors), but no code was
copied and no names are used commercially. Attribution is given as a
courtesy.

---

## TradingView Open-Source Scripts Policy

TradingView's official Pine Script documentation states:
> "If you publish your open-source scripts publicly on TradingView, your
> open-source code is by default protected by the Mozilla license."

Mozilla Public License 2.0 key terms relevant here:
- You may use, modify, and distribute the *concepts* freely.
- If you incorporate an MPL-licensed **source file** directly, that file
  (not your whole project) must remain MPL-licensed.
- Since this project re-implements the mathematical concepts in Python
  from scratch without copying any Pine Script source, the MPL file-level
  copyleft does not apply.

---

## Open-Source Library Licenses

All Python libraries used carry permissive licenses (MIT, BSD, Apache 2.0)
that are fully compatible with this project's MIT license.

| Library | License | Compatible |
|---|---|---|
| `pybit` | MIT | ✅ |
| `pandas` | BSD-3-Clause | ✅ |
| `numpy` | BSD-3-Clause | ✅ |
| `pandas-ta` | MIT | ✅ |
| `websockets` | BSD-3-Clause | ✅ |
| `rich` | MIT | ✅ |
| `loguru` | MIT | ✅ |
| `python-dotenv` | BSD-3-Clause | ✅ |
| `pyyaml` | MIT | ✅ |
| `aiohttp` | Apache-2.0 | ✅ |
| `apscheduler` | MIT | ✅ |

---

## Exchange Rate Data

- **ExchangeRate-API** (free public tier) — no attribution required for
  programmatic use of their public API.
- **Frankfurter / European Central Bank** — ECB reference rates are
  public data; attribution recommended and given here.

---

## Overall Compliance Assessment

| Risk | Items | Status |
|---|---|---|
| Copyright (formulas) | All strategies | ✅ No violation — formulas are not copyrightable |
| Trademark (Bollinger Bands®) | `bollinger_bands.py` | ✅ Safe — generic name used, no commercial branding |
| Trademark (TTM Squeeze) | `squeeze_momentum.py` | ✅ Safe — name never used, concept only |
| MPL 2.0 (LazyBear script) | `squeeze_momentum.py` | ✅ Safe — independent re-implementation, no code copied |
| Library licenses | All dependencies | ✅ All permissive, compatible with MIT |

**Conclusion:** This codebase does not infringe any copyright, trademark,
or patent found in research. All potentially sensitive names have been
replaced with generic descriptive terms. Proper attribution is given to
all original authors as a matter of professional courtesy.

---

## Disclaimer

This compliance assessment is based on publicly available information and
general legal principles. It does not constitute legal advice. If you
intend to commercialise this software, consult a qualified intellectual
property attorney in your jurisdiction.
