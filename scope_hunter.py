"""
Scope Hunter.

Licensed under MIT
Copyright (c) 2012 - 2015 Isaac Muse <isaacmuse@gmail.com>
"""
import sublime
import sublime_plugin
from time import time, sleep
import threading
from ScopeHunter.lib.color_scheme_matcher import ColorSchemeMatcher
from ScopeHunter.scope_hunter_notify import notify, error
import traceback

TOOLTIP_SUPPORT = int(sublime.version()) >= 3080
if TOOLTIP_SUPPORT:
    import mdpopups

if 'sh_thread' not in globals():
    sh_thread = None

scheme_matcher = None
sh_settings = {}

ADD_CSS = '''
.scope-hunter.content { margin: 0; padding: 0.5em; }
.scope-hunter.small { font-size: 0.8em; }
'''

# Scope Toolip Markdown
SCOPE_HEADER = '## Scope\n'
SCOPES = '''
%s
[(copy)](copy-scope:%d){: .scope-hunter .small}
'''

SCOPE_EXTENT_HEADER = '\n## Scope Extent\n'
PTS = '''
**pts:**{: .keyword} (%d, %d)
[(copy)](copy-points:%d){: .scope-hunter .small}
'''
CHAR_LINE = '''
**line/char:**{: .keyword} (**Line:** %d **Char:** %d, **Line:** %d **Char:** %d)
[(copy)](copy-line-char:%d){: .scope-hunter .small}
'''

APPEARANCE_HEADER = '\n## Appearance\n'
COLOR_BOX = '''
**%s:**{: .keyword} %s&nbsp;%s
[(copy)](%s:%d){: .scope-hunter .small}
'''
FONT_STYLE = '''
**style:**{: .keyword} <%(tag)s>%(type)s</%(tag)s>
[(copy)](copy-style:%(index)d){: .scope-hunter .small}
'''

SELECTOR_HEADER = '\n## Selectors\n'
FG_NAME = '''
**fg name:**{: .keyword} %s
[(copy)](copy-fg-sel-name:%d){: .scope-hunter .small}
'''
FG_SCOPE = '''
**fg scope:**{: .keyword} %s
[(copy)](copy-fg-sel-scope:%d){: .scope-hunter .small}
'''
BG_NAME = '''
**bg name:**{: .keyword} %s
[(copy)](copy-bg-sel-name:%d){: .scope-hunter .small}
'''
BG_SCOPE = '''
**bg scope:**{: .keyword} %s
[(copy)](copy-bg-sel-scope:%d){: .scope-hunter .small}
'''
BOLD_NAME = '''
**bold name:**{: .keyword} %s
[(copy)](copy-bold-sel-name:%d){: .scope-hunter .small}
'''
BOLD_SCOPE = '''
**bold scope:**{: .keyword} %s
[(copy)](copy-bold-sel-scope:%d){: .scope-hunter .small}
'''
ITALIC_NAME = '''
**italic name:**{: .keyword} %s
[(copy)](copy-italic-sel-name:%d){: .scope-hunter .small}
'''
ITALIC_SCOPE = '''
**italic scope:**{: .keyword} %s
[(copy)](copy-italic-sel-scope:%d){: .scope-hunter .small}
'''

FILE_HEADER = '\n## Files\n'
SCHEME_FILE = '''
**scheme:**{: .keyword} [%s](scheme)
[(copy)](copy-scheme:%d){: .scope-hunter .small}
'''
SYNTAX_FILE = '''
**syntax:**{: .keyword} [%s](syntax)
[(copy)](copy-syntax:%d){: .scope-hunter .small}
'''

COPY_ALL = '''
---

[(copy all)](copy-all){: .scope-hunter .small}
'''

# Text Entry
ENTRY = "%-30s %s"
SCOPE_KEY = "Scope"
PTS_KEY = "Scope Extents (Pts)"
PTS_VALUE = "(%d, %d)"
CHAR_LINE_KEY = "Scope Extents (Line/Char)"
CHAR_LINE_VALUE = "(line: %d char: %d, line: %d char: %d)"
FG_KEY = "Fg"
FG_SIM_KEY = "Fg (Simulated Alpha)"
BG_KEY = "Bg"
BG_SIM_KEY = "Bg (Simulated Alpha)"
STYLE_KEY = "Style"
FG_NAME_KEY = "Fg Name"
FG_SCOPE_KEY = "Fg Scope"
BG_NAME_KEY = "Bg Name"
BG_SCOPE_KEY = "Bg Scope"
BOLD_NAME_KEY = "Bold Name"
BOLD_SCOPE_KEY = "Bold Scope"
ITALIC_NAME_KEY = "Italic Name"
ITALIC_SCOPE_KEY = "Italic Scope"
SCHEME_KEY = "Scheme File"
SYNTAX_KEY = "Syntax File"


def log(msg):
    """Logging."""
    print("ScopeHunter: %s" % msg)


def debug(msg):
    """Debug."""
    if sh_settings.get('debug', False):
        log(msg)


def extent_style(option):
    """Configure style of region based on option."""

    style = sublime.HIDE_ON_MINIMAP
    if option == "outline":
        style |= sublime.DRAW_NO_FILL
    elif option == "none":
        style |= sublime.HIDDEN
    elif option == "underline":
        style |= sublime.DRAW_EMPTY_AS_OVERWRITE
    elif option == "thin_underline":
        style |= sublime.DRAW_NO_FILL
        style |= sublime.DRAW_NO_OUTLINE
        style |= sublime.DRAW_SOLID_UNDERLINE
    elif option == "squiggly":
        style |= sublime.DRAW_NO_FILL
        style |= sublime.DRAW_NO_OUTLINE
        style |= sublime.DRAW_SQUIGGLY_UNDERLINE
    elif option == "stippled":
        style |= sublime.DRAW_NO_FILL
        style |= sublime.DRAW_NO_OUTLINE
        style |= sublime.DRAW_STIPPLED_UNDERLINE
    return style


def underline(regions):
    """Convert to empty regions."""

    new_regions = []
    for region in regions:
        start = region.begin()
        end = region.end()
        while start < end:
            new_regions.append(sublime.Region(start))
            start += 1
    return new_regions


def copy_data(bfr, label, index, copy_format=None):
    """Copy data to clipboard from buffer."""

    line = bfr[index]
    if line.startswith(label + ':'):
        text = line.replace(label + ':', '', 1).strip()
        if copy_format is not None:
            text = copy_format(text)
        sublime.set_clipboard(text)
        notify("Copied: %s" % label)


def get_color_box(color, caption, link, index):
    """Display an HTML color box using the given color."""

    border = '#CCCCCC'
    border2 = '#333333'
    return (
        COLOR_BOX % (
            caption,
            mdpopups.color_box([color], border, border2, height=18, width=18, border_size=2),
            color.upper(),
            link,
            index
        )
    )


class ScopeHunterEditCommand(sublime_plugin.TextCommand):
    """Edit a view."""

    bfr = None
    pt = None

    def run(self, edit):
        """Insert text into buffer."""

        cls = ScopeHunterEditCommand
        self.view.insert(edit, cls.pt, cls.bfr)

    @classmethod
    def clear(cls):
        """Clear edit buffer."""

        cls.bfr = None
        cls.pt = None


class GetSelectionScope(object):
    """Get the scope and the selection(s)."""

    def next_index(self):
        """Get next index into scope buffer."""

        self.index += 1
        return self.index

    def get_extents(self, pt):
        """Get the scope extent via the sublime API."""

        pts = None
        file_end = self.view.size()
        scope_name = self.view.scope_name(pt)
        for r in self.view.find_by_selector(scope_name):
            if r.contains(pt):
                pts = r
                break
            elif pt == file_end and r.end() == pt:
                pts = r
                break

        if pts is None:
            pts = sublime.Region(pt)

        row1, col1 = self.view.rowcol(pts.begin())
        row2, col2 = self.view.rowcol(pts.end())

        # Scale back the extent by one for true points included
        if pts.size() < self.highlight_max_size:
            self.extents.append(sublime.Region(pts.begin(), pts.end()))

        if self.points_info or self.rowcol_info:
            if self.points_info:
                self.scope_bfr.append(ENTRY % (PTS_KEY + ':', PTS_VALUE % (pts.begin(), pts.end())))
            if self.rowcol_info:
                self.scope_bfr.append(
                    ENTRY % (CHAR_LINE_KEY + ':', CHAR_LINE_VALUE % (row1 + 1, col1 + 1, row2 + 1, col2 + 1))
                )

            if self.show_popup:
                self.scope_bfr_tool.append(SCOPE_EXTENT_HEADER)
                if self.points_info:
                    self.scope_bfr_tool.append(PTS % (pts.begin(), pts.end(), self.next_index()))
                if self.rowcol_info:
                    self.scope_bfr_tool.append(CHAR_LINE % (row1 + 1, col1 + 1, row2 + 1, col2 + 1, self.next_index()))

    def get_scope(self, pt):
        """Get the scope at the cursor."""

        scope = self.view.scope_name(pt)
        spacing = "\n" + (" " * 31)

        if self.clipboard:
            self.clips.append(scope)

        if self.first and self.show_statusbar:
            self.status = scope
            self.first = False

        # self.scope_bfr.append(ENTRY % (SCOPE_KEY + ':', self.view.scope_name(pt).strip().replace(" ", spacing)))
        self.scope_bfr.append(self.view.scope_name(pt))

        if self.show_popup:
            self.scope_bfr_tool.append(SCOPE_HEADER)
            self.scope_bfr_tool.append(SCOPES % (self.view.scope_name(pt).strip(), self.next_index()))

        return scope

    def get_appearance(self, color, color_sim, bgcolor, bgcolor_sim, style):
        """Get colors of foreground, background, and simulated transparency colors."""

        self.scope_bfr.append(ENTRY % (FG_KEY + ":", color))
        if self.show_simulated and len(color) == 9 and not color.lower().endswith('ff'):
            self.scope_bfr.append(ENTRY % (FG_SIM_KEY + ":", color_sim))

        self.scope_bfr.append(ENTRY % (BG_KEY + ":", bgcolor))
        if self.show_simulated and len(bgcolor) == 9 and not bgcolor.lower().endswith('ff'):
            self.scope_bfr.append(ENTRY % (BG_SIM_KEY + ":", bgcolor_sim))

        self.scope_bfr.append(ENTRY % (STYLE_KEY + ":", style))

        if self.show_popup:
            self.scope_bfr_tool.append(APPEARANCE_HEADER)
            self.scope_bfr_tool.append(get_color_box(color, 'fg', 'copy-fg', self.next_index()))
            if self.show_simulated and len(color) == 9 and not color.lower().endswith('ff'):
                self.scope_bfr_tool.append(
                    get_color_box(color_sim, 'fg (simulated alpha)', 'copy-fg-sim', self.next_index())
                )
            self.scope_bfr_tool.append(get_color_box(bgcolor, 'bg', 'copy-bg', self.next_index()))
            if self.show_simulated and len(bgcolor) == 9 and not bgcolor.lower().endswith('ff'):
                self.scope_bfr_tool.append(
                    get_color_box(bgcolor_sim, 'bg (simulated alpha)', 'copy-bg-sim', self.next_index())
                )

            if style == "bold":
                tag = "b"
            elif style == "italic":
                tag = "i"
            elif style == "underline":
                tag = "u"
            else:
                tag = "span"
            self.scope_bfr_tool.append(FONT_STYLE % {"type": style, "tag": tag, "index": self.next_index()})

    def get_scheme_syntax(self):
        """Get color scheme and syntax file path."""

        self.scheme_file = scheme_matcher.color_scheme.replace('\\', '/')
        self.syntax_file = self.view.settings().get('syntax')
        self.scope_bfr.append(ENTRY % (SCHEME_KEY + ":", self.scheme_file))
        self.scope_bfr.append(ENTRY % (SYNTAX_KEY + ":", self.syntax_file))

        if self.show_popup:
            self.scope_bfr_tool.append(FILE_HEADER)
            self.scope_bfr_tool.append(SCHEME_FILE % (self.scheme_file, self.next_index()))
            self.scope_bfr_tool.append(SYNTAX_FILE % (self.syntax_file, self.next_index()))

    def get_selectors(self, color_selector, bg_selector, style_selectors):
        """Get the selectors used to determine color and/or style."""

        self.scope_bfr.append(ENTRY % (FG_NAME_KEY + ":", color_selector.name))
        self.scope_bfr.append(ENTRY % (FG_SCOPE_KEY + ":", color_selector.scope))
        self.scope_bfr.append(ENTRY % (BG_NAME_KEY + ":", bg_selector.name))
        self.scope_bfr.append(ENTRY % (BG_SCOPE_KEY + ":", bg_selector.scope))
        if style_selectors["bold"].name != "" or style_selectors["bold"].scope != "":
            self.scope_bfr.append(ENTRY % (BOLD_NAME_KEY + ":", style_selectors["bold"].name))
            self.scope_bfr.append(ENTRY % (BOLD_SCOPE_KEY + ":", style_selectors["bold"].scope))

        if style_selectors["italic"].name != "" or style_selectors["italic"].scope != "":
            self.scope_bfr.append(ENTRY % (ITALIC_NAME_KEY + ":", style_selectors["italic"].name))
            self.scope_bfr.append(ENTRY % (ITALIC_SCOPE_KEY + ":", style_selectors["italic"].scope))

        if self.show_popup:
            self.scope_bfr_tool.append(SELECTOR_HEADER)
            self.scope_bfr_tool.append(FG_NAME % (color_selector.name, self.next_index()))
            self.scope_bfr_tool.append(FG_SCOPE % (color_selector.scope, self.next_index()))
            self.scope_bfr_tool.append(BG_NAME % (bg_selector.name, self.next_index()))
            self.scope_bfr_tool.append(BG_SCOPE % (bg_selector.scope, self.next_index()))
            if style_selectors["bold"].name != "" or style_selectors["bold"].scope != "":
                self.scope_bfr_tool.append(BOLD_NAME % (style_selectors["bold"].name, self.next_index()))
                self.scope_bfr_tool.append(BOLD_SCOPE % (style_selectors["bold"].scope, self.next_index()))
            if style_selectors["italic"].name != "" or style_selectors["italic"].scope != "":
                self.scope_bfr_tool.append(ITALIC_NAME % (style_selectors["italic"].name, self.next_index()))
                self.scope_bfr_tool.append(ITALIC_SCOPE % (style_selectors["italic"].scope, self.next_index()))
            self.scope_bfr_tool.append('\n')

    def get_info(self, pt):
        """Get scope related info."""

        scope = self.get_scope(pt)

        if self.rowcol_info or self.points_info or self.highlight_extent:
            self.get_extents(pt)

        if (self.appearance_info or self.selector_info) and scheme_matcher is not None:
            try:
                match = scheme_matcher.guess_color(self.view, pt, scope)
                color = match.fg
                bgcolor = match.bg
                color_sim = match.fg_simulated
                bgcolor_sim = match.bg_simulated
                style = match.style
                bg_selector = match.bg_selector
                color_selector = match.fg_selector
                style_selectors = match.style_selectors

                if self.appearance_info:
                    self.get_appearance(color, color_sim, bgcolor, bgcolor_sim, style)

                if self.selector_info:
                    self.get_selectors(color_selector, bg_selector, style_selectors)
            except Exception:
                log("Evaluating theme failed!  Ignoring theme related info.")
                debug(str(traceback.format_exc()))
                error("Evaluating theme failed!")
                self.scheme_info = False

        if self.file_path_info and scheme_matcher:
            self.get_scheme_syntax()

        self.next_index()

    def on_navigate(self, href):
        """Exceute link callback."""

        params = href.split(':')
        key = params[0]
        index = int(params[1]) if len(params) > 1 else None
        if key == 'copy-all':
            sublime.set_clipboard('\n'.join(self.scope_bfr))
            notify('Copied: All')
        elif key == 'copy-scope':
            copy_data(
                self.scope_bfr,
                SCOPE_KEY,
                index,
                lambda x: x.replace('\n' + ' ' * 31, ' ')
            )
        elif key == 'copy-points':
            copy_data(self.scope_bfr, PTS_KEY, index)
        elif key == 'copy-line-char':
            copy_data(self.scope_bfr, CHAR_LINE_KEY, index)
        elif key == 'copy-fg':
            copy_data(self.scope_bfr, FG_KEY, index)
        elif key == 'copy-fg-sim':
            copy_data(self.scope_bfr, FG_SIM_KEY, index)
        elif key == 'copy-bg':
            copy_data(self.scope_bfr, BG_KEY, index)
        elif key == 'copy-bg-sim':
            copy_data(self.scope_bfr, BG_SIM_KEY, index)
        elif key == 'copy-style':
            copy_data(self.scope_bfr, STYLE_KEY, index)
        elif key == 'copy-fg-sel-name':
            copy_data(self.scope_bfr, FG_NAME_KEY, index)
        elif key == 'copy-fg-sel-scope':
            copy_data(self.scope_bfr, FG_SCOPE_KEY, index)
        elif key == 'copy-bg-sel-name':
            copy_data(self.scope_bfr, BG_NAME_KEY, index)
        elif key == 'copy-bg-sel-scope':
            copy_data(self.scope_bfr, BG_SCOPE_KEY, index)
        elif key == 'copy-bold-sel-name':
            copy_data(self.scope_bfr, BOLD_NAME_KEY, index)
        elif key == 'copy-bold-sel-scope':
            copy_data(self.scope_bfr, BOLD_SCOPE_KEY, index)
        elif key == 'copy-italic-sel-name':
            copy_data(self.scope_bfr, ITALIC_NAME_KEY, index)
        elif key == 'copy-italic-sel-scope':
            copy_data(self.scope_bfr, ITALIC_SCOPE_KEY, index)
        elif key == 'copy-scheme':
            copy_data(self.scope_bfr, SCHEME_KEY, index)
        elif key == 'copy-syntax':
            copy_data(self.scope_bfr, SYNTAX_KEY, index)
        elif key == 'scheme' and self.scheme_file is not None:
            window = self.view.window()
            window.run_command(
                'open_file',
                {
                    "file": "${packages}/%s" % self.scheme_file.replace(
                        '\\', '/'
                    ).replace('Packages/', '', 1)
                }
            )
        elif key == 'syntax' and self.syntax_file is not None:
            window = self.view.window()
            window.run_command(
                'open_file',
                {
                    "file": "${packages}/%s" % self.syntax_file.replace(
                        '\\', '/'
                    ).replace('Packages/', '', 1)
                }
            )

    def run(self, v):
        """Run ScopeHunter and display in the approriate way."""

        self.view = v
        self.window = self.view.window()
        view = self.window.get_output_panel('scope_viewer')
        self.scope_bfr = []
        self.scope_bfr_tool = []
        self.clips = []
        self.status = ""
        self.scheme_file = None
        self.syntax_file = None
        self.show_statusbar = bool(sh_settings.get("show_statusbar", False))
        self.show_panel = bool(sh_settings.get("show_panel", False))
        if TOOLTIP_SUPPORT:
            self.show_popup = bool(sh_settings.get("show_popup", False))
        else:
            self.show_popup = False
        self.clipboard = bool(sh_settings.get("clipboard", False))
        self.multiselect = bool(sh_settings.get("multiselect", False))
        self.console_log = bool(sh_settings.get("console_log", False))
        self.highlight_extent = bool(sh_settings.get("highlight_extent", False))
        self.highlight_scope = sh_settings.get("highlight_scope", 'invalid')
        self.highlight_style = sh_settings.get("highlight_style", 'outline')
        self.highlight_max_size = int(sh_settings.get("highlight_max_size", 100))
        self.rowcol_info = bool(sh_settings.get("extent_line_char", False))
        self.points_info = bool(sh_settings.get("extent_points", False))
        self.appearance_info = bool(sh_settings.get("styling", False))
        self.show_simulated = bool(sh_settings.get("show_simulated_alpha_colors", False))
        self.file_path_info = bool(sh_settings.get("file_paths", False))
        self.selector_info = bool(sh_settings.get("selectors", False))
        self.scheme_info = self.appearance_info or self.selector_info
        self.first = True
        self.extents = []

        # Get scope info for each selection wanted
        self.index = -1
        if len(self.view.sel()):
            if self.multiselect:
                count = 0
                for sel in self.view.sel():
                    if count > 0 and self.show_popup:
                        self.scope_bfr_tool.append('\n---\n')
                    self.get_info(sel.b)
                    count += 1
            else:
                self.get_info(self.view.sel()[0].b)

        # Copy scopes to clipboard
        if self.clipboard:
            sublime.set_clipboard('\n'.join(self.clips))

        # Display in status bar
        if self.show_statusbar:
            sublime.status_message(self.status)

        # Show panel
        if self.show_panel:
            ScopeHunterEditCommand.bfr = '\n'.join(self.scope_bfr)
            ScopeHunterEditCommand.pt = 0
            view.run_command('scope_hunter_edit')
            ScopeHunterEditCommand.clear()
            self.window.run_command("show_panel", {"panel": "output.scope_viewer"})

        if self.console_log:
            print('\n'.join(["Scope Hunter"] + self.scope_bfr))

        if self.highlight_extent:
            style = extent_style(self.highlight_style)
            if style == 'underline':
                self.extents = underline(self.extents)
            self.view.add_regions(
                'scope_hunter',
                self.extents,
                self.highlight_scope,
                '',
                style
            )

        if self.show_popup:
            if self.scheme_info or self.rowcol_info or self.points_info or self.file_path_info:
                tail = COPY_ALL
            else:
                tail = ''
            md = mdpopups.md2html(self.view, ''.join(self.scope_bfr_tool) + tail)
            mdpopups.show_popup(
                self.view,
                '<div class="scope-hunter content">%s</div>' % md,
                css=ADD_CSS,
                max_width=500, on_navigate=self.on_navigate
            )

get_selection_scopes = GetSelectionScope()


class GetSelectionScopeCommand(sublime_plugin.TextCommand):
    """Command to get the selection(s) scope."""

    def run(self, edit):
        """On demand scope request."""

        sh_thread.modified = True

    def is_enabled(self):
        """Check if we should scope this view."""

        return sh_thread.is_enabled(self.view)


class ToggleSelectionScopeCommand(sublime_plugin.ApplicationCommand):
    """Command to toggle instant scoper."""

    def run(self):
        """Enable or disable instant scoper."""

        sh_thread.instant_scoper = False if sh_thread.instant_scoper else True
        if sh_thread.instant_scoper:
            sh_thread.modified = True
            sh_thread.time = time()
        else:
            win = sublime.active_window()
            if win is not None:
                view = win.get_output_panel('scope_viewer')
                parent_win = view.window()
                if parent_win:
                    parent_win.run_command('hide_panel', {'cancel': True})
                view = win.active_view()
                if view is not None and TOOLTIP_SUPPORT:
                    mdpopups.hide_popup(view)
                if (
                    view is not None and
                    sh_thread.is_enabled(view) and
                    bool(sh_settings.get("highlight_extent", False)) and
                    len(view.get_regions("scope_hunter"))
                ):
                    view.erase_regions("scope_hunter")


class SelectionScopeListener(sublime_plugin.EventListener):
    """Listern for instant scoping."""

    def clear_regions(self, view):
        """Clear the highlight regions."""

        if (
            bool(sh_settings.get("highlight_extent", False)) and
            len(view.get_regions("scope_hunter"))
        ):
            view.erase_regions("scope_hunter")

    def on_selection_modified(self, view):
        """Clean up regions or let thread know there was a modification."""

        enabled = sh_thread.is_enabled(view)
        if not sh_thread.instant_scoper or not enabled:
            # clean up dirty highlights
            if enabled:
                self.clear_regions(view)
        else:
            sh_thread.modified = True
            sh_thread.time = time()

    def on_activated(self, view):
        """Check color scheme on activated and update if needed."""

        if not view.settings().get('is_widget', False):
            scheme = view.settings().get("color_scheme")
            if scheme is None:
                pref_settings = sublime.load_settings('Preferences.sublime-settings')
                scheme = pref_settings.get('color_scheme')

            if scheme_matcher is not None and scheme is not None:
                if scheme != scheme_matcher.scheme_file:
                    reinit_plugin()


class ShThread(threading.Thread):
    """Load up defaults."""

    def __init__(self):
        """Setup the thread."""
        self.reset()
        threading.Thread.__init__(self)

    def reset(self):
        """Reset the thread variables."""
        self.wait_time = 0.12
        self.time = time()
        self.modified = False
        self.ignore_all = False
        self.instant_scoper = False
        self.abort = False

    def payload(self):
        """Code to run."""
        # Ignore selection inside the routine
        self.modified = False
        self.ignore_all = True
        window = sublime.active_window()
        view = None if window is None else window.active_view()
        if view is not None:
            get_selection_scopes.run(view)
        self.ignore_all = False
        self.time = time()

    def is_enabled(self, view):
        """Check if we can execute."""
        return not view.settings().get("is_widget") and not self.ignore_all

    def kill(self):
        """Kill thread."""
        self.abort = True
        while self.is_alive():
            pass
        self.reset()

    def run(self):
        """Thread loop."""
        while not self.abort:
            if not self.ignore_all:
                if (
                    self.modified is True and
                    time() - self.time > self.wait_time
                ):
                    sublime.set_timeout(self.payload, 0)
            sleep(0.5)


def init_color_scheme():
    """Setup color scheme match object with current scheme."""

    global scheme_matcher
    scheme_file = None

    # Attempt syntax specific from view
    window = sublime.active_window()
    if window is not None:
        view = window.active_view()
        if view is not None:
            scheme_file = view.settings().get('color_scheme', None)

    # Get global scheme
    if scheme_file is None:
        pref_settings = sublime.load_settings('Preferences.sublime-settings')
        scheme_file = pref_settings.get('color_scheme')

    try:
        scheme_matcher = ColorSchemeMatcher(scheme_file)
    except Exception:
        scheme_matcher = None
        log("Theme parsing failed!  Ignoring theme related info.")
        debug(str(traceback.format_exc()))


def reinit_plugin():
    """Relaod scheme object and tooltip theme."""

    init_color_scheme()


def init_plugin():
    """Setup plugin variables and objects."""

    global sh_thread
    global sh_settings

    # Preferences Settings
    pref_settings = sublime.load_settings('Preferences.sublime-settings')

    # Setup settings
    sh_settings = sublime.load_settings('scope_hunter.sublime-settings')

    # Setup color scheme
    init_color_scheme()

    pref_settings.clear_on_change('scopehunter_reload')
    pref_settings.add_on_change('scopehunter_reload', reinit_plugin)

    sh_settings.clear_on_change('reload')

    # Setup thread
    if sh_thread is not None:
        # This shouldn't be needed, but just in case
        sh_thread.kill()
    sh_thread = ShThread()
    sh_thread.start()


def plugin_loaded():
    """Setup plugin."""

    init_plugin()


def plugin_unloaded():
    """Kill the thead."""

    sh_thread.kill()
