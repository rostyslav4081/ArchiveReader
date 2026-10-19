# Implementation status

This is a working early desktop release, not completion of every research feature in the original product vision.

## Implemented and exercised

Import and preserved originals; lazy PDF/image rendering; multipage TIFF; SQLite persistence and history; cancellable isolated workers; restart recovery; Kraken inference with ALTO line geometry; Tesseract CLI adapter; selectable OCR regions; four interface languages; manual multiline and structured records; XLSX/JSON/CSV/TXT export; verified-line dataset export; CER/WER calculations.

The document workbench now includes editable line/entry/column regions and record evidence links, damage/missing-region notes, local paired Kraken/TrOCR line comparison with highlighted differences, book profiles, similar-name suggestions with source navigation, and explicit book-level train/validation/test roles. Photo tools create previewable derivatives for rotation, split spreads, four-corner perspective correction and manually guided page dewarping. JSON exports retain region metadata and book profiles.

Library review now provides a context-image queue for model disagreements/errors and marked damage, incremental full-text search across OCR/corrections/records/regions, reversible revision browsing, same-book column templates and frozen evaluation sets. Search reports unrecognized/error pages; dominant raster PDF pages bypass partial text layers. Three newly downloaded Czech/Polish/Hungarian archive samples completed import/render/recognition checks; see ARCHIVE_TESTS.uk.md for the exact scope and provenance.

Structure tools propose reviewable line/entry/column geometry and reading order from OCR boxes or fresh Kraken segmentation, with manual columns as anchors and optional table-rule detection. Order is editable and usable for assembling saved line text. Isolated OCR of saved entries/columns maps result boxes back to the original and preserves page OCR/manual corrections. These geometric heuristics remain unvalidated for reliable automatic register segmentation.

One native Windows fine-tuning run completed on synthetic verified lines, producing a separate checkpoint while preserving the base model. This verifies the training path, not historical recognition improvement. Held-out comparison rejects known training/validation overlap for models trained in this library; external model training overlap remains unknown.

Synthetic tests cover a 2500-page PDF import and last-page text extraction, duplicate protection, original-byte preservation, crop/history integrity, mixed narrative retention, export limits and formulas, failed workers, persisted corrections, training-data export and localization coverage. This is **not** a 2500-page neural OCR throughput test.

Real local corpus runs are kept in ignored `test-output/` directories. Their documents/transcriptions are not part of the repository. No real-document CER/WER is claimed without checked reference text. Initial base-model handwriting results contain recognition and reading-order errors.

Archival source cards distinguish shared book metadata from per-page folios and scan URLs. Citations, derivative source inheritance and JSON/CSV/XLSX/TXT source exports are implemented. Archive references are entered by the researcher; no metadata discovery or universal citation-style compliance is claimed.

Person identity links are explicitly reviewed between record/field mentions. Candidates retain both records, roles, citations and evidence; shared/conflicting place and house values are hints, not identity probabilities. Confirm/reject/withdraw decisions preserve snapshots and an audit trail, reject stale writes and flag changed records. JSON export retains decisions. No automatic record merge, transitive identity inference, date interpretation or splitting of multi-person fields is implemented.

Automatic core-library backups use SQLite's online backup API and checksum-verified imported originals in a shared vault. Seven consistent database snapshots are retained; shared objects are not automatically pruned. Restore verifies integrity and writes a new library with rebased original paths, even if the working database is corrupt. Models, training files and separate OCR/HTR reports are excluded. Main-window shortcuts save unverified edits, advance through unverified OCR lines, explicitly verify-and-advance and center zoom on evidence; the library review queue is not keyboard-integrated yet.

Person cards now explicitly collect record/field mentions with unique membership, reasons, source snapshots, variants, coarse original-year ordering and visible value variations. Parent/spouse links use separately confirmed records, prevent ancestor cycles and render a navigable family tree; stale evidence remains visible and decisions can be withdrawn. Genealogy JSON is separate from record export. These are researcher-defined identities/relationships, not automatic reconstruction.

Explicit-label/date field proposals retain text spans and citations, require selection, block stale input and require permission to replace populated fields. They are narrow heuristics, not general multilingual named-entity extraction. JSON records retain selected field evidence.

Persistent sequential multi-book queues resume after interruption, retain per-page failures and protect corrected line geometry. Coverage and local runtime/model diagnostics are available. A Windows ZIP with per-user install/update scripts excludes private data and model weights. The package requires Python and the .NET Desktop Runtime; dependency download and setup on a clean computer remain unvalidated. Four supplied documents were prepared in a private evaluation library with eight preview pages and zero invented verified references.

Fact-specific source bounds and record-region fallback now display scan evidence beside mentions. Card merge/split operations retain snapshots, reject self/cyclic/duplicate relationships and rejected identities, and provide conflict-checked undo. Chronology hints require explicit Gregorian profiles/date prefixes, use conservative ranges, exclude stale evidence and never convert unsupported calendars.

UTF-8 GEDCOM subset import has preview, unresolved/unmapped reports, duplicate protection and raw-byte preservation. Imported facts/relationships remain unverified; media are not fetched. GEDCOM 7 export emits a warning report, uses partial families for pairwise parent links and preserves unsupported dates as notes. This is not universal GEDCOM/application compatibility.

Incremental perceptual scan candidates compare full and sampled crop hashes. Explicit full-page decisions can skip queued target recognition only after a source page is done; fragment matches cannot. This heuristic is not validated for all rotations/perspective or same-template registers. Per-book researcher-verified dictionaries provide fuzzy manual hints, including F2 access, without modifying predictions.

## Implemented but not fully validated

- `ketos` fine-tuning launcher: requires a sufficiently large, verified historical corpus and independent before/after evaluation.
- Tesseract adapter: parser/failed-process tests exist; a Tesseract executable is not bundled.
- Adaptive concurrency: conservative CPU/RAM sizing exists. Comprehensive CPU/GPU/VRAM/disk benchmarking and dynamic model selection do not.
- Disk cache: cleanup targets old entries; active/recent processing can temporarily exceed the nominal budget.

## Remaining research and engineering

- Robust reading order for multi-column registers and reliable table-cell/entry segmentation.
- Validated extraction of people, relationships, dates and places, with reviewable evidence links.
- Model catalog by language, century, script and handwriting, with a representative evaluation corpus.
- Paleographic dictionaries, ligature assistance and handwriting clustering.
- OpenTK/tiled GPU viewer, automatic geometric correction and validated damage detection/restoration. Current geometry and damage annotation tools are manual.
- PaddleOCR/PyLaia adapters and representative model comparisons. Offline TrOCR supports selected regions and whole-page recognition after Kraken line segmentation. Model and script suitability still require validation.
- Full GEDCOM compatibility, richer relationship types and a complete training-history UI.
- DOCX and structured XML export beyond Kraken's raw ALTO files; richer PDF reading-order and archival PDF/A validation.
- Signed installer, broader Windows compatibility testing and distribution licensing decision.

Scanner integration remains explicitly deferred by product scope.

## Photo books (2026-10-15)

Ordered photo-folder and selected-page collections retain original frame IDs, annotations and records. Missing folios are explicit placeholders. Shared profile/source/dictionary scope, semantic column templates with page exceptions, record field conjunctions, book-scoped full-text search and fragment-linked research tasks are implemented. Recognition can resume unfinished pages; scanned/handwritten PDFs use the selected model rather than relying on the PDF extension. PDF export preserves page images and emits a Unicode line-positioned text layer plus a coverage/verification report. It is not archival PDF/A or a promise of correct historical transcription. Per-book model reports use common-success denominators alongside failed attempts and loading-inclusive time.

## Recognition, teaching and board evidence (2026-10-15)

- Separate Kraken/TrOCR adapters preserve individual readings and failures. Consensus remains unverified; disagreements and failed attempts require review. Model metadata includes identity hashes and missing codec characters.
- Human teaching saves source-bound corrections, uncertainty, revision history and book roles. Controlled Kraken candidate training freezes separate training/validation/test source families, compares base/candidate on identical held-out lines and never automatically activates a candidate. No real new candidate training or body-text accuracy gain is claimed in this release.
- Recognition jobs coordinate layout, recognizers, comparison and human review. Model feedback alone is not trusted ground truth.
- FigJam import preserves original nodes, images, Czech notes and connectors in isolated test libraries. Red means incorrect, yellow unresolved, grey logically consistent according to the author; these labels do not manufacture archival proof.
- Real integration exercised all 10 supplied files: 85/85 pages imported/rendered, and 20 recognition results from two models on 10 selected crops without runtime failure. This is not full-book transcription or an accuracy benchmark. Six readable heading development diagnostics are insufficient to establish general handwriting quality.
- Additional local models: Mannheim German handwriting, Bohemica registers, and experimental Polish metrical TrOCR. Downloaded weights and private test material stay outside the distribution and Git.

## Whole-entry review and evidence navigation (2026-10-15)

Whole-entry reference drafts, human review, revision history, immutable frozen entry datasets and paired end-to-end CER/WER evaluation are implemented. Shared line extraction is performed once per entry; complex tables require manually ordered child lines. The private real-data lab contains four unconfirmed drafts, not new human ground truth; no new historical full-entry accuracy claim is made.

Individual fact assessments are separate from original records and person links. Statuses distinguish document observations, transcriptions, hypotheses and corroborated claims; independent sources, explicit review, revision checks and evidence snapshots guard corroboration. Neighboring-page candidates expose signals and differences without automatic linkage. Board zoom, search and evidence navigation distinguish personal context from live relationship proof. Source locators preserve original page, archival scan index, image label and entry number separately from folio and local file page.

## Performance infrastructure (2026-10-15)

Added six hot-lookup indexes, streamed content validation of recognition folders/files and segmentation models in queues, bounded client latency logging, and a recyclable persistent inference worker. Native CPU Kraken, TrOCR, line comparisons and shared segmentation reuse process-local models; CLI compatibility routes remain. Synthetic SQL/IPC benchmarks verify identical outputs rather than asserting full-book OCR speedups. Dynamic RAM/VRAM scheduling and full scale library pagination remain future work.


## 2026-10-15 library and research workspace

- Main page browser loads at most 200 metadata rows per window, with previous/next, whole-library filtering and locating a selected evidence page. Full-book recognition obtains the complete ordered IDs separately; the visible window never limits recognition scope.
- Person evidence/card operations fetch only the required record IDs. General candidate discovery remains broader by design.
- Desktop full-text search reads the current index immediately. A background worker drains changed pages in bounded transactions (25 pages / soft 150 ms budget). Dirty pages are excluded from stale results; search reports remaining indexing work. A single very large page can exceed the soft budget. FTS row IDs have a normal page index, avoiding a full virtual-table scan per replaced page.
- **Переносний пакет дослідження** snapshots the SQLite database, hash-verified originals, reports and training/evaluation artifacts. Model identities/configuration are retained; large weight files are optional. Inspect checksums before restoring into a new directory. The normal automatic backups remain smaller recovery snapshots, not substitutes for this full research package.
- **Помічник дослідника** compares original/processed previews, reviews book-scoped disagreements with explicit field labels, searches family evidence by combined fields, reuses book/column profiles and reports explicit gaps, duplicate candidates and unfinished work. It does not infer missing pages from arbitrary archive numbering or confirm people automatically.
- **Обмін PAGE / ALTO** previews one-page text regions, real baselines and supported reading order before adding new unverified annotations. Existing records and verified text remain unchanged. Original XML and provenance are retained. Export includes the exact raster and a provenance manifest. This is a supported interchange subset, not a lossless conversion of every layout hierarchy or a training reference.

Optional PERO/PaddleOCR/Docling experiments use separate environments and private reports. They are not bundled runtime engines, and successful execution does not establish historical handwriting accuracy. See [external integration trials](EXTERNAL_INTEGRATIONS.md).


### Remaining historical-reading work

The current external tests do not implement the user's full visual→letter alternatives→word→sentence→page reasoning concept. The review layer below now supplies manual writer-specific exemplars and reviewable structure roles. Remaining automatic capabilities include learned handwriting matching, historical morphology, inferred span-level mixed-language hypotheses and bounded context-assisted re-recognition. Preserve the original spelling and uncertain/missing spans; no modern spellchecker or model consensus may silently rewrite them. See the explicit target design in ARCHITECTURE.md.

## Historical reading review layer (2026-10-15)
Book origin/period/hand profiles, literal lexicon forms and explicit multilingual concepts, source-bound comparison evidence, separate audited uncertain readings, manual layout roles, conservative grid proposals and checked pixel letter exemplars are implemented. Same-hand examples are advisory; no automatic writer identification, grammar reasoning, weight training or accuracy claim.

## Cited historical hints and structured references
Historical hints now retain checked title/URL/locator and independent work, manuscript-witness and edition periods, scope and authenticity notes. Exact-form orthography/grammar/paleography hints do not execute corrections. The optional source picker lists67 references (62 user-supplied catalogue links plus5 official paleography resources); selecting one fills an unchecked draft only. Persistent reading requirements are in READING_REQUIREMENTS.uk.md. Full source ingestion and automatic historical grammar remain unimplemented.

## Global discovery layer
Source catalogue expanded to 79 entries, retaining previous references and adding global bibliographies, dictionary collections and corpora. A separate offline pinned Glottolog registry provides 27,177 family/language/dialect rows (8,618 language rows), bounded search and publisher source URLs. This is discovery metadata, not all-language OCR/HTR, a complete historical-variant inventory, full-book ingestion or demonstrated accuracy improvement.


2026-10-19: Added explicit book knowledge packages, source-bound doubtful-word inspection, selected-region recognition reuse with immutable input fingerprints and conflict-preserving application, confirmed corpus fields and frozen-set field scoring, and content-addressed structure-proposal caching. Single saved lines bypass Kraken segmentation; segmentation model uses Kraken 7.1 `-i`, recognition model uses `-m`. No automatic historical truth labels or language normalization.


## Розпізнавання й порівняння (2026-10-19)
Розпізнавання вибраного рядка, запису або колонки у стандартному постійному процесі повторно використовує моделі Kraken. Для окремого рядка застосовується RecognitionTaskModel Kraken 7.1 з тією самою підготовкою, що й CLI; допоміжні процеси вирізання рядків вимкнено. Інший явно вибраний виконуваний файл залишається окремим CLI-запуском. Кеш результатів розрізняє ці шляхи та версію адаптера. Кнопка зупинки завершує власний процес; наступний запуск завантажує модель знову.

Перевірка сумнівного слова показує кандидат текстового зіставлення в квадратних дужках поруч із повним незалежним прочитанням. Вставка, пропуск або зміна поділу може дати кілька слів. Це не встановлює меж слова на фотографії, не виправляє оригінал і не підтверджує прочитання. Межі на скані можна задати вручну.

Після порівняння повних записів показується придатність моделей окремо для кожної книги замороженого набору. Нижчий спостережений CER обирається тільки за спільними успішними записами; нічия, відсутність порівнюваних записів або збої найкращої моделі не визначають переможця. Менше 20 спільних записів позначається як мала вибірка (це попередження, а не статистичний доказ достатності 20). Модель не активується автоматично. Звірені еталони створюються лише після перевірки людиною.


## Ручні рядки й контроль поділу (2026-10-19)
У майстерні → «Структура» ввімкнено читання запису за збереженими дочірніми ручними рядками. Потрібно призначити батьківський запис і порядок. Непідтверджені автоматичні пропозиції рядків не використовуються як ручні. Кожен рядок читається окремо без сегментації; порядок зберігається. Зміна дочірніх рядків скасовує придатність старого результату. Застосування показує конфлікти й не перезаписує наявний текст.

«Перевірка меж і стан книги» підсвічує малі ділянки, значні перекриття рядків одного батька й можливі проміжки. Це геометричні підказки, не доказ пропущеного тексту. Перевірка перекриттів обмежена 500 рядками, звіт — 1000 попередженнями. Для об’єднання виберіть кілька неперевірених рядків одного батька через Ctrl. Поділ одного рядка відбувається посередині висоти; нові межі можна далі виправити мишкою. Текст поділеного рядка лишається в історії та примітках, нові тексти порожні. Перевірені рядки, рядки з пов’язаними записами та рядки з дочірніми ділянками захищені від цих операцій. Операція атомарна, застарілий стан відхиляється.

Карта стану завантажує до 200 сторінок за раз. Для фотокниг зберігається порядок і явні пропущені аркуші. «Збережені рядки перевірено» не означає повноту сторінки.

«Порівняння поділу та зображень» дозволяє вибрати дві моделі сегментації й перемикати їхні пропозиції поверх одного скану. Пропозиції не застосовуються автоматично. Потрібна друга локальна придатна модель сегментації; модель читання не є її заміною. Джерело, стан розмітки та фрагмент перевіряються перед застосуванням.

Три варіанти читання — оригінал, збільшення ×2 (Lanczos) та autocontrast з cutoff=1. Похідні файли і результати окремі, пікселі оригіналу не змінюються. Обробка не відновлює втрачені штрихи й може погіршити результат; автоматичного вибору або підтвердження немає. Для збільшення діє межа 20 млн вхідних пікселів. Еталони повних записів надалі потребують ручного звірення; ці експерименти не створюють ground truth.


## Повна сторінка та продовження обробки (2026-10-19)
Майстерня → «Структура» → «Повна сторінка: обробка й перевірка». Виберіть порядок читання: колонки, табличні рядки або суцільний текст; модель A задається на вкладці HTR. Створення плану без прапорців охоплює всю сторінку. Прапорець розвороту явно ділить її на ліву та праву половини (50/50): перевірте, чи ця межа правильна. За наявності розмітки можна вибрати збережені записи/колонки й їхній порядок. Верхні ділянки плану включають свої дочірні рядки; вони не дублюються як окремі завдання.

«Продовжити» обробляє незавершені ділянки по одній, зберігаючи кожну завершену. «Зупинити» завершує власний робочий процес; після повторного відкриття завантажте останнє завдання й продовжте. Перерваний процес відновлюється лише якщо його власник більше не працює. Паралельне захоплення однієї ділянки блокується. «Повторити лише помилки» залишає завершені результати й повторює тільки невдалі. Порожня відповідь має окремий статус, а не вважається успішним прочитанням. Зміни джерела, розмітки, ваг моделей або версії обробки вимагають нового плану.

Межі вводу відокремлені від меж повернутих рядків. Зелений контур означає наявність модельного тексту, не правильність прочитання. Сірий фон поза повернутими межами — неоцінена частина зображення, а не доказ відсутності письма. Навіть ввід на всю сторінку не підтверджує повного текстового охоплення. Звіт показує цілу сторінку поруч з усіма прочитаннями, порожніми відповідями й помилками. Результати окремі від ручних записів; автоматичного перезапису немає.

Кнопка звірення записів відкриває наявний корпус для незалежного порівняння моделей, імен, дат і будинків. Без звірених людиною еталонів цей процес не дає достовірного рейтингу якості; результати нових тестів не стають еталонами.

Реальна перевірка повних сторінок завершена на 4 входах (5 ділянок, бо розворот розділено): всі повернули неперевірений текст. Відновлення після справжнього переривання зберегло першу половину й повторило лише другу. Це не доказ точності; незалежних звірених еталонів для цих сторінок досі немає.
