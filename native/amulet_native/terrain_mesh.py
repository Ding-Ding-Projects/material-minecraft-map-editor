"""One cooperative bounded CPU mesh worker; no Qt scene objects off-thread."""

import threading
from PySide6.QtCore import QThread,Signal
from .terrain_math import pack_faces


class MeshWorker(QThread):
    batchReady=Signal(object)
    outcome=Signal(object)

    def __init__(self,scene,origin,cut,generation,parent=None):
        super().__init__(parent)
        self.scene,self.origin,self.cut,self.generation=scene,origin,cut,generation
        self.cancelled=threading.Event()
        self.capacity=threading.Semaphore(2)

    def cancel(self): self.cancelled.set()
    def acknowledge(self): self.capacity.release()

    def run(self):
        try:
            batch=[];count=0;total_bytes=0
            colors=self.scene.colors()
            for face in self.scene.faces():
                if count%256==0 and self.cancelled.is_set():
                    self.outcome.emit({"generation":self.generation,"canceled":True});return
                if not self.cut[0]<=face[1]<=self.cut[1]: continue
                batch.append(face);count+=1
                if len(batch)==2048:
                    total_bytes+=self._emit(batch,colors)
                    batch=[]
            if batch: total_bytes+=self._emit(batch,colors)
            self.outcome.emit({"generation":self.generation,"canceled":self.cancelled.is_set(),
                               "faces":count,"bytes":total_bytes})
        except (ValueError,RuntimeError) as error:
            self.outcome.emit({"generation":self.generation,"error":str(error)})

    def _emit(self,batch,colors):
        while not self.capacity.acquire(timeout=.05):
            if self.cancelled.is_set(): raise RuntimeError("Mesh canceled")
        if self.cancelled.is_set(): self.capacity.release();raise RuntimeError("Mesh canceled")
        vertices,indices,bounds=pack_faces(batch,colors,self.origin)
        self.batchReady.emit({"generation":self.generation,"vertices":vertices,"indices":indices,
                              "bounds":bounds,"origin":self.origin})
        return len(vertices)+len(indices)
