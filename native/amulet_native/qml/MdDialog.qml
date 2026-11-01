import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material

Dialog {
    modal: true
    padding: 24
    Material.roundedScale: Material.ExtraLargeScale
    standardButtons: Dialog.Close
    Accessible.name: title
}
