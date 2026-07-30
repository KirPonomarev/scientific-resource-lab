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
STATE_REVISION: 13
PREVIOUS_STATE_SHA256: f9db73e0-eb34c0ac-cd2584c2-ef77abe3-83e388b8-a027dd42-f958df66-28e9c74d
CURRENT_STATE_SHA256: 9838f081-6b8610e1-4afb9c19-26ba605c-c902ee18-64715c82-c82085d7-988a8952

## CURRENT_FACTS

~~~yaml
current_facts:
  observed_at: 2026-07-29
  repository_head: 677b17baf3c8d49b7dad05c39616e5d1e2df7bcc
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
    - sympy
    - mpmath
  a07_sympy_mpmath_core: ACTIVE
  a07_python_flint: WAIT_LICENSE
  current_active_native_toolchains:
    - pari-gp
    - maxima
    - gap
    - singular
    - z3-native
    - cvc5
  a08_pari_gp: ACTIVE
  a08_maxima: ACTIVE
  a08_gap: ACTIVE
  a08_singular: ACTIVE
  a08_z3_native: ACTIVE
  a08_cvc5: ACTIVE
  current_active_formal_toolchains:
    - lean
    - lake
    - mathlib
    - cslib-index
    - erdos-problems-metadata
    - formal-conjectures
  a09_lean_kernel: ACTIVE
  a09_lake: ACTIVE
  a09_mathlib: ACTIVE
  a09_cslib_index: ACTIVE
  a09_erdos_problems_metadata: ACTIVE
  a09_formal_conjectures_corpus: ACTIVE
  a09_receipt_id: sha256:366c24395552933e3f758599b28e0e93ac136bd86a6ce0d5a7ff5ed61c0e2ca1
  a09_truth_projection: OFFLINE_HASH_BOUND_RECEIPT
  a09_verify_prepare_count: 1
  a09_verify_fetch_count: 1
  a09_warm_prepare_count: 0
  a09_warm_fetch_count: 0
  a09_t7_formal_toolchain_binding: WAIT_AUTHORITY
  current_active_independent_provers:
    - rocq
    - isabelle
    - hol4
  a10_rocq: ACTIVE
  a10_isabelle_hol: ACTIVE
  a10_hol4: ACTIVE
  a10_receipt_id: sha256:25c51de9b712afc0f1fc961c26f5dae38ed2872cb054850bd7182374ad3cca7f
  a10_truth_projection: OFFLINE_HASH_BOUND_RECEIPT
  a10_hol4_cache_status: REUSED_ON_FULL_VERIFY
  a10_hol4_prepare_count: 0
  a10_hol4_fetch_count: 0
  current_active_knowledge_sources:
    - openalex
    - crossref
    - arxiv
    - oeis
    - opencitations
    - zbmath
    - lmfdb
    - cslib
    - erdos_problems
    - formal_conjectures
  a11_knowledge_graph: ACTIVE
  a11_receipt_id: sha256:7dbacced167734bc0b16f0a81c5aa1b8848de4fd9ce47c06412f4716d80a6350
  a11_truth_projection: OFFLINE_HASH_BOUND_RECEIPT
  a11_live_fetch_count: 10
  a11_offline_replay_count: 10
  a11_cache_root_role: T7_SECURE_SESSION_CACHE
  current_active_discovery_dynamics:
    - pysr
    - pysindy
    - pydmd
  a12_discovery_dynamics: ACTIVE
  a12_receipt_ref: docs/verification/srf-v3-7-a12-discovery-dynamics-receipt.json
  a12_activation_receipt_ref: embedded_in_a12_receipt
  a12_truth_projection: OFFLINE_HASH_BOUND_RECEIPT
  a12_formally_replaced_packs:
    - sr4mdl
    - operon
    - gplearn
    - ai_feynman
    - pykoopman
    - dysts
  production_signer: WAIT_AUTHORITY
  production_ed25519_transport_interface: ACTIVE
  fixture_hmac_production_path: REJECTED
  transport_crash_reconciliation: ACTIVE
  t0_t1_subprocess_sandbox: ACTIVE
  sandbox_adversarial_suite: ACTIVE
  sandbox_output_and_scratch_limits: ACTIVE
  enforced_t2_t3_sandbox: WAIT_COMPUTE_TARGET
  durable_scheduler_software: ACTIVE
  scheduler_real_subprocess_dispatch: ACTIVE
  scheduler_terminal_receipt_binding: ACTIVE
  scheduler_t7_native_persistence: WAIT_T7_BINDING
  t7_binding: WAIT_T7_BINDING
  a02_t7_binding_gate: ACTIVE
  a02_physical_binding: WAIT_AUTHORITY
  environment_factory: ACTIVE
  supply_chain_gate: ACTIVE
  compute_target: WAIT_COMPUTE_NODE
  market_bridge: INACTIVE_WAIT_RUNTIME_HEALTH
  security_bridge: INACTIVE_WAIT_SECURITY_HEALTH
  dual_contour_closeout: WAIT_NATIVE_CHILD_CLOSEOUT
  capability_truth_ledger: ACTIVE
  release_false_closure_gate: ACTIVE
~~~

## EXECUTION_STATE

~~~yaml
execution_state:
  status: A20_TRUTH_GATE_ACTIVE_WAIT_NATIVE_CHILD_CLOSEOUT_READY_FOR_A21
  current_stage: A21
  next_stage: A21_real_disaster_recovery_and_chaos
  completed_stages:
    - A00
    - A01
    - A03
    - A04
    - A05
    - A06
    - A08
    - A09
    - A10
    - A11
    - A12
    - A13
    - A14
    - A16
    - A17
  completed_stage_lanes:
    - A07_sympy_mpmath_core
  parked_stages:
    - A02_non_destructive_t7_binding
    - A04_native_production_key_binding
    - A05_native_t2_t3_compute_binding
    - A06_native_t7_persistence_binding
    - A07_python_flint_license
    - A18_dual_contour_native_child_closeout
    - A19_market_native_bridge_closeout
    - A20_security_native_bridge_closeout
    - A09_t7_formal_toolchain_binding
  parked_blockers:
    - WAIT_AUTHORITY:A02_BIND_T7_NATIVE_TARGET
    - WAIT_AUTHORITY:A04_BIND_PRODUCTION_ED25519_KEYRING
    - WAIT_COMPUTE_TARGET:A05_BIND_NATIVE_SANDBOX_COMPUTE_TARGET
    - WAIT_LICENSE:A07_PYTHON_FLINT_LGPL_CLOSURE
    - WAIT_AUTHORITY:A09_BIND_PINNED_LEAN_MATHLIB_PROJECT_TO_T7
    - WAIT_COMPUTE_NODE:A15_PROVISION_HEAVY_COMPUTE_TARGET
    - WAIT_NATIVE_CHILD_CLOSEOUT:DUAL_CONTOUR_MAKE_CONTRACTS_FAIL
    - WAIT_NATIVE_CHILD_CLOSEOUT:MARKET_NATIVE_BRIDGE_CLOSEOUT_ABSENT
    - WAIT_RUNTIME_HEALTH:MARKET_ORGANISM_NOT_GREEN
    - WAIT_NATIVE_CHILD_CLOSEOUT:SECURITY_NATIVE_BRIDGE_CLOSEOUT_ABSENT
    - WAIT_SECURITY_HEALTH:SECURITY_ORGANISM_NOT_GREEN
  active_branch_or_null: codex/srf-a20-security-native-bridge
  active_pr_or_null: null
  writer_lease_or_null: null
  blocker_or_null: WAIT_NATIVE_CHILD_CLOSEOUT:SECURITY_NATIVE_BRIDGE_CLOSEOUT_ABSENT
  latest_stage_receipts:
    A18: sha256:d60e2fe35a732cbb29107b549ca4b6c89a280a0e5128b432a2b5cb1743896b50
    A19: sha256:f2e1638e40150c2929f8bc27ae4de4e6d6919bf3eb85e1a24668f1b9bb73391a
    A20: sha256:327881c83976f1b600b0b7ec3b15ba3f1e8aa661695705e3f340bc7631827cfd
  next_executable_action: continue A21 real disaster recovery and chaos while Security, Market and DualContour native closeouts, Security and Market runtime health, compute-node, T7-backed persistence, native compute binding, native production signing, FLINT license closure and A09 T7 formal toolchain binding remain parked
  updated_at: 2026-07-30
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
  - id: V37-D007
    decision: A01 CapabilityTruthLedger is the machine source for V3.7 capability closure truth
  - id: V37-D008
    decision: DONE/v2.0.0 release closure rejects fixture signer, policy-only sandbox, missing T7 and mandatory toolchain WAIT states
  - id: V37-D009
    decision: A02 non-destructive software gate is active, but physical T7 binding remains WAIT_AUTHORITY until native target receipt exists
  - id: V37-D010
    decision: A03 environment factory produces deterministic isolated profile manifests and rejects revoked dependencies, global depots and unknown-license ACTIVE claims
  - id: V37-D011
    decision: A04 Ed25519 transport interface is active with fixture-HMAC production rejection, revoked-key/replay guards and crash reconciliation; native production key binding remains WAIT_AUTHORITY
  - id: V37-D012
    decision: A05 local T0/T1 subprocess sandbox is enforced with adversarial, canary, output and scratch-limit evidence; native T2/T3 compute target remains WAIT_COMPUTE_TARGET
  - id: V37-D013
    decision: A06 durable scheduler software lane is active with T7-work namespace contract, crash/restart exact-once recovery, pool/backpressure controls and bound terminal receipts; native T7 persistence remains WAIT_T7_BINDING
  - id: V37-D014
    decision: A07 SymPy and mpmath default Python core packs are ACTIVE with real import probes, scientific smoke and independent crosschecks; python-flint/FLINT/Arb/Calcium remains WAIT_LICENSE because current package metadata declares an LGPL-family closure denied by SRL default dependency policy
  - id: V37-D015
    decision: A08 native algebra and SMT toolchains are ACTIVE with external PARI/GP, Maxima, GAP, Singular, native Z3 and cvc5 executable probes, bounded scientific smokes, Z3/cvc5 agreement and uv license-boundary enforcement
  - id: V37-D016
    decision: A09 Lean/lake/mathlib and mathematical corpora are ACTIVE with pinned Lean 4.32.2, real kernel accept/reject checks, pinned mathlib module import, axiom inventory, CSLib/Erdos/Formal Conjectures pins and remote corpus blob traversal; truth-ledger A09 projection is offline from hash-bound receipt sha256:366c24395552933e3f758599b28e0e93ac136bd86a6ce0d5a7ff5ed61c0e2ca1; full make verify uses one session-scoped A09 prepare with prepare_count=1 fetch_count=1 and warm prepare reuse reports prepare_count=0 fetch_count=0; physical T7 formal toolchain binding remains WAIT_AUTHORITY
  - id: V37-D017
    decision: A10 Rocq/Coq, Isabelle/HOL and HOL4 independent prover contours are ACTIVE with real executable probes and shared nat zero-add proof checks; semantic-gap manifests explicitly represent logic and assumption deltas and forbid automatic theorem equivalence claims; truth-ledger A10 projection is offline from hash-bound receipt sha256:25c51de9b712afc0f1fc961c26f5dae38ed2872cb054850bd7182374ad3cca7f; full verify reuses the pinned HOL4 cache with prepare_count=0 and fetch_count=0 after the cold T7-Secure preparation
  - id: V37-D018
    decision: A11 source-grounded knowledge graph is ACTIVE with bounded live public-source queries for OpenAlex, Crossref, arXiv, OEIS, OpenCitations, zbMATH Open, LMFDB, CSLib, Erdos Problems and Formal Conjectures; GitHub corpus sources use exact pinned raw blobs instead of unauthenticated commit API metadata; every live response is hash-bound to an exact no-network replay receipt; source policy cards project ACTIVE for all declared A11 sources; taint and citation-spoof guards keep raw corpus out of privileged prompts; truth-ledger A11 projection is offline from hash-bound receipt sha256:7dbacced167734bc0b16f0a81c5aa1b8848de4fd9ce47c06412f4716d80a6350
  - id: V37-D019
    decision: A12 PySR, PySINDy and PyDMD discovery/dynamics packs are ACTIVE with bounded real workloads, null controls, public benchmark receipt and no automatic scientific promotion; SR4MDL, Operon, gplearn, AI-Feynman, PyKoopman and Dysts are formally replaced for v2.0.0; truth-ledger A12 projection is offline from hash-bound receipt sha256:f76090d0a8bcbf72d986f9c7c32d125cc1624c80c7580b0aa3ea69f363ffc9a5
  - id: V37-D020
    decision: A13 applied-science packs are ACTIVE with ripser topology signal/null control, pyriemann SPD geometry diagnostics, CVXPY solver/license matrix, native analytic Bayesian diagnostics without MCMC convergence claims and native causal backdoor identification plus falsification; all broader catalog items are formally replaced for v2.0.0; truth-ledger A13 projection is offline from hash-bound receipt sha256:067abec4a2274b42e8e33122076045d9c67a6d1de6e51859505866adafdbca24
  - id: V37-D021
    decision: A14 SciML/domain packs are ACTIVE with a real Julia SciMLBase/OrdinaryDiffEq ODE solve, Python diffrax ODE solve, QuTiP quantum evolution, Astropy coordinate transform, Cantera combustion equilibrium, native bounded battery RC model, quimb many-body diagonalization and cotengra tensor-network contraction path; ModelingToolkit, DataDrivenDiffEq, Cadabra and PyBaMM are formally replaced for v2.0.0; cross-language ODE evidence is tolerance-only with no bitwise identity claim; truth-ledger A14 projection is offline from hash-bound receipt sha256:2ab6c81a418700072a1330008290304cd24fe74993efd65c22b4fd43397080ae
  - id: V37-D022
    decision: A15 heavy compute software readiness is PASS but stage remains WAIT_COMPUTE_NODE; PETSc, FEniCSx, pyMOR, scikit-fem, Dedalus and SageMath cannot become ACTIVE from accidental local imports and require a compatible Linux x86_64 compute target, exact image digests, real job receipts, checkpoint/resume evidence and artifact-return evidence; protected operator action is recorded at docs/target-binding/a15-heavy-compute-operator-action.json; wait receipt 6c0797c0-3e32208d-f9b79039-6d2ed444-4d514a76-55582837-42516212-061bb676 records remote_launches=0 and unbounded_local_runs=0
  - id: V37-D023
    decision: A16 scientific products are ACTIVE with five product-level request/result/receipt chains over hash-bound A09-A14 receipts; LawMiner binds PySR/PySINDy/PyDMD, Formal Verification Lab binds Lean/mathlib/Rocq/Isabelle/HOL4 with semantic-gap manifests, Geometry and Physics Compiler binds A13 geometry/topology/optimization plus A14 SciML/domain backends, Causal Economy Lab binds native causal/CVXPY/native Bayesian diagnostics, and Literature-to-Knowledge Graph binds ten source-grounded A11 sources; product layer creates no second ledger, grants no authority and preserves inconclusive/disagreement paths; A16 stage receipt sha256:34c59a29aa7694d7540260eff392be3425eaab4846027d516d2bc0ae29864955
  - id: V37-D024
    decision: A17 solo-agent entry is ACTIVE with JSON-first labctl enter/doctor/submit/status/result/export/replay/portal flow; standalone native bootstrap runs first, Market and Security entries remain proposal-only native-bootstrap WAITs, capability discovery is hash-bound to the offline truth ledger, stale or cross-head sessions fail closed, and the built-in fresh-agent task performs a real bounded units identity computation with sanitized export and deterministic replay; A17 stage receipt e4179946-b07a8931-b38ad900-abd154e2-acead3df-daf5bc8c-ccb8c3e8-e184a863
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
  - CAPABILITY-TRUTH-LEDGER.md
  - scripts/checks/srf-v37-a01-gate.py
  - docs/verification/srf-v3-7-a01-truth-ledger-receipt.json
  - scripts/checks/srf-v37-a11-gate.py
  - docs/verification/srf-v3-7-a11-knowledge-graph-receipt.json
  - scripts/checks/srf-v37-a02-gate.py
  - docs/target-binding/t7-native-binding-operator-action.json
  - docs/verification/srf-v3-7-a02-t7-binding-wait-receipt.json
  - docs/architecture/environment-factory.md
  - scripts/checks/srf-v37-a03-gate.py
  - docs/verification/srf-v3-7-a03-env-factory-receipt.json
  - docs/architecture/transport.md
  - docs/target-binding/ed25519-native-key-operator-action.json
  - scripts/checks/srf-v37-a04-gate.py
  - docs/verification/srf-v3-7-a04-signing-transport-receipt.json
  - docs/security/sandbox-boundary.md
  - docs/target-binding/native-sandbox-compute-operator-action.json
  - scripts/checks/srf-v37-a05-gate.py
  - docs/verification/srf-v3-7-a05-enforced-sandbox-receipt.json
  - docs/operations/runner.md
  - scripts/checks/srf-v37-a06-gate.py
  - docs/verification/srf-v3-7-a06-durable-executor-receipt.json
  - docs/architecture/p0-python-core.md
  - scripts/checks/srf-v37-a07-gate.py
  - docs/target-binding/a07-python-flint-license-operator-action.json
  - docs/verification/srf-v3-7-a07-p0-python-core-receipt.json
  - docs/architecture/native-algebra-smt.md
  - scripts/checks/srf-v37-a08-gate.py
  - docs/verification/srf-v3-7-a08-native-algebra-smt-receipt.json
  - docs/architecture/lean-mathlib-corpora.md
  - configs/packs/formal/lean/corpus-pins.json
  - docs/target-binding/a09-lean-mathlib-t7-operator-action.json
  - scripts/checks/srf-v37-a09-gate.py
  - scripts/ci/prepare_a09_mathlib.py
  - scripts/ci/verify-v37.py
  - docs/verification/srf-v3-7-a09-lean-corpora-receipt.json
  - configs/packs/formal/independent-prover-pins.json
  - docs/verification/srf-v3-7-a10-independent-provers-receipt.json
  - scripts/checks/srf-v37-a10-gate.py
  - scripts/ci/prepare_a10_hol4.py
  - src/srl/packs/formal/cross_prover.py
  - docs/architecture/discovery-dynamics-a12.md
  - scripts/checks/srf-v37-a12-prepare-julia.py
  - scripts/checks/srf-v37-a12-gate.py
  - docs/verification/srf-v3-7-a12-discovery-dynamics-receipt.json
  - docs/architecture/applied-science-a13.md
  - docs/catalog/applied-science.md
  - scripts/checks/srf-v37-a13-gate.py
  - docs/verification/srf-v3-7-a13-applied-science-receipt.json
  - docs/architecture/sciml-domain-a14.md
  - docs/catalog/sciml-domain.md
  - scripts/checks/srf-v37-a14-prepare-julia.py
  - scripts/checks/srf-v37-a14-gate.py
  - docs/verification/srf-v3-7-a14-sciml-domain-receipt.json
  - scripts/checks/srf-v37-a15-gate.py
  - docs/target-binding/a15-heavy-compute-operator-action.json
  - docs/verification/srf-v3-7-a15-heavy-compute-wait-receipt.json
  - src/srl/products/catalog.py
  - scripts/checks/srf-v37-a16-gate.py
  - docs/verification/srf-v3-7-a16-scientific-products-receipt.json
  - src/srl/solo_agent.py
  - scripts/checks/srf-v37-a17-gate.py
  - docs/verification/srf-v3-7-a17-solo-agent-receipt.json
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
