# DOCS Index — Fuel Supply Intelligence & Resilience Platform

**BUP CSE Fest 2026 Hackathon Finals** (with Poridhi.io). Read in this order.

## Start here

| Doc | What it answers |
|---|---|
| [PRD.md](PRD.md) | What are we building and why? Problem, users, requirements (F1–F11), success metrics |
| [TRD.md](TRD.md) | How is it designed? Architecture, stack choices, algorithms, API, resilience |

## System design

| Doc | What it answers |
|---|---|
| [SystemArchitecture.md](SystemArchitecture.md) | How do the pieces fit? Topology, components, data flow, failure domains, deployment |
| [ERD.md](ERD.md) | How is data modeled? Entities, key columns, lifecycle chain (canonical: `PROBLEMSTATEMENT DOCS/erd.mermaid`) |
| [ApplicationFlow.md](ApplicationFlow.md) | How does data move? Per-tick loop, decision write path, crisis + failure paths, invariants |

## Implementation

| Doc | What it answers |
|---|---|
| [Implementation.md](Implementation.md) | What do we build in what order? Phases 0–5, checkpoints, deliberate skips |
| [BackendImplementation.md](BackendImplementation.md) | How is the backend built? Modules, simulator client, pipeline, decision path, tests |
| [FrontendImplementation.md](FrontendImplementation.md) | How is the dashboard built? Layout, data access, 5 screens, interaction rules |

## Experience

| Doc | What it answers |
|---|---|
| [ScreenFlow.md](ScreenFlow.md) | What does the operator see? 5 screens, navigation rules |
| [UserFlow.md](UserFlow.md) | How does the operator use it? Happy path, crisis flow, failure flow |

## Reading paths

- **New teammate:** PRD → TRD → SystemArchitecture → ScreenFlow
- **Backend dev:** TRD §3–5 → ERD → BackendImplementation → ApplicationFlow
- **Frontend dev:** ScreenFlow → FrontendImplementation → TRD §6 (API)
- **Judge / demo:** PRD → UserFlow → ScreenFlow

Reference: full problem statement in `PROBLEMSTATEMENT DOCS/` (repo root), integration guide PDF alongside it.
