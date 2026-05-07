from __future__ import annotations

import html
import io
import json
import random
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont


APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "tournament_data.json"
BRACKET_PDF_FILE = APP_DIR / "schulfestturnier_felder.pdf"

GROUP_CONFIG = [
    {"id": "A", "name": "Gruppe A", "size": 4, "qualifiers": 2},
    {"id": "B", "name": "Gruppe B", "size": 4, "qualifiers": 2},
    {"id": "C", "name": "Gruppe C", "size": 4, "qualifiers": 2},
    {"id": "D", "name": "Gruppe D", "size": 3, "qualifiers": 1},
    {"id": "E", "name": "Gruppe E", "size": 3, "qualifiers": 1},
]

MAIN_QF = [
    ("HQF1", "Viertelfinale 1", 0, 1),
    ("HQF2", "Viertelfinale 2", 2, 3),
    ("HQF3", "Viertelfinale 3", 4, 5),
    ("HQF4", "Viertelfinale 4", 6, 7),
]

SIDE_R1 = [
    ("N1", "Nebenfeld Runde 1 - Spiel 1", 0, 1),
    ("N2", "Nebenfeld Runde 1 - Spiel 2", 2, 3),
    ("N3", "Nebenfeld Runde 1 - Spiel 3", 4, 5),
    ("N4", "Nebenfeld Runde 1 - Spiel 4", 6, 7),
    ("N5", "Nebenfeld Runde 1 - Spiel 5", 8, 9),
]

STATUS_OPTIONS = ["offen", "angesetzt", "laeuft", "fertig", "verschoben"]


def generate_group_matches(group_id: str, team_ids: list[str]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    counter = 1
    for i, first in enumerate(team_ids):
        for second in team_ids[i + 1 :]:
            matches.append(
                {
                    "id": f"G{group_id}{counter}",
                    "team_a": first,
                    "team_b": second,
                    "score_a": None,
                    "score_b": None,
                    "result": "",
                }
            )
            counter += 1
    return matches


def default_data() -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for config in GROUP_CONFIG:
        group_id = config["id"]
        team_ids = [f"{group_id}{i}" for i in range(1, config["size"] + 1)]
        groups[group_id] = {
            "name": config["name"],
            "qualifiers": config["qualifiers"],
            "teams": [
                {"id": team_id, "name": f"Klasse {team_id}", "bonus": 0}
                for team_id in team_ids
            ],
            "matches": generate_group_matches(group_id, team_ids),
            "tiebreak_winner": "",
        }

    return {
        "settings": {
            "event_title": "Schulfestturnier",
            "phase": "Gruppenphase",
            "projector_view": "Automatisch",
            "projector_auto_started_at": 0.0,
            "projector_auto_start_view": "Gruppenphase",
            "group_locked": False,
            "draw_done": False,
            "drawn_at": "",
            "bracket_pdf_path": "",
        },
        "groups": groups,
        "main": {
            "slot_overrides": [""] * 8,
            "scores": {},
        },
        "side": {
            "slot_overrides": [""] * 10,
            "wildcard_match": "N1",
            "direct_final_match": "NQ1",
            "scores": {},
        },
        "schedule": {},
        "custom_schedule": [],
    }


def deep_merge(default: Any, loaded: Any) -> Any:
    if isinstance(default, dict) and isinstance(loaded, dict):
        merged = deepcopy(default)
        for key, value in loaded.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    if isinstance(default, list) and isinstance(loaded, list):
        if len(default) == len(loaded):
            return [deep_merge(default_item, loaded_item) for default_item, loaded_item in zip(default, loaded)]
        return loaded
    return deepcopy(loaded) if loaded is not None else deepcopy(default)


def normalize_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = deep_merge(default_data(), data)
    for config in GROUP_CONFIG:
        group = normalized["groups"][config["id"]]
        expected_ids = [f"{config['id']}{i}" for i in range(1, config["size"] + 1)]
        existing_teams = {team.get("id"): team for team in group.get("teams", [])}
        group["teams"] = [
            {
                "id": team_id,
                "name": str(existing_teams.get(team_id, {}).get("name", f"Klasse {team_id}")),
                "bonus": int(float(existing_teams.get(team_id, {}).get("bonus", 0.0) or 0.0)),
            }
            for team_id in expected_ids
        ]
        existing_matches = {match.get("id"): match for match in group.get("matches", [])}
        group["matches"] = []
        for match in generate_group_matches(config["id"], expected_ids):
            saved = existing_matches.get(match["id"], {})
            match["score_a"] = saved.get("score_a")
            match["score_b"] = saved.get("score_b")
            match["result"] = saved.get("result", "")
            if not match["result"] and match["score_a"] is not None and match["score_b"] is not None:
                if match["score_a"] > match["score_b"]:
                    match["result"] = match["team_a"]
                elif match["score_b"] > match["score_a"]:
                    match["result"] = match["team_b"]
                else:
                    match["result"] = "draw"
            group["matches"].append(match)
        group["qualifiers"] = config["qualifiers"]
        group.setdefault("tiebreak_winner", "")
        group.setdefault("tiebreak_qualifiers", [])
    normalized["main"]["slot_overrides"] = (normalized["main"].get("slot_overrides", []) + [""] * 8)[:8]
    normalized["side"]["slot_overrides"] = (normalized["side"].get("slot_overrides", []) + [""] * 10)[:10]
    normalized["settings"].setdefault("projector_auto_started_at", 0.0)
    normalized["settings"].setdefault("projector_auto_start_view", "Gruppenphase")
    normalized["settings"].setdefault("bracket_pdf_path", "")
    normalized.setdefault("schedule", {})
    normalized.setdefault("custom_schedule", [])
    return normalized


def load_data() -> dict[str, Any]:
    if DATA_FILE.exists():
        try:
            return normalize_data(json.loads(DATA_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return default_data()
    return default_data()


def save_data(data: dict[str, Any]) -> None:
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_tournament_state() -> dict[str, Any]:
    fresh = default_data()
    save_data(fresh)
    try:
        if BRACKET_PDF_FILE.exists():
            BRACKET_PDF_FILE.unlink()
    except OSError:
        pass
    return fresh


def init_state() -> dict[str, Any]:
    if "tournament_data" not in st.session_state:
        st.session_state.tournament_data = load_data()
    st.session_state.tournament_data = normalize_data(st.session_state.tournament_data)
    return st.session_state.tournament_data


def css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #14213d;
            --muted: #667085;
            --line: #d0d5dd;
            --panel: #ffffff;
            --soft: #f3f6fb;
            --blue: #1f6feb;
            --green: #138a3d;
            --amber: #b7791f;
            --red: #c2410c;
        }

        .stApp {
            background: linear-gradient(180deg, #f7f9fd 0%, #eef3f8 100%);
            color: var(--ink);
        }

        .block-container {
            max-width: 1500px;
            padding-top: 1.2rem;
            padding-bottom: 2rem;
        }

        h1, h2, h3 {
            letter-spacing: 0;
        }

        .ts-header {
            border: 1px solid var(--line);
            background: var(--panel);
            padding: 16px 18px;
            margin-bottom: 14px;
        }

        .ts-header h1 {
            font-size: 1.75rem;
            margin: 0;
        }

        .ts-header p {
            margin: 4px 0 0 0;
            color: var(--muted);
        }

        .mini-note {
            color: var(--muted);
            font-size: 0.9rem;
        }

        .ts-table {
            border-collapse: collapse;
            width: 100%;
            background: var(--panel);
            border: 1px solid var(--line);
            font-size: 0.92rem;
        }

        .ts-table th {
            background: #e9eff8;
            border-bottom: 1px solid var(--line);
            color: var(--ink);
            padding: 7px 8px;
            text-align: left;
            white-space: nowrap;
        }

        .ts-table td {
            border-bottom: 1px solid #eaecf0;
            padding: 7px 8px;
            vertical-align: middle;
        }

        .ts-table tr:last-child td {
            border-bottom: none;
        }

        .qualified-row td {
            background: #e8f5ee;
            font-weight: 650;
        }

        .tie-row td {
            background: #fff7e6;
        }

        .bracket {
            --connector: #ffffff;
            background: #e9e8e5;
            border: 1px solid #ddd9d2;
            display: flex;
            gap: 34px;
            overflow-x: auto;
            padding: 26px 24px 34px;
            min-height: 360px;
            align-items: stretch;
        }

        .round-column {
            display: flex;
            flex-direction: column;
            gap: 20px;
            min-width: 252px;
            position: relative;
        }

        .round-column[data-round="1"] {
            padding-top: 52px;
            gap: 92px;
        }

        .round-column[data-round="2"] {
            padding-top: 128px;
            gap: 190px;
        }

        .round-column[data-round="3"] {
            padding-top: 218px;
            gap: 230px;
        }

        .round-title {
            background: transparent;
            border: 0;
            color: #3d414a;
            font-weight: 700;
            padding: 0 0 12px;
            text-transform: none;
            font-size: 1rem;
        }

        .match-card {
            background: var(--panel);
            border: 0;
            border-radius: 4px;
            box-shadow: 0 2px 7px rgba(16, 24, 40, 0.12);
            min-height: 88px;
            overflow: visible;
            position: relative;
        }

        .round-column:not(:last-child) .match-card::after {
            content: "";
            position: absolute;
            right: -34px;
            top: 50%;
            width: 34px;
            border-top: 4px solid var(--connector);
            filter: drop-shadow(0 1px 1px rgba(16, 24, 40, 0.12));
        }

        .match-title {
            background: #f8fafc;
            color: #8a94a6;
            font-size: 0.78rem;
            padding: 7px 10px 5px;
            border-bottom: 1px solid #eaecf0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .team-row {
            display: flex;
            justify-content: space-between;
            gap: 8px;
            padding: 7px 10px;
            min-height: 34px;
            align-items: center;
        }

        .team-row + .team-row {
            border-top: 1px solid #f1f3f6;
        }

        .team-name {
            overflow-wrap: anywhere;
        }

        .team-side {
            align-items: center;
            display: flex;
            gap: 6px;
            min-width: 0;
        }

        .result-dot {
            background: #45c23d;
            border-radius: 999px;
            display: inline-block;
            flex: 0 0 auto;
            height: 8px;
            width: 8px;
        }

        .team-score {
            font-variant-numeric: tabular-nums;
            min-width: 26px;
            text-align: right;
            color: var(--muted);
        }

        .winner {
            background: #ffffff;
            font-weight: 750;
        }

        .wildcard {
            box-shadow: inset 4px 0 0 var(--amber), 0 2px 7px rgba(16, 24, 40, 0.12);
        }

        .direct-final {
            box-shadow: inset 4px 0 0 var(--green), 0 2px 7px rgba(16, 24, 40, 0.12);
        }

        .metric-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 10px;
            margin: 10px 0 18px;
        }

        .metric-box {
            border: 1px solid var(--line);
            background: var(--panel);
            padding: 10px 12px;
        }

        .metric-box b {
            display: block;
            font-size: 1.25rem;
        }

        .metric-box span {
            color: var(--muted);
            font-size: 0.82rem;
        }

        .projector-shell {
            background: #e9e8e5;
            border: 0;
            min-height: calc(100vh - 48px);
            padding: 16px;
        }

        .projector-title {
            background: #08a3d7;
            color: #ffffff;
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: baseline;
            border-bottom: 0;
            padding: 14px 18px;
            margin: -16px -16px 14px;
        }

        .projector-title h1 {
            color: #ffffff;
            font-size: clamp(1.7rem, 3vw, 3.2rem);
            margin: 0;
        }

        .projector-title span {
            color: #eaf8ff;
            font-size: clamp(0.95rem, 1.6vw, 1.4rem);
            white-space: nowrap;
        }

        .projector-groups-fit {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: 10px;
            height: calc(100vh - 145px);
            overflow: hidden;
        }

        .projector-group-card {
            background: #ffffff;
            box-shadow: 0 2px 7px rgba(16, 24, 40, 0.12);
            min-width: 0;
            overflow: hidden;
        }

        .projector-group-card h2 {
            background: #343943;
            color: #ffffff;
            font-size: clamp(0.85rem, 1.15vw, 1.15rem);
            margin: 0;
            padding: 8px 9px;
        }

        .projector-table {
            border: 0;
            font-size: clamp(0.66rem, 0.82vw, 0.92rem);
        }

        .projector-table th,
        .projector-table td {
            padding: 5px 6px;
        }

        .projector-table th:nth-child(4),
        .projector-table td:nth-child(4) {
            display: none;
        }

        .bracket.projector-bracket-single {
            border: 0;
            min-height: calc(100vh - 165px);
            padding: 20px 18px 28px;
        }

        .bracket.projector-bracket-single .round-column {
            min-width: 235px;
        }

        .bracket.projector-bracket-single .round-column[data-round="1"] {
            padding-top: 44px;
            gap: 76px;
        }

        .bracket.projector-bracket-single .round-column[data-round="2"] {
            padding-top: 110px;
            gap: 150px;
        }

        .bracket.projector-bracket-single .round-column[data-round="3"] {
            padding-top: 190px;
            gap: 190px;
        }

        .bracket.projector-bracket-single .match-card {
            min-height: 72px;
        }

        .bracket.projector-bracket-single .team-row {
            font-size: 0.82rem;
            min-height: 28px;
            padding: 4px 8px;
        }

        .bracket.projector-bracket-single .match-title {
            font-size: 0.68rem;
            padding: 5px 8px 4px;
        }

        @media (max-width: 1200px) {
            .projector-groups-fit {
                grid-template-columns: repeat(3, minmax(0, 1fr));
                height: auto;
            }
        }

        /* Compact makeover */
        .block-container {
            max-width: 1280px;
            padding: 0.75rem 1rem 1.2rem;
        }

        div[data-testid="stVerticalBlock"] {
            gap: 0.45rem;
        }

        .ts-header {
            border: 0;
            border-left: 4px solid #08a3d7;
            box-shadow: 0 1px 4px rgba(16, 24, 40, 0.08);
            display: flex;
            align-items: baseline;
            gap: 12px;
            margin-bottom: 8px;
            padding: 7px 10px;
        }

        .ts-header h1 {
            font-size: 1.05rem;
            white-space: nowrap;
        }

        .ts-header p {
            margin: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .mini-note,
        .stCaptionContainer {
            font-size: 0.78rem;
        }

        .ts-table {
            font-size: 0.8rem;
        }

        .ts-table th,
        .ts-table td {
            padding: 4px 6px;
        }

        .metric-strip {
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 6px;
            margin: 6px 0 10px;
        }

        .metric-box {
            padding: 7px 9px;
        }

        .metric-box b {
            font-size: 1rem;
        }

        .metric-box span {
            font-size: 0.72rem;
        }

        .bracket-stage {
            background: #e9e8e5;
            border: 1px solid #dad7d1;
            overflow-x: auto;
            padding: 10px;
        }

        .tree-canvas {
            height: 560px;
            min-width: 1120px;
            width: 1120px;
            margin: 0 auto;
            position: relative;
        }

        .tree-canvas.side-tree {
            height: 560px;
            min-width: 1080px;
            width: 1080px;
        }

        .tree-lines {
            inset: 0;
            overflow: visible;
            position: absolute;
            z-index: 1;
        }

        .tree-lines path {
            fill: none;
            stroke: #ffffff;
            stroke-linecap: square;
            stroke-linejoin: round;
            stroke-width: 4;
            filter: drop-shadow(0 1px 1px rgba(16, 24, 40, 0.16));
        }

        .tree-match {
            background: #ffffff;
            border-radius: 4px;
            box-shadow: 0 2px 7px rgba(16, 24, 40, 0.16);
            min-height: 66px;
            overflow: hidden;
            position: absolute;
            width: 220px;
            z-index: 2;
        }

        .tree-match.compact {
            width: 185px;
        }

        .tree-match-title {
            background: #f8fafc;
            border-bottom: 1px solid #eaecf0;
            color: #8a94a6;
            font-size: 0.68rem;
            font-weight: 700;
            overflow: hidden;
            padding: 5px 8px;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .tree-team {
            align-items: center;
            border-top: 1px solid #f1f3f6;
            display: flex;
            font-size: 0.78rem;
            gap: 6px;
            justify-content: space-between;
            min-height: 26px;
            padding: 4px 8px;
        }

        .tree-team:first-of-type {
            border-top: 0;
        }

        .tree-team-name {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .tree-team.winner {
            font-weight: 800;
        }

        .tree-info {
            background: #f8fafc;
            border-top: 1px solid #eaecf0;
            color: #475467;
            font-size: 0.68rem;
            font-weight: 700;
            padding: 4px 8px;
        }

        .tree-slot {
            background: #f7f9fb;
            border-radius: 3px;
            color: #8a94a6;
            font-size: 0.7rem;
            padding: 1px 5px;
        }

        .tree-round-label {
            color: #3d414a;
            font-size: 0.92rem;
            font-weight: 800;
            position: absolute;
            z-index: 3;
        }

        .tree-badge {
            background: #11a6d9;
            border-radius: 3px;
            color: #ffffff;
            display: inline-block;
            font-size: 0.62rem;
            font-weight: 800;
            margin-left: 5px;
            padding: 1px 5px;
            text-transform: uppercase;
        }

        .projector-shell {
            min-height: 640px;
        }

        .projector-groups-fit {
            height: auto;
        }

        .projector-groups-fit {
            align-content: center;
            display: flex;
            flex-direction: column;
            gap: 18px;
            justify-content: center;
        }

        .projector-row {
            display: grid;
            gap: 18px;
            justify-content: center;
        }

        .projector-row-top {
            grid-template-columns: repeat(3, minmax(260px, 1fr));
        }

        .projector-row-bottom {
            grid-template-columns: repeat(2, minmax(260px, 1fr));
            margin-inline: auto;
            width: min(66%, 860px);
        }

        .projector-group-card {
            border-radius: 8px;
            min-height: 0;
        }

        .projector-table {
            font-size: clamp(0.82rem, 1vw, 1.08rem);
        }

        .projector-qualification {
            align-items: stretch;
            display: grid;
            gap: 24px;
            grid-template-columns: 1fr 1fr;
            height: calc(100vh - 120px);
            padding: 18px;
        }

        .projector-qualification section {
            background: #ffffff;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(16, 24, 40, 0.12);
            overflow: hidden;
        }

        .projector-qualification h2 {
            background: #343943;
            color: #ffffff;
            font-size: clamp(1.4rem, 2vw, 2.4rem);
            margin: 0;
            padding: 14px 18px;
        }

        .projector-qualification .ts-table {
            border: 0;
            font-size: clamp(1rem, 1.25vw, 1.45rem);
        }

        .projector-qualification .ts-table th,
        .projector-qualification .ts-table td {
            padding: 10px 14px;
        }

        section[data-testid="stSidebar"] {
            background: #07111f;
            border-right: 1px solid #162033;
        }

        section[data-testid="stSidebar"] * {
            color: #e8eef8;
        }

        section[data-testid="stSidebar"] [data-testid="stRadio"] label {
            background: transparent;
            border-radius: 8px;
            padding: 4px 6px;
        }

        section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
            background: #101d31;
        }

        .beamer-link {
            border: 1px solid #2b3952;
            border-radius: 8px;
            color: #e8eef8 !important;
            display: block;
            margin: 18px 0 10px;
            padding: 9px 10px;
            text-decoration: none;
        }

        .app-topbar {
            align-items: center;
            background: #ffffff;
            border-bottom: 1px solid #d8dee8;
            display: flex;
            justify-content: space-between;
            margin: -12px -16px 8px;
            padding: 10px 18px;
        }

        .app-topbar h1 {
            font-size: 1.05rem;
            margin: 0;
        }

        .app-topbar a {
            border: 1px solid #d8dee8;
            border-radius: 6px;
            color: #344054;
            font-size: 0.82rem;
            padding: 6px 10px;
            text-decoration: none;
        }

        .beamer-page .block-container,
        .beamer-page {
            height: 100vh;
            overflow: hidden;
        }

        .beamer-page .projector-shell {
            height: 100vh;
            min-height: 100vh;
            overflow: hidden;
            padding: 0;
        }

        .beamer-page .projector-title {
            margin: 0 0 6px;
            padding: 10px 16px;
        }

        .beamer-page .projector-groups-fit {
            grid-template-columns: repeat(5, minmax(0, 1fr));
            height: calc(100vh - 72px);
            padding: 8px;
        }

        .beamer-page .bracket-stage {
            border: 0;
            height: calc(100vh - 70px);
            overflow: hidden;
            padding: 8px;
        }

        .beamer-page .tree-canvas {
            transform: scale(0.88);
            transform-origin: top left;
        }

        header[data-testid="stHeader"], div[data-testid="stToolbar"] {
            display: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def team_map(data: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group in data["groups"].values():
        for team in group["teams"]:
            mapping[team["id"]] = team["name"]
    return mapping


def team_name(data: dict[str, Any], team_id: str | None) -> str:
    if not team_id:
        return "Offen"
    return team_map(data).get(team_id, team_id)


def all_team_ids(data: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for config in GROUP_CONFIG:
        ids.extend(team["id"] for team in data["groups"][config["id"]]["teams"])
    return ids


def team_label(data: dict[str, Any], team_id: str | None) -> str:
    if not team_id:
        return "-"
    return f"{team_name(data, team_id)} ({team_id})"


def score_to_text(score: Any) -> str:
    return "" if score is None else str(score)


def parse_score(raw: str, key_label: str) -> int | None:
    value = raw.strip()
    if value == "":
        return None
    try:
        score = int(value)
    except ValueError:
        st.warning(f"{key_label}: Bitte eine ganze Zahl eintragen.")
        return None
    if score < 0:
        st.warning(f"{key_label}: Negative Ergebnisse werden ignoriert.")
        return None
    return score


def score_input(label: str, value: int | None, key: str) -> int | None:
    raw = st.text_input(label, value=score_to_text(value), key=key, label_visibility="collapsed")
    return parse_score(raw, label)


def group_complete(group: dict[str, Any]) -> bool:
    return all(bool(match.get("result")) for match in group["matches"])


def calculate_standings(data: dict[str, Any], group_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    group = data["groups"][group_id]
    stats: dict[str, dict[str, Any]] = {}
    for team in group["teams"]:
        stats[team["id"]] = {
            "id": team["id"],
            "team": team["name"],
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "match_points": 0.0,
            "bonus": int(team.get("bonus", 0) or 0),
        }

    for match in group["matches"]:
        result = match.get("result", "")
        if not result:
            continue

        first = stats[match["team_a"]]
        second = stats[match["team_b"]]
        first["played"] += 1
        second["played"] += 1

        if result == match["team_a"]:
            first["wins"] += 1
            second["losses"] += 1
            first["match_points"] += 2
        elif result == match["team_b"]:
            second["wins"] += 1
            first["losses"] += 1
            second["match_points"] += 2
        else:
            first["draws"] += 1
            second["draws"] += 1
            first["match_points"] += 1
            second["match_points"] += 1

    for row in stats.values():
        row["total"] = row["match_points"] + row["bonus"]

    def base_sort(row: dict[str, Any]) -> tuple[Any, ...]:
        return (-row["total"], -row["wins"], row["team"].lower())

    ranked = sorted(stats.values(), key=base_sort)
    tie_ids: list[str] = []
    qualifiers = group["qualifiers"]
    if group_complete(group) and len(ranked) > qualifiers:
        boundary_points = ranked[qualifiers - 1]["total"]
        if ranked[qualifiers]["total"] == boundary_points:
            tie_ids = [row["id"] for row in ranked if row["total"] == boundary_points]

    tiebreak_qualifiers = [team_id for team_id in group.get("tiebreak_qualifiers", []) if team_id in tie_ids]
    tiebreak_winner = group.get("tiebreak_winner", "")
    if tiebreak_winner in tie_ids and not tiebreak_qualifiers:
        tiebreak_qualifiers = [tiebreak_winner]
    if tiebreak_qualifiers:
        ranked = sorted(
            stats.values(),
            key=lambda row: (
                -row["total"],
                0 if row["id"] in tiebreak_qualifiers else 1 if row["id"] in tie_ids else 0,
                -row["wins"],
                row["team"].lower(),
            ),
        )
    return ranked, tie_ids


def qualification_lists(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    main: list[dict[str, Any]] = []
    side: list[dict[str, Any]] = []
    for config in GROUP_CONFIG:
        group_id = config["id"]
        standings, _ = calculate_standings(data, group_id)
        qualifiers = data["groups"][group_id]["qualifiers"]
        for index, row in enumerate(standings, start=1):
            item = {
                "id": row["id"],
                "name": row["team"],
                "group": data["groups"][group_id]["name"],
                "rank": index,
                "points": row["total"],
            }
            if index <= qualifiers:
                main.append(item)
            else:
                side.append(item)
    return main, side


def tiebreak_status(data: dict[str, Any], group_id: str) -> dict[str, Any]:
    group = data["groups"][group_id]
    standings, tie_ids = calculate_standings(data, group_id)
    if not tie_ids:
        return {"needed": False, "tie_ids": [], "spots": 0, "selected": []}
    boundary_points = next((row["total"] for row in standings if row["id"] in tie_ids), 0)
    above_tie = sum(1 for row in standings if row["total"] > boundary_points)
    spots = max(0, group["qualifiers"] - above_tie)
    selected = [team_id for team_id in group.get("tiebreak_qualifiers", []) if team_id in tie_ids]
    return {
        "needed": len(selected) != spots,
        "tie_ids": tie_ids,
        "spots": spots,
        "selected": selected,
    }


def group_phase_ready(data: dict[str, Any]) -> tuple[bool, list[str]]:
    problems: list[str] = []
    for config in GROUP_CONFIG:
        group = data["groups"][config["id"]]
        if not group_complete(group):
            problems.append(f"{group['name']}: noch nicht alle Spiele eingetragen")
        status = tiebreak_status(data, config["id"])
        if status["needed"]:
            problems.append(f"{group['name']}: Stechen noch nicht korrekt ausgewaehlt")
    return not problems, problems


def draw_fields(data: dict[str, Any]) -> None:
    main, side = qualification_lists(data)
    main_slots = [item["id"] for item in main]
    side_slots = [item["id"] for item in side]
    random.shuffle(main_slots)
    random.shuffle(side_slots)
    data["main"]["slot_overrides"] = (main_slots + [""] * 8)[:8]
    data["side"]["slot_overrides"] = (side_slots + [""] * 10)[:10]
    data["settings"]["group_locked"] = True
    data["settings"]["draw_done"] = True
    data["settings"]["phase"] = "KO-Phase"
    data["settings"]["drawn_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    restart_projector_auto(data, "Qualifikation")
    write_bracket_pdf(data)


def render_header(data: dict[str, Any], subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="ts-header">
            <h1>{escape(data["settings"].get("event_title", "Schulfestturnier"))}</h1>
            <p>{escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def table_html(
    headers: list[str],
    rows: list[list[Any]],
    row_classes: list[str] | None = None,
    css_class: str = "ts-table",
) -> str:
    row_classes = row_classes or [""] * len(rows)
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = []
    for row, row_class in zip(rows, row_classes):
        cells = "".join(f"<td>{escape(cell)}</td>" for cell in row)
        body.append(f'<tr class="{escape(row_class)}">{cells}</tr>')
    return f'<table class="{escape(css_class)}"><thead><tr>{header_html}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def render_table(headers: list[str], rows: list[list[Any]], row_classes: list[str] | None = None) -> None:
    st.markdown(table_html(headers, rows, row_classes), unsafe_allow_html=True)


def standings_table_parts(data: dict[str, Any], group_id: str, compact: bool = False) -> tuple[list[str], list[list[Any]], list[str]]:
    group = data["groups"][group_id]
    standings, tie_ids = calculate_standings(data, group_id)
    rows: list[list[Any]] = []
    classes: list[str] = []
    for rank, row in enumerate(standings, start=1):
        if compact:
            rows.append([rank, row["team"], row["played"], f'{row["total"]:g}'])
        else:
            rows.append(
                [
                    rank,
                    row["team"],
                    row["played"],
                    row["wins"],
                    row["draws"],
                    row["losses"],
                    f'{row["match_points"]:g}',
                    f'{row["bonus"]:g}',
                    f'{row["total"]:g}',
                ]
            )
        if row["id"] in tie_ids:
            classes.append("tie-row")
        elif rank <= group["qualifiers"]:
            classes.append("qualified-row")
        else:
            classes.append("")
    headers = ["#", "Klasse", "Sp", "Pkt"] if compact else ["#", "Klasse", "Sp", "S", "U", "N", "P", "Bonus", "Gesamt"]
    return headers, rows, classes


def render_standings(data: dict[str, Any], group_id: str, compact: bool = False) -> None:
    headers, rows, classes = standings_table_parts(data, group_id, compact)
    render_table(headers, rows, classes)


def select_team(
    data: dict[str, Any],
    label: str,
    value: str,
    key: str,
    options: list[str] | None = None,
    auto_team: str = "",
) -> str:
    options = options or all_team_ids(data)
    choices = [""] + options
    safe_value = value if value in choices else ""

    def format_choice(choice: str) -> str:
        if choice == "":
            return f"Auto: {team_label(data, auto_team)}" if auto_team else "Auto / offen"
        return team_label(data, choice)

    return st.selectbox(
        label,
        choices,
        index=choices.index(safe_value),
        key=key,
        format_func=format_choice,
    )


def match_record(data: dict[str, Any], bracket: str, match_id: str) -> dict[str, Any]:
    scores = data[bracket].setdefault("scores", {})
    scores.setdefault(match_id, {"score_a": None, "score_b": None, "winner": ""})
    scores[match_id].setdefault("score_a", None)
    scores[match_id].setdefault("score_b", None)
    scores[match_id].setdefault("winner", "")
    scores[match_id].setdefault("time", "")
    scores[match_id].setdefault("place", "")
    scores[match_id].setdefault("show_info", False)
    return scores[match_id]


def winner_from_record(team_a: str, team_b: str, record: dict[str, Any]) -> str:
    manual = record.get("winner", "")
    if manual in [team_a, team_b]:
        return manual
    score_a = record.get("score_a")
    score_b = record.get("score_b")
    if team_a and team_b and score_a is not None and score_b is not None and score_a != score_b:
        return team_a if score_a > score_b else team_b
    return ""


def loser_from_record(team_a: str, team_b: str, record: dict[str, Any]) -> str:
    winner = winner_from_record(team_a, team_b, record)
    if not winner:
        return ""
    return team_b if winner == team_a else team_a


def render_ko_match_editor(
    data: dict[str, Any],
    bracket: str,
    match_id: str,
    label: str,
    team_a: str,
    team_b: str,
) -> None:
    record = match_record(data, bracket, match_id)
    with st.container(border=True):
        cols = st.columns([1.2, 2.4, 2.4, 2.0])
        cols[0].markdown(f"**{label}**")
        cols[1].write(team_label(data, team_a))
        cols[2].write(team_label(data, team_b))
        options = [""] + [team for team in [team_a, team_b] if team]
        current = record.get("winner", "")
        if current not in options:
            current = ""
        record["winner"] = cols[3].selectbox(
            "Sieger",
            options,
            index=options.index(current),
            key=f"{bracket}_{match_id}_winner",
            label_visibility="collapsed",
            format_func=lambda value: "offen" if value == "" else team_name(data, value),
        )
        with st.expander("Uhrzeit / Ort fuer Beamer", expanded=False):
            with st.form(f"{bracket}_{match_id}_info_form", clear_on_submit=False):
                info_cols = st.columns([1.2, 1.6, 1.1, 1])
                staged_time = info_cols[0].text_input("Uhrzeit", value=str(record.get("time", "")), placeholder="10:30")
                staged_place = info_cols[1].text_input("Ort", value=str(record.get("place", "")), placeholder="Halle 1")
                staged_show = info_cols[2].checkbox("Auf Beamer", value=bool(record.get("show_info", False)))
                submitted = info_cols[3].form_submit_button("Bestaetigen")
                if submitted:
                    record["time"] = staged_time.strip()
                    record["place"] = staged_place.strip()
                    record["show_info"] = staged_show
                    st.success("Beamer-Info gespeichert.")


def html_match_card(data: dict[str, Any], match: dict[str, Any]) -> str:
    team_a = match.get("team_a", "")
    team_b = match.get("team_b", "")
    score_a = match.get("score_a")
    score_b = match.get("score_b")
    winner = match.get("winner", "")
    extra = " wildcard" if match.get("wildcard") else ""
    extra += " direct-final" if match.get("direct_final") else ""

    def row(team_id: str, score: Any) -> str:
        winner_class = " winner" if team_id and team_id == winner else ""
        winner_dot = '<span class="result-dot"></span>' if winner_class else ""
        return (
            f'<div class="team-row{winner_class}">'
            f'<span class="team-side"><span class="team-name">{escape(team_name(data, team_id))}</span>{winner_dot}</span>'
            f'<span class="team-score">{escape("-" if score is None else score)}</span>'
            "</div>"
        )

    return (
        f'<div class="match-card{extra}">'
        f'<div class="match-title">{escape(match.get("label", match.get("id", "")))}</div>'
        f"{row(team_a, score_a)}{row(team_b, score_b)}</div>"
    )


def render_bracket_html(data: dict[str, Any], rounds: list[tuple[str, list[dict[str, Any]]]], extra_class: str = "") -> None:
    columns = []
    for round_index, (title, matches) in enumerate(rounds):
        cards = "".join(html_match_card(data, match) for match in matches)
        columns.append(f'<div class="round-column" data-round="{round_index}"><div class="round-title">{escape(title)}</div>{cards}</div>')
    class_name = "bracket" if not extra_class else f"bracket {extra_class}"
    st.markdown(f'<div class="{escape(class_name)}">{"".join(columns)}</div>', unsafe_allow_html=True)


def tree_match_html(
    data: dict[str, Any],
    match: dict[str, Any],
    left: int,
    top: int,
    compact: bool = False,
    badge: str = "",
) -> str:
    winner = match.get("winner", "")
    team_a = match.get("team_a", "")
    team_b = match.get("team_b", "")
    class_name = "tree-match compact" if compact else "tree-match"
    title = escape(match.get("label", match.get("id", "")))
    badge_html = f'<span class="tree-badge">{escape(badge)}</span>' if badge else ""
    info_bits = [str(match.get("time", "")).strip(), str(match.get("place", "")).strip()]
    info_text = " · ".join(bit for bit in info_bits if bit)
    info_html = f'<div class="tree-info">{escape(info_text)}</div>' if match.get("show_info") and info_text else ""

    def row(team_id: str, slot_label: str) -> str:
        winner_class = " winner" if team_id and team_id == winner else ""
        dot = '<span class="result-dot"></span>' if winner_class else ""
        return (
            f'<div class="tree-team{winner_class}">'
            f'<span class="tree-team-name">{escape(team_name(data, team_id))}</span>'
            f'<span>{dot}<span class="tree-slot">{escape(slot_label)}</span></span>'
            "</div>"
        )

    return (
        f'<div class="{class_name}" style="left:{left}px; top:{top}px;">'
        f'<div class="tree-match-title">{title}{badge_html}</div>'
        f'{row(team_a, "A")}{row(team_b, "B")}{info_html}</div>'
    )


def render_main_tree(data: dict[str, Any], projector: bool = False) -> None:
    rounds = build_main_state(data)
    matches = {match["id"]: match for _, round_matches in rounds for match in round_matches}
    labels = [
        ("Viertelfinale", 24, 28),
        ("Halbfinale", 390, 88),
        ("Finale", 760, 208),
    ]
    cards = [
        tree_match_html(data, matches["HQF1"], 24, 70),
        tree_match_html(data, matches["HQF2"], 24, 190),
        tree_match_html(data, matches["HQF3"], 24, 310),
        tree_match_html(data, matches["HQF4"], 24, 430),
        tree_match_html(data, matches["HHF1"], 390, 130),
        tree_match_html(data, matches["HHF2"], 390, 370),
        tree_match_html(data, matches["HFIN"], 760, 250),
    ]
    lines = """
        <path d="M244 103 H300 V163 H390" />
        <path d="M244 223 H300 V163 H390" />
        <path d="M244 343 H300 V403 H390" />
        <path d="M244 463 H300 V403 H390" />
        <path d="M610 163 H680 V283 H760" />
        <path d="M610 403 H680 V283 H760" />
    """
    label_html = "".join(
        f'<div class="tree-round-label" style="left:{left}px; top:{top}px;">{escape(label)}</div>'
        for label, left, top in labels
    )
    height_style = "height:520px;" if projector else ""
    st.markdown(
        f"""
        <div class="bracket-stage">
            <div class="tree-canvas" style="{height_style}">
                <svg class="tree-lines" viewBox="0 0 1120 560" preserveAspectRatio="none">{lines}</svg>
                {label_html}
                {"".join(cards)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_side_tree(data: dict[str, Any], projector: bool = False) -> None:
    rounds = build_side_state(data)
    matches = {match["id"]: match for _, round_matches in rounds for match in round_matches}
    cards = [
        tree_match_html(data, matches["N1"], 20, 70, compact=True, badge="frei"),
        tree_match_html(data, matches["N2"], 20, 165, compact=True),
        tree_match_html(data, matches["N3"], 20, 260, compact=True),
        tree_match_html(data, matches["N4"], 20, 355, compact=True),
        tree_match_html(data, matches["N5"], 20, 450, compact=True),
        tree_match_html(data, matches["NQ1"], 340, 215, compact=True),
        tree_match_html(data, matches["NWHF"], 615, 145, compact=True),
        tree_match_html(data, matches["NQ2"], 615, 405, compact=True, badge="Halbfinale"),
        tree_match_html(data, matches["NFIN"], 875, 255),
    ]
    lines = """
        <path d="M205 103 H520 V178 H615" />
        <path d="M205 198 H270 V248 H340" />
        <path d="M205 293 H270 V248 H340" />
        <path d="M525 248 H570 V178 H615" />
        <path d="M205 388 H470 V438 H615" />
        <path d="M205 483 H470 V438 H615" />
        <path d="M800 438 H835 V288 H875" />
        <path d="M800 178 H835 V288 H875" />
    """
    height_style = "height:560px;" if projector else ""
    st.markdown(
        f"""
        <div class="bracket-stage">
            <div class="tree-canvas side-tree" style="{height_style}">
                <svg class="tree-lines" viewBox="0 0 1080 560" preserveAspectRatio="none">{lines}</svg>
                {"".join(cards)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main_auto_slots(data: dict[str, Any]) -> list[str]:
    by_group_rank: dict[tuple[str, int], str] = {}
    for config in GROUP_CONFIG:
        standings, _ = calculate_standings(data, config["id"])
        for rank, row in enumerate(standings, start=1):
            by_group_rank[(config["id"], rank)] = row["id"]
    return [
        by_group_rank.get(("A", 1), ""),
        by_group_rank.get(("B", 2), ""),
        by_group_rank.get(("B", 1), ""),
        by_group_rank.get(("A", 2), ""),
        by_group_rank.get(("C", 1), ""),
        by_group_rank.get(("D", 1), ""),
        by_group_rank.get(("E", 1), ""),
        by_group_rank.get(("C", 2), ""),
    ]


def side_auto_slots(data: dict[str, Any]) -> list[str]:
    _, side = qualification_lists(data)
    return [item["id"] for item in side] + [""] * (10 - len(side))


def effective_slots(overrides: list[str], auto_slots: list[str], length: int) -> list[str]:
    slots = []
    for index in range(length):
        override = overrides[index] if index < len(overrides) else ""
        auto = auto_slots[index] if index < len(auto_slots) else ""
        slots.append(override or auto)
    return slots


def build_main_state(data: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    slots = effective_slots(data["main"]["slot_overrides"], main_auto_slots(data), 8)
    qf_matches: list[dict[str, Any]] = []
    qf_winners: list[str] = []
    qf_losers: list[str] = []
    for match_id, label, a_index, b_index in MAIN_QF:
        record = match_record(data, "main", match_id)
        team_a = slots[a_index]
        team_b = slots[b_index]
        winner = winner_from_record(team_a, team_b, record)
        loser = loser_from_record(team_a, team_b, record)
        qf_winners.append(winner)
        qf_losers.append(loser)
        qf_matches.append(
            {
                "id": match_id,
                "label": label,
                "team_a": team_a,
                "team_b": team_b,
                "score_a": record.get("score_a"),
                "score_b": record.get("score_b"),
                "winner": winner,
                "time": record.get("time", ""),
                "place": record.get("place", ""),
                "show_info": record.get("show_info", False),
            }
        )

    semi_pairs = [
        ("HHF1", "Halbfinale 1", qf_winners[0], qf_winners[1]),
        ("HHF2", "Halbfinale 2", qf_winners[2], qf_winners[3]),
    ]
    semis: list[dict[str, Any]] = []
    semi_winners: list[str] = []
    semi_losers: list[str] = []
    for match_id, label, team_a, team_b in semi_pairs:
        record = match_record(data, "main", match_id)
        winner = winner_from_record(team_a, team_b, record)
        loser = loser_from_record(team_a, team_b, record)
        semi_winners.append(winner)
        semi_losers.append(loser)
        semis.append(
            {
                "id": match_id,
                "label": label,
                "team_a": team_a,
                "team_b": team_b,
                "score_a": record.get("score_a"),
                "score_b": record.get("score_b"),
                "winner": winner,
                "time": record.get("time", ""),
                "place": record.get("place", ""),
                "show_info": record.get("show_info", False),
            }
        )

    final_record = match_record(data, "main", "HFIN")
    final = {
        "id": "HFIN",
        "label": "Finale Hauptfeld",
        "team_a": semi_winners[0],
        "team_b": semi_winners[1],
        "score_a": final_record.get("score_a"),
        "score_b": final_record.get("score_b"),
        "winner": winner_from_record(semi_winners[0], semi_winners[1], final_record),
        "time": final_record.get("time", ""),
        "place": final_record.get("place", ""),
        "show_info": final_record.get("show_info", False),
    }
    return [
        ("Viertelfinale", qf_matches),
        ("Halbfinale", semis),
        ("Finale", [final]),
    ]


def build_side_state(data: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    slots = effective_slots(data["side"]["slot_overrides"], side_auto_slots(data), 10)
    wildcard_match = "N1"
    direct_final_match = "NQ2"

    r1_matches: list[dict[str, Any]] = []
    r1_winners: dict[str, str] = {}
    for match_id, label, a_index, b_index in SIDE_R1:
        record = match_record(data, "side", match_id)
        team_a = slots[a_index]
        team_b = slots[b_index]
        winner = winner_from_record(team_a, team_b, record)
        r1_winners[match_id] = winner
        r1_matches.append(
            {
                "id": match_id,
                "label": label,
                "team_a": team_a,
                "team_b": team_b,
                "score_a": record.get("score_a"),
                "score_b": record.get("score_b"),
                "winner": winner,
                "time": record.get("time", ""),
                "place": record.get("place", ""),
                "show_info": record.get("show_info", False),
                "wildcard": match_id == wildcard_match,
            }
        )

    wildcard_winner = r1_winners.get(wildcard_match, "")
    r2_pairs = [
        ("NQ1", "Runde 2 - Spiel 1", r1_winners.get("N2", ""), r1_winners.get("N3", "")),
        ("NQ2", "Runde 2 - Spiel 2", r1_winners.get("N4", ""), r1_winners.get("N5", "")),
    ]
    r2_matches: list[dict[str, Any]] = []
    r2_winners: dict[str, str] = {}
    for match_id, label, team_a, team_b in r2_pairs:
        record = match_record(data, "side", match_id)
        winner = winner_from_record(team_a, team_b, record)
        r2_winners[match_id] = winner
        r2_matches.append(
            {
                "id": match_id,
                "label": label,
                "team_a": team_a,
                "team_b": team_b,
                "score_a": record.get("score_a"),
                "score_b": record.get("score_b"),
                "winner": winner,
                "time": record.get("time", ""),
                "place": record.get("place", ""),
                "show_info": record.get("show_info", False),
                "direct_final": match_id == direct_final_match,
            }
        )

    direct_finalist = r2_winners.get(direct_final_match, "")
    wildcard_path_team = r2_winners.get("NQ1", "")
    wildcard_record = match_record(data, "side", "NWHF")
    wildcard_semi_winner = winner_from_record(wildcard_path_team, wildcard_winner, wildcard_record)
    wildcard_semi = {
        "id": "NWHF",
        "label": "Wildcard-Halbfinale",
        "team_a": wildcard_path_team,
        "team_b": wildcard_winner,
        "score_a": wildcard_record.get("score_a"),
        "score_b": wildcard_record.get("score_b"),
        "winner": wildcard_semi_winner,
        "time": wildcard_record.get("time", ""),
        "place": wildcard_record.get("place", ""),
        "show_info": wildcard_record.get("show_info", False),
        "wildcard": True,
    }

    final_record = match_record(data, "side", "NFIN")
    side_final = {
        "id": "NFIN",
        "label": "Finale Nebenfeld",
        "team_a": direct_finalist,
        "team_b": wildcard_semi_winner,
        "score_a": final_record.get("score_a"),
        "score_b": final_record.get("score_b"),
        "winner": winner_from_record(direct_finalist, wildcard_semi_winner, final_record),
        "time": final_record.get("time", ""),
        "place": final_record.get("place", ""),
        "show_info": final_record.get("show_info", False),
    }
    return [
        ("Runde 1", r1_matches),
        ("Runde 2", r2_matches),
        ("Wildcard-Weg", [wildcard_semi]),
        ("Finale", [side_final]),
    ]


def setup_tab(data: dict[str, Any]) -> None:
    render_header(data, "Setup: Klassen, Gruppen und Bonuspunkte")
    st.write("Hier kannst du die Klassennamen und Bonuspunkte eintragen. Die Gruppengroessen und Qualigrenzen sind so voreingestellt, wie du sie beschrieben hast.")
    locked = bool(data["settings"].get("group_locked", False))
    if locked:
        st.info("Teams und Bonuspunkte sind gesperrt, weil die Felder bereits ausgelost wurden.")

    for config in GROUP_CONFIG:
        group = data["groups"][config["id"]]
        with st.expander(f"{group['name']} - {config['size']} Klassen, {config['qualifiers']} ins Hauptfeld", expanded=config["id"] == "A"):
            group["name"] = st.text_input("Gruppenname", value=group["name"], key=f"setup_group_name_{config['id']}", disabled=locked)
            for team in group["teams"]:
                cols = st.columns([4, 1])
                with cols[0]:
                    team["name"] = st.text_input("Klasse", value=team["name"], key=f"setup_team_{team['id']}", disabled=locked)
                with cols[1]:
                    team["bonus"] = st.number_input(
                        "Bonus",
                        value=int(team.get("bonus", 0) or 0),
                        step=1,
                        key=f"setup_bonus_{team['id']}",
                        disabled=locked,
                    )

    main, side = qualification_lists(data)
    st.subheader("Aktuelle Aufteilung")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Hauptfeld**")
        render_table(["Klasse", "Gruppe", "Rang", "Punkte"], [[item["name"], item["group"], item["rank"], f'{item["points"]:g}'] for item in main])
    with cols[1]:
        st.markdown("**Nebenfeld**")
        render_table(["Klasse", "Gruppe", "Rang", "Punkte"], [[item["name"], item["group"], item["rank"], f'{item["points"]:g}'] for item in side])


def groups_tab(data: dict[str, Any]) -> None:
    render_header(data, "Gruppenphase: Ergebnisse, Tabellen und Stechen")
    st.write("Hier trägst du nur ein, wer gewonnen hat. Sieg = 2 Punkte, Unentschieden = 1 Punkt pro Team, Niederlage = 0 Punkte. Bonuspunkte werden addiert.")

    locked = bool(data["settings"].get("group_locked", False))
    if locked:
        st.info("Die Gruppenphase ist gesperrt, weil die Felder bereits ausgelost wurden.")

    tabs = st.tabs([data["groups"][config["id"]]["name"] for config in GROUP_CONFIG])
    for tab, config in zip(tabs, GROUP_CONFIG):
        group_id = config["id"]
        group = data["groups"][group_id]
        with tab:
            st.subheader(group["name"])
            st.caption(f"Qualifikation: Die ersten {group['qualifiers']} kommen ins Hauptfeld.")
            with st.expander("Bonuspunkte", expanded=False):
                bonus_cols = st.columns(len(group["teams"]))
                for bonus_col, team in zip(bonus_cols, group["teams"]):
                    team["bonus"] = bonus_col.number_input(
                        team["name"],
                        value=int(team.get("bonus", 0) or 0),
                        step=1,
                        key=f"group_bonus_{team['id']}",
                        disabled=locked,
                    )
            for match in group["matches"]:
                cols = st.columns([1.1, 2.3, 2.3, 2.4])
                cols[0].caption(match["id"])
                cols[1].write(team_label(data, match["team_a"]))
                cols[2].write(team_label(data, match["team_b"]))
                choices = ["", match["team_a"], "draw", match["team_b"]]
                current = match.get("result", "")
                if current not in choices:
                    current = ""
                match["result"] = cols[3].selectbox(
                    "Ergebnis",
                    choices,
                    index=choices.index(current),
                    key=f"group_{match['id']}_result",
                    label_visibility="collapsed",
                    disabled=locked,
                    format_func=lambda value, m=match: (
                        "offen"
                        if value == ""
                        else "Unentschieden"
                        if value == "draw"
                        else team_name(data, value)
                    ),
                )

            st.markdown("**Tabelle**")
            status = tiebreak_status(data, group_id)
            if status["tie_ids"]:
                with st.container(border=True):
                    st.markdown("**Stechen an der Qualigrenze**")
                    st.caption(
                        f"Diese Teams sind punktgleich: {', '.join(team_name(data, team_id) for team_id in status['tie_ids'])}. "
                        f"Waehle genau {status['spots']} Team(s), die weiterkommen."
                    )
                    if status["spots"] == 1:
                        choices = [""] + status["tie_ids"]
                        current = status["selected"][0] if status["selected"] else ""
                        if current not in choices:
                            current = ""
                        selected_one = st.selectbox(
                            "Sieger des Stechens",
                            choices,
                            index=choices.index(current),
                            key=f"tiebreak_one_{group_id}",
                            disabled=locked,
                            format_func=lambda value: "Noch offen" if value == "" else team_name(data, value),
                        )
                        selected = [selected_one] if selected_one else []
                    else:
                        selected = st.multiselect(
                            "Teams, die nach dem Stechen weiterkommen",
                            status["tie_ids"],
                            default=status["selected"],
                            key=f"tiebreak_multi_{group_id}",
                            disabled=locked,
                            max_selections=status["spots"] or None,
                            format_func=lambda value: team_name(data, value),
                        )
                    if len(selected) != status["spots"] and not locked:
                        st.info(f"Noch {status['spots'] - len(selected)} Auswahl(en) offen.")
                    group["tiebreak_qualifiers"] = selected
                    group["tiebreak_winner"] = selected[0] if selected else ""
            else:
                group["tiebreak_winner"] = ""
                group["tiebreak_qualifiers"] = []
            render_standings(data, group_id)


def main_bracket_tab(data: dict[str, Any]) -> None:
    render_header(data, "Hauptfeld: 8er-KO-Baum")
    if not data["settings"].get("draw_done", False):
        st.warning("Das Hauptfeld wird erst nach der gesperrten Gruppenphase ausgelost. Gehe zu Qualifikation und gib den Code ein.")
        return
    main, _ = qualification_lists(data)
    st.caption(f"Aktuell im Hauptfeld: {len(main)} von 8 Slots. Du kannst jeden Slot manuell ueberschreiben.")

    auto_slots = main_auto_slots(data)
    options = [item["id"] for item in main] or all_team_ids(data)
    with st.expander("Setzung bearbeiten", expanded=False):
        for row_start in range(0, 8, 4):
            cols = st.columns(4)
            for offset, col in enumerate(cols):
                index = row_start + offset
                with col:
                    data["main"]["slot_overrides"][index] = select_team(
                        data,
                        f"Slot {index + 1}",
                        data["main"]["slot_overrides"][index],
                        f"main_slot_{index}",
                        options=options,
                        auto_team=auto_slots[index] if index < len(auto_slots) else "",
                    )

    with st.expander("Sieger eintragen", expanded=False):
        state = build_main_state(data)
        qf_lookup = {match["id"]: match for _, matches in state for match in matches}
        for match_id, label, _, _ in MAIN_QF:
            match = qf_lookup[match_id]
            render_ko_match_editor(data, "main", match_id, label, match["team_a"], match["team_b"])

        state = build_main_state(data)
        for match in state[1][1]:
            render_ko_match_editor(data, "main", match["id"], match["label"], match["team_a"], match["team_b"])

        state = build_main_state(data)
        for match in state[2][1]:
            render_ko_match_editor(data, "main", match["id"], match["label"], match["team_a"], match["team_b"])

    st.subheader("Baum")
    render_main_tree(data)


def side_bracket_tab(data: dict[str, Any]) -> None:
    render_header(data, "Nebenfeld: 10er-Baum mit Wildcard-Spiel")
    if not data["settings"].get("draw_done", False):
        st.warning("Das Nebenfeld wird erst nach der gesperrten Gruppenphase ausgelost. Gehe zu Qualifikation und gib den Code ein.")
        return
    _, side = qualification_lists(data)
    st.caption("Die 10 Nebenfeld-Teams starten in Runde 1. Der Sieger des Wildcard-Spiels hat Runde 2 frei.")

    auto_slots = side_auto_slots(data)
    options = [item["id"] for item in side] or all_team_ids(data)
    with st.expander("Setzung bearbeiten", expanded=False):
        for row_start in range(0, 10, 2):
            cols = st.columns(2)
            for offset, col in enumerate(cols):
                index = row_start + offset
                with col:
                    data["side"]["slot_overrides"][index] = select_team(
                        data,
                        f"Slot {index + 1}",
                        data["side"]["slot_overrides"][index],
                        f"side_slot_{index}",
                        options=options,
                        auto_team=auto_slots[index] if index < len(auto_slots) else "",
                    )

    with st.expander("Sieger eintragen", expanded=False):
        st.caption("Nach Skizze: Spiel 1 ist Wildcard/frei, der 7-10-Zweig geht direkt ins Finale.")
        state = build_side_state(data)
        for match in state[0][1]:
            label = match["label"]
            if match["id"] == "N1":
                label += " (Wildcard)"
            render_ko_match_editor(data, "side", match["id"], label, match["team_a"], match["team_b"])

        state = build_side_state(data)
        for match in state[1][1]:
            label = match["label"]
            if match["id"] == "NQ2":
                label += " (Sieger direkt im Finale)"
            render_ko_match_editor(data, "side", match["id"], label, match["team_a"], match["team_b"])

        state = build_side_state(data)
        for match in state[2][1] + state[3][1]:
            render_ko_match_editor(data, "side", match["id"], match["label"], match["team_a"], match["team_b"])

    st.subheader("Baum")
    render_side_tree(data)


def collect_match_catalog(data: dict[str, Any]) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for config in GROUP_CONFIG:
        group = data["groups"][config["id"]]
        for match in group["matches"]:
            catalog.append(
                {
                    "id": match["id"],
                    "phase": "Gruppenphase",
                    "round": group["name"],
                    "label": f"{group['name']} - {match['id']}",
                    "team_a": match["team_a"],
                    "team_b": match["team_b"],
                }
            )

    for round_name, matches in build_main_state(data):
        for match in matches:
            catalog.append(
                {
                    "id": match["id"],
                    "phase": "Hauptfeld",
                    "round": round_name,
                    "label": match["label"],
                    "team_a": match["team_a"],
                    "team_b": match["team_b"],
                }
            )

    for round_name, matches in build_side_state(data):
        for match in matches:
            catalog.append(
                {
                    "id": match["id"],
                    "phase": "Nebenfeld",
                    "round": round_name,
                    "label": match["label"],
                    "team_a": match["team_a"],
                    "team_b": match["team_b"],
                }
            )
    return catalog


def schedule_dataframe(data: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for match in collect_match_catalog(data):
        schedule = data["schedule"].setdefault(match["id"], {})
        rows.append(
            {
                "ID": match["id"],
                "Phase": match["phase"],
                "Runde": match["round"],
                "Spiel": match["label"],
                "Team A": team_name(data, match["team_a"]),
                "Team B": team_name(data, match["team_b"]),
                "Zeit": schedule.get("time", ""),
                "Ort": schedule.get("place", ""),
                "Status": schedule.get("status", "offen"),
                "Notiz": schedule.get("note", ""),
            }
        )
    return pd.DataFrame(rows)


def schedule_tab(data: dict[str, Any]) -> None:
    render_header(data, "Spielplan: Zeiten, Orte und Zusatzspiele")
    st.write("Hier kannst du eintragen, wo und wann welche Klasse sein soll. Zusatzspiele fuer Platzierungen oder Klassenraeume kannst du unten frei ergaenzen.")

    schedule_df = schedule_dataframe(data)
    edited = st.data_editor(
        schedule_df,
        use_container_width=True,
        hide_index=True,
        disabled=["ID", "Phase", "Runde", "Spiel", "Team A", "Team B"],
        column_config={
            "Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS),
            "Zeit": st.column_config.TextColumn("Zeit", help="Zum Beispiel 10:30"),
            "Ort": st.column_config.TextColumn("Ort", help="Zum Beispiel Halle 1"),
        },
        key="schedule_editor",
    )
    for _, row in edited.iterrows():
        data["schedule"][row["ID"]] = {
            "time": "" if pd.isna(row["Zeit"]) else str(row["Zeit"]),
            "place": "" if pd.isna(row["Ort"]) else str(row["Ort"]),
            "status": "offen" if pd.isna(row["Status"]) else str(row["Status"]),
            "note": "" if pd.isna(row["Notiz"]) else str(row["Notiz"]),
        }

    st.subheader("Freie Zusatzzeilen")
    custom_columns = ["Spiel", "Team A", "Team B", "Zeit", "Ort", "Status", "Notiz"]
    custom_df = pd.DataFrame(data.get("custom_schedule", []), columns=custom_columns)
    custom_edited = st.data_editor(
        custom_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={"Status": st.column_config.SelectboxColumn("Status", options=STATUS_OPTIONS)},
        key="custom_schedule_editor",
    )
    cleaned_custom = custom_edited.fillna("").to_dict("records")
    data["custom_schedule"] = [
        {column: str(row.get(column, "")) for column in custom_columns}
        for row in cleaned_custom
        if any(str(row.get(column, "")).strip() for column in custom_columns)
    ]

    st.subheader("Export")
    export_df = schedule_dataframe(data)
    if data.get("custom_schedule"):
        custom_export = pd.DataFrame(data["custom_schedule"])
        custom_export.insert(0, "ID", "frei")
        custom_export.insert(1, "Phase", "Zusatz")
        custom_export.insert(2, "Runde", "")
        export_df = pd.concat([export_df, custom_export], ignore_index=True, sort=False)
    st.download_button(
        "Spielplan als CSV herunterladen",
        data=export_df.to_csv(index=False).encode("utf-8-sig"),
        file_name="spielplan.csv",
        mime="text/csv",
    )
    st.download_button(
        "Turnier als Excel herunterladen",
        data=excel_export(data),
        file_name="turnier_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def standings_dataframe(data: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for config in GROUP_CONFIG:
        group_id = config["id"]
        group = data["groups"][group_id]
        standings, _ = calculate_standings(data, group_id)
        for rank, row in enumerate(standings, start=1):
            rows.append(
                {
                    "Gruppe": group["name"],
                    "Rang": rank,
                    "Klasse": row["team"],
                    "Spiele": row["played"],
                    "Siege": row["wins"],
                    "Unentschieden": row["draws"],
                    "Niederlagen": row["losses"],
                    "Punkte": row["match_points"],
                    "Bonus": row["bonus"],
                    "Gesamt": row["total"],
                    "Qualifikation": "Hauptfeld" if rank <= group["qualifiers"] else "Nebenfeld",
                }
            )
    return pd.DataFrame(rows)


def excel_export(data: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        standings_dataframe(data).to_excel(writer, sheet_name="Tabellen", index=False)
        schedule_dataframe(data).to_excel(writer, sheet_name="Spielplan", index=False)
        pd.DataFrame(collect_match_catalog(data)).to_excel(writer, sheet_name="Spiele", index=False)
        if data.get("custom_schedule"):
            pd.DataFrame(data["custom_schedule"]).to_excel(writer, sheet_name="Zusatz", index=False)
    return output.getvalue()


def bracket_pdf(data: dict[str, Any]) -> bytes:
    def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
        try:
            return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)
        except OSError:
            return ImageFont.load_default()

    def card(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, a: str, b: str, winner: str = "") -> None:
        x1, y1, x2, y2 = box
        draw.rounded_rectangle(box, radius=8, fill="white", outline="#cfd6df", width=2)
        draw.rectangle((x1, y1, x2, y1 + 28), fill="#f5f7fa")
        draw.text((x1 + 10, y1 + 7), title, fill="#667085", font=font(14, True))
        draw.text((x1 + 10, y1 + 38), a, fill="#111827", font=font(16, a == winner))
        draw.text((x1 + 10, y1 + 68), b, fill="#111827", font=font(16, b == winner))

    def line(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]]) -> None:
        draw.line(points, fill="#344054", width=3, joint="curve")

    main_img = Image.new("RGB", (1600, 1000), "#f4f5f7")
    d = ImageDraw.Draw(main_img)
    d.text((55, 35), "Hauptfeld", fill="#111827", font=font(34, True))
    main_matches = {m["id"]: m for _, ms in build_main_state(data) for m in ms}
    main_pos = {
        "HQF1": (60, 120, 380, 220),
        "HQF2": (60, 300, 380, 400),
        "HQF3": (60, 520, 380, 620),
        "HQF4": (60, 700, 380, 800),
        "HHF1": (600, 210, 920, 310),
        "HHF2": (600, 610, 920, 710),
        "HFIN": (1120, 410, 1440, 510),
    }
    for points in [
        [(380, 170), (480, 170), (480, 260), (600, 260)],
        [(380, 350), (480, 350), (480, 260), (600, 260)],
        [(380, 570), (480, 570), (480, 660), (600, 660)],
        [(380, 750), (480, 750), (480, 660), (600, 660)],
        [(920, 260), (1010, 260), (1010, 460), (1120, 460)],
        [(920, 660), (1010, 660), (1010, 460), (1120, 460)],
    ]:
        line(d, points)
    for match_id, box in main_pos.items():
        match = main_matches[match_id]
        card(d, box, match["label"], team_name(data, match["team_a"]), team_name(data, match["team_b"]), team_name(data, match.get("winner", "")))

    side_img = Image.new("RGB", (1600, 1000), "#f4f5f7")
    d = ImageDraw.Draw(side_img)
    d.text((55, 35), "Nebenfeld", fill="#111827", font=font(34, True))
    side_matches = {m["id"]: m for _, ms in build_side_state(data) for m in ms}
    side_pos = {
        "N1": (50, 90, 330, 180),
        "N2": (50, 250, 330, 340),
        "N3": (50, 410, 330, 500),
        "N4": (50, 590, 330, 680),
        "N5": (50, 750, 330, 840),
        "NQ1": (520, 330, 800, 420),
        "NWHF": (930, 210, 1210, 300),
        "NQ2": (930, 670, 1210, 760),
        "NFIN": (1280, 450, 1560, 540),
    }
    for points in [
        [(330, 135), (720, 135), (720, 255), (930, 255)],
        [(330, 295), (430, 295), (430, 375), (520, 375)],
        [(330, 455), (430, 455), (430, 375), (520, 375)],
        [(800, 375), (860, 375), (860, 255), (930, 255)],
        [(330, 635), (700, 635), (700, 715), (930, 715)],
        [(330, 795), (700, 795), (700, 715), (930, 715)],
        [(1210, 715), (1240, 715), (1240, 495), (1280, 495)],
        [(1210, 255), (1240, 255), (1240, 495), (1280, 495)],
    ]:
        line(d, points)
    for match_id, box in side_pos.items():
        match = side_matches[match_id]
        card(d, box, match["label"], team_name(data, match["team_a"]), team_name(data, match["team_b"]), team_name(data, match.get("winner", "")))

    output = io.BytesIO()
    main_img.save(output, format="PDF", save_all=True, append_images=[side_img])
    return output.getvalue()


def write_bracket_pdf(data: dict[str, Any]) -> None:
    BRACKET_PDF_FILE.write_bytes(bracket_pdf(data))
    data["settings"]["bracket_pdf_path"] = str(BRACKET_PDF_FILE)


def restart_projector_auto(data: dict[str, Any], start_view: str | None = None) -> None:
    now = time.time()
    if not data["settings"].get("draw_done", False):
        start_view = "Gruppenphase"
    elif start_view not in {"Gruppenphase", "Qualifikation", "Hauptfeld", "Nebenfeld", "KO-Felder"}:
        start_view = "Qualifikation"
    if start_view == "KO-Felder":
        start_view = "Hauptfeld"
    data["settings"]["projector_view"] = "Automatisch"
    data["settings"]["projector_auto_start_view"] = start_view
    data["settings"]["projector_auto_started_at"] = now - 300 if start_view in {"Hauptfeld", "Nebenfeld"} else now


def auto_projector_display(data: dict[str, Any]) -> tuple[str, str]:
    if not data["settings"].get("draw_done", False):
        return "Gruppenphase", ""

    started = float(data["settings"].get("projector_auto_started_at", 0.0) or 0.0)
    if started <= 0:
        restart_projector_auto(data, "Qualifikation")
        save_data(data)
        started = float(data["settings"].get("projector_auto_started_at", 0.0) or 0.0)

    elapsed = max(0, time.time() - started)
    start_view = data["settings"].get("projector_auto_start_view", "Qualifikation")
    if elapsed < 300:
        first = start_view if start_view in {"Gruppenphase", "Qualifikation"} else "Qualifikation"
        second = "Gruppenphase" if first == "Qualifikation" else "Qualifikation"
        display_label = first if int(elapsed % 30) < 15 else second
        return display_label, ""

    first_bracket = start_view if start_view in {"Hauptfeld", "Nebenfeld"} else "Hauptfeld"
    second_bracket = "Nebenfeld" if first_bracket == "Hauptfeld" else "Hauptfeld"
    active_bracket = first_bracket if int((elapsed - 300) // 15) % 2 == 0 else second_bracket
    return active_bracket, active_bracket


def current_projector_screen(data: dict[str, Any]) -> str:
    view_setting = data["settings"].get("projector_view", "Automatisch")
    if view_setting == "Automatisch":
        return auto_projector_display(data)[0]
    if view_setting == "KO-Felder":
        return "Hauptfeld" if int(time.time() // 15) % 2 == 0 else "Nebenfeld"
    return view_setting


def future_planning_placeholder(data: dict[str, Any]) -> None:
    """Reserviert fuer spaetere Zeit-/Ort-Planung, falls sie wieder gebraucht wird."""
    return None


def qualification_tab(data: dict[str, Any]) -> None:
    render_header(data, "Qualifikation: Gruppenphase sperren und Felder auslosen")
    ready, problems = group_phase_ready(data)
    locked = bool(data["settings"].get("group_locked", False))
    if locked:
        st.success(f"Gruppenphase gesperrt. Felder ausgelost: {data['settings'].get('drawn_at', '-')}")
    elif problems:
        st.warning("Vor der Auslosung muss die Gruppenphase komplett sein.")
        for problem in problems:
            st.write(f"- {problem}")
    else:
        st.success("Gruppenphase komplett. Code eingeben, um zu sperren und auszulosen.")

    main, side = qualification_lists(data)
    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Hauptfeld-Kandidaten**")
        render_table(["Klasse", "Gruppe", "Rang"], [[item["name"], item["group"], item["rank"]] for item in main])
    with cols[1]:
        st.markdown("**Nebenfeld-Kandidaten**")
        render_table(["Klasse", "Gruppe", "Rang"], [[item["name"], item["group"], item["rank"]] for item in side])

    if not locked:
        code = st.text_input("Auslosungs-Code", type="password", placeholder="")
        if st.button("Gruppenphase sperren und Felder auslosen", disabled=not ready):
            if code == "0987":
                draw_fields(data)
                save_data(data)
                st.rerun()
            else:
                st.error("Falscher Code.")
    else:
        if not BRACKET_PDF_FILE.exists():
            write_bracket_pdf(data)
        st.download_button(
            "PDF der Felder herunterladen",
            data=BRACKET_PDF_FILE.read_bytes(),
            file_name="schulfestturnier_felder.pdf",
            mime="application/pdf",
        )
        if st.button("PDF neu erstellen"):
            write_bracket_pdf(data)
            save_data(data)
            st.success("PDF wurde neu erstellt.")


def active_matches(data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if not data["settings"].get("draw_done", False):
        return []
    matches: list[tuple[str, dict[str, Any]]] = []
    for field_name, rounds in [("Hauptfeld", build_main_state(data)), ("Nebenfeld", build_side_state(data))]:
        for _, round_matches in rounds:
            for match in round_matches:
                if match.get("team_a") and match.get("team_b") and not match.get("winner"):
                    matches.append((field_name, match))
    return matches


def live_games_tab(data: dict[str, Any]) -> None:
    render_header(data, "Laufende Spiele: Sieger eintragen")
    matches = active_matches(data)
    if not matches:
        st.info("Aktuell gibt es keine offenen KO-Spiele mit zwei feststehenden Teams.")
        return
    for field_name, match in matches:
        render_ko_match_editor(data, "main" if field_name == "Hauptfeld" else "side", match["id"], f"{field_name} - {match['label']}", match["team_a"], match["team_b"])


def settings_tab(data: dict[str, Any]) -> None:
    render_header(data, "Einstellungen")
    data["settings"]["event_title"] = st.text_input("Titel", value=data["settings"].get("event_title", "Schulfestturnier"))
    data["settings"]["phase"] = st.selectbox(
        "Aktive Phase",
        ["Gruppenphase", "KO-Phase"],
        index=["Gruppenphase", "KO-Phase"].index(data["settings"].get("phase", "Gruppenphase")),
    )
    projector_options = ["Automatisch", "Gruppenphase", "Qualifikation", "Hauptfeld", "Nebenfeld", "KO-Felder"]
    current_projector = data["settings"].get("projector_view", "Automatisch")
    if current_projector not in projector_options:
        current_projector = "Automatisch"
    previous_projector = current_projector
    selected_projector = st.selectbox(
        "Beamer zeigt",
        projector_options,
        index=projector_options.index(current_projector),
    )
    if selected_projector != data["settings"].get("projector_view", "Automatisch"):
        if selected_projector == "Automatisch":
            restart_projector_auto(data, previous_projector)
        else:
            data["settings"]["projector_view"] = selected_projector
    if data["settings"].get("projector_view") == "Automatisch":
        if st.button("Automatik ab aktuellem Bild neu starten"):
            restart_projector_auto(data, current_projector_screen(data))
            st.success("Beamer-Automatik neu gestartet.")

    st.divider()
    st.markdown("**Turnier komplett zuruecksetzen**")
    reset_code = st.text_input("Reset-Code", type="password", placeholder="")
    if st.button("Alles auf null setzen"):
        if reset_code == "2611":
            st.session_state.tournament_data = reset_tournament_state()
            st.success("Turnier wurde zurueckgesetzt.")
            st.rerun()
        else:
            st.error("Falscher Reset-Code.")

    st.divider()
    st.download_button(
        "JSON-Backup herunterladen",
        data=json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
        file_name="turnier_backup.json",
        mime="application/json",
    )
    uploaded = st.file_uploader("JSON-Backup laden", type=["json"])
    if uploaded is not None:
        try:
            st.session_state.tournament_data = normalize_data(json.loads(uploaded.getvalue().decode("utf-8")))
            save_data(st.session_state.tournament_data)
            st.success("Backup geladen.")
            st.rerun()
        except (json.JSONDecodeError, UnicodeDecodeError):
            st.error("Das Backup konnte nicht gelesen werden.")


def render_projector_groups(data: dict[str, Any]) -> None:
    cards = []
    for config in GROUP_CONFIG:
        group_id = config["id"]
        headers, rows, classes = standings_table_parts(data, group_id, compact=True)
        cards.append(
            f'<section class="projector-group-card">'
            f'<h2>{escape(data["groups"][group_id]["name"])}</h2>'
            f'{table_html(headers, rows, classes, css_class="ts-table projector-table")}'
            f"</section>"
        )
    st.markdown(
        f"""
        <div class="projector-groups-fit">
            <div class="projector-row projector-row-top">{"".join(cards[:3])}</div>
            <div class="projector-row projector-row-bottom">{"".join(cards[3:])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_projector_brackets(data: dict[str, Any], active_bracket: str) -> None:
    if active_bracket == "Nebenfeld":
        render_side_tree(data, projector=True)
    else:
        render_main_tree(data, projector=True)


def render_projector_qualification(data: dict[str, Any]) -> None:
    main, side = qualification_lists(data)

    def rows(items: list[dict[str, Any]]) -> str:
        return "".join(
            f"<tr><td>{escape(item['name'])}</td><td>{escape(item['group'])}</td><td>{escape(item['rank'])}</td></tr>"
            for item in items
        )

    st.markdown(
        f"""
        <div class="projector-qualification">
            <section>
                <h2>Hauptfeld</h2>
                <table class="ts-table projector-table">
                    <thead><tr><th>Klasse</th><th>Gruppe</th><th>Rang</th></tr></thead>
                    <tbody>{rows(main)}</tbody>
                </table>
            </section>
            <section>
                <h2>Nebenfeld</h2>
                <table class="ts-table projector-table">
                    <thead><tr><th>Klasse</th><th>Gruppe</th><th>Rang</th></tr></thead>
                    <tbody>{rows(side)}</tbody>
                </table>
            </section>
        </div>
        """,
        unsafe_allow_html=True,
    )


def projector_view(data: dict[str, Any]) -> None:
    view_setting = data["settings"].get("projector_view", "Automatisch")
    active_bracket = ""
    display_label = "Gruppenphase"
    if view_setting == "Automatisch":
        display_label, active_bracket = auto_projector_display(data)
    elif view_setting == "Qualifikation":
        display_label = "Qualifikation"
    elif view_setting in ["Hauptfeld", "Nebenfeld"]:
        active_bracket = view_setting
        display_label = view_setting
    elif view_setting == "KO-Felder":
        active_bracket = "Hauptfeld" if int(time.time() // 15) % 2 == 0 else "Nebenfeld"
        display_label = active_bracket

    st.markdown(
        f"""
        <div class="projector-title">
            <h1>{escape(data["settings"].get("event_title", "Schulfestturnier"))}</h1>
            <span>{escape(display_label)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if display_label == "Gruppenphase":
        render_projector_groups(data)
    elif display_label == "Qualifikation":
        render_projector_qualification(data)
    else:
        render_projector_brackets(data, active_bracket)


def live_projector_panel() -> None:
    projector_view(load_data())


if hasattr(st, "fragment"):
    live_projector_panel = st.fragment(run_every="2s")(live_projector_panel)


def sidebar(data: dict[str, Any]) -> tuple[str, str]:
    st.sidebar.markdown("## Schulfest Turnier")
    page = st.sidebar.radio(
        "Navigation",
        [
            "Start / Teams",
            "Gruppenphase",
            "Qualifikation",
            "K.O.-Felder",
            "Laufende Spiele",
            "Beamer",
            "Einstellungen",
        ],
        label_visibility="collapsed",
    )
    field = "Hauptfeld"
    if page == "K.O.-Felder":
        field = st.sidebar.radio("Feld", ["Hauptfeld", "Nebenfeld"], label_visibility="collapsed")
    st.sidebar.markdown(
        '<a class="beamer-link" href="?view=beamer" target="_blank">Beamer-Modus öffnen</a>',
        unsafe_allow_html=True,
    )
    st.sidebar.caption(
        "Status: "
        + ("KO-Phase" if data["settings"].get("draw_done") else "Gruppenphase")
        + (" · gesperrt" if data["settings"].get("group_locked") else "")
    )
    return page, field


def dashboard_metrics(data: dict[str, Any]) -> None:
    main, side = qualification_lists(data)
    group_matches = [match for group in data["groups"].values() for match in group["matches"]]
    played = sum(1 for match in group_matches if match.get("result"))
    total = len(group_matches)
    main_winner = build_main_state(data)[2][1][0].get("winner", "")
    side_winner = build_side_state(data)[3][1][0].get("winner", "")
    st.markdown(
        f"""
        <div class="metric-strip">
            <div class="metric-box"><b>{played}/{total}</b><span>Gruppenspiele eingetragen</span></div>
            <div class="metric-box"><b>{len(main)}</b><span>Hauptfeld-Slots</span></div>
            <div class="metric-box"><b>{len(side)}</b><span>Nebenfeld-Slots</span></div>
            <div class="metric-box"><b>{escape(team_name(data, main_winner))}</b><span>Sieger Hauptfeld</span></div>
            <div class="metric-box"><b>{escape(team_name(data, side_winner))}</b><span>Sieger Nebenfeld</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Schulfestturnier",
        page_icon="🏆",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    css()
    data = init_state()
    if st.query_params.get("view") == "beamer":
        st.markdown(
            """
            <style>
            section[data-testid="stSidebar"], header[data-testid="stHeader"], div[data-testid="stToolbar"] {
                display: none !important;
            }
            .block-container {
                max-width: 100% !important;
                padding: 0 !important;
            }
            html, body, .stApp {
                overflow: hidden !important;
            }
            .projector-shell {
                height: 100vh !important;
                min-height: 100vh !important;
                overflow: hidden !important;
                padding: 0 !important;
            }
            .projector-title {
                display: none !important;
            }
            .projector-groups-fit {
                height: 100vh !important;
                padding: 8px !important;
            }
            .projector-row {
                gap: 14px !important;
            }
            .projector-row-top {
                grid-template-columns: repeat(3, minmax(280px, 1fr)) !important;
                width: min(96vw, 1420px) !important;
                margin-inline: auto !important;
            }
            .projector-row-bottom {
                grid-template-columns: repeat(2, minmax(280px, 1fr)) !important;
                width: min(64vw, 920px) !important;
                margin-inline: auto !important;
            }
            .projector-qualification {
                height: 100vh !important;
                padding: 12px !important;
            }
            .bracket-stage {
                border: 0 !important;
                height: 100vh !important;
                overflow: hidden !important;
                padding: 8px !important;
            }
            .tree-canvas {
                transform: scale(0.88);
                transform-origin: top left;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
        live_projector_panel()
        return

    page, field = sidebar(data)
    st.markdown(
        f"""
        <div class="app-topbar">
            <h1>{escape(data["settings"].get("event_title", "Schulfestturnier"))} Verwaltung</h1>
            <a href="?view=beamer" target="_blank">Beamer-Modus</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
    dashboard_metrics(data)

    if page == "Start / Teams":
        setup_tab(data)
    elif page == "Gruppenphase":
        groups_tab(data)
    elif page == "Qualifikation":
        qualification_tab(data)
    elif page == "K.O.-Felder" and field == "Hauptfeld":
        main_bracket_tab(data)
    elif page == "K.O.-Felder":
        side_bracket_tab(data)
    elif page == "Laufende Spiele":
        live_games_tab(data)
    elif page == "Beamer":
        live_projector_panel()
    elif page == "Einstellungen":
        settings_tab(data)

    save_data(data)


if __name__ == "__main__":
    main()
