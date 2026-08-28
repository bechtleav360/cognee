# Specialized entity-extraction SLMs via LoRA adapters on a single T4 -- Design

**Date:** 2026-08-28
**Branch:** `experiment/slm-lora`
**Status:** design recorded; no adapter trained yet
**Revision:** v1 -- first versioned form. Supersedes a set of six mutable tickets in a
fork we do not control. Those tickets had already begun to decay: the epic's own
"parent analysis" pointer resolved to the wrong document after a routine copy between
forks, and two sub-issue references (`#DATA`, `#SERVE`) never resolved to anything at
all. Everything below is reachable by relative link or anchor for that reason.

---

## Problem

Entity extraction is the highest-volume narrow task in the cognee pipeline, and it
runs on a frontier model for every chunk. A general-purpose model is being paid for
work a small specialized one could do.

The obvious fix -- one fine-tuned model per entity type -- does not fit. A single fp16
7B model is roughly 14GB, so one 16GB T4 holds exactly one. Specialization has
therefore had no practical path.

## Goal

For each domain entity type (`DRUG`, `GENE`, `DOSAGE`, ...), produce a LoRA adapter
that extracts that type about as accurately as a frontier model, emits schema-valid
JSON, and runs alongside every other adapter on one 16GB GPU.

Because the adapters share a base, twenty specialists cost one base model plus roughly
a gigabyte -- not twenty models.

## Scope

**In:** the adapter family for entity extraction, the data and training and evaluation
machinery that produces it, serving them concurrently on one T4, and routing cognee's
extraction calls to them.

**Out, deliberately:**

- Heavy reasoning stays on a frontier model -- core graph extraction, graph and RAG
  completion, query decomposition, chain-of-thought retrieval. See
  [the scope guard](#the-scope-guard-is-the-main-failure-mode).
- Full fine-tuning, pretraining, RLHF.
- Training on the T4 as a steady-state activity. The T4 is the **serving** target;
  training may run there and is expected to be slow.

## Approach (selected: shared-base multi-LoRA)

Train one LoRA adapter per entity type over a single shared base, serve them all from
one T4 with the base loaded once and adapters swapped per request, and route cognee's
extraction to the right adapter per type.

The alternative -- a separate full model per type -- was rejected on arithmetic: it
does not fit the hardware, and the hardware is the constraint the whole design exists
to satisfy.

---

## Architecture decisions -- NORMATIVE

**This section is the contract. Every phase of
[the plan](../plans/slm-lora-adapters-plan.md) inherits it, and no phase may vary a
value here without amending this document and bumping its revision.**

| Decision | Value | Why |
|---|---|---|
| Strategy | LoRA/QLoRA adapters over **one shared base** | N full models do not fit 16GB (one fp16 7B is about 14GB) |
| Base model | `Qwen/Qwen2.5-7B-Instruct` | strong structured output, int4-friendly, permissive licence |
| Training | QLoRA -- 4-bit nf4 base, fp16 compute | fits a T4 |
| Serving | multi-LoRA (LoRAX or vLLM), int4 AWQ base | base loaded once, adapters hot-swapped per request |
| Parallelism | continuous batching, **one** server process | requests for different adapters batch together on shared base weights |
| Precision | **fp16 everywhere -- never bf16** | the T4 is Turing (sm_75): no bf16, no FlashAttention-2 |
| JSON safety | guided/grammar decoding at inference | local models trip instructor's schema modes |
| Adapters | exported separately, **never merged into the base** | merging defeats the shared-base design |

### Cross-adapter compatibility contract

The multi-LoRA server loads **one** base with **one** rank ceiling. Every adapter must
therefore be trained with:

- the same base model **and revision** (pin the exact commit),
- the same `lora_rank` (**16**) and `lora_alpha` (**32**),
- the same `target_modules` -- all attention and MLP projections
  (`q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj`),
- the same chat template and the same serving prompt,
- the same output schema.

**A single adapter trained off-contract breaks the shared-base server.** It is not a
degraded adapter; it is an adapter the stack refuses to load, and the failure appears
at deploy time rather than at training time. This contract is the acceptance criterion
for the training harness, and
[the drift check](../plans/slm-lora-adapters-plan.md#phase-5----reproducibility-and-drift-enforcement)
is what enforces it.

If rank must change, it changes for **every** adapter and all are retrained -- recorded
as a family version bump in this document.

### Why the hardware dictates so much

Every unusual choice above traces to one fact: the T4 is Turing, sm_75, 16GB.

- No bf16 support, so fp16 everywhere -- a bf16 setting is not a preference here, it
  is a crash.
- No FlashAttention-2.
- 16GB holds exactly one fp16 7B model, which is what makes the shared base
  **mandatory** rather than an optimisation.

---

## Known schema problem

cognee's entity extraction response model is `EntityList` -> `List[Entity]`, and
`Entity` extends `DataPoint`. The generated JSON schema therefore also carries `id`,
`created_at`, `updated_at`, `ontology_valid`, `relations`, `truth_alignment`,
`truth_subspace_signature`, `truth_epoch` and `metadata` -- none of which the prompt
asks for.

Meanwhile `extract_entities_system.txt` documents a **lean** contract: `name`,
`is_a{name, description}`, `description`.

So the prompt contract and the Pydantic schema disagree. A frontier model shrugs this
off. A 7B model hallucinates ids and timestamps, or stalls.

**This matters twice.** It constrains this experiment -- the training target schema
must be pinned in
[phase 1](../plans/slm-lora-adapters-plan.md#phase-1----dataset-pipeline) and the serving
grammar must match it exactly. And it is **a genuine upstream bug, independent of
whether any adapter is ever built**: verified still present in `upstream/dev` at
`cognee/tasks/entity_completion/entity_extractors/llm_entity_extractor.py`. It should
be reported upstream on its own merits, not carried privately as an experiment note.

---

## Architecture and components

### Data flow

```
  domain corpus
       |
       v
  cognee's own chunker            <- same chunker as inference, so chunk-length
       |                             distribution matches production
       v
  frontier teacher + cognee's own prompts
       |                          <- reusing the real prompts is what prevents
       v                             train/serve skew
  validate -> dedup -> split by DOCUMENT
       |
       v
  train / val / test  +  shared cross-type test set
       |
       v
  QLoRA training (one template, varied only by type)
       |
       v
  adapters/<TYPE>/  (adapter weights + config + run manifest)
       |
       v
  eval gates  --fail-->  error dump -> targeted new examples -> retrain
       |
       | pass
       v
  adapter registry -> multi-LoRA server on the T4
       |
       v
  cognee entity extraction, routed per type
```

### The scope guard is the main failure mode

Routing must cover **only** the narrow structured extraction calls. Explicitly staying
on the frontier model:

- core graph extraction (`extract_content_graph.py`)
- graph and RAG completion (`modules/retrieval/utils/completion.py`)
- query decomposition, chain-of-thought retrieval

A context wrapper drawn too wide silently downgrades reasoning quality. The symptom --
slightly worse answers -- is far harder to notice than an outright error, which is
what makes this the failure mode to design against rather than test for afterwards.

### Where the integration hook goes

cognee resolves LLM settings through the `llm_config` ContextVar;
`get_llm_context_config()` returns the ContextVar value if set, else the cached global
config. Any LLM call inside that context uses those settings.

There is already a per-stage mechanism, `pipeline_stage(stage)`, which merges
`llm_<stage>_*` overrides. But `_STAGE_NAMES` covers only `{extraction, summarization,
query}`, and **entity extraction is not wrapped in any stage** --
`LLMEntityExtractor.extract_entities` calls `LLMGateway.acreate_structured_output`
directly. Entity extraction therefore always uses the global `LLM_MODEL`.

Two paths, and the recommendation is to do both in order:

- **Path A, short term:** a `use_adapter(name)` context manager that copies the current
  config with `llm_provider="custom"`, `llm_endpoint=<slm server>` and
  `llm_model=<adapter id>`, sets the ContextVar, and resets it on exit. The adapter is
  selected purely by `llm_model`, because the OpenAI-compatible provider passes that
  through as the request's `model` field -- exactly how LoRAX and vLLM pick an adapter.
  Works today with no core changes; the downside is that routing lives in caller code
  rather than configuration.
- **Path B, proper:** give entity extraction its own stage, or a per-task model knob,
  so it is driven by env config like the existing three. Requires extending
  `_STAGE_NAMES` and wrapping the extractor call site.

Ship A to unblock end-to-end validation, then land B and migrate. **Path B is the one
piece of this experiment with a plausible upstream future** (see
[the upstream seam](#the-upstream-seam)), so it warrants its own review rather than
riding along here.

## Adapter registry schema

One source of truth, consumed by **both** the server launch config and cognee's
routing, so the two cannot drift apart:

```
<TYPE> -> { adapter_id, base_model, base_revision, lora_rank, target_modules,
            train_data_hash, f1, json_validity, shipped_at, manifest_path }
```

### Consumer invariants (explicit contract)

- Every registry entry has a manifest, and every manifest has a registry entry. A
  one-sided entry is an error, not a warning.
- `base_model`, `base_revision`, `lora_rank` and `target_modules` are identical across
  **all** entries. Divergence means the shared-base server cannot load them together.
- `lora_rank` never exceeds the server's configured `--max-lora-rank`.
- A mismatch between the server's loaded adapters and the registry fails **loudly at
  startup**, not lazily on first request.

## Configuration

| Setting | Value | Note |
|---|---|---|
| `LLM_PROVIDER` | `custom` | OpenAI-compatible path to the multi-LoRA server |
| `LLM_ENDPOINT` | the SLM server URL | |
| `LLM_MODEL` | the adapter id | this is what selects the adapter |
| `STRUCTURED_OUTPUT_FRAMEWORK` | `litellm_native` | its JSON-object fallback and self-correction loop tolerate local models; the default `instructor` path is what produces parse failures and retry storms against local servers |

**Open constraint:** `STRUCTURED_OUTPUT_FRAMEWORK` is currently a **global** config
field, not per-stage. Whether it can be varied per context, or whether routing to the
SLM implies switching it globally, must be established before committing to Path A. If
it is global-only, that is a constraint to record and possibly a small core change.

## Testing

- Anything exercisable without a GPU is unit tested.
- Anything requiring the target hardware states the hardware it was measured on.
- Evaluation uses greedy or low-temperature decoding so metrics are stable.
- GPU nondeterminism means results are **comparable, not bit-identical** -- assert on a
  tolerance, never on equality.
- The real cross-adapter compatibility test is two adapters from the same template
  loading **simultaneously** on the serving stack without shape errors. Nothing short
  of that proves the contract holds.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Teacher labels are a ceiling** -- the adapter cannot beat its teacher | human-review a stratified sample; consider a stronger teacher for hard types |
| **Prompt drift** -- cognee's prompt files change and adapters silently degrade | record prompt file hashes in every manifest; the drift check compares them against the working tree |
| **Rank or target-module drift across adapters** | hyperparameters live only in the shared template; assert them from manifests in CI |
| **Over-broad routing** downgrading reasoning quality | the scope guard above; assert that heavy-reasoning calls still hit the frontier model |
| **ContextVar leakage** across concurrent async tasks | always `reset()` in a `finally`; test with concurrent tasks |
| **Metric gaming** -- thresholds set after seeing results | thresholds recorded per type in config *before* evaluation runs |
| **Test-set leakage** via near-duplicate chunks | dedup before splitting; split by document, not chunk; assert it in the eval harness |
| **Training and serving on the same T4 concurrently** | will OOM. Serialize, or train elsewhere |
| **Scope creep into full MLOps tooling** | manifests, one registry, one check. Experiment tracking is optional |

## The upstream seam

Most of this will never be cognee code. Marking the boundary now makes a future
contribution a clean extraction rather than an archaeology exercise.

| Component | Nature | Plausible upstream? |
|---|---|---|
| Dataset pipeline, training harness, eval harness | trains models; not cognee code at all | **No** |
| Serving scripts | T4-specific deployment tooling | **No** |
| Per-task routing (`use_adapter()`, the registry, Path B) | touches cognee core config | **Yes** -- once proven |
| The `EntityList` schema mismatch | an upstream bug | **Yes** -- and independent of everything else here |

If this experiment succeeds, what gets proposed upstream is the **routing hook** and
the **schema fix**. Not the adapters, not the training rig, and not these documents.
