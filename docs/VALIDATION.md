# Validation: experimental v0.1.0

Local validation date: 2026-10-01. The current [machine manifest](validation-manifest.json) and [test log](test-results.txt) are authoritative for test count, versions and file hashes. The original fixture artwork and all proof pages were rendered and visually inspected by an assistant. This is not a human security audit.

## Positive cases

- Two linked original advertising pages placed into a five-page fictional magazine in reversed order, with editorial inserts
- Three original external links restored, including mailto and exact query/fragment strings; one existing external link and internal TOC link retained
- Multiple outlines and named destinations preserved, with logical page destinations checked by independent MuPDF parsing rather than comparing unstable object IDs
- Every target page's visible pixels unchanged in actual Poppler and MuPDF rendering
- A repeat against a reviewed/hash-bound recovered input adds zero links and produces byte-identical PDF bytes
- Running the same input/map twice produces identical PDF, proof and receipt bytes in this environment
- A skill folder copied outside the repository successfully runs repair independently
- A synthetic 144-dpi rasterized re-export keeps the same page dimensions and alignment: exact-artwork mode rejects its nonidentical pixels; an explicitly approved test-only reviewed-identity map permits repair and reports that alignment is not automatically proved

The example approved maps are generated from known fixture construction. They simulate the input contract for tests; they are explicitly labeled automated test acknowledgments, not human reviews of real publications.

## Refusal and regression cases

Tests cover bad hashes, unapproved maps, duplicate JSON keys, reserved IDs, ambiguous/invalid page maps, boolean page numbers, wrong pages with matching dimensions, declared scale/offset/skew, actual shifted artwork in exact mode, rotation (including malformed fractional rotation), cropping, UserUnit, hotspot conflicts, source duplicate suppression, QuadPoints, hidden links, forms, encryption, signature indicators, JavaScript, action chains, untyped/indirect/unknown outline actions, file destinations, malformed rectangles/PDFs, output overwrite, FIFO map input, URI ambiguity and canonicalization work limits.

Source internal links are reported as skipped. Exact duplicate source links are suppressed with separate provenance and counts; they are not mislabeled as links that already existed in the target.

A separate reviewer added `tests/test_independent_review.py`, then reran the full suite and inspected fresh proof renders. Review findings were fixed and retained as regression tests. Original fixtures now use embedded fonts; the earlier unembedded-font renderer artifact is not present in the shipped examples.

## Important unproven claims

No actual InDesign export was available. No compatibility claim is made for all exporters, all viewers, large customer publications, Windows, print production or accessibility standards. `reviewed-identity` can be wrong if a reviewer approves incorrect alignment; the helper cannot prove a human assertion. The skill explicitly forbids an assistant silently self-approving such a map.

Bounds and timeouts are not OS isolation. Parser/decompression behavior still depends on patched dependencies, and 96-dpi rendering does not establish equality at every resolution. No link destination was visited or tested for availability. There is no public CI run until this repository is actually published and CI executes.

## Reproduce

```bash
python -m pip install -r requirements-dev.txt
python tests/validate_release.py
```

This reruns all tests, verifies the checked-in example bundle hashes, and refreshes the local manifest and log. Updating source code without refreshing this validation record makes its file hashes stale; check them before describing a release as validated.
