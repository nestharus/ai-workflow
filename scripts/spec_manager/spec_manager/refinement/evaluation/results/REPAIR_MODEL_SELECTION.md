# Repair Model Selection Report

**Date**: 2026-01-31

## Models Tested
- gpt-5.2-none
- gpt-5.2-low
- claude-haiku
- gemini-3-flash

## Fixture Summary
- Total fixtures: 36
- Categories: invalid_file_id, invented_section, missing_citation, stray_preamble, trailing_fence, compound_pointer

## Results Table
| Model | Pass Rate | Avg Edit Distance | Avg Latency (ms) | Total Cost (USD) |
| --- | --- | --- | --- | --- |
| gpt-5.2-none | Pending bakeoff | Pending bakeoff | Pending bakeoff | Pending bakeoff |
| gpt-5.2-low | Pending bakeoff | Pending bakeoff | Pending bakeoff | Pending bakeoff |
| claude-haiku | Pending bakeoff | Pending bakeoff | Pending bakeoff | Pending bakeoff |
| gemini-3-flash | Pending bakeoff | Pending bakeoff | Pending bakeoff | Pending bakeoff |

## Recommendation
Current default: **gpt-5.2-low**, which matches the existing repair agent configuration. Run
`uv run spec.repair-bakeoff` to confirm or update this recommendation based on measured pass
rate, latency, and cost.

## Next Steps
- Update repair agents to use the selected model once bakeoff results are available.
