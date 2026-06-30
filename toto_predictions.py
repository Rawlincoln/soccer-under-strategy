"""1xBet Toto & jackpot (1X2) predictions using Pro Punter data stack."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from fotmob_stats import FOTMOB_PROVIDER
from prophitbet_stats import PROPHIT_PROVIDER
from soccerpunter_stats import SOCCERPUNTER_PROVIDER
from team_aliases import (
    apply_team_alias,
    is_national_team,
    parse_onexbet_context,
    team_match_quality,
)
from thesportsdb_stats import SPORTSDB_PROVIDER
from bet_assistant import STORE, effective_onexbet_android_package, effective_onexbet_site
from onexbet_client import (
    app_base_url,
    onexbet_toto_telegram_open_url,
    onexbet_toto_url,
)
from toto_client import (
    DEFAULT_TYPE_ID,
    TotoJackpot,
    TotoMatch,
    fetch_jackpots_list,
    get_jackpot,
    jackpot_to_dict,
    product_info,
)


@dataclass
class WDLScores:
    home_win: float = 33.0
    draw: float = 34.0
    away_win: float = 33.0

    def as_dict(self) -> dict[str, float]:
        return {
            "W": round(self.home_win, 1),
            "D": round(self.draw, 1),
            "L": round(self.away_win, 1),
        }

    def ranked(self) -> list[tuple[str, float]]:
        return sorted(self.as_dict().items(), key=lambda x: -x[1])


@dataclass
class TotoMatchAnalysis:
    num: int
    home_team: str
    away_team: str
    league: str = ""
    kickoff: str = ""
    pick_primary: str = "W"
    pick_value: str = "D"
    pick_upset: str = "L"
    confidence_primary: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    coverage: dict[str, bool] = field(default_factory=dict)
    prophitbet: Optional[dict[str, Any]] = None
    soccerpunter: Optional[dict[str, Any]] = None
    fotmob: Optional[dict[str, Any]] = None
    sportsdb: Optional[dict[str, Any]] = None
    market_wdl: dict[str, float] = field(default_factory=dict)


@dataclass
class TotoPredictionSet:
    id: str
    label: str
    description: str
    picks: list[str]
    slip: str


def _clamp(val: float, lo: float = 5.0, hi: float = 85.0) -> float:
    return max(lo, min(hi, val))


def _normalize_wdl(scores: WDLScores) -> WDLScores:
    scores = WDLScores(
        home_win=_clamp(scores.home_win, lo=1.0, hi=500.0),
        draw=_clamp(scores.draw, lo=1.0, hi=500.0),
        away_win=_clamp(scores.away_win, lo=1.0, hi=500.0),
    )
    total = scores.home_win + scores.draw + scores.away_win
    if total <= 0:
        return WDLScores()
    return WDLScores(
        home_win=scores.home_win / total * 100,
        draw=scores.draw / total * 100,
        away_win=scores.away_win / total * 100,
    )


def _prophitbet_trusted(home: str, away: str, pb: Optional[dict[str, Any]]) -> bool:
    if not pb or pb.get("partial"):
        return False
    hf, af = pb.get("home"), pb.get("away")
    if not hf or not af:
        return False
    if is_national_team(home) or is_national_team(away):
        return False
    h_q = team_match_quality(home, str(hf.get("matched_name") or hf.get("team") or ""))
    a_q = team_match_quality(away, str(af.get("matched_name") or af.get("team") or ""))
    return h_q >= 0.80 and a_q >= 0.80


def _soccerpunter_quick(home: str, away: str) -> Optional[dict[str, Any]]:
    """Feed + cache only — avoids slow per-match H2H page fetches on jackpot batch."""
    SOCCERPUNTER_PROVIDER.ensure_loaded(background=True)
    if SOCCERPUNTER_PROVIDER._feed_loaded_at == 0:
        SOCCERPUNTER_PROVIDER._load_feed()
    pair = SOCCERPUNTER_PROVIDER._resolve_pair(home, away)
    if not pair:
        return None
    home_id, away_id = pair["home_id"], pair["away_id"]
    cached = SOCCERPUNTER_PROVIDER._get_cached_h2h(home_id, away_id)
    if cached and cached.get("h2h_meetings", 0) > 0:
        return SOCCERPUNTER_PROVIDER._build_stats_dict(home, away, pair, cached)
    parsed = SOCCERPUNTER_PROVIDER._feed_fallback(
        home, away, home_id, away_id, pair.get("league", ""),
    )
    return SOCCERPUNTER_PROVIDER._build_stats_dict(home, away, pair, parsed, partial=True)


def _pick_from_ranked(ranked: list[tuple[str, float]], index: int) -> str:
    if not ranked:
        return "D"
    return ranked[min(index, len(ranked) - 1)][0]


def _apply_market_wdl(scores: WDLScores, market: dict[str, float]) -> tuple[WDLScores, list[str]]:
    """Blend 1xBet pool percentages (BukPercentage) into model scores."""
    signals: list[str] = []
    if not market:
        return scores, signals
    w = float(market.get("W") or 0)
    d = float(market.get("D") or 0)
    l = float(market.get("L") or 0)
    if w + d + l <= 0:
        return scores, signals
    scores.home_win += w * 0.35
    scores.draw += d * 0.35
    scores.away_win += l * 0.35
    top = max(("W", w), ("D", d), ("L", l), key=lambda x: x[1])
    signals.append(f"1xBet pool: W {w:.0f}% · D {d:.0f}% · L {l:.0f}% (fav {top[0]})")
    return scores, signals


def _compute_wdl(
    home: str,
    away: str,
    league: str = "",
    country: str = "",
    market_wdl: Optional[dict[str, float]] = None,
) -> tuple[WDLScores, list[str], dict[str, bool], dict[str, Any]]:
    home_a = apply_team_alias(home)
    away_a = apply_team_alias(away)
    signals: list[str] = []
    coverage: dict[str, bool] = {}
    extras: dict[str, Any] = {}

    scores = WDLScores(home_win=33.0, draw=34.0, away_win=33.0)

    if is_national_team(home_a) and is_national_team(away_a):
        scores.draw += 6
        signals.append("International friendly — club form skipped; draw lean applied")

    PROPHIT_PROVIDER.ensure_loaded(background=True)
    pb = None if is_national_team(home_a) or is_national_team(away_a) else PROPHIT_PROVIDER.lookup_match(home_a, away_a)
    coverage["prophitbet"] = _prophitbet_trusted(home_a, away_a, pb)
    extras["prophitbet"] = pb if coverage["prophitbet"] else None

    if coverage["prophitbet"] and pb:
        hf, af = pb["home"], pb["away"]
        h_wp = float(hf.get("win_pct") or 0)
        a_wp = float(af.get("win_pct") or 0)
        h_gf = float(hf.get("goals_scored") or 0)
        h_ga = float(hf.get("goals_conceded") or 0)
        a_gf = float(af.get("goals_scored") or 0)
        a_ga = float(af.get("goals_conceded") or 0)

        scores.home_win += h_wp * 0.55 + h_gf * 9 - a_ga * 7 + float(hf.get("goal_diff") or 0) * 4
        scores.away_win += a_wp * 0.55 + a_gf * 9 - h_ga * 7 + float(af.get("goal_diff") or 0) * 4

        u25 = (float(hf.get("under_25_pct") or 0) + float(af.get("under_25_pct") or 0)) / 2
        if u25 >= 58:
            scores.draw += 10
            signals.append(f"ProphitBet: low-scoring form (U2.5 {u25:.0f}%)")
        if h_wp >= 55:
            signals.append(f"ProphitBet: {hf.get('matched_name', home)} strong at home ({h_wp:.0f}% W)")
        if a_wp >= 55:
            signals.append(f"ProphitBet: {af.get('matched_name', away)} strong away ({a_wp:.0f}% W)")

    sp = _soccerpunter_quick(home_a, away_a)
    coverage["soccerpunter"] = bool(sp and (sp.get("h2h_meetings") or sp.get("home_played")))
    extras["soccerpunter"] = sp

    if sp:
        meetings = int(sp.get("h2h_meetings") or 0)
        if meetings:
            hw = int(sp.get("h2h_home_wins") or 0)
            dr = int(sp.get("h2h_draws") or 0)
            aw = int(sp.get("h2h_away_wins") or 0)
            scores.home_win += hw / meetings * 22
            scores.draw += dr / meetings * 22
            scores.away_win += aw / meetings * 22
            signals.append(f"SoccerPunter H2H: {hw}W-{dr}D-{aw}L ({meetings} meetings)")
        avg = float(sp.get("combined_goals_avg") or sp.get("h2h_avg_total_goals") or 0)
        if avg:
            if avg <= 2.0:
                scores.draw += 8
                signals.append(f"SoccerPunter: tight fixtures ({avg:.2f} avg goals)")
            elif avg >= 2.8:
                scores.home_win += 4
                scores.away_win += 4
                scores.draw -= 6

    _, _, ccode = parse_onexbet_context(league, country)
    FOTMOB_PROVIDER.ensure_loaded(background=True)
    fm = FOTMOB_PROVIDER.lookup_match(home_a, away_a, half="fh", league=league, country=country or ccode or "")
    coverage["fotmob"] = bool(fm)
    extras["fotmob"] = fm
    if fm:
        hxg = float(fm.get("home_xg") or 0)
        axg = float(fm.get("away_xg") or 0)
        if hxg > axg + 0.25:
            scores.home_win += 6
            signals.append(f"FotMob xG favours home ({hxg:.2f} vs {axg:.2f})")
        elif axg > hxg + 0.25:
            scores.away_win += 6
            signals.append(f"FotMob xG favours away ({hxg:.2f} vs {axg:.2f})")

    SPORTSDB_PROVIDER.ensure_loaded(background=True)
    sd = SPORTSDB_PROVIDER.lookup_match(home_a, away_a)
    coverage["sportsdb"] = bool(sd)
    extras["sportsdb"] = sd

    scores, mkt_signals = _apply_market_wdl(scores, market_wdl or {})
    signals.extend(mkt_signals)

    scores = _normalize_wdl(scores)
    gap = abs(scores.home_win - scores.away_win)
    if gap < 8:
        scores.draw = _clamp(scores.draw + 8)
        scores = _normalize_wdl(scores)
        signals.append("Model: evenly matched — draw boosted")

    return scores, signals, coverage, extras


def analyze_toto_match(match: TotoMatch) -> TotoMatchAnalysis:
    scores, signals, coverage, extras = _compute_wdl(
        match.home_team,
        match.away_team,
        league=match.league,
        country=match.country,
        market_wdl=match.market_wdl,
    )
    ranked = scores.ranked()
    primary = _pick_from_ranked(ranked, 0)
    value = _pick_from_ranked(ranked, 1 if ranked[0][1] - ranked[1][1] < 14 else 0)
    upset = _pick_from_ranked(ranked, 2 if ranked[0][1] - ranked[2][1] < 20 else 1)

    return TotoMatchAnalysis(
        num=match.num,
        home_team=match.home_team,
        away_team=match.away_team,
        league=match.league,
        kickoff=match.kickoff,
        pick_primary=primary,
        pick_value=value,
        pick_upset=upset,
        confidence_primary=ranked[0][1] if ranked else 33.0,
        scores=scores.as_dict(),
        signals=signals[:8],
        coverage=coverage,
        prophitbet=extras.get("prophitbet"),
        soccerpunter=extras.get("soccerpunter"),
        fotmob=extras.get("fotmob"),
        sportsdb=extras.get("sportsdb"),
        market_wdl=dict(match.market_wdl or {}),
    )


def build_prediction_sets(analyses: list[TotoMatchAnalysis]) -> list[TotoPredictionSet]:
    primary = [a.pick_primary for a in analyses]
    value = [a.pick_value for a in analyses]
    upset = [a.pick_upset for a in analyses]

    def slip(picks: list[str]) -> str:
        return "-".join(picks)

    return [
        TotoPredictionSet(
            id="bankers",
            label="Set 1 · Bankers",
            description="Highest model confidence per match (ProphitBet form + SoccerPunter H2H + FotMob)",
            picks=primary,
            slip=slip(primary),
        ),
        TotoPredictionSet(
            id="value",
            label="Set 2 · Value",
            description="Second-best outcome when top pick is not clear — more draws and tight games",
            picks=value,
            slip=slip(value),
        ),
        TotoPredictionSet(
            id="upset",
            label="Set 3 · Upset hunter",
            description="Contrarian/longshot mix for jackpot variance — targets close odds and underdogs",
            picks=upset,
            slip=slip(upset),
        ),
    ]


def _ensure_analysis_providers() -> None:
    PROPHIT_PROVIDER.ensure_loaded(background=False)
    SOCCERPUNTER_PROVIDER.ensure_loaded(background=False)
    FOTMOB_PROVIDER.ensure_loaded(background=False)
    SPORTSDB_PROVIDER.ensure_loaded(background=False)


def build_toto_payload(
    *,
    type_id: int = DEFAULT_TYPE_ID,
    force_refresh: bool = False,
) -> dict[str, Any]:
    type_id = int(type_id)
    jackpot = get_jackpot(type_id=type_id, force_refresh=force_refresh)
    _ensure_analysis_providers()
    analyses = [analyze_toto_match(m) for m in jackpot.matches]
    sets = build_prediction_sets(analyses)

    sources_hit = {
        "prophitbet": sum(1 for a in analyses if a.coverage.get("prophitbet")),
        "soccerpunter": sum(1 for a in analyses if a.coverage.get("soccerpunter")),
        "fotmob": sum(1 for a in analyses if a.coverage.get("fotmob")),
        "sportsdb": sum(1 for a in analyses if a.coverage.get("sportsdb")),
    }

    config = STORE.load_config()
    onex_site = effective_onexbet_site(config)
    onex_pkg = effective_onexbet_android_package(config)
    pinfo = product_info(type_id)
    toto_href = pinfo["toto_url"]
    app_base = app_base_url()
    products = fetch_jackpots_list(site=onex_site)

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "type_id": type_id,
        "jackpot": jackpot_to_dict(jackpot),
        "match_count": len(analyses),
        "sources_hit": sources_hit,
        "matches": [asdict(a) for a in analyses],
        "sets": [asdict(s) for s in sets],
        "error": jackpot.error,
        "loading": False,
        "products": products,
        "onexbet": {
            "site": onex_site,
            "type_id": type_id,
            "toto_url": toto_href,
            "toto_open_url": onexbet_toto_telegram_open_url(app_base),
            "android_package": onex_pkg,
            "product": pinfo["label"],
            "slug": pinfo["slug"],
            "draw_number": jackpot.draw_number,
            "note": f"Live {pinfo['label']} draw #{jackpot.draw_number or '—'} from 1xBet toto-api-v2.",
        },
    }


class TotoCache:
    """On-demand Toto analysis cache (separate from live under-goals scan)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data_by_type: dict[int, dict[str, Any]] = {}
        self._refresh_in_progress: set[int] = set()
        self._default_type = DEFAULT_TYPE_ID

    def _loading_payload(self, type_id: int) -> dict[str, Any]:
        return {
            "loading": True,
            "type_id": type_id,
            "matches": [],
            "sets": [],
            "products": [],
        }

    def refresh(self, *, type_id: int = DEFAULT_TYPE_ID, force_jackpot: bool = False) -> None:
        type_id = int(type_id)
        with self._lock:
            if type_id in self._refresh_in_progress:
                return
            self._refresh_in_progress.add(type_id)
        try:
            payload = build_toto_payload(type_id=type_id, force_refresh=force_jackpot)
            with self._lock:
                self._data_by_type[type_id] = payload
        except Exception as exc:
            with self._lock:
                self._data_by_type[type_id] = {
                    "loading": False,
                    "type_id": type_id,
                    "error": str(exc),
                    "matches": [],
                    "sets": [],
                    "products": [],
                }
        finally:
            with self._lock:
                self._refresh_in_progress.discard(type_id)

    def request_refresh(
        self,
        *,
        type_id: int = DEFAULT_TYPE_ID,
        force_jackpot: bool = False,
    ) -> bool:
        type_id = int(type_id)
        with self._lock:
            if type_id in self._refresh_in_progress:
                return False
            self._data_by_type[type_id] = self._loading_payload(type_id)
        threading.Thread(
            target=self.refresh,
            kwargs={"type_id": type_id, "force_jackpot": force_jackpot},
            daemon=True,
        ).start()
        return True

    def get(self, type_id: int = DEFAULT_TYPE_ID) -> dict[str, Any]:
        type_id = int(type_id)
        with self._lock:
            data = self._data_by_type.get(type_id)
            if data:
                return dict(data)
            return self._loading_payload(type_id)