# Specialized entity-extraction SLMs via LoRA adapters -- Implementation Plan

**Date:** 2026-08-28
**Design:** [slm-lora-adapters-design.md](../specs/slm-lora-adapters-design.md) (v1)
**Branch:** `experiment/slm-lora`
**Ledger:** [progress.md](../../../.superpowers/sdd/progress.md)

> Every value in the design's
> [Architecture decisions](../specs/slm-lora-adapters-design.md#architecture-decisions----normative)
> section is normative here. No phase below restates them, deliberately: one source of
> truth, referenced by anchor. A phase that needs a different value amends the design
> document instead of diverging from it.

---

## Task ordering and dependencies

```
   Phase 1: data
       |
       |  splits + target-schema decision
       v
   Phase 2: training  ------------------+
       |                                |
       |  adapters                      | two adapters, same template
       v                                v
   Phase 3: eval                   Phase 4: serving
       |                                |
       |  ship gates pass               |  running endpoint
       +---------------+----------------+
                       |
                       v
                 Phase 6: cognee integration
                       |
                       v
                  end-to-end green

   Phase 5: reproducibility  ---- cross-cuts 1, 2, 3, 4 and 6 ----
            (start with Phase 2; the drift check gates Phase 4)
```

Two orderings matter and are easy to get wrong:

- **Phase 3 cannot start before Phase 1 finishes**, because the ship gates are
  meaningless if test data leaked into training.
- **Phase 5 is not last.** Manifests must be emitted by the training harness from its
  first run, or the early adapters are unreproducible and have to be retrained. The
  enforcement check gates serving.

---

## Phase 1 -- Dataset pipeline

**The highest-leverage phase.** Adapter quality is dominated by data quality, not
hyperparameters. One reusable pipeline, run once per entity type, producing versioned
train/val/test splits.

- **Task 1.1 -- Entity type specification** (`specs/<TYPE>.md`)
  Do this first; ambiguity here propagates into every downstream number. Each spec:
  a one-paragraph unambiguous definition, at least 10 real positive surface forms from
  the corpus, negative examples that look like the type but are not, and boundary
  rules (modifiers, abbreviations, plurals, nested mentions). Drives both the teacher
  prompt and the human review rubric.

- **Task 1.2 -- Target schema decision** *(blocks Phase 2)*
  Record one of:
  **(a) Lean target -- recommended.** Train on exactly what the prompt documents:
  `{"entities": [{"name": ..., "is_a": {"name": "TYPE", "description": ...}, "description": ...}]}`
  and let cognee's deserialization fill the `DataPoint` defaults. Smallest schema, best
  adherence.
  **(b) Full generated schema.** Rejected unless (a) fails -- it forces the model to
  emit ids and timestamps it cannot know.
  Whichever is chosen, **the serving grammar must match it exactly**. Background in the
  design's [known schema problem](../specs/slm-lora-adapters-design.md#known-schema-problem).

- **Task 1.3 -- Distillation** (`distil.py`)
  Teacher: a frontier model prompted with the **exact** cognee prompts
  (`extract_entities_system.txt` + `extract_entities_user.txt` rendered via
  `render_prompt`) plus the type spec. Input: real domain corpus text, chunked with
  cognee's own chunker. Synthetic-only text is not acceptable as the sole source; it
  may supplement rare types.
  *Unit tests:* prompt rendering matches the production render; chunker invoked with
  production settings; teacher output captured verbatim before validation.

- **Task 1.4 -- Validation and cleaning** (`validate.py`)
  Every example must parse as JSON, validate against the target schema, have every
  entity `name` verifiably present in the source chunk (guards teacher hallucination),
  and have `is_a.name` uppercase and in the allowed set. Repair or drop otherwise, and
  **log the drop rate** -- a high rate means the teacher prompt is wrong, not that the
  data is noisy.
  *Unit tests:* each gate rejects a crafted violation; drop-rate accounting is exact.

- **Task 1.5 -- Dedup and splits** (`split.py`)
  Exact and near-duplicate dedup (minhash) across the whole pool **before** splitting.
  Split by **source document, not by chunk**, so chunks from one document cannot
  straddle splits. Produce `train` / `val` / `test` (held out, untouched until final
  eval), plus a **shared cross-type test set** reused by every adapter.
  *Unit tests:* zero document overlap between splits, asserted; near-duplicates land in
  the same split.

- **Task 1.6 -- Composition** (per adapter)
  500-5000 examples; start around 1k and grow only if eval F1 plateaus low.
  **Hard negatives are mandatory at 20-30%** -- chunks with no entity of the target
  type, labeled `{"entities": []}`. Without them the adapter over-predicts on every
  chunk. Add near-miss negatives (chunks with *other* types) to teach boundaries.
  Represent multi-entity and zero-entity chunks both.
  *Unit tests:* negative ratio within target, reported per split.

- **Task 1.7 -- Chat formatting**
  `system` = rendered system prompt plus type spec; `user` = rendered user prompt with
  the chunk; `assistant` = the validated JSON. Keep the roles separate -- do **not**
  pre-flatten to a single string, or loss masking cannot be expressed downstream.

**Gates:** 100% of shipped examples validate against the target schema; negative ratio
in range and reported per split; zero document overlap (asserted by a test); dataset
manifest reproducible from a recorded hash; a stratified 5-10% sample human-reviewed
with observed agreement recorded.

---

## Phase 2 -- Training harness

One parameterized QLoRA template producing every adapter, so that producing an
incompatible adapter requires editing the shared contract rather than forgetting a
flag.

- **Task 2.1 -- Parameterized template** (`train_adapter.py` / `.yaml`)
  Parameterized **only** by `{entity_type, dataset_path, adapter_out}`. Everything
  affecting adapter shape is fixed, per the design's
  [compatibility contract](../specs/slm-lora-adapters-design.md#cross-adapter-compatibility-contract).
  T4 settings: `load_in_4bit` nf4 with double quant, `bnb_4bit_compute_dtype=float16`
  (**never bf16**), `seq_len` 2048 capped to real chunk length, per-device batch 1 with
  grad accumulation 16, gradient checkpointing on, `paged_adamw_8bit`, lr 2e-4, cosine
  with warmup 0.03, 2-3 epochs with early stop on val.
  Memory: nf4 base about 4.5GB plus checkpointed activations plus 8-bit optimizer
  states, roughly 11-13GB. **On OOM: drop `seq_len` to 1024 first**, then reduce grad
  accumulation.

- **Task 2.2 -- Loss masking** (`train_on_completions_only`)
  Train on the assistant JSON only. If loss covers the system prompt -- which contains
  the full schema and examples -- the model spends capacity memorizing the prompt and
  generalizes worse.
  *Verify empirically:* dump one batch's label tensor and confirm prompt positions are
  `-100`. This is a task, not an assumption.

- **Task 2.3 -- Driver** -- loops over entity types, trains each adapter.

- **Task 2.4 -- Adapter export**
  Export the **adapter only** (`adapter_model.safetensors` + `adapter_config.json`)
  into `adapters/<type>/`. **Never merge into the base** -- merging defeats the
  shared-base design and multiplies VRAM.

- **Task 2.5 -- Record measured VRAM and wall-clock** for one 7B run on the T4.
  The memory figure in task 2.1 is an *estimate*; this is the measurement. It is what
  tells the next person whether a longer `seq_len` or a second concurrent job is
  possible at all, and it belongs in the ledger with the environment line filled in.

**Tooling:** Unsloth recommended (Turing-supported, roughly 2x faster and about 50%
less VRAM than vanilla peft on a T4). Axolotl or raw `trl.SFTTrainer` + `peft` are
acceptable alternatives.

**Gates:** two adapters from the same template load **simultaneously** on the serving
stack without shape errors -- the real compatibility test, coordinated with Phase 4;
loss masking verified; val curve converges without overfit and the chosen epoch is
justified; adapters exported unmerged at roughly 200MB or less; same seed plus dataset
hash reproduces comparable val loss.

---

## Phase 3 -- Evaluation harness and ship gates

No adapter reaches the serving stack without passing these. Runs on the **held-out
test split**, never train or val.

- **Task 3.1 -- Entity-level accuracy** -- precision, recall, F1 per type. Report both
  **exact match** (after normalization) and **partial/overlap** match: exact-only
  under-credits harmless boundary differences, overlap-only hides sloppiness.
  Normalization rules are defined once and shared with the type spec's boundary rules.

- **Task 3.2 -- JSON validity, measured WITHOUT guided decoding**
  Guided decoding at serve time forces near-100%, so measuring raw is the only thing
  that reveals a weak adapter. **A model that stays on-schema only because a grammar
  forced it is probably producing wrong content too, and the grammar hides exactly
  that.** Also record mean retries under the self-correcting path.

- **Task 3.3 -- Cross-type false-fire** -- run each adapter over the shared cross-type
  set; expected output `{"entities": []}`. A high rate means insufficient near-miss
  negatives; feed back to Phase 1.

- **Task 3.4 -- Empty-input behavior** -- on chunks with no entities at all the adapter
  emits an empty list rather than hallucinating. Reported separately from cross-type.

- **Task 3.5 -- Baseline comparison** -- same test set and prompts against the current
  default frontier model **and** the distillation teacher. Report F1 delta, p50/p95
  latency, cost per 1k chunks. The teacher is the adapter's practical ceiling.

- **Task 3.6 -- Failure feedback loop** -- dump `(chunk, expected, actual)` for each
  failure, cluster the errors, route them back to Phase 1 as targeted examples.
  Retrain, re-evaluate, track F1 per adapter version.

**Ship gates -- all must hold:** F1 within an agreed margin of the teacher; raw JSON
validity above an agreed floor; cross-type false-fire below an agreed ceiling; no
regression against the previously shipped adapter for that type.

**Thresholds are recorded per type in the eval config BEFORE evaluation runs.** Set
afterwards, the threshold quietly becomes whatever the adapter achieved.

---

## Phase 4 -- Serving on the T4

**Partially delivered.** `deployment/slm/` already carries LoRAX and vLLM launch
scripts for T4 multi-adapter inference, and a first cut of the routing helper. They are
scaffolds: written before any adapter existed, and unverified against a real one.

- **Task 4.1 -- Stand up the multi-LoRA server** from the existing scripts; confirm the
  int4 AWQ base loads and `--max-lora-rank` matches the contract.
- **Task 4.2 -- Guided/grammar decoding** enforcing the Phase 1 target schema
  **exactly**.
- **Task 4.3 -- Concurrent-load verification** -- two adapters serving simultaneously
  under concurrent requests, which is also Phase 2's compatibility gate.

---

## Phase 5 -- Reproducibility and drift enforcement

Cross-cuts every other phase. Low effort, high payoff. **Start it with Phase 2**, not
after: manifests must be emitted from the first training run.

- **Task 5.1 -- Run manifest**, one per training run, shipped inside `adapters/<type>/`:
  base model and exact revision; `lora_rank`, `lora_alpha`, `lora_dropout`,
  `target_modules`; chat template id; `seq_len`, epochs, lr, scheduler, effective
  batch, seed; dataset hash and counts and negative ratio; **prompt file hashes**;
  target schema plus its hash; teacher model and revision; cognee git SHA and training
  code git SHA; final train and val loss.
  The **prompt file hashes** and the **schema hash** are the two most valuable entries:
  they catch drift that is otherwise invisible.

- **Task 5.2 -- Adapter registry** -- the single file defined in the design's
  [registry schema](../specs/slm-lora-adapters-design.md#adapter-registry-schema),
  consumed by both the server config and cognee's routing.

- **Task 5.3 -- Dataset versioning** -- content-hash every split and store the manifest
  alongside. Decide DVC or a hashed object store based on size. **A hash with no way
  to retrieve the bytes is not reproducibility**: given a manifest, the exact training
  data must be re-fetchable.

- **Task 5.4 -- Pre-deploy drift check** *(runnable in CI; gates Phase 4)*
  Reads every manifest and fails if: base model or revision differs across adapters;
  `lora_rank` or `target_modules` differ across adapters; `lora_rank` exceeds the
  server's `--max-lora-rank`; prompt file hashes differ from the working tree's prompt
  files; or an adapter in the registry has no manifest, or vice versa.
  **This check is the deliverable.** Manifests that exist but are never checked are
  decoration.

- **Task 5.5 -- Runbook** -- reproducing a past adapter from its manifest.

**Gates:** every shipped adapter has a complete manifest and the check fails on any
missing field; the check catches a deliberately mismatched adapter in a test; a prompt
file change is detected as drift; retraining from a manifest reproduces val loss and
F1 within a stated tolerance.

---

## Phase 6 -- cognee integration

- **Task 6.1 -- `use_adapter()` context manager** (Path A in the design's
  [integration hook](../specs/slm-lora-adapters-design.md#where-the-integration-hook-goes)).
  Always `reset()` in a `finally`.
  *Unit tests:* concurrent async tasks do not see a leaked config -- this is the test
  that matters, since leakage silently routes unrelated calls to the SLM.
- **Task 6.2 -- Entity-type to adapter mapping driven by the registry**, not hardcoded.
  Fail loudly at startup if the server's loaded adapters and the registry disagree.
- **Task 6.3 -- Resolve the `STRUCTURED_OUTPUT_FRAMEWORK` question** -- establish
  whether it can vary per context or is global-only. If global-only, record the
  constraint; it may force an all-or-nothing choice.
- **Task 6.4 -- Design note for Path B** -- new stage versus per-task knob. Touches
  shared config; warrants its own review and is the one genuinely upstreamable piece.
- **Task 6.5 -- Config recipe documented** -- see the design's
  [configuration table](../specs/slm-lora-adapters-design.md#configuration).
- **Task 6.6 -- End-to-end test** -- `add` -> `cognify` with extraction on the SLM.

**Gates:** extraction demonstrably hits the SLM endpoint with the correct adapter per
type, verified from server logs; heavy-reasoning calls demonstrably still hit the
frontier model, **asserted rather than assumed**; the ContextVar is always reset
including on exception; end-to-end `add` -> `cognify` produces a graph equivalent in
quality to the all-frontier baseline; cost and latency delta recorded.

---

## Definition of done for the whole experiment

1. At least two adapters trained and passing the Phase 3 gates.
2. All adapters served concurrently from one T4, verified under concurrent load.
3. cognee entity extraction routed per type, end-to-end `add` -> `cognify` green.
4. Measured cost and latency delta against the current default model, documented.
5. Config recipe and runbook committed.

Plus two honesty conditions carried over from the original epic, which matter more than
they look:

- **Any phase closed by reducing its scope says so explicitly**, so the experiment is
  never reported complete on the strength of work that was quietly dropped.
- **The architecture decisions still hold at the end, or the deviation is written
  down** in the design document.

## Artifact hygiene

`adapters/`, dataset outputs and eval dumps are **gitignored** -- adapters are roughly
a gigabyte each. Commit the **manifests and the registry** instead: small, diffable,
and the thing that actually makes a run reproducible.
