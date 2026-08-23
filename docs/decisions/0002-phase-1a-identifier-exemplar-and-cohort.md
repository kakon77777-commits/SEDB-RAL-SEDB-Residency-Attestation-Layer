# Decision 0002: Identifier exemplar and claimed cohort contract

**Status:** Accepted for the unreleased Phase 1A contract  
**Date:** 2026-08-23  
**Review anchor:** `ctcl:instant:339f553d-11b6-4c60-9168-cd14419087ab`

## Context

The first identifier-discrimination fixture embedded a property named
`identifier`, while the gate actually evaluated a population of observations
for an identifier kind. The observations were not bound to the embedded
namespace, kind, or exemplar value. The gate also counted residents and
instances globally without requiring a same-runtime cohort or a consistent
instance-to-resident topology.

Those omissions allowed two false admissions:

- a runtime-dependent value could appear resident-unique when each resident
  was sampled in a different runtime;
- one `instance_ref` could claim two residents while still satisfying the
  numeric instance threshold.

## Decision

Phase 1A keeps one identifier-field schema but names the nested fixture object
`identifier_exemplar`. It is a sample of the identifier kind being tested, not
an admitted registry instance.

Every observation must carry the exemplar's `namespace` and
`identifier_kind`; the exemplar value must appear in the observation set.
Observation IDs must be unique. Within one fixture, an `instance_ref` binds to
exactly one claimed resident and one claimed runtime.

Conclusive contradictions are evaluated before sufficiency:

- instability within a resident rejects;
- a value shared across residents rejects.

Admission then requires at least one claimed runtime cohort containing two or
more residents, with each admitted cohort resident represented by the declared
minimum number of distinct instances.

We do not split identifier-kind declarations and identifier instances into two
schemas in Phase 1A. No Phase 1A consumer registers the exemplar as a canonical
identifier, and splitting now would enlarge the deliberately narrow slice. A
future split requires an explicit contract version; it must not silently change
the meaning of `identifier_exemplar`.

## Evidence boundary

The cohort topology remains applicant-claimed. In particular, `runtime_ref` is
not receiver-observed identity evidence. An admit result therefore means:

> The value discriminated the claimed residents under the claimed runtime
> grouping in this fixture.

It does not mean that the registry independently proved the residents,
instances, runtimes, or their relationships.

## Consequences

- Pre-release fixtures using the old `identifier` property are invalid.
- Cross-runtime-only populations cannot support admission.
- Shared values and unstable values are not downgraded to indeterminate merely
  because the positive-admission sample threshold is incomplete.
- Later authority logic must still attest the claimed topology independently.
