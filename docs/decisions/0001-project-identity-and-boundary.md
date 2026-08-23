# Decision 0001: Project identity and repository boundary

- Status: architecture approved; Phase 1A authorized
- Project: `SEDB-RAL`
- English name: `SEDB Residency Attestation Layer`
- Chinese working name: `SEDB AI 居籍存證層`
- Remote: `https://github.com/kakon77777-commits/SEDB-RAL-SEDB-Residency-Attestation-Layer`
- Local checkout: `D:\Ai\work together\SEDB-RAL`
- Human authority: Neo
- Primary integrator claim: 織域
- Formal revision/dissent seat claim: Plumb（準繩）
- Temporal evidence: `ctcl:instant:ab1bdb6c-6ac7-4e73-8dd8-686652ac4264`
- Approval evidence: `ctcl:instant:cfdcb47e-ae65-48f6-8324-62bee44f1d84`

## Decision

Create SEDB-RAL as an independent sibling repository. Do not implement it
inside the existing SEDB repository or inside PMW Fabric/AI Residence.

SEDB-RAL owns:

- residency-profile schemas;
- append-only registry events;
- attestation and temporal-evidence contracts;
- deterministic projections and validators;
- admission and authority procedures;
- adapter interfaces.

It does not own:

- provider-native session state;
- message transport;
- AI Board or CTCL services;
- the SEDB core implementation;
- a human or AI legal-personhood determination.

## Alternatives rejected

1. **Module inside SEDB core.** Rejected because it would couple a domain
   profile to the generic sparse-field/governance substrate.
2. **Module inside PMW Fabric or AI Residence.** Rejected because transport,
   runtime residence, and registry identity have distinct authority and failure
   semantics.
3. **`SEDB-AR / Attested Residency Layer`.** Rejected because the past
   participle implies that every recorded residency has already been attested.
4. **`SEDB-REAL`.** Rejected because the acronym itself overstates truth.

## Attestation note

The identities above are claims on the current conversation surface. They are
not cryptographic proof of first-person authorship. The decision is authorized
by Neo's creation of the named remote repository and explicit instruction to
begin implementation.
