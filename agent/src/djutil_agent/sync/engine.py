"""Delta/full sync of the Rekordbox library to the DJUtil server."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path

from djutil_shared import ENTITIES, Track

from ..rekordbox.reader import RekordboxReader
from .client import SyncClient

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


class SyncEngine:
    def __init__(
        self,
        reader: RekordboxReader,
        client: SyncClient,
        share_dir: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.reader = reader
        self.client = client
        self.share_dir = share_dir
        self.state_file = state_file
        self._known_artwork: set[str] = set()
        self._fps: dict[str, dict[str, str]] | None = None

    # -- change fingerprint for entities without a usable usn ---------------

    def _load_fps(self) -> dict[str, str]:
        """Fingerprint map for the current server.

        Fingerprints are per-server ({server: {entity: fp}}) so pointing the
        agent at a fresh server never suppresses the first send.
        """
        if self._fps is None:
            import json

            self._fps = {}
            if self.state_file is not None and self.state_file.exists():
                try:
                    raw = json.loads(self.state_file.read_text())
                except (OSError, ValueError):
                    raw = {}
                if isinstance(raw, dict):
                    # Legacy flat format {entity: fp} counts as empty.
                    self._fps = {
                        k: v for k, v in raw.items() if isinstance(v, dict)
                    }
        return self._fps.setdefault(self.client.base_url, {})

    def _save_fps(self) -> None:
        if self.state_file is None or self._fps is None:
            return
        import json

        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self._fps))
        except OSError:
            logger.warning("could not write %s", self.state_file)

    @staticmethod
    def _fingerprint(upserts: Sequence[object], ids: list[str]) -> str:
        h = hashlib.sha256()
        for m in upserts:
            h.update(m.model_dump_json().encode())  # type: ignore[attr-defined]
            h.update(b"\x00")
        for i in sorted(ids):
            h.update(i.encode())
            h.update(b"\x00")
        return h.hexdigest()

    # -- artwork -----------------------------------------------------------

    def _prepare_track(self, track: Track) -> None:
        if not track.artwork_path or self.share_dir is None:
            return
        path = self.share_dir / track.artwork_path.lstrip("/\\")
        if not path.exists():
            # ImagePath may be relative to the share dir root already.
            alt = self.share_dir.parent / track.artwork_path.lstrip("/\\")
            path = alt if alt.exists() else path
        if not path.exists():
            return
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return
        track.artwork_hash = digest
        if digest in self._known_artwork:
            return
        if self.client.artwork_exists(digest):
            self._known_artwork.add(digest)
            return
        self.client.upload_artwork(digest, path.read_bytes())
        self._known_artwork.add(digest)

    # -- sync passes --------------------------------------------------------

    def run_delta(self, force: bool = False) -> dict[str, int]:
        """One delta pass over all entities. Returns per-entity sent counts.

        ``force`` bypasses the no-usn fingerprint skip so a full sync always
        re-sends entities that cannot be diffed by usn.
        """
        state = self.client.get_state()
        stats: dict[str, int] = {}
        for entity in ENTITIES:
            since = state.get(entity)
            if since is not None and not self.reader.has_usn(entity):
                since = None
            upserts, deletes, max_usn = self.reader.entity_delta(entity, since)
            if not upserts and not deletes:
                stats[entity] = 0
                continue

            # Some tables (e.g. djmdCue on RB7) have rb_local_usn present but
            # entirely NULL, so usn deltas are impossible. Fall back to sending
            # every live row and pruning by id-set — but only when the entity
            # content actually changed since the last send (fingerprint).
            no_usn = max_usn is None
            if no_usn:
                ids = self.reader.ids(entity)
                fp = self._fingerprint(upserts, ids)
                fps = self._load_fps()
                if not force and fps.get(entity) == fp:
                    stats[entity] = 0
                    continue
                for i in range(0, len(upserts), BATCH_SIZE):
                    chunk = upserts[i : i + BATCH_SIZE]
                    if entity == "tracks":
                        for t in chunk:
                            assert isinstance(t, Track)
                            self._prepare_track(t)
                    self.client.post_batch(
                        {
                            "entity": entity,
                            "upserts": [m.model_dump(mode="json") for m in chunk],
                            "deletes": [],
                            "max_usn": None,
                        }
                    )
                self.client.post_ids(entity, ids)
                fps[entity] = fp
                self._save_fps()
                stats[entity] = len(upserts) + len(deletes)
                continue

            # Upsert rows are usn-ordered; deletes go in a final batch whose
            # max_usn covers the deleted rows too.
            sent = 0
            for i in range(0, len(upserts), BATCH_SIZE):
                chunk = upserts[i : i + BATCH_SIZE]
                if entity == "tracks":
                    for t in chunk:
                        assert isinstance(t, Track)
                        self._prepare_track(t)
                usns = [
                    int(u)
                    for u in (getattr(m, "rb_local_usn", None) for m in chunk)
                    if u is not None
                ]
                self.client.post_batch(
                    {
                        "entity": entity,
                        "upserts": [m.model_dump(mode="json") for m in chunk],
                        "deletes": deletes if i + BATCH_SIZE >= len(upserts) else [],
                        "max_usn": max(
                            usns
                            + ([max_usn or 0] if i + BATCH_SIZE >= len(upserts) else []),
                            default=0,
                        )
                        or None,
                    }
                )
                sent += len(chunk)
            if not upserts and deletes:
                self.client.post_batch(
                    {
                        "entity": entity,
                        "upserts": [],
                        "deletes": deletes,
                        "max_usn": max_usn,
                    }
                )
            sent += len(deletes)
            stats[entity] = sent
        return stats

    def reconcile_ids(self) -> dict[str, int]:
        """Delete server rows that no longer exist in Rekordbox."""
        stats: dict[str, int] = {}
        for entity in ENTITIES:
            result = self.client.post_ids(entity, self.reader.ids(entity))
            stats[entity] = int(result.get("deleted", 0))
        return stats

    def run_full(self) -> dict[str, int]:
        """Delta from scratch (server state empty) + id-set reconcile."""
        stats = self.run_delta(force=True)
        pruned = self.reconcile_ids()
        for k, v in pruned.items():
            stats[k] = stats.get(k, 0) + v
        return stats

    def server_empty(self) -> bool:
        state = self.client.get_state()
        return all(v is None for v in state.values())
