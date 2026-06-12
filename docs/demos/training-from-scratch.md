# Demo: Training from scratch

**Scenario:** a new official-source signal suggests a training requirement may
need review. The buyer wants to see how LearningOps Suite moves from source
signal to training design to rollout evidence without pretending AI made the
legal or instructional decision.

**Data status:** synthetic demo only. No real employee, student, client, or
employer data.

## Modules shown

| Step | Module | Maturity | Output |
| --- | --- | --- | --- |
| 1 | RegWatch | Contract | Source-backed alert proposal with coverage gaps. |
| 2 | NeedsAnalysis | Synthetic demo | Is-training-the-fix decision. |
| 3 | ObjectiveBuilder | Synthetic demo | Measurable objective set. |
| 4 | StoryboardStudio | Synthetic demo | 3-5 minute microlearning outline. |
| 5 | MicroLearn Radar | Roadmap | Source-backed learning suggestion queue. |
| 6 | AssessmentBuilder | Synthetic demo | Knowledge check and scenario prompts. |
| 7 | FacilitationOps | Synthetic demo | Run-of-show and materials checklist. |
| 8 | Scheduling/Rosters | Synthetic demo | Cohort roster and assignment plan. |
| 9 | ComplyOS | Live | Evidence packet path if completion proof matters. |

## Demo path

1. Load
   `examples/learningops-suite/training-from-scratch/regwatch-alert-proposal.json`.
2. Show the source/provenance panel:
   - source URL;
   - jurisdiction;
   - source identifier;
   - checked timestamp;
   - coverage disclosure;
   - human-review status.
3. Open `needs-analysis.json` and show why training is proposed but not assumed.
4. Open `module-design.json` and show objectives, storyboard, assessment, and
   accessibility/localization notes.
5. Import or preview `rollout-roster.csv` to show CSV fallback when LMS/HRIS API
   access is blocked.
6. Stop at the human approval gate before any training is assigned or published.
7. If approved, route the completion proof to ComplyOS for normal evidence
   packet generation.

## Approval gate

Before state changes, a human reviewer must approve:

- the interpretation of the source signal;
- the training-impact brief;
- the module objectives and assessment;
- the rollout audience;
- any learner/manager notifications;
- any ComplyOS rule-change proposal.

## What this proves

- RegWatch can create a source-backed proposal without mutating rules.
- Instructional-design modules can draft a course package with SME review.
- CSV fallback remains available when enterprise APIs are blocked.
- ComplyOS stays the evidence module instead of becoming a giant monolith.

## What this does not prove

- It does not prove an implemented RegWatch parser.
- It does not prove automated legal interpretation.
- It does not prove production-ready MicroLearn research.
- It does not prove training was actually assigned.

