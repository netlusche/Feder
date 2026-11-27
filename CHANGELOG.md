# Changelog

All notable changes to Feder are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [1.1.0] – 2026-11-28

### Added
- **English user interface.** Feder now speaks English and German and follows the system language (German for German systems, English otherwise).
- **Language menu** in the main menu (System Default, Deutsch, English), takes effect after a restart.
- **Save button** at the top left, next to Open and New.
- Introduction text in English (`data/welcome.en.md`), German text unchanged (`data/welcome.de.md`).
- **Support for common distributions:** the installer detects Arch/Manjaro, Debian/Ubuntu/Linux Mint and Fedora and prints the matching package command if dependencies are missing. It also checks for libadwaita 1.4 or newer.
- Installer messages in English and German, app menu entry with German name and description.
- Translation workflow with gettext (`po/`, `locale/`, `tools/update-translations.sh`).
- English README (`README.md`) and German README (`README.de.md`) with screenshots in both languages.

### Changed
- Numbers, shortcut names (Ctrl/Strg, Shift/Umschalt) and placeholder texts follow the interface language.
- The “pandoc is missing” hint shows the install command for the detected distribution.
- Exported HTML files carry the interface language in their `lang` attribute.
- Preview style moved to `data/preview.css`, introduction texts to `data/`.

### Fixed
- Word count now uses the singular for one word (“1 word” / „1 Wort“).

## [1.0.0] – 2026-11-27

### Added
- First release: Markdown editor with syntax highlighting, live preview (editor, split, preview), focus mode, Hemingway mode, formatting bar, search, statistics, full screen, light and dark mode.
- Export to Markdown, HTML, Word (DOCX) and LibreOffice (ODT) via pandoc and to PDF via WebKit, without LaTeX.
- German user interface, installer for `~/.local`.

[1.1.0]: https://github.com/netlusche/Feder/releases/tag/v1.1.0
[1.0.0]: https://github.com/netlusche/Feder/releases/tag/v1.0.0
