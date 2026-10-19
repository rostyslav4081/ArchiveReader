# Local PaddleOCR integration experiment

This experiment uses a separate `integration-envs/paddle` Python environment. It does not change the application's `.venv` or save recognition into the live library. Inputs are the checksummed, normalized copies in `test-output/integrations/cases.json`; every source alias remains in the report.

The initial isolated environment uses PaddleOCR **3.7.0**, CPU PaddlePaddle **3.3.1** and PaddleX **3.7.2**. A second, separate `integration-envs/paddle-stable` environment uses CPU PaddlePaddle **3.2.2** with the same OCR/PaddleX versions to work around the actual accelerated-inference failure below. Reports always record their exact package versions and configuration identity. Resolved package lists are stored in the ignored integration output folders.

Primary upstream references:

- [PaddleOCR on PyPI](https://pypi.org/project/paddleocr/3.7.0/)
- [PaddlePaddle on PyPI](https://pypi.org/project/paddlepaddle/3.3.1/)
- [Official local OCR pipeline documentation](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/OCR.en.md)

`scripts/download_paddle_models.py` downloads the official `PP-OCRv6_small_det` and `PP-OCRv6_small_rec` inference archives. It records their URLs, archive SHA-256 digests and extraction directories in `models/paddle-integration/provenance.json`. The detector archive SHA-256 is `bfb7c1e59f0faa6b540ebdca93aea3f4b1f2477805b389fbee117820d68fe9f5`; the recognizer archive SHA-256 is `da460f968ce9f88325ac3a34fa302077d6e9b0dcefb16ba3137cd7796f879d06`. Weights are excluded from Git and the normal Windows application package.

For a fresh checkout on Windows with Python 3.12, create only the separate environment and install the committed dependency pins:

```powershell
py -3.12 -m venv integration-envs/paddle-stable
integration-envs/paddle-stable/Scripts/python.exe -m pip install -r scripts/requirements-paddle-windows-py312.txt
integration-envs/paddle-stable/Scripts/python.exe scripts/download_paddle_models.py
```

Downloads must match the pinned archive checksums. Existing extracted model files are verified and are never silently overwritten if they have changed.

Run the isolated control:

```powershell
integration-envs/paddle-stable/Scripts/python.exe -X utf8 scripts/test_paddle_integration.py --representative --mkldnn
integration-envs/paddle-stable/Scripts/python.exe -X utf8 scripts/test_paddle_integration.py --retry-errors --mkldnn
```

The first command selects the eight supplied photographs and one page from each of the two supplied PDFs. The second processes the complete common manifest. Both use local CPU inference with at most four configured inference threads. Document orientation, unwarping and line orientation classifiers are disabled, so this measures the selected detector/recognizer without additional image correction. No language filter is requested: the explicit upstream multilingual recognizer controls its character coverage.

The original safe CPU experiment processed all ten representative cases without an inference error. This proves execution only. The optional `--mkldnn` probe failed on the first supplied image with `ConvertPirAttribute2RuntimeAttribute ... pir::DoubleAttribute` in the installed Windows runtime. Its failure is retained in `test-output/integrations/paddle-fast-probe/report.json`. The same input and model files completed successfully under PaddlePaddle 3.2.2 with MKL-DNN enabled. This workaround is also reported in the [primary upstream Paddle issue](https://github.com/PaddlePaddle/Paddle/issues/77340). The full-corpus run therefore uses the separate 3.2.2 environment with MKL-DNN enabled. The earlier 3.3.1 safe-mode partial run (23 cases, including one empty output) is preserved separately in `paddle-3.3.1-safe-partial`; the ten-case safe representative run remains in `paddle-slow-representative`. These versions are not mixed or counted as independent recognition models.

Paddle also initializes its normal local dataset cache under the user's profile during import. A restricted process may fail to create that directory; the test requires permission for this local cache. This is not cloud inference. Explicit local model directories are passed to PaddleOCR, and the test disables Hugging Face network access and Paddle's model-source availability probe. No document content is sent to an external service.

Results are checkpointed after each case in `test-output/integrations/paddle/report.json` and `report.html`. Raw recognition arrays, polygons, scores and transcriptions are saved separately; visualization font objects are represented by type rather than serialized. Cached reuse requires the same input checksum, model-file digests, package versions and execution configuration. Case times remain attached to their original attempts; the summary distinguishes reused and newly attempted cases.

There is no independently verified transcription for this corpus. The experiment therefore reports coverage, empty outputs, errors and elapsed time, **not CER/WER or recognition accuracy**. All predicted text remains unverified. It is not evidence that a modern printed-text OCR model accurately reads the historical handwriting.

The complete common manifest finished on 15 October 2026: 109 newly inferred cases (114 source aliases), 108 with some predicted text, one empty result, and zero inference failures. The pinned 3.2.2 run took 689.2 seconds including 18.9 seconds loading the models. Evidence is retained in `test-output/integrations/paddle/report.json`; this count measures successful execution, not correct transcription.

Additional books use separate manifests and report directories so their results cannot replace the common corpus. The 107-page handwritten AGAD301/332 marriage book uses `test-output/gologory-301-332/cases.json` and output `test-output/integrations/gologory-paddle`; the 123-page AGAD301/334 death book uses `test-output/gologory-301-334/cases.json` and output `test-output/integrations/gologory-deaths-paddle`. Pass these paths with `--manifest` and `--output` together with `--retry-errors --mkldnn`. These books require their own actual completed reports before any result count is stated. A missed surname in unverified OCR is never evidence that the surname is absent from a book.

AGAD301/332 subsequently completed all 107 pages with predicted text on every page, zero empty outputs and zero inference failures, in 638.9 seconds including model loading. Its transcriptions remain unverified. `scripts/run_paddle_queue.py` runs the remaining supplied Gologory manifests sequentially (334, 331, 333, 335, 336), waiting for preparation and stopping if a run is incomplete. Each book retains its own report; `gologory-queue.json` is an execution summary rather than a recognition-quality score.

AGAD301/334 completed all 123 pages with some predicted text on every page, zero empty outputs and zero inference failures, in 594.8 seconds including loading. Raw strings and polygons are retained in `test-output/integrations/gologory-deaths-paddle/raw/`; historical handwriting still requires visual checking and human transcription.

All six additional supplied books completed under the same pinned local runtime. These are execution counts, not correct-reading counts:

| AGAD unit | Pages newly inferred | Nonempty unverified outputs | Failed | Seconds including load |
| --- | ---: | ---: | ---: | ---: |
| 332 | 107 | 107 | 0 | 638.9 |
| 334 | 123 | 123 | 0 | 594.8 |
| 331 | 40 | 40 | 0 | 377.7 |
| 333 | 15 | 15 | 0 | 136.0 |
| 335 | 45 | 45 | 0 | 434.3 |
| 336 (mixed records) | 30 | 30 | 0 | 245.5 |

The six books total 360 pages, all newly inferred with zero execution failures. Together with the common 109-case corpus, the runs cover 469 inputs: 468 nonempty unverified outputs, one empty output and zero failures. Model loading is included in each run's elapsed time; total recorded runtime is 3,116.3 seconds. Source aliases and repeated sources are retained, so this is not a count of independent historical evidence.

A separate native-resolution retry of the visually reviewed death entry completed three actual inputs (full spread, left page, first-entry crop), zero empty outputs and zero failures, in 21.3 seconds. Evidence is in `test-output/integrations/gologory-native-retry/report.json`; source SHA and crop transforms remain in `test-output/gologory-surname-review/resolution-cases.json`. The output contained 65, 28 and 5 lines respectively. Cropping isolates the entry from its facing page, but the surname still was not reliably transcribed (the entry prediction split it as `Cxa` / `Tova`). This does not demonstrate improved transcription accuracy or establish absence of any surname.

Saved-output surname triage on the four smaller books parsed all 130 actual pages (28,376 raw OCR lines) and produced 13 fuzzy candidate lines: four in331, none in333, two in335 and seven in336. All candidate images passed their source checksums and every candidate retained its real line polygon and context crop. Visual triage found many formula fragments such as `qui supra`; two lines merited independent review (331 scan21 and336 scan25). These remain provisional readings, with no confirmed identity or relationship and no changes to library facts. Local evidence and review notes are in `test-output/gologory-{unit}-surname-candidates/` and `test-output/gologory-extra-surname-review.json`. A search yielding zero candidates cannot establish absence, particularly with this error-prone handwriting OCR.
