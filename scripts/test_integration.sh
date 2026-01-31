#!/bin/bash
# Run spec refinement integration tests with coverage and benchmarks

uv run pytest tests/spec_refinement/test_full_workflow.py \
  --cov=scripts/spec_refinement \
  --cov-report=html \
  --benchmark-only \
  --benchmark-save=integration_benchmark \
  -v
