# Contributing

Use Python 3.12 and .NET 10 on Windows. Keep changes in the appropriate frontend/backend directory and add regression coverage for persistence, data-loss or OCR protocol changes.

Run `python -m unittest discover -s tests -v` and `dotnet build ArchiveReader.slnx -c Release --warnaserror` before submitting a change. For UI changes, run `python scripts/smoke_test.py` and inspect all four screenshots under `test-output/ui/`.

Keep localization keys and format placeholders complete in `translations.json`. Persist canonical record values independently from translated display labels.

Use synthetic documents in committed tests. Put real scans, OCR output, model weights and private metadata only in ignored folders. Never improve apparent accuracy by dropping uncertain text or silently replacing historical spelling.

New OCR adapters must expose process failures, cancellation, source provenance and line coordinates where available. Confidence must not be presented as measured CER/WER. Training changes require a separate validation set and must not replace the active model automatically.
