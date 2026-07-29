# Scientific Reasoning Fabric: Activation Master Plan V3.7

STATUS: FINAL_CONTENT / PLAN_ONLY / A00_APPROVED
PLAN_ID: SRF-ACTIVATION-2026-07-29-V3.7
MISSION_ID: activate-scientific-reasoning-fabric-v2
PROJECT_ID: scientific-resource-lab
PRODUCT_NAME: Scientific Reasoning Fabric
PLAN_CLASSIFICATION: PUBLIC_SAFE
AUTONOMY_CONTRACT_VERSION: V3.7
PROJECT_STANDING_AUTHORITY: FULL_IN_SCOPE
USER_APPROVAL_GATES_FOR_ROUTINE_WORK: 0
TARGET_RELEASE: v2.0.0
PLAN_CONTRACT_SHA256: 170e5a47-2d5c0dcc-b6713f7c-8c9228f4-51f86691-be281544-d92b445c-0a594a5c

## Зачем нужен новый план

V3.6 успешно построил и выпустил контрактный каркас SRF v1.0.1, но допустил
ошибочную семантику закрытия: стадия считалась выполненной, когда существовали
adapter, config, fixture и честный WAIT_CAPABILITY, даже если реальный научный
инструмент не был установлен и не выполнял вычисления.

V3.7 сохраняет v1.0.1 как исторический foundation release и заменяет критерий
приёмки. Для каждого заявленного ресурса теперь требуются реальная среда,
исполняемый probe, нефикстурный bounded scientific run, provenance и
воспроизводимый receipt. WAIT_CAPABILITY для software, входящего в scope,
является открытой работой, а не терминальным успехом.

## PLAN_REVIEW

~~~yaml
PLAN_REVIEW:
  status: APPROVED
  reviewed_by_or_null: codex-independent-exact-hash-review
  reviewed_at_or_null: 2026-07-29T05:45:00Z
  review_findings:
    - exact PLAN_CONTRACT_SHA256 verified for normalized repository plan artifact
    - exact CURRENT_STATE_SHA256 verified before A00 mutable transition
    - pasted operator plan copy had line-wrap drift and is not the executable artifact
    - V3.6 preserved and marked SUPERSEDED_FOR_EXECUTION
    - no second active plan writer found
  approved_plan_contract_sha256_or_null: 170e5a47-2d5c0dcc-b6713f7c-8c9228f4-51f86691-be281544-d92b445c-0a594a5c
~~~

<!-- BEGIN_PLAN_CONTRACT_V3_7 -->
## CONTROL

~~~yaml
control:
  plan_id: SRF-ACTIVATION-2026-07-29-V3.7
  mission_id: activate-scientific-reasoning-fabric-v2
  predecessor_plan_id: SRF-MASTER-2026-07-29-V3.6
  predecessor_release: v1.0.1
  predecessor_terminal_state: RELEASED_WITH_DECLARED_WAITS
  supersedes_predecessor_executable_ownership: true
  preserves_predecessor_history: true
  run_mode: PLAN_ONLY
  canonical_claim: true
  mutation_concurrency: 1
  writer_concurrency: 1
  plan_owned_branch_concurrency: 1
  physical_mutation_chain_concurrency: 1
  same_signature_rerun_max: 1
  materially_different_recovery_approaches_max: 3
  checkpoint_interval_active_minutes: 25-40
  subjective_progress_percentages: forbidden
  release_before_acceptance: forbidden
~~~

## PROJECT_BINDING

~~~yaml
project_binding:
  project_id: scientific-resource-lab
  canonical_origin: https://github.com/KirPonomarev/scientific-resource-lab.git
  default_branch: main
  baseline_head: dc0ceca30c22d30916828c6b37c77962aeec7b66
  baseline_release: v1.0.1
  baseline_relation: local_main_equals_origin_main
  baseline_worktree: clean
  project_fingerprint: d56e03d0-d5e1a9bb-9c33a008-ab989510-2d8e41e8-bfd001df-bfc8e1c8-0b9df0b3
  mutation_owner: scientific-resource-lab
  external_projects:
    - DualContour: native_child_mission_only
    - Crypto Market Lab: native_child_mission_only
    - Security Researcher: native_child_mission_only
~~~

## MISSION

Преобразовать выпущенный контрактный каркас v1.0.1 в физически работающий
Scientific Reasoning Fabric v2.0.0:

- реальные scientific packs установлены в изолированных T7 environments;
- обязательные локальные и формальные контуры выполняют настоящие задачи;
- тяжёлые контуры выполняются на зарегистрированном compute target;
- production transport использует реальную подпись, а не fixture HMAC;
- sandbox не только описывает policy, но реально применяет ограничения;
- T7 является физическим work/CAS target с проверенным restore;
- одиночный агент вызывает capabilities через единый labctl;
- Market, Security и DualContour подключены контрактами без слияния канонов;
- ни один result не получает authority на торговлю, security action или
  canonical promotion.

## SCOPE

### Входит

- исправление acceptance semantics и governance checks;
- T7 work, cold-CAS, quarantine, spool и restore-test namespaces;
- production signing and verification;
- enforced subprocess/container/remote isolation;
- durable scheduler and crash/resume;
- P0, P1, P2 и domain pack installation and activation;
- Lean, Rocq, Isabelle/HOL and HOL4 contours;
- CSLib, Erdős Problems and Formal Conjectures;
- live public scientific metadata adapters;
- LawMiner, Formal Verification Lab, Geometry and Physics Compiler,
  Causal Economy Lab and Literature-to-Knowledge Graph;
- standalone, Market and Security solo-agent entry paths;
- shared-contract native child closeout;
- system validation, disaster recovery and v2.0.0 release.

### Не входит

- live trading or orders;
- target-specific security execution;
- secret installation without exact native authority;
- paid API spend without budget receipt;
- hardware purchase without target-scoped authority;
- bypass of native bootstraps or branch protection;
- private research data in public Git;
- WBP;
- second broker, ledger, provider loop or orchestrator.

## ИСПРАВЛЕННАЯ СЕМАНТИКА ГОТОВНОСТИ

Каждая capability проходит только такую лестницу:

~~~text
DECLARED
  -> ADAPTER_IMPLEMENTED
  -> ENVIRONMENT_LOCKED
  -> INSTALLED
  -> EXECUTABLE_PROBED
  -> SCIENTIFIC_SMOKE_PASSED
  -> CROSSCHECKED
  -> ACTIVE
~~~

Значения:

- DECLARED: существует schema, card или config.
- ADAPTER_IMPLEMENTED: есть код и hermetic tests.
- ENVIRONMENT_LOCKED: зафиксированы source, lock, hashes, license and SBOM.
- INSTALLED: bytes физически установлены в целевой isolated environment.
- EXECUTABLE_PROBED: import или native executable реально запущен.
- SCIENTIFIC_SMOKE_PASSED: выполнена bounded нефикстурная научная задача.
- CROSSCHECKED: результат проверен независимым методом там, где это требуется.
- ACTIVE: scheduler может выбрать pack и получить signed run receipt.

Только ACTIVE закрывает pack acceptance.

Запрещено:

- считать config или MethodCard реализацией;
- считать fixture-only path production execution;
- закрывать software stage состоянием WAIT_CAPABILITY;
- считать route-to-WAIT тяжёлым compute;
- считать pinned version установленным toolchain;
- считать зелёный unit test доказательством наличия external executable;
- выпускать v2.0.0 при mandatory WAIT_CAPABILITY, WAIT_TOOLCHAIN,
  fixture signer или policy-only sandbox.

## КЛАССЫ WAIT

### Non-terminal internal waits

Эти состояния никогда не закрывают stage и не позволяют final release:

- WAIT_CAPABILITY для software pack из каталога;
- WAIT_TOOLCHAIN для Lean/Rocq/Isabelle/HOL4;
- WAIT_ADAPTER;
- WAIT_INSTALL;
- WAIT_LICENSE_RESEARCH;
- WAIT_TEST_ENVIRONMENT;
- WAIT_PRODUCTION_SIGNER;
- WAIT_SANDBOX_IMPLEMENTATION.

### External protected waits

Эти состояния могут временно парковать только соответствующую lane:

- WAIT_T7_AUTHORITY для физической namespace mutation;
- WAIT_COMPUTE_TARGET или WAIT_HARDWARE_PURCHASE;
- WAIT_PAID_API_CREDENTIAL_OR_BUDGET;
- WAIT_RUNTIME_HEALTH для чужого runtime;
- WAIT_TARGET_SCOPED_SECURITY_AUTHORITY;
- WAIT_NATIVE_CHILD_CLOSEOUT, если child owner недоступен.

External WAIT не превращается в DONE. Агент продолжает независимые stages.
MissionCloseout разрешён только как BLOCKED с точным decision packet либо DONE.
Терминал RELEASED_WITH_DECLARED_WAITS для этой mission запрещён.

## ФАКТИЧЕСКОЕ СОСТОЯНИЕ v1.0.1

### Реально активные зависимости

| Capability | Фактический статус |
|---|---|
| NumPy | ACTIVE |
| SciPy | ACTIVE |
| Pint | ACTIVE |
| Z3 | ACTIVE |
| ripser | ACTIVE |
| pyRiemann | ACTIVE |
| CVXPY + Clarabel | ACTIVE |

### Реализован foundation, но не production-complete

| Контур | Правда |
|---|---|
| JSON contracts | Реальные schemas и validators |
| CAS layout | Реальная логика на fixture roots; T7 не привязан |
| Spool | Atomic/fsync logic есть; signer только test-hmac-sha256 |
| Sandbox | Policy engine; container/microVM не запускаются |
| Scheduler | Bounded state machine; remote executor отсутствует |
| Recovery | Fixture restore drill; второй recovery target отсутствует |
| labctl | Entry и scope logic есть; native integrations не активны |
| Market bridge | Код есть, activation_state=INACTIVE |
| Security bridge | Код есть, activation_state=INACTIVE |
| Heavy routing | Решения WAIT; реального node executor нет |

### Toolchains и packs, отсутствующие физически

- SymPy, mpmath, python-flint/FLINT, Arb/Calcium;
- PARI/GP, Maxima, GAP, Singular, cvc5;
- Lean/lake, Rocq, Isabelle/HOL, HOL4;
- PySR, SR4MDL, Operon, gplearn, AI-Feynman;
- PySINDy, PyDMD, pyKoopman, dysts;
- GUDHI, geomstats, POT, pymanopt, KeplerMapper, TopoNetX, Regina;
- PyMC, ArviZ, DoWhy, Tigramite, EconML, JAXopt, BoTorch;
- Julia SciML, ModelingToolkit, DataDrivenDiffEq, diffrax;
- QuTiP, Cadabra, Astropy, Cantera, PyBaMM, quimb, cotengra;
- PETSc, FEniCSx, pyMOR, scikit-fem, Dedalus;
- Modulus, neural operators, SageMath and Wolfram runtime.

## ЦЕЛЕВАЯ ФИЗИЧЕСКАЯ АРХИТЕКТУРА

~~~text
Solo agent
  -> labctl enter
  -> native cell bootstrap
  -> LabAccessReceipt, scope only
  -> ScientificRequestEnvelope
  -> validation + admission + resource gate
  -> real isolated scientific pack
  -> ScientificResultEnvelope
  -> production signature + provenance chain
  -> LabExportPacket
  -> standalone result or native C3 intake
~~~

### Размещение

Mac:

- operator terminal;
- foreground bounded execution only;
- no autonomous long-running service;
- no project environments, datasets, caches or results on internal disk.

T7:

~~~text
SRF/
  cold-cas/        immutable scientific artifacts and receipts
  work/
    envs/python/
    envs/native/
    envs/julia/
    envs/formal/
    caches/
    scratch/
    spool/
    indexes/
  quarantine/
  restore-tests/
~~~

- maximum SRF allocation: 400 GiB;
- minimum free reserve: 100 GiB;
- cold-cas contains no active DB/WAL;
- work is mutable and rebuildable;
- unique receipts are never garbage-collected automatically.

Current VPS:

- remains Market runtime and transport endpoint;
- is not a heavy scientific compute node;
- is not the sole backup target for T7.

Science Compute Target:

- headless Linux;
- always-on only after explicit provisioning;
- rootless containers or microVMs;
- CPU/RAM/scratch and optional accelerator labels;
- deny outbound network by default;
- signed job intake;
- durable checkpoint/resume;
- returns artifacts, never authority.

## PACK PLACEMENT POLICY

Каждый pack получает отдельный manifest со следующими обязательными полями:

~~~yaml
pack:
  pack_id:
  upstream_identity:
  source_sha256:
  lock_sha256:
  license_expression:
  sbom_sha256:
  architecture:
  environment_root_class:
  trust_class:
  network_policy:
  cpu_limit:
  memory_limit:
  wall_time_limit:
  scratch_limit:
  deterministic_seed_policy:
  scientific_smoke:
  independent_crosscheck:
  revocation_status:
  activation_status:
~~~

Лицензионно несовместимые runtime tools не bundle-ятся в Apache wheel. Они
могут работать как изолированные external executables при подтверждённом
license boundary. Нельзя скрывать проблему словом optional.

## ПОЛНЫЙ CATALOG И ЦЕЛЕВОЙ СТАТУС

### Core numerical, symbolic and algebra

Обязательный ACTIVE:

- NumPy, SciPy, Pint, mpmath;
- SymPy;
- python-flint, FLINT, Arb and Calcium;
- PARI/GP;
- Maxima;
- GAP;
- Singular;
- Z3 and cvc5.

Crosschecks:

- SymPy versus FLINT/PARI on exact arithmetic;
- Z3 versus cvc5 on common decidable fragments;
- unit and dimensional checks through Pint;
- float result versus exact or interval result when feasible.

### Formal mathematics

Обязательный ACTIVE:

- Lean 4 plus pinned mathlib as primary;
- Rocq as independent constructive/software-correctness contour;
- Isabelle/HOL as independent HOL contour;
- HOL4 as conservative additional contour;
- CSLib index adapter;
- Erdős Problems pinned metadata and Lean corpus;
- Formal Conjectures pinned corpus.

Proof receipt must bind source, theorem, imports, axioms, toolchain, library
revision, stdout/stderr digest and kernel exit status.

### Discovery and dynamics

Обязательный ACTIVE or explicitly replaced after demonstrated incompatibility:

- PySR;
- SR4MDL;
- Operon;
- gplearn;
- AI-Feynman;
- PySINDy;
- PyDMD;
- pyKoopman;
- dysts.

Incompatibility does not allow silent removal. The agent must try:

1. native ARM environment;
2. isolated x86/Linux compute target;
3. maintained functional alternative with a recorded replacement decision.

### Geometry, topology, probability, causal and optimization

Обязательный ACTIVE:

- GUDHI, ripser;
- geomstats, POT, pymanopt;
- KeplerMapper, TopoNetX, Regina;
- PyMC and ArviZ in an isolated license-reviewed environment;
- DoWhy, Tigramite, EconML;
- CVXPY with solver/license matrix;
- JAXopt and BoTorch.

### SciML and domain science

Обязательный ACTIVE:

- Julia, SciML, ModelingToolkit, DataDrivenDiffEq;
- diffrax;
- QuTiP;
- Cadabra;
- Astropy;
- Cantera;
- PyBaMM;
- quimb and cotengra.

### Heavy compute

Обязательный ACTIVE on a compatible compute target before final DONE:

- PETSc;
- FEniCSx;
- pyMOR;
- scikit-fem;
- Dedalus;
- SageMath.

Conditional:

- Modulus and large neural operators require accelerator capability;
- Wolfram requires explicit credential and positive budget receipt.

Если accelerator или paid oracle не предоставлены, они остаются protected
external blockers, но бесплатные CPU-capable heavy packs всё равно должны быть
активированы на compute target.

### Knowledge sources

Обязательный ACTIVE:

- OpenAlex;
- Crossref;
- OpenCitations;
- zbMATH;
- OEIS;
- LMFDB;
- CSLib;
- Erdős Problems;
- Formal Conjectures.

Каждый live adapter требует rate limit, cache policy, source timestamp,
license/terms record, citation provenance and prompt-injection isolation.

## PRODUCTION SECURITY GATES

### Signatures

- Replace test-hmac-sha256 in production path with Ed25519.
- HMAC fixture remains test-only and cannot sign ACTIVE receipts.
- Key material comes from native credential storage, never Git/env files.
- Key rotation, revoked key and sequence rollback are tested.

### Sandbox

T0/T1:

- fixed allowlisted executable;
- no shell;
- stripped environment;
- read-only input and environment;
- per-run scratch;
- CPU, RSS, process, FD, output and wall-time limits.

T2/T3:

- rootless container or microVM on compatible Linux target;
- network deny by default;
- egress allowlist only for declared source adapters;
- read-only pack image;
- no inherited credentials;
- CAS writer outside the sandbox.

Policy-only decision is insufficient. Acceptance requires an attempted escape,
network attempt, fork/process flood, disk flood and secret canary to be
mechanically denied.

### Supply chain

- pinned hashes and immutable revisions;
- CycloneDX SBOM;
- license inventory;
- vulnerability policy;
- signatures/checksums;
- pack revocation registry;
- dependency DAG and transitive revalidation;
- no mutable global Python, Julia or Lean depot.

## AUTONOMOUS EXECUTION POLICY

Агент не спрашивает оператора об обычных инженерных решениях.

Он самостоятельно:

- выбирает maintained and reversible implementation;
- создаёт clean codex worktree;
- добавляет dependencies and locks through governance-change workflow;
- строит isolated environments on T7;
- пишет adapters, tests, docs and receipts;
- создаёт issue, PR and review packet;
- исправляет CI;
- включает native auto-merge only after required checks;
- выпускает intermediate prereleases when useful;
- продолжает независимые stages при external WAIT.

Recovery:

1. Один identical retry только для transient failure.
2. До трёх materially different approaches.
3. Минимальный reproducible case.
4. Upstream docs/source/license inspection.
5. Alternative placement: M1, compute target, compliant API.
6. Если решение требует protected authority, exact WAIT packet и продолжение
   всех независимых stages.

Запрещено:

- завершать mission ради красивого release;
- превращать missing software в external blocker;
- понижать acceptance после начала stage;
- считать tests against mocks подтверждением production integration;
- скрывать flaky test, weak sandbox or license conflict;
- переписывать опубликованную историю;
- мутировать чужой canonical repo напрямую.

## EXECUTION ORDER

### A00 — Freeze successor plan

Goal:

- доказать единственный executable successor;
- проверить plan hash and project binding;
- пометить V3.6 historical/non-executable.

Acceptance:

- exact hash review независимым reviewer;
- PLAN_REVIEW=APPROVED;
- predecessor preserved;
- no second active plan writer.

Не закрывается:

- только наличием файла без review.

### A01 — Truth ledger and acceptance harness

Actions:

- generate CapabilityTruthLedger from executable probes;
- add states DECLARED through ACTIVE;
- add CI rule: mandatory pack may not close in WAIT_CAPABILITY;
- add production-versus-fixture evidence axis;
- add release gate rejecting fixture signer, policy-only sandbox and missing
  mandatory toolchains.

Acceptance:

- current v1.0.1 inventory reproduced exactly;
- negative fixtures prove old false closure is rejected;
- generated docs agree with machine ledger.

### A02 — Non-destructive T7 binding

Actions:

- verify exact volume identity and capacity;
- create SRF namespaces under target-scoped authority;
- enforce 400 GiB cap and 100 GiB reserve;
- bind private overlay without owner paths in Git;
- move package environments, caches, scratch and spool to T7;
- prove no project data is written to internal Mac disk.

Acceptance:

- T7BindingReceipt with volume identity, namespace and quota hashes;
- real object write/read/corruption test;
- cold-CAS rejects DB/WAL;
- unplug produces WAIT_T7 without corruption;
- replug resumes safely.

### A03 — Environment factory and supply-chain gate

Actions:

- implement uv/micromamba or equivalent Python profile factory;
- implement native binary profiles;
- implement Julia depot isolation;
- implement Lean/prover environment isolation;
- generate locks, hashes, SBOM and licenses;
- implement revocation and dependency DAG.

Acceptance:

- rebuild same environment twice with matching manifest;
- no global mutable depot;
- revoked dependency prevents scheduling;
- license-unknown package cannot become ACTIVE.

### A04 — Production signing and transport

Actions:

- implement Ed25519 signer/verifier interface;
- bind keys through private native configuration;
- preserve HMAC fixture only in test namespace;
- prove ack, dedup, retry, expiry, quarantine, DLQ and replay.

Acceptance:

- real signed message accepted;
- fixture signature rejected in production mode;
- revoked key, replay and sequence rollback rejected;
- crash at every spool transition loses no acknowledged message.

### A05 — Enforced sandbox

Actions:

- implement real T0/T1 subprocess isolation;
- implement T2/T3 container or microVM adapter on Linux target;
- enforce resources and network;
- isolate CAS writer and credentials.

Acceptance:

- adversarial escape suite passes;
- unsupported host returns WAIT_COMPUTE_TARGET, never weak fallback;
- no secret canary visible inside pack;
- output and scratch limits enforced.

### A06 — Durable executor and scheduler

Actions:

- persist request FSM and checkpoints on T7 work namespace;
- implement crash/restart reconciliation;
- implement light/heavy pools, aging and backpressure;
- integrate pack revocation and real sandbox dispatch;
- bind production receipts.

Acceptance:

- process kill and host restart resume exact job once;
- no double result or double import;
- heavy M1 concurrency remains one;
- disk reserve prevents admission before breach.

### A07 — Activate P0 Python core

Packs:

- SymPy;
- mpmath;
- python-flint with FLINT/Arb/Calcium.

Scientific smoke:

- exact polynomial factorization;
- high-precision numerical evaluation;
- interval enclosure;
- dimensional consistency.

Acceptance:

- each pack ACTIVE;
- real imports from T7 environment;
- independent result crosschecks;
- no WAIT_CAPABILITY remains for these packs.

### A08 — Activate native algebra and SMT

Packs:

- PARI/GP;
- Maxima;
- GAP;
- Singular;
- cvc5 alongside Z3.

Acceptance:

- native executable version probes;
- bounded real algebra/number-theory/Groebner/group tasks;
- Z3/cvc5 agreement corpus;
- license boundary documented and enforced;
- each pack ACTIVE.

### A09 — Activate Lean and mathematical corpora

Actions:

- install pinned Lean and lake on T7;
- build pinned mathlib;
- integrate CSLib;
- pin Erdős Problems and Formal Conjectures revisions;
- run solved regression and open-statement parsing.

Acceptance:

- real Lean kernel accepts valid theorem and rejects invalid theorem;
- mathlib import works outside fixture mocks;
- theorem receipt includes axioms and revisions;
- at least one Erdős/Formal Conjectures statement traverses full pipeline.

### A10 — Activate independent provers

Packs:

- Rocq;
- Isabelle/HOL;
- HOL4.

Acceptance:

- real executable and library probes;
- one shared mathematical claim represented per logic;
- assumptions and semantic gaps explicit;
- no automatic equivalence claim;
- all three contours ACTIVE or a documented compute-target implementation is
  actively executing toward completion.

### A11 — Activate knowledge graph

Actions:

- live bounded adapters for all declared public sources;
- deterministic normalization and citation graph;
- taint untrusted corpus;
- injection and citation-spoof protection;
- cache on T7 with source timestamps.

Acceptance:

- live queries to each source;
- offline replay from exact cached response;
- source terms and provenance captured;
- malicious corpus cannot alter privileged instructions.

### A12 — Activate discovery and dynamics

Actions:

- install each discovery pack in isolated profiles;
- implement common candidate-law interface;
- run real synthetic and public benchmark datasets;
- null/surrogate, holdout and unit checks;
- measure resource envelopes.

Acceptance:

- every catalog pack ACTIVE or replaced through explicit reviewed decision;
- PySR runs against real Julia backend;
- PySINDy/PyDMD produce real bounded results;
- no automatic scientific promotion.

### A13 — Activate applied science

Actions:

- geometry/topology packs;
- Bayesian and causal packs;
- optimization packs and solver matrix.

Acceptance:

- real nonfixture workloads;
- topology null checks;
- Bayesian diagnostics truthful;
- causal identification and falsification;
- solver/license status explicit;
- all catalog items ACTIVE or formally replaced.

### A14 — Activate SciML and domain science

Actions:

- build isolated Julia and Python environments;
- implement common units/tolerance/provenance envelope;
- activate all listed domain packs.

Acceptance:

- real Julia SciML model executes;
- Python diffrax path executes;
- representative quantum, astronomy, combustion, battery and tensor-network
  tasks execute;
- cross-language claims use tolerances, never false bitwise identity.

### A15 — Provision and activate heavy compute

Actions:

- discover or provision compatible Linux compute target under exact authority;
- register signed capability manifest;
- build CPU heavy pack images;
- test checkpoint/resume and artifact return;
- add accelerator profiles only when hardware exists.

Acceptance:

- PETSc, FEniCSx, pyMOR, scikit-fem, Dedalus and SageMath execute real jobs;
- no current VPS overload;
- node loss resumes from checkpoint;
- remote result carries exact image and node identities.

Stage remains open while WAIT_COMPUTE_TARGET persists.

### A16 — Complete scientific products

Products:

- LawMiner;
- Formal Verification Lab;
- Geometry and Physics Compiler;
- Causal Economy Lab;
- Literature-to-Knowledge Graph.

Acceptance:

- each product uses at least two real scientific backends where applicable;
- complete request/result/receipt chain;
- inconclusive and disagreement paths preserved;
- no product creates second ledger or authority.

### A17 — Complete solo-agent entry

Actions:

- labctl enter for standalone, Market and Security contexts;
- native bootstrap first;
- capability discovery from real ledger;
- submit, status, result, export, replay and doctor;
- MCP and portal use same service layer.

Acceptance:

- fresh agent with no chat history completes one real research task;
- wrong checkout redirects;
- stale/cross-head receipt fails closed;
- docs and CLI behavior match.

### A18 — DualContour native child closeout

Actions:

- send hash-bound shared-contract child mission;
- child owner runs native governance;
- import closeout and conformance corpus.

Acceptance:

- both producer and consumer suites pass;
- no direct parent write;
- shared contract grants no scientific or domain authority.

Stage remains open while WAIT_NATIVE_CHILD_CLOSEOUT persists.

### A19 — Market native bridge

Actions:

- wait for native Market bootstrap to permit code work;
- merge inactive adapter through Market owner;
- reuse existing central material-event projector;
- test C3 import, dedup, stale identity and failure isolation.

Acceptance:

- native Market closeout receipt;
- SRF offline produces WAIT_SRF without false global health;
- no trading/order path;
- activation requires native authority.

Market runtime RED may park activation but not justify false child closeout.

### A20 — Security native bridge

Actions:

- native Security bootstrap;
- merge inactive sanitized adapter;
- preserve ebashim as sole executor;
- prove D0/D1-only transport and D2/D3 containment.

Acceptance:

- native Security closeout receipt;
- target, exploit, credential and private evidence never cross;
- no scanner control or security action from SRF.

### A21 — Real disaster recovery and chaos

Actions:

- classify rebuildable versus unique state;
- configure second encrypted recovery target for unique small artifacts;
- execute T7 restore drill;
- kill executor during real runs;
- test corrupt objects, revoked packs, stale keys and lost indexes.

Acceptance:

- measured RPO/RTO receipt;
- unique receipt chain restored;
- rebuildable environments reconstructed from locks;
- no current VPS used as sole backup.

### A22 — Final system acceptance and v2.0.0

Preconditions:

- A00-A21 accepted;
- zero mandatory WAIT_CAPABILITY or WAIT_TOOLCHAIN;
- production Ed25519 active;
- enforced sandbox active;
- T7 real binding active;
- heavy CPU packs active on compute target;
- native child closeouts present;
- full documentation generated from truth ledger.

Checks:

- make verify;
- candidate-specific integration suite;
- public-boundary and secret scan;
- SBOM, license and vulnerability gates;
- reproducible build;
- clean-install smoke;
- solo-agent end-to-end;
- restore and chaos receipts;
- independent final review.

Release:

- publish v2.0.0 only from exact accepted merge SHA;
- artifacts, SBOM, signatures and hashes;
- no retagging;
- MissionCloseoutReceipt result must equal DONE.

## STAGE COMPLETION RECEIPT

Каждая stage создаёт:

~~~yaml
stage_receipt:
  plan_id:
  mission_id:
  stage_id:
  candidate_tree_sha256:
  environment_sha256:
  exact_inputs:
  real_executables:
  real_nonfixture_runs:
  scientific_crosschecks:
  fixture_only_evidence:
  active_capabilities:
  remaining_internal_waits:
  remaining_external_waits:
  checks:
  terminal_result:
  receipt_sha256:
~~~

terminal_result PASS запрещён, если remaining_internal_waits не пуст.

## DEFINITION OF DONE

- DOD-01: predecessor retained, V3.7 is sole executable plan.
- DOD-02: CapabilityTruthLedger is generated from real probes.
- DOD-03: T7 physical namespaces and quotas are active.
- DOD-04: no project data depends on internal Mac storage.
- DOD-05: production receipts use Ed25519, not fixture HMAC.
- DOD-06: T0/T1 and T2/T3 isolation is mechanically enforced.
- DOD-07: durable scheduler survives process and host interruption.
- DOD-08: P0 core has no WAIT_CAPABILITY.
- DOD-09: Lean and mathlib execute real kernel checks.
- DOD-10: Rocq, Isabelle/HOL and HOL4 execute real probes and proofs.
- DOD-11: mathematical corpora are pinned and traversable.
- DOD-12: discovery/dynamics catalog is ACTIVE or formally replaced.
- DOD-13: applied-science catalog is ACTIVE or formally replaced.
- DOD-14: SciML/domain catalog is ACTIVE.
- DOD-15: CPU heavy catalog is ACTIVE on compute target.
- DOD-16: public knowledge sources perform real bounded queries.
- DOD-17: all five scientific products use real backends.
- DOD-18: fresh solo agent completes real research through labctl.
- DOD-19: DualContour native child closeout exists.
- DOD-20: Market native bridge closeout exists and remains authority-negative.
- DOD-21: Security native bridge closeout exists and preserves ebashim.
- DOD-22: restore/chaos drill proves measured RPO/RTO.
- DOD-23: zero mandatory internal WAIT states remain.
- DOD-24: independent candidate audit passes.
- DOD-25: v2.0.0 is reproducible and MissionCloseoutReceipt says DONE.

## FINAL AUDIT

Аудитор обязан отдельно доказать:

1. Config versus installed versus ACTIVE statuses are not collapsed.
2. Every ACTIVE pack has real executable evidence.
3. At least one nonfixture run exists per capability family.
4. Fixture signer cannot reach production.
5. Sandbox restrictions are enforced, not documented only.
6. T7 and compute target identities are exact and current.
7. No hidden internal WAIT is relabeled external.
8. No dependency license is concealed by optional packaging.
9. Market and Security integrations remain proposal-only.
10. Release claim matches physical deployment truth.

Допустимые final states:

- DONE;
- BLOCKED_EXTERNAL_AUTHORITY with a single exact decision packet;
- BLOCKED_PHYSICAL_CAPABILITY after three materially different approaches.

Недопустимый final state:

- RELEASED_WITH_DECLARED_WAITS.
<!-- END_PLAN_CONTRACT_V3_7 -->

<!-- BEGIN_MUTABLE_STATE_V3_7 -->
STATE_REVISION: 2
PREVIOUS_STATE_SHA256: fe6850c7-c14a0897-67073c11-8efdcfdf-22ab1914-5bf89990-9781ad53-0989c7c7
CURRENT_STATE_SHA256: 348b2c37-557aebc7-364f9572-02bce394-b60180ab-29cadedc-09512a23-97933935

## CURRENT_FACTS

~~~yaml
current_facts:
  observed_at: 2026-07-29
  repository_head: dc0ceca30c22d30916828c6b37c77962aeec7b66
  predecessor_release: v1.0.1
  predecessor_result: RELEASED_WITH_DECLARED_WAITS
  current_active_default_packs:
    - numpy
    - scipy
    - pint
    - z3
    - ripser
    - pyriemann
    - cvxpy
    - clarabel
  production_signer: missing
  enforced_t2_t3_sandbox: missing
  t7_binding: WAIT_T7_BINDING
  compute_target: WAIT_COMPUTE_NODE
  market_bridge: INACTIVE_WAIT_RUNTIME_HEALTH
  security_bridge: INACTIVE_WAIT_SECURITY_HEALTH
  dual_contour_closeout: WAIT_NATIVE_CHILD_CLOSEOUT
~~~

## EXECUTION_STATE

~~~yaml
execution_state:
  status: A00_ACCEPTED
  current_stage: A01
  next_stage: A01_truth_ledger_and_acceptance_harness
  completed_stages:
    - A00
  active_branch_or_null: codex/srf-activation-master-plan-v3-7
  active_pr_or_null: null
  writer_lease_or_null: null
  blocker_or_null: null
  next_executable_action: implement CapabilityTruthLedger and release blockers
  updated_at: 2026-07-29
~~~

## DECISION_LOG

~~~yaml
decision_log:
  - id: V37-D001
    decision: v1.0.1 is historical foundation, not full scientific activation
  - id: V37-D002
    decision: WAIT_CAPABILITY cannot close in-scope software work
  - id: V37-D003
    decision: ACTIVE requires real installation and nonfixture execution
  - id: V37-D004
    decision: final target is v2.0.0 with DONE only
  - id: V37-D005
    decision: external protected waits park lanes but never become false success
  - id: V37-D006
    decision: A00 exact-hash review approved V3.7 as the sole executable successor plan
~~~

## EVIDENCE_INDEX

~~~yaml
evidence_index:
  - repository HEAD and clean status
  - pyproject runtime dependency inventory
  - executable and import probes
  - configs/packs admission manifests
  - docs/catalog declared ACTIVE and WAIT states
  - mission-closeout-receipt v1.0.1
  - runtime source inspection for signer, sandbox, scheduler, CAS and recovery
  - docs/verification/srf-v3-7-a00-freeze-receipt.json
~~~

<!-- END_MUTABLE_STATE_V3_7 -->

## Exact hash algorithm

The plan contract digest is SHA-256 over exact UTF-8 bytes after the newline
ending BEGIN_PLAN_CONTRACT_V3_7 and before the newline immediately preceding
END_PLAN_CONTRACT_V3_7.

The mutable state digest uses the same boundary rule after removing exactly the
complete CURRENT_STATE_SHA256 line and its terminating newline.

Public digest rendering uses eight groups of eight lowercase hexadecimal
characters. Remove grouping hyphens before machine comparison.
