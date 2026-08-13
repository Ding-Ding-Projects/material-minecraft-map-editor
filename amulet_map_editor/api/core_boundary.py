"""The core/wx boundary.

This module names the part of ``amulet_map_editor.api`` that does not import
``wx`` -- directly or transitively -- and is therefore already portable to a
non-wx runtime (a Node/Electron sidecar, a headless test process, or any other
host that does not carry a wxPython dependency).

The list below is HAND-WRITTEN on purpose, not discovered by scanning the
package tree. A module gaining a wx import by accident must make the boundary
test fail; a module that is *not* on this list is simply outside the
boundary's promise, whether or not it happens to be wx-free today. Discovery
would silently grow or shrink the boundary every time someone adds a file;
this list only changes when a person decides it should.

See ``tests/test_core_boundary.py`` for the enforcement test and
``docs/features/core-boundary/README.md`` for the article explaining why this
boundary exists and how to add a module to it.
"""

from __future__ import annotations

# Dotted module names, relative to nothing (fully qualified), that must never
# import wx -- directly or by importing something else that does. Each entry
# was verified by importing it in a subprocess with wx removed from
# sys.modules and blocked from being imported again.
PORTABLE_CORE_MODULES: tuple[str, ...] = (
    "amulet_map_editor.api.appearance_editor",
    "amulet_map_editor.api.appearance_presets",
    "amulet_map_editor.api.app_logo",
    "amulet_map_editor.api.changelog",
    "amulet_map_editor.api.colour",
    "amulet_map_editor.api.config",
    "amulet_map_editor.api.converter",
    "amulet_map_editor.api.converter.adapters",
    "amulet_map_editor.api.converter.core",
    "amulet_map_editor.api.converter.registry",
    "amulet_map_editor.api.converter.sandbox",
    "amulet_map_editor.api.converter.signatures",
    "amulet_map_editor.api.datatypes",
    "amulet_map_editor.api.dim_sum_surprise",
    "amulet_map_editor.api.docs_browser",
    "amulet_map_editor.api.dpi",
    "amulet_map_editor.api.export_actions",
    "amulet_map_editor.api.external_editor",
    "amulet_map_editor.api.credential_vault",
    "amulet_map_editor.api.lang",
    "amulet_map_editor.api.item_locks",
    "amulet_map_editor.api.authenticator",
    "amulet_map_editor.api.local_history",
    "amulet_map_editor.api.material_menu",
    "amulet_map_editor.api.notifications",
    "amulet_map_editor.api.notification_copy",
    "amulet_map_editor.api.outcome",
    "amulet_map_editor.api.preferences",
    "amulet_map_editor.api.process",
    "amulet_map_editor.api.progress",
    "amulet_map_editor.api.regex_builder",
    "amulet_map_editor.api.scheduled_refresh",
    "amulet_map_editor.api.scheduled_runtime",
    "amulet_map_editor.api.scheduled_settings",
    "amulet_map_editor.api.scheduled_sources",
    "amulet_map_editor.api.school_mode",
    "amulet_map_editor.api.sidecar",
    "amulet_map_editor.api.sidecar.methods",
    "amulet_map_editor.api.sidecar.protocol",
    "amulet_map_editor.api.sidecar.server",
    "amulet_map_editor.api.startup_diagnostics",
    "amulet_map_editor.api.tab_groups",
    "amulet_map_editor.api.text_overlay",
    "amulet_map_editor.api.tts_narrator",
)

# Modules that were checked and found NOT (yet) portable, with the reason.
# Keeping this list beside the portable one means the next person does not
# have to rediscover why a plausible-looking module is missing above.
KNOWN_NOT_PORTABLE: dict[str, str] = {
    "amulet_map_editor.api.forge_accounts": (
        "imports wx directly at module scope to define ForgeAccountsDialog "
        "(wx.Dialog) alongside its account-list data model. The credential "
        "vault it used to own now lives in "
        "amulet_map_editor.api.credential_vault, which imports no toolkit, so "
        "nothing that must run without wx has to reach through this module "
        "any more."
    ),
    "amulet_map_editor.api.resources": (
        "imports amulet_map_editor.api.image, whose __init__ imports wx to "
        "build wx.Bitmap/wx.Image objects from bundled PNG data."
    ),
}
