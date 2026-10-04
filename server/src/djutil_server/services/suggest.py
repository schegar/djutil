"""Next-track suggestions: Camelot + BPM compatibility with history bonus."""

from __future__ import annotations

import math
import os
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Weights (overridable via DJUTIL_SUGGEST_* env vars).
W_KEY = float(os.environ.get("DJUTIL_SUGGEST_KEY", "1.0"))
W_BPM = float(os.environ.get("DJUTIL_SUGGEST_BPM", "1.0"))
W_HISTORY = float(os.environ.get("DJUTIL_SUGGEST_HISTORY", "0.5"))
W_GENRE = float(os.environ.get("DJUTIL_SUGGEST_GENRE", "0.2"))
W_RATING = float(os.environ.get("DJUTIL_SUGGEST_RATING", "0.1"))
W_RECENT = float(os.environ.get("DJUTIL_SUGGEST_RECENT", "0.3"))

RECENT_SETS = 3


def camelot_parse(key: str | None) -> tuple[int, str] | None:
    if not key:
        return None
    k = key.strip().upper()
    if len(k) < 2 or not k[:-1].isdigit():
        return None
    num = int(k[:-1])
    if not (1 <= num <= 12) or k[-1] not in "AB":
        return None
    return num, k[-1]


def key_score(a: tuple[int, str] | None, b: tuple[int, str] | None) -> float:
    if not a or not b:
        return 0.0
    na, la = a
    nb, lb = b
    if na == nb and la == lb:
        return 1.0
    diff = (nb - na) % 12
    if la == lb and diff in (1, 11):  # +-1 with wrap
        return 0.9
    if na == nb:  # relative major/minor
        return 0.85
    if la == lb and diff == 2:  # energy boost up
        return 0.6
    return 0.0


def key_reason(a: tuple[int, str], b: tuple[int, str]) -> str:
    label = f"{a[0]}{a[1]} → {b[0]}{b[1]}"
    if a == b:
        return f"{label} (same)"
    diff = (b[0] - a[0]) % 12
    if a[1] == b[1] and diff in (1, 11):
        return f"{label} ({'+' if diff == 1 else '-'}1)"
    if a[0] == b[0]:
        return f"{label} (relative)"
    if a[1] == b[1] and diff == 2:
        return f"{label} (+2 boost)"
    return label


def bpm_score(t: float | None, c: float | None) -> tuple[float, float, str]:
    """Score candidate BPM c vs target t, best of c, 2c, c/2.

    Returns (score, effective_c, label).
    """
    if not t or not c:
        return 0.0, c or 0.0, ""
    best = (0.0, c, "")
    for factor, tag in ((1.0, ""), (2.0, "2x"), (0.5, "½x")):
        ce = c * factor
        pct = abs(ce - t) / t
        score = max(0.0, 1.0 - (pct - 0.03) / 0.05) if pct > 0.03 else 1.0
        if score > best[0]:
            delta = (ce - t) / t * 100
            label = (
                f"{tag} {c:g} → {t:g}"
                if tag
                else f"{c:g} → {t:g} ({delta:+.1f}%)"
            )
            best = (score, ce, label)
    return best


def _neighbor_camelots(a: tuple[int, str]) -> list[str]:
    n, letter = a
    return [
        f"{n}{letter}",
        f"{(n % 12) + 1}{letter}",
        f"{((n - 2) % 12) + 1}{letter}",
        f"{((n + 1) % 12) + 1}{letter}",
        f"{n}{'B' if letter == 'A' else 'A'}",
    ]


def _track_summary(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "mix": row["mix"],
        "artist": row["artist"],
        "bpm": row["bpm"],
        "camelot": row["camelot"],
        "artwork_hash": row["artwork_hash"],
    }


def suggestions_for(
    conn: Connection,
    track_id: str,
    *,
    limit: int = 50,
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Ranked suggestions for now-playing ``track_id``."""
    t_row = conn.execute(
        text(
            "SELECT id, title, mix, artist, bpm, camelot, genre"
            " FROM tracks WHERE id = :id AND deleted = 0"
        ),
        {"id": track_id},
    ).mappings().first()
    if not t_row:
        return []
    t_key = camelot_parse(t_row["camelot"])
    t_bpm = t_row["bpm"]
    t_genre = (t_row["genre"] or "").lower()

    exclude = set(exclude_ids or set()) | {track_id}

    where = ["deleted = 0", "id != :tid"]
    params: dict[str, Any] = {"tid": track_id}
    parts = []
    if t_key:
        keys = ", ".join(f":k{i}" for i in range(5))
        for i, k in enumerate(_neighbor_camelots(t_key)):
            params[f"k{i}"] = k
        parts.append(f"camelot IN ({keys})")
    if t_bpm:
        lo, hi = t_bpm * 0.92, t_bpm * 1.08
        params.update(lo=lo, hi=hi, hlo=lo / 2, hhi=hi / 2,
                      dlo=lo * 2, dhi=hi * 2)
        parts.append(
            "(bpm BETWEEN :lo AND :hi OR bpm BETWEEN :hlo AND :hhi"
            " OR bpm BETWEEN :dlo AND :dhi)"
        )
    prefilter = ""
    if parts:
        prefilter = "(" + " AND ".join(parts) + ")"
    # Union in all tracks with a transition from T regardless of key/BPM.
    if prefilter:
        where.append(
            f"({prefilter} OR EXISTS (SELECT 1 FROM transitions x"
            " WHERE x.from_track_id = :tid AND x.to_track_id = tracks.id))"
        )

    rows = conn.execute(
        text(
            "SELECT id, title, mix, artist, bpm, camelot, genre, rating,"
            " artwork_hash FROM tracks WHERE " + " AND ".join(where)
        ),
        params,
    ).mappings().all()

    # transition stats T->C
    stats = {
        r["to_track_id"]: r
        for r in conn.execute(
            text(
                "SELECT to_track_id, count, fav_count, avg_rating"
                " FROM transition_stats WHERE from_track_id = :tid"
            ),
            {"tid": track_id},
        ).mappings().all()
    }
    # tracks played in the last 3 completed sets (excludes the active one)
    recent = {
        r[0]
        for r in conn.execute(
            text(
                "SELECT DISTINCT se.track_id FROM set_entries se"
                " WHERE se.set_id IN (SELECT id FROM sets"
                "  WHERE ended_at IS NOT NULL ORDER BY id DESC LIMIT :n)"
            ),
            {"n": RECENT_SETS},
        ).all()
    }

    out: list[dict[str, Any]] = []
    for r in rows:
        if r["id"] in exclude:
            continue
        c_key = camelot_parse(r["camelot"])
        ks = key_score(t_key, c_key)
        bs, _eff, bpm_label = bpm_score(t_bpm, r["bpm"])
        st = stats.get(r["id"])
        hist = 0.0
        if st:
            hist = (
                math.log(1 + (st["count"] or 0))
                + 2 * (st["fav_count"] or 0)
                + (st["avg_rating"] or 0)
            )
        genre_hit = bool(
            t_genre and r["genre"] and r["genre"].lower() == t_genre
        )
        rating_bonus = (r["rating"] or 0) / 5
        recent_penalty = W_RECENT if r["id"] in recent else 0.0

        score = (
            W_KEY * ks
            + W_BPM * bs
            + W_HISTORY * hist
            + W_GENRE * (1.0 if genre_hit else 0.0)
            + W_RATING * rating_bonus
            - recent_penalty
        )
        reasons = []
        if ks and t_key and c_key:
            reasons.append(
                {"kind": "key", "label": key_reason(t_key, c_key), "value": ks}
            )
        if bs:
            reasons.append({"kind": "bpm", "label": bpm_label, "value": bs})
        if st and st["count"]:
            label = f"played {st['count']}x"
            if st["fav_count"]:
                label += f" · ★{st['fav_count']}"
            if st["avg_rating"]:
                label += f" · avg {st['avg_rating']:.1f}"
            reasons.append(
                {"kind": "transition", "label": label, "value": hist}
            )
        if genre_hit:
            reasons.append(
                {"kind": "genre", "label": r["genre"], "value": 1.0}
            )
        if r["id"] in recent:
            reasons.append(
                {"kind": "recent", "label": "in a recent set", "value": -recent_penalty}
            )
        out.append(
            {"track": _track_summary(r), "score": round(score, 4), "reasons": reasons}
        )

    out.sort(key=lambda s: -float(s["score"]))
    return out[:limit]
