# Native chunk component registration

All component paths are relative to `native/amulet_native/qml/`. These registered wrappers retain actual Qt Quick Controls Material implementations and add task-specific anatomy. Runtime visual conformance and all interaction states still require the pinned hidden-desktop audit; registration alone does not prove acceptance.

| Registered file | Actual anatomy | Required state coverage |
| --- | --- | --- |
| `MdNumericField.qml` | Persistent label, Qt Material outlined TextField, independent clear and help targets, semantic integer description, bounded help dialog | empty, populated, editing, focus, invalid draft, clear, help open/closed, disabled |
| `MdSelect.qml` | Label, Qt Material ComboBox anchor, opaque bounded popup, owned filter field, clear, adjacent regex workbench, ItemDelegate results | selected, expanded, filtered, no match, regex pending/invalid, keyboard focus, disabled |
| `MdSpinBox.qml` | Qt Material SpinBox with editable value and separate increase/decrease controls, 48-unit preferred height | valid, editing, bounds, disabled, hover, pressed, focus |
| `MdProgress.qml` | Qt Material ProgressBar track/indicator and accessible progress name | indeterminate, hidden after acknowledgement |
| `MdDialog.qml` | Qt Material Dialog container, title, padded content, footer actions, modality and accessible name | open, focused, closed, focus return |
| `MdRegexDialog.qml` | Registered dialog with synchronized pattern/mode, case/multiline flags, escaped-literal insertion, sample text, match spans and exact capability disclosure | plain, regex, valid, invalid, no match, bounded timeout, helper unavailable |

## Installed upstream provenance

Runtime package: PySide6 6.12.0, verified in the isolated project environment. Source location inside that package: `qml/QtQuick/Controls/Material/`. The inspected source headers identify The Qt Company and the SPDX choice `LicenseRef-Qt-Commercial OR LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. Preserve distribution notices and comply with the selected upstream license when packaging; this receipt is not legal advice or a completed redistribution audit.

| Upstream source | SHA-256 |
| --- | --- |
| TextField.qml | `1DAAE4AA7D850F30756AD72D6476B7A215775AAC659D55149714B2A5553955D3` |
| ComboBox.qml | `FC94E32F37B75BF2EF872FA10B377778DAC260CE0BAC49630DAB1C6783F50FDA` |
| SpinBox.qml | `2FFD976EB2551CAD85CC525E44FF841CB629E8B3AB2D828D9C720BFA9E704ABE` |
| ProgressBar.qml | `BC084EFA4134D5EF622ED1D856807B3D2CE054C765D5352CB6FA6AA5E01E9DD7` |
| Dialog.qml | `A22F55CD16E6AD3406B73DBFDC22CC25EF06DFFCBD396196711844C1AB1868AA` |
| CheckBox.qml | `977722929DD84FF6FE8290C57EF2CD11E739E11F4B8B4FC926E8C998AD176558` |
| Switch.qml | `2BB9B1D6317FE83283FF0C9F5632E7F73F475BBEEB64681739C92C07E46F0974` |
| ItemDelegate.qml | `A5EA449C6CCDC72830CD4192DB8BEACAD078E88FC1051AE213CFE991E275056B` |

The source contract is [Qt Material Style](https://doc.qt.io/qt-6/qtquickcontrols-material.html), reviewed alongside the installed files. [Material Design 3 components](https://m3.material.io/components) remain the visual reference; complete rendered comparison is outstanding.

## Regex capability boundary

Each dimension and section selector has its own `SelectorFilter` QObject. Plain text is default. Mode, pattern, flags, validation, filtered results and sample matches remain owned by that selector and synchronize with its workbench. Supported execution is the running interpreter's Python `re`, named with its exact version in successful results. Patterns are limited to 512 characters, samples to 4096, items to 256 with 256 characters each, sample matches to 64, input/output to 64 KiB and isolated worker execution to 750 ms after startup. A 2-second startup timeout is separate. Superseded requests are killed and cannot publish stale results.

Actual supported actions are matching, case/multiline flags, literal escaping, sample match spans and filtering. Engine conversion, step debugging, benchmarking, replacement/code templates, persistent collections and file search are unsupported and visibly disclosed. This is not full RegexBuddy parity. No in-process arbitrary regex evaluation runs on the GUI thread.

The worker uses the verified direct base interpreter, selecting its windowless executable on Windows, with `-I -S` and the exact stdlib-only worker script. A bounded verification process checks executable identity, interpreter version and direct PID equality; the executable hash is rechecked before launching a worker. Before receiving a pattern, each evaluator reports its PID/executable/version and must match its owning QProcess. An unverified evaluator receives no regex payload.

Timeout and supersession kill only that owned direct process. Window closure waits for both selector workers and the engine to acknowledge stopping. Cancel close retains the window; presentation destruction rejects pending workers instead of ignoring a failed wait. The same cumulative 64 KiB stdout limit applies during normal reads and the final drain. A successful result requires exact fields, bounded unique indices, bounded match spans/text and the expected interpreter version. Native process-snapshot tests prove matching evaluator/QProcess identities and no remaining evaluator or descendants after timeout, supersession and close. These are nonvisual lifecycle checks, not GUI acceptance.
