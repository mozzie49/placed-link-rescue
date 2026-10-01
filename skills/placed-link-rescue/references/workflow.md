# Input contract and operating notes

Requires Python 3.10+, `pypdf`, Pillow, ReportLab and Poppler `pdftoppm`. See the pinned adjacent requirements file. Copies of this entire skill folder run independently of the repository. Example commands use `python /path/to/placed-link-rescue/scripts/placed_link_rescue.py` as `HELPER` below.

- `HELPER inspect original.pdf export.pdf`: JSON inventory; no PDF writes
- `HELPER draft-map --source ads=original.pdf --target export.pdf --placement ads:2:2 --placement ads:1:4 --output map.json`: exclusive-create unapproved map
- `HELPER preview --map map.json --output-dir review-proof`: proof and comparison JSON, no repaired PDF
- `HELPER repair --map map.json --output-dir digital-bundle`: new digital PDF, final proof, receipt

All file paths in a map are relative to that map's directory, unless absolute. Input bytes are captured once and hash-checked; parsing/rendering use those captured bytes. SHA256 values are lowercase hex. Source IDs are identifiers and cannot be `target`. Repeated placements of one source page to different target pages are allowed. A target page may have at most one source placement. Page counts may differ. Page numbers are positive 1-based integers, not labels.

## Map schema 1

```json
{
  "schema": 1,
  "review": {
    "approved": false,
    "reviewer": "",
    "note": "",
    "alignment": "exact-artwork"
  },
  "target": {"path": "export.pdf", "sha256": "64-character SHA256"},
  "sources": {"ads": {"path": "original.pdf", "sha256": "64-character SHA256"}},
  "placements": [
    {"source": "ads", "source_page": 1, "target_page": 4, "transform": [1, 0, 0, 1, 0, 0]}
  ]
}
```

Only the identity transform is accepted. Matching effective MediaBox, CropBox, TrimBox, BleedBox and ArtBox are required; all pages in these narrow v0 input documents must have zero-origin MediaBox, no crop, zero rotation and UserUnit 1. Any declared scale, translation, skew or rotation fails. Artwork can still move *inside* equal page boxes; `reviewed-identity` is a human assertion that this has not happened. No approximate image match or automatic coordinate transformation exists.

`exact-artwork` compares source/target RGB render bytes at 96 dpi with annotations hidden; equality is a useful check at that resolution, not a mathematical proof at every resolution. `reviewed-identity` also computes and reports this comparison, but permits unequal artwork only on an already approved map. It does not prove placement. Re-exporting fonts, rasterizing or changing antialiasing can make otherwise valid placement unequal.

## Preservation and repeat runs

The target is cloned as a complete document. New annotations contain a fresh Link/URI dictionary, the source rectangle and an invisible border. Source resources/actions/appearance streams are never imported. The tool verifies catalog (including outlines, named destinations, page labels), page content/resources, info metadata and existing annotations semantically after reopening, with indirect page references normalized to page indexes. All target pages are additionally rendered before/after at 96 dpi with annotations shown and must match byte-for-byte in RGB pixels. Any verification failure discards the temporary bundle.

Existing exact URI+rectangle links are retained and counted as already present. Repeated identical source annotations are separately counted as `source_duplicates` and appear as `source-duplicate` in the receipt; only one hotspot is added. Any other overlap, including internal target links, refuses the operation. A repeat run must use a new target record bound to the repaired PDF and be reviewed for that input; then no-op recovery copies its bytes exactly to the new bundle. A stale original map deliberately fails against a newer target.

## Boundaries and errors

Only rectangular visible link annotations are accepted; QuadPoints, hidden/no-view/optional-content links and other annotation subtypes are rejected. Existing target internal navigation is retained. Source internal links are listed as skipped because destination page remapping is outside v0. Unsupported source URI schemes are reported, not activated. Forms, signatures, encryption (even empty-password), automatic/JavaScript/remote/launch/chained actions, attachments and other recognized active features are rejected rather than removed. Tagged documents can retain existing tags, but added annotations are untagged. No PDF/UA, PDF/A or print-ready guarantee.

Bounds: 64 MiB per input; 256 MiB total; 600 pages/document; 100 sources; 20,000 annotations/document; 100,000 reachable indirect objects; 500,000 traversal/canonicalization work steps; depth 100/120; 2 MiB map; 2,000 pt page edges; 8 million rendered pixels; 4,096-character destinations; 45-second timeout per rendered page; 512 MiB total rendered working images. XMP/XML is not parsed, fetched or expanded. These are practical checks, not a hardened hostile-PDF sandbox: parsing/decompression can still consume resources before a check. Use current patched dependencies and OS isolation for untrusted files. The helper has no network code; PDF-renderer safety still depends on Poppler and the host.

Exit 0 means the command completed. Processing failures use exit 2 and a JSON refusal on stderr; invalid command syntax uses argparse usage text. No repair is emitted if prerequisites, mapping, links, rendering or preservation fail. Existing output directories and symlinks are refused. Bundle creation is staged and completed with the receipt last; process termination or hardware failure can still interrupt filesystem publication, so require all three files and verify receipt hashes before use.
