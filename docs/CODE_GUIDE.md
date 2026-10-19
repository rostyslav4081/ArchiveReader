# Reading the code

ArchiveReader is a Windows desktop application with a local Python engine. Start with this guide for the request flow, then use [Architecture](ARCHITECTURE.md) for persistence and evidence rules.

## Repository layout

| Location | Responsibility |
| --- | --- |
| `src/ArchiveReader.Desktop/` | WPF windows, user interaction, localization, and process ownership |
| `backend/archivereader/` | Import, SQLite persistence, OCR adapters, research tools, and exports |
| `tests/` | Synthetic regression tests; no private scans or model weights |
| `scripts/` | Setup, pinned downloads, diagnostic runners, packaging, and UI smoke tools |
| `docs/` | Architecture, user guides, source catalogues, and documented limitations |
| `.github/workflows/ci.yml` | Windows build and synthetic backend tests |

## Follow a request

1. A WPF event collects explicit user input. `MainWindow.xaml.cs` sends a command through `Call`.
2. Short commands use `CallOnce`. Selected inference commands use `PythonSession.cs`, which serializes requests to a reusable Python process.
3. `model_session.py` carries JSON-lines requests and separates library output from protocol replies. `engine.py` dispatches commands and closes each database connection after the request.
4. Tool modules validate source identity and saved evidence, perform bounded work, and return JSON. `recognizers.py` adapts local recognition runtimes; model output remains a proposal.
5. The window displays the result. Confirmation, source-bound corrections, and training exports are separate actions.

## Where to change behavior

- Document import, rendering, raw OCR, and base tables: `engine.py`.
- Editable normalized regions and reading order: `workbench.py` and `layout.py`.
- Resumable page recognition: `page_review.py`; checkpoint identity includes sources, geometry, and models.
- Verified examples and evaluation: `tutor.py` and `review_corpus.py`. Keep held-out books independent from training.
- Historical context and manually checked exemplars: `historical_reading.py`.
- Similar visual forms: `shape_search.py`. DTW ranks shapes; it does not assign text or establish a common writer.
- Shared model readiness and advisory flags: `recognition_workflow.py`.
- Incremental search: `library.py`; bounded browsing: `paging.py`.
- Backups: `backups.py`; portable research packages: `research_bundle.py`. Their scopes differ.
- People and family evidence: `people.py`, `genealogy.py`, and `fact_review.py`.

## Development conventions

Write comments and commit messages in English. Explain why a guard, boundary, or algorithm exists rather than narrating each statement. Preserve historical spelling and localized interface strings. Never turn a prediction, dictionary match, or visual resemblance into confirmed evidence automatically.

Keep scans, library databases, downloaded weights, environments, build output, and diagnostic artifacts in ignored folders. A source checkout does not include those assets. Download models explicitly using the appropriate scripts; third-party model licences remain separate from this application's code.

Run `python -m unittest discover -s tests` and `dotnet build ArchiveReader.slnx -c Release --nologo --warnaserror`. See [Contributing](../CONTRIBUTING.md) for UI checks. Historical accuracy requires independently verified references; passing software tests does not establish transcription accuracy.
