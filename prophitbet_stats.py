"""
ProphitBet-style historical stats from football-data.co.uk.
Adapted from kochlisGit/ProphitBet-Soccer-Bets-Predictor StatisticsEngine.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from functools import reduce
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from team_aliases import apply_team_alias

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data" / "prophitbet"
LEAGUES_CFG = ROOT / "data" / "leagues.json"
CACHE_TTL_HOURS = 24

STAT_COLUMNS = [
    "HW", "AW", "HGF", "AGF", "HGA", "AGA", "HGD", "AGD",
    "HW%", "AW%", "HSTF", "ASTF", "HCF", "ACF",
]


class StatisticsEngine:
    """Rolling form stats (shift-1, last N matches) — ProphitBet core."""

    def __init__(self, match_history_window: int = 3, goal_diff_margin: int = 2):
        self._n = match_history_window
        self._gd_margin = goal_diff_margin
        self._basic_stats_fn = {
            "HW": self._compute_home_wins,
            "AW": self._compute_away_wins,
            "HGF": self._compute_home_goals_forward,
            "AGF": self._compute_away_goals_forward,
            "HGA": self._compute_home_goals_against,
            "AGA": self._compute_away_goals_against,
            "HGD": self._compute_home_goal_diff,
            "AGD": self._compute_away_goal_diff,
            "HW%": self._compute_total_home_win_rate,
            "AW%": self._compute_total_away_win_rate,
        }
        self._extended_stats_fn = {
            "HSTF": self._compute_home_shots_on_target_forward,
            "ASTF": self._compute_away_shots_on_target_forward,
            "HCF": self._compute_home_corners_forward,
            "ACF": self._compute_away_corners_forward,
        }
        self._all_stats_fn = {**self._basic_stats_fn, **self._extended_stats_fn}

    def compute_stats(self, df: pd.DataFrame, stat_columns: list[str]) -> pd.DataFrame:
        if not df["Date"].is_monotonic_increasing:
            raise ValueError("Expected dates sorted ascending.")

        stat_funcs = [self._all_stats_fn[col] for col in stat_columns]

        def season_pipeline(season_df: pd.DataFrame) -> pd.DataFrame:
            return reduce(lambda s_df, fn: fn(s_df), stat_funcs, season_df)

        df = df.groupby(by="Season", group_keys=False).apply(season_pipeline)
        return df.sort_values(by=["Date", "Home"], ascending=False)

    def _aggregate_previous_stats(self, match_stats: pd.Series) -> pd.Series:
        return match_stats.shift(periods=1).rolling(window=self._n, min_periods=1).sum()

    def _compute_home_wins(self, df: pd.DataFrame) -> pd.DataFrame:
        temp = df[["Home", "Result"]].copy()
        temp["HomeWin"] = temp["Result"].eq("H").astype(int)
        df["HW"] = temp.groupby(by="Home")["HomeWin"].transform(self._aggregate_previous_stats)
        return df

    def _compute_away_wins(self, df: pd.DataFrame) -> pd.DataFrame:
        temp = df[["Away", "Result"]].copy()
        temp["AwayWin"] = temp["Result"].eq("A").astype(int)
        df["AW"] = temp.groupby(by="Away")["AwayWin"].transform(self._aggregate_previous_stats)
        return df

    def _compute_home_goals_forward(self, df: pd.DataFrame) -> pd.DataFrame:
        df["HGF"] = df.groupby(by="Home")["HG"].transform(self._aggregate_previous_stats)
        return df

    def _compute_away_goals_forward(self, df: pd.DataFrame) -> pd.DataFrame:
        df["AGF"] = df.groupby(by="Away")["AG"].transform(self._aggregate_previous_stats)
        return df

    def _compute_home_goals_against(self, df: pd.DataFrame) -> pd.DataFrame:
        df["HGA"] = df.groupby(by="Home")["AG"].transform(self._aggregate_previous_stats)
        return df

    def _compute_away_goals_against(self, df: pd.DataFrame) -> pd.DataFrame:
        df["AGA"] = df.groupby(by="Away")["HG"].transform(self._aggregate_previous_stats)
        return df

    def _compute_home_goal_diff(self, df: pd.DataFrame) -> pd.DataFrame:
        if "HGF" in df and "HGA" in df:
            df["HGD"] = df["HGF"] - df["HGA"]
            return df
        temp = df[["Home", "HG", "AG"]].copy()
        temp["HG-AG"] = temp["HG"] - temp["AG"]
        df["HGD"] = temp.groupby(by="Home")["HG-AG"].transform(self._aggregate_previous_stats)
        return df

    def _compute_away_goal_diff(self, df: pd.DataFrame) -> pd.DataFrame:
        if "AGF" in df and "AGA" in df:
            df["AGD"] = df["AGF"] - df["AGA"]
            return df
        temp = df[["Away", "HG", "AG"]].copy()
        temp["AG-HG"] = temp["AG"] - temp["HG"]
        df["AGD"] = temp.groupby(by="Away")["AG-HG"].transform(self._aggregate_previous_stats)
        return df

    def _compute_total_home_win_rate(self, df: pd.DataFrame) -> pd.DataFrame:
        temp = df[["Home", "Result"]].copy()
        temp["HomeWins"] = temp["Result"].eq("H").astype(float)
        temp["CumWins"] = temp.groupby(by="Home")["HomeWins"].cumsum() - temp["HomeWins"]
        temp["CumCounts"] = temp.groupby(by="Home").cumcount()
        denom = temp["CumCounts"].where(temp["CumCounts"] > 0)
        df["HW%"] = (temp["CumWins"] / denom * 100).round(1)
        return df

    def _compute_total_away_win_rate(self, df: pd.DataFrame) -> pd.DataFrame:
        temp = df[["Away", "Result"]].copy()
        temp["AwayWins"] = temp["Result"].eq("A").astype(float)
        temp["CumWins"] = temp.groupby(by="Away")["AwayWins"].cumsum() - temp["AwayWins"]
        temp["CumCounts"] = temp.groupby(by="Away").cumcount()
        denom = temp["CumCounts"].where(temp["CumCounts"] > 0)
        df["AW%"] = (temp["CumWins"] / denom * 100).round(1)
        return df

    def _compute_home_shots_on_target_forward(self, df: pd.DataFrame) -> pd.DataFrame:
        df["HSTF"] = df.groupby(by="Home")["HST"].transform(self._aggregate_previous_stats)
        return df

    def _compute_away_shots_on_target_forward(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ASTF"] = df.groupby(by="Away")["AST"].transform(self._aggregate_previous_stats)
        return df

    def _compute_home_corners_forward(self, df: pd.DataFrame) -> pd.DataFrame:
        df["HCF"] = df.groupby(by="Home")["HC"].transform(self._aggregate_previous_stats)
        return df

    def _compute_away_corners_forward(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ACF"] = df.groupby(by="Away")["AC"].transform(self._aggregate_previous_stats)
        return df


def _normalize_team(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower()
    name = re.sub(r"\b(fc|cf|sc|ac|fk|cd|ud|sv|vfb|vfl|rb|tsg|1\.)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(val):
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


@dataclass
class TeamForm:
    team: str
    matched_name: str
    league: str
    goals_scored: float = 0.0
    goals_conceded: float = 0.0
    goal_diff: float = 0.0
    shots_on_target: float = 0.0
    corners: float = 0.0
    win_pct: float = 0.0
    under_25_pct: float = 0.0
    under_15_fh_pct: float = 0.0
    avg_fh_goals: float = 0.0
    matches_sampled: int = 0
    venue: str = ""


@dataclass
class MatchProphitStats:
    home: TeamForm
    away: TeamForm
    combined_goals_last_n: float = 0.0
    combined_under_25_pct: float = 0.0
    combined_under_15_fh_pct: float = 0.0
    combined_sot_last_n: float = 0.0
    combined_corners_last_n: float = 0.0
    form_window: int = 3
    source: str = "prophitbet/football-data"


def _download_main_season(url_tpl: str, year: int) -> Optional[pd.DataFrame]:
    url = url_tpl.format(f"{str(year)[-2:]}{str(year + 1)[-2:]}")
    try:
        df = pd.read_csv(url, on_bad_lines="skip")
    except Exception:
        try:
            df = pd.read_csv(url, encoding="latin1", on_bad_lines="skip")
        except Exception:
            return None
    return df.assign(Season=year)


def _download_extra_league(url: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_csv(url, on_bad_lines="skip")
    except Exception:
        try:
            df = pd.read_csv(url, encoding="latin1", on_bad_lines="skip")
        except Exception:
            return None
    if "Season" not in df.columns:
        df["Season"] = date.today().year
    return df


def _preprocess_raw(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {
        "HomeTeam": "Home", "AwayTeam": "Away",
        "FTHG": "HG", "FTAG": "AG", "FTR": "Result",
        "HTHG": "HT_HG", "HTAG": "HT_AG",
        "Res": "Result",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    cols = ["Date", "Home", "Away", "HG", "AG", "Result", "Season"]
    extra = ["HST", "AST", "HC", "AC", "HT_HG", "HT_AG"]
    available = [c for c in cols + extra if c in df.columns]
    df = df[available].copy()
    if "Season" not in df.columns:
        df["Season"] = df["Date"].apply(lambda d: pd.Timestamp(d).year if pd.notna(d) else date.today().year)
    for col in ["HST", "AST", "HC", "AC"]:
        if col not in df.columns:
            df[col] = 0
    if "HT_HG" not in df.columns:
        df["HT_HG"] = pd.NA
    if "HT_AG" not in df.columns:
        df["HT_AG"] = pd.NA

    df = df.dropna(subset=["Date", "Result", "Home", "Away"])
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date"])
    df = df.sort_values(by=["Date", "Home"], ascending=True)
    df = df.drop_duplicates()
    df["Result-U/O"] = (df["HG"] + df["AG"]).ge(2.5).replace({True: "O", False: "U"})
    if "HT_HG" in df.columns and "HT_AG" in df.columns:
        fh_total = df["HT_HG"].fillna(0) + df["HT_AG"].fillna(0)
        df["FH-U/O"] = fh_total.le(1.5).replace({True: "U", False: "O"})
    return df


def _build_team_recent(df: pd.DataFrame, window: int) -> dict[str, dict[str, Any]]:
    """Latest home/away form rows per team."""
    index: dict[str, dict[str, Any]] = {}

    for _, row in df.iterrows():
        for venue, team_col, opp_col in (
            ("home", "Home", "Away"),
            ("away", "Away", "Home"),
        ):
            team = row[team_col]
            norm = _normalize_team(team)
            if norm not in index:
                index[norm] = {"canonical": team, "home": None, "away": None, "recent": []}

            entry = index[norm]
            entry["canonical"] = team
            entry["recent"].append({
                "date": str(row["Date"].date()) if hasattr(row["Date"], "date") else str(row["Date"]),
                "venue": venue,
                "hg": int(row["HG"]), "ag": int(row["AG"]),
                "ht_hg": _safe_float(row.get("HT_HG"), 0),
                "ht_ag": _safe_float(row.get("HT_AG"), 0),
                "uo": row.get("Result-U/O", "U"),
                "fh_uo": row.get("FH-U/O", "U"),
                "league": row.get("League", ""),
            })
            entry[venue] = {
                k: (v.item() if hasattr(v, "item") else v)
                for k, v in row.items()
                if k in {
                    "League", "HGF", "AGF", "HGA", "AGA", "HGD", "AGD",
                    "HSTF", "ASTF", "HCF", "ACF", "HW%", "AW%",
                }
            }

    for norm, entry in index.items():
        recent = entry["recent"][-window:]
        under_25 = sum(1 for m in recent if m["uo"] == "U") / max(len(recent), 1) * 100
        fh_valid = [m for m in recent if m["ht_hg"] + m["ht_ag"] >= 0]
        under_15_fh = (
            sum(1 for m in fh_valid if m["ht_hg"] + m["ht_ag"] <= 1) / max(len(fh_valid), 1) * 100
            if fh_valid else 0.0
        )
        avg_fh = (
            sum(m["ht_hg"] + m["ht_ag"] for m in fh_valid) / max(len(fh_valid), 1)
            if fh_valid else 0.0
        )
        entry["under_25_pct"] = round(under_25, 1)
        entry["under_15_fh_pct"] = round(under_15_fh, 1)
        entry["avg_fh_goals"] = round(avg_fh, 2)
        entry["matches_sampled"] = len(recent)

    return index


class ProphitBetStatsProvider:
    """Singleton cache of ProphitBet rolling stats from football-data.co.uk."""

    _instance: Optional["ProphitBetStatsProvider"] = None

    def __init__(self):
        self._lock = threading.Lock()
        self._team_index: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._loading = False
        self._error: Optional[str] = None
        self._updated_at: Optional[str] = None
        self._leagues_loaded = 0
        self._teams_count = 0
        self._window = 3

    @classmethod
    def get(cls) -> "ProphitBetStatsProvider":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def status(self) -> dict[str, Any]:
        return {
            "loaded": self._loaded,
            "loading": self._loading,
            "updated_at": self._updated_at,
            "leagues_loaded": self._leagues_loaded,
            "leagues_configured": self._leagues_configured(),
            "teams_count": self._teams_count,
            "form_window": self._window,
            "error": self._error,
            "source": "football-data.co.uk (ProphitBet StatisticsEngine)",
        }

    def _leagues_configured(self) -> int:
        try:
            with open(LEAGUES_CFG, encoding="utf-8") as f:
                cfg = json.load(f)
            return len(cfg.get("leagues") or [])
        except (OSError, json.JSONDecodeError):
            return 0

    def _leagues_version(self) -> int:
        try:
            with open(LEAGUES_CFG, encoding="utf-8") as f:
                cfg = json.load(f)
            return int(cfg.get("version") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return 0

    def ensure_loaded(self, background: bool = True) -> None:
        if self._loaded or self._loading:
            return
        if self._cache_fresh():
            self._load_cache()
            if self._loaded:
                return
        if background:
            threading.Thread(target=self._load_all, daemon=True).start()
        else:
            self._load_all()

    def _cache_fresh(self) -> bool:
        meta = DATA_DIR / "meta.json"
        if not meta.exists():
            return False
        try:
            with open(meta, encoding="utf-8") as f:
                info = json.load(f)
            updated = datetime.fromisoformat(info["updated_at"])
            age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
            if info.get("leagues_version", 0) != self._leagues_version():
                return False
            return age_h < CACHE_TTL_HOURS and (DATA_DIR / "team_index.json").exists()
        except (json.JSONDecodeError, KeyError, ValueError):
            return False

    def _load_cache(self) -> None:
        try:
            with open(DATA_DIR / "team_index.json", encoding="utf-8") as f:
                self._team_index = json.load(f)
            with open(DATA_DIR / "meta.json", encoding="utf-8") as f:
                meta = json.load(f)
            self._updated_at = meta.get("updated_at")
            self._leagues_loaded = meta.get("leagues_loaded", 0)
            self._teams_count = len(self._team_index)
            self._window = meta.get("form_window", 3)
            self._loaded = True
        except (OSError, json.JSONDecodeError) as exc:
            self._error = str(exc)

    def _save_cache(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "team_index.json", "w", encoding="utf-8") as f:
            json.dump(self._team_index, f)
        meta = {
            "updated_at": self._updated_at,
            "leagues_loaded": self._leagues_loaded,
            "leagues_version": self._leagues_version(),
            "teams_count": self._teams_count,
            "form_window": self._window,
        }
        with open(DATA_DIR / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f)

    def _load_all(self) -> None:
        with self._lock:
            if self._loaded or self._loading:
                return
            self._loading = True
            self._error = None

        try:
            with open(LEAGUES_CFG, encoding="utf-8") as f:
                cfg = json.load(f)
            window = cfg.get("match_history_window", 3)
            margin = cfg.get("goal_diff_margin", 2)
            leagues = cfg.get("leagues", [])
            engine = StatisticsEngine(window, margin)

            frames: list[pd.DataFrame] = []
            loaded = 0
            start_year = date.today().year - 2

            for lg in leagues:
                if lg["category"] == "main":
                    parts = []
                    for year in range(max(lg["start_year"], start_year), date.today().year + 1):
                        part = _download_main_season(lg["url"], year)
                        if part is not None and not part.empty:
                            parts.append(part)
                    if not parts:
                        continue
                    raw = pd.concat(parts, ignore_index=True)
                else:
                    raw = _download_extra_league(lg["url"])
                    if raw is None or raw.empty:
                        continue

                df = _preprocess_raw(raw)
                if df.empty:
                    continue
                df["League"] = lg["name"]
                try:
                    df = engine.compute_stats(df, STAT_COLUMNS)
                except ValueError:
                    continue
                frames.append(df)
                loaded += 1

            if not frames:
                raise RuntimeError("No league data downloaded from football-data.co.uk")

            combined = pd.concat(frames, ignore_index=True)
            combined = combined.sort_values(by=["Date", "Home"], ascending=True)
            self._team_index = _build_team_recent(combined, window)
            self._window = window
            self._leagues_loaded = loaded
            self._teams_count = len(self._team_index)
            self._updated_at = datetime.now(timezone.utc).isoformat()
            self._loaded = True
            self._save_cache()
        except Exception as exc:
            self._error = str(exc)
        finally:
            self._loading = False

    def _resolve_team(self, name: str) -> Optional[dict[str, Any]]:
        if not self._team_index:
            return None
        norm = _normalize_team(apply_team_alias(name))
        if norm in self._team_index:
            return self._team_index[norm]

        best_key = None
        best_score = 0.0
        for key in self._team_index:
            if norm in key or key in norm:
                score = 0.92
            else:
                score = SequenceMatcher(None, norm, key).ratio()
            if score > best_score:
                best_score = score
                best_key = key
        if best_key and best_score >= 0.72:
            return self._team_index[best_key]
        return None

    def _team_form(self, name: str, venue: str) -> Optional[TeamForm]:
        entry = self._resolve_team(name)
        if not entry:
            return None

        row = entry.get(venue)
        if row is None:
            return None

        if venue == "home":
            return TeamForm(
                team=name,
                matched_name=entry["canonical"],
                league=str(row.get("League", "")),
                goals_scored=_safe_float(row.get("HGF")),
                goals_conceded=_safe_float(row.get("HGA")),
                goal_diff=_safe_float(row.get("HGD")),
                shots_on_target=_safe_float(row.get("HSTF")),
                corners=_safe_float(row.get("HCF")),
                win_pct=_safe_float(row.get("HW%")),
                under_25_pct=entry.get("under_25_pct", 0),
                under_15_fh_pct=entry.get("under_15_fh_pct", 0),
                avg_fh_goals=entry.get("avg_fh_goals", 0),
                matches_sampled=entry.get("matches_sampled", 0),
                venue="home",
            )

        return TeamForm(
            team=name,
            matched_name=entry["canonical"],
            league=str(row.get("League", "")),
            goals_scored=_safe_float(row.get("AGF")),
            goals_conceded=_safe_float(row.get("AGA")),
            goal_diff=_safe_float(row.get("AGD")),
            shots_on_target=_safe_float(row.get("ASTF")),
            corners=_safe_float(row.get("ACF")),
            win_pct=_safe_float(row.get("AW%")),
            under_25_pct=entry.get("under_25_pct", 0),
            under_15_fh_pct=entry.get("under_15_fh_pct", 0),
            avg_fh_goals=entry.get("avg_fh_goals", 0),
            matches_sampled=entry.get("matches_sampled", 0),
            venue="away",
        )

    def lookup_match(self, home: str, away: str) -> Optional[dict[str, Any]]:
        self.ensure_loaded(background=True)
        if not self._loaded:
            return None

        home_form = self._team_form(home, "home")
        away_form = self._team_form(away, "away")

        if not home_form and not away_form:
            home_entry = self._resolve_team(home)
            away_entry = self._resolve_team(away)
            if not home_entry and not away_entry:
                return None
            if home_entry and not home_form:
                home_form = self._generic_form(home, home_entry)
            if away_entry and not away_form:
                away_form = self._generic_form(away, away_entry)

        if not home_form or not away_form:
            partial = {}
            if home_form:
                partial["home"] = asdict(home_form)
            if away_form:
                partial["away"] = asdict(away_form)
            partial["partial"] = True
            partial["form_window"] = self._window
            partial["source"] = "prophitbet/football-data"
            return partial

        combined_goals = (
            home_form.goals_scored + home_form.goals_conceded
            + away_form.goals_scored + away_form.goals_conceded
        )
        combined_u25 = (home_form.under_25_pct + away_form.under_25_pct) / 2
        combined_u15_fh = (home_form.under_15_fh_pct + away_form.under_15_fh_pct) / 2
        combined_sot = home_form.shots_on_target + away_form.shots_on_target
        combined_corners = home_form.corners + away_form.corners

        stats = MatchProphitStats(
            home=home_form,
            away=away_form,
            combined_goals_last_n=round(combined_goals, 2),
            combined_under_25_pct=round(combined_u25, 1),
            combined_under_15_fh_pct=round(combined_u15_fh, 1),
            combined_sot_last_n=round(combined_sot, 1),
            combined_corners_last_n=round(combined_corners, 1),
            form_window=self._window,
        )
        return asdict(stats)

    def _generic_form(self, name: str, entry: dict[str, Any]) -> TeamForm:
        recent = entry.get("recent", [])
        last = recent[-1] if recent else {}
        return TeamForm(
            team=name,
            matched_name=entry["canonical"],
            league=last.get("league", ""),
            under_25_pct=entry.get("under_25_pct", 0),
            under_15_fh_pct=entry.get("under_15_fh_pct", 0),
            avg_fh_goals=entry.get("avg_fh_goals", 0),
            matches_sampled=entry.get("matches_sampled", 0),
            venue="any",
        )


def prophit_scoring_boost(stats: Optional[dict[str, Any]]) -> tuple[float, list[str]]:
    """Translate ProphitBet form into up to 15 confidence points."""
    if not stats:
        return 0.0, []

    boost = 0.0
    signals: list[str] = []
    window = stats.get("form_window", 3)

    combined_goals = stats.get("combined_goals_last_n")
    if combined_goals is not None:
        if combined_goals <= 4.0:
            boost += 6
            signals.append(f"ProphitBet: low scoring form ({combined_goals:.1f} goals last {window})")
        elif combined_goals <= 6.0:
            boost += 3

    u25 = stats.get("combined_under_25_pct", 0)
    if u25 >= 75:
        boost += 5
        signals.append(f"ProphitBet: {u25:.0f}% under 2.5 in recent form")
    elif u25 >= 60:
        boost += 2

    u15_fh = stats.get("combined_under_15_fh_pct", 0)
    if u15_fh >= 70:
        boost += 5
        signals.append(f"ProphitBet: {u15_fh:.0f}% under 1.5 FH in recent form")
    elif u15_fh >= 55:
        boost += 2

    sot = stats.get("combined_sot_last_n", 0)
    if sot <= 8:
        boost += 3
        signals.append(f"ProphitBet: low SoT form ({sot:.0f} last {window})")
    elif sot <= 12:
        boost += 1

    corners = stats.get("combined_corners_last_n", 0)
    if corners <= 10:
        boost += 2
        signals.append(f"ProphitBet: low corner form ({corners:.0f} last {window})")

    home = stats.get("home") or {}
    away = stats.get("away") or {}
    avg_fh = (home.get("avg_fh_goals", 0) + away.get("avg_fh_goals", 0)) / 2
    if avg_fh > 0 and avg_fh <= 0.8:
        boost += 4
        signals.append(f"ProphitBet: low FH goal avg ({avg_fh:.2f})")

    return min(boost, 15.0), signals


PROPHIT_PROVIDER = ProphitBetStatsProvider.get()