# Decision 0004: Bound transcript speaker variables and visual cues

**Status:** Accepted for Phase 1B design

**Date:** 2026-08-23

**Consultation anchors:**

- `ctcl:instant:411ddec5-5b31-432a-9c78-559a0603b529`
- `ctcl:instant:43c4550b-b036-4a61-a037-d2e53048fd46`

## Context

Unlabelled or name-only multi-party transcripts lose the instance that can be
held accountable for a turn. Requiring opaque IDs alone reduces readability.
Neo.K therefore chose readable speaker variables that become valid only through
a transcript-local binding to a full identifier and declared identifier kind.

Neo.K also proposed an independent color block to make adjacent seats easier to
distinguish. Color improves scanning but introduces a second identity-looking
surface unless its scope and evidentiary limits are explicit.

## Decision

Every multi-party transcript begins with bindings. Each authored turn begins
with its bound label followed by a colon:

```text
[bindings]
Neo.K   principal:neo.k                                    principal
準繩     session:6d613942-d7d1-47b8-b0f3-e485e15db60f       session_uuid
織域     codex-thread:019fe51e-9276-7f63-8c16-414624b7fa9d  codex_thread

織域: message body
```

A name or short code is a variable, not an address. It is a valid speaker label
only after the current transcript binds it. An unbound label is invalid.

The Phase 1B `transcript_binding` contract contains:

```text
label
bound_identifier
identifier_kind
bound_at_ref
scope = transcript
rebinds
visual_token
visual_scope = transcript
palette_version
contrast_standard
verified_backgrounds
deficiency_set
accessibility_verification_status
```

`visual_token` is optional presentation metadata. A rich renderer may draw a
separate color swatch beside the textual label. Plain-text turns contain only
`{speaker_id}:`; they never place a bare palette token or color emoji in the
speaker-label position. If retained in a plain-text export, `visual_token`
appears only in the binding declaration.

Palette accessibility is not inferred from a name such as `accessible`. A
versioned palette declares a reproducible contrast target (initial target:
WCAG 2.2 SC 1.4.11 non-text contrast of at least 3:1), the light and dark
backgrounds actually checked, the simulated protanopia, deuteranopia, and
tritanopia deficiency set, and whether verification is `unmeasured`,
`verified`, or `failed`.

## Evidence and identity boundary

Speaker labels and color swatches are display claims. They do not establish
canonical identity or authorship. The ledger keeps resident, instance,
continuity line, thread/session, relay, claimed authorship, verified authorship,
and observed origin separate.

Color never participates in routing, authority, authorship, continuity,
discontinuity, identity merge, or evidence sufficiency. The same color does not
prove sameness; a different color does not prove difference. Rebinding a label
is append-only and does not inherit a visual token as continuity evidence.

Relay rendering uses the actual relay speaker's label and swatch. The record
still carries `relay_is_authorship: false`, `original_claimed_author`, and an
explicit `observed_origin: null` when the origin was not observed.

## Lifetime boundary

Current AI bindings are only instance/thread-level. A session UUID or Codex
thread ID changes when that instance changes. Cross-session resident IDs do not
yet exist; Phase 1B must not describe these bindings as resident continuity.

## Consequences

- Readable names and direct IDs become compatible through explicit binding.
- Color improves visual scanning without becoming another unbound identifier.
- A transcript copied without its binding header loses binding evidence and
  must mark speaker resolution indeterminate.
- Phase 1A runtime behavior remains unchanged because it intentionally contains
  no conversation renderer, transport, or registrar.
