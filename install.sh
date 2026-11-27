#!/usr/bin/env bash
# Feder installieren (nur für deinen Benutzer, ohne root, ohne AUR)
#   ./install.sh              installieren oder aktualisieren
#   ./install.sh --uninstall  wieder entfernen
set -euo pipefail

APP_ID="io.github.netlusche.Feder"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="$HOME/.local/bin"
TARGET="$DATA/feder"
DESKTOP="$DATA/applications/$APP_ID.desktop"
ICON="$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"

refresh_caches() {
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -f -t "$DATA/icons/hicolor" 2>/dev/null || true
    command -v update-desktop-database >/dev/null && update-desktop-database -q "$DATA/applications" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -rf "$TARGET" "$BIN/feder" "$DESKTOP" "$ICON"
    refresh_caches
    echo "Feder wurde entfernt. Einstellungen liegen noch in ~/.config/feder (darfst du löschen)."
    exit 0
fi

echo "→ Prüfe Abhängigkeiten …"
if ! python3 - <<'PY' 2>/dev/null
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5"); gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, Adw, GtkSource, WebKit
assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 4)
PY
then
    echo
    echo "Es fehlen Pakete (alle aus den offiziellen Repos). Bitte einmal ausführen:"
    echo
    echo "    sudo pacman -S --needed python-gobject gtk4 libadwaita gtksourceview5 webkitgtk-6.0 pandoc-cli"
    echo
    echo "und danach ./install.sh erneut starten."
    exit 1
fi
command -v pandoc >/dev/null || echo "  Hinweis: pandoc fehlt, Word/ODT-Export ist dann aus. Nachrüsten: sudo pacman -S pandoc-cli"

echo "→ Kopiere Programmdateien nach $TARGET"
mkdir -p "$TARGET" "$BIN" "$(dirname "$DESKTOP")" "$(dirname "$ICON")"
install -m755 "$SRC/feder.py" "$TARGET/feder.py"
rm -rf "$TARGET/icons"
cp -r "$SRC/icons" "$TARGET/icons"
install -m644 "$SRC/$APP_ID.svg" "$ICON"
ln -sf "$TARGET/feder.py" "$BIN/feder"

echo "→ Lege Starter im App-Menü an"
cat > "$DESKTOP" <<DESK
[Desktop Entry]
Type=Application
Name=Feder
GenericName=Markdown-Editor
Comment=Markdown schreiben mit Vorschau, Fokus- und Hemingway-Modus, Export nach Word, ODT, PDF und HTML
Exec=$TARGET/feder.py %F
Icon=$APP_ID
Terminal=false
Categories=Office;TextEditor;GTK;
MimeType=text/markdown;text/x-markdown;
Keywords=Markdown;Editor;Schreiben;Text;Writer;Hemingway;Fokus;
StartupNotify=true
StartupWMClass=$APP_ID
DESK

refresh_caches

echo
echo "✓ Fertig. Starte Feder über das App-Menü (Super-Taste, »Feder« tippen),"
echo "  per Rechtsklick auf eine .md-Datei → »Öffnen mit« → Feder,"
echo "  oder im Terminal mit: $TARGET/feder.py [DATEI.md]"
