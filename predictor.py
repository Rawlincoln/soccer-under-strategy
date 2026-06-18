"""CLI entry point. For the live dashboard run: py app.py"""

from datetime import datetime, timezone

from engine import (
    LEAGUE_BASELINES,
    TIME_DECAY_0_0,
    WC_2026_OBSERVED,
    LiveStats,
    build_dashboard_payload,
    score_live_under,
)


def main():
    data = build_dashboard_payload()
    print("=" * 70)
    print("LIVE FIRST-HALF UNDER GOALS — PREDICTION SCAN")
    print(f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    b = data["baselines"]
    print(f"\nWC Under 1.5 FH: {b['wc_under_15_pct']}%")
    print(f"0-0 at 20' → under 1.5 FH: {b['time_decay_20_under_15']}%")

    print(f"\n--- BET SIGNALS ({data['bet_signal_count']}) ---")
    for p in data["bet_signals"]:
        print(f"  {p['match']}: {p['market']} @ {p['confidence']:.0f}%")

    print(f"\n--- MATCHES ({data['match_count']}) ---")
    for m in data["matches"]:
        print(f"\n  {m['home_team']} vs {m['away_team']} [{m['status']}] {m['score']}")
        for p in m["predictions"]:
            print(f"    {p['market']}: {p['confidence']:.0f}% → {p['recommendation']}")

    # Retrospective
    print("\n--- RETROSPECTIVE: Uzbekistan vs Colombia @ 20' ---")
    stats = LiveStats(minute=20, home_goals=0, away_goals=0, total_shots=6, shots_on_target=2, corners=2, home_possession=42)
    for key, p in score_live_under(stats, "Uzbekistan", "Colombia", "FIFA World Cup").items():
        won = (key == "Under 1.5 FH" or key == "Under 2.5 FH")
        print(f"  {p.market}: {p.confidence:.0f}% → {p.recommendation} → {'WON' if won else 'LOST'}")


if __name__ == "__main__":
    main()