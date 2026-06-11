# ComplyOS Connectivity Tracks Design

## Decision

ComplyOS remains one product and one repository. It should not split into separate corporate and education products yet.

The product will use one shared compliance evidence engine with two market-facing tracks:

1. **ComplyOS Workforce** — corporate and enterprise learning compliance.
2. **ComplyOS Campus** — higher-ed and K-12 learning compliance.

The two tracks should share the same normalized learning-record model, audit engine, evidence ledger, reporting, digest, remediation, CLI, MCP server, and release pipeline.

## Why this direction

The core problem is the same across both markets:

> Given people, learning items, assignments/completions, deadlines, exemptions, and evidence from one or more learning systems, determine who is non-compliant and produce defensible proof.

The market language changes, but the underlying engine should not:

| Workforce language | Campus language | Shared ComplyOS concept |
| --- | --- | --- |
| Employee | Student / learner | Learner |
| Manager | Advisor / instructor / admin | Responsible party |
| Training module | Course / assignment | Learning item |
| Transcript item | Enrollment / submission / grade | Learning record |
| Compliance gap | Missing requirement | Compliance gap |

Splitting into two products now would duplicate connector work, docs, packaging, evidence logic, and audit semantics before there is enough market evidence that the workflows truly diverge.

## Product shape

### Shared core

The shared ComplyOS core owns:

- Connector interfaces.
- CSV/report import.
- Learner normalization.
- Learning item normalization.
- Learning record/transcript normalization.
- Assignment and due-date normalization.
- Completion, exemption, overdue, and expiry semantics.
- Evidence hashing and audit ledger output.
- Compliance gap detection.
- Digest generation.
- HTML report and dashboard export.
- MCP tools and CLI commands.

### Workforce track

ComplyOS Workforce is the corporate compliance lane.

Primary users:

- L&D operators.
- People Ops / HRIS admins.
- Security compliance owners.
- Regulatory compliance owners.

Initial connector priority:

1. CSV/export folder connector.
2. Workday Learning hardening.
3. Cornerstone OnDemand / Cornerstone Learn.
4. SAP SuccessFactors Learning.
5. Docebo.
6. Absorb LMS.
7. Litmos.
8. LearnUpon.
9. TalentLMS.
10. Oracle Learning Cloud.

Default language:

- Employee.
- Training.
- Manager.
- Transcript.
- Remediation.
- Audit evidence.

### Campus track

ComplyOS Campus is the education compliance lane.

Primary users:

- Academic technology teams.
- Higher-ed IT admins.
- Program compliance teams.
- District technology teams.

Initial connector priority:

1. CSV/export folder connector.
2. Canvas.
3. D2L Brightspace.
4. Anthology Blackboard Learn.
5. Moodle.
6. Schoology.
7. Google Classroom.

Default language:

- Student / learner.
- Course.
- Instructor / advisor.
- Enrollment / submission.
- Missing requirement.
- Evidence record.

## Connector strategy

Do not build fifteen fully certified connectors before validating demand.

Build in this order:

1. **Universal CSV/import connector** strong enough for both Workforce and Campus.
2. **One Workforce flagship connector**: Cornerstone or SAP SuccessFactors Learning.
3. **One Campus flagship connector**: Canvas.
4. **Connector capability matrix** documenting which systems can provide users, courses, assignments, completions, due dates, exemptions, scores, and recertification/expiry.
5. **Additional connectors** based on user pull, not theoretical market coverage.

## Domain model implication

The current `Enrollment` term is useful but too narrow for long-term major-LMS coverage.

Different LMSs expose compliance data as:

- enrollment,
- transcript item,
- learning assignment,
- learning plan item,
- course assignment,
- completion record,
- grade/submission,
- certification,
- recertification,
- exemption.

The canonical cross-LMS concept should become **LearningRecord**.

A LearningRecord should normalize:

- learner/user identifier,
- learning item/course identifier,
- source system,
- source record identifier,
- assigned date,
- due date,
- status,
- completion date,
- completion percentage,
- score,
- exemption status,
- expiry/recertification date,
- raw source evidence hash.

The existing `Enrollment` model can remain for compatibility during v0.1, but future connector work should map external records into this broader LearningRecord concept.

## Phase roadmap update

### Phase 4 — Operator-ready release

Finish the current product as a credible source-available v0.1:

- Scheduled audit runs.
- Slack/Teams notification path.
- Release packaging.
- Security/docs polish.
- Clear BUSL-1.1 to Apache-2.0 license story.
- `CONTEXT.md` domain glossary.
- Changelog and release process.

### Phase 5 — Major LMS connectivity

Add the cross-market connector foundation:

- LearningRecord abstraction.
- Connector capability matrix.
- Workforce/Campus profile support.
- Cornerstone or SAP SuccessFactors connector.
- Canvas connector.
- Stronger import/export fixtures.

### Phase 6 — Scale-out

Only after demand proves it:

- PostgreSQL backend.
- Live web dashboard.
- Additional enterprise and education connectors.
- Multi-tenant hosted mode, if needed.

## CLI/MCP profile direction

A future profile command should configure vocabulary, sample data, and recommended connector setup without forking the product:

```bash
complyos init --profile workforce
complyos init --profile campus
```

Profile selection should affect:

- sample CSV templates,
- report copy,
- default compliance templates,
- docs examples,
- connector recommendations,
- dashboard labels.

It should not fork the underlying audit engine.

## Non-goals for the next implementation cycle

- No separate `complyos-workforce` and `complyos-campus` repositories.
- No hosted SaaS requirement.
- No PostgreSQL requirement for v0.1.
- No live web dashboard requirement for v0.1.
- No attempt to certify every major LMS connector before shipping the current product.
- No school-specific data model fork until real Campus users force one.

## Success criteria

This direction is successful if ComplyOS can:

1. Explain one coherent core product.
2. Present Workforce and Campus as clear market tracks.
3. Preserve one implementation path for audit evidence.
4. Prioritize major LMS connectors without overbuilding all of them upfront.
5. Keep the v0.1 release focused on operator readiness.
