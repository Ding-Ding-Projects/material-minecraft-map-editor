import math
import struct
import unittest
from dataclasses import asdict
import copy

from native.amulet_native.terrain_math import Camera, FACE_CORNERS, FACE_NORMALS, camera_coordinate, cross, sub, dot, pack_faces, world_to_render


class TerrainMathTests(unittest.TestCase):
    def test_all_face_windings_preserve_outward_normals(self):
        for direction,corners in FACE_CORNERS.items():
            self.assertGreater(dot(cross(sub(corners[1],corners[0]),sub(corners[2],corners[0])),FACE_NORMALS[direction]),0)
            vertices,indices,bounds=pack_faces([(0,0,0,direction,0)],{0:(.5,.6,.7,1)},(0,0,0))
            self.assertEqual(len(vertices),160);self.assertEqual(len(indices),24)
            points=[struct.unpack_from("<10f",vertices,i*40)[:3] for i in range(4)]
            tri=struct.unpack("<6I",indices)[:3]
            normal=FACE_NORMALS[direction]
            qt_normal=normal
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

    def test_rejected_camera_operations_leave_every_field_unchanged(self):
        actions=(lambda c:c.orbit(float('nan'),0),lambda c:c.orbit(0,float('inf')),
                 lambda c:c.go((34359738368,0,0)),lambda c:c.go((True,0,0)),
                 lambda c:c.pan(float('nan'),0),lambda c:c.dolly(float('inf')),
                 lambda c:c.frame(((0,0,0),(100000,1,1))))
        for action in actions:
            camera=Camera();before=copy.deepcopy(asdict(camera))
            with self.assertRaises(ValueError):action(camera)
            self.assertEqual(asdict(camera),before)

    def test_edge_orbit_rejects_absolute_eye_overflow_atomically(self):
        camera=Camera();camera.go((34359738367,0,0));before=copy.deepcopy(asdict(camera))
        with self.assertRaises(ValueError):camera.orbit(90,0)
        self.assertEqual(asdict(camera),before)

    def test_mesh_rejects_nonfinite_positions_and_colors(self):
        for faces,colors,origin in (([(0,0,0,'xp',0)],{0:(float('nan'),1,1,1)},(0,0,0)),
                                     ([(float('nan'),0,0,'xp',0)],{0:(1,1,1,1)},(0,0,0)),
                                     ([(0,0,0,'xp',0)],{0:(1,1,1,1)},(0,float('inf'),0))):
            with self.assertRaises(ValueError):pack_faces(faces,colors,origin)

    def test_fly_look_keeps_eye_and_rejects_long_frame(self):
        camera=Camera();eye=camera.eye
        camera.look(10,5)
        for a,b in zip(camera.eye,eye):self.assertAlmostEqual(a,b)
        before=copy.deepcopy(asdict(camera))
        with self.assertRaises(ValueError):camera.fly(1,0,0,1)
        self.assertEqual(asdict(camera),before)

    def test_exact_top_is_dedicated_and_history_restores_it(self):
        camera=Camera();camera.orientation('top')
        self.assertEqual(camera.eye,(0.,40.,0.))
        self.assertEqual(camera.ray(400,300,800,600)[1],(0.,-1.,0.))
        right=camera.ray(800,300,800,600)[0]
        self.assertGreater(right[0],0);self.assertEqual(right[2],0)
        upper=camera.ray(400,0,800,600)[0];self.assertLess(upper[2],0)
        before=copy.deepcopy(asdict(camera))
        with self.assertRaises(ValueError):camera.orbit(0,-1)
        self.assertEqual(asdict(camera),before)
        camera.orientation('perspective');camera.back()
        self.assertEqual(asdict(camera),before)

    def test_diagonal_flight_respects_absolute_speed_bound(self):
        camera=Camera();eye=camera.eye
        camera.fly(1,1,1,.05,True)
        delta=sub(camera.eye,eye)
        self.assertLessEqual(math.sqrt(dot(delta,delta)),1.6000000001)

    def test_translation_preserves_asymmetric_signed_volume_and_rebase_offsets(self):
        points=((0,0,0),(2,0,0),(0,3,0),(0,0,5))
        for origin in ((0,0,0),(-256,256,512)):
            transformed=[world_to_render(p,origin) for p in points]
            edges=[sub(p,transformed[0]) for p in transformed[1:]]
            self.assertEqual(dot(edges[0],cross(edges[1],edges[2])),30)
            self.assertEqual(sub(transformed[1],transformed[0]),(2,0,0))
