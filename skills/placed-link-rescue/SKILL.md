---
name: placed-link-rescue
description: Recover original external PDF link hotspots into a separately exported publication using an explicit reviewed page map. Use for whole-page PDF placements that lost hyperlinks; excludes scaled, cropped, rotated, partial-page placements and guessing URLs from text.
---

# Placed Link Rescue

Use the local helper in `scripts/placed_link_rescue.py`. Resolve its path relative to this skill, not the current working directory. Install `requirements.txt` in an isolated Python environment and provide Poppler's `pdftoppm` on PATH. No service, credentials, network requests, InDesign installation, or other skills are required.

## What counts as evidence

The source PDF must contain the actual supported HTTP(S)/mailto link annotation. The final exported PDF is the document to preserve. Never infer a hidden destination from its visible label, search the web for a replacement, swap source pages into the target, or treat equal page dimensions as proof of placement.

Ask for the originals, the final export and the source-page → final-page mapping if absent. Pages are 1-based. A map may be proposed from visible artwork or layout records, but label it unreviewed and show the evidence. Do not set `approved: true` yourself merely because visual inspection looks plausible. Obtain the user/human reviewer's explicit identity-placement acknowledgment, or use a supplied already-approved map. A supplied, hash-matching map with an explicit identity-placement review can be used without demanding the same approval again.

## Local workflow

1. Run `inspect SOURCE.pdf TARGET.pdf`. It reports original annotations, hashes, geometry and skipped internal/unsupported-scheme links. Read refusal messages instead of bypassing a guard.
2. Create an unapproved map with `draft-map --source ads=SOURCE.pdf --target TARGET.pdf --placement ads:1:4 --output map.json`. Repeat source and placement options as needed. The helper does not discover mappings or approve them.
3. Run `preview --map map.json --output-dir preview`. Inspect every source/target pair in `preview/proof.pdf`, including every numbered hotspot. Verify whole-page artwork, the exact text/image under each hotspot, 100% scale and zero offset. If evidence cannot establish identity coordinates, stop and ask for the placement record or a corrected export. Do not approve shifted, scaled, cropped or reflowed content.
4. Review the map's `review` record. `approved: true` requires an identified human reviewer, their explicit acknowledgment and an evidence note. An assistant's own inspection is supporting evidence, not that acknowledgment. Keep `alignment: "exact-artwork"` when possible. This requires equal rendered artwork at 96 dpi. Normal re-exports may differ; use `alignment: "reviewed-identity"` only after explicit visual/placement-record review of the proof. The receipt will call this human-attested, not automatically proved. Never silently change to this mode because exact mode failed.
5. Run `repair --map map.json --output-dir NEW_BUNDLE`. It creates `digital.pdf`, `proof.pdf`, and `receipt.json` only after preservation checks pass. Do not overwrite the source, export or an old bundle. Inspect final proof and receipt; report recovered, already-present and skipped counts plus any human-attested alignment.

For syntax, schema, limitations and repeat-run handling, read [references/workflow.md](references/workflow.md).

## Deliver honestly

Deliver the separate digital copy with its proof and receipt. Originals stay unchanged. No destination is visited, tested, executed or deemed safe. Existing target navigation is preserved, not rebuilt. Do not claim restored source internal navigation, accessibility tags, print certification, general InDesign compatibility or production validation. This version has original synthetic vector/raster fixtures, no real InDesign export or private publication test. If a guard blocks a real file, report it; do not strip features, alter the map hash, or loosen checks to make it pass.
