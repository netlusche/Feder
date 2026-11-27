#!/usr/bin/env python3
# Feder – Markdown editor with live preview, focus and Hemingway mode
#
# Native GTK4/libadwaita app, only packages from the official distribution repos.
# Dependencies per distribution: see README.md or run ./install.sh
#
# Usage:  feder [FILE.md]

import gettext
import html
import json
import os
import re
import sys
import shutil

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, GtkSource, WebKit  # noqa: E402

APP_ID = "io.github.netlusche.Feder"
APP_NAME = "Feder"
VERSION = "1.1.0"
HERE = os.path.dirname(os.path.realpath(__file__))
CONFIG_PATH = os.path.join(GLib.get_user_config_dir(), "feder", "config.json")
WORDS_PER_MINUTE = 200


# --------------------------------------------------------------------------- Sprache (gettext)

_TRANSLATION = gettext.NullTranslations()
LANG = "en"
LOCALE_DIRS = [os.path.join(HERE, "locale"), os.path.join(GLib.get_user_data_dir(), "feder", "locale")]
SUPPORTED_LANGS = ("en", "de")


def _(text):
    return _TRANSLATION.gettext(text)


def ngettext(singular, plural, n):
    return _TRANSLATION.ngettext(singular, plural, n)


def N_(text):
    """Markiert Text zum Übersetzen, ohne ihn sofort zu übersetzen."""
    return text


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "")
        if value and value not in ("C", "POSIX"):
            return "de" if value.split(":")[0].lower().startswith("de") else "en"
    return "en"


def translation_for(lang):
    for d in LOCALE_DIRS:
        if os.path.isdir(d):
            t = gettext.translation("feder", localedir=d, languages=[lang], fallback=True)
            if not isinstance(t, gettext.NullTranslations) or type(t) is not gettext.NullTranslations:
                return t
    return gettext.NullTranslations()


def setup_language(preference):
    """preference: 'system', 'de' oder 'en'."""
    global _TRANSLATION, LANG
    LANG = preference if preference in SUPPORTED_LANGS else system_language()
    _TRANSLATION = translation_for(LANG) if LANG != "en" else gettext.NullTranslations()


def os_release():
    info = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                k, _sep, v = line.strip().partition("=")
                info[k] = v.strip('"')
    except OSError:
        pass
    return info


def install_command(package):
    """Installationsbefehl für ein Paket auf der erkannten Distribution."""
    info = os_release()
    ids = (info.get("ID", "") + " " + info.get("ID_LIKE", "")).lower().split()
    names = {"pandoc": {"pacman": "pandoc-cli", "apt": "pandoc", "dnf": "pandoc"}}[package]
    if any(i in ids for i in ("arch", "manjaro", "endeavouros")):
        return f"sudo pacman -S {names['pacman']}"
    if any(i in ids for i in ("debian", "ubuntu", "linuxmint", "pop")):
        return f"sudo apt install {names['apt']}"
    if any(i in ids for i in ("fedora", "rhel", "centos")):
        return f"sudo dnf install {names['dnf']}"
    return names["apt"]


EXPORTS = {
    "html": (N_("HTML page"), "html"),
    "docx": (N_("Word document"), "docx"),
    "odt": (N_("LibreOffice document"), "odt"),
    "pdf": (N_("PDF document"), "pdf"),
}

def welcome_text():
    for d in (os.path.join(HERE, "data"), os.path.join(GLib.get_user_data_dir(), "feder", "data")):
        for lang in (LANG, "en"):
            path = os.path.join(d, f"welcome.{lang}.md")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    return f.read()
    return "# Feder\n"

def _load_preview_css():
    for d in (os.path.join(HERE, "data"), os.path.join(GLib.get_user_data_dir(), "feder", "data")):
        path = os.path.join(d, "preview.css")
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return "body { font-family: sans-serif; max-width: 44em; margin: 0 auto; padding: 2em; }"


PREVIEW_CSS = _load_preview_css()

TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}" class="{body_class}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head><body><main id="content">{body}</main>{script}</body></html>"""

LIVE_SCRIPT = """<script>
function feder_set(h) { document.getElementById('content').innerHTML = h; }
function feder_theme(dark) { document.documentElement.className = dark ? 'dark' : ''; }
function feder_scroll(f) {
  var max = document.documentElement.scrollHeight - window.innerHeight;
  window.scrollTo(0, Math.max(0, max * f));
}
</script>"""

SMART_LIST = re.compile(r"^(\s*)([-*+]|\d+[.)])(\s+)(\[[ xX]\]\s+)?")
QUOTE = re.compile(r"^(\s*>\s?)")


# --------------------------------------------------------------------------- Helfer

def load_config():
    cfg = {"font_size": 13, "view_mode": "split", "welcomed": False, "last_dir": None,
           "width": 1180, "height": 780, "language": "system"}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


def num(n):
    return f"{n:,}".replace(",", ".") if LANG == "de" else f"{n:,}"


def count_words(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return len(re.findall(r"\w[\w'’-]*", text))


def title_from_markdown(text, fallback):
    m = re.search(r"^#\s+(.+)$", text, flags=re.M)
    return m.group(1).strip() if m else fallback


class Renderer:
    """Markdown → HTML. Bevorzugt pandoc, sonst python-markdown, sonst Klartext."""

    def __init__(self):
        self.pandoc = shutil.which("pandoc")
        self.pymd = None
        if not self.pandoc:
            try:
                import markdown  # noqa: F401
                self.pymd = markdown
            except ImportError:
                pass

    @property
    def name(self):
        return "pandoc" if self.pandoc else ("python-markdown" if self.pymd else _("plain text"))

    def render_async(self, text, cwd, callback):
        if self.pandoc:
            launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE |
                                                  Gio.SubprocessFlags.STDERR_SILENCE)
            if cwd:
                launcher.set_cwd(cwd)
            try:
                proc = launcher.spawnv([self.pandoc, "-f", "markdown", "-t", "html5"])
            except GLib.Error as exc:
                callback("<p>" + html.escape(_("pandoc error: {message}").format(message=exc.message)) + "</p>")
                return

            def done(p, res):
                try:
                    _ok, out, _err = p.communicate_utf8_finish(res)
                except GLib.Error as exc:
                    out = "<p>" + html.escape(_("pandoc error: {message}").format(message=exc.message)) + "</p>"
                callback(out or "")

            proc.communicate_utf8_async(text, None, done)
        elif self.pymd:
            callback(self.pymd.markdown(text, extensions=["tables", "fenced_code", "footnotes", "sane_lists"]))
        else:
            callback(f"<pre>{html.escape(text)}</pre>")


# --------------------------------------------------------------------------- Editor

class Editor(GtkSource.View):
    __gsignals__ = {"hemingway-blocked": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        self.buffer = GtkSource.Buffer()
        super().__init__(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                         top_margin=36, bottom_margin=120, left_margin=24, right_margin=24,
                         pixels_below_lines=3, pixels_inside_wrap=3, vexpand=True, hexpand=True,
                         css_classes=["feder-editor"], accepts_tab=True)
        lang = GtkSource.LanguageManager.get_default().get_language("markdown")
        if lang:
            self.buffer.set_language(lang)
        self.buffer.set_highlight_matching_brackets(False)
        self.hemingway = False
        self.focus = False
        self._allow_delete = 0
        self._focus_idle = 0
        self.dim_tag = self.buffer.create_tag("feder-dim")
        self.buffer.connect("delete-range", self._on_delete_range)
        self.buffer.connect("notify::cursor-position", lambda *_: self.queue_focus_update())
        self.buffer.connect("changed", lambda *_: self.queue_focus_update())

        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        sm = Adw.StyleManager.get_default()
        sm.connect("notify::dark", lambda *_: self.update_scheme())
        self.update_scheme()

    # ---- Programmatic changes that may delete text
    def allow_delete(self):
        editor = self

        class Ctx:
            def __enter__(self):
                editor._allow_delete += 1

            def __exit__(self, *a):
                editor._allow_delete -= 1
        return Ctx()

    def set_text(self, text):
        with self.allow_delete():
            self.buffer.begin_irreversible_action()
            self.buffer.set_text(text)
            self.buffer.end_irreversible_action()
        self.buffer.place_cursor(self.buffer.get_start_iter())
        self.buffer.set_modified(False)

    def get_text(self):
        b = self.buffer
        return b.get_text(b.get_start_iter(), b.get_end_iter(), True)

    def update_scheme(self):
        dark = Adw.StyleManager.get_default().get_dark()
        sm = GtkSource.StyleSchemeManager.get_default()
        for name in (("Adwaita-dark", "oblivion") if dark else ("Adwaita", "classic")):
            scheme = sm.get_scheme(name)
            if scheme:
                self.buffer.set_style_scheme(scheme)
                break
        c = Gdk.RGBA()
        c.parse("rgba(255,255,255,0.28)" if dark else "rgba(0,0,0,0.25)")
        self.dim_tag.set_property("foreground-rgba", c)

    # ---- Hemingway
    def set_hemingway(self, on):
        self.hemingway = on
        self.buffer.set_enable_undo(not on)

    def _on_delete_range(self, buf, start, end):
        if self.hemingway and not self._allow_delete:
            GObject.signal_stop_emission_by_name(buf, "delete-range")
            self.emit("hemingway-blocked")

    # ---- Tastatur
    def _on_key(self, ctrl, keyval, keycode, state):
        mods = state & Gtk.accelerator_get_default_mod_mask()
        primary = mods & Gdk.ModifierType.CONTROL_MASK
        if self.hemingway:
            if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
                self.emit("hemingway-blocked")
                return True
            shift = mods & Gdk.ModifierType.SHIFT_MASK
            if primary and (keyval in (Gdk.KEY_z, Gdk.KEY_Z, Gdk.KEY_y, Gdk.KEY_Y) or
                            (keyval in (Gdk.KEY_x, Gdk.KEY_X) and not shift)):
                self.emit("hemingway-blocked")
                return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not mods:
            return self._continue_list()
        return False

    def _continue_list(self):
        b = self.buffer
        if b.get_has_selection():
            return False
        it = b.get_iter_at_mark(b.get_insert())
        line_start = it.copy()
        line_start.set_line_offset(0)
        before = b.get_text(line_start, it, True)
        m = SMART_LIST.match(before)
        q = QUOTE.match(before) if not m else None
        if not m and not q:
            return False
        marker_len = (m or q).end()
        if not before[marker_len:].strip():
            # leerer Listenpunkt → Liste beenden
            if self.hemingway:
                return False
            with self.allow_delete():
                b.begin_user_action()
                b.delete(line_start, it)
                b.end_user_action()
            return True
        if m:
            indent, mark, space, box = m.group(1), m.group(2), m.group(3), m.group(4)
            if mark[0].isdigit():
                mark = f"{int(mark[:-1]) + 1}{mark[-1]}"
            prefix = indent + mark + space + ("[ ] " if box else "")
        else:
            prefix = q.group(1)
        b.begin_user_action()
        b.insert_at_cursor("\n" + prefix)
        b.end_user_action()
        self.scroll_mark_onscreen(b.get_insert())
        return True

    # ---- Formatierung
    def wrap_selection(self, before, after, placeholder=None):
        placeholder = placeholder or _("text")
        b = self.buffer
        b.begin_user_action()
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            text = b.get_text(s, e, True)
            with self.allow_delete():
                b.delete(s, e)
            b.insert_at_cursor(before + text + after)
        else:
            b.insert_at_cursor(before + placeholder + after)
            end = b.get_iter_at_mark(b.get_insert())
            end.backward_chars(len(after))
            start = end.copy()
            start.backward_chars(len(placeholder))
            b.select_range(start, end)
        b.end_user_action()

    def insert_link(self):
        b = self.buffer
        b.begin_user_action()
        text = _("link text")
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            text = b.get_text(s, e, True)
            with self.allow_delete():
                b.delete(s, e)
        b.insert_at_cursor(f"[{text}](https://)")
        end = b.get_iter_at_mark(b.get_insert())
        end.backward_char()
        start = end.copy()
        start.backward_chars(len("https://"))
        b.select_range(start, end)
        b.end_user_action()

    def set_heading(self, level):
        b = self.buffer
        it = b.get_iter_at_mark(b.get_insert())
        start = it.copy()
        start.set_line_offset(0)
        end = start.copy()
        if not end.ends_line():
            end.forward_to_line_end()
        line = b.get_text(start, end, True)
        m = re.match(r"^#{1,6}\s*", line)
        b.begin_user_action()
        if m:
            e2 = start.copy()
            e2.forward_chars(m.end())
            with self.allow_delete():
                b.delete(start, e2)
            start = b.get_iter_at_mark(b.get_insert())
            start.set_line_offset(0)
        if not m or len(m.group(0).strip()) != level:
            b.insert(start, "#" * level + " ")
        b.end_user_action()

    def _selected_lines(self):
        b = self.buffer
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            if e.starts_line() and e.get_line() > s.get_line():
                e.backward_char()
        else:
            s = e = b.get_iter_at_mark(b.get_insert())
        return s.get_line(), e.get_line()

    def toggle_line_prefix(self, kind):
        """kind: bullet, number, task, quote. Erneut anwenden entfernt das Präfix."""
        b = self.buffer
        first, last = self._selected_lines()
        pattern = {"bullet": r"^(\s*)[-*+]\s+(?!\[[ xX]\])", "number": r"^(\s*)\d+[.)]\s+",
                   "task": r"^(\s*)[-*+]\s+\[[ xX]\]\s+", "quote": r"^(\s*)>\s?"}[kind]
        any_prefix = r"^(\s*)(?:[-*+]\s+\[[ xX]\]\s+|[-*+]\s+|\d+[.)]\s+|>\s?)"

        def line_bounds(n):
            r = b.get_iter_at_line(n)
            st = r[1] if isinstance(r, tuple) else r
            en = st.copy()
            if not en.ends_line():
                en.forward_to_line_end()
            return st, en

        lines = [b.get_text(*line_bounds(n), True) for n in range(first, last + 1)]
        content = [ln for ln in lines if ln.strip()]
        remove = bool(content) and all(re.match(pattern, ln) for ln in content)
        b.begin_user_action()
        with self.allow_delete():
            counter = 1
            for i, n in enumerate(range(first, last + 1)):
                ln = lines[i]
                if not ln.strip() and len(lines) > 1:
                    continue
                if remove:
                    new = re.sub(any_prefix, r"\1", ln, count=1)
                else:
                    m = re.match(any_prefix, ln)
                    indent = m.group(1) if m else re.match(r"^\s*", ln).group(0)
                    body = ln[m.end():] if m else ln[len(indent):]
                    prefix = {"bullet": "- ", "number": f"{counter}. ", "task": "- [ ] ", "quote": "> "}[kind]
                    new = indent + prefix + body
                    counter += 1
                if new != ln:
                    st, en = line_bounds(n)
                    b.delete(st, en)
                    st, _en = line_bounds(n)
                    b.insert(st, new)
        b.end_user_action()
        if len(lines) == 1:
            _st, en = line_bounds(first)
            b.place_cursor(en)

    def _ensure_own_block(self):
        """Sorgt dafür, dass an der Cursorposition ein neuer Absatz beginnt."""
        b = self.buffer
        it = b.get_iter_at_mark(b.get_insert())
        if it.starts_line():
            prev = it.copy()
            if prev.backward_line():
                end = prev.copy()
                if not end.ends_line():
                    end.forward_to_line_end()
                if b.get_text(prev, end, True).strip():
                    b.insert_at_cursor("\n")
        else:
            b.insert_at_cursor("\n\n")

    def insert_table(self):
        b = self.buffer
        b.begin_user_action()
        if b.get_has_selection():
            b.place_cursor(b.get_selection_bounds()[1])
        self._ensure_own_block()
        mark = b.create_mark(None, b.get_iter_at_mark(b.get_insert()), True)
        cols = [_("Column {n}").format(n=n) for n in (1, 2, 3)]
        b.insert_at_cursor("| " + " | ".join(cols) + " |\n|---|---|---|\n|  |  |  |\n")
        st = b.get_iter_at_mark(mark)
        st.forward_chars(2)
        en = st.copy()
        en.forward_chars(len(cols[0]))
        b.select_range(st, en)
        b.delete_mark(mark)
        b.end_user_action()

    def insert_code_block(self):
        b = self.buffer
        b.begin_user_action()
        code = ""
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            code = b.get_text(s, e, True)
            with self.allow_delete():
                b.delete(s, e)
        self._ensure_own_block()
        b.insert_at_cursor("```\n")
        mark = b.create_mark(None, b.get_iter_at_mark(b.get_insert()), True)
        b.insert_at_cursor((code.rstrip("\n") + "\n" if code else "\n") + "```\n")
        it = b.get_iter_at_mark(mark)
        if not code:
            b.place_cursor(it)
        b.delete_mark(mark)
        b.end_user_action()

    def insert_image(self, path, alt=None):
        alt = alt or _("image description")
        b = self.buffer
        b.begin_user_action()
        if b.get_has_selection():
            s, e = b.get_selection_bounds()
            alt = b.get_text(s, e, True) or alt
            with self.allow_delete():
                b.delete(s, e)
        target = path.replace(" ", "%20")
        b.insert_at_cursor(f"![{alt}]({target})")
        it = b.get_iter_at_mark(b.get_insert())
        it.backward_chars(len(target) + 3)
        st = it.copy()
        st.backward_chars(len(alt))
        b.select_range(st, it)
        b.end_user_action()

    # ---- Fokus-Modus
    def set_focus_mode(self, on):
        self.focus = on
        self._apply_margins()
        self.queue_focus_update()

    def _apply_margins(self):
        sw = self.get_ancestor(Gtk.ScrolledWindow)
        h = sw.get_height() if sw else 0
        if self.focus and h > 200:
            self.set_top_margin(h // 2 - 20)
            self.set_bottom_margin(h // 2)
        else:
            self.set_top_margin(36)
            self.set_bottom_margin(120)

    def queue_focus_update(self):
        if not self._focus_idle:
            self._focus_idle = GLib.idle_add(self._update_focus)

    def _update_focus(self):
        self._focus_idle = 0
        b = self.buffer
        b.remove_tag(self.dim_tag, b.get_start_iter(), b.get_end_iter())
        if not self.focus:
            return False
        self.dim_tag.set_priority(b.get_tag_table().get_size() - 1)
        text = self.get_text()
        off = b.get_property("cursor-position")
        s, e = sentence_bounds(text, off)
        b.apply_tag(self.dim_tag, b.get_start_iter(), b.get_iter_at_offset(s))
        b.apply_tag(self.dim_tag, b.get_iter_at_offset(e), b.get_end_iter())
        GLib.timeout_add(20, self._center_cursor)
        return False

    def _center_cursor(self):
        if self.focus:
            self.scroll_to_mark(self.buffer.get_insert(), 0.0, True, 0.0, 0.5)
        return False


def sentence_bounds(text, off):
    """Grenzen des Satzes (bzw. Listenpunkts/Überschrift) um die Position off."""
    p_start = text.rfind("\n\n", 0, off)
    p_start = 0 if p_start < 0 else p_start + 2
    p_end = text.find("\n\n", off)
    p_end = len(text) if p_end < 0 else p_end
    line_start = text.rfind("\n", 0, off) + 1
    line_end = text.find("\n", off)
    line_end = len(text) if line_end < 0 else line_end
    line = text[line_start:line_end]
    if re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|\||```)", line):
        return line_start, line_end
    para = text[p_start:p_end]
    rel = off - p_start
    start = 0
    for m in re.finditer(r"[.!?…]+[\"”»)']*\s+", para):
        if m.end() <= rel:
            start = m.end()
        else:
            break
    end = len(para)
    m = re.compile(r"[.!?…]+[\"”»)']*(?=\s|$)").search(para, max(rel, start))
    if m:
        end = m.end()
    return p_start + start, p_start + end


# --------------------------------------------------------------------------- Vorschau

class Preview(WebKit.WebView):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True)
        s = self.get_settings()
        s.set_enable_developer_extras(False)
        s.set_allow_file_access_from_file_urls(True)
        s.set_enable_back_forward_navigation_gestures(False)
        self.ready = False
        self.pending = None
        self.base_dir = None
        self.connect("load-changed", self._on_load)
        self.connect("decide-policy", self._on_policy)
        self._apply_bg()
        Adw.StyleManager.get_default().connect("notify::dark", self._on_dark)
        self.reload_shell(None)

    def _apply_bg(self):
        c = Gdk.RGBA()
        c.parse("#1d1d20" if Adw.StyleManager.get_default().get_dark() else "#ffffff")
        self.set_background_color(c)

    def _on_dark(self, *_):
        self._apply_bg()
        self._js(f"feder_theme({json.dumps(Adw.StyleManager.get_default().get_dark())})")

    def reload_shell(self, base_dir):
        self.base_dir = base_dir
        self.ready = False
        dark = Adw.StyleManager.get_default().get_dark()
        page = TEMPLATE.format(title=_("Preview"), css=PREVIEW_CSS, lang=LANG, body_class="dark" if dark else "",
                               body="", script=LIVE_SCRIPT)
        base = GLib.filename_to_uri(base_dir, None) + "/" if base_dir else "file:///"
        self.load_html(page, base)

    def _on_load(self, view, event):
        if event == WebKit.LoadEvent.FINISHED:
            self.ready = True
            self._js(f"feder_theme({json.dumps(Adw.StyleManager.get_default().get_dark())})")
            if self.pending is not None:
                self.set_body(self.pending)

    def _on_policy(self, view, decision, kind):
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            if action.get_navigation_type() == WebKit.NavigationType.LINK_CLICKED:
                uri = action.get_request().get_uri()
                base = (GLib.filename_to_uri(self.base_dir, None) + "/") if self.base_dir else "file:///"
                if "#" in uri and uri.split("#", 1)[0] in (base, base.rstrip("/"), "about:blank"):
                    frag = json.dumps(uri.split("#", 1)[1])
                    self._js(f"var e=document.getElementById({frag}); if(e) e.scrollIntoView({{behavior:'smooth'}});")
                elif not uri.startswith("about:"):
                    Gtk.UriLauncher.new(uri).launch(self.get_root(), None, None)
                decision.ignore()
                return True
        return False

    def _js(self, script):
        if self.ready:
            self.evaluate_javascript(script, -1, None, None, None, None)

    def set_body(self, body_html):
        self.pending = body_html
        if not body_html.strip():
            body_html = '<p class="empty">' + html.escape(_("The preview appears here as soon as you start writing.")) + "</p>"
        self._js(f"feder_set({json.dumps(body_html)})")

    def scroll_fraction(self, f):
        self._js(f"feder_scroll({f:.4f})")


def print_to_pdf(parent, page_html, base_dir, path, done):
    """Rendert HTML in einer unsichtbaren WebView und druckt es als A4-PDF."""
    holder = Gtk.Window(transient_for=parent)
    view = WebKit.WebView()
    holder.set_child(view)
    view.get_settings().set_allow_file_access_from_file_urls(True)

    def loaded(v, event):
        if event != WebKit.LoadEvent.FINISHED:
            return
        op = WebKit.PrintOperation.new(v)
        settings = Gtk.PrintSettings()
        settings.set_printer("Print to File")
        settings.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT, "pdf")
        settings.set(Gtk.PRINT_SETTINGS_OUTPUT_URI, GLib.filename_to_uri(path, None))
        op.set_print_settings(settings)
        setup = Gtk.PageSetup()
        setup.set_paper_size(Gtk.PaperSize.new(Gtk.PAPER_NAME_A4))
        for side in ("top", "bottom", "left", "right"):
            getattr(setup, f"set_{side}_margin")(20, Gtk.Unit.MM)
        op.set_page_setup(setup)

        def finish(err=None):
            done(err)
            holder.destroy()

        op.connect("finished", lambda *_: finish())
        op.connect("failed", lambda _o, e: finish(e.message if hasattr(e, "message") else str(e)))
        op.print_()

    view.connect("load-changed", loaded)
    base = GLib.filename_to_uri(base_dir, None) + "/" if base_dir else "file:///"
    view.load_html(page_html, base)


# --------------------------------------------------------------------------- Fenster

CSS = """
textview.feder-editor { font-family: "IBM Plex Mono", "Fira Mono", "Source Code Pro", "DejaVu Sans Mono", monospace;
                        font-size: %dpt; }
.statusbar { padding: 4px 14px; border-top: 1px solid alpha(currentColor, 0.08); }
.statusbar label { font-size: 0.88em; }
.mode-pill { background: alpha(@accent_bg_color, 0.16); color: @accent_color; border-radius: 99px;
             padding: 1px 9px; font-weight: 700; font-size: 0.8em; }
.mode-pill.hemingway { background: alpha(@warning_bg_color, 0.2); color: @warning_color; }
.editor-pane, textview.feder-editor, textview.feder-editor > text { background-color: @view_bg_color; }
textview.feder-editor { background-color: transparent; }
textview.feder-editor > text { background-color: transparent; }
.statusbar { min-height: 34px; padding-top: 2px; padding-bottom: 2px; }
.statusbar button { min-height: 26px; min-width: 28px; padding: 2px 5px; }
.statusbar .fmt-sep { min-width: 1px; margin: 6px 4px; background: alpha(currentColor, 0.15); }
.statusbar .fmt-letter { font-size: 1.05em; font-family: "Cantarell", "Inter", sans-serif; }
.statusbar .stats-btn { padding: 2px 8px; }
.preview-pane { border-left: 1px solid alpha(currentColor, 0.08); }
"""


class FederWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        self.cfg = load_config()
        super().__init__(application=app, default_width=self.cfg["width"], default_height=self.cfg["height"])
        self.set_size_request(520, 420)
        self.file = None
        self.renderer = Renderer()
        self._render_src = 0
        self._rendering = False
        self._render_again = False
        self._last_block_toast = 0
        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self._css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._apply_font()

        # Editor
        self.editor = Editor()
        self.editor.connect("hemingway-blocked", self._on_blocked)
        clamp = Adw.ClampScrollable(child=self.editor, maximum_size=820, tightening_threshold=600)
        self.editor_scroller = Gtk.ScrolledWindow(child=clamp, hscrollbar_policy=Gtk.PolicyType.NEVER,
                                                  css_classes=["editor-pane"])
        self.editor_scroller.get_vadjustment().connect("value-changed", self._on_editor_scroll)
        self.editor_scroller.get_vadjustment().connect("notify::page-size", lambda *_: self.editor._apply_margins())

        # Suche
        self.search_settings = GtkSource.SearchSettings(wrap_around=True, case_sensitive=False)
        self.search_ctx = GtkSource.SearchContext(buffer=self.editor.buffer, settings=self.search_settings)
        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Search in text …"), width_chars=30)
        self.search_entry.connect("search-changed", self._on_search)
        self.search_entry.connect("activate", lambda *_: self._search_step(True))
        self.search_entry.connect("next-match", lambda *_: self._search_step(True))
        self.search_entry.connect("previous-match", lambda *_: self._search_step(False))
        self.search_entry.connect("stop-search", lambda *_: self.search_bar.set_search_mode(False))
        self.search_info = Gtk.Label(css_classes=["dim-label", "caption"])
        sbox = Gtk.Box(spacing=8)
        sbox.append(self.search_entry)
        sbox.append(self.search_info)
        self.search_bar = Gtk.SearchBar(child=sbox, show_close_button=True)
        self.search_bar.connect_entry(self.search_entry)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.append(self.search_bar)
        left.append(self.editor_scroller)

        # Vorschau
        self.preview = Preview()
        self.preview_box = Gtk.Box(css_classes=["preview-pane"])
        self.preview_box.append(self.preview)

        self.paned = Gtk.Paned(start_child=left, end_child=self.preview_box, resize_start_child=True,
                               resize_end_child=True, shrink_start_child=False, shrink_end_child=False,
                               wide_handle=False)

        # Statusleiste mit Formatierungsknöpfen
        self.format_revealer = self._build_format_bar()
        self.pill_focus = Gtk.Label(label=_("FOCUS"), css_classes=["mode-pill"], visible=False)
        self.pill_hem = Gtk.Label(label="HEMINGWAY", css_classes=["mode-pill", "hemingway"], visible=False)
        self.pos_label = Gtk.Label(css_classes=["dim-label", "numeric"])
        self.stats_label = Gtk.Label(css_classes=["dim-label", "numeric"])
        self.stats_button = Gtk.Button(child=self.stats_label, css_classes=["flat", "stats-btn"],
                                       tooltip_text=_("Words, characters and reading time"))
        self.stats_button.connect("clicked", self._cycle_stats)
        self._stats_compact = False
        self._stats_index = 0
        self._stats = (0, 0, 0)
        status = Gtk.Box(spacing=8, css_classes=["statusbar"])
        status.append(self.format_revealer)
        right = Gtk.Box(spacing=8, hexpand=True, halign=Gtk.Align.END)
        right.append(self.pill_focus)
        right.append(self.pill_hem)
        right.append(self.pos_label)
        right.append(self.stats_button)
        status.append(right)

        self.toasts = Adw.ToastOverlay(child=self.paned)

        # Kopfleiste
        self.title = Adw.WindowTitle(title=APP_NAME)
        header = Adw.HeaderBar(title_widget=self.title)
        open_btn = Gtk.Button(icon_name="document-open-symbolic", tooltip_text=_("Open (Ctrl+O)"),
                              action_name="win.open")
        header.pack_start(open_btn)
        save_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text=_("Save (Ctrl+S)"),
                              action_name="win.save")
        header.pack_start(save_btn)
        new_btn = Gtk.Button(icon_name="document-new-symbolic", tooltip_text=_("New (Ctrl+N)"),
                             action_name="win.new")
        header.pack_start(new_btn)

        menu = Gio.Menu()
        sec = Gio.Menu()
        sec.append(_("New"), "win.new")
        sec.append(_("Open …"), "win.open")
        sec.append(_("Save"), "win.save")
        sec.append(_("Save As …"), "win.save-as")
        menu.append_section(None, sec)
        exp = Gio.Menu()
        for key, (label, _ext) in EXPORTS.items():
            exp.append(f"{_(label)} (.{key})", f"win.export::{key}")
        menu.append_submenu(_("Export As"), exp)
        sec2 = Gio.Menu()
        sec2.append(_("Search"), "win.find")
        sec2.append(_("Full Screen"), "win.fullscreen")
        langs = Gio.Menu()
        langs.append(_("System Default"), "win.language::system")
        langs.append("Deutsch", "win.language::de")
        langs.append("English", "win.language::en")
        sec2.append_submenu(_("Language"), langs)
        menu.append_section(None, sec2)
        sec3 = Gio.Menu()
        sec3.append(_("Show Introduction"), "win.welcome")
        sec3.append(_("Keyboard Shortcuts"), "win.shortcuts")
        sec3.append(_("About Feder"), "app.about")
        menu.append_section(None, sec3)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text=_("Main Menu")))

        exp_btn = Gtk.MenuButton(icon_name="feder-export-symbolic", menu_model=exp,
                                 tooltip_text=_("Export (Ctrl+E)"))
        self.export_button = exp_btn
        header.pack_end(exp_btn)

        views = Gio.Menu()
        views.append(_("Editor Only"), "win.view-mode::editor")
        views.append(_("Editor and Preview"), "win.view-mode::split")
        views.append(_("Preview Only"), "win.view-mode::preview")
        header.pack_end(Gtk.MenuButton(icon_name="feder-preview-symbolic", menu_model=views,
                                       tooltip_text=_("View (Ctrl+P switches)")))
        header.pack_end(Gtk.ToggleButton(icon_name="feder-hemingway-symbolic", action_name="win.hemingway",
                                         tooltip_text=_("Hemingway mode: no deleting (Ctrl+Shift+H)")))
        header.pack_end(Gtk.ToggleButton(icon_name="feder-focus-symbolic", action_name="win.focus",
                                         tooltip_text=_("Focus mode (Ctrl+D)")))
        self.header = header

        self.tv = Adw.ToolbarView(content=self.toasts)
        self.tv.add_top_bar(header)
        self.tv.add_bottom_bar(status)
        self.set_content(self.tv)
        if hasattr(Adw, "Breakpoint"):
            for cond, level in (("max-width: 1000sp", 1), ("max-width: 760sp", 2)):
                bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(cond))
                bp.connect("apply", lambda _b, lv=level: self._set_bar_level(lv))
                bp.connect("unapply", lambda _b, lv=level: self._set_bar_level(lv - 1))
                self.add_breakpoint(bp)

        self._setup_actions(app)
        self.editor.buffer.connect("changed", self._on_changed)
        self.editor.buffer.connect("modified-changed", lambda *_: self._update_title())
        self.editor.buffer.connect("notify::cursor-position", lambda *_: self._update_pos())
        self.connect("close-request", self._on_close_request)
        self.connect("notify::fullscreened", self._on_fullscreen)
        esc = Gtk.EventControllerKey()
        esc.connect("key-pressed", lambda _c, k, _kc, _s: (self.unfullscreen(), True)[1]
                    if k == Gdk.KEY_Escape and self.is_fullscreen() else False)
        self.add_controller(esc)

        self._view_mode = None
        self._set_view_mode(self.cfg.get("view_mode", "split"))
        self.paned.set_position(self.cfg["width"] // 2)

        if not self.cfg.get("welcomed"):
            self.editor.set_text(welcome_text())
            self.cfg["welcomed"] = True
            save_config(self.cfg)
        self._update_title()
        self._update_pos()
        self._schedule_render(0)

    # ---------------------------------------------------------------- Aktionen
    def _setup_actions(self, app):
        def add(name, cb, accels=(), param=None, state=None):
            if state is not None:
                act = Gio.SimpleAction.new_stateful(name, GLib.VariantType.new(param) if param else None, state)
                act.connect("change-state", cb)
            else:
                act = Gio.SimpleAction.new(name, GLib.VariantType.new(param) if param else None)
                act.connect("activate", cb)
            self.add_action(act)
            if accels:
                app.set_accels_for_action(f"win.{name}", list(accels))
            return act

        add("new", lambda *_: self._guard(self._new), ["<primary>n"])
        add("open", lambda *_: self._guard(self._open_dialog), ["<primary>o"])
        add("save", lambda *_: self.save(), ["<primary>s"])
        add("save-as", lambda *_: self.save(force_dialog=True), ["<primary><shift>s"])
        add("export", lambda _a, v: self.export(v.get_string()), param="s")
        add("export-menu", lambda *_: self.export_button.popup(), ["<primary>e"])
        self.act_view = add("view-mode", self._on_view_mode, param="s", state=GLib.Variant("s", "split"))
        add("cycle-view", lambda *_: self._set_view_mode(
            {"split": "editor", "editor": "preview", "preview": "split"}[self._view_mode]), ["<primary>p"])
        self.act_focus = add("focus", self._on_focus, ["<primary>d"], state=GLib.Variant("b", False))
        self.act_hem = add("hemingway", self._on_hemingway, ["<primary><shift>h"], state=GLib.Variant("b", False))
        add("fullscreen", lambda *_: self.unfullscreen() if self.is_fullscreen() else self.fullscreen(), ["F11"])
        add("find", lambda *_: (self.search_bar.set_search_mode(True), self.search_entry.grab_focus()),
            ["<primary>f"])
        add("bold", lambda *_: self.editor.wrap_selection("**", "**"), ["<primary>b"])
        add("italic", lambda *_: self.editor.wrap_selection("*", "*"), ["<primary>i"])
        add("code", lambda *_a: self.editor.wrap_selection("`", "`", _("code")), ["<primary><shift>c"])
        add("link", lambda *_: self.editor.insert_link(), ["<primary>k"])
        add("strike", lambda *_: self.editor.wrap_selection("~~", "~~"), ["<primary><shift>x"])
        add("list-bullet", lambda *_: self.editor.toggle_line_prefix("bullet"), ["<primary><shift>l"])
        add("list-number", lambda *_: self.editor.toggle_line_prefix("number"), ["<primary><shift>n"])
        add("list-task", lambda *_: self.editor.toggle_line_prefix("task"), ["<primary><shift>o"])
        add("quote", lambda *_: self.editor.toggle_line_prefix("quote"), ["<primary><shift>q"])
        add("image", lambda *_: self._choose_image(), ["<primary><shift>i"])
        add("table", lambda *_: self.editor.insert_table(), ["<primary><shift>t"])
        add("code-block", lambda *_: self.editor.insert_code_block(), ["<primary><alt>c"])
        for n in (1, 2, 3):
            add(f"h{n}", lambda *_a, n=n: self.editor.set_heading(n), [f"<primary>{n}"])
        add("zoom-in", lambda *_: self._zoom(1), ["<primary>plus", "<primary>equal", "<primary>KP_Add"])
        add("zoom-out", lambda *_: self._zoom(-1), ["<primary>minus", "<primary>KP_Subtract"])
        add("zoom-reset", lambda *_: self._zoom(0), ["<primary>0"])
        add("shortcuts", lambda *_: self._show_shortcuts(), ["<primary>question"])
        add("welcome", lambda *_: self._guard(self._show_welcome))
        self.act_lang = add("language", self._on_language, param="s",
                            state=GLib.Variant("s", self.cfg.get("language", "system")))

    def _build_format_bar(self):
        groups = [
            [("<b>B</b>", "win.bold", _("Bold (Ctrl+B)")),
             ("<i>I</i>", "win.italic", _("Italic (Ctrl+I)")),
             ("<s>S</s>", "win.strike", _("Strikethrough (Ctrl+Shift+X)"))],
            [("heading", None, _("Heading (Ctrl+1, 2, 3)")),
             ("feder-list-bullet-symbolic", "win.list-bullet", _("Bulleted list (Ctrl+Shift+L)")),
             ("feder-list-number-symbolic", "win.list-number", _("Numbered list (Ctrl+Shift+N)")),
             ("feder-list-task-symbolic", "win.list-task", _("Task list (Ctrl+Shift+O)")),
             ("feder-quote-symbolic", "win.quote", _("Quote (Ctrl+Shift+Q)"))],
            [("feder-link-symbolic", "win.link", _("Link (Ctrl+K)")),
             ("feder-image-symbolic", "win.image", _("Insert image (Ctrl+Shift+I)")),
             ("feder-table-symbolic", "win.table", _("Insert table (Ctrl+Shift+T)")),
             ("feder-code-symbolic", "win.code-block", _("Code block (Ctrl+Alt+C)"))],
        ]
        bar = Gtk.Box(spacing=1, valign=Gtk.Align.CENTER)
        self.format_groups = []
        for gi_, group in enumerate(groups):
            gbox = Gtk.Box(spacing=1)
            if gi_:
                gbox.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL, css_classes=["fmt-sep"]))
            for icon, action, tip in group:
                if icon == "heading":
                    hm = Gio.Menu()
                    for n in (1, 2, 3):
                        hm.append(_("Heading {n}").format(n=n), f"win.h{n}")
                    btn = Gtk.MenuButton(menu_model=hm, tooltip_text=tip, css_classes=["flat"],
                                         always_show_arrow=True)
                    btn.set_child(Gtk.Label(label="<b>H</b>", use_markup=True, css_classes=["fmt-letter"]))
                elif icon.startswith("<"):
                    btn = Gtk.Button(action_name=action, tooltip_text=tip, css_classes=["flat"])
                    btn.set_child(Gtk.Label(label=icon, use_markup=True, css_classes=["fmt-letter"]))
                else:
                    btn = Gtk.Button(icon_name=icon, action_name=action, tooltip_text=tip, css_classes=["flat"])
                btn.set_focusable(False)
                gbox.append(btn)
            bar.append(gbox)
            self.format_groups.append(gbox)
        return Gtk.Revealer(child=bar, reveal_child=True, transition_type=Gtk.RevealerTransitionType.CROSSFADE,
                            transition_duration=220)

    def _update_format_bar(self):
        if not hasattr(self, "format_revealer"):
            return
        show = not getattr(self, "_in_focus", False) and self._view_mode != "preview"
        self.format_revealer.set_reveal_child(show)

    def _set_bar_level(self, level):
        """0 = breit, 1 = kompakte Statistik, 2 = zusätzlich ohne Einfügen-Gruppe und Position."""
        self._stats_compact = level >= 1
        self.format_groups[2].set_visible(level < 2)
        self.pos_label.set_visible(level < 2)
        self._show_stats()

    def _cycle_stats(self, _btn):
        if self._stats_compact:
            self._stats_index = (self._stats_index + 1) % 3
            self._show_stats()

    def _show_stats(self):
        words, chars, minutes = self._stats
        parts = [ngettext("{n} word", "{n} words", words).format(n=num(words)),
                 ngettext("{n} character", "{n} characters", chars).format(n=num(chars)),
                 _("{n} min read").format(n=minutes)]
        if self._stats_compact:
            self.stats_label.set_label(parts[self._stats_index])
            self.stats_button.set_tooltip_text(_("Click to switch between words, characters and reading time"))
        else:
            self.stats_label.set_label("  ·  ".join(parts))
            self.stats_button.set_tooltip_text(_("Words, characters and reading time"))

    def _choose_image(self):
        store = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter(name=_("Images"))
        for p in ("*.png", "*.jpg", "*.jpeg", "*.gif", "*.svg", "*.webp"):
            f.add_pattern(p)
            f.add_pattern(p.upper())
        store.append(f)
        dlg = Gtk.FileDialog(title=_("Insert Image"), modal=True, filters=store)
        folder = self._initial_folder()
        if folder:
            dlg.set_initial_folder(folder)

        def done(d, res):
            try:
                gf = d.open_finish(res)
            except GLib.Error:
                return
            path = gf.get_path()
            doc_dir = self._doc_dir()
            if doc_dir:
                rel = os.path.relpath(path, doc_dir)
                path = rel if not rel.startswith("../../..") else path
            else:
                self.toast(_("Tip: Save the document first, then the image path becomes relative and portable."))
            self.editor.insert_image(path)
        dlg.open(self, None, done)

    def _on_language(self, act, value):
        lang = value.get_string()
        if lang == self.cfg.get("language", "system"):
            return
        act.set_state(value)
        self.cfg["language"] = lang
        save_config(self.cfg)
        target = lang if lang in SUPPORTED_LANGS else system_language()
        t = translation_for(target) if target != "en" else gettext.NullTranslations()
        self.toast(t.gettext("Restart Feder to switch the language."))

    def _on_view_mode(self, act, value):
        self._set_view_mode(value.get_string())

    def _set_view_mode(self, mode):
        if mode not in ("editor", "split", "preview"):
            mode = "split"
        self._view_mode = mode
        self.act_view.set_state(GLib.Variant("s", mode))
        self.paned.get_start_child().set_visible(mode != "preview")
        self.preview_box.set_visible(mode != "editor")
        if mode == "split" and self.paned.get_width() > 0:
            self.paned.set_position(self.paned.get_width() // 2)
        if not getattr(self, "_in_focus", False):
            self.cfg["view_mode"] = mode
        if mode != "editor":
            self._schedule_render(0)
        self._update_format_bar()

    def _on_focus(self, act, value):
        on = value.get_boolean()
        act.set_state(value)
        self.pill_focus.set_visible(on)
        if on:
            self._mode_before_focus = self._view_mode
            self._in_focus = True
            self._set_view_mode("editor")
        else:
            self._in_focus = False
            self._set_view_mode(getattr(self, "_mode_before_focus", "split"))
        self.editor.set_focus_mode(on)
        self._update_format_bar()
        self.editor.grab_focus()

    def _on_hemingway(self, act, value):
        on = value.get_boolean()
        act.set_state(value)
        self.pill_hem.set_visible(on)
        self.editor.set_hemingway(on)
        self.toast(_("Hemingway mode on: deleting is disabled. Only forward!") if on
                   else _("Hemingway mode off: you can delete again."))
        self.editor.grab_focus()

    def _on_blocked(self, _ed):
        now = GLib.get_monotonic_time()
        if now - self._last_block_toast > 8_000_000:
            self._last_block_toast = now
            self.toast(_("Hemingway mode: deleting is disabled. Just keep writing."))
        self.error_bell()

    def _on_fullscreen(self, *_):
        fs = self.is_fullscreen()
        self.tv.set_reveal_top_bars(not fs)
        self.tv.set_reveal_bottom_bars(not fs)

    def _zoom(self, step):
        self.cfg["font_size"] = 13 if step == 0 else max(8, min(32, self.cfg["font_size"] + step))
        self._apply_font()
        save_config(self.cfg)

    def _apply_font(self):
        css = CSS % self.cfg["font_size"]
        if hasattr(self._css, "load_from_string"):
            self._css.load_from_string(css)
        else:
            self._css.load_from_data(css.encode())

    # ---------------------------------------------------------------- Rendering & Statistik
    def _on_changed(self, *_):
        self._schedule_render(250)

    def _schedule_render(self, delay):
        if self._render_src:
            GLib.source_remove(self._render_src)
        self._render_src = GLib.timeout_add(delay, self._render)

    def _render(self):
        self._render_src = 0
        text = self.editor.get_text()
        words = count_words(text)
        minutes = max(1, round(words / WORDS_PER_MINUTE)) if words else 0
        self._stats = (words, len(text), minutes)
        self._show_stats()
        if not self.preview_box.get_visible():
            return False
        if self._rendering:
            self._render_again = True
            return False
        self._rendering = True
        self.renderer.render_async(text, self._doc_dir(), self._on_rendered)
        return False

    def _on_rendered(self, body):
        self._rendering = False
        self.preview.set_body(body)
        if self._render_again:
            self._render_again = False
            self._schedule_render(0)

    def _on_editor_scroll(self, adj):
        rng = adj.get_upper() - adj.get_page_size()
        if rng > 0:
            self.preview.scroll_fraction(adj.get_value() / rng)

    def _update_pos(self):
        it = self.editor.buffer.get_iter_at_mark(self.editor.buffer.get_insert())
        self.pos_label.set_label(_("Line {line}, Column {column}").format(line=it.get_line() + 1,
                                                                           column=it.get_line_offset() + 1))

    # ---------------------------------------------------------------- Suche
    def _on_search(self, entry):
        self.search_settings.set_search_text(entry.get_text() or None)
        GLib.timeout_add(60, self._update_search_info)
        self._search_step(True, from_start=True)

    def _update_search_info(self):
        n = self.search_ctx.get_occurrences_count()
        self.search_info.set_label("" if not self.search_entry.get_text() else
                                   (_("no matches") if n == 0 else
                                    ngettext("{n} match", "{n} matches", n).format(n=n) if n > 0 else ""))
        return False

    def _search_step(self, forward, from_start=False):
        b = self.editor.buffer
        if not self.search_settings.get_search_text():
            return
        if from_start:
            it = b.get_iter_at_mark(b.get_selection_bound())
            if b.get_has_selection():
                it = b.get_selection_bounds()[0]
        else:
            s, e = (b.get_selection_bounds() if b.get_has_selection()
                    else (b.get_iter_at_mark(b.get_insert()),) * 2)
            it = e if forward else s
        res = self.search_ctx.forward(it) if forward else self.search_ctx.backward(it)
        if res[0]:
            b.select_range(res[1], res[2])
            self.editor.scroll_to_iter(res[1], 0.15, False, 0, 0)

    # ---------------------------------------------------------------- Dateien
    def _doc_dir(self):
        if self.file and self.file.get_path():
            return os.path.dirname(self.file.get_path())
        return None

    def _update_title(self):
        name = self.file.get_basename() if self.file else _("Untitled") + ".md"
        mod = self.editor.buffer.get_modified()
        self.title.set_title(("• " if mod else "") + name)
        if self.file and self.file.get_path():
            d = os.path.dirname(self.file.get_path()).replace(GLib.get_home_dir(), "~", 1)
            self.title.set_subtitle(d)
        else:
            self.title.set_subtitle(_("Not saved yet"))
        self.set_title(f"{name} – {APP_NAME}")

    def _guard(self, then):
        """Bei ungespeicherten Änderungen erst nachfragen."""
        if not self.editor.buffer.get_modified():
            then()
            return
        self._ask_unsaved(then)

    def _ask_unsaved(self, then):
        name = self.file.get_basename() if self.file else _("Untitled") + ".md"
        heading = _("Save changes?")
        body = _("“{name}” has unsaved changes. They will be lost if you don’t save them.").format(name=name)
        cls = getattr(Adw, "AlertDialog", None)
        dlg = cls(heading=heading, body=body) if cls else Adw.MessageDialog(transient_for=self, heading=heading,
                                                                             body=body)
        dlg.add_response("cancel", _("Cancel"))
        dlg.add_response("discard", _("Discard"))
        dlg.add_response("save", _("Save"))
        dlg.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("save")
        dlg.set_close_response("cancel")

        def resp(_d, r):
            if r == "discard":
                then()
            elif r == "save":
                self.save(after=then)
        dlg.connect("response", resp)
        dlg.present(self) if cls else dlg.present()

    def _show_welcome(self):
        self.file = None
        self.editor.set_text(welcome_text())
        self.preview.reload_shell(None)
        self._update_title()
        self._schedule_render(0)

    def _new(self):
        self.file = None
        self.editor.set_text("")
        self.preview.reload_shell(None)
        self._update_title()
        self._schedule_render(0)

    def _filters(self, kind="md"):
        store = Gio.ListStore.new(Gtk.FileFilter)
        if kind == "md":
            f = Gtk.FileFilter(name="Markdown")
            for p in ("*.md", "*.markdown", "*.mdown", "*.mkd", "*.txt"):
                f.add_pattern(p)
            store.append(f)
            a = Gtk.FileFilter(name=_("All Files"))
            a.add_pattern("*")
            store.append(a)
        else:
            label, ext = EXPORTS[kind]
            f = Gtk.FileFilter(name=_(label))
            f.add_pattern(f"*.{ext}")
            store.append(f)
        return store

    def _initial_folder(self):
        d = self._doc_dir() or self.cfg.get("last_dir") or GLib.get_user_special_dir(
            GLib.UserDirectory.DIRECTORY_DOCUMENTS) or GLib.get_home_dir()
        return Gio.File.new_for_path(d) if d and os.path.isdir(d) else None

    def _open_dialog(self):
        dlg = Gtk.FileDialog(title=_("Open Markdown File"), modal=True, filters=self._filters("md"))
        folder = self._initial_folder()
        if folder:
            dlg.set_initial_folder(folder)

        def done(d, res):
            try:
                f = d.open_finish(res)
            except GLib.Error:
                return
            self.load_file(f)
        dlg.open(self, None, done)

    def load_file(self, gfile):
        try:
            with open(gfile.get_path(), encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError, TypeError) as exc:
            self.toast(_("Could not open the file: {error}").format(error=exc))
            return
        self.file = gfile
        self.editor.set_text(text)
        self.cfg["last_dir"] = os.path.dirname(gfile.get_path())
        save_config(self.cfg)
        Gtk.RecentManager.get_default().add_item(gfile.get_uri())
        self.preview.reload_shell(self._doc_dir())
        self._update_title()
        self._schedule_render(0)

    def save(self, force_dialog=False, after=None):
        if self.file and not force_dialog:
            self._write(self.file, after)
            return
        dlg = Gtk.FileDialog(title=_("Save As"), modal=True, filters=self._filters("md"))
        dlg.set_initial_name(self.file.get_basename() if self.file else
                             self._suggest_name() + ".md")
        folder = self._initial_folder()
        if folder:
            dlg.set_initial_folder(folder)

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            path = f.get_path()
            if not os.path.splitext(path)[1]:
                f = Gio.File.new_for_path(path + ".md")
            self.file = f
            self.preview.reload_shell(self._doc_dir())
            self._schedule_render(0)
            self._write(f, after)
        dlg.save(self, None, done)

    def _write(self, gfile, after=None):
        try:
            with open(gfile.get_path(), "w", encoding="utf-8") as fh:
                fh.write(self.editor.get_text())
        except OSError as exc:
            self.toast(_("Saving failed: {error}").format(error=exc))
            return
        self.editor.buffer.set_modified(False)
        self.cfg["last_dir"] = os.path.dirname(gfile.get_path())
        save_config(self.cfg)
        Gtk.RecentManager.get_default().add_item(gfile.get_uri())
        self._update_title()
        self.toast(_("Saved: {name}").format(name=gfile.get_basename()))
        if after:
            after()

    def _suggest_name(self):
        if self.file:
            return os.path.splitext(self.file.get_basename())[0]
        t = title_from_markdown(self.editor.get_text(), _("Untitled"))
        return re.sub(r"[^\w\- ]", "", t).strip()[:60] or _("Untitled")

    # ---------------------------------------------------------------- Export
    def export(self, kind):
        if kind in ("docx", "odt") and not self.renderer.pandoc:
            self.toast(_("Word and ODT export needs pandoc: {command}").format(command=install_command("pandoc")))
            return
        label, ext = EXPORTS[kind]
        dlg = Gtk.FileDialog(title=_("Export as {format}").format(format=_(label)), modal=True,
                             filters=self._filters(kind))
        dlg.set_initial_name(f"{self._suggest_name()}.{ext}")
        folder = self._initial_folder()
        if folder:
            dlg.set_initial_folder(folder)

        def done(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            path = f.get_path()
            if not path.lower().endswith("." + ext):
                path += "." + ext
            self._do_export(kind, path)
        dlg.save(self, None, done)

    def _standalone_html(self, body, for_print=False):
        title = html.escape(title_from_markdown(self.editor.get_text(), self._suggest_name()))
        return TEMPLATE.format(title=title, css=PREVIEW_CSS, lang=LANG, body_class="", body=body, script="")

    def _do_export(self, kind, path):
        text = self.editor.get_text()
        cwd = self._doc_dir()

        def finished(err=None):
            if err:
                self.toast(_("Export failed: {error}").format(error=err))
                return
            t = Adw.Toast(title=GLib.markup_escape_text(_("Exported: {name}").format(name=os.path.basename(path))),
                          timeout=6)
            t.set_button_label(_("Open"))
            t.connect("button-clicked", lambda *_: Gtk.FileLauncher.new(Gio.File.new_for_path(path)).launch(
                self, None, None))
            self.toasts.add_toast(t)

        if kind in ("html", "pdf"):
            def rendered(body):
                page = self._standalone_html(body)
                if kind == "html":
                    try:
                        with open(path, "w", encoding="utf-8") as fh:
                            fh.write(page)
                    except OSError as exc:
                        finished(str(exc))
                        return
                    finished()
                else:
                    self.toast(_("Creating PDF …"))
                    print_to_pdf(self, page, cwd, path, finished)
            self.renderer.render_async(text, cwd, rendered)
            return

        # docx / odt über pandoc
        title = title_from_markdown(text, self._suggest_name())
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_SILENCE |
                                              Gio.SubprocessFlags.STDERR_PIPE)
        if cwd:
            launcher.set_cwd(cwd)
        argv = [self.renderer.pandoc, "-f", "markdown", "-t", kind, "-s", "-o", path,
                "--metadata", f"pagetitle={title}"]
        try:
            proc = launcher.spawnv(argv)
        except GLib.Error as exc:
            finished(exc.message)
            return

        def done(p, res):
            try:
                _ok, _out, err = p.communicate_utf8_finish(res)
            except GLib.Error as exc:
                finished(exc.message)
                return
            if p.get_exit_status() != 0:
                finished((err or "").strip().splitlines()[-1] if err else
                         _("pandoc exit code {code}").format(code=p.get_exit_status()))
            else:
                finished()
        proc.communicate_utf8_async(text, None, done)

    # ---------------------------------------------------------------- Sonstiges
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=3))

    def _show_shortcuts(self):
        rows = [(_("New / Open / Save"), _("Ctrl+N / Ctrl+O / Ctrl+S")), (_("Save As"), _("Ctrl+Shift+S")),
                (_("Export"), _("Ctrl+E")), (_("Switch view"), _("Ctrl+P")), (_("Focus mode"), _("Ctrl+D")),
                (_("Hemingway mode"), _("Ctrl+Shift+H")),
                (_("Bold / Italic / Code"), _("Ctrl+B / Ctrl+I / Ctrl+Shift+C")),
                (_("Strikethrough"), _("Ctrl+Shift+X")), (_("Bulleted / Numbered"), _("Ctrl+Shift+L / N")),
                (_("Task list / Quote"), _("Ctrl+Shift+O / Q")), (_("Image / Table"), _("Ctrl+Shift+I / T")),
                (_("Code block"), _("Ctrl+Alt+C")), (_("Link"), _("Ctrl+K")), (_("Heading 1 to 3"), _("Ctrl+1 / 2 / 3")),
                (_("Search"), _("Ctrl+F")),
                (_("Font larger / smaller / normal"), _("Ctrl++ / Ctrl+- / Ctrl+0")), (_("Full Screen"), "F11")]
        body = "\n".join(f"{a}:  {b}" for a, b in rows)
        cls = getattr(Adw, "AlertDialog", None)
        dlg = cls(heading=_("Keyboard Shortcuts"), body=body) if cls else Adw.MessageDialog(
            transient_for=self, heading=_("Keyboard Shortcuts"), body=body)
        dlg.add_response("ok", _("Close"))
        dlg.present(self) if cls else dlg.present()

    def _on_close_request(self, *_):
        if not self.is_fullscreen() and not self.is_maximized():
            self.cfg["width"], self.cfg["height"] = self.get_width(), self.get_height()
        save_config(self.cfg)
        if self.editor.buffer.get_modified():
            self._ask_unsaved(lambda: (self.editor.buffer.set_modified(False), self.close()))
            return True
        return False


class FederApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        GLib.set_application_name(APP_NAME)
        for name, cb, accels in (("quit", self._quit, ["<primary>q"]), ("about", self._about, [])):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    def do_startup(self):
        Adw.Application.do_startup(self)
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for d in (os.path.join(HERE, "icons"), os.path.join(GLib.get_user_data_dir(), "feder", "icons")):
            if os.path.isdir(d):
                theme.add_search_path(d)

    def _window(self):
        win = self.get_active_window()
        if not win:
            win = FederWindow(self)
        return win

    def do_activate(self):
        self._window().present()

    def do_open(self, files, n_files, hint):
        win = self._window()
        if files:
            win.load_file(files[0])
        win.present()

    def _quit(self, *_):
        win = self.get_active_window()
        if win:
            win.close()
        else:
            self.quit()

    def _about(self, *_args):
        kw = dict(application_name=APP_NAME, application_icon=APP_ID, version=VERSION,
                  developer_name="netlusche & Claudia",
                  comments=_("Write Markdown with live preview, focus and Hemingway mode. "
                             "Export to HTML, Word, LibreOffice and PDF."),
                  translator_credits=_("translator-credits"),
                  website="https://github.com/netlusche/Feder",
                  license_type=Gtk.License.MIT_X11)
        win = self.get_active_window()
        if hasattr(Adw, "AboutDialog"):
            Adw.AboutDialog(**kw).present(win)
        else:
            Adw.AboutWindow(transient_for=win, **kw).present()


def main():
    setup_language(load_config().get("language", "system"))
    if "--version" in sys.argv:
        print(f"{APP_NAME} {VERSION}")
        return 0
    return FederApp().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
