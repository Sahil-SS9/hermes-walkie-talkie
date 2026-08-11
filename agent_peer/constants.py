"""Protocol and policy constants (ADR-0003 §4.4).

All limits are configurable within these safe hard ceilings; invalid values
fail configuration validation at the policy layer.
"""

from __future__ import annotations

# Wire protocol
PROTOCOL_NAME = "agent-peer"
PROTOCOL_VERSION = 1
PROTOCOL_ID = f"{PROTOCOL_NAME}/{PROTOCOL_VERSION}"
# V2: stable agent identity, capability advertisement, groups, workflows.
PROTOCOL_VERSION_2 = 2
PROTOCOL_ID_V2 = f"{PROTOCOL_NAME}/{PROTOCOL_VERSION_2}"
SUPPORTED_PROTOCOLS = (PROTOCOL_ID, PROTOCOL_ID_V2)

# Hard ceilings (bytes)
MAX_CONTENT_BYTES = 32 * 1024          # 32 KiB UTF-8 content ceiling
MAX_FRAME_BYTES = 64 * 1024            # 64 KiB full framed envelope ceiling
FRAME_LENGTH_PREFIX_BYTES = 4          # big-endian uint32

# Time defaults (seconds)
DEFAULT_MESSAGE_TTL = 300              # 5 minutes
CONNECT_TIMEOUT = 1.0
RECEIPT_TIMEOUT = 3.0
HEARTBEAT_INTERVAL = 15.0
STALE_THRESHOLD = 45.0                 # followed by a socket handshake

# Hop/loop protection
MAX_HOP_COUNT = 4

# Rate limiting (per sender/recipient pair)
RATE_BURST = 5
RATE_SUSTAINED = 20                     # messages per minute
RATE_WINDOW_SECONDS = 60.0

# Capacity
INBOX_CAPACITY = 100                    # pending messages per peer

# Policy
DEFAULT_INBOUND_POLICY = "accept"       # accept | hold | refuse
