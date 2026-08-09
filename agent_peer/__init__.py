"""agent_peer — harness-neutral peer messaging core.

Zero runtime dependencies. No Hermes imports anywhere in this package
(enforced by a structural test in P7). The wire protocol is ``agent-peer/1``
(see :mod:`agent_peer.codec` and ``docs/protocol.md``).
"""

from __future__ import annotations

__version__ = "0.1.0rc1"
PROTOCOL_NAME = "agent-peer"
PROTOCOL_VERSION = 1
PROTOCOL_ID = f"{PROTOCOL_NAME}/{PROTOCOL_VERSION}"

__all__ = ["PROTOCOL_ID", "PROTOCOL_NAME", "PROTOCOL_VERSION", "__version__"]
