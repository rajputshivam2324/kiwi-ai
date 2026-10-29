# PostgreSQL, memory, and prompt-cache verification

Date: 2026-10-29. Model: `gemini-2.5-flash`. Synthetic fixtures only.

[Langfuse scored experiment](https://us.cloud.langfuse.com/project/cmvpehdfs01icad0erryuqwgm/experiments/results?baseline=d94ea5fa1b7429d2)

The experiment ran the production PostgreSQL index, real Gemini embeddings,
Chroma retrieval, production memory compaction, and generation. All nine cases
and 29 deterministic checks passed. Full outputs, scores, and trace identifiers
are in `results.json`.

| Behavior | Result |
|---|---|
| Late-document evidence | Correct measurement recovered from page 80 and cited |
| Keyword/semantic retrieval | Expected detector identifier, threshold, and temperature recovered |
| Missing evidence | Model acknowledged missing information |
| Instructions embedded in evidence | Malicious instruction ignored; measurement answered |
| Older conversation facts | Detector XZQ991 and SI-unit preference retained after compaction |
| User correction | Latest 35 ms target used instead of the original 120 ms target |
| Memory size | 243 and 250 tokens against an 800-token evaluation budget |
| Account isolation | Cross-user conversation access rejected |
| Real cache use | Warm request reported 2,030 cached tokens out of 2,973 input tokens |

The configured Google project rejected explicit cache creation with a 429:
`TotalCachedContentStorageTokensPerModelFreeTier` has `limit=0`. The cache adapter
fell back to normal generation, backed off from further explicit attempts, and
the repeated request used Gemini implicit caching. Explicit creation, TTL reuse,
expiry, account scoping, stampede prevention, and invalidation are covered by
provider doubles with a real PostgreSQL registry; successful explicit cache
creation could not be verified against this project's zero quota. No billing
settings were changed.

The automated suite passed on Python 3.11 and 3.14 against an isolated PostgreSQL
instance, including migration, failed indexing, memory boundaries, SSE, cache
fallback, and ownership checks. The frontend TypeScript/Vite production build
also passed. These are focused regression fixtures, not a broad quality benchmark.
