"""GUI-thread Qt Quick 3D geometry objects with bounded immutable inputs."""

from PySide6.QtCore import QByteArray,QThread
from PySide6.QtGui import QVector3D
from PySide6.QtQuick3D import QQuick3DGeometry
import struct
from .terrain_math import world_to_render


class SceneGeometry(QQuick3DGeometry):
    def rearm_for_scene(self):
        """Repopulate a newly attached scene node from retained CPU data.

        Qt 6.12.0's full-buffer setters unconditionally mark geometry data
        changed, even for equal QByteArrays. update() alone does not do that.
        Keep the implicitly shared buffers, attributes, bounds and identity.
        """
        if QThread.currentThread() != self.thread():
            raise RuntimeError('Geometry reattachment requires its GUI thread')
        vertices, indices = self.vertexData(), self.indexData()
        self.setVertexData(vertices)
        self.setIndexData(indices)
        self.update()


class TerrainGeometry(SceneGeometry):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.payload_bytes=0

    def apply_batch(self,vertices,indices,bounds):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("Geometry mutation requires its GUI thread")
        if len(vertices)%40 or len(indices)%24 or len(vertices)+len(indices)>376832:
            raise ValueError("Invalid geometry batch size")
        if len(vertices)//160 != len(indices)//24:
            raise ValueError("Geometry face counts do not match")
        self.clear()
        self.setStride(40)
        self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Triangles)
        attribute=QQuick3DGeometry.Attribute
        self.addAttribute(attribute.Semantic.PositionSemantic,0,attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.NormalSemantic,12,attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.ColorSemantic,24,attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.IndexSemantic,0,attribute.ComponentType.U32Type)
        self.setVertexData(QByteArray(vertices))
        self.setIndexData(QByteArray(indices))
        self.setBounds(QVector3D(*bounds[0]),QVector3D(*bounds[1]))
        self.payload_bytes=len(vertices)+len(indices)
        self.update()


class SelectionGeometry(SceneGeometry):
    """Explicit selection/unsupported-cell annotation, never terrain content."""
    def set_box(self,cell,origin):
        self.set_bounds(cell,cell,origin)

    def set_bounds(self,low,high,origin):
        if QThread.currentThread()!=self.thread():raise RuntimeError('Selection geometry requires GUI thread')
        self.clear()
        if low is None or high is None:self.update();return
        points=[world_to_render((x,y,z),origin)
                for x in (low[0],high[0]+1) for y in (low[1],high[1]+1) for z in (low[2],high[2]+1)]
        if any(abs(v)>8192 for point in points for v in point):self.update();return
        edges=[(i,i^(1<<axis)) for i in range(8) for axis in range(3) if not i&(1<<axis)]
        vertices=b''.join(struct.pack('<7f',*points[index],1.,.85,.1,1.) for edge in edges for index in edge)
        attribute=QQuick3DGeometry.Attribute
        self.setStride(28);self.setPrimitiveType(QQuick3DGeometry.PrimitiveType.Lines)
        self.addAttribute(attribute.Semantic.PositionSemantic,0,attribute.ComponentType.F32Type)
        self.addAttribute(attribute.Semantic.ColorSemantic,12,attribute.ComponentType.F32Type)
        self.setVertexData(QByteArray(vertices))
        self.setBounds(QVector3D(*(min(p[i] for p in points) for i in range(3))),QVector3D(*(max(p[i] for p in points) for i in range(3))))
        self.update()
