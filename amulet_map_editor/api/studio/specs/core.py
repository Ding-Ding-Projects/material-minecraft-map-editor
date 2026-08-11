"""Core Amulet Studio surfaces: history, pickers, progress, and legal windows.

These are the surfaces that are not tied to one editing tool -- the project
history browser, the block/biome/version pickers, the appearance editors, the
tab manager, the documentation reader, the progress and safety windows, and the
small informational windows such as the licence list.  They live here as data so
that :mod:`amulet_map_editor.api.studio.spec_dialog` can render each one without
a bespoke window class, and so that the text a user reads can be reviewed in a
single place rather than scattered across two dozen dialogs.
"""

from __future__ import annotations

from typing import Callable, Dict, List

from amulet_map_editor.api.studio import keys as studio_keys
from amulet_map_editor.api.studio.spec import (
    Action,
    Check,
    Commit,
    Field,
    RangeDef,
    Row,
    Section,
    Select,
    Spec,
    SwatchDef,
    TreeNode,
    sec,
    tex_section,
)

#: The sample article rendered inside the offline documentation reader.  It is
#: kept as one literal so the line breaks the reader shows are the line breaks
#: written here, rather than something a formatter decided.
_DOCS_ARTICLE = (
    "# Open a world\n"
    "\n"
    "Amulet opens Minecraft worlds outside the game so that you can inspect\n"
    "terrain, select precise regions, move builds between worlds, run block and\n"
    "biome operations, import or export structures, delete or regenerate chunks,\n"
    "and convert world data.\n"
    "\n"
    "Back up every world before editing it."
)

#: The target line shown at the top of the per-element appearance editor.
_APPEARANCE_TARGET = (
    "element: ribbon/home/clipboard/paste\n" "role:    primary-container"
)


def _controls_spec() -> Spec:
    """Build the Key Select surface from the key group the editor listens to.

    **Every key on this surface is read, never written down.**  It had been
    transcribed from the design instead, and the design and the editor did not
    agree: measured against the shipped key group, this window offered ``MMB``
    for "Rotate Camera" (really ``RMB``), ``Ctrl+Scroll`` for both selection
    distance rows (really ``R`` and ``F``), ``Esc`` for "Deselect Active Box"
    (really ``Ctrl+D``), ``RMB`` for "Inspect Block" (really ``Alt``) and ``P``
    for "Toggle Projection" (really ``Tab``).  Six wrong keys in the one window
    a user opens *to learn the keys* -- and a user who had rebound any of them
    was being taught the shipped default on top of that.

    The rows are the editor's own action list in the editor's own order, so an
    action the editor gains appears here without anybody editing this file, and
    the active group is named rather than assumed: the keys below belong to one
    group, and saying which one is what makes them checkable.

    A configuration that cannot be read produces a section that says so.  An
    empty grid would read as a window that failed to load, and the shipped
    default would be exactly the key a user who rebound it no longer presses.
    """
    groups = studio_keys.read_key_groups()
    bindings = studio_keys.editor_bindings()

    if bindings:
        binding_section: Section = sec("Bindings", "keys", keys=list(bindings))
    else:
        binding_section = sec(
            "Bindings",
            "note",
            hint=(
                "The 3D editor's key configuration could not be read, so no key "
                "is listed here. Nothing is shown rather than the shipped "
                "defaults, which are exactly the keys somebody who rebound them "
                "no longer presses."
            ),
        )

    options = groups.ids or ((groups.active,) if groups.active else ())
    group_section = sec(
        "Key group",
        "selects",
        selects=[
            Select("Active group", tuple(options), groups.active),
            Select("Action set", ("3D editor", "Selection", "Camera")),
        ],
    )

    sections: List[Section] = [group_section, binding_section]
    if groups.active:
        sections.append(
            sec(
                "",
                "note",
                hint=(
                    f"Read from the 3D editor's active key group "
                    f"“{groups.active}”. Every key above is the key that group "
                    "is bound to right now, not a shipped default."
                ),
            )
        )

    return Spec(
        key="controls",
        eyebrow="Key configuration",
        title="Key Select",
        width=720,
        confirm="Save group",
        intro=(
            "Press the key you want assigned to an action. The active key group is "
            "not editable; editing offers to create a new group."
        ),
        sections=tuple(sections),
        actions=(
            Action("New group", "tonal"),
            Action("Reset group", "outlined"),
        ),
    )


#: Surfaces in this family that are rebuilt on every open rather than served
#: from the import-time snapshot below.  The Key Select window reads the user's
#: live key group, and a key group changed during a session must not leave the
#: window teaching the keys it was opened with the first time.
REBUILDERS: Dict[str, Callable[[], Spec]] = {"controls": _controls_spec}


SPECS: Dict[str, Spec] = {
    "history": Spec(
        key="history",
        eyebrow="Local Git repository",
        title="Project history",
        width=760,
        confirm="Close",
        intro=(
            "Every project owns an isolated Git repository beside its world data, "
            "so undo depth is unlimited. Restoring writes a new revision instead of "
            "rewinding, which keeps the state you restored from undoable."
        ),
        sections=(
            sec("", "search", hint="Search commit messages, chunks, and coordinates"),
            sec(
                "Repository",
                "list",
                rows=[
                    Row(
                        "Repository path",
                        "%LOCALAPPDATA%\\Amulet\\projects\\1-17-height\\.git",
                        "isolated",
                    ),
                    Row("Branch", "amulet/main · no remote configured", "local"),
                    Row(
                        "Revisions",
                        "1,284 commits · unlimited undo depth",
                        "append-only",
                    ),
                    Row(
                        "Autocommit",
                        "One commit per applied operation, rename, or selection change",
                        "on",
                    ),
                ],
            ),
            sec(
                "Revisions",
                "commits",
                commits=[
                    Commit(
                        "Fill selection with deepslate",
                        "a91f0c7 · 10 Aug 2026, 09:41 · 12 chunks",
                        head=True,
                    ),
                    Commit(
                        "Move box 1 to -2, 98, -49",
                        "5d3e118 · 10 Aug 2026, 09:22 · 1 box",
                    ),
                    Commit(
                        "Paste spawn arch structure",
                        "c72ba40 · 10 Aug 2026, 08:58 · 384 blocks",
                    ),
                    Commit(
                        "Delete unselected chunks",
                        "1e6f9d2 · 09 Aug 2026, 21:14 · 96 chunks",
                    ),
                    Commit(
                        "Import Debug 1.14 chunk backup",
                        "7ab4c05 · 09 Aug 2026, 20:02 · 48 chunks",
                    ),
                    Commit(
                        "Initial project commit",
                        "0004aa1 · 09 Aug 2026, 19:40 · world snapshot",
                    ),
                ],
            ),
        ),
        actions=(
            Action("Restore selected", "tonal"),
            Action("Compare with working tree", "outlined"),
            Action("Export patch", "outlined"),
            Action("Open repository in VS Code", "outlined"),
        ),
    ),
    "controls": _controls_spec(),
    "goto": Spec(
        key="goto",
        eyebrow="Camera",
        title="Teleport",
        width=460,
        confirm="Go to location",
        intro=(
            "Type a coordinate to go to the location. Ctrl+C copies the coordinate; "
            "Ctrl+V pastes three numbers separated with spaces or commas."
        ),
        sections=(
            sec(
                "Coordinates",
                "fields",
                fields=[
                    Field("x:", "66.40"),
                    Field("y:", "118.13"),
                    Field("z:", "-43.12"),
                ],
            ),
        ),
        actions=(
            Action("Copy", "outlined"),
            Action("Paste", "outlined"),
        ),
    ),
    "nbtLegacy": Spec(
        key="nbtLegacy",
        eyebrow="Raw data",
        title="NBT editor",
        width=720,
        confirm="Commit changes",
        intro=(
            "Edit the raw tag tree for the inspected block entity. Right-click a node "
            "to add, rename, retype, or delete a tag."
        ),
        sections=(
            sec(
                "Tag tree",
                "tree",
                tree=[
                    TreeNode("▾", 'Compound  ""'),
                    TreeNode("▾", "  Compound  Chest"),
                    TreeNode("·", '    String   id = "minecraft:chest"'),
                    TreeNode("·", "    Int      x = -2"),
                    TreeNode("·", "    Int      y = 98"),
                    TreeNode("·", "    Int      z = -49"),
                    TreeNode("▾", "    List     Items (2)", selected=True),
                    TreeNode("·", "      Compound [0] minecraft:oak_planks x32"),
                    TreeNode("·", "      Compound [1] minecraft:torch x8"),
                ],
            ),
            sec(
                "Selected tag",
                "fields",
                fields=[
                    Field("Name", "Items"),
                    Field("Value", "2 entries"),
                ],
            ),
            sec(
                "Tag type",
                "chips",
                chips=[
                    "Byte",
                    "Short",
                    "Int",
                    "Long",
                    "Float",
                    "Double",
                    "String",
                    "List",
                    "Compound",
                    "Byte Array",
                    "Int Array",
                    "Long Array",
                ],
            ),
        ),
        actions=(
            Action("Add tag", "tonal"),
            Action("Delete tag", "danger"),
        ),
    ),
    "blockSelect": Spec(
        key="blockSelect",
        eyebrow="Block picker",
        title="Select block",
        width=720,
        confirm="Use this block",
        intro=(
            "Pick a namespace, base name, and block-state properties. Multi-block "
            "definitions accept several entries for replace operations."
        ),
        sections=(
            sec("", "search", hint="Search block names"),
            sec(
                "Identity",
                "selects",
                selects=[
                    Select("Platform and version", ("bedrock 1.17.0.1", "java 1.20.4")),
                    Select("Namespace", ("minecraft", "amulet")),
                ],
            ),
            sec(
                "Blocks",
                "list",
                rows=[
                    Row("minecraft:stone", "No properties", "1"),
                    Row("minecraft:deepslate", "axis=y", "3"),
                    Row("minecraft:oak_log", "axis=y", "3"),
                    Row("minecraft:water", "liquid_depth=0", "16"),
                ],
            ),
            tex_section(
                "minecraft:deepslate",
                "blockpicker-texture",
                "The picked block's texture shows here, with its top, side, and "
                "bottom faces. Tiles are generated placeholders until an install or "
                "resource pack is loaded.",
            ),
            sec(
                "Properties",
                "fields",
                fields=[
                    Field("axis", "y"),
                    Field("waterlogged", "false"),
                ],
            ),
        ),
        actions=(Action("Add to multi-block set", "tonal"),),
    ),
    "biomeSelect": Spec(
        key="biomeSelect",
        eyebrow="Biome picker",
        title="Select biome",
        width=620,
        confirm="Use this biome",
        sections=(
            sec("", "search", hint="Search biome names"),
            sec(
                "Biomes",
                "list",
                rows=[
                    Row("minecraft:plains", "Temperate · overworld", "1"),
                    Row("minecraft:dark_forest", "Temperate · overworld", "29"),
                    Row("minecraft:warm_ocean", "Aquatic · overworld", "44"),
                    Row("minecraft:nether_wastes", "Nether", "8"),
                ],
            ),
        ),
        actions=(),
    ),
    "versionSelect": Spec(
        key="versionSelect",
        eyebrow="Platform",
        title="Select version",
        width=560,
        confirm="Use this version",
        intro=(
            "Structure handlers and translations resolve against the selected "
            "platform and data version."
        ),
        sections=(
            sec(
                "Version",
                "selects",
                selects=[
                    Select("Platform", ("java", "bedrock", "universal")),
                    Select(
                        "Data version",
                        ("1.17.0.1", "1.16.0.51.1", "1.20.4", "1.12.2"),
                    ),
                ],
            ),
            sec(
                "Options",
                "checks",
                checks=[
                    Check(
                        "Force blockstate format",
                        "Use numerical ids only when the platform requires them.",
                    ),
                ],
            ),
        ),
        actions=(),
    ),
    "elementAppearance": Spec(
        key="elementAppearance",
        eyebrow="Per-element appearance",
        title="Edit appearance",
        width=640,
        confirm="Apply appearance",
        intro=(
            "Portable Material 3 roles are editable here. Italic, underline, and "
            "strikethrough apply live. Letter spacing is retained for backends that "
            "support it; this backend reports it as capability-limited. Unsupported "
            "axes are not silently saved."
        ),
        sections=(
            sec("Target", "code", code=_APPEARANCE_TARGET),
            sec(
                "Roles",
                "swatches",
                hint="#006A63 · contrast 7.1:1",
                swatches=[
                    SwatchDef("Primary", "#006A63"),
                    SwatchDef("Primary container", "#A6F2E9"),
                    SwatchDef("Surface container", "#E1EAE8"),
                    SwatchDef("Error", "#BA1A1A"),
                ],
            ),
            sec(
                "Type",
                "selects",
                selects=[
                    Select("Font weight", ("normal", "medium", "bold")),
                    Select("Font family", ("IBM Plex Sans", "Segoe UI", "Consolas")),
                ],
            ),
            sec(
                "Decoration",
                "checks",
                checks=[
                    Check("Italic", "Applies live"),
                    Check("Underline", "Applies live"),
                    Check("Strikethrough", "Applies live"),
                ],
            ),
            sec(
                "Metrics",
                "ranges",
                ranges=[
                    RangeDef("Corner radius", 12, 4, 32),
                    RangeDef("Font scale", 100, 80, 130),
                    RangeDef("Letter spacing", 0, 0, 4),
                ],
            ),
        ),
        actions=(
            Action("Reset this element", "danger"),
            Action("Save as named theme", "tonal"),
        ),
    ),
    "presets": Spec(
        key="presets",
        eyebrow="Versioned interchange",
        title="Appearance presets",
        width=720,
        confirm="Load selected",
        intro=(
            "Named presets carry theme, density, accent, UI font, and UI scale. "
            "Export and import use strict versioned JSON; malformed payloads fail "
            "closed."
        ),
        sections=(
            sec("", "search", hint="Filter presets"),
            sec(
                "Presets",
                "list",
                rows=[
                    Row(
                        "Studio dark · v3",
                        "dark · comfortable · #82D5CC · 100%",
                        "active",
                    ),
                    Row(
                        "Classroom light · v2",
                        "light · spacious · #006A63 · 120%",
                        "stored",
                    ),
                    Row(
                        "Compact review · v1",
                        "light · compact · #006A63 · 90%",
                        "stored",
                    ),
                ],
            ),
            sec(
                "Staged reset",
                "selects",
                selects=[
                    Select(
                        "Property",
                        ("Theme", "Density", "Accent colour", "UI font", "UI scale"),
                    ),
                    Select(
                        "Scope",
                        (
                            "Selected property",
                            "Appearance only",
                            "All preferences",
                        ),
                    ),
                ],
            ),
        ),
        actions=(
            Action("Save preset", "tonal"),
            Action("Update selected", "outlined"),
            Action("Export selected…", "outlined"),
            Action("Import preset…", "outlined"),
            Action("Open export in VS Code", "outlined"),
            Action("Delete selected", "danger"),
        ),
    ),
    "tabManager": Spec(
        key="tabManager",
        eyebrow="Workspace navigation",
        title="Tabs, groups, and safe closing",
        width=820,
        confirm="Activate selected",
        intro=(
            "Four independent searches cover this strip, group names, every tab, and "
            "the selected group. Bulk closing previews the exact visible-label match "
            "set before it is authorized."
        ),
        sections=(
            sec("Current strip search", "search", hint="Search this strip"),
            sec("Master tab search", "search", hint="Search every tab"),
            sec(
                "Open tabs",
                "list",
                rows=[
                    Row(
                        "1.17 Height",
                        "com.mojang\\minecraftWorlds\\8Dt6Xr5OAAA=",
                        "pinned",
                    ),
                    Row(
                        "Spawn rebuild",
                        "Documents\\Amulet\\spawn-rebuild",
                        "Survival worlds",
                    ),
                    Row("Debug 1.14", ".minecraft\\saves\\Debug 1_14", "no group"),
                ],
            ),
            sec(
                "Groups",
                "chips",
                chips=[
                    "No group",
                    "Survival worlds",
                    "Conversions",
                    "New group…",
                ],
            ),
            sec(
                "Strip edge",
                "selects",
                selects=[
                    Select("Tab strip edge", ("Top", "Bottom", "Left", "Right")),
                    Select("Group state", ("Expanded", "Collapsed")),
                ],
            ),
            sec(
                "Bulk close",
                "fields",
                fields=[
                    Field(
                        "Close tabs containing text",
                        "",
                        "Visible label text",
                    ),
                    Field(
                        "Close tabs not containing text",
                        "",
                        "Visible label text",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Enter one close query, then preview the exact visible-label "
                    "match set. Pinned tabs are included only after a preview."
                ),
            ),
        ),
        actions=(
            Action("Preview close set", "tonal"),
            Action("Authorize previewed close", "danger"),
        ),
    ),
    "docs": Spec(
        key="docs",
        eyebrow="Offline bundle",
        title="Documentation",
        width=820,
        confirm="Close",
        intro=(
            "The bundle is generated deterministically from every feature article. "
            "Search is literal first with an explicit bounded regex mode, and "
            "internal links resolve locally. Remote content is never fetched."
        ),
        sections=(
            sec("", "search", hint="Search articles and body text"),
            sec(
                "Articles",
                "list",
                rows=[
                    Row(
                        "Open a world",
                        "Discovery, backups, and platform support",
                        "read",
                    ),
                    Row(
                        "3D editor guide",
                        "Camera, selection boxes, and tools",
                        "read",
                    ),
                    Row(
                        "World conversion",
                        "Chunk merging and overwrite behaviour",
                        "read",
                    ),
                    Row(
                        "Offline history contract",
                        "Per-project Git repository and restore semantics",
                        "read",
                    ),
                    Row(
                        "Self-hosted runner contract",
                        "Live inventory and cloud fallback",
                        "read",
                    ),
                ],
            ),
            sec("Article", "code", code=_DOCS_ARTICLE),
        ),
        actions=(
            Action("Export article", "outlined"),
            Action("Open in VS Code", "outlined"),
        ),
    ),
    "languageSelect": Spec(
        key="languageSelect",
        eyebrow="Localization",
        title="Language Select",
        width=520,
        confirm="Use language",
        intro=(
            "Amulet loads en.lang first, then the language section, then any region "
            "file. Translation contributions are welcome."
        ),
        sections=(
            sec(
                "Available languages",
                "list",
                rows=[
                    Row("en", "English", "active"),
                    Row("en_GB", "English (United Kingdom)", ""),
                    Row("zh_TW", "繁體中文", ""),
                    Row("ja", "日本語", ""),
                    Row("de", "Deutsch", ""),
                    Row("fr", "Français", ""),
                    Row("pt_BR", "Português (Brasil)", ""),
                    Row("ru", "Русский", ""),
                ],
            ),
        ),
        actions=(Action("Contribute a translation", "outlined"),),
    ),
    "narrator": Spec(
        key="narrator",
        eyebrow="Optional speech",
        title="Narrator and voice",
        width=600,
        confirm="Save narrator settings",
        intro=(
            "The narrator is off by default and speaks only event announcements. "
            "English and Cantonese levels are independent."
        ),
        sections=(
            sec(
                "Narrator",
                "checks",
                checks=[
                    Check(
                        "Enable narrator",
                        "Off by default; announcements are queued and bounded.",
                    ),
                    Check(
                        "Announce operation results",
                        "Speaks after an operation returns.",
                    ),
                ],
            ),
            sec(
                "Voice",
                "selects",
                selects=[
                    Select("Narrator language", ("English", "Yue", "Both")),
                    Select("Backend", ("System speech", "Silent (log only)")),
                ],
            ),
            sec(
                "Levels",
                "ranges",
                ranges=[
                    RangeDef("English funny level", 1, 1, 5),
                    RangeDef("Cantonese funny level", 1, 1, 5),
                ],
            ),
        ),
        actions=(Action("Speak a test line", "tonal"),),
    ),
    "externalEditor": Spec(
        key="externalEditor",
        eyebrow="Safe bridge",
        title="External editor",
        width=620,
        confirm="Use this editor",
        intro=(
            "Discovered Visual Studio Code installations are validated before being "
            "persisted. Exported folders open as workspace roots."
        ),
        sections=(
            sec(
                "Discovered installations",
                "list",
                rows=[
                    Row(
                        "Visual Studio Code",
                        "%LOCALAPPDATA%\\Programs\\Microsoft VS Code\\Code.exe",
                        "validated",
                    ),
                    Row(
                        "VS Code Insiders",
                        "%LOCALAPPDATA%\\Programs\\Microsoft VS Code Insiders\\"
                        "Code - Insiders.exe",
                        "found",
                    ),
                ],
            ),
            sec(
                "Manual path",
                "fields",
                fields=[Field("Executable", "", "Browse for an executable")],
            ),
            sec(
                "",
                "note",
                hint=(
                    "The executable is validated on selection. An invalid path "
                    "reports an exact failure and is not saved."
                ),
            ),
        ),
        actions=(
            Action("Browse…", "outlined"),
            Action("Check editor", "tonal"),
            Action("Clear selection", "danger"),
        ),
    ),
    "schoolUnlock": Spec(
        key="schoolUnlock",
        eyebrow="Presentation lock",
        title="School mode",
        width=520,
        confirm="Unlock",
        intro=(
            "School mode enforces English-only serious presentation and removes "
            "inapplicable language settings. Unlocking verifies a salted local hash "
            "and restores the prior language and funny-level choices."
        ),
        sections=(
            sec(
                "Unlock",
                "fields",
                fields=[
                    Field("Unlock phrase", "", "Enter the local unlock phrase"),
                ],
            ),
            sec(
                "Locked settings",
                "list",
                rows=[
                    Row("Language mode", "Forced to English", "locked"),
                    Row("Funny levels", "Forced to 1", "locked"),
                    Row("Dialog emojis", "Disabled", "locked"),
                ],
            ),
        ),
        actions=(Action("Forget stored phrase", "danger"),),
    ),
    "confirm": Spec(
        key="confirm",
        eyebrow="Safety gate",
        title="Delete unselected chunks",
        width=520,
        confirm="Authorize",
        intro=(
            "This deletes every chunk outside the selection, including all data "
            "inside them. Minecraft recreates the chunks the next time the area "
            "loads."
        ),
        sections=(
            sec("Two-key gate", "keygate"),
            sec(
                "",
                "note",
                hint=(
                    "Hold both keys, then drag the slider through its full range. "
                    "The emergency exit stays available until the final "
                    "authorization."
                ),
            ),
        ),
        actions=(Action("Emergency exit", "outlined"),),
    ),
    "update": Spec(
        key="update",
        eyebrow="Windows delivery",
        title="Update status",
        width=620,
        confirm="Restart to install update",
        intro=(
            "The updater talks only to the project's exact immutable HTTPS release "
            "route. Packages are unsigned by design."
        ),
        sections=(
            sec(
                "Staged package",
                "list",
                rows=[
                    Row(
                        "0.10.0-dev.414",
                        "Setup.exe · RELEASES · Amulet-0.10.0-dev414-full.nupkg",
                        "ready",
                    ),
                    Row(
                        "Signature",
                        "NotSigned · code signing is prohibited by policy",
                        "unsigned",
                    ),
                    Row(
                        "Deadline",
                        "One 900-second deadline across apply and post-check",
                        "bounded",
                    ),
                ],
            ),
            sec(
                "Download",
                "progress",
                hint="Staging to the install root",
                progress_label="100%",
                progress_fraction=1.0,
            ),
        ),
        actions=(
            Action("Check for updates", "outlined"),
            Action("Release notes", "outlined", surface="changelog"),
            Action("Later", "outlined"),
        ),
    ),
    "loading": Spec(
        key="loading",
        eyebrow="Renderer",
        title="Please wait while the renderer loads",
        width=560,
        confirm="Run in background",
        sections=(
            sec(
                "Resource packs",
                "progress",
                hint="Downloading Bedrock vanilla resource pack",
                progress_label="62%",
                progress_fraction=0.62,
            ),
            sec(
                "Texture atlas",
                "progress",
                hint="Creating texture atlas",
                progress_label="18%",
                progress_fraction=0.18,
            ),
            sec(
                "Stages",
                "list",
                rows=[
                    Row(
                        "Loading resource packs",
                        "Vanilla plus any configured packs",
                        "done",
                    ),
                    Row("Creating texture atlas", "Packed per platform", "running"),
                    Row(
                        "Setting up renderer",
                        "OpenGL context and chunk generator",
                        "queued",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "If a resource-pack download fails, Amulet offers a retry and "
                    "reports the exact cause rather than continuing silently."
                ),
            ),
        ),
        actions=(Action("Retry download", "tonal"),),
    ),
    "convertProgress": Spec(
        key="convertProgress",
        eyebrow="World conversion",
        title="Converting world",
        width=600,
        confirm="Run in background",
        sections=(
            sec(
                "Progress",
                "progress",
                hint="Translating chunks into the destination world",
                progress_label="41%",
                progress_fraction=0.41,
            ),
            sec(
                "Job",
                "list",
                rows=[
                    Row("Input", "1.17 Height · bedrock 1.17.0.1", "source"),
                    Row(
                        "Output",
                        "1.12.2 Amulet Output · java 1.12.2",
                        "destination",
                    ),
                    Row(
                        "Overwrite",
                        "Destination chunks at matching coordinates are overwritten",
                        "warning",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "World conversion completed. You may need to teleport to the "
                    "correct location to see the converted chunks."
                ),
            ),
        ),
        actions=(Action("Cancel job", "danger"),),
    ),
    "operationOptions": Spec(
        key="operationOptions",
        eyebrow="Stock operation",
        title="Replace",
        width=640,
        confirm="Run operation",
        intro=(
            "Stock operations run inside the selection. The framework also loads "
            "project-specific Python extensions from the operations folder."
        ),
        sections=(
            sec(
                "Blocks",
                "list",
                rows=[
                    Row("Original block", "minecraft:stone", "pick"),
                    Row(
                        "Replacement block",
                        "minecraft:deepslate[axis=y]",
                        "pick",
                    ),
                ],
            ),
            sec(
                "Scope",
                "checks",
                checks=[
                    Check(
                        "Apply to every selection box",
                        "Unticked applies to the active box only.",
                    ),
                    Check("Skip air", "Leaves existing air untouched."),
                ],
            ),
            sec(
                "Stock operations",
                "chips",
                chips=["Clone", "Fill", "Replace", "Set Biome", "Waterlog"],
            ),
        ),
        actions=(
            Action("Reload plugins", "outlined"),
            Action("Open operations folder", "outlined"),
        ),
    ),
    "importChunks": Spec(
        key="importChunks",
        eyebrow="Chunk tool",
        title="Import chunks",
        width=600,
        confirm="Import into selection",
        intro=(
            "Replace the selected chunks with chunks from another world. Useful when "
            "restoring chunks from a backup."
        ),
        sections=(
            sec(
                "Source world",
                "list",
                rows=[
                    Row(
                        "Debug 1.14",
                        ".minecraft\\saves\\Debug 1_14 · java 1.14.4",
                        "select",
                    ),
                    Row(
                        "1.12.2 Amulet Output",
                        ".minecraft\\saves\\1_12_2 Amulet Output",
                        "select",
                    ),
                ],
            ),
            sec(
                "Selection",
                "fields",
                fields=[
                    Field("Chunks selected", "12"),
                    Field("Existing in source", "9"),
                ],
            ),
        ),
        actions=(Action("Browse for a world…", "outlined"),),
    ),
    "exportStructure": Spec(
        key="exportStructure",
        eyebrow="Structure files",
        title="Export selection",
        width=600,
        confirm="Export",
        sections=(
            sec(
                "Format",
                "selects",
                selects=[
                    Select(
                        "Handler",
                        (
                            "construction (.construction)",
                            "mcstructure (.mcstructure)",
                            "schematic (.schematic)",
                            "Sponge schem (.schem)",
                        ),
                    ),
                    Select("Platform", ("bedrock 1.17.0.1", "java 1.20.4")),
                ],
            ),
            sec(
                "Contents",
                "checks",
                checks=[
                    Check(
                        "Include air",
                        "Air blocks are written into the structure.",
                    ),
                    Check(
                        "Include block entities",
                        "Chests, signs, and other NBT-bearing blocks.",
                    ),
                ],
            ),
            sec(
                "Destination",
                "fields",
                fields=[
                    Field("Folder", "Documents\\Amulet\\exports"),
                    Field("File name", "spawn-arch"),
                ],
            ),
        ),
        actions=(Action("Open export in VS Code", "outlined"),),
    ),
    "licenses": Spec(
        key="licenses",
        eyebrow="Legal",
        title="Third Party Licenses",
        width=700,
        confirm="Close",
        sections=(
            sec(
                "Bundled components",
                "list",
                rows=[
                    Row("wxPython", "wxWindows Library Licence", "GUI"),
                    Row("PyOpenGL", "BSD 3-Clause", "renderer"),
                    Row("Amulet-Core", "MIT", "world api"),
                    Row("Squirrel.Windows 2.0.1", "MIT", "installer"),
                    Row("IBM Plex", "SIL Open Font License 1.1", "type"),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "Full licence texts ship with the application and are readable "
                    "offline."
                ),
            ),
        ),
        actions=(Action("Open licence folder", "outlined"),),
    ),
    "dimsum": Spec(
        key="dimsum",
        eyebrow="Startup surprise",
        title="Har gow · 蝦餃",
        width=520,
        confirm="Dismiss",
        intro=(
            "A bounded startup surprise reads authoritative dish names from the "
            "public catalog. Photos are never copied or vendored into this "
            "repository."
        ),
        sections=(
            sec(
                "Dish",
                "list",
                rows=[
                    Row("English name", "Har gow", "catalog"),
                    Row("Cantonese name", "蝦餃", "catalog"),
                    Row(
                        "Image asset",
                        "catalog-v1/har-gow.jpg (resolved at runtime)",
                        "public",
                    ),
                ],
            ),
            sec(
                "",
                "note",
                hint=(
                    "The surprise is also written to notification history, so a "
                    "missed eight-second toast stays reviewable."
                ),
            ),
        ),
        actions=(
            Action("Open Dim Sum Atlas", "tonal"),
            Action("Turn surprises off", "outlined"),
        ),
    ),
}
