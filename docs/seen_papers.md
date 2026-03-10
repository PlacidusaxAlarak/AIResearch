# Seen Papers State

History-based sent-paper deduplication is currently disabled in the public release.
The legacy `seen_cache_path` setting is still accepted for compatibility, but the
pipeline treats it as deprecated and does not persist a seen-paper cache.

## What This Means

- Re-running the pipeline can notify the same paper again.
- `seen_cache_path` is retained only to avoid breaking older local configs.
- Runtime state that is still written lives under `state/` and `output/`.

## Recommendation

If you need deduplication, implement it as a separate publishing or notification
policy instead of relying on the deprecated seen-paper cache path.
