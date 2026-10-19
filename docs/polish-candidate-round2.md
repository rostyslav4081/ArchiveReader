# User-supplied Polish candidates — 2026-10-19

| Candidate | Verified availability and scope | Test status |
| --- | --- | --- |
| Polski Wieszcz, model 464825 | Official Transkribus description: Polish handwriting, 17th–19th centuries, metrical/notarial/correspondence material. Downloadable offline weights not confirmed. | Not run. Trial upload accepts service terms; user confirmation of that acceptance is still pending. |
| Polish M2, model 44976 | Public Transkribus historical/modern Polish model. Offline weights not confirmed. | Not run for the same reason. |
| PP-OCRv6 Tiny, Zenodo 21788403 | Published MD5 `1835fe215247475370503b0b325b100c` exactly matches the already installed `tiny.safetensors`. | Already tested on a whole Polish manuscript page with identical saved baseline geometry; raw output is `test-output/accuracy-improvement/polish-same-layout-tiny.json`. No independent human-reference accuracy claim. |
| PET3R12/trocr-base-polish-handwriting | Public safetensors checkpoint with MIT metadata. Word-level project; historical manuscript training not documented in the minimal model card. | Tested three real word crops against Tiny and Medium in 28.45 seconds total, including loading all three models. Outputs: `Obrzy`, `mój`, `Obym`; errors remain. No automatic full-page activation. |
| The Polish Schwabacher | Official Transkribus model for printed Polish Schwabacher, based on a 1616 edition. Not a handwriting model. | Not run. Requires an appropriate printed sample and Transkribus access/terms. |

Sources:
- https://www.transkribus.org/models/polski-wieszcz
- https://www.transkribus.org/models/polish-general-model
- https://zenodo.org/records/21788403
- https://huggingface.co/PET3R12/trocr-base-polish-handwriting
- https://github.com/PET3R12/pl-handwriting-ocr
- https://www.transkribus.org/models/the-polish-schwabacher

Publisher validation scores are not measurements on our private books. Test reports preserve uncorrected machine outputs; they are not training references or genealogical facts.
