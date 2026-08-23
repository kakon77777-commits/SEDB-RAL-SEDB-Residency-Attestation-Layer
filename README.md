# SEDB-RAL

**SEDB Residency Attestation Layer**<br>
**SEDB AI 居籍存證層**

SEDB-RAL is a federated, file-first profile for recording AI residents, runtime
instances, continuity lines, identifiers, addresses, claims, observations,
attestations, authority, and delivery state without collapsing those concepts
into one overloaded identity field.

The project is currently in the **architecture-review stage**. It does not yet
provide a runtime, registrar, transport, or authoritative routing directory.

## Core boundary

```text
Claim != Observation
Observation != Proof
Line != Instance
Role != Resident
Runtime Tag != Address
Transport Accepted != Delivered
Capability != Authority
Decision != Commit
Wall-clock Time != Causal Order
```

The initial design is in
[`docs/superpowers/specs/2026-08-23-sedb-ral-core-design.md`](docs/superpowers/specs/2026-08-23-sedb-ral-core-design.md).

## Repository relationship

SEDB-RAL is a sibling of SEDB, not a replacement for it. SEDB supplies the
governance and sparse-field concepts; SEDB-RAL defines the residency and
attestation profile. EveMissLab PMW Fabric, Claude Code session messaging,
Codex queue, AI Board, and future transports remain external adapters.

## Current evidence boundary

- No existing SEDB, AI Residence, or PMW Fabric files are modified by this
  repository.
- External archives and handoffs are design evidence until explicitly adopted.
- CTCL receipts are stored as temporal evidence; a timestamp string by itself
  is not treated as a verified clock observation.
- No license has been selected yet. Repository visibility does not imply a
  reuse license.
