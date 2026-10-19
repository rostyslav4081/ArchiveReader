# ArchiveReader

Local Windows workspace for scanned books, photographs, historical handwriting and modern documents. Built with C# / WPF and a process-isolated Python engine.

**Interface languages:** Ukrainian, English, Polish and Czech. Interface language never changes a document's spelling or the OCR model.

**Photo books:** assemble naturally ordered photo folders or selected imported pages, reorder scans, mark missing folios, recognize the book and export an image PDF with a searchable Unicode OCR/HTR layer and a coverage report. Shared book profiles, source cards, dictionaries, semantic column templates, field-filtered search and region-linked research tasks are available under **Книги з фото**. Handwritten and mixed PDFs use the selected handwriting model; PDF format never implies printed text.

[Вимоги до історичного читання](docs/READING_REQUIREMENTS.uk.md) · [Довідники письма](docs/HISTORICAL_GRAMMARS.uk.md) · [Глобальні каталоги мов](docs/GLOBAL_SOURCES.uk.md) · [Українська інструкція](docs/USER_GUIDE.uk.md) · [Architecture](docs/ARCHITECTURE.md) · [Development status](docs/STATUS.md) · [Code guide](docs/CODE_GUIDE.md)

[International sources and reproducible multilingual evaluation](docs/INTERNATIONAL.uk.md): initial archive research across 17 countries, FamilySearch access notes, HTR-United metadata tooling and a pinned seven-language EHRI diagnostic test. Portal discovery is recorded separately from actual OCR evaluation. [Handwriting comparisons](docs/HTR_COMPARISON.uk.md) keep shared line inputs, reference text and model provenance together.

The current research workspace adds bounded page browsing, background full-text indexing, full portable research packages, a book review assistant, offline PAGE/ALTO interchange and a historical-reading review window. [Scope and limitations](docs/STATUS.md) · [External engine trials](docs/EXTERNAL_INTEGRATIONS.md).

## What works

- Review literal historical readings separately from explanations; keep explicit multilingual lexical concepts, manual hand labels and source-bound pixel letter examples. Same-hand examples are advisory, not an automatic handwriting classifier or trained grammar model.

- Import PDF, JPEG, PNG, multipage TIFF, BMP, WebP and GIF; keep a hash-verified copy of each original and avoid duplicate imports.
- Browse pages without rendering the entire book into memory. Preview images are limited to 1800 pixels on the longest side; OCR derivatives to 7000.
- Run Kraken 7.1.1 with local `.safetensors` / `.mlmodel` weights, or an independently installed Tesseract executable. PDF text-layer extraction is optional.
- Run a bounded background queue with one or two isolated OCR workers, selected conservatively from available memory and CPU count. Failed pages can be resumed.
- Select an OCR region with the mouse, keeping the original image intact. Useful for book spreads, individual columns, screenshots and page margins.
- Preview lighting normalization and inspect basic image-quality hints. Mark missing fragments separately from illegible writing; unresolved markers remain in exports but are excluded from training and verified-line accuracy calculations.
- Inspect OCR lines, confidence and bounding boxes; select a line from the scan or the list.
- Keep complete page text separately from structured register entries. A page may contain multiple entries; narrative and mixed documents remain free text until a researcher interprets them.
- Record birth, marriage, death, other and illegible entries. Names, dates and historical spelling are entered verbatim; there is no automatic genealogical inference.
- Export the selected book to XLSX (five sheets, filters and frozen headings), JSON, CSV or TXT. Full page OCR text, source paths and page numbers remain available in structured exports. XLSX export rejects oversized cells instead of silently truncating them.
- Record archival source cards with fonds/inventory/file references, original folios and scan URLs; copy citations and include them in exports. Derived images inherit their original source references.
- Review possible person links between saved records with both source texts and citations. Explicitly confirm, reject or withdraw with a reason; changed records flag earlier decisions for review. JSON preserves link evidence snapshots.
- Automatic verified database/original backups, seven snapshots and restore to a separate library, including recovery from a corrupt working database. Configure a different disk for disk-loss protection; models and separate report/training files are excluded.
- Keyboard correction: F8 next unverified OCR line, Ctrl+Enter verify-and-next, Ctrl+S save, Ctrl +/− zoom and Ctrl+0 reset.
- Person cards collect explicitly assigned mentions and source evidence. Confirm parent/spouse relationships, reject ancestor cycles and navigate a family tree; export genealogy JSON.
- Selected field proposals from explicit labels and numeric dates preserve source text spans; populated fields require explicit replacement permission.
- Persistent sequential multi-book queues support cancellation, restart recovery and error retry. Evaluation coverage and local runtime/model checks help prepare verified test books.
- Build a Windows ZIP with `scripts/Package-Windows.ps1`; run `Install-ArchiveReader.cmd` for a per-user copy. Requires Python and .NET Desktop Runtime; model weights and private data are excluded.
- Fact-specific scan crops, reversible person-card merge/split and conservative chronology hints with explicit calendar settings.
- UTF-8 GEDCOM subset preview/import and GEDCOM 7 export with loss reports. Imported facts remain unverified; scan media and complete history are excluded.
- Perceptual duplicate candidates require manual decisions; only confirmed full-page targets with recognized sources can be skipped in queues. Per-book verified dictionaries provide F2 correction hints.
- Store correction history in SQLite. Export verified line images and ground truth for Kraken, with document-separated training/validation splits.
- Start an explicit fine-tuning run into a **new** checkpoint directory. The active model is never replaced automatically. Full training has not yet been validated with an adequately sized historical ground-truth corpus.
- Inspect CER/WER on manually verified lines. These statistics are **not** an unbiased accuracy benchmark.
- Open the document workbench for editable line/entry/column evidence regions, damage notes, paired Kraken/TrOCR predictions with highlighted differences, book profiles and similar-name source links.
- Preview rotation, spread splitting, perspective correction and manually guided dewarping as separate images before importing them.
- Assign whole books to train/validation/test, export verified regions and compare the original and fine-tuned models on held-out books. A synthetic native Windows training smoke run succeeded; historical quality improvement remains unvalidated.
- Review disagreements, OCR failures and marked damage with neighboring-line context; search an incremental library index with highlighted snippets and unrecognized-page counts.
- Restore earlier records, corrected lines and region bounds, apply column templates to selected same-book pages, and compare models on checksum-verified frozen evaluation sets.
- Propose line/entry/column geometry and reading order for review; reuse manual columns, edit sequence and assemble saved line text. Recognize a saved entry/column through an isolated crop without overwriting page OCR or manual corrections.

[Downloaded archive samples](docs/ARCHIVE_TESTS.uk.md) cover a Czech handwritten register spread, a Polish document mixing print and handwriting, and a 26-page Hungarian scanned book. These are execution tests, not a representative accuracy benchmark. Photographed PDF pages require OCR/HTR before their contents are searchable; a dominant scan is not skipped merely because a caption is present.

Scanners, TWAIN and WIA are intentionally outside the current scope.

## Quick start on Windows

Prerequisites: **.NET 10 SDK**, **Python 3.12**, internet access for initial dependency/model downloads. Processing then runs locally.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/Setup.ps1
python scripts/download_model.py
.\Start-ArchiveReader.cmd
```

The launcher selects the project's `.venv`, local Kraken executable and downloaded base model. Its library is stored in `data/`. Running the executable directly instead uses `%LOCALAPPDATA%/ArchiveReader`, unless `ARCHIVEREADER_DATA` is set.

The pinned tiny model is small and useful for initial tests, **not a promise of accurate historical transcription**. Difficult handwriting, old orthography, faded ink and tables still need careful review and suitable models. Model provenance and checksum are documented in [MODELS.md](docs/MODELS.md).

Kraken's officially documented operating systems are Linux/macOS. Native Windows installation and an inference smoke test succeeded on the development machine; the application reports dependency failures rather than substituting invented text.

## Development

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
dotnet build ArchiveReader.slnx -c Release --nologo --warnaserror
python scripts/smoke_test.py
python scripts/smoke_test.py --library
python scripts/smoke_import.py
```

`requirements-ocr.txt` specifies the OCR dependency. `requirements-ocr-windows.lock.txt` records the exact Windows Python 3.12 environment used for inference testing. GitHub Actions builds the WPF application and runs tests without downloading neural models. The UI smoke script renders all four languages using synthetic content.

```text
src/ArchiveReader.Desktop/   WPF application, UI localization
backend/archivereader/       SQLite, import, previews, OCR adapters and export
tests/                      Synthetic regression and localization tests
scripts/                    Setup, model download, UI/corpus tests
docs/                       User guide, architecture and known limitations
.github/workflows/          Build and test automation
```

## Testing your own documents

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/test_corpus.py C:\MyArchive `
  --pdf book.pdf --image page.jpg --output test-output/my-archive
```

Optional `--region x y width height` uses normalized coordinates from 0 to 1 and compares whole-page OCR with region OCR. Reports include import/recognition times, process-tree memory observations, errors and verification that source files did not change. Source files, copied originals, transcriptions, SQLite databases and screenshots stay in the ignored output folder.

## Repository and data

Only source code, documentation and synthetic tests belong in Git. `.gitignore` excludes `data/`, `models/`, `.venv/`, `test-output/`, build outputs, databases and model weights. Do not move private collections into tracked source folders.

No cloud OCR, telemetry or account is required. This repository does not include third-party model weights. See [THIRD_PARTY.md](docs/THIRD_PARTY.md) for dependency notices. A distribution license for this project's own source has not yet been selected.
