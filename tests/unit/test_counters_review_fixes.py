"""Regression tests for the 2026-08-29 PR-#3 review fixes.

Each test names the review issue it covers:

- Issue 3: one-snapshot rows+counts contract in ``summary()``.
- Issue 4: stale ``working`` status reconciled to idle at display time.
- Issue 5: heartbeat-sized starting grace (no offline flapping).
- Issue 6: gateway bucket sums to total; pid-less probe-live records kept.
- Issue 8: naive/garbage ``last_seen`` never crashes ``summary()``.
- Presence events: lifecycle hooks publish content-free events (issue 2).
- Probe cache (issue 8, cost half): TTL dedupe + repair stays uncached.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

import agent_peer.constants as C
from agent_peer.models import PeerRecord, Presence
from hermes_peer import sessions as S
from hermes_peer.sessions import PeerSessionManager


def _record(status=Presence.IDLE.value, surface="cli", last_seen=None,
            pid=12345, socket_path=""):
    """Build one registry record. ``last_seen`` is an ISO STRING (or None)."""
    now_iso = datetime.now(UTC).isoformat()
    return PeerRecord(
        peer_id=str(uuid.uuid4()),
        instance_id=str(uuid.uuid4()),
        session_id="x",
        name="me",
        profile="p",
        agent_id=str(uuid.uuid4()),
        surface=surface,
        pid=pid,
        cwd="/tmp",
        git_repo_root="",
        git_branch="",
        started_at=now_iso,
        last_seen=last_seen if last_seen is not None else now_iso,
        status=status,
        socket_path=socket_path,
    )


class _FakeDiscovery:
    def __init__(self, live=()):
        self._live = tuple(live)

    def list_live_peers(self, requesting_peer_id=None, requesting_peer_ids=None):
        return self._live


class _Reg:
    def __init__(self, records):
        self._records = list(records)

    def list_peers(self):
        return list(self._records)


def _mgr(registry_records, live_records, handles=None) -> PeerSessionManager:
    """Bare PeerSessionManager with fakes; no runtime/sockets needed."""
    m = object.__new__(PeerSessionManager)
    m._registry = _Reg(registry_records)
    m._discovery = _FakeDiscovery(live_records)
    m._peer_handles = handles if handles is not None else {}
    m._peers = {}
    m._ctx = None
    return m


# ---------------------------------------------------------------------------
# Issue 3: rows and counts come from one snapshot
# ---------------------------------------------------------------------------

class TestOneSnapshotContract:
    def test_rows_mirror_counts_exactly(self):
        recs = [_record(), _record(status=Presence.WORKING.value)]
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr(recs, recs).summary()
        live_ids = {r.peer_id for r in recs}
        assert out["total"] == len(out["peers"])
        # Buckets are exhaustive: live + gateway + offline == total.
        # (idle/working are sub-splits of live, not additive classes.)
        assert (out["live_count"] + out["gateway_count"]
                + out["offline_count"]) == out["total"]
        assert {p["peer_id"] for p in out["peers"]} == live_ids

    def test_every_peer_row_classified_into_exactly_one_bucket(self):
        recs = [
            _record(),                                # live + idle
            _record(status=Presence.WORKING.value),   # live + working
            _record(surface="gateway"),               # gateway
        ]
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr(recs, recs).summary()
        # Two interactive-live records (idle + working) + one automation peer.
        assert out["live_count"] == 2
        assert out["active_count"] == 1
        assert out["idle_count"] == 1
        assert out["gateway_count"] == 1
        assert out["offline_count"] == 0
        assert out["live_count"] + out["gateway_count"] + out["offline_count"] == out["total"]
        # working/idle are a partition of live.
        assert out["active_count"] + out["idle_count"] == out["live_count"]

    def test_offline_peer_still_has_a_row(self):
        # PID alive, probe dead, outside grace -> offline counter AND a row.
        stale_iso = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        r = _record(last_seen=stale_iso)
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], []).summary()
        assert out["offline_count"] == 1
        assert out["total"] == 1
        assert len(out["peers"]) == 1
        assert out["peers"][0]["offline"] is True
        assert out["peers"][0]["status_label"] == "offline"


# ---------------------------------------------------------------------------
# Issue 4: stale working reconciled at display time
# ---------------------------------------------------------------------------

class TestStaleWorkingReconciliation:
    def test_stale_working_shows_idle(self):
        from agent_peer.constants import STALE_THRESHOLD

        stale_iso = (datetime.now(UTC)
                     - timedelta(seconds=STALE_THRESHOLD + 60)).isoformat()
        r = _record(status=Presence.WORKING.value, last_seen=stale_iso)
        reg = _Reg([r])
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], [r]).summary()
        assert out["active_count"] == 0
        assert out["idle_count"] == 1
        # The stored record is never mutated (probe compares status exactly).
        assert reg.list_peers()[0].status == Presence.WORKING.value

    def test_fresh_working_counts_as_active(self):
        r = _record(status=Presence.WORKING.value)
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], [r]).summary()
        assert out["active_count"] == 1
        assert out["idle_count"] == 0


# ---------------------------------------------------------------------------
# Issue 5: grace window covers a heartbeat cycle
# ---------------------------------------------------------------------------

class TestGraceWindow:
    def test_grace_at_least_one_and_a_half_heartbeat(self):
        assert S._STARTING_GRACE_SECONDS >= C.HEARTBEAT_INTERVAL * 1.5

    def test_peer_between_heartbeats_not_offline(self):
        import datetime as _dt

        r = _record(last_seen=(datetime.now(UTC)
                               - timedelta(seconds=C.HEARTBEAT_INTERVAL * 1.2)).isoformat())
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], []).summary()
        # Inside the (raised) grace window + probe failed -> starting, never
        # offline. Flapping fixed.
        assert out["offline_count"] == 0


# ---------------------------------------------------------------------------
# Issue 6: gateway bucket + pid-less probe-live records
# ---------------------------------------------------------------------------

class TestGatewayAndPidless:
    def test_gateway_peer_counted_in_gateway_bucket(self):
        gw = _record(surface="gateway")
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([gw], [gw]).summary()
        assert out["total"] == 1
        assert out["gateway_count"] == 1
        assert out["live_count"] == 0
        assert out["offline_count"] == 0

    def test_pidless_probe_live_record_kept_in_total(self):
        r = _record(pid=0)
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], [r]).summary()
        assert out["total"] == 1
        assert out["live_count"] == 1

    def test_pidless_dead_probe_record_dropped(self):
        r = _record(pid=0, last_seen=(datetime.now(UTC) - timedelta(hours=1)).isoformat())
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], []).summary()
        # No PID, no probe -> not in the snapshot at all.
        assert out["total"] == 0


# ---------------------------------------------------------------------------
# Issue 8: naive/garbage last_seen never crashes the summary
# ---------------------------------------------------------------------------

class TestNaiveAndBrokenTimestamps:
    def test_naive_last_seen_does_not_crash(self):
        naive = datetime(2026, 8, 29, 12, 0, 0)  # no tzinfo -> TypeError path
        r = _record(last_seen=naive.isoformat())
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], [r]).summary()
        assert out["total"] == 1

    def test_garbage_last_seen_classifies_offline_not_crash(self):
        r = _record(last_seen="not-a-timestamp")
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([r], []).summary()
        # Unparseable age (age=None) -> not starting; probe failed -> offline.
        assert out["offline_count"] == 1

    def test_missing_last_seen_not_starting(self):
        r = _record(last_seen="")
        # Empty last_seen parses to None age -> never 'starting' (old code
        # treated missing as not-starting too; contract preserved).
        assert S._age_seconds(r) is None
        assert S._is_starting(r) is False


# ---------------------------------------------------------------------------
# Presence events (issue 2 backend half)
# ---------------------------------------------------------------------------

class TestPresenceEvents:
    def test_open_status_close_publish_events(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir(exist_ok=True)

        class Ctx:
            pass

        mgr = PeerSessionManager(ctx=Ctx(), runtime_root=tmp_path / "runtime")
        sid = mgr._events.subscribe()

        mgr.on_session_open("sess-1", platform="cli")
        mgr.on_session_end("sess-1", platform="cli")
        mgr.on_session_finalize("sess-1", platform="cli", reason="test")

        drained = mgr._events.drain(sid)
        kinds = [e["kind"] for e in drained]
        assert "peer_open" in kinds
        assert "peer_status" in kinds
        assert "peer_close" in kinds
        opened = next(e for e in drained if e["kind"] == "peer_open")
        assert opened["status"] == Presence.IDLE.value
        # Content-free: presence events never carry message payloads.
        for e in drained:
            assert "content" not in e

    def test_presence_publish_failure_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGENT_PEER_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
        (tmp_path / "home").mkdir(exist_ok=True)

        class Ctx:
            pass

        mgr = PeerSessionManager(ctx=Ctx(), runtime_root=tmp_path / "runtime")
        mgr.on_session_open("sess-2", platform="cli")
        with patch.object(mgr._events, "publish", side_effect=RuntimeError("boom")):
            # Must not raise even though the broker is broken.
            mgr.on_session_end("sess-2", platform="cli")
        mgr.shutdown()


# ---------------------------------------------------------------------------
# Probe cache (issue 8, cost half)
# ---------------------------------------------------------------------------

class TestProbeCache:
    def test_second_probe_within_ttl_uses_cache(self):
        from agent_peer.discovery import DiscoveryService

        r = _record(socket_path="/nonexistent/sock")
        calls = []

        def fake_probe_once(record, backend=None):
            calls.append(1)
            return {"nonce": "n"}

        svc = DiscoveryService.__new__(DiscoveryService)
        svc._backend = object()
        with patch("agent_peer.discovery._probe_once", fake_probe_once):
            first = svc._cached_probe(r)
            second = svc._cached_probe(r)
        assert first == second
        assert len(calls) == 1  # second read served from cache

    def test_cache_respects_ttl_expiry(self):
        from agent_peer.discovery import DiscoveryService

        r = _record(socket_path="/nonexistent/sock")
        calls = []

        def fake_probe_once(record, backend=None):
            calls.append(len(calls))
            return {"n": len(calls)}

        svc = DiscoveryService.__new__(DiscoveryService)
        svc._backend = object()
        svc._probe_cache = {}
        svc._probe_cache_lock = __import__("threading").Lock()
        svc._probe_cache_ttl = -1.0  # everything instantly expired
        with patch("agent_peer.discovery._probe_once", fake_probe_once):
            svc._cached_probe(r)
            svc._cached_probe(r)
        assert len(calls) == 2

    def test_repair_path_not_cached(self):
        # repair_stale's fenced remove must probe fresh — the source must not
        # route through the cache.
        import inspect

        from agent_peer.discovery import DiscoveryService

        src = inspect.getsource(DiscoveryService._fenced_remove)
        assert "_cached_probe" not in src