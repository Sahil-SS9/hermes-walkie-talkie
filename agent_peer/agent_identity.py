"""Long-lived agent identity (P3.2, G2.3, ADR-0004).

The Hermes adapter persists its stable ``agent_id`` inside the profile's
``HERMES_HOME`` as an owner-only file. The id is a UUID minted once and
reused across session rotation; it is NEVER inferred from mutable alias,
profile name or filesystem path text (G2.3, G3.3).
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from .errors import ConfigurationError
from .paths import same_owner

logger = logging.getLogger("agent_peer.agent_identity")

_AGENT_ID_FILE = "agent_id"  # inside HERMES_HOME/agent-peer/


def load_or_create_agent_id(hermes_home: Path) -> str:
    """Load the stable agent_id from *hermes_home*, creating it if absent.

    The file lives at ``<HERMES_HOME>/agent-peer/agent_id`` and is created
    owner-only (0600) inside an owner-only (0700) directory. A symlinked or
    wrong-owner file is refused — identity must not be readable by others.
    """
    home = Path(hermes_home)
    if home.is_symlink():
        raise ConfigurationError(f"HERMES_HOME must not be a symlink: {home}")
    identity_dir = home / "agent-peer"
    try:
        identity_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(identity_dir, 0o700)
    except OSError as exc:
        raise ConfigurationError(f"cannot create identity dir {identity_dir}: {exc}") from exc
    path = identity_dir / _AGENT_ID_FILE
    if path.is_symlink():
        raise ConfigurationError(f"agent identity file must not be a symlink: {path}")
    try:
        st = path.stat()
        if not same_owner(st) or (st.st_mode & 0o077):
            raise ConfigurationError(
                f"agent identity file must be owner-only: {path}"
            )
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        value = ""
    except OSError as exc:
        raise ConfigurationError(f"cannot read agent identity {path}: {exc}") from exc
    if value:
        try:
            # Validate the stored value is a real UUID before trusting it.
            # A corrupt value is treated as absent and refreshed below.
            return str(uuid.UUID(value))
        except ValueError:
            logger.warning("agent identity file corrupt; refreshing %s", path)

    # Mint a fresh identity and persist it owner-only.
    fresh = str(uuid.uuid4())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, fresh.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return fresh


def read_agent_id(hermes_home: Path) -> str:
    """Read the existing agent_id without creating; '' when absent."""
    path = Path(hermes_home) / "agent-peer" / _AGENT_ID_FILE
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


__all__ = ["load_or_create_agent_id", "read_agent_id"]
