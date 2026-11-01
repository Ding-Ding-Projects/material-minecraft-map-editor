import math
import struct
import unittest

from native.amulet_native.terrain_math import Camera, FACE_CORNERS, FACE_NORMALS, camera_coordinate, cross, sub, dot, pack_faces


class TerrainMathTests(unittest.TestCase):
    def test_all_face_windings_survive_axis_reflection(self):
        for direction,corners in FACE_CORNERS.items():
            self.assertGreater(dot(cross(sub(corners[1],corners[0]),sub(corners[2],corners[0])),FACE_NORMALS[direction]),0)
            vertices,indices,bounds=pack_faces([(0,0,0,direction,0)],{0:(.5,.6,.7,1)},(0,0,0))
            self.assertEqual(len(vertices),160);self.assertEqual(len(indices),24)
            points=[struct.unpack_from("<10f",vertices,i*40)[:3] for i in range(4)]
            tri=struct.unpack("<6I",indices)[:3]
            normal=FACE_NORMALS[direction]
            qt_normal=(normal[0],normal[1],-normal[2])
            self.assertGreater(dot(cross(sub(points[tri[1]],points[tri[0]]),sub(points[tri[2]],points[tri[0]])),qt_normal),0)

    def test_camera_ray_center_and_rebase_are_consistent(self):
        camera=Camera(target=(-400.,-64.,-500.))
        eye_before=camera.eye;camera.rebase()
        self.assertEqual(camera.eye,eye_before)
        self.assertEqual(camera.origin,tuple(math.floor(v/256)*256 for v in eye_before))
        origin,direction=camera.ray(400,300,800,600)
        self.assertEqual(origin,camera.eye)
        self.assertGreater(dot(direction,sub(camera.target,camera.eye)),0)
        self.assertAlmostEqual(dot(direction,direction),1)

    def test_camera_coordinates_reject_nonfinite_fractional_and_overflow(self):
        for value in ("nan","1.2","1e3","34359738368",True):
            with self.assertRaises(ValueError): camera_coordinate(value,0)
        self.assertEqual(camera_coordinate("-34359738368",0),-34359738368)
        with self.assertRaises(ValueError): camera_coordinate("4096",1)

    def test_camera_history_and_mesh_limits(self):
        camera=Camera();previous=camera.eye
        camera.go((100,200,300));self.assertEqual(camera.eye,(100,200,300))
        camera.back();self.assertEqual(camera.eye,previous)
        with self.assertRaises(ValueError): pack_faces([(0,0,0,"xp",0)]*2049,{0:(1,1,1,1)},(0,0,0))
        with self.assertRaises(ValueError): pack_faces([(9000,0,0,"xp",0)],{0:(1,1,1,1)},(0,0,0))
