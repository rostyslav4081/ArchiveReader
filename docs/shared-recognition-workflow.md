# Shared recognition workflow

Main window: **Спільна робота з моделями** (requires a selected page).

- Scribe label edits the existing historical book profile with its revision guard. The existing checked, source-bound glyph samples and applicability rules remain authoritative; changing the writer does not silently relabel old examples.
- Line boundaries open the existing manual merge/split/order workflow. Geometry belongs to source annotations rather than a particular model.
- Confirmed examples open the existing teacher workflow. Drafts, stale examples and book roles remain visible. Export uses the existing explicit dataset exporter, retaining damage/uncertainty exclusions and train/validation/test separation. Machine agreement never becomes human verification.
- Advisory review flags identify empty output, unusually short fragments, repeated word sequences, numbers and explicitly recorded names/dates/house values. These are review hints, not error diagnoses or automatic corrections. Empty annotations are labelled **not yet transcribed**, not failed model output. Separate region results are shown only when their source hash and annotation snapshot still match.
- The model chooser shows local size and component availability. File/configuration readiness is distinct from successful execution and book-specific accuracy; book validation is opened separately. It does not claim that untested Asian language packages were validated.

Capabilities are explicit for Kraken, TrOCR, Tesseract and Paddle. Built-in fine-tuning remains Kraken-only and creates a copy; other engines currently use export-only examples. Automatic handwriting identification, automatic learning of grammar and engine-independent fine-tuning are not implemented.

Safetensors comparisons now route through the modern persistent Kraken adapter instead of the legacy recognizer. The comparison model is no longer automatically prefilled with a German specialist for arbitrary books.

Checks: synthetic workflow/reference isolation, test-book role retention, missing-component readiness, modern comparison dispatch, localisation and WPF rendering. No recognition was run with the newly installed Asian language packages.
