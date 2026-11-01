"""Native terrain presentation, bounded worker handoff and exact selection."""

import math
import threading
from PySide6.QtCore import QObject,Property,Signal,Slot,QTimer,Qt
from PySide6.QtGui import QVector3D,QQuaternion
from PySide6.QtQml import QQmlEngine
from shiboken6 import delete,isValid

from .terrain_math import Camera,camera_coordinate,sub,norm
from .terrain_scene import TerrainRequest
from .terrain_session import TerrainSession
from .terrain_mesh import MeshWorker
from .terrain_geometry import TerrainGeometry,SelectionGeometry
from .terrain_picking import pick_shape,selection_counts


class FrameReceipt(QObject):
    submitted=Signal(int,int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self._lock=threading.Lock();self.requested=None;self.synchronized=None

    def expect(self,epoch,serial):
        with self._lock:self.requested=(epoch,serial)

    def disarm(self):
        with self._lock:self.requested=None

    def synchronize(self):
        with self._lock:self.synchronized=self.requested

    def frame_end(self):
        with self._lock:receipt=self.synchronized
        if receipt is not None:self.submitted.emit(*receipt)


class TerrainModel(QObject):
    changed=Signal()
    loadRequested=Signal(object)

    def __init__(self,engine_path,coordinator,references,parent=None):
        super().__init__(parent)
        self.session=TerrainSession(engine_path,coordinator,references,self)
        self.session.changed.connect(self._session_changed);self.session.completed.connect(self._received)
        self.camera=Camera();self.scene=None;self.worker=None;self._worker_result=None
        self._geometries=[];self._pending_geometries=[];self._charged=0;self._retiring=0
        self.generation=0;self.mesh_revision=0;self.render_serial=0;self.awaiting_frame=False;self._ready=False
        self.cut=(-2048,2047);self.selected=None;self.anchor=None;self.box=None
        self._selection_geometry=SelectionGeometry()
        QQmlEngine.setObjectOwnership(self._selection_geometry,QQmlEngine.ObjectOwnership.CppOwnership)
        self._status='Select a verified world and load a bounded area.';self._last_context=None
        self._pending_mesh=False;self._queued_request=None;self._window=None
        self._look_capture=False
        self._view_dimensions=None
        self._viewport_owner=None;self._attachment_epoch=0;self._owner_connection=None
        self._frame=FrameReceipt(self);self._frame.submitted.connect(self.frameSubmitted,Qt.ConnectionType.QueuedConnection)
        self.deadline=QTimer(self);self.deadline.setSingleShot(True);self.deadline.timeout.connect(self._timeout)

    @Property(str,notify=changed)
    def status(self):return self._status
    @Property(bool,notify=changed)
    def ready(self):return self._ready
    @Property(bool,notify=changed)
    def hasScene(self):return self.scene is not None
    @Property(bool,notify=changed)
    def hasGeometry(self):return bool(self._geometries)
    @Property(bool,notify=changed)
    def hasUnsupported(self):return bool(self.scene and self.scene.manifest['totals']['unsupportedCells'])
    @Property(bool,notify=changed)
    def busy(self):return self.session.busy or self.worker is not None or self._retiring>0 or self._queued_request is not None
    @Property('QVariantList',notify=changed)
    def geometries(self):return self._geometries
    @Property(QObject,constant=True)
    def selectionGeometry(self):return self._selection_geometry
    @Property(int,notify=changed)
    def minimumY(self):return self.scene.bounds[0][1] if self.scene else -2048
    @Property(int,notify=changed)
    def maximumY(self):return self.scene.bounds[1][1]-1 if self.scene else 2047
    @Property(QVector3D,notify=changed)
    def cameraPosition(self):
        local=sub(self.camera.eye,self.camera.origin)
        return QVector3D(*local)
    @Property(QQuaternion,notify=changed)
    def cameraRotation(self):
        direction=norm(sub(self.camera.target,self.camera.eye))
        up=QVector3D(0,0,-1) if self.camera.preset=='top' else QVector3D(0,1,0)
        return QQuaternion.fromDirection(QVector3D(-direction[0],-direction[1],-direction[2]),up)
    @Property(str,notify=changed)
    def cameraText(self):return ', '.join(f'{v:.2f}' for v in self.camera.eye)
    @Property(str,notify=changed)
    def projection(self):return self.camera.projection
    @Property(str,notify=changed)
    def viewLabel(self):return {'top':'Top (north up, east right)','front':'Front orthographic','side':'Side orthographic','free':'Perspective'}[self.camera.preset]
    @Property(float,notify=changed)
    def orthographicSpan(self):return self.camera.span
    @Property(str,notify=changed)
    def selectionText(self):
        if self.box:return f"Selection {self.box['minimum']} to {self.box['maximum']} · {self.box['decoded']} decoded · {self.box['unknown']} unknown"
        if self.selected:return 'Selected '+', '.join(map(str,self.selected['world']))
        return 'No shape selected'
    @Property('QVariantMap',notify=changed)
    def inspection(self):
        if not self.scene or not self.selected:return {'valid':False,'block':None,'message':'Select a submitted shape or an unsupported cell.'}
        hit=self.selected;state=self.scene.state_table[hit['stateId']];x,y,z=hit['world']
        block={'name':state['name'],'properties':[{'key':k,'value':v} for k,v in state['properties']],
               'world':f'{x}, {y}, {z}','local':f'{x%16}, {y%16}, {z%16}',
               'chunk':f'{x//16}, {z//16}','dimension':self.scene.request.dimension,
               'dataVersion':str(state['dataVersion'])}
        return {'valid':True,'block':block,'message':''}

    def attach_window(self,window):
        self._window=window
        window.afterSynchronizing.connect(self._frame.synchronize,Qt.ConnectionType.DirectConnection)
        window.afterFrameEnd.connect(self._frame.frame_end,Qt.ConnectionType.DirectConnection)
        window.activeChanged.connect(lambda:self.lookCapture(False) if not window.isActive() else None)
        window.sceneGraphError.connect(lambda code,message:self._render_failure(message))

    def _render_failure(self,message):
        self.cancel();self._status='Native renderer unavailable: '+str(message)[:300];self.changed.emit()

    def _view_attached(self):
        owner=self._viewport_owner
        if owner is None or not isValid(owner) or owner.property('visible') is not True:return False
        dimensions=(owner.property('width'),owner.property('height'))
        return bool(all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in dimensions)
                    and (self._window is None or (isValid(self._window) and self._window.isVisible())))

    def _disconnect_owner(self):
        if self._owner_connection is not None:
            QObject.disconnect(self._owner_connection)
            self._owner_connection=None

    @Slot(QObject,result=int)
    def viewportAttached(self,owner):
        if owner is None or not isValid(owner) or owner.property('visible') is not True:
            return 0
        self._disconnect_owner()
        self._attachment_epoch+=1
        epoch=self._attachment_epoch;self._viewport_owner=owner;self._view_dimensions=None
        self._owner_connection=owner.destroyed.connect(lambda *unused:self.viewportDetached(epoch))
        self._ready=False;self.awaiting_frame=False;self._frame.disarm()
        for geometry in self._geometries:
            geometry.rearm_for_scene()
        self._selection_geometry.rearm_for_scene()
        self._invalidate_frame()
        if self.awaiting_frame and not self.deadline.isActive():self.deadline.start(30000)
        self.changed.emit()
        return epoch

    @Slot(int)
    def viewportDetached(self,epoch):
        if epoch!=self._attachment_epoch:return
        self.lookCapture(False)
        self._disconnect_owner()
        self._viewport_owner=None;self._attachment_epoch+=1;self._view_dimensions=None
        self._ready=False;self.awaiting_frame=False;self._frame.disarm()
        if not self.session.busy and self.worker is None:self.deadline.stop()
        self.changed.emit()

    def _invalidate_frame(self):
        self._ready=False;self.awaiting_frame=False;self._frame.disarm()
        if self._geometries and not self.worker and self._view_attached():
            self.render_serial+=1;self._frame.expect(self._attachment_epoch,self.render_serial)
            self.awaiting_frame=True;self._ready=False
            if self._window and isValid(self._window):self._window.update()

    def require_submission(self):
        self._invalidate_frame();self.changed.emit()

    @Slot(int,int,int)
    def viewportChanged(self,epoch,width,height):
        if epoch==self._attachment_epoch and self._view_attached() and width>0 and height>0 and self._view_dimensions!=(width,height):
            self._view_dimensions=(width,height);self._invalidate_frame();self.changed.emit()

    def request(self,request):
        self.generation+=1;self._ready=False;self.selected=self.anchor=self.box=None
        self._queued_request=None;self.session.cancel();self._pending_mesh=False
        if self.worker:self.worker.cancel()
        self._clear_geometry();self._status='Loading replaces the previous displayed scene.'
        self._selection_geometry.set_box(None,self.camera.origin)
        self.scene=None;self._queued_request=request
        self.deadline.start(30000);self._advance();self.changed.emit()

    def _advance(self):
        if self._queued_request and not self.worker and not self.session.busy and not self._retiring:
            request=self._queued_request;self._queued_request=None
            self.scene=None;self.session.request(request)

    def _session_changed(self):
        if self.session.busy or self.session.phase=='unavailable':self._status=self.session.status
        if self.session.phase in ('unavailable','canceled') and not self._queued_request and not self.worker:self.deadline.stop()
        self._advance();self.changed.emit()

    def _received(self,scene):
        self.scene=scene;self.cut=(scene.bounds[0][1],scene.bounds[1][1]-1)
        context=(scene.request.world_id,scene.request.dimension)
        try:
            if not scene.manifest['totals']['cubeCells']:
                self._status='Loaded coverage has no admitted cube shapes. Missing and unsupported cells are not air.'
                self.deadline.stop();self.changed.emit();return
            if self._last_context!=context:
                self.camera.frame(scene.bounds);self._last_context=context
            self._begin_mesh()
        except ValueError as error:self._status=str(error);self.deadline.stop();self.changed.emit()

    def _begin_mesh(self):
        if not self.scene:return
        self._ready=False;self.awaiting_frame=False
        self._frame.disarm()
        if not self.deadline.isActive():self.deadline.start(30000)
        if self.worker:
            self.worker.cancel();self._pending_mesh=True;return
        self.mesh_revision+=1
        self._retire(self._pending_geometries);self._pending_geometries=[]
        worker=MeshWorker(self.scene,self.camera.origin,self.cut,self.mesh_revision,self)
        self.worker=worker;self._worker_result=None
        worker.batchReady.connect(lambda batch:self._accept_batch(worker,batch))
        worker.outcome.connect(lambda outcome:self._outcome(worker,outcome))
        worker.finished.connect(lambda:self._mesh_finished(worker))
        self._status='Building bounded cube-shape buffers…';worker.start();self.changed.emit()

    def _accept_batch(self,worker,batch):
        try:
            if worker is not self.worker or worker.cancelled.is_set() or batch['generation']!=self.mesh_revision:return
            size=len(batch['vertices'])+len(batch['indices'])
            # Reserve transient colors, queued batches and packing copies in
            # addition to retained data and both application/Qt CPU payloads.
            if self.scene.retained_bytes()+self._charged+size*2+32*1024*1024>256*1024*1024 or self._charged//2+size+1024*1024>128*1024*1024:
                raise ValueError('Native geometry allocation budget exceeded. Clear the previous scene before loading more.')
            geometry=TerrainGeometry()
            QQmlEngine.setObjectOwnership(geometry,QQmlEngine.ObjectOwnership.CppOwnership)
            geometry.apply_batch(batch['vertices'],batch['indices'],batch['bounds'])
            self._charged+=size*2
            geometry.destroyed.connect(lambda *unused,charge=size*2:self._release_charge(charge))
            self._pending_geometries.append(geometry)
        except (ValueError,RuntimeError) as error:
            self._worker_result={'error':str(error)};worker.cancel()
        finally:worker.acknowledge()

    def _outcome(self,worker,outcome):
        if worker is self.worker and not (self._worker_result and 'error' in self._worker_result):self._worker_result=outcome

    def _mesh_finished(self,worker):
        if worker is not self.worker:return
        result=self._worker_result or {'error':'Mesh worker ended without a result'}
        worker.scene=None
        self.worker=None;worker.deleteLater()
        if result.get('error') or result.get('canceled') or worker.cancelled.is_set():
            self._retire(self._pending_geometries);self._pending_geometries=[]
            self._status=result.get('error','Mesh canceled.')
        else:
            old=self._geometries;self._geometries=self._pending_geometries;self._pending_geometries=[]
            self.changed.emit();self._retire(old)
            self._invalidate_frame()
            self._status=('Geometry accepted by GUI; awaiting this viewport attachment frame.' if self.awaiting_frame
                          else 'Geometry retained. Return to the terrain view to display it.')
            if not self._view_attached():self.deadline.stop()
        if self._pending_mesh:
            self._pending_mesh=False;self._begin_mesh()
        self._advance();self.changed.emit()

    @Slot(int,int)
    def frameSubmitted(self,epoch,serial):
        if self.awaiting_frame and epoch==self._attachment_epoch and self._view_attached() and serial==self.render_serial and self.scene:
            self.awaiting_frame=False;self._ready=True;self.deadline.stop()
            totals=self.scene.manifest['totals']
            unavailable=sum(row['availability']!='present' for row in self.scene.coverage.values())
            self._status=f"Verified cube shapes: {totals['cubeCells']} supported cells; {totals['unsupportedCells']} unsupported cells; {unavailable} unavailable sections. Material opacity, textures and lighting are not represented."
            self.changed.emit()

    def _retire(self,objects):
        if not objects:return
        self._retiring+=len(objects)
        def retire():
            for obj in objects:
                if isValid(obj):delete(obj)
                self._retiring-=1
            self._advance();self.changed.emit()
        QTimer.singleShot(0,retire)

    def _release_charge(self,charge):self._charged-=charge
    def _clear_geometry(self):
        old=self._geometries;self._geometries=[];self.awaiting_frame=False;self._ready=False
        self._frame.disarm()
        self.changed.emit();self._retire(old)

    def cancel(self):
        self.lookCapture(False)
        self._queued_request=None;self._pending_mesh=False;self.session.cancel();self.deadline.stop()
        if self.worker:self.worker.cancel()
        self._clear_geometry();self.selected=self.anchor=self.box=None
        self._selection_geometry.set_box(None,self.camera.origin)
        self._status='Terrain operation canceled; waiting for owned work to stop.';self.changed.emit()

    def invalidate(self):
        self.cancel();self.scene=None;self._last_context=None

    def _timeout(self):
        self.cancel();self._status='Terrain load/assembly/submission exceeded its 30-second deadline.';self.changed.emit()

    def _camera_action(self,action):
        previous=self.camera.origin_revision
        try:
            action()
            if previous!=self.camera.origin_revision and self.scene:
                self._clear_geometry();self._begin_mesh()
            else:self._invalidate_frame()
            if self.box:self._selection_geometry.set_bounds(self.box['minimum'],self.box['maximum'],self.camera.origin)
            else:self._selection_geometry.set_box(self.selected['world'] if self.selected else None,self.camera.origin)
        except ValueError as error:self._status=str(error)
        self.changed.emit()

    @Slot(float,float)
    def orbit(self,x,y):self._camera_action(lambda:self.camera.orbit(x,y))
    @Slot(float,float)
    def look(self,x,y):self._camera_action(lambda:self.camera.look(x,y))
    @Slot(float,float)
    def pan(self,x,y):self._camera_action(lambda:self.camera.pan(x,y))
    @Slot(float)
    def dolly(self,steps):self._camera_action(lambda:self.camera.dolly(steps))
    @Slot(float,float,float,float,bool)
    def fly(self,forward,right,up,seconds,fast):self._camera_action(lambda:self.camera.fly(forward,right,up,seconds,fast))
    @Slot()
    def frameLoaded(self):
        if self.scene:self._camera_action(lambda:self.camera.frame(self.scene.bounds))
    @Slot()
    def back(self):self._camera_action(self.camera.back)
    @Slot(str,str,str)
    def go(self,x,y,z):
        try:coords=tuple(camera_coordinate(v,i) for i,v in enumerate((x,y,z)))
        except ValueError as error:self._status=str(error);self.changed.emit();return
        self._camera_action(lambda:self.camera.go(coords))
    @Slot(str)
    def view(self,mode):
        self._camera_action(lambda:self.camera.orientation(mode))
    @Slot(int,int)
    def setCut(self,low,high):
        if not self.scene:return
        if not self.scene.bounds[0][1]<=low<=high<self.scene.bounds[1][1]:
            self._status='Cutaway must stay within the accepted inclusive Y bounds.';self.changed.emit();return
        self.cut=(low,high);self.selected=None;self._begin_mesh()
        if not self.box:self._selection_geometry.set_box(None,self.camera.origin)
    @Slot(float,float,float,float,bool)
    def pick(self,x,y,width,height,extend):
        if not self._ready or not self.scene:return
        origin,direction=self.camera.ray(x,y,width,height)
        hit=pick_shape(self.scene,origin,direction,*self.cut)
        self.selected=hit
        self._selection_geometry.set_box(hit['world'] if hit else None,self.camera.origin)
        if hit:
            if extend and self.anchor:
                self.box=selection_counts(self.scene,self.anchor,hit['world']);self.anchor=None
                self._selection_geometry.set_bounds(self.box['minimum'],self.box['maximum'],self.camera.origin)
            elif extend:self.anchor=hit['world'];self.box=None
            else:self.box=None
            self._status='Supported shape hit; not a physical collision or native material surface.'
        else:self._status='No loaded supported shape at this position.'
        self.changed.emit()

    @Slot(str,str,str,str,str,str)
    def selectBox(self,x1,y1,z1,x2,y2,z2):
        if not self.scene:return
        try:
            first=tuple(camera_coordinate(v,i) for i,v in enumerate((x1,y1,z1)))
            second=tuple(camera_coordinate(v,i) for i,v in enumerate((x2,y2,z2)))
            if any(not -2048<=p[1]<=2047 for p in (first,second)):raise ValueError('Selection world Y must be -2048 through 2047.')
            candidate=selection_counts(self.scene,first,second)
        except ValueError as error:self._status=str(error);self.changed.emit();return
        self.box=candidate;self.anchor=None
        self._selection_geometry.set_bounds(candidate['minimum'],candidate['maximum'],self.camera.origin)
        self._status='Inclusive selection recorded. Unknown cells remain unknown; no world data changed.';self.changed.emit()

    @Slot()
    def cancelSelection(self):
        if self.anchor is not None:
            self.anchor=None;self._status='Selection anchor canceled.';self.changed.emit()

    @Slot()
    def frameSelection(self):
        if self.box:self._camera_action(lambda:self.camera.frame((self.box['minimum'],tuple(v+1 for v in self.box['maximum']))))
        elif self.selected:self._camera_action(lambda:self.camera.frame((self.selected['world'],tuple(v+1 for v in self.selected['world']))))

    def select_coordinate(self,x,y,z):
        if not self.scene:return
        state=self.scene.cell_state(x,y,z)
        self.selected=None if state is None else {'world':(x,y,z),'stateId':state,'face':None}
        self.box=self.anchor=None
        self._selection_geometry.set_box((x,y,z) if state is not None else None,self.camera.origin)
        self._status='Selection transferred from the same accepted source snapshot.' if state is not None else 'Selected source cell is not decoded.'
        self.changed.emit()
    @Slot()
    def nextUnsupported(self):
        if not self.scene:return
        current=self.selected['world'] if self.selected else None
        first=None;seen=current is None
        for x,y,z,state in self.scene.cells():
            if not self.scene.supported(state):
                entry={'world':(x,y,z),'stateId':state,'face':None}
                if first is None:first=entry
                if seen:self.selected=entry;break
                if entry['world']==current:seen=True
        else:self.selected=first
        self._selection_geometry.set_box(self.selected['world'] if self.selected else None,self.camera.origin)
        self._status='Unsupported cell selected from retained data; no cube shape is inferred.';self.changed.emit()

    @Slot(bool,result=bool)
    def lookCapture(self,enabled):
        if not self._window or not isValid(self._window):return False
        if enabled and not self._window.isActive():return False
        accepted=self._window.setMouseGrabEnabled(enabled)
        self._look_capture=bool(enabled and accepted)
        return not enabled or self._look_capture

    def dispose(self):
        if self.busy:raise RuntimeError('Terrain work has not acknowledged stop')
        if isValid(self._selection_geometry):delete(self._selection_geometry)
