#!/bin/bash
# Run integration tests without benchmarks

uv run pytest tests/spec_refinement/test_full_workflow.py \
  -v \
  -m "not slow"
