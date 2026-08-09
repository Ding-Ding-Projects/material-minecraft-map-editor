from pathlib import Path

SOURCE = Path("amulet_map_editor/api/wx/material3.py").read_text(encoding="utf-8")


def _function_body(name: str, next_name: str) -> str:
    start = SOURCE.index(f"def {name}(")
    end = SOURCE.index(f"def {next_name}(", start)
    return SOURCE[start:end]


def test_dialog_sizer_is_detached_before_it_is_nested_in_replacement_chrome():
    body = _function_body(
        "_ensure_material_dialog_chrome", "_ensure_material_frame_chrome"
    )

    detach = body.index("wx.Dialog.SetSizer(window, None, False)")
    nest = body.index("outer.Add(content, 1, wx.EXPAND)")
    install = body.index("wx.Dialog.SetSizer(window, outer)")

    assert detach < nest < install


def test_frame_sizer_uses_the_same_safe_native_ownership_order():
    body = _function_body("_ensure_material_frame_chrome", "apply_material3")

    detach = body.index("wx.Frame.SetSizer(window, None, False)")
    nest = body.index("outer.Add(content, 1, wx.EXPAND)")
    install = body.index("wx.Frame.SetSizer(window, outer)")

    assert detach < nest < install
