# ADR 0001: LearningOps Suite as modular umbrella, not monolithic runtime

## Status

Accepted.

## Context

ComplyOS has matured into a learning-compliance evidence engine with CSV,
connector-profile, CLI, API, MCP, privacy, security-readiness, and audit-packet
surfaces. The broader business opportunity is larger than compliance alone:
training coordinators, L&D analysts, instructional designers, training
specialists, and training providers also need help with intake, rosters,
scheduling, learner support, microlearning, instructional design, facilitation,
evaluation, and manager/client reporting.

The risk is scope creep. If every future module is folded into one runtime now,
ComplyOS becomes harder to explain, harder to test, and easier to overclaim.
Enterprise buyers also need clear capability boundaries: some will only need
CSV-backed compliance evidence; others may want regulatory intelligence or
training-ops automation later.

## Decision

Use **LearningOps Suite** as the umbrella product/working title and keep
**ComplyOS** as the implemented compliance/evidence module.

Adopt the “brand now, integrate later” approach:

1. Preserve ComplyOS as the live, tested evidence/readiness engine.
2. Define suite modules with explicit maturity labels.
3. Add RegWatch as a narrow, proposal-only regulatory intelligence contract
   inside or adjacent to ComplyOS.
4. Build synthetic demos for broader LearningOps workflows without representing
   them as production modules.
5. Promote demo/spec modules into runtime only after buyer pull validates the
   workflow.

## Consequences

### Positive

- ComplyOS stays sellable and testable as a focused product.
- The suite can tell the full L&D/training-ops story without pretending every
  module is live.
- Buyers can activate only the pieces they need.
- CSV fallback remains a first-class path for enterprise environments where
  Workday, Cornerstone, SuccessFactors, Canvas, or other APIs are gated.
- Regulatory intelligence stays safer because official-source provenance and
  human approval are built into the contract from the start.

### Negative

- Docs and demos must be disciplined about maturity labels.
- Some prospects may ask why the suite modules are not all in one app yet.
- More interface design is required before modules graduate from synthetic demo
  to production runtime.

### Mitigations

- Every public/internal page that describes the suite must distinguish **Live**,
  **Contract**, **Synthetic demo**, and **Roadmap** capability.
- RegWatch must remain proposal-only until explicit approval workflows exist.
- Landing/demo copy must say readiness, control mapping, evidence preparation,
  and review packets; it must not claim certification, attorney-grade
  interpretation, or final compliance status.
- Forgejo remains the source-of-truth remote for ComplyOS work. GitHub is not a
  target unless explicitly requested as mirror/legacy hosting.

## Alternatives considered

### Monolithic LearningOps Suite runtime now

This would create the fastest-looking single demo, but it would force shared
abstractions before real module boundaries are validated. Rejected because it
would weaken the current ComplyOS product and increase overclaim risk.

### Separate repos/packages for every module now

This would create strong boundaries and independent deployability, but it adds
packaging and coordination overhead before demand is proven. Rejected for v0.

### Keep only ComplyOS and ignore broader LearningOps

This would protect scope, but it misses the larger training-ops automation
vertical that maps to real L&D, coordinator, analyst, instructional-design, and
training-specialist work. Rejected because the broader wedge is commercially
important.

## Operating rules

1. ComplyOS can run without any speculative suite module.
2. Suite modules may call ComplyOS for evidence, packets, and audit logs.
3. AI-generated recommendations are draft/proposal-only until a human approves.
4. Regulatory changes require source URL, jurisdiction, date checked, coverage
   note, and review status.
5. Training publication, assignment, notifications, rule updates, and client
   communications require explicit approval gates.
