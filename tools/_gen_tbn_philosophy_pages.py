"""Generate drive/TBN_Philosophy.html and detailed system write-ups.

System pages come from tools/_gen_system_writeups.py (not the old stubs).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = ROOT / "drive" / "systems"
SYSTEMS.mkdir(parents=True, exist_ok=True)

STUB_CSS = """
  :root {
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --ok-bg: #e8f2ec; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6; --bad: #9b2226; --bad-bg: #fdecea;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }
  .wrap { max-width: 880px; margin: 0 auto; padding: 36px 24px 64px; }
  header { border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }
  .eyebrow {
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 6px;
  }
  h1 { font-size: 1.6rem; margin: 0 0 6px; letter-spacing: -0.02em; }
  h2 { font-size: 1.1rem; margin: 24px 0 10px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }
  .lede { margin: 0; color: var(--muted); max-width: 68ch; }
  .back { font-size: 0.9rem; margin: 0 0 10px; }
  .badge {
    display: inline-block; font-size: 0.75rem; font-weight: 700;
    letter-spacing: 0.04em; padding: 2px 8px; margin: 8px 0 0;
  }
  .badge-ok { background: var(--ok-bg); color: var(--ok); }
  .badge-warn { background: var(--warn-bg); color: var(--warn); }
  .badge-muted { background: var(--fill); color: var(--muted); }
  p, li { margin: 0 0 10px; }
  ul { padding-left: 1.2rem; margin: 0 0 12px; }
  a { color: var(--accent); }
  code, .path {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 0.86em; background: var(--fill); padding: 0.08em 0.3em;
  }
  .card {
    background: var(--card); border: 1px solid var(--line);
    padding: 12px 14px; margin: 0 0 14px;
  }
  footer { margin-top: 28px; font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--line); padding-top: 12px; }
"""


def stub(
    heading: str,
    eyebrow: str,
    badge_class: str,
    badge_text: str,
    lede: str,
    sections: list[tuple[str, str]],
    footer_note: str,
) -> str:
    body = "\n".join(f"<h2>{h}</h2>\n{html}" for h, html in sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{heading}</title>
<style>{STUB_CSS}
</style>
</head>
<body>
<div class="wrap">
  <p class="back"><a href="../tbn_philosophy.html">&larr; TBN Philosophy</a></p>
  <header>
    <p class="eyebrow">{eyebrow}</p>
    <h1>{heading}</h1>
    <p class="lede">{lede}</p>
    <div class="badge {badge_class}">{badge_text}</div>
  </header>
{body}
  <footer>{footer_note}</footer>
</div>
</body>
</html>
"""


PHILOSOPHY = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>TBN Philosophy — Twin Beacon Networks</title>
<style>
  :root {
    --bg: #f7f6f2; --ink: #1c1b19; --muted: #5a574f; --line: #d4d0c4;
    --card: #ffffff; --accent: #2a4a5c; --accent-soft: #e8eef2;
    --ok: #2d6a4f; --ok-bg: #e8f2ec; --warn: #8a5a12; --warn-bg: #f7efe0;
    --fill: #f0eee6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", "Helvetica Neue", Georgia, serif;
    font-size: 15px; line-height: 1.55; color: var(--ink);
    background:
      radial-gradient(ellipse 80% 50% at 10% -10%, #e4ebe8 0%, transparent 55%),
      radial-gradient(ellipse 60% 40% at 100% 0%, #ebe6dc 0%, transparent 50%),
      var(--bg);
  }
  .wrap { max-width: 920px; margin: 0 auto; padding: 40px 28px 72px; }
  header.doc-head { border-bottom: 2px solid var(--ink); padding-bottom: 18px; margin-bottom: 28px; }
  .eyebrow {
    font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--accent); font-weight: 650; margin: 0 0 8px;
  }
  h1 { font-size: 1.85rem; font-weight: 700; margin: 0 0 8px; letter-spacing: -0.025em; line-height: 1.2; }
  h2 { font-size: 1.15rem; margin: 28px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }
  .lede { margin: 0; color: var(--muted); max-width: 64ch; font-size: 0.98rem; }
  .meta-row { display: flex; flex-wrap: wrap; gap: 10px 18px; margin-top: 12px; font-size: 0.82rem; color: var(--muted); }
  p { margin: 0 0 12px; }
  ul { margin: 0 0 14px; padding-left: 1.25rem; }
  li { margin: 0.25em 0; }
  a { color: var(--accent); }
  code, .path {
    font-family: Consolas, "Cascadia Mono", monospace;
    font-size: 0.86em; background: var(--fill); padding: 0.08em 0.3em;
  }
  .callout { background: var(--accent-soft); border-left: 4px solid var(--accent); padding: 12px 14px; margin: 14px 0 18px; }
  .callout.warn { background: var(--warn-bg); border-left-color: var(--warn); }
  .callout.ok { background: var(--ok-bg); border-left-color: var(--ok); }
  .grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 12px; margin: 14px 0 8px;
  }
  a.card {
    display: block; text-decoration: none; color: inherit;
    background: var(--card); border: 1px solid var(--line); padding: 14px 14px 12px;
  }
  a.card:hover { border-color: var(--accent); box-shadow: 0 2px 10px #1c1b1912; }
  a.card .tag {
    display: inline-block; font-size: 0.7rem; font-weight: 700;
    letter-spacing: 0.06em; text-transform: uppercase; margin-bottom: 6px; color: var(--accent);
  }
  a.card .tag.gold { color: var(--ok); }
  a.card .tag.research { color: var(--warn); }
  a.card .tag.parked, a.card .tag.deprecated, a.card .tag.retired { color: var(--muted); }
  a.card strong { display: block; font-size: 1.02rem; margin-bottom: 4px; }
  a.card span.blurb { display: block; font-size: 0.88rem; color: var(--muted); line-height: 1.4; }
  footer.doc-foot { margin-top: 36px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 0.8rem; color: var(--muted); }
</style>
</head>
<body>
<div class="wrap">
<header class="doc-head">
  <p class="eyebrow">Twin Beacon Networks · one-pager</p>
  <h1>TBN Philosophy</h1>
  <p class="lede">
    <strong>TBN</strong> (Twin Beacon Networks) is the shared multi-sleeve trading engine and process
    (<span class="path">stock_analysis/rocket_tbn.py</span>) — not a single strategy.
    Each sleeve keeps its own entry/exit identity; the house standard is process discipline,
    evidence over optimization theater, and clear promotion bars.
  </p>
  <div class="meta-row">
    <span><strong>Engine</strong> TBN host</span>
    <span><strong>Process</strong> <a href="system_setup_process.html">System setup process</a></span>
    <span><strong>Live reports</strong> <a href="investment.html">Investment</a> · <a href="monthly.html">Monthly</a> · <a href="system_performance.html">Performance</a></span>
  </div>
</header>

<h2>What TBN is</h2>
<ul>
  <li><strong>Multi-sleeve portfolio</strong> — diversify by setup type (zones, relative strength, short bursts, year-high, etc.), not by stacking correlated copies of one idea.</li>
  <li><strong>Shared host, system prefixes</strong> — one engine; outputs stay <code>BRT_*</code>, <code>RL_*</code>, <code>RS_*</code>, … so books, reconcile, and reports stay auditable.</li>
  <li><strong>Process over max PnL</strong> — hypothesis tests are one-knob A/Bs with frozen controls; trade-diff HTML and Thinkorswim (ToS) review gate adoption, not leaderboard chasing.</li>
</ul>

<div class="callout">
  <strong>TBN vs BRT:</strong> TBN is the platform. <strong>BRT</strong> (Break and ReTest) is one system on that platform.
  Do not rename engine docs as “BRT engine.”
</div>

<h2>Research discipline</h2>
<ul>
  <li><strong>In-sample (IS) / out-of-sample (OOS)</strong> — default chronological split: IS = entry before 2024-01-01; OOS = entry on/after. OOS is report-only; never retune on OOS to “fix” a soft result.</li>
  <li><strong>Research candidate ≠ gold ≠ DailyRun</strong> — stamped A/Bs can be research-only; gold needs wider/walk-forward or multi-universe confirmation plus reconcile; DailyRun requires an explicit wire.</li>
  <li><strong>Quality over count</strong> — KEEP / LEAN KEEP only when quality improves without collapsing sample size; flat → HOLD; worse → DISMISS.</li>
  <li><strong>Selection bias honesty</strong> — picking after seeing the same-history table is in-sample selection; label it and re-score under the chosen freeze.</li>
</ul>

<div class="callout ok">
  Canonical process: <a href="system_setup_process.html">System setup process</a>
  · Hypothesis framing: <span class="path">docs/HYPOTHESIS_TEST.md</span> (repo).
</div>

<h2>System descriptions</h2>
<p>
  Full write-ups for each sleeve (identity, entry, exit, frozen levers, universe, caveats).
  Production gold / DailyRun first; then research and retired.
  Regenerated by <span class="path">tools/_gen_system_writeups.py</span>.
</p>

<div class="grid">
  <a class="card" href="systems/rs.html"><span class="tag gold">Production</span><strong>RS — Relative Strength</strong><span class="blurb">SPY excess + Strong Trend Condition (TC); multiplier stop/target; 252-bar time stop.</span></a>
  <a class="card" href="systems/sb.html"><span class="tag gold">Production</span><strong>SB — StockBee Momentum Burst</strong><span class="blurb">Short impulse after coil; Low of Day (LOD) risk; 3–5 day hold sleeve.</span></a>
  <a class="card" href="systems/rl.html"><span class="tag gold">Production</span><strong>RL — Rocket Launcher</strong><span class="blurb">50-SMA dip-and-stack mega-cap launcher; AWK math authoritative vs Python port.</span></a>
  <a class="card" href="systems/yh.html"><span class="tag gold">Production</span><strong>YH — Year High</strong><span class="blurb">Year-high zone / band path; Mag9-style universe (no TSLA in prod list).</span></a>
  <a class="card" href="systems/brt.html"><span class="tag gold">Production</span><strong>BRT — Break and ReTest</strong><span class="blurb">Daily pivot-zone break → support retest on the TBN host.</span></a>
  <a class="card" href="systems/wpbr.html"><span class="tag gold">Production</span><strong>WPBR — Pivot Break and Retest</strong><span class="blurb">Weekly pivot zones, weekly breakout + confirm, daily hold-above retest.</span></a>
  <a class="card" href="systems/mts.html"><span class="tag gold">Production</span><strong>MTS — Magic Touch</strong><span class="blurb">STONK_DATA MTS-tab BI first-touch (not the BRT retest pipeline).</span></a>
  <a class="card" href="systems/vz.html"><span class="tag research">Research</span><strong>VZ — Volume Zone</strong><span class="blurb">Max-volume HL zones; break → retest. Not DailyRun-wired.</span></a>
  <a class="card" href="systems/wrl.html"><span class="tag research">Research</span><strong>WRL — Weekly Range / Swing</strong><span class="blurb">Previous-week range + walk-back swing high/low; watch the lower zone, buy the upside break.</span></a>
  <a class="card" href="systems/mvcp.html"><span class="tag retired">Retired</span><strong>MVCP — Minervini VCP</strong><span class="blurb">Volatility Contraction Pattern (VCP) sleeve retired from DailyRun and active reporting (2026-08-21).</span></a>
  <a class="card" href="systems/ind.html"><span class="tag deprecated">Deprecated</span><strong>IND — Indicator / TC</strong><span class="blurb">Legacy indicator / Trend Condition path; still in some reports, not an active gold sleeve.</span></a>
</div>

<div class="callout warn">
  Research pages (e.g. VZ) and retired notes (MVCP) are for process transparency — not live allocation advice.
</div>

<footer class="doc-foot">
  <p>stockresearch · TBN Philosophy · Canonical: <span class="path">drive/TBN_Philosophy.html</span> (published to Pages as <span class="path">tbn_philosophy.html</span>)</p>
</footer>
</div>
</body>
</html>
"""

GUIDE_BANNER = (
    '<p style="font-size:0.9rem;margin:0 0 12px;">'
    '<a href="../tbn_philosophy.html">&larr; TBN Philosophy</a></p>\n'
)


def publish_guide_copy(src_name: str, dst_name: str) -> None:
    src = ROOT / "drive" / "paul_experiments" / src_name
    text = src.read_text(encoding="utf-8")
    if "tbn_philosophy.html" not in text:
        if "<body>" in text:
            text = text.replace("<body>", "<body>\n" + GUIDE_BANNER, 1)
        elif "<body " in text:
            # rare
            import re

            text = re.sub(r"<body([^>]*)>", r"<body\1>\n" + GUIDE_BANNER, text, count=1, flags=re.I)
    (SYSTEMS / dst_name).write_text(text, encoding="utf-8")


def main() -> None:
    (ROOT / "drive" / "TBN_Philosophy.html").write_text(PHILOSOPHY, encoding="utf-8")
    # Pages copy (docs/tbn_philosophy.html) is produced by publish_github_pages.py
    # (nav / cache-bust). Drive file is the SSoT.

    import importlib.util

    wu_path = ROOT / "tools" / "_gen_system_writeups.py"
    spec = importlib.util.spec_from_file_location("gen_system_writeups", wu_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {wu_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    written = mod.write_all()
    print(f"Wrote {ROOT / 'drive' / 'TBN_Philosophy.html'}")
    for p in written:
        try:
            rel = p.relative_to(ROOT)
        except ValueError:
            rel = p
        print(f"  {rel} ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
