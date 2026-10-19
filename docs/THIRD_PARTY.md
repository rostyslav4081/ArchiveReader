# Third-party components

ArchiveReader does not vendor the source of these projects or copy code from HandWritten-OCR-II.

| Component | Purpose | Upstream |
| --- | --- | --- |
| .NET / WPF | Windows UI/runtime | https://github.com/dotnet/wpf |
| Python | Local document workers | https://www.python.org/ |
| Pillow | Image decoding/derivatives | https://python-pillow.org/ |
| PyMuPDF | PDF rendering and text extraction | https://pymupdf.readthedocs.io/ |
| Kraken | OCR/HTR and optional training | https://github.com/mittagessen/kraken |
| PyTorch and related dependencies | Neural inference | https://pytorch.org/ |
| Tesseract (optional) | Printed-text OCR | https://github.com/tesseract-ocr/tesseract |

Installed package metadata identifies Pillow as MIT-CMU, Kraken as Apache-2.0, and PyMuPDF as AGPL-3.0 / Artifex commercial dual licensing. Dependencies and model weights retain their own licenses. No claim is made that the complete application bundle is MIT-licensed. This project's distribution license is not yet selected.

The starter model's provenance and license are in MODELS.md. Documents used for local testing are user-provided, remain local and are not included in the repository.


## Optional isolated experiments

PERO OCR, PaddleOCR/PaddlePaddle and Docling/EasyOCR are tested in separate local environments and are not added to the core runtime dependency list or Windows ZIP. Upstream projects and their model licenses remain separate. PERO public model provenance and the narrow Shapely2 compatibility diff are retained locally with hashes. PAGE and ALTO are interchange schemas; validation copies/hashes are retained in private test output, while the application uses a bounded offline subset without network schema resolution. See [external trials](EXTERNAL_INTEGRATIONS.md).

## Glottolog language identifier metadata
Bundled global_languages.json derives from the official glottolog/glottolog-cldf languages.csv at revision 072ca0d0410039fb8b779be8fc165bac575d2cda. CC-BY-4.0. Attribution: Hammarström, Harald & Forkel, Robert & Haspelmath, Martin & Bank, Sebastian. 2026. Glottolog 5.3. Leipzig: Max Planck Institute for Evolutionary Anthropology. DOI 10.5281/zenodo.18840967. Exact source URL, CSV SHA256, license URL and the README/CLDF version-label discrepancy are retained in the bundled metadata. Reproducible offline transformation: scripts/build_global_languages.py; publisher names/identifiers retained, no dictionaries or OCR weights included.
