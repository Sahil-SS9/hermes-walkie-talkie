"""Host-open lifecycle shim for real-process e2e drivers (2026-09-29 compat audit).

The KENSEI fork exposes ``hermes_cli.plugins.notify_session_open`` (its custom
``on_session_open`` host seam, REM-304/306). Stock upstream main removed that
helper — see the compat audit: the ``on_session_open`` plugin hook is not in
upstream ``VALID_HOOKS`` (register warns and stores; nothing dispatches it),
and the plugin's own legacy ``on_session_start`` fallback (sessions.py) is the
supported registration path on stock hosts.

Drivers import this shim instead of the fork-only helper so the real-process
e2e suite runs against both host generations:

1. fork host: call ``notify_session_open`` directly (exact old behaviour);
2. stock host: call ``hermes_cli.lifecycle.invoke_hook("on_session_open", ...)
   which dispatches the plugin-registered callback on hosts that know the hook
   and is harmless on stock upstream (stored-but-undispatched) — either way
   the AIAgent's first-turn ``on_session_start`` dispatch (agent/
   conversation_loop.py) registers the peer through the plugin's legacy
   fallback, which is what these e2e tests actually assert downstream.

Lives under tests/e2e/ (not hermes_peer/) because the HP-710 adapter
boundary test bans hermes_cli imports inside the adapter package.
"""

from __future__ import annotations

import logging


def notify_session_open_compat(session_id: str, platform: str | None = None) -> bool:
    """Fire the host-open lifecycle on fork and stock hosts; fail closed."""
    log = logging.getLogger("hermes_peer.e2e")
    session_id = str(session_id or "").strip()
    if not session_id:
        log.warning("notify_session_open_compat: empty session id; refusing")
        return False

    try:
        from hermes_cli import plugins as _plugins
    except Exception as exc:
        log.warning("notify_session_open_compat: hermes_cli.plugins import failed: %s", exc)
        return False

    notify = getattr(_plugins, "notify_session_open", None)
    if callable(notify):
        try:
            return bool(notify(session_id, platform))
        except Exception as exc:
            log.warning("notify_session_open raised: %s", exc)
            return False

    try:
        from hermes_cli.lifecycle import invoke_hook
    except Exception as exc:
        log.warning("hermes_cli.lifecycle import failed: %s", exc)
        return False
    try:
        invoke_hook("on_session_open", session_id=session_id, platform=platform)
        return True
    except Exception as exc:
        log.warning("on_session_open invoke_hook failed: %s", exc)
        return False
