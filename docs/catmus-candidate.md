# CATMuS Medieval candidate

User-selected record: https://zenodo.org/records/21488839 (record version 1.6.2). The actual released weight filename remains `catmus-medieval-1.6.0.mlmodel`. Published MD5: `326a6ea675661ec9ce0bb6b1958de495`; downloader verifies it and records local SHA256 and original metadata.

Install with `scripts/download_historical_models.py catmus-medieval`, then choose `models/catmus-medieval/model.mlmodel` in the existing Kraken model chooser. No separate engine is needed. Its stated languages are Old/Middle French, Latin, Spanish and Italian; Polish is not a stated training language. Graphematic transcription preserves abbreviations rather than automatically expanding them.

Real tests use three Latin manuscript line crops and the entire original archive scan `PL_1_301_334_0003.jpg`, corresponding to AGAD 301/334 PDF frame 5. Machine outputs are not reference transcriptions. This later metrical source is outside the typical medieval training domain. No CER/WER or winning model is claimed.

IHPAN LightOnOCR engine, downloaded base/adapter and separate environment were removed at the user's request. Previous diagnostic reports are retained as test history, not active models.
