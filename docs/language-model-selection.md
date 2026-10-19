# Language and script model selection

The main window now has **Моделі за мовою…**. Selecting a language filters curated model choices; it does not constrain decoding, translate text or certify historical suitability. Installed candidates can be selected; unavailable or unconnected candidates cannot be activated. Selection saves OCR preferences and does not change existing page transcriptions or annotations.

PP-OCRv6 Medium remains the broad multilingual candidate. The catalogue includes European languages, Arabic, Persian, Ottoman Turkish, Hebrew, Yiddish, Syriac, Armenian, Georgian, Greek and other declared categories. Publisher language support is separate from measured accuracy. Classical Armenian and Geʽez are synthetic-only in the publisher's training description. Right-to-left reading order still needs document-specific verification.

Specialist choices: Mannheim German handwriting; Mannheim German/Latin print; CATMuS Medieval; Bohemica with its narrow German/Czech register scope. The newly downloaded German-print model was tested on two real typewritten German line crops and performed poorly; it is not selected automatically.

Chinese/Japanese, Korean and Devanagari (including Sanskrit) PaddleOCR packages were subsequently installed and connected without recognition tests, at the user’s request. Tamil/Telugu remain **not connected** candidates. Historical handwriting and historical language varieties are unverified. A catalogue of thousands of languages/dialects does not mean thousands of functioning recognizers.

Actual local diagnostic: `test-output/multilingual-candidates/report.html`, two lines each of Czech, Hungarian, Slovak and German, from public EHRI source images. EHRI overlaps PP-OCRv6 training, so this is not an independent accuracy evaluation. No private-book CER/WER or coverage guarantee is claimed.

Sources:
- https://huggingface.co/small-models-for-glam/kraken-ppocrv6-medium
- https://zenodo.org/records/7933463
- https://zenodo.org/records/10519596
- https://zenodo.org/records/21488839
- https://zenodo.org/records/11673242
- https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
