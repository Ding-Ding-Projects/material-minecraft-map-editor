import struct
import unittest
from PySide6.QtCore import QCoreApplication
from shiboken6 import delete
from native.amulet_native.terrain_geometry import TerrainGeometry,SelectionGeometry
from native.amulet_native.terrain_math import pack_faces


class TerrainGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])

    def test_registered_geometry_receives_bounded_native_buffers(self):
        geometry=TerrainGeometry()
        try:
            vertices,indices,bounds=pack_faces([(2,0,-5,'zp',0)],{0:(.2,.3,.4,1)},(0,0,0))
            geometry.apply_batch(vertices,indices,bounds)
            self.assertEqual(geometry.stride(),40)
            self.assertEqual(geometry.attributeCount(),4)
            self.assertEqual(bytes(geometry.vertexData()),vertices)
            self.assertEqual(bytes(geometry.indexData()),indices)
            self.assertEqual(geometry.boundsMin().z(),-4)
        finally:delete(geometry)

    def test_selection_annotation_uses_same_translation_and_can_clear(self):
        geometry=SelectionGeometry()
        try:
            geometry.set_box((2,0,-5),(0,0,0))
            raw=bytes(geometry.vertexData())
            self.assertEqual(len(raw),24*28)
            points=[struct.unpack_from('<7f',raw,i*28)[:3] for i in range(24)]
            self.assertEqual(min(p[2] for p in points),-5)
            self.assertEqual(max(p[2] for p in points),-4)
            geometry.set_box(None,(0,0,0))
            self.assertEqual(len(geometry.vertexData()),0)
        finally:delete(geometry)
