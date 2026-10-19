# Optional Asian language packages

Installed without running recognition, at the user's explicit request:
- Chinese / Japanese: `PP-OCRv5_server_rec`.
- Korean: `korean_PP-OCRv5_mobile_rec`.
- Devanagari: `devanagari_PP-OCRv5_mobile_rec` for Hindi, Sanskrit, Marathi and Nepali among its documented languages.

Choose a package in **Моделі за мовою…**. Selection sets the separate `paddle` engine and its package manifest, leaving Kraken Medium available. These packages have **not** been tested on images, PDFs, or historical handwriting. No accuracy or historical-suitability claim is made. Tamil/Telugu remain unconnected candidates.

The separate existing environment is `integration-envs/paddle-stable`. The backend uses only local detector and recognition directories, disables model-source checks and Hugging Face online access, and runs the optional engine in a subprocess. User-triggered recognition follows existing correction guards and history. Cancellation from the app terminates its owned process tree. Batch model fingerprints include recognition weights, detector weights and the runtime executable in addition to the package manifest.

Downloader: `scripts/download_asian_models.py`. It obtains official `PaddlePaddle` Hugging Face repositories at pinned revisions, checks published LFS SHA256 where provided and records local file hashes in `models/paddle-asian/provenance.json`. Models and optional environments are not included in the portable ZIP.

Official scope: https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
