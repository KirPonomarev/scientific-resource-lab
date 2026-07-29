# Scientific Reasoning Fabric: автономный master-plan V3.6

STATUS: FINAL_CONTENT / PLAN_ONLY / READY_FOR_REVIEW
PLAN_ID: SRF-MASTER-2026-07-29-V3.6
PROJECT_ID: scientific-resource-lab
PRODUCT_NAME: Scientific Reasoning Fabric
REPOSITORY_SLUG: scientific-resource-lab
PACKAGE_AND_CLI_PREFIX: srl
PLAN_CLASSIFICATION: PUBLIC_SAFE
AUTONOMY_CONTRACT_VERSION: V3.6
PROJECT_STANDING_AUTHORITY: FULL_IN_SCOPE
USER_APPROVAL_GATES_FOR_ROUTINE_WORK: 0
RUN_MODE: PLAN_ONLY
PLAN_CONTRACT_SHA256: 947d1858-c8cf110f-3c6bdb07-c70a8ff1-32459f9e-7b6448d1-afbf84d4-270c1ff0

## Назначение

Этот документ является единственным публично-безопасным исполнимым планом
превращения scientific-resource-lab в Scientific Reasoning Fabric: единый
научный мозг лаборатории, доступный одиночному агенту из Market Lab, Security
Researcher и самостоятельного научного контура через контракты, а не через
слияние репозиториев.

План не выдаёт SRF полномочия торговать, выполнять security-действия, менять
каноническую научную истину других систем, обходить их native bootstrap или
подменять их authority receipts. Он делает максимум инженерной работы
автономным: discovery, код, документацию, тесты, зависимости, lockfiles,
ветки, pull requests, безопасные merges, воспроизводимые релизы, локальные
bounded-проверки и формирование inactive integration adapters.

## Как исполнять

1. Один canonical plan, один writer, WIP=1.
2. Любая новая сессия сначала проверяет immutable hash и mutable state hash.
3. Агент не задаёт оператору вопросы по обычным инженерным развилкам. Он
   выбирает наиболее зрелый, обратимый, лицензируемый и проверяемый вариант.
4. Если одна независимая lane заблокирована, агент фиксирует точный blocker и
   продолжает только те стадии, чьи зависимости действительно закрыты.
5. Запрещено объявлять успех по процентам. Используются stage IDs, hashes,
   receipts, checks и terminal states.
6. Cross-project запись выполняется только нативным child mission владельца
   соответствующего репозитория. Родительский SRF writer передаёт контрактный
   пакет и принимает только проверяемое evidence.
7. Public plan не содержит имён хостов, секретов, абсолютных owner paths,
   приватных данных, торговых стратегий, exploit material или target data.

## PLAN_REVIEW

~~~yaml
PLAN_REVIEW:
  status: APPROVED
  reviewed_by_or_null: codex-independent-exact-hash-review
  reviewed_at_or_null: 2026-07-29T00:44:46Z
  review_findings:
    - exact PLAN_CONTRACT_SHA256 verified after declaration-only S00 recovery
    - exact CURRENT_STATE_SHA256 verified before mutable transition
    - no canonical plan conflict found
    - native writer ledger empty before S01
  approved_plan_contract_sha256_or_null: 947d1858c8cf110f3c6bdb07c70a8ff132459f9e7b6448d1afbf84d4270c1ff0
~~~

По правилам V3.6 новый или изменённый immutable plan остаётся DRAFT до проверки
точного PLAN_CONTRACT_SHA256. После такой проверки все routine-safe стадии
исполняются без дополнительных пользовательских approval gates. Protected
operations остаются связанными с native authority соответствующей системы.

<!-- BEGIN_PLAN_CONTRACT_V3_6 -->

## CONTROL

~~~yaml
control:
  plan_id: SRF-MASTER-2026-07-29-V3.6
  plan_schema: MasterPlan/V3.6
  mission_id: build-scientific-reasoning-fabric-v1
  run_mode: PLAN_ONLY
  canonical_claim: true
  predecessor_plan: null
  supersedes: []
  plan_classification: PUBLIC_SAFE
  standing_authority: FULL_IN_SCOPE
  user_approval_gates_for_routine_work: 0
  mutation_concurrency: 1
  writer_concurrency: 1
  plan_owned_branch_concurrency: 1
  physical_mutation_chain_concurrency: 1
  checkpoint_interval_active_minutes: 25-40
  same_signature_rerun_max: 1
  materially_different_recovery_approaches_max: 3
  digest_rendering: lowercase hex in eight 8-character groups separated by hyphens
  digest_normalization: remove grouping hyphens before comparison or hashing claims
~~~

### Неподменяемые правила управления

- План является canonical только для scientific-resource-lab.
- Изменение Market Lab, Security Researcher или shared-contract repository
  требует отдельного native child mission и его собственного mutation owner.
- Read-only scouts могут работать параллельно. Одновременная запись запрещена.
- Ни один model response, benchmark score или proof attempt не является
  authority, promotion или live permit.
- Auto-merge допустим только после всех repository-native required checks,
  требуемого review и отсутствия bypass branch protection.
- Force push, history rewrite, branch-protection bypass и удаление evidence
  запрещены.
- Для неоднозначного provider dispatch повторный dispatch запрещён. Сначала
  выполняется read-only reconciliation.
- Plan checkpoint не создаёт бессодержательный WIP commit.

## PROJECT_BINDING

~~~yaml
project_binding:
  project_id: scientific-resource-lab
  product_name: Scientific Reasoning Fabric
  repository_slug: scientific-resource-lab
  canonical_origin: https://github.com/KirPonomarev/scientific-resource-lab.git
  default_branch: main
  baseline_head: 947cbb4515307b54fe3eb9b6366cdb392361c867
  baseline_relation: local_main_equals_origin_main
  baseline_worktree: clean
  project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  fingerprint_preimage:
    project_id: scientific-resource-lab
    origin: https://github.com/KirPonomarev/scientific-resource-lab.git
  fingerprint_algorithm: sha256_canonical_compact_json
~~~

## MUTATION_OWNER_BINDING

~~~yaml
mutation_owner_binding:
  owner_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  authoritative_mutable_target: scientific-resource-lab source tree
  owner_scope:
    - SRF contracts, schemas, package manifests and conformance corpus
    - SRF CLI, MCP, portal, scheduler, runners and adapters
    - SRF documentation, tests, CI and release metadata
    - public-safe fixtures and generated documentation
  external_mutation_policy: native_child_mission_only
  owner_mismatch_terminal: BLOCKED_MUTATION_OWNER_MISMATCH
  cross_project_without_contract_terminal: BLOCKED_CROSS_PROJECT_MUTATION
~~~

## AUTONOMY_CONTRACT_BINDING

~~~yaml
autonomy_contract_binding:
  version: V3.6
  source_kind: operator_supplied_master_plan_protocol
  repository_governance:
    - GOVERNANCE.md
    - CONTRIBUTING.md
    - SECURITY.md
    - LICENSE
  precedence:
    - repository native safety and governance
    - this immutable mission contract
    - exact-bound execution receipts
    - mutable execution state
    - chat and tracker summaries
  interpretation:
    full_in_scope: autonomous routine-safe engineering inside owner scope
    no_approval_gates: no repeated operator questions for routine-safe choices
    not_granted:
      - live trading or order authority
      - target-specific security execution
      - secrets or credential disclosure
      - paid-service spend
      - hardware purchase
      - runtime deploy, restart, reboot or service kill
      - destructive T7 or backup operations
      - cross-project ownership
      - governance or branch-protection bypass
~~~

## MISSION_CONTRACT

~~~yaml
mission_contract:
  mission_id: build-scientific-reasoning-fabric-v1
  objective: >-
    Build and release a complete contract-first Scientific Reasoning Fabric
    that exposes reproducible scientific computation, formal proof, literature
    intelligence, causal and dynamical analysis, geometry, topology, SciML and
    bounded heavy-compute capabilities to standalone and cross-lab agents
    through one safe entrypoint, while preserving native authority boundaries.
  mutation_owner_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  read_only_external_dependencies:
    - DualContour shared-contract repository and conformance receipts
    - Crypto Market Lab native bootstrap, Pulse, contracts and bridge receipts
    - Security Researcher native bootstrap, health and ebashim receipts
    - public package registries and upstream source repositories
    - public scientific APIs and corpora
    - T7 capability and filesystem facts exposed through private overlay
    - optional dedicated Science Compute Node capability receipt
  scope_in:
    - one solo-agent entrypoint named labctl
    - request, result, receipt and health nerve contracts
    - isolated and revocable scientific packs
    - exact provenance, signatures and hash chains
    - bounded M1 operator-compute profile
    - T7 mutable work and immutable cold-CAS namespaces
    - dedicated compute-node profile for long or incompatible workloads
    - Market and Security inactive adapters plus native child missions
    - full documentation and machine-verifiable drift checks
    - failure isolation, observability, disaster recovery and restore drills
    - regression, conformance, adversarial and solo-agent acceptance suites
  scope_out:
    - direct trade execution
    - direct target-specific security execution
    - replacement of Market or Security native bootstraps
    - a second event ledger, broker, database, provider loop or orchestrator
    - active database or WAL in immutable cold storage
    - autonomous long-running jobs on the operator Mac
    - raw private datasets or exploit material in public Git
    - training on sources whose terms prohibit it
    - silent licensing exceptions
    - WBP integration
  affected_components:
    - contracts and schemas
    - object fabric and content-addressed storage
    - pack catalog, admission and revocation
    - runner, scheduler, checkpointing and sandbox
    - CLI, MCP and portal
    - knowledge retrieval and corpus safety
    - formal proof environments
    - public and private overlay boundary
    - cross-lab adapters
    - documentation and conformance
  authoritative_mutable_targets:
    - scientific-resource-lab repository
    - SRF-owned rebuildable runtime state selected by private overlay
    - SRF-owned immutable artifacts selected by private overlay
  delivery_target:
    - public Apache-2.0 repository
    - signed reproducible releases
    - inactive integration packets for native child missions
  runtime_targets:
    - bounded foreground M1 operator-compute profile
    - T7 SRF work namespace
    - T7 SRF immutable cold-CAS namespace
    - optional always-on Science Compute Node
    - public external APIs through budgeted adapters
  definition_of_done:
    - DOD-01 through DOD-24 in this contract are proven
  required_checks:
    - format and lint
    - unit and property tests
    - schema and consumer-driven contract conformance
    - public-boundary and secret scan
    - dependency lock, license, SBOM and vulnerability policy
    - reproducible build and artifact hash comparison
    - sandbox escape and resource-exhaustion adversarial tests
    - spool idempotency, crash-resume, DLQ and replay tests
    - corpus prompt-injection and taint tests
    - restore drill
    - solo-agent end-to-end acceptance
    - repository-native pull-request checks
  identity_sensitive_paths:
    - pyproject.toml
    - uv.lock
    - src/srl/contracts
    - src/srl/schemas
    - src/srl/runtime
    - src/srl/security
    - src/srl/storage
    - src/srl/transport
    - src/srl/cli
    - .github
    - GOVERNANCE.md
  protected_decisions:
    - installation or rotation of credentials
    - paid API spend or cloud resource purchase
    - live trading or order activation
    - target-specific security execution
    - deployment, service restart, reboot or kill on a managed runtime
    - destructive storage operation or restore overwrite
    - public disclosure of non-public evidence
    - license exception or copyleft boundary change
    - governance or branch-protection override
  forbidden_actions:
    - bypass native authority
    - write secrets to Git, logs, receipts, prompts or process arguments
    - copy D2 or D3 payloads across cells
    - infer approval from urgency or model agreement
    - claim empirical validation from contract validation
    - retry an ambiguous provider dispatch
    - force push or rewrite published history
    - delete unique evidence automatically
  authority_profile:
    routine_safe:
      - read-only discovery
      - create clean codex branch and worktree
      - edit SRF code, tests and public-safe docs
      - add license-compatible dependencies
      - refresh lockfiles and generated artifacts
      - run bounded local tests and fixtures
      - create issues, branches, pull requests and review packets
      - merge only through native green repository rules
      - publish a release only after the dedicated release stage is green
    child_project:
      - prepare hash-bound request
      - hand off to native child mission
      - verify returned evidence
      - never write the child worktree directly
    protected:
      - park exact action as WAIT_AUTHORITY
      - continue independent lanes
      - never weaken the requested functionality in code or design
  evidence_profile:
    minimum_binding:
      - project fingerprint
      - mission and stage IDs
      - exact source tree and artifact hashes
      - inputs, environment, policy and schema versions
      - terminal result and timestamp
      - invalidation keys and expiry
  data_classification:
    D0: public
    D1: sanitized and non-sensitive
    D2: private operational or research data
    D3: secrets, credentials, target data or highly sensitive evidence
    normal_transport: D0_D1_only
    D2_D3_policy: local_native_cell_only_unless_explicitly_allowlisted
~~~

## SOURCE_OF_TRUTH

### Приоритет фактов

1. Current physical state and direct read-only probes.
2. Exact Git, remote, CI, runtime and artifact identity.
3. Repository-native contracts and governance.
4. Exact-bound immutable receipts.
5. Rebuildable read models.
6. Tracker, plan mutable state, chat and attachments.

При конфликте identity выполнение завершается
BLOCKED_IDENTITY_CONFLICT. Stale evidence не обновляется догадкой.

### Базовая правда на момент заморозки

~~~yaml
truth_anchor:
  observed_at: 2026-07-29
  srf:
    branch: main
    head: 947cbb4515307b54fe3eb9b6366cdb392361c867
    origin_relation: local_main_equals_origin_main
    worktree: clean
    release_line: v1.0.0
    known_complete:
      - ScientificClaim and ScientificRun object family
      - contracts and JSON schemas
      - CAS interfaces
      - runner skeleton
      - pack manifests and initial packs
      - CLI, MCP, portal and LabExportPacket
    known_gaps:
      - T7ArtifactStore is not production-complete
      - production execution is still bounded to demonstration handlers
      - MCP export path has capability drift
      - no unified solo-agent labctl bootstrap
      - no production sandbox, revocation and complete supply-chain gate
      - no production spool semantics
      - no SRFPulse or FederationStatus
      - integration adapters are not fully activated
  market:
    observation_only: true
    current_head_at_freeze: 59ce6ff4c8b514c93d8d4b26d648ba6e7dd7b764
    current_pulse_at_freeze: RED
    current_gate_at_freeze: F8_resume_interrupted_durable_job
    rule: no_market_mutation_until_native_bootstrap_permits
  dual_contour:
    observation_only: true
    rule: revalidate_current_head_and_contracts_before_child_mission
  security:
    observation_only: true
    rule: native_bootstrap_and_health_precede_child_mission
~~~

## ЦЕЛЕВАЯ АРХИТЕКТУРА

~~~mermaid
flowchart LR
    A["Solo agent"] --> E["labctl enter"]
    E --> N["Native cell bootstrap"]
    E --> C["SRF capability catalog"]
    N --> L["LabAccessReceipt / scope only"]
    C --> L
    L --> Q["ScientificRequestEnvelope"]
    Q --> G["Validation + policy gate"]
    G --> S["Scheduler + sandboxed pack"]
    S --> R["ScientificResultEnvelope"]
    R --> P["Signed receipt + provenance chain"]
    P --> X["LabExportPacket"]
    X --> M["Market native C3 intake"]
    X --> Y["Security native proposal intake"]
    X --> O["Standalone research session"]
    M --> Z["Native A1/A2 gates remain authoritative"]
    Y --> Z
~~~

### Клетки и ответственность

| Клетка | Ответственность | Не имеет права |
|---|---|---|
| SRF | computation, proof, literature, advisory results | trading, target action, promotion |
| DualContour | shared schemas and conformance | domain truth, runtime authority |
| Market Lab | market canon, central material-event projector | delegate authority to SRF |
| Security Researcher | security canon and safe workflow | delegate execution outside ebashim |
| ebashim | единственный native security executor | принимать SRF result как permit |
| Science Compute Node | long/heavy pack execution | хранить authority or canonical truth |
| T7 cold-CAS | immutable artifacts and recovery evidence | active DB/WAL/runtime dependency |
| T7 work | rebuildable env/cache/scratch/spool | быть единственной копией unique evidence |

### Четыре нервных окончания

1. Request nerve: ScientificRequestEnvelope/v1.
2. Result nerve: ScientificResultEnvelope/v1.
3. Receipt nerve: signed ScientificRunReceipt/v1 and ImportReceipt/v1.
4. Health nerve: SRFPulse/v1 plus read-only FederationStatus/v1.

### Единый вход

labctl enter выполняет:

1. Detect cell from signed or repository-native identity.
2. Run native bootstrap without replacing it.
3. Verify exact HEAD, health, authority and allowed scope.
4. Load signed SRF CapabilityManifest.
5. Emit LabAccessReceipt as a scope projection over native receipts.
6. Select only compatible packs and transports.
7. Refuse stale, cross-HEAD, ambiguous or legacy checkout.

LabAccessReceipt всегда содержит:

~~~yaml
grants_authority: false
canonical_writes: 0
live_actions: 0
orders_allowed: false
security_actions_allowed: false
~~~

Старый или неправильный checkout возвращает REDIRECT_CANONICAL_ENTRY и не
создаёт второй runtime.

## КОНТРАКТНАЯ МОДЕЛЬ

### Обязательные схемы

- LabFederationManifest/v1
- LabCellManifest/v1
- LabSessionEnvelope/v1
- LabAccessReceipt/v1
- CapabilityManifest/v1
- SciencePackManifest/v2
- SciencePackAdmissionReceipt/v1
- PackRevocationRecord/v1
- ScientificRequestEnvelope/v1
- ScientificResultEnvelope/v1
- ScientificRunReceipt/v1
- ScientificImportReceipt/v1
- LabExportPacket/v1
- MethodCard/v1
- SRFPulse/v1
- FederationStatus/v1
- SpoolMessage/v1
- SpoolAck/v1
- DeadLetterRecord/v1
- CheckpointManifest/v1
- RestoreDrillReceipt/v1

### Общие обязательные поля

~~~yaml
identity:
  schema_id:
  schema_version:
  object_id:
  project_fingerprint:
  mission_id:
  stage_id:
  trace_id:
  correlation_id:
  causation_id:
  idempotency_key:
  created_at:
bindings:
  source_tree_sha256:
  input_manifest_sha256:
  environment_sha256:
  policy_sha256:
  pack_manifest_sha256:
  capability_manifest_sha256:
authority:
  grants_authority: false
  canonical_writes: 0
  live_actions: 0
classification:
  level: D0_or_D1
integrity:
  content_sha256:
  signer_key_id:
  sequence_number:
  previous_receipt_sha256:
  signature:
~~~

### Schema governance

- Semantic versioning applies to every public schema.
- Additive compatible fields require minor version and conformance fixtures.
- Breaking changes require a new major schema and a bounded dual-read window.
- Every producer ships golden vectors.
- Every consumer ships consumer-driven contract tests.
- Unknown security- or authority-sensitive fields fail closed.
- Schema registry never chooses newest by timestamp; resolution is exact.
- Revoked schema or pack identity is rejected even if cached.
- Generated documentation is committed and CI runs generation in check mode.

## ТРАНСПОРТ

Новый broker, daemon, shared database и SFTP transport не вводятся.

Transport V1:

- canonical JSON;
- local atomic spool using write-to-temp, fsync, atomic rename;
- existing rsync-over-SSH where a native cell already permits it;
- at-least-once delivery;
- receiver-side dedup by idempotency key plus content hash;
- explicit ack;
- bounded exponential retry with jitter;
- TTL and expiry;
- quarantine for schema, signature or classification failure;
- DLQ for terminal delivery failure;
- deterministic replay by exact message identity;
- Ed25519 signatures and per-cell monotonic sequence/hash chain;
- D0/D1 classifier on sender and independently on receiver;
- payload artifacts referenced by immutable hash, not silently embedded.

Message lifecycle:

~~~text
CREATED
  -> SEALED
  -> QUEUED
  -> IN_FLIGHT
  -> ACKNOWLEDGED
  -> IMPORTED_AS_C3

Terminal alternatives:
REJECTED | EXPIRED | DUPLICATE | QUARANTINED | DEAD_LETTERED
~~~

Transport acceptance includes crash at every state boundary, duplicate
delivery, reordering, partial files, replay, key rotation and revoked sender.

## REQUEST LIFECYCLE

~~~text
SUBMITTED
  -> VALIDATED
  -> QUEUED
  -> DISPATCHED
  -> RUNNING
  -> CHECKPOINTED*
  -> RESULT_SEALED
  -> EXPORT_READY
  -> DELIVERED
  -> IMPORTED_AS_C3

Terminal alternatives:
WAIT_CAPABILITY | WAIT_RUNTIME | WAIT_AUTHORITY | REJECTED |
EXPIRED | DUPLICATE | CANCELLED | FAILED | QUARANTINED | DLQ
~~~

Каждый переход:

- compare-and-set по current state и revision;
- one terminal receipt;
- idempotent replay;
- exact causation chain;
- no silent retry after possible external dispatch;
- timeout does not imply failure or permission to dispatch again.

## COMPUTE И STORAGE

### Phase 1: M1 Operator Compute Profile

- Только foreground, explicit on-demand, bounded jobs.
- Availability class: B2_BATCH_DEFERRED.
- Heavy concurrency: 1.
- Light concurrency: bounded by measured memory and thermal policy.
- Никаких timers, scheduled autonomous loops или long-running services.
- Каждый run имеет wall-time, CPU, RSS, disk, open-files and output limits.
- Checkpoint before timeout where the pack supports deterministic resume.
- Mac internal disk не является project storage.
- OS swap, system logs and Keychain are acknowledged unavoidable host behavior,
  but project datasets, envs, caches, scratch and results target T7.

### T7 namespaces

~~~text
SRF/
  cold-cas/       immutable, authoritative artifact objects
  work/
    envs/         rebuildable package environments
    caches/       rebuildable download/build caches
    scratch/      per-run disposable workspaces
    spool/        mutable transport state
    indexes/      rebuildable indexes
  quarantine/     untrusted or invalid artifacts, no execution
  restore-tests/  bounded restore drill targets
~~~

- cold-cas never contains active DB or WAL.
- work may contain package-manager DB/WAL because it is explicitly mutable and
  rebuildable.
- hard allocation cap: 400 GiB.
- free-space reserve: 100 GiB.
- admission uses measured compressed and expanded footprint, not estimates.
- cleanup is bounded and explicit; no background GC daemon.
- unique receipts, proofs and session chains are never auto-deleted.
- Market cold archive remains a separate namespace and policy.
- Current VPS is neither heavy-compute target nor T7 backup target.

### Phase 2: Science Compute Node

The complete node profile is built even if hardware is initially absent:

- always-on headless Linux;
- architecture and runtime capability receipt;
- isolated rootless containers or microVMs;
- CPU, RAM, scratch and accelerator labels;
- outbound network deny by default;
- no inbound public control plane;
- SSH through allowlisted operator route;
- signed job intake and artifact return;
- durable checkpoint/resume;
- watchdog and SRFPulse integration;
- no canonical authority and no secrets inherited by packs.

Until a compatible node is registered, incompatible or long jobs return
WAIT_COMPUTE_NODE. This is capability truth, not removal of functionality.

## SECURITY MODEL

### Trust classes

| Class | Example | Isolation |
|---|---|---|
| T0 | pure in-process deterministic primitive | process limits plus strict adapter |
| T1 | trusted native solver/prover | subprocess, read-only env/input, private scratch |
| T2 | complex scientific runtime | container or microVM, network deny |
| T3 | untrusted corpus or experimental pack | strongest isolation, taint, no secrets |
| T4 | remote or paid API | egress allowlist, budget, redaction, provider receipt |

### Sandbox invariants

- network deny by default;
- no inherited environment secrets;
- read-only pack, environment and input mounts;
- unique per-run scratch;
- output allowlist and maximum size;
- UID and filesystem isolation;
- CPU, RSS, wall-time, process, file and descriptor limits;
- syscall or VM boundary proportional to trust class;
- CAS writer remains outside sandbox;
- host paths never appear in public result;
- deterministic seed and locale where supported;
- abort receipt preserves evidence without claiming result.

If macOS cannot prove required isolation for T2/T3, the run is routed to the
Science Compute Node or remains WAIT_COMPUTE_NODE.

### Supply chain

Every pack requires:

- pinned source and artifact hashes;
- lockfile or immutable upstream revision;
- license classification;
- architecture compatibility;
- CycloneDX SBOM;
- signature or trusted checksum verification;
- vulnerability scan with explicit severity policy;
- build provenance;
- deterministic smoke probe;
- capability and footprint measurement;
- revocation state;
- dependency DAG and transitive revalidation triggers.

Pack lifecycle:

~~~text
DISCOVERED
  -> LICENSE_CHECKED
  -> BUILDABLE
  -> INSTALLED_ISOLATED
  -> PROBED
  -> VALIDATED
  -> ADMITTED
  -> ACTIVE

Side states:
DEGRADED | QUARANTINED | REVOKED | RE_ADMISSION_REQUIRED
~~~

Revocation is checked before scheduling and again before result import.

### Corpus and prompt-injection safety

- External text enters as D_UNTRUSTED_CORPUS regardless of prestige.
- Retrieval and extraction are separate from agent instructions.
- Raw corpus text is never concatenated into privileged prompts.
- Deterministic extractors emit quoted facts with source offsets and hashes.
- Models receive normalized evidence objects, not executable instructions.
- Injection canaries, malicious PDFs/HTML, Unicode confusion and citation
  spoofing are regression fixtures.
- Literature claims remain evidence candidates until source and date checks.

## SCHEDULER И RESOURCE POLICY

- Health, receipt sealing and recovery tasks have highest priority.
- Separate light and heavy queues.
- Heavy concurrency on M1 equals 1.
- Admission checks live memory, disk reserve and pack-expanded footprint.
- Fairness uses aging without bypassing priority or authority.
- Backpressure begins before reserve breach.
- A job with missing capability stays parked; it is not retried continuously.
- Long node jobs checkpoint by deterministic step count or time interval.
- Abort conditions include memory pressure, thermal threshold, disk reserve,
  revoked pack, stale authority binding and lost signer state.
- Cache reuse requires exact environment, input, policy and pack identity.

## НАБОР SCIENCE PACKS БЕЗ УРЕЗАНИЯ ФУНКЦИЙ

### P0 core

| Domain | Packs and sources | Placement |
|---|---|---|
| Numeric | NumPy, SciPy, mpmath, Pint | M1/T7 work |
| Symbolic/exact | SymPy, python-flint, FLINT, Arb, Calcium, PARI/GP, Maxima | isolated M1 or node |
| Algebra | GAP, Singular | isolated M1 or node |
| SMT | Z3, cvc5 | trusted subprocess |
| Formal primary | Lean 4, pinned mathlib | isolated Lean environment |
| Formal independent | Rocq, Isabelle/HOL, HOL4 | isolated environments/node |
| Formal corpora | CSLib, Erdős Problems, Formal Conjectures | pinned metadata/corpus adapters |
| Knowledge | OpenAlex, Crossref, OpenCitations, zbMATH, OEIS, LMFDB | budgeted API/cache |

### P1 discovery and applied science

| Domain | Packs | Placement |
|---|---|---|
| Symbolic regression | PySR, SR4MDL, Operon, gplearn, AI-Feynman | M1 bounded/node |
| Dynamics | PySINDy, PyDMD, pyKoopman, dysts | M1 bounded/node |
| Geometry/topology | GUDHI, ripser, geomstats, POT, pymanopt, KeplerMapper, TopoNetX, Regina | isolated profiles |
| Probability | PyMC, ArviZ | bounded honest diagnostics/node |
| Causal | DoWhy, Tigramite, EconML | bounded profiles |
| Optimization | CVXPY, solver matrix, JAXopt, BoTorch | isolated profiles |
| SciML | Julia SciML, ModelingToolkit, DataDrivenDiffEq, diffrax | Julia/Python profiles |
| Physics/domain | QuTiP, Cadabra, Astropy, Cantera, PyBaMM, quimb, cotengra | isolated profiles |

### P2 heavy and optional oracles

| Domain | Packs | Policy |
|---|---|---|
| PDE/HPC | PETSc, FEniCSx, pyMOR, scikit-fem, Dedalus | tiny bounded CPU locally; real work on node |
| Neural operators | Modulus and large operator models | accelerator-capable node only |
| Broad CAS | SageMath | isolated, optional, deduplicated profile |
| Paid oracle | Wolfram API | explicit credential and budget receipt |

No pack is admitted only because installation succeeded. Each pack receives a
MethodCard with supported claim classes, known unsoundness or approximation,
resource envelope, license, deterministic settings and required cross-check.

### Formal trust policy

- Lean 4 plus mathlib is the primary mathematical proof environment.
- Rocq and Isabelle/HOL are independent critical cross-checks.
- HOL4 is an optional conservative independent oracle.
- CSLib is a Lean library and API index, not an independent oracle.
- Version-skewed Lean corpora use separate pinned environments.
- A transpiled theorem is not considered equivalent until assumptions,
  definitions, universes and side conditions are compared.
- Proof kernel acceptance proves formal derivability in the frozen environment,
  not empirical truth or correct problem formalization.

### Public problem-source policy

Erdős Problems is ingested from pinned public repository metadata. The website
is used on demand under its published terms. The pipeline records status date,
formalization availability, source references, licensing and robots/training
restrictions. Open status is never assumed current without a fresh literature
check.

### Автоматизируемые продукты

1. LawMiner: data to candidate law to surrogate/null tests to exact checks.
2. Formal Verification Lab: statement normalization, Lean primary proof and
   optional independent prover cross-check.
3. Geometry and Physics Compiler: units, symbolic, geometry, topology and
   simulation consistency.
4. Causal Economy Lab: causal graph, identification, sensitivity, simulation
   and honest uncertainty.
5. Literature-to-Knowledge Graph: source retrieval, provenance, contradiction
   map and claim packets.

Каждый продукт использует общий ScientificClaim/ScientificRun fabric и не
создаёт собственный ledger или authority model.

## EVIDENCE_CONTRACT

Для каждого final claim создаётся:

~~~yaml
evidence_binding:
  claim:
  project_fingerprint:
  mission_id:
  stage_id:
  source_or_artifact_identity:
  command_or_source:
  environment_or_policy_identity:
  inputs_sha256:
  terminal_result:
  artifact_or_receipt_hash:
  observed_at:
  expires_or_invalidates_on:
~~~

Evidence reuse допустим только при полном совпадении:

- source tree;
- input and dataset manifests;
- dependency lock and runtime;
- pack manifest and policy;
- schema versions;
- architecture;
- configuration;
- TTL and all invalidation keys.

Exit code 0, model agreement, proof search success, contract validation and
fixture success закрывают только соответствующий узкий claim.

## AUTHORITY_MODEL

### Автономный выбор агента

Без вопроса оператору агент:

- выбирает reversible implementation with lowest coupling;
- предпочитает standard formats and maintained upstreams;
- выбирает local deterministic primitive before remote API;
- выбирает exact arithmetic before floating approximation when feasible;
- выбирает fail-closed on authority, integrity, classification and signature;
- чинит flaky infra через один same-signature rerun и до трёх materially
  different recovery approaches;
- паркует необязательную недоступную capability и продолжает независимые stages;
- обновляет документацию и tests вместе с behavior;
- создаёт PR и включает native auto-merge только после required checks;
- не расширяет scope молча.

### Protected operation

Если требуется protected decision, агент не задаёт серии вопросов и не
имитирует полномочия. Он:

1. полностью готовит code, tests, runbook, preflight and rollback;
2. фиксирует exact target, maximums and expected receipt;
3. ставит только физический action в WAIT_AUTHORITY;
4. продолжает все независимые стадии;
5. оставляет один минимальный decision packet.

### Cross-project mutation

SRF parent mission:

1. строит signed ChildMissionRequest;
2. связывает contract hash, expected write set and acceptance;
3. передаёт его нативному entry другого project;
4. не получает write access к чужому canonical worktree;
5. принимает ChildMissionCloseout только при exact identity;
6. импортирует результат как evidence, не как authority.

## EXECUTION_ORDER

### Общие параметры каждой стадии

~~~yaml
stage_defaults:
  writer_count: 1
  wip: 1
  same_signature_rerun_max: 1
  recovery_approaches_max: 3
  provider_policy:
    provider_dispatches_per_role: 1
    pre_dispatch_recovery_attempts: 1
    ambiguous_dispatch_retries: 0
  checkpoint:
    after_transition: true
    before_long_wait: true
    before_context_compaction: true
  rollback_or_keep_rule:
    uncommitted_failure: keep isolated evidence and restore owned files only
    committed_failure: revert by new commit; never rewrite published history
    unique_evidence: preserve
  global_stop_conditions:
    - mutation owner mismatch
    - dirty canonical entry not owned by mission
    - identity conflict
    - secret or D2/D3 leakage
    - signature or hash-chain break
    - branch-protection bypass requirement
    - write outside declared write set
~~~

### S00 — Reconcile and freeze canonical plan

~~~yaml
stage:
  id: S00
  dependencies: []
  goal: prove one canonical SRF master-plan and freeze exact hashes
  scope_in: [plan discovery, project identity, current writers, plan hashes]
  scope_out: [product implementation]
  write_set: [docs/plans/scientific-reasoning-fabric-master-plan-v3.6.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: ABSENT_OR_DRAFT_TO_READY_FOR_REVIEW
  primary_evidence: [git identity, bounded plan search, calculated hashes]
  executable_action:
    tool_or_command: validate markers, calculate SHA-256, verify git diff
    working_directory_or_target: SRF repository
    exact_inputs: [this file, baseline HEAD, origin URL]
    preconditions: [clean main, no competing live plan writer]
    expected_result: one PUBLIC_SAFE plan with valid immutable and state hashes
    focused_checks: [marker uniqueness, hash recomputation, permission 0644]
    affected_checks: [public-boundary scan]
    maximums: {writers: 1, plans_created: 1}
    stop_conditions: [canonical plan conflict, owner mismatch]
    terminal_receipt: PlanFreezeReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [immutable contract edit, project fingerprint change]
  forbidden_actions: [implementation, Git history mutation, remote mutation]
  next_action: wait for exact-hash plan review, then S01
~~~

### S01 — Execution bootstrap and baseline truth repair

~~~yaml
stage:
  id: S01
  dependencies: [S00 approved exact hash]
  goal: create isolated execution branch and machine-readable discrepancy ledger
  scope_in: [repo governance, tests, package state, docs, open PRs, CI]
  scope_out: [external project mutation, runtime deployment]
  write_set: [.tmp mission receipts, one codex worktree, docs generated baseline]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: READY_FOR_REVIEW_TO_IN_PROGRESS
  primary_evidence: [exact HEAD, tree, status, branch, dependency lock, test results]
  executable_action:
    tool_or_command: create clean codex/srf-fabric-v1 worktree; run repository-native bootstrap, lint and tests
    working_directory_or_target: isolated SRF worktree
    exact_inputs: [approved plan hash, origin/main exact SHA]
    preconditions: [approved hash equals current plan hash, clean canonical entry]
    expected_result: AgentBootstrapReceipt and discrepancy-ledger.json
    focused_checks: [uv sync --frozen, make lint, make test]
    affected_checks: [secret scan, public path scan]
    maximums: {active_branches: 1, active_worktrees: 1}
    stop_conditions: [baseline identity drift, unowned changes]
    terminal_receipt: BaselineTruthReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [origin main changes before branch creation]
  forbidden_actions: [modify canonical main checkout, discard user WIP]
  next_action: S02
~~~

### S02 — Solo-agent bootstrap and system atlas

~~~yaml
stage:
  id: S02
  dependencies: [S01]
  goal: make one agent able to orient, request science and recover without chat history
  scope_in: [AGENTS, START-HERE, system atlas, generated manifests, runbooks]
  scope_out: [pack execution]
  write_set: [AGENTS.md, docs/system, docs/operations, schemas for cell manifests]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: NO_UNIFIED_BOOTSTRAP_TO_DOCUMENTED_BOOTSTRAP
  primary_evidence: [generated docs diff, fresh-agent fixture]
  executable_action:
    tool_or_command: implement manifest-driven docs generator and labctl orientation specification
    working_directory_or_target: SRF worktree
    exact_inputs: [mission contract, current schemas and CLI]
    preconditions: [S01 discrepancy ledger frozen]
    expected_result: START-HERE, SYSTEM-ATLAS, SOLO-AGENT-RUNBOOK, CELL-MATRIX, AUTHORITY-MATRIX
    focused_checks: [docs generator --check, public boundary, fresh-context walkthrough]
    affected_checks: [schema tests, CLI help snapshots]
    maximums: {manual_sources_of_truth: 1}
    stop_conditions: [docs contradict executable manifest]
    terminal_receipt: SoloAgentBootstrapDesignReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [manifest or authority schema change]
  forbidden_actions: [hard-code private paths, claim LabAccessReceipt grants authority]
  next_action: S03
~~~

### S03 — Contract kernel and conformance corpus

~~~yaml
stage:
  id: S03
  dependencies: [S02]
  goal: implement all V1 federation, access, request, result, receipt, health and transport schemas
  scope_in: [schemas, validators, golden vectors, compatibility rules]
  scope_out: [runtime dispatch]
  write_set: [src/srl/contracts, src/srl/schemas, tests/contracts, docs/contracts]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: PARTIAL_CONTRACTS_TO_CONFORMANCE_KERNEL
  primary_evidence: [schema hashes, golden vectors, negative fixtures]
  executable_action:
    tool_or_command: add versioned JSON Schemas, strict validators and consumer fixtures
    working_directory_or_target: SRF worktree
    exact_inputs: [contract model in this plan, existing LabExportPacket and MethodCard]
    preconditions: [authority invariants frozen]
    expected_result: deterministic schema registry with exact version resolution
    focused_checks: [roundtrip, unknown authority field fail-close, downgrade rejection]
    affected_checks: [full unit suite, generated contract docs]
    maximums: {implicit_schema_upgrades: 0}
    stop_conditions: [authority ambiguity, non-deterministic canonical JSON]
    terminal_receipt: ContractKernelReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [schema breaking change, canonicalization change]
  forbidden_actions: [latest-by-time resolution, permissive unknown security fields]
  next_action: S04
~~~

### S04 — Storage fabric and T7 split

~~~yaml
stage:
  id: S04
  dependencies: [S03]
  goal: complete T7ArtifactStore, immutable CAS and mutable work namespace logic
  scope_in: [storage abstraction, layout, quotas, atomicity, integrity, private overlay]
  scope_out: [physical T7 formatting or destructive migration]
  write_set: [src/srl/storage, tests/storage, docs/operations/T7-OPERATIONS.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: STORAGE_STUB_TO_TESTED_STORAGE_FABRIC
  primary_evidence: [fault-injection tests, quota receipts, CAS hash proof]
  executable_action:
    tool_or_command: implement abstract roots, atomic CAS writes, quota ledger and rebuildable work stores
    working_directory_or_target: fixture volume, never owner T7 during code stage
    exact_inputs: [400 GiB cap, 100 GiB reserve, namespace policy]
    preconditions: [contract kernel green]
    expected_result: filesystem-neutral production storage adapter proven on fixture volume
    focused_checks: [partial write, fsync, rename, duplicate object, corruption, low-space]
    affected_checks: [materializer, exporter, runner tests]
    maximums: {fixture_disk_gib: 5, destructive_owner_storage_actions: 0}
    stop_conditions: [cold CAS accepts mutable DB/WAL, quota bypass]
    terminal_receipt: StorageFabricValidationReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [filesystem semantics change, hash algorithm change]
  forbidden_actions: [format T7, delete unique artifacts, use current VPS as backup]
  next_action: S05
~~~

### S05 — Reliable spool transport

~~~yaml
stage:
  id: S05
  dependencies: [S04]
  goal: implement the complete at-least-once spool protocol without a new broker
  scope_in: [atomic spool, ack, dedup, retry, TTL, quarantine, DLQ, replay, signatures]
  scope_out: [second daemon, second orchestrator, SFTP]
  write_set: [src/srl/transport, tests/transport, docs/architecture/transport.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: NO_PROTOCOL_TO_CRASH_SAFE_PROTOCOL
  primary_evidence: [state-machine property tests, crash matrix, signature fixtures]
  executable_action:
    tool_or_command: implement canonical JSON spool and deterministic replay engine
    working_directory_or_target: SRF worktree and temporary fixture roots
    exact_inputs: [SpoolMessage/v1, Ed25519 key interface, classification policy]
    preconditions: [storage and schemas green]
    expected_result: no loss, no double import and truthful terminal state under injected faults
    focused_checks: [crash every boundary, duplicate, reorder, expiry, revoke, corrupt]
    affected_checks: [exporter and import tests]
    maximums: {delivery_semantics: at_least_once, ambiguous_dispatch_retries: 0}
    stop_conditions: [silent loss, unsigned acceptance, non-idempotent import]
    terminal_receipt: TransportConformanceReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [canonical JSON, signature or schema policy change]
  forbidden_actions: [introduce broker, shared DB, SFTP or polling daemon]
  next_action: S06
~~~

### S06 — Sandbox and adversarial execution boundary

~~~yaml
stage:
  id: S06
  dependencies: [S05]
  goal: enforce trust-class isolation and resource limits before real pack admission
  scope_in: [sandbox adapters, secret stripping, network policy, mounts, limits, abort]
  scope_out: [unbounded host execution]
  write_set: [src/srl/security, src/srl/runtime/sandbox, tests/security, docs/security]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: TRUSTED_DEMO_RUNNER_TO_ENFORCED_SANDBOX
  primary_evidence: [escape suite, resource exhaustion suite, secret canaries]
  executable_action:
    tool_or_command: implement process, container and remote isolation adapters with fail-closed capability probes
    working_directory_or_target: SRF worktree and disposable fixtures
    exact_inputs: [T0-T4 policy, host capability manifest]
    preconditions: [signed transport and storage]
    expected_result: unsupported isolation returns WAIT_COMPUTE_NODE, never weak fallback
    focused_checks: [network, env, filesystem, fork bomb, disk flood, timeout, signal]
    affected_checks: [runner, pack admission]
    maximums: {untrusted_host_fallbacks: 0}
    stop_conditions: [secret inherited, host write escape, unenforced limit]
    terminal_receipt: SandboxValidationReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [OS, sandbox runtime or policy change]
  forbidden_actions: [claim macOS isolation without probe, run T2/T3 unsandboxed]
  next_action: S07
~~~

### S07 — Supply chain, admission, dependency DAG and revocation

~~~yaml
stage:
  id: S07
  dependencies: [S06]
  goal: make every pack reproducible, licensed, scanned, revocable and transitively revalidated
  scope_in: [manifest v2, lock, hashes, SBOM, licenses, vulnerabilities, revocation]
  scope_out: [pack feature implementation]
  write_set: [src/srl/packs, configs/packs, tests/packs, docs/architecture/pack-admission.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: STATIC_PACKS_TO_GOVERNED_PACK_LIFECYCLE
  primary_evidence: [SBOMs, license matrix, revocation fixtures, DAG tests]
  executable_action:
    tool_or_command: implement SciencePackManifest/v2 admission and revocation registry
    working_directory_or_target: SRF worktree
    exact_inputs: [pack inventory, governance, public license evidence]
    preconditions: [sandbox green]
    expected_result: no ACTIVE pack without complete admission receipt
    focused_checks: [hash mismatch, CVE threshold, license reject, transitive revoke]
    affected_checks: [catalog, scheduler, CLI]
    maximums: {unhashed_dependencies: 0, unknown_licenses: 0}
    stop_conditions: [incompatible license, unverifiable artifact]
    terminal_receipt: PackGovernanceReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [dependency, lock, license, CVE feed or policy change]
  forbidden_actions: [admit by install success alone, hide optional license wait]
  next_action: S08
~~~

### S08 — Runner, scheduler, checkpoints and backpressure

~~~yaml
stage:
  id: S08
  dependencies: [S07]
  goal: replace demonstration handlers with durable policy-driven execution
  scope_in: [request FSM, queues, resource policy, checkpoint, cancel, result sealing]
  scope_out: [autonomous Mac daemon]
  write_set: [src/srl/runtime, src/srl/runner, tests/runtime, docs/operations/runner.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: DEMO_RUNNER_TO_PRODUCTION_BOUNDED_RUNNER
  primary_evidence: [FSM property tests, crash-resume receipts, resource measurements]
  executable_action:
    tool_or_command: implement queue scheduler, pack dispatcher, checkpoint and sealed output pipeline
    working_directory_or_target: SRF worktree and fixture roots
    exact_inputs: [request schemas, sandbox, admission registry, storage]
    preconditions: [S03-S07 green]
    expected_result: exactly one truthful terminal outcome per run
    focused_checks: [cancel race, timeout, resume, stale pack, disk pressure, fairness]
    affected_checks: [CLI, MCP, export]
    maximums: {m1_heavy_concurrency: 1, background_mac_services: 0}
    stop_conditions: [double result, reserve breach, unsealed output]
    terminal_receipt: RunnerConformanceReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [FSM, scheduler, resource or checkpoint format change]
  forbidden_actions: [continuous Mac execution, execute arbitrary user command]
  next_action: S09
~~~

### S09 — SRFPulse, federation status, tracing and disaster recovery

~~~yaml
stage:
  id: S09
  dependencies: [S08]
  goal: expose honest SRF health and prove recovery of unique state
  scope_in: [metrics, SLO, trace IDs, pulse, backup classes, restore drill]
  scope_out: [overwriting Market OrganismPulse, backup to current VPS]
  write_set: [src/srl/health, src/srl/observability, tests/recovery, docs/operations/RECOVERY-RUNBOOK.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: NO_HEALTH_MODEL_TO_INDEPENDENT_SRFPULSE
  primary_evidence: [SLO fixtures, trace linkage, RestoreDrillReceipt]
  executable_action:
    tool_or_command: implement SRFPulse, read-only FederationStatus and bounded restore harness
    working_directory_or_target: fixture storage
    exact_inputs: [health contracts, storage classes, transport states]
    preconditions: [runner and storage green]
    expected_result: SRF failure becomes WAIT_SRF without falsely making Market RED
    focused_checks: [stale pulse, cross-head, corrupt CAS, lost index, restore unique receipts]
    affected_checks: [labctl and adapters]
    maximums: {runtime_health_authorities: 1_per_cell}
    stop_conditions: [federation status mutates native health, restore loses unique state]
    terminal_receipt: HealthAndRecoveryReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [SLO, health schema, storage class or signer change]
  forbidden_actions: [declare whole federation healthy from partial pulse]
  next_action: S10
~~~

### S10 — labctl, MCP, portal and export convergence

~~~yaml
stage:
  id: S10
  dependencies: [S09]
  goal: provide one equivalent agent entry across CLI, MCP and portal
  scope_in: [enter, capabilities, submit, status, result, export, replay, doctor]
  scope_out: [native authority replacement]
  write_set: [src/srl/cli, src/srl/mcp, src/srl/portal, tests/interfaces, docs/operations]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: MULTIPLE_PARTIAL_ENTRIES_TO_ONE_SEMANTIC_ENTRY
  primary_evidence: [interface parity matrix, transcript fixtures, export packet hashes]
  executable_action:
    tool_or_command: implement labctl command family and route MCP/portal through same application service
    working_directory_or_target: SRF worktree
    exact_inputs: [current CLI, MCP, portal, LabExportPacket]
    preconditions: [health and runner green]
    expected_result: identical request and receipt semantics on all interfaces
    focused_checks: [MCP export capability drift, stale bootstrap, wrong checkout redirect]
    affected_checks: [end-to-end fixtures]
    maximums: {business_logic_implementations: 1}
    stop_conditions: [interface bypasses validator or native bootstrap]
    terminal_receipt: InterfaceConvergenceReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [application service, schema or CLI contract change]
  forbidden_actions: [duplicate interface business logic, make portal authoritative]
  next_action: S11
~~~

### S11 — P0 numerical, symbolic, exact algebra and SMT packs

~~~yaml
stage:
  id: S11
  dependencies: [S10]
  goal: admit complete P0 compute core with cross-check policies
  scope_in: [NumPy, SciPy, Pint, SymPy, mpmath, FLINT family, PARI, Maxima, GAP, Singular, Z3, cvc5]
  scope_out: [formal theorem libraries, heavy PDE]
  write_set: [configs/packs/p0, src/srl/packs/p0, tests/packs/p0, docs/catalog]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: PARTIAL_P0_TO_ADMITTED_P0_CORE
  primary_evidence: [per-pack admission receipt, method cards, regression corpus]
  executable_action:
    tool_or_command: build isolated profiles, adapters, probes and cross-check suites
    working_directory_or_target: T7 fixture roots then private overlay target
    exact_inputs: [pinned upstream revisions, pack manifests, license matrix]
    preconditions: [governed runner operational]
    expected_result: each pack ACTIVE, DEGRADED or truthful WAIT_CAPABILITY
    focused_checks: [exact versus float, units, solver disagreement, malformed input]
    affected_checks: [catalog and scheduler]
    maximums: {pack_parallel_mutations: 1}
    stop_conditions: [silent approximation, license or hash failure]
    terminal_receipt: P0CoreAdmissionBundle/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [pack version, lock, method card or policy change]
  forbidden_actions: [collapse independent solvers into one evidence claim]
  next_action: S12
~~~

### S12 — Lean primary formal environment

~~~yaml
stage:
  id: S12
  dependencies: [S11]
  goal: establish Lean 4 plus pinned mathlib as primary formal mathematics pack
  scope_in: [toolchain pinning, theorem request adapter, proof receipts, regression]
  scope_out: [claiming correct formalization from kernel acceptance]
  write_set: [configs/packs/formal/lean, src/srl/packs/formal/lean, tests/formal/lean]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: FORMAL_PROFILE_CARD_TO_PRIMARY_PROVER_ACTIVE
  primary_evidence: [toolchain hash, mathlib revision, kernel receipts]
  executable_action:
    tool_or_command: build separate pinned Lean environments and proof-check adapter
    working_directory_or_target: T7 work or Science Compute Node profile
    exact_inputs: [Lean and mathlib pins, trusted regression theorems]
    preconditions: [sandbox and pack admission]
    expected_result: deterministic proof check with assumption and environment manifest
    focused_checks: [invalid proof, version skew, hidden axiom, timeout]
    affected_checks: [formal result schema, exporter]
    maximums: {implicit_toolchain_upgrades: 0}
    stop_conditions: [unbound mathlib, missing axiom inventory]
    terminal_receipt: LeanAdmissionReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [Lean toolchain, mathlib revision, theorem normalization change]
  forbidden_actions: [reuse incompatible Lake build, call proof empirical validation]
  next_action: S13
~~~

### S13 — Rocq, Isabelle/HOL and HOL4 independent contours

~~~yaml
stage:
  id: S13
  dependencies: [S12]
  goal: add independent formal verification without false theorem equivalence
  scope_in: [Rocq, Isabelle/HOL, HOL4, translation manifests, assumption comparison]
  scope_out: [automatic semantic equivalence claims]
  write_set: [configs/packs/formal, src/srl/packs/formal, tests/formal/cross_prover]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: SINGLE_PROVER_TO_CROSS_PROVER_FABRIC
  primary_evidence: [per-prover admission, semantic-gap fixtures, independent receipts]
  executable_action:
    tool_or_command: implement isolated adapters and explicit theorem translation records
    working_directory_or_target: T7 work or compatible node
    exact_inputs: [pinned prover distributions, shared theorem fixtures]
    preconditions: [Lean primary active]
    expected_result: independent checks labeled by exact logic and assumptions
    focused_checks: [logic mismatch, omitted side condition, false equivalence]
    affected_checks: [formal products, catalog]
    maximums: {automatic_equivalence_claims: 0}
    stop_conditions: [translation erases assumptions, kernel identity absent]
    terminal_receipt: CrossProverAdmissionBundle/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [prover, library or translation policy change]
  forbidden_actions: [present CSLib as independent oracle]
  next_action: S14
~~~

### S14 — Scientific knowledge and untrusted corpus layer

~~~yaml
stage:
  id: S14
  dependencies: [S13]
  goal: build safe source-grounded literature and mathematical knowledge graph
  scope_in: [OpenAlex, Crossref, OpenCitations, zbMATH, OEIS, LMFDB, CSLib, Erdős, Formal Conjectures]
  scope_out: [restricted-site mirroring, forbidden training use]
  write_set: [src/srl/knowledge, configs/sources, tests/knowledge, docs/architecture/knowledge-sources.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: BASIC_RETRIEVER_TO_TAINT_SAFE_KNOWLEDGE_GRAPH
  primary_evidence: [source terms records, pinned snapshots, injection corpus tests]
  executable_action:
    tool_or_command: implement source adapters, deterministic extractors, citation graph and taint boundary
    working_directory_or_target: SRF worktree and bounded public cache
    exact_inputs: [public APIs, pinned public repositories, source policy]
    preconditions: [corpus sandbox and schemas]
    expected_result: source facts with offsets, hashes, dates, terms and contradictions
    focused_checks: [prompt injection, stale open status, DOI collision, robots and license]
    affected_checks: [LawMiner and Formal Verification Lab]
    maximums: {raw_corpus_in_privileged_prompt: 0}
    stop_conditions: [terms prohibit requested use, source cannot be attributed]
    terminal_receipt: KnowledgeLayerReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [API terms, source revision, extraction policy change]
  forbidden_actions: [full forbidden mirror, treat website status as final truth]
  next_action: S15
~~~

### S15 — Law discovery and dynamical systems packs

~~~yaml
stage:
  id: S15
  dependencies: [S14]
  goal: implement LawMiner and dynamical discovery with null and holdout honesty
  scope_in: [PySR, SR4MDL, Operon, gplearn, AI-Feynman, PySINDy, PyDMD, pyKoopman, dysts]
  scope_out: [automatic promotion of discovered laws]
  write_set: [configs/packs/discovery, src/srl/products/lawminer, tests/discovery]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: PACK_CARDS_TO_VALIDATED_DISCOVERY_PRODUCT
  primary_evidence: [synthetic truth recovery, null tests, leakage fixtures]
  executable_action:
    tool_or_command: implement common candidate-law protocol and independent validation adapters
    working_directory_or_target: bounded M1 profile and node profile
    exact_inputs: [pinned packs, preregistered synthetic datasets]
    preconditions: [P0 core and knowledge layer]
    expected_result: candidate laws separated from validation and promotion
    focused_checks: [leakage, overfit, unit violation, surrogate/null, seed sensitivity]
    affected_checks: [export and products]
    maximums: {automatic_promotions: 0}
    stop_conditions: [training/holdout leakage, missing resource bound]
    terminal_receipt: LawMinerValidationReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [dataset, algorithm, seed policy or validation policy change]
  forbidden_actions: [rename above-null observation as validated law]
  next_action: S16
~~~

### S16 — Geometry, topology, probability, causal and optimization packs

~~~yaml
stage:
  id: S16
  dependencies: [S15]
  goal: complete Geometry and Physics Compiler and Causal Economy Lab foundations
  scope_in: [GUDHI, ripser, geomstats, POT, pymanopt, KeplerMapper, TopoNetX, Regina, PyMC, ArviZ, DoWhy, Tigramite, EconML, CVXPY, JAXopt, BoTorch]
  scope_out: [unbounded MCMC, causal claims without identification]
  write_set: [configs/packs/applied, src/srl/products, tests/applied]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: ISOLATED_PACKS_TO_COMPOSED_APPLIED_PRODUCTS
  primary_evidence: [benchmark corpus, diagnostic honesty, solver/license matrix]
  executable_action:
    tool_or_command: implement admitted adapters and cross-domain result composition
    working_directory_or_target: bounded M1 and compatible node profiles
    exact_inputs: [pinned packs, synthetic and public fixtures]
    preconditions: [runner, P0 and knowledge layers]
    expected_result: explicit assumptions, diagnostics, uncertainty and solver status
    focused_checks: [topology nulls, MCMC diagnostics, causal falsification, solver mismatch]
    affected_checks: [products and export]
    maximums: {default_mcmc_chains_on_m1: 1, silent_solver_fallbacks: 0}
    stop_conditions: [diagnostics missing, unidentified causal effect presented as estimate]
    terminal_receipt: AppliedScienceAdmissionBundle/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [pack, solver, license or diagnostic policy change]
  forbidden_actions: [hide solver license, suppress inconclusive result]
  next_action: S17
~~~

### S17 — SciML and domain-science packs

~~~yaml
stage:
  id: S17
  dependencies: [S16]
  goal: admit Julia/Python SciML and domain packs under reproducible environments
  scope_in: [SciML, ModelingToolkit, DataDrivenDiffEq, diffrax, QuTiP, Cadabra, Astropy, Cantera, PyBaMM, quimb, cotengra]
  scope_out: [large accelerator runs]
  write_set: [configs/packs/sciml, configs/packs/domain, src/srl/packs, tests/sciml]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: PROFILE_CARDS_TO_REPRODUCIBLE_SCIML_DOMAIN_PACKS
  primary_evidence: [Julia manifest hashes, Python locks, cross-language fixtures]
  executable_action:
    tool_or_command: build separate Julia and Python environments with common result adapters
    working_directory_or_target: T7 work and node-compatible profiles
    exact_inputs: [pinned manifests, units and solver fixtures]
    preconditions: [supply-chain and products foundation]
    expected_result: reproducible domain results with units, solver and tolerance provenance
    focused_checks: [cross-language tolerance, environment isolation, resume]
    affected_checks: [Geometry and Physics Compiler, catalog]
    maximums: {shared_mutable_global_depots: 0}
    stop_conditions: [unfrozen Julia resolution, unit loss]
    terminal_receipt: SciMLDomainAdmissionBundle/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [Julia manifest, Python lock, solver or tolerance change]
  forbidden_actions: [reuse mutable global environment, claim bitwise identity across solvers]
  next_action: S18
~~~

### S18 — PDE, HPC, Sage and budgeted remote oracles

~~~yaml
stage:
  id: S18
  dependencies: [S17]
  goal: preserve full heavy capability through bounded local probes and remote-capability routing
  scope_in: [PETSc, FEniCSx, pyMOR, scikit-fem, Dedalus, Modulus, neural operators, SageMath, Wolfram adapter]
  scope_out: [unbounded M1 workload, implicit paid calls]
  write_set: [configs/packs/heavy, src/srl/runtime/remote, tests/heavy, docs/operations/compute-node.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: HEAVY_WAIT_CAPABILITY_TO_ROUTABLE_HEAVY_PROFILES
  primary_evidence: [tiny probes, remote job conformance, budget rejection fixtures]
  executable_action:
    tool_or_command: implement capability matching, tiny local profiles and signed remote job protocol
    working_directory_or_target: fixture node and bounded local sandbox
    exact_inputs: [Science Compute Node manifest, pack resource envelopes]
    preconditions: [scheduler and transport green]
    expected_result: compatible jobs run; absent node or credentials yield truthful WAIT state
    focused_checks: [architecture mismatch, checkpoint, lost node, budget zero, revoked image]
    affected_checks: [catalog, labctl, pulse]
    maximums: {implicit_spend: 0, unbounded_local_runs: 0}
    stop_conditions: [paid call without budget receipt, weak heavy fallback]
    terminal_receipt: HeavyCapabilityRoutingReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [node capability, image, credential scope or budget policy change]
  forbidden_actions: [purchase node, install credential, launch paid request]
  next_action: S19
~~~

### S19 — Shared contract child mission

~~~yaml
stage:
  id: S19
  dependencies: [S18]
  goal: reconcile domain-neutral schemas with DualContour without cross-project ownership
  scope_in: [child mission packet, shared schemas, conformance vectors]
  scope_out: [direct DualContour writes]
  write_set: [SRF child request artifact, SRF conformance adapters]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: LOCAL_CONTRACTS_TO_CROSS_PROJECT_CONFORMANCE
  primary_evidence: [ChildMissionRequest hash, returned native closeout, conformance bundle]
  executable_action:
    tool_or_command: emit signed child mission; native DualContour agent validates, PRs and returns receipt
    working_directory_or_target: SRF parent plus native DualContour entry
    exact_inputs: [schema hashes, golden vectors, expected compatibility]
    preconditions: [fresh DualContour fingerprint and native startup]
    expected_result: common contracts pass both repositories without domain authority leakage
    focused_checks: [producer and consumer suites, version skew, downgrade]
    affected_checks: [all cross-lab adapters]
    maximums: {parent_direct_external_writes: 0}
    stop_conditions: [fingerprint mismatch, active conflicting child writer]
    terminal_receipt: SharedContractChildCloseout/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: native repository policy, status: NATIVE_POLICY}
  invalidation_triggers: [either schema or conformance corpus changes]
  forbidden_actions: [treat shared contract as scientific truth, bypass child review]
  next_action: S20
~~~

### S20 — Market bridge implementation, inactive

~~~yaml
stage:
  id: S20
  dependencies: [S19]
  goal: implement SRF-side Market adapter reusing existing ScienceRequest/ScienceObservation and central projector
  scope_in: [export mapping, import validation, C3 semantics, health projection]
  scope_out: [Market repo mutation, activation, second ledger, trading]
  write_set: [src/srl/integrations/market, tests/integrations/market, docs/integrations/MARKET-INTEGRATION.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: EXPORT_ONLY_TO_INACTIVE_MARKET_ADAPTER
  primary_evidence: [mapping fixtures, negative authority tests, C3 import packet]
  executable_action:
    tool_or_command: implement adapters against frozen public-safe contract vectors
    working_directory_or_target: SRF worktree
    exact_inputs: [Market contract fixtures, LabExportPacket, shared schemas]
    preconditions: [shared conformance green]
    expected_result: every SRF result maps to proposal-only Market intake
    focused_checks: [authority flags, D2/D3 rejection, duplicate import, stale head]
    affected_checks: [exporter, transport, labctl]
    maximums: {market_writes: 0, live_actions: 0}
    stop_conditions: [adapter can bypass central projector or native admission]
    terminal_receipt: MarketAdapterInactiveReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [Market contract, shared schema or authority policy change]
  forbidden_actions: [start Market provider, daemon, writer, order or experiment]
  next_action: S21
~~~

### S21 — Security bridge implementation, inactive

~~~yaml
stage:
  id: S21
  dependencies: [S20]
  goal: implement SRF-side Security adapter with ebashim as sole executor
  scope_in: [sanitized request/result mapping, method evidence, C3 proposal]
  scope_out: [target data, exploit execution, direct scanner control]
  write_set: [src/srl/integrations/security, tests/integrations/security, docs/integrations/SECURITY-INTEGRATION.md]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: NO_SECURITY_ADAPTER_TO_INACTIVE_SECURITY_ADAPTER
  primary_evidence: [redaction fixtures, authority negatives, proposal packet]
  executable_action:
    tool_or_command: implement D0/D1-only advisory adapter and native-executor boundary
    working_directory_or_target: SRF worktree
    exact_inputs: [shared contracts, Security public-safe fixtures]
    preconditions: [shared conformance green]
    expected_result: scientific services available without copying sensitive targets
    focused_checks: [secret, target, exploit, prompt injection, executor bypass]
    affected_checks: [transport, classification, labctl]
    maximums: {security_actions: 0, D2_D3_transfers: 0}
    stop_conditions: [raw target material exits native cell, direct execution path]
    terminal_receipt: SecurityAdapterInactiveReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [Security contract, data policy or ebashim boundary change]
  forbidden_actions: [execute exploit, start scanner, reveal private evidence]
  next_action: S22
~~~

### S22 — Market native child mission and bridge activation

~~~yaml
stage:
  id: S22
  dependencies: [S21]
  goal: obtain native Market bridge code merged inactive, then activate only through Market authority
  scope_in: [child request, native bootstrap, adapter PR, import receipt]
  scope_out: [parent direct Market write, live trading]
  write_set: [SRF child packet and returned evidence index only]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: INACTIVE_SRF_ADAPTER_TO_NATIVE_MARKET_CHILD_RECEIPT_OR_EXACT_WAIT
  primary_evidence: [fresh Market bootstrap, child PR checks, native closeout]
  executable_action:
    tool_or_command: hand off signed child mission to Market native entry; wait and reconcile receipt
    working_directory_or_target: Market native canonical workflow, controlled by Market owner
    exact_inputs: [MarketAdapterInactiveReceipt, schema hashes, test vectors]
    preconditions: [fresh non-RED or explicitly scope-permitting native Pulse, no conflicting canonical writer]
    expected_result: BRIDGE_CODE_MERGED_INACTIVE or exact WAIT_RUNTIME_HEALTH; activation remains a separate native protected action
    focused_checks: [central projector reuse, C3-only, no order path, crash and replay]
    affected_checks: [Market native required checks]
    maximums: {parent_market_writes: 0, live_trades: 0}
    stop_conditions: [Market RED, stale context, second ledger, authority ambiguity]
    terminal_receipt: MarketBridgeChildCloseout/v1
    owner_decision:
      required: false
      decision_type_or_null: null
      authority_or_null: null
      status: NOT_REQUIRED_FOR_CHILD_PACKET_OR_INACTIVE_CODE
  invalidation_triggers: [Market HEAD, Pulse, adapter or contract change]
  forbidden_actions: [interpret broad plan approval as deploy, reboot or trading permit]
  next_action: S23; physical activation may remain WAIT_AUTHORITY
~~~

### S23 — Security native child mission and bridge activation

~~~yaml
stage:
  id: S23
  dependencies: [S22]
  goal: obtain native Security bridge merged inactive and prove safe proposal flow
  scope_in: [child request, native bootstrap, adapter PR, ebashim boundary tests]
  scope_out: [parent direct Security write, target action]
  write_set: [SRF child packet and returned evidence index only]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: INACTIVE_SRF_ADAPTER_TO_NATIVE_SECURITY_CHILD_RECEIPT_OR_EXACT_WAIT
  primary_evidence: [fresh Security bootstrap, child PR checks, native closeout]
  executable_action:
    tool_or_command: hand off signed child mission to Security native entry; wait and reconcile receipt
    working_directory_or_target: Security native workflow, controlled by Security owner
    exact_inputs: [SecurityAdapterInactiveReceipt, schema hashes, redaction vectors]
    preconditions: [native health permits bounded code work, no conflicting writer]
    expected_result: bridge merged inactive or exact WAIT_SECURITY_HEALTH; ebashim remains sole executor
    focused_checks: [D2/D3 containment, authority negatives, replay, audit chain]
    affected_checks: [Security native required checks]
    maximums: {parent_security_writes: 0, target_actions: 0}
    stop_conditions: [native STOP, sensitive leak, executor bypass]
    terminal_receipt: SecurityBridgeChildCloseout/v1
    owner_decision:
      required: false
      decision_type_or_null: null
      authority_or_null: null
      status: NOT_REQUIRED_FOR_CHILD_PACKET_OR_INACTIVE_CODE
  invalidation_triggers: [Security HEAD, health, policy or adapter change]
  forbidden_actions: [run security action from SRF result]
  next_action: S24
~~~

### S24 — Physical T7 profile and optional Science Compute Node

~~~yaml
stage:
  id: S24
  dependencies: [S23]
  goal: prepare exact physical-binding packet and reconcile any already-authorized target receipt
  scope_in: [binding specification, read-only capability probe, quota, ownership, encryption status, node registration]
  scope_out: [formatting, destructive migration, hardware purchase, unauthorized target write]
  write_set: [SRF target-binding request artifact and returned evidence index only]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: FIXTURE_PROFILE_TO_BINDING_PACKET_AND_REAL_RECEIPT_OR_EXACT_WAIT
  primary_evidence: [binding packet hash, read-only capability probe, optional native target receipt]
  executable_action:
    tool_or_command: emit signed target-binding request; perform read-only preflight; reconcile a native receipt if one already exists
    working_directory_or_target: SRF parent and declared external target owner
    exact_inputs: [storage policy, tested adapter, target identity when safely discoverable]
    preconditions: [S04, S06, S09 and S18 green]
    expected_result: binding packet plus real native receipt or truthful WAIT_T7_BINDING / WAIT_COMPUTE_NODE
    focused_checks: [wrong volume, free-space reserve, cold/work split, architecture]
    affected_checks: [restore drill, heavy pack probes]
    maximums: {t7_allocation_gib: 400, minimum_free_reserve_gib: 100}
    stop_conditions: [wrong target, destructive requirement, insufficient reserve]
    terminal_receipt: PhysicalCapabilityBindingPacketReceipt/v1
    owner_decision:
      required: false
      decision_type_or_null: null
      authority_or_null: null
      status: NOT_REQUIRED_FOR_PACKET_AND_READ_ONLY_PREFLIGHT
  invalidation_triggers: [volume UUID, filesystem, node identity or capacity change]
  forbidden_actions: [format, erase, overwrite restore target, buy cloud or hardware]
  next_action: S25; independent software validation continues if capability waits
~~~

### S25 — Full-system validation, chaos and solo-agent acceptance

~~~yaml
stage:
  id: S25
  dependencies: [S24]
  goal: prove standalone and cross-lab contract behavior under success and failure
  scope_in: [all interfaces, packs, transport, recovery, child receipts, fresh agent]
  scope_out: [live trading, target execution, unbounded heavy job]
  write_set: [tests/e2e, tests/adversarial, docs/verification, generated evidence manifest]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: COMPONENT_GREEN_TO_SYSTEM_ACCEPTED
  primary_evidence: [test manifest, chaos receipts, solo-agent transcripts, restore receipt]
  executable_action:
    tool_or_command: run layered validation matrix from unit through bounded end-to-end
    working_directory_or_target: isolated SRF worktree, fixtures and registered safe profiles
    exact_inputs: [exact candidate tree, all locks, manifests, schemas and receipts]
    preconditions: [required component stages green; WAIT capabilities excluded honestly]
    expected_result: all required gates green and limitations machine-visible
    focused_checks: [fresh-agent use, crash, duplicate, revoke, corrupt, stale, injection, low disk]
    affected_checks: [full repository test and public-boundary suite]
    maximums: {live_actions: 0, ambiguous_provider_retries: 0}
    stop_conditions: [candidate-specific evidence missing, flaky test concealed]
    terminal_receipt: SystemAcceptanceReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [any identity-sensitive candidate change]
  forbidden_actions: [reuse predecessor evidence across changed sensitive paths]
  next_action: S26
~~~

### S26 — Documentation closure and generated drift gates

~~~yaml
stage:
  id: S26
  dependencies: [S25]
  goal: make every operational and scientific path reconstructible by one agent
  scope_in: [all docs, manifests, diagrams, failure routing, examples, drift checks]
  scope_out: [undocumented manual procedure]
  write_set: [docs, generated catalogs, docs tests]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: DOCUMENTED_COMPONENTS_TO_SELF_DESCRIBING_SYSTEM
  primary_evidence: [doc generation check, link check, fresh-agent acceptance]
  executable_action:
    tool_or_command: generate and verify complete system documentation from manifests and schemas
    working_directory_or_target: SRF worktree
    exact_inputs: [accepted candidate, all manifests and receipts]
    preconditions: [system acceptance green]
    expected_result: no undocumented capability, authority boundary or recovery path
    focused_checks: [START-HERE, SYSTEM-ATLAS, CAPABILITY-CATALOG, CONTRACT-MATRIX, FAILURE-ROUTING]
    affected_checks: [public boundary, CLI examples]
    maximums: {manual_duplicate_capability_tables: 0}
    stop_conditions: [docs drift from machine truth]
    terminal_receipt: DocumentationClosureReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: null, status: NOT_REQUIRED}
  invalidation_triggers: [manifest, schema, CLI or runbook behavior change]
  forbidden_actions: [embed owner paths, secrets or volatile private health]
  next_action: S27
~~~

Required documents:

- START-HERE.md
- SYSTEM-ATLAS.md
- SOLO-AGENT-RUNBOOK.md
- CELL-MATRIX.md
- CAPABILITY-CATALOG.md
- CONTRACT-MATRIX.md
- AUTHORITY-MATRIX.md
- DATA-CLASSIFICATION.md
- FAILURE-ROUTING.md
- T7-OPERATIONS.md
- COMPUTE-NODE.md
- MARKET-INTEGRATION.md
- SECURITY-INTEGRATION.md
- TRADING-EXECUTION-BOUNDARY.md
- PACK-AUTHORING.md
- PACK-REVOCATION.md
- RECOVERY-RUNBOOK.md
- RELEASE-RUNBOOK.md

### S27 — Candidate PR, independent review and merge

~~~yaml
stage:
  id: S27
  dependencies: [S26]
  goal: deliver the exact accepted candidate through repository-native governance
  scope_in: [commit series, PR, CI, independent review, squash merge]
  scope_out: [branch protection bypass, force push, unrelated changes]
  write_set: [one codex branch, one pull request]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: ACCEPTED_CANDIDATE_TO_MAIN_MERGED
  primary_evidence: [candidate SHA/tree, PR URL, required checks, review, merge SHA]
  executable_action:
    tool_or_command: create focused commits, push branch, open ready PR, enable native auto-merge when eligible
    working_directory_or_target: SRF GitHub repository
    exact_inputs: [SystemAcceptanceReceipt, DocumentationClosureReceipt, candidate tree]
    preconditions: [clean worktree, complete closeout draft, no unrelated diff]
    expected_result: squash merge to main with all governance checks
    focused_checks: [old and new verifier for governance-sensitive changes, exact CI]
    affected_checks: [all repository required checks]
    maximums: {open_plan_prs: 1, force_pushes: 0}
    stop_conditions: [required review missing, CI red, conflict with user changes]
    terminal_receipt: MergeReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: repository native review rules, status: NATIVE_POLICY}
  invalidation_triggers: [candidate changes after final checks]
  forbidden_actions: [self-approve where independent review required, merge red]
  next_action: S28
~~~

### S28 — Reproducible release and final closeout

~~~yaml
stage:
  id: S28
  dependencies: [S27]
  goal: publish reproducible SRF release and close mission with exact residual waits
  scope_in: [version, changelog, artifacts, SBOM, signatures, closeout]
  scope_out: [claim physical activation where only code is merged]
  write_set: [release commit if required, tag, release artifacts, closeout receipt]
  write_set_project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  expected_transition: MAIN_MERGED_TO_RELEASED_AND_CLOSED
  primary_evidence: [main SHA, tag, artifact hashes, SBOM, signatures, release URL]
  executable_action:
    tool_or_command: run repository-native release workflow and verify published artifacts from clean checkout
    working_directory_or_target: SRF repository and release platform
    exact_inputs: [merged main SHA, release policy, acceptance receipts]
    preconditions: [main checks green, tag absent, release permissions available]
    expected_result: signed reproducible release plus AgentCloseoutReceipt
    focused_checks: [clean rebuild hash, install smoke, CLI/MCP schema, artifact signatures]
    affected_checks: [release CI and public boundary]
    maximums: {release_attempts_per_identity: 1, history_rewrites: 0}
    stop_conditions: [tag collision, artifact hash mismatch, missing required signature]
    terminal_receipt: MissionCloseoutReceipt/v1
    owner_decision: {required: false, decision_type_or_null: null, authority_or_null: repository release policy, status: NATIVE_POLICY}
  invalidation_triggers: [main SHA, build image or lock change]
  forbidden_actions: [retag published version, conceal WAIT_AUTHORITY integrations]
  next_action: final audit
~~~

## RECOVERY PLAYBOOK

| Failure signature | First action | Alternative approaches | Terminal condition |
|---|---|---|---|
| dependency fetch transient | one identical retry | mirror/cache, upstream artifact, source build | BLOCKED_UPSTREAM if all differ and fail |
| provider timeout before proof of dispatch | verify uncalled state | reconcile provider ledger | BLOCKED_AMBIGUOUS_DISPATCH |
| schema incompatibility | freeze producer/consumer identities | compatibility adapter, major schema child mission | BLOCKED_CONTRACT_INCOMPATIBLE |
| T7 absent | park physical binding | fixture validation, node-backed work root | WAIT_T7_BINDING |
| incompatible M1 pack | capability route | node container, budgeted API adapter | WAIT_COMPUTE_NODE |
| Market RED | preserve child packet | monitor native receipt only | WAIT_RUNTIME_HEALTH |
| Security STOP/degraded | preserve child packet | continue SRF-only validation | WAIT_SECURITY_HEALTH |
| license unclear | do not install | find official terms, replace implementation | WAIT_LICENSE |
| secret/classification hit | quarantine and stop | sanitize from original native source | BLOCKED_DATA_BOUNDARY |
| candidate CI flaky | one exact rerun | isolate nondeterminism, deterministic fixture, upstream fix | BLOCKED_NONDETERMINISM |

## DEFINITION_OF_DONE

- DOD-01: exactly one canonical SRF plan exists and both hashes verify.
- DOD-02: a fresh solo agent can orient through labctl without chat context.
- DOD-03: native cell bootstrap always precedes LabAccessReceipt.
- DOD-04: all authority-negative fields are schema-enforced and tested.
- DOD-05: every request has one idempotent lifecycle and terminal receipt.
- DOD-06: spool survives crash, duplicate, reorder, expiry and replay.
- DOD-07: receipts use Ed25519 signature, sequence and previous hash.
- DOD-08: T7 cold-CAS and mutable work namespaces are mechanically separated.
- DOD-09: 400 GiB cap and 100 GiB reserve are enforced by admission.
- DOD-10: sandbox blocks secrets, network and host writes by trust class.
- DOD-11: every active pack has locks, hashes, license, SBOM and admission.
- DOD-12: revocation prevents scheduling and import and triggers dependent recheck.
- DOD-13: M1 has no autonomous long-running runtime dependency.
- DOD-14: heavy/incompatible packs route to node or truthful WAIT state.
- DOD-15: complete P0, P1 and P2 catalog exists with no silently removed function.
- DOD-16: Lean primary and independent prover semantics are explicit.
- DOD-17: corpus injection and terms restrictions are enforced.
- DOD-18: SRFPulse is independent; FederationStatus is read-only aggregation.
- DOD-19: restore drill reconstructs unique receipts and rebuildable indexes.
- DOD-20: Market adapter is C3-only and reuses native central projector.
- DOD-21: Security adapter transfers D0/D1 only and preserves ebashim boundary.
- DOD-22: Market and Security child mutations have native closeout receipts or
  exact WAIT state; no parent direct write occurred.
- DOD-23: all required docs are generated or drift-checked from machine truth.
- DOD-24: exact candidate passes full checks, independent review, reproducible
  release and final audit.

## FINAL_AUDIT_CONTRACT

Final audit is independent of implementation author where governance requires.
It must verify:

1. Plan and state hash integrity.
2. Project fingerprint and exact merge/release identity.
3. No second canonical plan, writer, ledger, broker or orchestrator.
4. No public secret, private path, D2/D3 payload or target data.
5. No authority escalation or misleading success language.
6. Candidate-specific checks for every identity-sensitive path.
7. All pack admission, revocation and dependency DAG evidence.
8. Sandbox and corpus adversarial suites.
9. Transport crash/replay/idempotency guarantees.
10. Resource enforcement and honest WAIT capabilities.
11. T7 cold/work separation and recovery evidence.
12. Cross-project native ownership and child closeouts.
13. Solo-agent end-to-end path from each supported cell.
14. Documentation drift checks and link validation.
15. Reproducible release artifacts, SBOM and signatures.

Final terminal states:

- DONE: all DOD items proven, including required native child closeouts.
- RELEASED_WITH_DECLARED_WAITS: standalone SRF complete; only protected physical
  activation or unavailable hardware remains, explicitly machine-visible.
- BLOCKED: same exact blocker exhausted under recovery policy.

The final report must list exact IDs and hashes, never subjective percentages.

<!-- END_PLAN_CONTRACT_V3_6 -->

<!-- BEGIN_MUTABLE_STATE_V3_6 -->

STATE_REVISION: 18
PREVIOUS_STATE_SHA256: 055a8e39-ccbf186a-86917f74-b5e3e744-13cd15be-f69b5912-a756958b-5c544dac
CURRENT_STATE_SHA256: 160fc420-a13de71b-f483e9b5-e3f8f3ce-529e37cf-a746d4df-aaa206da-21cf2979

## CURRENT_FACTS

~~~yaml
current_facts:
  observed_at: 2026-07-29
  canonical_plan_conflict_status: NONE_FOUND
  baseline_project_identity:
    head: 947cbb4515307b54fe3eb9b6366cdb392361c867
    branch: main
    origin_relation: local_main_equals_origin_main
    worktree: clean
  market_dependency:
    status: READ_ONLY_RED
    blocker: DURABLE_HEALTH_DEGRADED
    gate: F8_resume_interrupted_durable_job
  implementation_started: true
~~~

## EXECUTION_STATE

~~~yaml
execution_state:
  status: IN_PROGRESS
  current_stage: S17
  next_stage: S18_after_sciml_domain
  completed_stages: [S00_plan_content_written, S00_exact_hash_review_approved, S01_baseline_truth_proven, S02_solo_agent_bootstrap_proven, S03_contract_kernel_proven, S04_storage_fabric_validated, S05_reliable_spool_transport_proven, S06_sandbox_boundary_proven, S07_pack_governance_proven, S08_runner_scheduler_proven, S09_health_recovery_proven, S10_interface_convergence_proven, S11_p0_core_proven, S12_lean_primary_proven, S13_cross_prover_proven, S14_knowledge_layer_proven, S15_lawminer_proven, S16_applied_science_proven]
  invalidated_stages: []
  exact_identity: 947cbb4515307b54fe3eb9b6366cdb392361c867
  last_proven_transition: applied_science_packs_proven
  active_branch_or_null: codex/srf-fabric-v1
  active_pr_or_null: null
  active_worktree_or_null: isolated_codex_worktree
  writer_lease_or_null: srf-fabric-v1-single-writer
  active_operation_or_null: S17_sciml_domain_science_packs
  active_process_or_job_or_null: null
  next_checkpoint: after_S17_sciml_domain_admission_receipt
  next_executable_action: admit Julia/Python SciML and domain packs under reproducible environments
  blocker_or_null: null
  updated_at: 2026-07-29
~~~

## STATE_CAPSULE

~~~yaml
state_capsule:
  project_id: scientific-resource-lab
  project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  mission_id: build-scientific-reasoning-fabric-v1
  stage_id: S17
  state_revision: 18
  exact_identity: 947cbb4515307b54fe3eb9b6366cdb392361c867
  last_proven_transition: applied_science_packs_proven
  active_operation: S17_sciml_domain_science_packs
  active_process_or_job: null
  frozen_preimages:
    - baseline HEAD
    - repository governance
    - operator-supplied V3.6 protocol
  new_primary_evidence:
    - AppliedScienceAdmissionReceipt 2126e15b-7963a97e-d4d63834-792bed31-3270dcf9-98b9f9a7-14661450-6f443261
    - AppliedScienceAdmissionBundle sha256:51d0d0e5-78ab0d5d-012a02d7-df40d5b3-0917a11b-885fcd0d-879ed0b7-3fb9ab83
    - ripser, pyriemann and cvxpy admitted as ACTIVE bounded local applied packs
    - GUDHI, geomstats, POT, pymanopt, KeplerMapper, TopoNetX, Regina, PyMC, ArviZ, DoWhy, Tigramite, EconML, JAXopt and BoTorch recorded as WAIT_CAPABILITY
    - applied result receipts require assumptions, diagnostics and solver status
    - unidentified causal effects are rejected when an effect estimate is supplied
    - applied result receipts remain authority-negative and canonical_writes=0
    - focused applied product and adapter tests PASS with 140 passed and 1 skipped
    - make test PASS with 1859 passed and 1 skipped
    - make lint PASS
    - make typecheck PASS
  next_executable_action: S17 SciML and domain-science packs
  blocker_or_null: null
  updated_at: 2026-07-29
~~~

## EVIDENCE_INDEX

~~~yaml
evidence_index:
  - claim: project identity
    source: local Git and origin
    identity: 947cbb4515307b54fe3eb9b6366cdb392361c867
  - claim: no existing SRF canonical master-plan found in bounded repository search
    source: repository file inventory
    invalidates_on: new plan file or registry claim
  - claim: exact-hash review approved
    source: marker-bounded SHA-256 verifier
    identity: 947d1858c8cf110f3c6bdb07c70a8ff132459f9e7b6448d1afbf84d4270c1ff0
  - claim: S01 baseline truth proven
    source: AgentBootstrapReceipt and DiscrepancyLedger
    identity: 5e89e9d35fcbc83a0079b34dfe2f327ff07b0bfefb50597bb5fe5a520bd2e10c
  - claim: S01 discrepancy ledger sealed
    source: DiscrepancyLedger/v1
    identity: 09484b5183da84f426370d27191aab6a93bc74132c350b909019c90080d3af46
  - claim: S02 solo-agent bootstrap proven
    source: SoloAgentBootstrapDesignReceipt/v1
    identity: c284d65b8b0dd8debc9e9e585b7d0a4f41e90379fe429ceb5d0f45f68cbb80e6
  - claim: S03 contract kernel proven
    source: ContractKernelReceipt/v1
    identity: 29af2e796dd11af2940c5293d5797292e23705ff5219e462af2f5fc413a3d0c3
  - claim: S04 storage fabric validated
    source: StorageFabricValidationReceipt/v1
    identity: 9481a281f1a66ec544d71a2542c297c7b8fb292c19fd63c3d4409eac40c9d0bd
  - claim: S05 reliable spool transport proven
    source: TransportConformanceReceipt/v1
    identity: ebcc66c557998ed0ba292b392532a1ed7d385fdbc38d5e6afc0bf4fc1a0859ed
  - claim: S06 sandbox boundary proven
    source: SandboxValidationReceipt/v1
    identity: b2bb63de-e3c202cf-345b78e2-431d54b8-9890cb72-70ee9146-96ddfb99-a9764c3d
  - claim: S07 pack governance proven
    source: PackGovernanceReceipt/v1
    identity: 73968fe5-9b961600-40c14e0b-03b6873a-0b7af1ed-b4c93668-1b1175b5-77e211cb
  - claim: S08 runner scheduler proven
    source: RunnerConformanceReceipt/v1
    identity: ce425ad7-37745abf-c4a26441-bc96ddac-244c64fc-0d05e7e4-1b48a5ee-f73eebac
  - claim: S09 health and recovery proven
    source: HealthAndRecoveryReceipt/v1
    identity: dd7e5233-44698068-a686ef20-b9725301-9830352a-e8d0942b-abbfc483-1d7e1a27
  - claim: S10 interface convergence proven
    source: InterfaceConvergenceReceipt/v1
    identity: be999a0f-61f07901-62d96a44-28035147-ade36978-e07050aa-0e5f5e82-6cfea448
  - claim: S11 P0 core admission proven
    source: P0CoreAdmissionReceipt/v1
    identity: 9517a304-74b48a50-766d7570-c6c1521c-8aa645fc-0ff92324-11479b40-e03078e9
  - claim: S12 Lean primary formal environment proven
    source: LeanAdmissionReceipt/v1
    identity: 685653b0-e12407ec-db6a11f0-adeef991-7744d2af-89dc6ee8-a2267f95-25c7d527
  - claim: S13 cross-prover contours proven with declared waits
    source: CrossProverAdmissionReceipt/v1
    identity: 59bafa9a-6972eaea-bb0f49ad-0e1ea743-1a12c1ce-9c95208a-4327a284-a122ec4b
  - claim: S14 knowledge layer proven with declared waits
    source: KnowledgeLayerReceipt/v1
    identity: d0292caf-1ef6db10-7b5a80ac-77ac063c-6f40573c-0407f988-79f58213-1055d841
  - claim: S15 LawMiner and dynamical discovery proven with declared waits
    source: LawMinerValidationReceipt/v1
    identity: 5267df4e-3070c277-c007a48d-e4bb0d3c-01f275ff-74cb5860-7d9c8147-caebad47
  - claim: S16 applied science packs proven with declared waits
    source: AppliedScienceAdmissionReceipt/v1
    identity: 2126e15b-7963a97e-d4d63834-792bed31-3270dcf9-98b9f9a7-14661450-6f443261
  - claim: Market mutation currently forbidden
    source: native operator bootstrap
    identity: 59ce6ff4c8b514c93d8d4b26d648ba6e7dd7b764
    terminal: RED_F8
~~~

## AUTHORITY_LEDGER

~~~yaml
authority_ledger:
  routine_safe_plan_creation: exercised
  exact_hash_review_authority: exercised
  implementation_authority: exercised_routine_safe_S01_S16
  market_mutation_authority: absent
  security_mutation_authority: absent
  physical_t7_authority: absent
  compute_purchase_or_paid_api_authority: absent
~~~

## DECISION_LOG

~~~yaml
decision_log:
  - id: D001
    decision: use Scientific Reasoning Fabric as product name; retain repository and package compatibility
  - id: D002
    decision: contract federation, never repository merger
  - id: D003
    decision: public-safe master plan plus owner-private runtime overlay
  - id: D004
    decision: T7 cold immutable CAS separated from mutable rebuildable work
  - id: D005
    decision: M1 is bounded B2 batch terminal; long jobs require Science Compute Node
  - id: D006
    decision: existing JSON and rsync-over-SSH transport; no SFTP, broker or second daemon
  - id: D007
    decision: Market and Security mutations are native child missions
  - id: D008
    decision: WBP is excluded
  - id: D009
    decision: S02 leaves AGENTS.md untouched because it is governance-protected; labctl docs and CLI carry the solo-agent bootstrap contract
  - id: D010
    decision: Cross-lab labctl entries are proposal-only WAIT_NATIVE_BOOTSTRAP projections until native child missions return receipts
  - id: D011
    decision: S03 ships minimal strict envelope schemas before runtime implementation; later stages implement storage, transport, health and scheduling behavior against these fail-closed contracts
  - id: D012
    decision: S04 implements filesystem-neutral SRF layout and quota admission on fixture roots while preserving physical T7 binding as WAIT until native target receipt exists
  - id: D013
    decision: S05 implements local file-spool transport only; no broker, daemon, shared database, SFTP route or polling loop is introduced
  - id: D014
    decision: S05 ships a fail-closed detached signature verifier interface with deterministic test-hmac-sha256 conformance signer; native Ed25519 key binding remains WAIT_NATIVE_KEY_BINDING until an authorized keyring exists
  - id: D015
    decision: S05 preserves the native secret-scan regex and adds exact allowlist entries only for declared public SHA-256 evidence and SRF fingerprint literals that triggered long_hex false positives after staging
  - id: D016
    decision: S06 extends the existing execution runner with a separate trust-class sandbox admission policy instead of creating a second runtime or claiming unproven Mac isolation
  - id: D017
    decision: S06 treats T2/T3 missing container, microVM, network-deny or taint capabilities as WAIT_COMPUTE_NODE and treats T4 missing budget/provider authority as WAIT_AUTHORITY
  - id: D018
    decision: S07 keeps production packs out of ACTIVE until complete SBOM, lock, vulnerability, license and admission evidence exists; current packs remain usable inventory records but not governed ACTIVE packs
  - id: D019
    decision: S08 adds an explicit-dispatch scheduler over the existing runner/materializer/sealer stack rather than starting a Mac daemon or creating a second execution path
  - id: D020
    decision: S09 makes SRFPulse independent and FederationStatus read-only; live T7 restore and destructive recovery operations remain WAIT_AUTHORITY
  - id: D021
    decision: S10 uses a shared read-only InterfaceService for common CLI, MCP and portal semantics while leaving each surface responsible only for transport/framing/rendering
  - id: D022
    decision: S11 admits P0 components by truthful per-engine ACTIVE, DEGRADED or WAIT_CAPABILITY evidence and preserves independent solver disagreement instead of substituting z3 for cvc5
  - id: D023
    decision: S12 pins Lean/mathlib to the stable v4.32.2 line and records kernel acceptance only for the declared formal statement, not as empirical evidence or external-formalization correctness
  - id: D024
    decision: S13 ships independent formal contours as explicit ACTIVE or WAIT_TOOLCHAIN records and rejects automatic cross-logic theorem equivalence claims
  - id: D025
    decision: S14 layers taint-safe source-grounded graph manifests over existing retriever adapters and records missing corpus/source adapters as explicit WAIT states
  - id: D026
    decision: S15 uses a bounded deterministic LawMiner baseline to prove null, leakage and candidate-only semantics while advanced symbolic and dynamical engines remain explicit WAIT_CAPABILITY
  - id: D027
    decision: S16 admits only already bounded local applied adapters as ACTIVE and keeps missing topology, probability, causal and optimization engines in WAIT_CAPABILITY while enforcing assumptions, diagnostics, solver status and unidentified-causal-effect guards
~~~

## PROGRESS_LOG

~~~yaml
progress_log:
  - revision: 1
    stage: S00
    result: plan content created and integrity hashes verified
    observed_at: 2026-07-29
  - revision: 2
    stage: S00
    result: declaration-only hash recovery approved; plan advanced to S01
    observed_at: 2026-07-29
  - revision: 3
    stage: S01
    result: baseline truth proven; bootstrap, lint, tests, public-boundary and secret scan passed
    observed_at: 2026-07-29
  - revision: 4
    stage: S02
    result: solo-agent labctl entry, generated bootstrap docs and tests proven
    observed_at: 2026-07-29
  - revision: 5
    stage: S03
    result: contract kernel expanded to federation/access/transport/health envelope schemas with schema and receipt gates green
    observed_at: 2026-07-29
  - revision: 6
    stage: S04
    result: storage fabric layout, immutable cold-cas guard and quota admission validated on fixture roots
    observed_at: 2026-07-29
  - revision: 7
    stage: S05
    result: reliable spool transport validated with signed import, dedup, TTL, quarantine, DLQ, deterministic replay, reorder and tamper tests
    observed_at: 2026-07-29
  - revision: 8
    stage: S06
    result: trust-class sandbox admission validated; T2/T3 weak fallback absent, T4 authority parked, adversarial runner gate passed
    observed_at: 2026-07-29
  - revision: 9
    stage: S07
    result: pack governance validated; manifest v2 projection, revocation, license, vulnerability and complete-admission gates proven
    observed_at: 2026-07-29
  - revision: 10
    stage: S08
    result: durable explicit-dispatch scheduler validated; WIP=1, resume, cancel, backpressure, stale-pack wait, resource wait and sealed-result invariants proven
    observed_at: 2026-07-29
  - revision: 11
    stage: S09
    result: independent SRFPulse, read-only FederationStatus, deterministic tracing and bounded restore drill validated
    observed_at: 2026-07-29
  - revision: 12
    stage: S10
    result: CLI, MCP and portal common semantics routed through shared InterfaceService and parity-tested
    observed_at: 2026-07-29
  - revision: 13
    stage: S11
    result: P0 admission bundle proven with NumPy, SciPy, Pint and Z3 ACTIVE, cvc5 DEGRADED, advanced engines WAIT_CAPABILITY and authority-negative tests green
    observed_at: 2026-07-29
  - revision: 14
    stage: S12
    result: Lean v4.32.2 and mathlib v4.32.2 primary formal environment proven with real Mathlib smoke, invalid-proof rejection, tests, lint and typecheck green
    observed_at: 2026-07-29
  - revision: 15
    stage: S13
    result: Cross-prover contour layer proven with Lean ACTIVE, Rocq/Isabelle/HOL4 WAIT_TOOLCHAIN and semantic-gap manifests rejecting equivalence claims
    observed_at: 2026-07-29
  - revision: 16
    stage: S14
    result: Knowledge graph and taint layer proven with active bounded sources, declared source waits, prompt-injection detection and raw-corpus prompt boundary
    observed_at: 2026-07-29
  - revision: 17
    stage: S15
    result: LawMiner and dynamical validation layer proven with candidate-only receipts, null controls, leakage rejection and explicit advanced-engine waits
    observed_at: 2026-07-29
  - revision: 18
    stage: S16
    result: Applied science packs proven with ripser, pyriemann and cvxpy active; missing engines parked as WAIT_CAPABILITY; diagnostics, solver status and causal-identification guards enforced
    observed_at: 2026-07-29
~~~

## POST_RELEASE_ASSURANCE

~~~yaml
post_release_assurance:
  scheduled: false
  required_after_release:
    - dependency and vulnerability refresh cadence
    - pack revocation feed check
    - schema consumer conformance
    - bounded restore drill
    - documentation drift check
    - capability and footprint remeasurement
  note: scheduling belongs to an always-on approved runtime, never the operator Mac
~~~

<!-- END_MUTABLE_STATE_V3_6 -->

## Хеширование и проверка

PLAN_CONTRACT_SHA256 вычисляется по точным UTF-8 bytes между immutable
markers, не включая строки markers.

В этом PUBLIC_SAFE документе 256-bit digest values отображаются восемью
группами по восемь hex-символов. Для машинного сравнения группирующие дефисы
удаляются; нормализованное значение состоит из 64 lowercase hex-символов.

CURRENT_STATE_SHA256 вычисляется по точным UTF-8 bytes между mutable markers,
не включая строки markers и после удаления только полной строки
CURRENT_STATE_SHA256.

Любое изменение immutable contract:

1. возвращает PLAN_REVIEW в DRAFT;
2. очищает approved hash;
3. пересчитывает PLAN_CONTRACT_SHA256;
4. не переписывает старую execution history.

Каждое изменение mutable state:

1. проверяет текущий hash;
2. копирует его в PREVIOUS_STATE_SHA256;
3. увеличивает STATE_REVISION;
4. применяет один proven transition;
5. пересчитывает CURRENT_STATE_SHA256;
6. перечитывает файл и повторно проверяет hash.
