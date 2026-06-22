"""Audit FotMob (and ProphitBet) match coverage vs 1xBet live football."""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from filters import is_excluded_match
from fotmob_stats import FOTMOB_PROVIDER
from onexbet_client import OneXBetClient, detect_half_time, parse_match_clock
from prophitbet_stats import PROPHIT_PROVIDER


def half_for(raw: dict) -> str:
    sc = raw.get("SC") or {}
    period = int(sc.get("CP") or 0)
    period_name = sc.get("CPS") or ""
    if detect_half_time(period, period_name):
        return "ht"
    if period == 2 or "2nd" in period_name.lower():
        return "sh"
    return "fh"


def main() -> None:
    print("Loading FotMob index...")
    FOTMOB_PROVIDER.ensure_loaded(background=False)
    fm_status = FOTMOB_PROVIDER.status()
    print(f"  FotMob index: {fm_status.get('index_matches', 0)} matches, error={fm_status.get('error')}")

    print("Loading ProphitBet (cache if fresh)...")
    PROPHIT_PROVIDER.ensure_loaded(background=False)
    pb_status = PROPHIT_PROVIDER.status()
    print(f"  ProphitBet: {pb_status.get('teams_count', 0)} teams, {pb_status.get('leagues_loaded', 0)} leagues")

    print("Fetching 1xBet live football...")
    client = OneXBetClient()
    raw_matches = client.fetch_live_football(count=500)
    print(f"  1xBet raw live: {len(raw_matches)}")

    rows: list[dict] = []
    by_league_fm: dict[str, list[bool]] = defaultdict(list)
    by_league_pb: dict[str, list[bool]] = defaultdict(list)

    for raw in raw_matches:
        home = raw.get("O1", "")
        away = raw.get("O2", "")
        league = raw.get("L", "")
        country = raw.get("CN", "")
        if is_excluded_match(home, away, league, country):
            continue

        half = half_for(raw)
        if half == "ht":
            lookup_half = "fh"
        else:
            lookup_half = half

        fm_index = FOTMOB_PROVIDER._resolve_match(home, away, league=league, country=country)
        fm = FOTMOB_PROVIDER.lookup_match(
            home, away, half=lookup_half, league=league, country=country,
        )
        pb = PROPHIT_PROVIDER.lookup_match(home, away)

        fm_index_hit = fm_index is not None
        fm_hit = fm is not None

        pb_hit = bool(pb and pb.get("home") and pb.get("away") and not pb.get("partial"))

        sc = raw.get("SC") or {}
        period = int(sc.get("CP") or 0)
        timer_sec = int(sc.get("TS") or 0)
        minute, _ = parse_match_clock(period, half == "ht", timer_sec, sc.get("CPS") or "")

        row = {
            "league": league,
            "match": f"{home} vs {away}",
            "half": half,
            "minute": minute,
            "fotmob_index": fm_index_hit,
            "fotmob": fm_hit,
            "fotmob_league": (fm or {}).get("league", (fm_index or {}).get("league", "")),
            "fotmob_xg": (fm or {}).get("total_xg"),
            "prophitbet": pb_hit,
            "pb_u15": (pb or {}).get("combined_under_15_fh_pct"),
        }
        rows.append(row)
        by_league_fm[league].append(fm_hit)
        by_league_pb[league].append(pb_hit)

    total = len(rows)
    fm_index_ok = sum(1 for r in rows if r["fotmob_index"])
    fm_ok = sum(1 for r in rows if r["fotmob"])
    pb_ok = sum(1 for r in rows if r["prophitbet"])
    both_ok = sum(1 for r in rows if r["fotmob"] and r["prophitbet"])
    neither = sum(1 for r in rows if not r["fotmob"] and not r["prophitbet"])
    index_only = sum(1 for r in rows if r["fotmob_index"] and not r["fotmob"])

    print()
    print("=" * 60)
    print("COVERAGE AUDIT (non-excluded 1xBet live matches)")
    print("=" * 60)
    print(f"Matches scanned:     {total}")
    print(f"FotMob index match:  {fm_index_ok} ({pct(fm_index_ok, total)})")
    print(f"FotMob stats parsed: {fm_ok} ({pct(fm_ok, total)})")
    print(f"  (index but no stats: {index_only})")
    print(f"ProphitBet matched:  {pb_ok} ({pct(pb_ok, total)})")
    print(f"Both matched:        {both_ok} ({pct(both_ok, total)})")
    print(f"Neither matched:     {neither} ({pct(neither, total)})")
    print(f"FotMob only:         {fm_ok - both_ok}")
    print(f"ProphitBet only:     {pb_ok - both_ok}")

    print()
    print("By league (FotMob hit rate):")
    league_stats = []
    for lg, hits in by_league_fm.items():
        n = len(hits)
        fm_h = sum(hits)
        pb_h = sum(by_league_pb[lg])
        league_stats.append((fm_h / n if n else 0, lg, n, fm_h, pb_h))
    league_stats.sort(key=lambda x: (x[0], -x[2]))

    print(f"  {'League':<45} {'N':>3} {'FM':>4} {'PB':>4} {'FM%':>6}")
    for rate, lg, n, fm_h, pb_h in league_stats[:40]:
        print(f"  {lg[:45]:<45} {n:>3} {fm_h:>4} {pb_h:>4} {rate*100:>5.0f}%")

    misses = [r for r in rows if not r["fotmob"]]
    if misses:
        print()
        print(f"FotMob misses ({len(misses)} matches):")
        for r in misses[:25]:
            pb_tag = "PB✓" if r["prophitbet"] else "PB✗"
            print(f"  [{pb_tag}] {r['league'][:40]} | {r['match']} ({r['half']} {r['minute']}')")
        if len(misses) > 25:
            print(f"  ... and {len(misses) - 25} more")

    hits = [r for r in rows if r["fotmob"]]
    if hits:
        print()
        print("Sample FotMob hits:")
        for r in hits[:8]:
            print(
                f"  {r['match']} | FM league: {r['fotmob_league'][:35]} | "
                f"xG={r['fotmob_xg']} | 1xBet: {r['league'][:30]}"
            )

    out = ROOT / "data" / "fotmob_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {
            "total": total,
            "fotmob_index_matched": fm_index_ok,
            "fotmob_stats_matched": fm_ok,
            "fotmob_index_only": index_only,
            "fotmob_matched": fm_ok,
            "prophitbet_matched": pb_ok,
            "both_matched": both_ok,
            "neither_matched": neither,
        },
        "by_league": {
            lg: {"n": len(hits), "fotmob": sum(hits), "prophitbet": sum(by_league_pb[lg])}
            for lg, hits in by_league_fm.items()
        },
        "misses": misses,
        "hits": hits,
    }, indent=2), encoding="utf-8")
    print()
    print(f"Full report: {out}")


def pct(n: int, total: int) -> str:
    if not total:
        return "0%"
    return f"{100 * n / total:.1f}%"


if __name__ == "__main__":
    main()