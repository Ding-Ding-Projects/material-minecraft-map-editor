from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QCoreApplication,QEventLoop,QTimer,QSettings
from PySide6.QtGui import QVector3D
from native.amulet_native.terrain_model import TerrainModel
from native.amulet_native.engine_coordinator import EngineCoordinator
from native.amulet_native.references import ReferenceSettings
from native.amulet_native.terrain_math import norm,sub,dot
from native.amulet_native.terrain_scene import SceneAssembler
from terrain_protocol_fixture import wire_fixture,envelope_bytes


def wait(predicate):
    loop=QEventLoop();timer=QTimer();timer.setInterval(5)
    timer.timeout.connect(lambda:loop.quit() if predicate() else None)
    deadline=QTimer();deadline.setSingleShot(True);deadline.timeout.connect(loop.quit)
    timer.start();deadline.start(3000);loop.exec();timer.stop();deadline.stop()
    if not predicate():raise AssertionError('Terrain worker did not acknowledge completion')


class TerrainModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.settings=QSettings(str(Path(self.temp.name)/'settings.ini'),QSettings.Format.IniFormat)
        self.references=ReferenceSettings(self.settings)
        self.coordinator=EngineCoordinator()
        self.model=TerrainModel(Path('missing-engine'),self.coordinator,self.references)

    def tearDown(self):
        self.model.cancel();wait(lambda:not self.model.busy);self.model.dispose()
        self.model.deleteLater();self.references.deleteLater();self.coordinator.deleteLater()
        self.app.processEvents();self.temp.cleanup()

    def scene(self):
        request,manifest,pages,end=wire_fixture()
        scene=SceneAssembler(manifest,request,envelope_bytes('terrain:1:begin',manifest))
        for i,page in enumerate(pages):scene.accept_page(page,envelope_bytes(f'terrain:1:page:{i}',page))
        return scene.finish(end,envelope_bytes('terrain:1:end',end))

    def test_cpu_geometry_requires_matching_submission_receipt(self):
        self.model._received(self.scene())
        wait(lambda:self.model.worker is None)
        self.assertEqual(len(self.model.geometries),1)
        self.assertEqual(len(self.model.geometries[0].vertexData()),6*160)
        self.assertFalse(self.model.ready)
        self.model.frameSubmitted(self.model.render_serial-1);self.assertFalse(self.model.ready)
        # Synthetic receipt tests the model boundary, not a rendered frame.
        self.model.frameSubmitted(self.model.render_serial);self.assertTrue(self.model.ready)
        previous=self.model.render_serial
        self.model.viewportChanged(800,600)
        self.assertFalse(self.model.ready)
        self.model.frameSubmitted(previous);self.assertFalse(self.model.ready)
        self.model.frameSubmitted(self.model.render_serial);self.assertTrue(self.model.ready)
        self.model.cancel();wait(lambda:not self.model.busy)
        self.assertFalse(self.model.ready);self.assertEqual(self.model.geometries,[])
        self.assertEqual(self.model._charged,0)

    def test_camera_ray_matches_qt_rotation_in_world_axes(self):
        rotation=self.model.cameraRotation
        qt_forward=rotation.rotatedVector(QVector3D(0,0,-1))
        world_forward=(qt_forward.x(),qt_forward.y(),qt_forward.z())
        _,center=self.model.camera.ray(400,300,800,600)
        self.assertGreater(dot(norm(world_forward),center),.99999)
        qt_right=rotation.rotatedVector(QVector3D(1,0,0))
        world_right=(qt_right.x(),qt_right.y(),qt_right.z())
        _,edge=self.model.camera.ray(800,300,800,600)
        self.assertGreater(dot(sub(edge,center),world_right),0)

    def test_cancel_before_mesh_delivery_releases_pending_objects(self):
        self.model._received(self.scene());self.model.cancel()
        wait(lambda:not self.model.busy)
        self.assertFalse(self.model.ready);self.assertEqual(self.model._charged,0)
        self.assertFalse(self.model.awaiting_frame)

    def test_exact_top_qt_axes_agree_with_cpu_rays(self):
        self.model.view('top')
        rotation=self.model.cameraRotation
        forward=rotation.rotatedVector(QVector3D(0,0,-1))
        right=rotation.rotatedVector(QVector3D(1,0,0))
        up=rotation.rotatedVector(QVector3D(0,1,0))
        self.assertAlmostEqual(forward.y(),-1,delta=1e-6)
        self.assertAlmostEqual(right.x(),1,delta=1e-6)
        self.assertAlmostEqual(up.z(),-1,delta=1e-6)
        self.assertEqual(self.model.camera.ray(400,300,800,600)[1],(0.,-1.,0.))
        def project(point):
            p=QVector3D(*point)
            return QVector3D.dotProduct(p,right),QVector3D.dotProduct(p,up)
        self.assertAlmostEqual(project((2,0,0))[0],2,delta=1e-6)
        self.assertAlmostEqual(project((0,0,-5))[1],5,delta=1e-6)
        self.assertAlmostEqual(project((0,0,3))[1],-3,delta=1e-6)

    def test_cancel_after_cpu_finish_before_queued_delivery_cannot_resurrect_scene(self):
        self.model._received(self.scene())
        self.assertTrue(self.model.worker.wait(1000))
        self.model.cancel()
        wait(lambda:not self.model.busy)
        self.assertFalse(self.model.awaiting_frame)
        self.model.frameSubmitted(self.model.render_serial)
        self.assertFalse(self.model.ready)
        self.assertEqual(self.model.geometries,[])
