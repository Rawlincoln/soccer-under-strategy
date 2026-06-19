"""Quick integration test for SoccerPunter stats."""
from soccerpunter_stats import SOCCERPUNTER_PROVIDER
from combined_analysis import build_combined_analysis, combined_to_dict
from engine import LiveStats

SOCCERPUNTER_PROVIDER.ensure_loaded(background=False)

for home, away in [
    ("Ba", "Nadroga"),
    ("United States", "Australia"),
    ("Bohemians", "Dundalk"),
]:
    stats = SOCCERPUNTER_PROVIDER.lookup_match(home, away)
    print(f"\n{home} vs {away}:")
    if not stats:
        print("  NO MATCH")
        continue
    print(f"  H2H meetings={stats.get('h2h_meetings')} avg={stats.get('h2h_avg_total_goals')} u2.25={stats.get('combined_under_225_pct')}%")
    live = LiveStats(minute=18, home_goals=0, away_goals=0, total_shots=4, shots_on_target=1, corners=2)
    fused = combined_to_dict(build_combined_analysis(live, None, 0, 18, soccer_punter_stats=stats))
    print(f"  Fusion: {fused['verdict']} {fused['confidence']}% SP={fused['breakdown']['soccer_punter']} profile={fused['sp_profile']}")

print("\nProvider:", SOCCERPUNTER_PROVIDER.status())