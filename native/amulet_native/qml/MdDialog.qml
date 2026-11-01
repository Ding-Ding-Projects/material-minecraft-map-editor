import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material

Dialog {
    modal: true
    padding: 24
    Material.roundedScale: Material.ExtraLargeScale
    standardButtons: Dialog.Close
    // QQuickDialog supplies QAccessible::Dialog and forwards title to its
    // accessible popup item. Accessible cannot attach to this Popup QObject.
}
