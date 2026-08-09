# Changelog

All notable changes to Hermes Walkie Talkie are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Initial v1 implementation of the Agent Peer core (`agent_peer`): peer
  identity, owner-local registry and presence, Unix-socket transport with a
  per-process selector supervisor, envelope v1 codec (`agent-peer/1`),
  persistent store, inbound policies (accept/hold/refuse), receipts,
  deduplication, rate/capacity limits and TTL handling.
- Initial Hermes adapter (`hermes_peer`): lifecycle hooks, config loader,
  tools (`peer_list_agents`, `peer_send_message`, `peer_read_inbox`),
  slash commands (`/peers`, `/peer-name`, `/peer-policy`, `/peer-inbox`),
  `hermes peer ...` CLI and bundled `peer-messaging` skill.
- Generic Hermes delivery seam (upstream candidate): additive
  `ctx.inject_message(..., mode=..., target_session=...)` with host-owned
  routing on CLI, TUI/dashboard and gateway surfaces.
- Documentation: architecture, protocol v1, security model, troubleshooting,
  ADRs, compatibility matrix and independent-review packet.

### Notes

- Linux is the release-blocking platform for v1. macOS CI is configured but
  its execution is deferred to post-goal approved remote CI. Windows is out
  of scope.
- This is an unreleased local review candidate (`v0.1.0-rc1`); no Git tag,
  package publication or live activation has occurred.
