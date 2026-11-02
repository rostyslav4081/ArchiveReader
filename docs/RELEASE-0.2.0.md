# ArchiveReader 0.2.0

People, couples and their evidence can now be reviewed on a single zoomable canvas, with document photos, descriptions, citations and archive links together.

- Import and export GEDZIP (`.gdz`) packages containing GEDCOM 7 data and referenced photos. Plain `.ged` exports can retain adjacent media files.
- Keep relationship evidence visible in person cards and deduplicate shared document photos.
- Preserve missing-photo entries so incomplete evidence stays visible.
- Validate packaged media paths and roll back failed imports.
- Fix Windows launcher error reporting and update interface translations.

Validation: 242 automated tests passed. Windows Release build completed with warnings treated as errors. The canvas and photo-preserving exports were also checked on a local research library; personal documents are excluded from this release.

Download the Windows ZIP, extract it, and follow README.md / Install-ArchiveReader.cmd for dependencies. Model weights are optional separate downloads from [v0.1.0](https://github.com/rostyslav4081/ArchiveReader/releases/tag/v0.1.0); those existing model packs remain usable and have not changed in this release. Python/.NET and OCR dependencies are not bundled in the application ZIP. Existing research libraries are not included or overwritten by the package.
