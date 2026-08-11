"""Protocol/capability advertisement and negotiation (P3.3, ADR-0004).

Negotiation picks the highest mutual protocol version. A peer that cannot
perform a group/workflow operation returns ``incompatible`` — never a
free-text fallback.
"""

from __future__ import annotations

from .constants import PROTOCOL_ID, PROTOCOL_ID_V2, SUPPORTED_PROTOCOLS


def highest_mutual_protocol(advertised: tuple[str, ...] | list[str] | None) -> str:
    """Highest protocol version mutually supported.

    Missing/empty advertisement (V1 peers) resolves to ``agent-peer/1``.
    Returns ``agent-peer/1`` when no mutual version exists (fail closed to
    the oldest interoperable wire, not a fake V2 claim).
    """
    theirs = set(advertised or ())
    if not theirs:
        theirs = {PROTOCOL_ID}
    mutual = set(SUPPORTED_PROTOCOLS) & theirs
    if not mutual:
        return PROTOCOL_ID  # fail closed: V1 wire, then incompatible at op level
    return PROTOCOL_ID_V2 if PROTOCOL_ID_V2 in mutual else PROTOCOL_ID


def supports_v2(advertised: tuple[str, ...] | list[str] | None) -> bool:
    return PROTOCOL_ID_V2 in set(advertised or ())


def capability_flag(record_capabilities: dict | None, flag: str) -> bool:
    """True when a peer advertises *flag* (unknown flags fail closed)."""
    return bool(record_capabilities and record_capabilities.get(flag) is True)


__all__ = ["capability_flag", "highest_mutual_protocol", "supports_v2"]
