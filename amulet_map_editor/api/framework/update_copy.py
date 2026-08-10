"""Localized, School-mode-safe copy for the unsigned Squirrel updater UI.

The updater remains factual at every language/funny level.  This module keeps
copy out of the wx layer so state transitions can be tested without a desktop.
"""

from __future__ import annotations

from typing import Any, Tuple

from amulet_map_editor.api import preferences, school_mode


def _presentation() -> Any:
    return school_mode.presentation_preferences(preferences.load())


def _tone(text: str, level: int) -> str:
    """Style the sentence without changing its update facts."""
    if level <= 1:
        return text
    if level == 2:
        return f"{text} (No work is interrupted.)"
    if level == 3:
        return f"{text} (The update is waiting politely in the wings.)"
    if level == 4:
        return f"{text} (The updater is wearing a tiny hard hat.)"
    return f"{text} (The update queue has brought snacks, not chaos.)"


def update_copy(
    status: str, *, version: str | None = None, detail: str | None = None
) -> Tuple[str, str]:
    """Return ``(title, body)`` for an update state.

    ``language_mode`` follows the shared persisted preferences.  School mode
    deliberately passes through its presentation projection, which forces
    English and the serious funny level without exposing the mode's shipped
    name in updater copy.
    """

    prefs = _presentation()
    mode = prefs.language_mode
    level = (
        prefs.funny_level_english if mode == "english" else prefs.funny_level_cantonese
    )
    version_text = version or "a new version"
    if status == "available":
        english = f"Update {version_text} is available. Choose Stage available update to download it."
        cantonese = f"有新版本 {version_text}。撳「Stage available update」先下載，唔會打斷你而家嘅工作。"
        title_en, title_zh = "Update available", "有更新"
    elif status == "ready_to_restart":
        ready_version = f" {version}" if version else ""
        english = f"The unsigned update{ready_version} is staged. Choose Restart to install update when your work is saved."
        cantonese = f"未簽署更新{ready_version} 已準備好。儲存好工作後撳「Restart to install update」就可以安裝。"
        title_en, title_zh = "Update ready", "更新已準備"
    elif status == "failed":
        reason = detail or "The update feed was unavailable."
        english = (
            f"Update check failed: {reason} Choose Check for updates to try again."
        )
        cantonese = f"更新檢查失敗：{reason}。撳「Check for updates」再試。"
        title_en, title_zh = "Update check failed", "更新檢查失敗"
    else:
        english = "Updates are unavailable in this installation."
        cantonese = "呢個安裝版本未有更新功能。"
        title_en, title_zh = "Updates unavailable", "更新不可用"
    if mode == "cantonese":
        return title_zh, _tone(cantonese, level)
    if mode == "bilingual":
        return (
            f"{title_en} · {title_zh}",
            f"{_tone(english, prefs.funny_level_english)}\n{_tone(cantonese, prefs.funny_level_cantonese)}",
        )
    return title_en, _tone(english, level)


def action_labels(status: str) -> Tuple[str, str]:
    """Return localized primary and secondary labels for the banner."""

    prefs = _presentation()
    if prefs.language_mode == "cantonese":
        primary = {
            "available": "Stage available update",
            "ready_to_restart": "Restart to install update",
            "failed": "Check for updates",
        }.get(status, "Close")
        return primary, "稍後"
    if prefs.language_mode == "bilingual":
        primary = {
            "available": "Stage available update · 下載更新",
            "ready_to_restart": "Restart to install update · 重新啟動安裝",
            "failed": "Check for updates · 再檢查",
        }.get(status, "Close · 關閉")
        return primary, "Later · 稍後"
    return {
        "available": "Stage available update",
        "ready_to_restart": "Restart to install update",
        "failed": "Check for updates",
    }.get(status, "Close"), "Later"


def release_notes_label() -> str:
    """Return the localized label for the validated release-notes action."""

    mode = _presentation().language_mode
    if mode == "cantonese":
        return "版本說明"
    if mode == "bilingual":
        return "Release notes · 版本說明"
    return "Release notes"
