# Material application shell

The Windows shell uses a frameless frame with an app-owned title bar, compact
owner-drawn caption controls, and a Material command bar. The main menu is one
rounded surface card with a single product mark and clear filled, tonal,
outlined, and text action hierarchy. A one-page workspace does not reserve a
duplicate side tab rail.

Startup makes the editor usable immediately. It does not present an
acknowledgement, purchase, donation, sponsorship, rating, review, upgrade, or
other promotional gate. Safety guidance stays attached to the **Open World**
action and in the offline manual. Update states remain non-blocking operational
status and retain explicit user control over restart.

## Configuration and failure modes

The shell consumes the persisted light/dark theme, density, accent, UI font,
and scale roles. Owner-drawn buttons expose Return and Space activation, focus,
hover, pressed, disabled, and minimum-target states. When a persisted appearance
value is invalid, the existing preference normalizer falls back to shipped
roles rather than preventing startup.

Legacy editor pages still contain native controls and are being migrated
incrementally. The shared role projection keeps them readable, but it is not
evidence that every editor tool has completed component-level M3 migration.

## Security and accessibility

Window actions resolve the real top-level owner before minimizing, maximizing,
or closing, so a decorative child panel cannot receive a frame operation.
Caption and command controls have accessible names, visible focus, keyboard
activation, and bounded targets. No startup route performs a purchase or stores
payment data.

## Verification

Run:

```powershell
py -3 -m pytest tests/test_material_components_contract.py tests/test_nag_free_startup_contract.py -q
```

The native surface is also exercised on an isolated hidden Windows desktop and
captured through the real wx window. Static tests are not a substitute for that
runtime evidence.

Suggested articles: [appearance](../appearance/README.md),
[notification centre](../notification-centre/README.md), and
[tab groups](../tab-groups/README.md).
