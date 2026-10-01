# Need, related work and scope

Sources checked on 2026-10-01. These are need signals and technical references, not endorsements or proof that the problem remains identical in every current product version.

## A concrete publishing problem

- [Adobe Community, April 2025](https://community.adobe.com/questions-671/keeping-links-from-a-placed-pdf-active-in-indesign-exported-pdf-895686): a manual publisher describes source PDFs whose hidden hyperlink labels lose interactivity after placement, while final-publication TOC requirements make wholesale page replacement unsuitable
- [InDesign feature request](https://indesign.uservoice.com/forums/601021-adobe-indesign-feature-requests/suggestions/33658483-enable-hyperlinks-to-stay-live-in-pdfs-even-af): users describe advertisements/newsletters and repeated manual hotspot reconstruction; recent comments also report large-document pain

This v0 does not reproduce those authors' private publications and is not an Adobe plugin. It tests a constrained after-export recovery approach with original fixtures.

## Existing solutions deserve credit

- [notein-pdf-repair](https://github.com/jadia/notein-pdf-repair): fixes Notein link borders/zoom and copies original navigation catalog structures to an exported counterpart. Its current README specifies equal page counts for navigation synchronization. This project is scoped to explicit placements across differently sized publications while preserving the target's existing catalog
- [apdfhelper](https://github.com/PeterMosmans/apdfhelper): provides PDF/planner link rewriting, TOC editing and page organization
- [EverMap AutoBookmark](https://evermap.com/abm_lnk_summary.asp): documents link import/export and transferring links between documents, plus broader link-management tools

These observations are not a complete competitive audit. Copying annotations is not new. PlacedLinkRescue's proposed value is the assistant workflow: refuse guessing, bind a reviewed map to bytes, show exact hotspot/destination evidence, and verify the target publication survives.

## Technical references

- [pypdf writer](https://pypdf.readthedocs.io/en/stable/modules/PdfWriter.html): whole-document cloning and annotation operations
- [pypdf security](https://pypdf.readthedocs.io/en/stable/user/security.html): security limits and parser behavior; this helper does not disable dependency protection
- [PDF Association link annotation errata](https://pdf-issues.pdfa.org/32000-2-2020/clause12.html): a rectangle is not equivalent to arbitrary QuadPoints; this v0 refuses the latter
- [Poppler pdftoppm manual](https://manpages.debian.org/unstable/poppler-utils/pdftoppm.1.en.html): page rendering and annotation-hiding behavior

No third-party source code was imported from the related projects. No forum participant was contacted, and no private material was collected.
