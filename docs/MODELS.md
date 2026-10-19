# Models

The reproducible starter download uses `small-models-for-glam/kraken-ppocrv6-tiny`, a mirror of Benjamin Kiessling / ALMAnaCH's Kraken multilingual PP-OCRv6 model.

- Model card: https://huggingface.co/small-models-for-glam/kraken-ppocrv6-tiny
- Canonical record linked by the model card: https://doi.org/10.5281/zenodo.21788403
- Pinned mirror revision: `316cf2a4b4b0cab5f3f8c4f28f3310ca3e03c726`
- File: `tiny.safetensors`, 2,837,508 bytes
- SHA-256: `972700b1c72de14bdde028f9b06d77f13c88ec60da5e942bb9e57aca421fa361`
- Model card license: Apache-2.0

`scripts/download_model.py` checks this digest before replacing the local model file. Weights are excluded from Git. The mirror was used because the Zenodo API returned HTTP 504 during setup.

Language coverage is not proof of accuracy on a specific historical spelling or handwriting. The model card describes mixed transcription conventions. ArchiveReader never silently modernizes names or treats model confidence as a guarantee.

Choose specialized local weights in the UI when available. Kraken's CLI documentation is the source for the inference and fine-tuning adapters:

- https://kraken.re/7.1/user_guide/inference.html
- https://kraken.re/7.1/user_guide/training_recognition.html
- https://kraken.re/7.1/user_guide/models.html

## Additional local handwriting candidates

These optional weights are separate downloads, excluded from the application ZIP and Git. The listed licenses come from the saved upstream records; this table is attribution, not a decision to redistribute their weights.

| Local candidate | Upstream record | Pinned identity | Recorded license |
| --- | --- | --- | --- |
| German handwriting / Mannheim, Kraken | [Zenodo 7933463](https://zenodo.org/records/7933463) | `german_handwriting.mlmodel`, SHA-256 `b81a07b9dce15569258750d1c9e9cf48478e37c167d2330c1626afc80f22cb90` | CC BY-SA 4.0 |
| Bohemica, Kraken | [Zenodo 11673242](https://zenodo.org/records/11673242) | `rec_bohemica.mlmodel`, SHA-256 `c16da6b363e9046c7eb6da957bb7a7c9a295c74bf5e9defa8893ef7eb638a8a6` | CC BY 4.0 |
| Experimental Polish metrical TrOCR | [Model repository](https://huggingface.co/meldynamics/polish-metrical-htr-experimental) | revision `9c471a913ffb3694c22b6ad6d4469e9a5f68a91e`; weights SHA-256 `34b651452fc0f015b6b03a2faee50fb1b6d2c6595e5c542066fc3c7d6dd8ac01` | Consult the pinned repository LICENSE before redistribution |

The experimental Polish model uses pseudo-label training. Its output must be checked against human transcription, and agreement with another model is not independent proof. Small development diagnostics are not held-out validation or evidence that one model is best for all books.

The recognition assistants retain each model's raw reading and errors. A failed model cannot create consensus. Human-confirmed tutor examples can train a separate Kraken candidate; its training/validation books must be independent of the frozen test books. Candidate checks compare both models on the same successful test rows and report failures separately. Strictly lower CER with no additional failures is only a provisional improvement; the active model is never replaced automatically.
