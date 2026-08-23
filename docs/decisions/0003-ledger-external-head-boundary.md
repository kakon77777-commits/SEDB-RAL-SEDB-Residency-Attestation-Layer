# Decision 0003: Ledger validity requires an externally retained head

**Status:** Accepted for the unreleased Phase 1A contract

**Date:** 2026-08-23

**Review anchor:** `ctcl:instant:bfc7939d-d10b-453c-94bc-0028316407b5`

## Context

A local hash chain detects mutation, gaps, and unmatched event/anchor deletion.
It cannot detect deletion of a matched tail pair or deletion of the entire
ledger: the remaining local bytes form a shorter internally consistent chain.
Calling that state simply `valid=true` confuses absence of contradiction with
proof of completeness.

## Decision

Ledger verification reports one of four states:

```text
empty
internally_consistent
checkpoint_verified
invalid
```

`valid` is true only for `checkpoint_verified`. The caller supplies an
independently retained expected final chain digest. A non-empty chain without
that checkpoint remains `internally_consistent`; an empty directory remains
`empty`.

Appending also requires an explicit previous-head declaration. `null` declares
genesis. A non-empty ledger cannot be appended under a genesis declaration, and
an expected previous head that does not match the local chain fails closed.

## Evidence boundary

The implementation verifies a supplied checkpoint; it does not create an
external authority for that checkpoint. Its strength depends on where and how
the caller retained it. A CTCL registered instant is not automatically a signed
chain checkpoint because the current CTCL signature covers only
`instant_id|unix_ns|timescale`, not arbitrary metadata containing a digest.

## Consequences

- Paired tail deletion and total erasure are detectable when the expected head
  is retained outside the ledger directory.
- A caller may still falsely declare genesis after erasure; authority policy
  must govern that explicit claim in Phase 1B.
- Local internal consistency remains useful diagnostic evidence but is not
  completeness proof.
- Stale-lock recovery remains fail-closed and deferred until an authorized
  mutation procedure exists.
