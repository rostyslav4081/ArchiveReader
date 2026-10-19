# Polish manuscript candidates — 2026-10-19

These are model scopes, not measured accuracy on the user's books. Historical Polish does not automatically mean Old Polish (normally before about 1500). Establish the book's date separately.

| Candidate | Publisher scope | Local test / availability |
| --- | --- | --- |
| [Transkribus Polish M2, ID 44976](https://www.transkribus.org/models/polish-general-model) | Polish handwriting, 17th–21st centuries | Strong scope match for later historical Polish. No downloadable offline weights confirmed. Not tested here; no private images uploaded. Publisher validation CER 4.1% is not our result. |
| [PP-OCRv6 medium](https://huggingface.co/small-models-for-glam/kraken-ppocrv6-medium) | Multilingual handwriting and print | Downloaded pinned revision 01b574f071bf21cff7d7e2a4f38966925dddc30a; SHA256 15313b51ace64cbfa81f8f6ef25ad64f04e5a6fb7f7823e67b107527bc081ac9. Tested another whole Polish manuscript photo: 48 returned boxes, 78.23 seconds. Many visible transcription errors remain. Not automatically activated. |
| [Polish metrical experimental](https://huggingface.co/meldynamics/polish-metrical-htr-experimental) | Mainly 1800–1865 Roman Catholic registers; automatic teacher labels | Installed experimental line recognizer. Different period and document genre from an undated prose manuscript; cannot treat its outputs as evidence or reference transcriptions. |
| [IHPAN LightOnOCR Polish](https://huggingface.co/IHPAN/LightOnOCR-2-1B-htr-polish-1) | Primarily first half of the 20th century | Adapter candidate; not downloaded or tested. Do not assume suitability for 17th-century material. |

Actual raw outputs, source-linked polygons and timings are under `test-output/accuracy-improvement/`. This directory contains private test material and is excluded from distribution. The original photo is unchanged. Medium and tiny were also run with identical saved ALTO baseline polygons (48 boxes each), separating recognition changes from segmentation changes.

No manually verified reference transcription exists for this test page: CER/WER and a winning model cannot honestly be claimed. No model suitable specifically for Polish before 1500 was verified in this search. Historical dictionaries support interpretation; they do not repair unreadable image evidence or establish transcription accuracy.
