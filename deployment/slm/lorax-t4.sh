#!/usr/bin/env bash
# Multi-LoRA serving on a single T4 (16GB, Turing sm_75, fp16 only).
# One int4 base + many hot-swapped adapters. Adapters live under ./adapters/<name>.
# LoRAX = OpenAI-compatible server; pick the adapter per request via the "model" field.
#
# Scaffold only -- see the design doc at
# ../../docs/superpowers/specs/slm-lora-adapters-design.md,
# and the serving phase of ../../docs/superpowers/plans/slm-lora-adapters-plan.md.
set -euo pipefail

ADAPTERS_DIR="${ADAPTERS_DIR:-$PWD/adapters}"

docker run --rm --gpus all --shm-size 1g -p 8080:80 \
  -v "${ADAPTERS_DIR}:/data/adapters" \
  ghcr.io/predibase/lorax:latest \
  --model-id Qwen/Qwen2.5-7B-Instruct-AWQ \
  --quantize awq \
  --dtype float16 \
  --max-input-length 3072 \
  --max-total-tokens 4096 \
  --max-batch-prefill-tokens 4096 \
  --max-concurrent-requests 64

# Notes:
#  - AWQ int4 base ~4.5GB -> leaves ~8GB for KV cache + adapters.
#  - float16 forced: Turing has NO bf16.
#  - All adapters MUST be trained from Qwen2.5-7B-Instruct with rank <= the server default.
#  - Request routing: set OpenAI "model" = adapter path/id, e.g. "drug", "gene".
#    LoRAX loads/caches the adapter on first use and merges it per request.
