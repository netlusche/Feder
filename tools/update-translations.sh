#!/usr/bin/env bash
# Developer tool: refresh po/feder.pot, merge into po/*.po and compile locale/*/LC_MESSAGES/feder.mo
# Needs the gettext tools (xgettext, msgmerge, msgfmt). Users don't need this.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
xgettext --language=Python --from-code=UTF-8 --keyword=_ --keyword=N_ --keyword=ngettext:1,2 \
         --add-comments=TRANSLATORS --package-name=Feder --package-version="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' feder.py)" \
         --msgid-bugs-address=https://github.com/netlusche/Feder/issues -o po/feder.pot feder.py
for po in po/*.po; do
    lang="$(basename "$po" .po)"
    msgmerge --quiet --update --backup=none --no-fuzzy-matching "$po" po/feder.pot
    mkdir -p "locale/$lang/LC_MESSAGES"
    msgfmt --check --statistics -o "locale/$lang/LC_MESSAGES/feder.mo" "$po"
done
