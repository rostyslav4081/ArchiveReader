# Local external-engine trials

The supplied archival material stays local. Experiments use ignored `integration-envs/`, `models/` and `test-output/`; no private pages or weights enter the Windows distribution or repository.

## Common inputs

`scripts/build_integration_cases.py` inventories the available attachments, all 77 rendered pages of the two supplied PDFs, 16 FigJam photo-node renders, explicitly supplied JPGs and recovered full archival scans. It currently yields 109 unique normalized images and 114 source aliases. Exact normalized pixel duplicates share inference, while every alias, source document/page and SHA-256 remains recorded. Normalization is EXIF transpose, RGB, maximum side 2400 px; existing PDF previews are 1800 px. This tests available derivatives, not full-resolution equality across the collection. Software error-dialog screenshots are excluded.

There is no human-confirmed body-text reference corpus. Reports therefore record execution, detected geometry, output text and duration, **not CER/WER or accuracy improvement**. Confidence and model agreement are not truth. The complete supplied photos, including headers, margins and phone-browser chrome where present, remain inputs; unrelated text may appear in outputs.

## Roles and deliberate boundaries

| Project | Actual local role | Boundary |
| --- | --- | --- |
| Kraken and experimental Polish TrOCR | Existing specialist handwriting routes and side-by-side comparison | Existing heading diagnostics do not validate whole-body handwriting quality |
| PERO OCR 0.7.0 | Full common-input OCR/layout control, PAGE/ALTO output | Public 2022-09-26 European/Czech newspaper model is primarily print; no handwriting suitability claim |
| PaddleOCR 3.7.0 / PaddlePaddle CPU 3.2.2 (full run), 3.3.1 (earlier control) | Independent full common-input OCR control using PP-OCRv6 small | Unverified text; Windows 3.3.1 oneDNN failure retained; isolated 3.2.2 probe supports the fast mode |
| Docling 2.139.0 | Ten representative full-OCR cases, plus all common inputs through a separate structure-only profile | Handwritten OCR was visibly poor. Structure mode has OCR off and retains empty layout clusters; it cannot claim recognized text or verified table cells |
| eScriptorium | Offline PAGE/ALTO exchange for corrected layouts/text | Uses Kraken, so it is not an independent recognition vote; no full web server is installed |
| Docling MCP, ocr-mcp, pdf-mcp | Reviewed as orchestration wrappers | They are not independent OCR models and are not installed merely to multiply votes |
| MinerU | Reviewed as another document-structure candidate | Not executed or integrated in this package; do not count it in tested model coverage |

Primary project references: [eScriptorium documentation](https://escriptorium.readthedocs.io/en/latest/), [PERO OCR](https://github.com/DCGM/pero-ocr), [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [Docling](https://github.com/docling-project/docling), [MinerU](https://github.com/opendatalab/MinerU).

## Reproduction and retained evidence

- `scripts/test_pero_integration.py`: CPU4, one loaded pipeline, language-model decoder off, per-case raw JSON/PAGE/ALTO and checkpoint report. Official weight archive and its checksum are recorded in `models/pero-print/provenance.json`.
- `scripts/test_paddle_integration.py`: local PP-OCRv6 small weights, CPU4, separate runtime identities for safe and fast modes; resume identity binds actual model-file hashes, package versions and input hashes. See [Paddle setup](PADDLE_INTEGRATION.md).
- `scripts/test_docling_integration.py`: separate OCR and structure reports, preserved raw layout and source identity. Each profile has its own checkpoint fingerprint.
- Private common manifest: `test-output/integrations/cases.json`; per-tool reports are under `test-output/integrations/`.
- PAGE/ALTO import retains raw XML, checks target dimensions/source identities and requires explicit approval of ambiguity or any supported minor coordinate clipping. It never makes imported text verified ground truth.

Model weights have their own licenses. The downloaded PERO archive did not supply a model-license statement; do not redistribute those weights based only on the code license. External environments and experiments do not change the application's core Python dependencies.


## Completed observations

Docling full OCR completed 10/10 representative real inputs with no runtime errors but visibly poor/sparse manuscript text and zero assembled tables (median 55.639 s; total 572.594 s case time). Its separate OCR-disabled structure profile completed 109/109 with zero failures, 193 predicted regions across 97 inputs and zero assembled tables (median 3.974 s; total 628.984 s). Thus even layout execution on this collection does not establish useful handwritten table reconstruction. All 585 referenced output files were checked; source and alias hashes were unchanged.

Latest WPF import/view checks used the actual Downloads PDFs, not synthetic substitutes: 18 pages and 59 pages imported, first-page renders inspected, both original hashes unchanged. These UI checks deliberately leave OCR pending; model inference evidence is recorded in the separate real-image reports. The actual supplied Polish photo was also displayed with PERO's 61 line baselines and its original XML clipping warnings.

## Completed local trials, 2026-10-15
PaddleOCR completed the common109 inputs plus360 pages of six additional AGAD books (469 cases:468 nonempty,1 empty,0 execution failures). Three additional native-resolution/crop diagnostics also completed; the known surname remained incorrectly recognized. PERO completed109 after five isolated compatibility retries (104 upstream successes retained); Docling completed10 OCR examples and109 structure-only cases. These are execution/coverage results, not CER/WER or demonstrated historical-reading accuracy. All source hashes remain unchanged. Candidate surname review is provisional and does not create family facts.
