# System overview

GaiaLab is a local-first, file-backed governance platform. Its append-only
dataset registry feeds advisory quality checks and explicit human review.
Immutable releases feed eligibility, deterministic splitting, offline export,
and verification. A separate write-once model registry links training inputs,
scripts, artifacts, evaluation reports, and model releases.

```mermaid
flowchart LR
  A[Contributed or synthetic record] --> B[Validation]
  B --> C[Quality intelligence]
  C --> D[Technical review]
  D --> E{Domain review required?}
  E -->|yes| F[Domain review]
  E -->|no| G[Human approval]
  F --> G
  G --> H[Immutable dataset release]
  H --> I[Eligibility and deterministic splits]
  I --> J[Explicit training run registration]
  J --> K[Artifact registration]
  K --> L[Human evaluation]
  L --> M[Model approval/publication]
  H --> N[Public dataset verification]
  M --> O[Public model verification]
```

Automated systems never approve records, run training, or publish externally.
