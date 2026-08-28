# SLM/LoRA entity-extraction adapters -- progress ledger

**Branch:** `experiment/slm-lora`
**Design:** [slm-lora-adapters-design.md](../../docs/superpowers/specs/slm-lora-adapters-design.md) (v1)
**Plan:** [slm-lora-adapters-plan.md](../../docs/superpowers/plans/slm-lora-adapters-plan.md)
**Base:** cut from `upstream/dev`

**Env:** _not yet recorded -- no hardware run has happened._
Before **any** measured number is written into this ledger, fill in:
GPU model | driver version | CUDA version | base model revision (exact commit) |
Unsloth/peft/transformers versions.
For an experiment whose entire premise is a 16GB hardware ceiling, this line is the
difference between a result and an anecdote.

---

## Status

| # | Task | Status | Commit |
|---|---|---|---|
| 1.1 | Entity type specifications | not started | |
| 1.2 | Target schema decision (lean vs full) | not started | |
| 1.3 | Distillation script | not started | |
| 1.4 | Validation and cleaning | not started | |
| 1.5 | Dedup and document-level splits | not started | |
| 1.6 | Composition and hard negatives | not started | |
| 1.7 | Chat formatting | not started | |
| 2.1 | Parameterized QLoRA template | not started | |
| 2.2 | Loss masking, empirically verified | not started | |
| 2.3 | Multi-type driver | not started | |
| 2.4 | Adapter export (unmerged) | not started | |
| 2.5 | Measured VRAM / wall-clock on the T4 | not started | |
| 3.1 | Entity-level P/R/F1 | not started | |
| 3.2 | Raw JSON validity (no guided decoding) | not started | |
| 3.3 | Cross-type false-fire | not started | |
| 3.4 | Empty-input behavior | not started | |
| 3.5 | Baseline comparison | not started | |
| 3.6 | Failure feedback loop | not started | |
| 4.1 | Multi-LoRA server stood up | **scaffold only** | see log 2026-08-28 |
| 4.2 | Guided decoding matching the target schema | not started | |
| 4.3 | Concurrent-load verification | not started | |
| 5.1 | Run manifest schema + emission | not started | |
| 5.2 | Adapter registry | not started | |
| 5.3 | Dataset versioning | not started | |
| 5.4 | Pre-deploy drift check | not started | |
| 5.5 | Reproduction runbook | not started | |
| 6.1 | `use_adapter()` context manager | **partial** | see log 2026-08-28 |
| 6.2 | Registry-driven type mapping | not started | |
| 6.3 | `STRUCTURED_OUTPUT_FRAMEWORK` scope question | **open question** | |
| 6.4 | Path B design note | not started | |
| 6.5 | Config recipe documented | not started | |
| 6.6 | End-to-end `add` -> `cognify` test | not started | |

**Nothing has been trained.** Two partial deliveries exist, both predating any adapter.

---

## Log

### 2026-08-28 -- documents created, two partial deliveries recorded

Six mutable tickets became this document set. The move was not bookkeeping: the
originals lived in a repository we do not control and had already started to decay --
the epic's "parent analysis" pointer resolved to the wrong document after a routine
copy between forks, and two sub-issue references never resolved to anything at all.
Every cross-reference here is a relative link or an anchor for that reason.

**Partial delivery 1 -- serving scaffolds** (`deployment/slm/`, on this branch).
`lorax-t4.sh`, `vllm-t4.sh` and `cognee_slm_routing.py`. Written before any adapter
existed and **unverified against a real one**; the header of each says "scaffold only".
`cognee_slm_routing.py` also contains a first cut of `use_adapter()`, which is properly
task 6.1's deliverable rather than serving's -- recorded as partial under both.

**Partial delivery 2 -- SLM opportunity benchmark** (branch
`feature/slm-task-benchmark`, deliberately not merged here).
Benchmarks cognee's own call sites -- `search_type` routing, categories, chunk
association, cascade nodes, summary, content graph -- using cognee's real prompts and
response models rather than paraphrases. It answers "which call sites could a small
model take over", which is the question upstream of this whole experiment. It is held
back from an upstream PR until this experiment produces results: a benchmark harness
alone is a weak contribution; a harness plus findings across six call sites is a
strong one.

**Open question carried forward (task 6.3).** `STRUCTURED_OUTPUT_FRAMEWORK` is a global
config field, not per-stage. Whether it can be varied per context, or whether routing
to the SLM implies switching it globally, must be settled before committing to Path A.
Flagged now because it can invalidate the integration approach, not merely delay it.

**Artifact hygiene applied.** `adapters/`, dataset outputs and eval dumps are
gitignored on this branch; manifests and the registry are committed instead.
