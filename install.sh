#!/usr/bin/env bash
# Install Feder for the current user (no root, no AUR, nothing system-wide)
# Feder für den aktuellen Benutzer installieren (ohne root, ohne AUR)
#   ./install.sh              install or update / installieren oder aktualisieren
#   ./install.sh --uninstall  remove / entfernen
set -euo pipefail

APP_ID="io.github.netlusche.Feder"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"
TARGET="$DATA/feder"
DESKTOP="$DATA/applications/$APP_ID.desktop"
ICON="$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"

# ---------------------------------------------------------------- language / Sprache
UI_LANG=en
for var in "${LANGUAGE:-}" "${LC_ALL:-}" "${LC_MESSAGES:-}" "${LANG:-}"; do
    if [[ -n "$var" && "$var" != "C" && "$var" != "POSIX" ]]; then
        [[ "${var,,}" == de* ]] && UI_LANG=de
        break
    fi
done
msg() { if [[ "$UI_LANG" == de ]]; then echo -e "$1"; else echo -e "$2"; fi; }

# ---------------------------------------------------------------- distribution
DISTRO=unknown
if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    IDS="$(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}" | tr '[:upper:]' '[:lower:]')"
    case " $IDS " in
        *" arch "*|*" manjaro "*|*" endeavouros "*) DISTRO=arch ;;
        *" debian "*|*" ubuntu "*|*" linuxmint "*|*" pop "*) DISTRO=debian ;;
        *" fedora "*|*" rhel "*|*" centos "*) DISTRO=fedora ;;
    esac
fi

deps_command() {
    case "$DISTRO" in
        arch)   echo "sudo pacman -S --needed python-gobject gtk4 libadwaita gtksourceview5 webkitgtk-6.0 pandoc-cli" ;;
        debian) echo "sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gtksource-5 gir1.2-webkit-6.0 pandoc" ;;
        fedora) echo "sudo dnf install python3-gobject gtk4 libadwaita gtksourceview5 webkitgtk6.0 pandoc" ;;
        *)      echo "python3-gobject, gtk4, libadwaita (>= 1.4), gtksourceview5, webkitgtk-6.0, pandoc" ;;
    esac
}
pandoc_command() {
    case "$DISTRO" in
        arch) echo "sudo pacman -S --needed pandoc-cli" ;;
        debian) echo "sudo apt install pandoc" ;;
        fedora) echo "sudo dnf install pandoc" ;;
        *) echo "pandoc" ;;
    esac
}

refresh_caches() {
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t "$DATA/icons/hicolor" 2>/dev/null || true
    command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -rf "$TARGET" "$BIN/feder" "$DESKTOP" "$ICON"
    refresh_caches
    msg "Feder wurde entfernt. Einstellungen liegen noch in ~/.config/feder (darfst du löschen)." \
        "Feder has been removed. Your settings are still in ~/.config/feder (feel free to delete them)."
    exit 0
fi

msg "→ Prüfe Abhängigkeiten …" "→ Checking dependencies …"
set +e
python3 - <<'PY' 2>/dev/null
import sys
try:
    import gi
    gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
    gi.require_version("GtkSource", "5"); gi.require_version("WebKit", "6.0")
    from gi.repository import Gtk, Adw, GtkSource, WebKit  # noqa: F401
except (ImportError, ValueError):
    sys.exit(1)
sys.exit(0 if (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 4) else 2)
PY
CHECK=$?
set -e
if [[ $CHECK -eq 2 ]]; then
    msg "\nDeine libadwaita ist zu alt, Feder braucht Version 1.4 oder neuer.\nDas haben z. B. Ubuntu 24.04, Linux Mint 22, Debian 13, Fedora 40 und aktuelles Arch/Manjaro." \
        "\nYour libadwaita is too old, Feder needs version 1.4 or newer.\nFor example Ubuntu 24.04, Linux Mint 22, Debian 13, Fedora 40 and current Arch/Manjaro have it."
    exit 1
elif [[ $CHECK -ne 0 ]]; then
    msg "\nEs fehlen Pakete (alle aus den offiziellen Repos). Bitte einmal ausführen:\n" \
        "\nSome packages are missing (all from the official repositories). Please run:\n"
    echo "    $(deps_command)"
    msg "\nund danach ./install.sh erneut starten." "\nand then run ./install.sh again."
    exit 1
fi
if ! command -v pandoc >/dev/null; then
    msg "  Hinweis: pandoc fehlt, Word/ODT-Export ist dann aus. Nachrüsten: $(pandoc_command)" \
        "  Note: pandoc is missing, so Word/ODT export is disabled. To add it: $(pandoc_command)"
fi

msg "→ Kopiere Programmdateien nach $TARGET" "→ Copying program files to $TARGET"
mkdir -p "$TARGET" "$BIN" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
install -m755 "$SRC/feder.py" "$TARGET/feder.py"
for dir in icons data locale; do
    rm -rf "${TARGET:?}/$dir"
    cp -r "$SRC/$dir" "$TARGET/$dir"
done
install -m644 "$SRC/$APP_ID.svg" "$ICON"
ln -sf "$TARGET/feder.py" "$BIN/feder"

msg "→ Lege Starter im App-Menü an" "→ Adding launcher to the app menu"
cat > "$DESKTOP" <<DESK
[Desktop Entry]
Type=Application
Name=Feder
GenericName=Markdown Editor
GenericName[de]=Markdown-Editor
Comment=Write Markdown with preview, focus and Hemingway mode, export to Word, ODT, PDF and HTML
Comment[de]=Markdown schreiben mit Vorschau, Fokus- und Hemingway-Modus, Export nach Word, ODT, PDF und HTML
Exec=$TARGET/feder.py %F
Icon=$APP_ID
Terminal=false
Categories=Office;TextEditor;GTK;
MimeType=text/markdown;text/x-markdown;
Keywords=Markdown;Editor;Writing;Text;Writer;Hemingway;Focus;
Keywords[de]=Markdown;Editor;Schreiben;Text;Writer;Hemingway;Fokus;
StartupNotify=true
StartupWMClass=$APP_ID
DESK

refresh_caches

echo
msg "✓ Fertig. Starte Feder über das App-Menü (Super-Taste, »Feder« tippen),\n  per Rechtsklick auf eine .md-Datei → »Öffnen mit« → Feder,\n  oder im Terminal mit: $TARGET/feder.py [DATEI.md]" \
    "✓ Done. Start Feder from the app menu (press Super, type “Feder”),\n  via right-click on a .md file → “Open With” → Feder,\n  or in a terminal: $TARGET/feder.py [FILE.md]"
