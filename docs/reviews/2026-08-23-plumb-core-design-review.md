# Plumb review integration record — SEDB-RAL core design

- Review claim: Plumb（準繩）, interactive session
  `6d613942-d7d1-47b8-b0f3-e485e15db60f`
- Review mode: read-only; reviewer reported no file modifications
- CTCL instant: `ctcl:instant:13760557-37b0-4bab-92bb-90428933ddfb`
- CTCL registered at: `2026-08-23T07:48:33.079Z`
- Evidence boundary: file reads claimed as `own_execution`; review judgments
  remain conversation-surface claims; first-person authorship is unproven
- Integration owner: 織域
- Final review claim: `ACCEPT`; §11.4 dissent withdrawn
- Final-review CTCL instant:
  `ctcl:instant:3e892537-4174-401d-89ce-faf1ad7c2a7b`

## Outcome

The reviewer returned one blocking dissent and revisions grouped across six
areas. The blocking dissent is resolved in the design. The non-blocking
revisions are also integrated before the initial design commit.

The reviewer then re-read the 761-line integrated spec and review record,
reported every requested change present, formally withdrew the §11.4 dissent,
and reported no remaining blocker to an implementation plan.

## Integrated revisions

### Attestation semantics

- Replaced a universal evidence ladder with categorical `evidence_basis`,
  separate `verification_status`, and separate record lifecycle status.
- Added machine-evaluable sufficiency predicates per authority scope.
- Added a tombstone for the incident corpus's former ordinal interpretation.
- Added a migration mapping for `filesystem_only` and
  `peer_assertion_verified`.

### Origin matrix

- Added the required fourth adapter state, `unmeasured`.
- Kept `unmeasured` distinct from `structurally_unavailable`.
- Required bounded negative evidence before declaring structural
  unavailability.

### Temporal evidence

- Replaced the untestable phrase “near send time” with measured
  `receipt_to_send_delta_ms` and a transport-specific bound.
- Limited ledger sequence to insertion order and causal chains; unrelated
  overlapping events remain temporally indeterminate.

### Address and delivery semantics

- Added `address_failure_indeterminate` with candidate failure codes.
- Added receiver-observed `presented_instance_ref` and mismatch handling.

### Phase 1A scope

- Removed the JSON/SQLite projector from Phase 1A.
- Limited the first executable slice to canonical bytes, hash-chain ledger,
  identifier/discrimination contract, record-only CTCL receipts, and fixtures
  that deliberately turn every gate red.
- Moved domain schemas and projections to later slices.

### Authority dissent

The original design allowed ordinary registration after a claimed prior
conversation with Neo. The reviewer correctly identified that as a silent
authority expansion because the receiver could not verify the premise.

The design now requires a principal-authored authority artifact bound to a
specific resident ID or application digest. The registry never interprets “I
spoke with Neo” as authority. This satisfies the reviewer's stated condition
for withdrawing the dissent.

### Documentation-gate follow-up

The final re-read initially produced false absences because a literal search
did not cross Markdown hard wraps and because it searched for proposed wording
rather than the adopted claim. The design now separates exact-byte generated
artifact checks from assertion-ID prose coverage and normalizes whitespace for
text anchors.

## Additional integrator self-review

The integration also fixes two related one-field/one-semantics defects noticed
after dispatching the review:

- sender-authored `authored_by_instance` fields are renamed
  `claimed_authored_by_instance`; canonical authorship requires an attestation;
- identifier discrimination no longer treats every equal value across two
  instances as a runtime tag. The fixture separates distinct residents from
  multiple instances claiming one resident.

## External observations not changed here

- The GitHub repository slug contains `SEDB` twice.
- The repository is public and has no license.

These are visible repository properties, not review authority to rename the
repository or choose a license. They remain for Neo to decide.

## Independent-review availability note

An additional isolated Codex reviewer (`Hypatia`, agent
`01a02da1-116c-7753-85b3-5edca9d8a826`) was dispatched read-only after the
Plumb integration. It returned no findings or status within the bounded wait,
did not respond to an interrupt requesting immediate partial findings, and was
closed while still reported as running. Closure was observed at CTCL instant
`ctcl:instant:4697e63d-2c97-4192-ba23-2fd7935e52af`
(`2026-08-23T08:08:36.134Z`).

This attempt is `review_unavailable`; it is not counted as acceptance, failure,
or evidence that the design has no remaining defects.
