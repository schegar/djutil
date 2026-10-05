"""Fader-aware now-playing decision (pure; reused by `decks watch` and,
later, the live forwarder).

A deck is *audible* while it is playing and its channel fader is up
(*confirmed*), or while it is playing with the fader unreadable
(*assumed*).  Now-playing is the audible deck with the most recent
audible start that has stayed audible for at least ``min_audible_s`` —
but a merely assumed deck never wins while a confirmed deck is audible:
a track playing with its fader down on an unmapped channel must not
steal now-playing from the deck that is verifiably up.  Failing any
qualified pick, the previous pick survives while still audible.
"""

from __future__ import annotations

from dataclasses import dataclass

FADER_MIN = 0.05


@dataclass
class DeckSample:
    """One polling sample of a deck."""

    cid: str | None      # identity of the loaded track (None = unloaded)
    title: str
    playing: bool        # same track as last sample AND position advanced
    fader: float | None  # channel fader 0..1 (None = unknown)


@dataclass
class NowPlayingEvent:
    deck: int
    cid: str
    title: str
    audible_since: float  # monotonic ts the deck became audible (mix-in)
    wall_since: float     # wall-clock ts of the same instant


def is_playing(
    prev_key: str | None,
    prev_pos: int | None,
    key: str | None,
    pos: int | None,
) -> bool:
    """Playing iff the loaded track is unchanged and the sample count
    strictly advanced since the previous sample."""
    return (
        key is not None
        and key == prev_key
        and pos is not None
        and prev_pos is not None
        and pos > prev_pos
    )


class NowPlayingTracker:
    """Stateful tracker; call ``update`` once per poll.

    ``gap_grace_s`` absorbs brief non-audible gaps (pause/resume, a
    backwards scratch, a loop jump, a failed read): the deck's entry -
    and its ``audible_since`` - survives while the gap is within the
    grace and the content id is unchanged.  ``_key`` is never cleared on
    an empty pick, so the same audible period can never re-emit.
    """

    def __init__(
        self, min_audible_s: float = 5.0, gap_grace_s: float = 3.0
    ) -> None:
        self.min_audible_s = min_audible_s
        self.gap_grace_s = gap_grace_s
        # per deck: (cid, audible_since, gap_start, confirmed)
        # gap_start is the first non-audible ts of the current gap
        # (None while the deck is audible at the latest sample);
        # confirmed records whether audibility last rested on a known-up
        # fader (False = fader unreadable, audibility assumed)
        self._aud: dict[int, tuple[str, float, float | None, bool]] = {}
        self._key: tuple[int, str, float] | None = None

    def update(
        self,
        now: float,
        wall_now: float,
        decks: list[DeckSample],
    ) -> NowPlayingEvent | None:
        """Returns an event when the now-playing pick changes, else None."""
        for i, d in enumerate(decks):
            playing = d.playing and d.cid is not None
            confirmed = (
                playing and d.fader is not None and d.fader > FADER_MIN
            )
            audible = confirmed or (playing and d.fader is None)
            cur = self._aud.get(i)
            cid_changed = (
                cur is not None and d.cid is not None and d.cid != cur[0]
            )
            if cid_changed:
                cur = None
            if audible:
                assert d.cid is not None
                if cur is not None and (
                    cur[2] is None or now - cur[2] <= self.gap_grace_s
                ):
                    # continuous, or resumed inside the grace window
                    self._aud[i] = (cur[0], cur[1], None, confirmed)
                else:
                    self._aud[i] = (d.cid, now, None, confirmed)
            elif cur is not None:
                gap = cur[2] if cur[2] is not None else now
                if now - gap > self.gap_grace_s:
                    self._aud.pop(i, None)
                else:
                    self._aud[i] = (cur[0], cur[1], gap, cur[3])

        # confirmed (fader known up) beats assumed (fader unreadable)
        pick: int | None = None
        pick_since = -1.0
        for tier in (True, False):
            for i, (_cid, since, _gap, conf) in self._aud.items():
                if (
                    conf == tier
                    and now - since >= self.min_audible_s
                    and since > pick_since
                ):
                    pick, pick_since = i, since
            if pick is not None:
                break
        if pick is None and self._key is not None:
            prev_deck = self._key[0]
            entry = self._aud.get(prev_deck)
            if entry is not None and entry[:2] == self._key[1:]:
                pick = prev_deck
        if pick is None:
            return None
        cid, since, _gap, _conf = self._aud[pick]
        key = (pick, cid, since)
        if key == self._key:
            return None
        self._key = key
        return NowPlayingEvent(
            deck=pick,
            cid=cid,
            title=decks[pick].title,
            audible_since=since,
            wall_since=wall_now - (now - since),
        )
