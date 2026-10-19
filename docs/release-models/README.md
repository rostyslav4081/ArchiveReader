# ArchiveReader model packs
Extract the chosen ZIP into the installed ArchiveReader folder, so its models directory merges with the existing models directory. Do not extract into another nested models folder. Restart the launcher; existing saved selections take precedence. Medium is the main candidate, not a guarantee of accurate historical handwriting.

Kraken pack: eight original checkpoints (Medium, Tiny, CATMuS, Bohemica, German handwriting/print, FoNDUE handwriting/mixed).
Paddle pack: detector and recognition files only. Requires a separate compatible Paddle runtime at integration-envs/paddle-stable/Scripts/python.exe. These optional Asian models have not been tested on user documents.
PolishWords: PET3R12 TrOCR, word-oriented and historically unvalidated. Requires the optional Transformers/PyTorch dependencies.
PolishExperimental: experimental pseudo-label TrOCR; requires optional dependencies. Never treat it as verified reference text.

All model weights are distributed unchanged. Upstream metadata, author information and licences are in model-licenses. Files within JSON provenance that contained a local installation path have been replaced with portable paths. Models remain under their own licences; ArchiveReader does not claim their authorship. See each upstream model record for intended use and limitations.

PERO and microsoft/trocr-small-handwritten are omitted because weight redistribution conditions were not sufficiently verified. Python environments and private documents are never included.

For PolishExperimental, download every .part file and Merge-ModelParts.ps1 into the same directory. Run the script in PowerShell, then extract the resulting ZIP as above. Checksums must match MODEL-SHA256SUMS.txt before use.
