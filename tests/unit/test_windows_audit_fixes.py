"""Regression tests for the 2026-09-01 Windows audit fixes.

Each test names the audit finding it covers:

- C-1: PID-liveness probe never terminates the target on any platform.
- H-1: glyph degradation + _safe_print survive a cp1252 (non-UTF) stdout.
- M-2: grace-window sessions surface status_label "starting"; STATUS_GLYPH
  has an explicit starting entry.
- M-3: summary() last_updated is tz-aware over mixed-offset ISO strings.
- M-5: dashboard /peers/summary serves through a 2s TTL cache.
- H-2: discovery fenced cleanup is Windows-safe (no socket-stat gate on the
  named-pipe namespace; NG-07 bound-fence applies cross-platform).
- H-3: prune() contract documents the pid_liveness requirement.
"""

from __future__ import annotations

import inspect
import io
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from agent_peer.models import PeerRecord, Presence
from hermes_peer import commands as CM
from hermes_peer import sessions as S
from hermes_peer.sessions import PeerSessionManager


def _record(status=Presence.IDLE.value, surface="cli", last_seen=None,
            pid=1, socket_path="", peer_id=None):
    """Build one registry record. pid=1 is the POSIX-safe live PID (init)."""
    now_iso = datetime.now(UTC).isoformat()
    return PeerRecord(
        peer_id=peer_id or str(uuid.uuid4()),
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

    def get(self, peer_id):
        for r in self._records:
            if r.peer_id == peer_id:
                return r
        return None


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
# C-1: PID liveness never kills
# ---------------------------------------------------------------------------


class TestPidLiveness:
    def test_posix_probe_returns_true_for_live_pid(self):
        from agent_peer.pid_liveness import pid_alive

        assert pid_alive(1) is True

    def test_posix_probe_returns_false_for_dead_pid(self):
        from agent_peer.pid_liveness import pid_alive

        proc = subprocess.Popen(["sleep", "0"])
        pid = proc.pid
        proc.wait()
        assert pid_alive(pid) is False

    def test_windows_helper_is_query_only(self):
        # On a POSIX box the Windows branch must be importable and safe to
        # call — it reports not-alive (no ctypes.windll) instead of raising.
        from agent_peer.pid_liveness import _pid_alive_windows

        assert _pid_alive_windows(1) is False

    def test_sessions_wrapper_delegates(self):
        # The plugin seam must route through the new primitive, not os.kill.
        src = inspect.getsource(S._pid_alive)
        assert "pid_liveness" in src
        code = chr(10).join(
            line for line in src.splitlines()
            if not line.strip().startswith(("#", '"""', "'''"))
            and "historical" not in line
        )
        assert "os.kill(" not in code

    def test_summary_filters_by_liveness_without_killing(self):
        proc = subprocess.Popen(["sleep", "0"])
        pid = proc.pid
        proc.wait()
        rec_dead = _record(pid=pid)
        rec_none = _record(pid=None)
        out = _mgr([rec_dead, rec_none], []).summary()
        assert out["total"] == 0

    def test_summary_keeps_live_pid_record(self):
        rec = _record(pid=1)
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([rec], []).summary()
        assert out["total"] == 1

    def test_pid_alive_rejects_junk(self):
        from agent_peer.pid_liveness import pid_alive

        assert pid_alive(0) is False
        assert pid_alive(-5) is False
        assert pid_alive(None) is False

    def test_repo_has_no_bare_os_kill_in_plugin_code(self):
        # Class-level guard: the kill-by-accident primitive must not come
        # back. AST-based so docstrings that DOCUMENT the footgun do not
        # trip it. agent_peer/pid_liveness.py is the single sanctioned home
        # of os.kill (POSIX branch) and is excluded.
        import ast
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[2]
        targets = list((repo / "hermes_peer").glob("*.py"))
        targets += [p for p in (repo / "agent_peer").glob("*.py")]
        offenders: list[str] = []
        for path in targets:
            if path.name == "pid_liveness.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "kill"
                ):
                    offenders.append(f"{path.relative_to(repo)}:{node.lineno}")
        assert offenders == []


# ---------------------------------------------------------------------------
# H-1: glyph degradation + safe print
# ---------------------------------------------------------------------------


class _Cp1252Out(io.TextIOWrapper):
    pass


def _swap_stdout_cp1252():
    fake = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    import sys

    old = sys.stdout
    sys.stdout = fake
    return fake, old


class TestGlyphDegradation:
    def test_g_degrades_on_cp1252_stdout(self):
        # Chars genuinely absent from cp1252 must degrade.
        fake, old = _swap_stdout_cp1252()
        try:
            assert CM._g("●") == "*"
            assert CM._g("○") == "o"
            assert CM._g("▸") == ">"
            # Degradation contract: EVERY glyph that reaches stdout must be
            # encodable in the active encoding, whatever the fallback is.
            # (cp1252 legitimately contains ×, ·, — and … (0x85), so those
            # may pass through unchanged; only ● ○ ▸ degrade on cp1252.)
            for ch in ("●", "○", "×", "▸", "·", "—", "…"):
                CM._g(ch).encode("cp1252")  # must never raise
        finally:
            import sys

            sys.stdout = old
            fake.close()

    def test_g_keeps_glyph_on_utf8_stdout(self):
        assert CM._g("●") == "●"

    def test_safe_print_survives_unencodable_content(self, capsys):
        fake, old = _swap_stdout_cp1252()
        try:
            CM._safe_print("peer ● working")
        finally:
            import sys

            sys.stdout = old
            fake.close()

    def test_plain_listing_uses_degraded_glyphs_on_cp1252(self):
        rec = _record(pid=1)
        fake, old = _swap_stdout_cp1252()
        try:
            with patch.object(S, "_pid_alive", lambda p: True), patch.object(
                CM, "get_manager", return_value=_mgr([rec], [rec])
            ):
                out = CM._cmd_peers_plain()
        finally:
            import sys

            sys.stdout = old
            fake.close()
        assert out  # rendered
        # ● and ○ have no cp1252 codepoint: they must be degraded. × is a
        # cp1252 native and may pass through.
        assert "●" not in out and "○" not in out and "▸" not in out
        assert "*" in out

    def test_cli_list_smoke_without_manager(self):
        with patch.object(CM, "get_manager", return_value=None):
            assert CM._cmd_peers_plain() == "hermes-peer is not active in this process."


# ---------------------------------------------------------------------------
# M-2: starting label/glyph
# ---------------------------------------------------------------------------


class TestStartingLabel:
    def test_status_glyph_has_starting_entry(self):
        assert CM.STATUS_GLYPH.get("starting") == "·"

    def test_grace_window_record_gets_starting_label(self):
        # PID-alive (patched), probe NOT answered, inside the grace window ->
        # status_label must be "starting", never "offline".
        fresh = _record(last_seen=datetime.now(UTC).isoformat())
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([fresh], []).summary()
        row = out["peers"][0]
        assert row["status_label"] == "starting"
        assert row["offline"] is False
        assert out["total"] == 1
        assert out["offline_count"] == 0

    def test_stale_record_beyond_grace_is_offline(self):
        old_seen = (datetime.now(UTC) - timedelta(seconds=600)).isoformat()
        rec = _record(last_seen=old_seen)
        with patch.object(S, "_pid_alive", lambda p: True):
            out = _mgr([rec], []).summary()
        assert out["peers"][0]["status_label"] == "offline"
        assert out["offline_count"] == 1


# ---------------------------------------------------------------------------
# M-3: tz-aware last_updated
# ---------------------------------------------------------------------------


class TestLastUpdatedTzAware:
    def test_mixed_offset_timestamps_pick_newest_instant(self):
        now = datetime.now(UTC)
        # "Z" form sorts lexicographically LAST but is an HOUR older.
        stale_z = (now - timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ")
        fresh_offset = (now - timedelta(seconds=10)).isoformat()
        rec_stale = _record(last_seen=stale_z)
        rec_fresh = _record(last_seen=fresh_offset)
        out = _mgr([rec_stale, rec_fresh], []).summary()
        assert out["last_updated"] == fresh_offset

    def test_unparseable_last_seen_never_breaks_summary(self):
        rec = _record(last_seen="not-a-timestamp")
        out = _mgr([rec], []).summary()  # must not raise
        assert out["total"] == 1
        assert out["last_updated"] in ("", None)


# ---------------------------------------------------------------------------
# M-5: dashboard /peers/summary TTL cache
# ---------------------------------------------------------------------------


class TestDashboardSummaryCache:
    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import dashboard.plugin_api as api

        app = FastAPI()
        app.include_router(api.router, prefix="/api/plugins/hermes-peer")
        # Isolate module cache between tests.
        api._summary_cache["at"] = 0.0
        api._summary_cache["value"] = None
        return TestClient(app), api

    def test_summary_served_from_cache_within_ttl(self):
        client, api = self._client()
        calls = {"n": 0}

        class _M:
            def summary(self):
                calls["n"] += 1
                return {"total": 2, "live_count": 2}

        with patch.object(api, "_manager", return_value=_M()):
            r1 = client.get("/api/plugins/hermes-peer/peers/summary")
            r2 = client.get("/api/plugins/hermes-peer/peers/summary")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert calls["n"] == 1  # second GET hit the TTL cache

    def test_cache_respects_ttl_expiry(self):
        client, api = self._client()
        calls = {"n": 0}

        class _M:
            def summary(self):
                calls["n"] += 1
                return {"total": 2, "live_count": 2}

        with patch.object(api, "_manager", return_value=_M()):
            client.get("/api/plugins/hermes-peer/peers/summary")
            api._summary_cache["at"] -= 10.0  # age past the TTL
            client.get("/api/plugins/hermes-peer/peers/summary")
        assert calls["n"] == 2


# ---------------------------------------------------------------------------
# H-2: fenced cleanup is Windows-safe
# ---------------------------------------------------------------------------


class _Backend:
    """Stub transport backend: bound() verdict set per test."""

    def __init__(self, bound=False):
        self._bound = bound

    def bound(self, endpoint, *, timeout):
        return self._bound


def _svc(tmp_path, records, bound=False):
    from agent_peer.discovery import DiscoveryService
    from agent_peer.paths import RuntimePaths

    paths = RuntimePaths(root=tmp_path / ".agent-peer")
    paths.root.mkdir(parents=True, exist_ok=True)
    svc = object.__new__(DiscoveryService)
    svc._paths = paths
    svc._registry = _Reg(records)
    svc._backend = _Backend(bound=bound)
    return svc


def _write_registry(paths, record) -> None:
    import json as _json

    reg_path = paths.registry_file_for(record.peer_id)
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    reg_path.write_text(_json.dumps({"peer_id": record.peer_id}), encoding="utf-8")
    return reg_path


_FAKE_PEER = "12345678-1234-5678-1234-567812345678"


class TestFencedRemove:
    def test_windows_mode_cleans_stale_record_without_socket_fs(self, tmp_path):
        # Windows simulation (POSIX host): no filesystem node for the pipe
        # path. On Windows the socket-stat fence is skipped entirely and the
        # registry-level fences still run to removal.
        from agent_peer import discovery as D

        rec = _record(peer_id=_FAKE_PEER, socket_path=str(tmp_path / "pipe-x"))
        svc = _svc(tmp_path, [rec])
        reg_path = svc._paths.registry_file_for(_FAKE_PEER)
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text("{}", encoding="utf-8")

        removed: list = []
        with patch.object(D, "_POSIX_TRANSPORT", False), patch.object(
            D.DiscoveryService, "_probe", lambda self, r: False
        ):
            svc._fenced_remove(rec, removed)
        assert removed == [rec]
        assert not reg_path.exists()

    def test_windows_mode_refuses_when_listener_alive(self, tmp_path):
        # NG-07: a live listener at the (pipe) address blocks cleanup even
        # though the record's probe fails — now enforced cross-platform.
        from agent_peer import discovery as D

        rec = _record(peer_id=_FAKE_PEER, socket_path=str(tmp_path / "pipe-x"))
        svc = _svc(tmp_path, [rec], bound=True)
        reg_path = svc._paths.registry_file_for(_FAKE_PEER)
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text("{}", encoding="utf-8")

        removed: list = []
        with patch.object(D, "_POSIX_TRANSPORT", False), patch.object(
            D.DiscoveryService, "_probe", lambda self, r: False
        ):
            svc._fenced_remove(rec, removed)
        assert removed == []
        assert reg_path.exists()

    def test_posix_mode_still_unlinks_socket_file(self, tmp_path):
        from agent_peer import discovery as D

        sock = tmp_path / "a.sock"
        sock.write_bytes(b"")  # socket-shaped placeholder
        rec = _record(peer_id=_FAKE_PEER, socket_path=str(sock))
        svc = _svc(tmp_path, [rec])
        reg_path = _write_registry(svc._paths, rec)

        removed: list = []
        with patch.object(D, "_POSIX_TRANSPORT", True), patch.object(
            D.DiscoveryService, "_probe", lambda self, r: False
        ):
            svc._fenced_remove(rec, removed)
        assert removed == [rec]
        assert not reg_path.exists()
        assert not sock.exists()


# ---------------------------------------------------------------------------
# H-3: prune contract
# ---------------------------------------------------------------------------


def test_prune_contract_documents_pid_liveness():
    from agent_peer.registry import Registry

    doc = Registry.prune.__doc__ or ""
    assert "pid_liveness" in doc
