"""Agent Peer error hierarchy.

Every failure the core can raise derives from :class:`AgentPeerError`, so
transport and host layers can catch one base class without swallowing
unrelated exceptions.
"""

from __future__ import annotations


class AgentPeerError(Exception):
    """Base class for all Agent Peer errors."""


class ValidationError(AgentPeerError, ValueError):
    """A model, envelope or configuration value failed validation."""


class ProtocolError(AgentPeerError):
    """A wire-format or protocol-version error."""


class UnsupportedVersionError(ProtocolError):
    """An envelope declared an unsupported protocol version (major mismatch)."""


class FrameError(ProtocolError):
    """A framing error: bad length prefix, oversize, invalid UTF-8 or JSON."""


class OversizedError(FrameError):
    """A frame or payload exceeded the hard ceiling."""


class ExpiredError(ValidationError):
    """An envelope expired before delivery."""


class TransportError(AgentPeerError):
    """A socket/transport-level failure."""


class UnreachableError(TransportError):
    """The target peer could not be reached."""


class TimeoutError_(TransportError, TimeoutError):
    """A connect or receipt wait exceeded its bound."""


class PolicyError(AgentPeerError):
    """A receiver policy rejected the message."""


class RateLimitedError(PolicyError):
    """The sender exceeded the rate limit for the recipient."""


class OverCapacityError(PolicyError):
    """The recipient's pending inbox is full."""


class ConfigurationError(ValidationError):
    """Invalid configuration values (limits, policy, paths)."""


class StoreError(AgentPeerError):
    """Persistent-store failure (disk-full, read-only, corruption)."""
