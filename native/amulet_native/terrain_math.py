"""Exact voxel identities and bounded camera/mesh math; no Qt or file IO."""

from dataclasses import dataclass, field, replace
import math
import re
import struct

FACE_CORNERS = {
    "xp": ((1,0,0),(1,1,0),(1,1,1),(1,0,1)),
    "xn": ((0,0,1),(0,1,1),(0,1,0),(0,0,0)),
    "yp": ((0,1,1),(1,1,1),(1,1,0),(0,1,0)),
    "yn": ((0,0,0),(1,0,0),(1,0,1),(0,0,1)),
    "zp": ((1,0,1),(1,1,1),(0,1,1),(0,0,1)),
    "zn": ((0,0,0),(0,1,0),(1,1,0),(1,0,0)),
}
FACE_NORMALS = {"xp":(1,0,0),"xn":(-1,0,0),"yp":(0,1,0),"yn":(0,-1,0),"zp":(0,0,1),"zn":(0,0,-1)}
TRIANGLES = (0,2,1,0,3,2)


def add(a,b): return tuple(x+y for x,y in zip(a,b))
def sub(a,b): return tuple(x-y for x,y in zip(a,b))
def mul(a,n): return tuple(x*n for x in a)
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def cross(a,b): return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def norm(a):
    length = math.sqrt(dot(a,a))
    if not math.isfinite(length) or length < 1e-12: raise ValueError("Invalid camera direction")
    return mul(a,1/length)


def camera_coordinate(text, axis):
    if not isinstance(text,str) or not re.fullmatch(r"-?[0-9]{1,11}",text):
        raise ValueError("Camera coordinates require signed decimal integers")
    value=int(text)
    lo,hi=(-4096,4095) if axis==1 else (-34359738368,34359738367)
    if not lo<=value<=hi: raise ValueError("Camera coordinate outside supported domain")
    return value


@dataclass
class Camera:
    target: tuple = (0.,0.,0.)
    yaw: float = 35.
    pitch: float = 30.
    distance: float = 40.
    span: float = 32.
    projection: str = "perspective"
    origin: tuple = (0,0,0)
    origin_revision: int = 0
    history: list = field(default_factory=list)

    @property
    def eye(self):
        yaw,pitch=math.radians(self.yaw),math.radians(self.pitch)
        return add(self.target,(self.distance*math.cos(pitch)*math.sin(yaw),
                                self.distance*math.sin(pitch), self.distance*math.cos(pitch)*math.cos(yaw)))

    def _validate(self):
        for value in (self.yaw,self.pitch,self.distance,self.span,*self.target):
            if type(value) not in (int,float) or not math.isfinite(value):
                raise ValueError("Nonfinite or invalid camera value")
        if not (-180<=self.yaw<=180 and -89<=self.pitch<=89 and .5<=self.distance<=2048 and 1<=self.span<=4096):
            raise ValueError("Camera projection/navigation limit reached")
        if self.projection not in ('perspective','orthographic'):
            raise ValueError("Unsupported camera projection")
        for point in (self.target,self.eye):
            if len(point)!=3: raise ValueError("Camera point requires three coordinates")
            for axis,value in enumerate(point):
                low,high=(-4096,4095) if axis==1 else (-34359738368,34359738367)
                if not math.isfinite(value) or not low<=value<=high:
                    raise ValueError("Camera eye or pivot outside supported absolute domain")
        if len(self.origin)!=3 or any(type(v) is not int for v in self.origin):
            raise ValueError("Camera render origin must be exact integers")

    def _candidate(self,remember=False,**changes):
        self._validate()
        candidate=replace(self,history=list(self.history),**changes)
        if remember:
            candidate.history=(candidate.history+[(self.target,self.yaw,self.pitch,self.distance,self.span,self.projection)])[-32:]
        return candidate

    def _commit(self,candidate):
        candidate._validate()
        eye=candidate.eye
        if any(abs(eye[i]-candidate.origin[i])>=256 for i in range(3)):
            candidate.origin=tuple(math.floor(v/256)*256 for v in eye)
            candidate.origin_revision+=1
        self.__dict__.update(candidate.__dict__)

    def back(self):
        if self.history:
            target,yaw,pitch,distance,span,projection=self.history[-1]
            candidate=self._candidate(target=target,yaw=yaw,pitch=pitch,distance=distance,span=span,projection=projection)
            candidate.history.pop()
            self._commit(candidate)

    def rebase(self):
        self._commit(self._candidate())

    def orbit(self, dx, dy):
        if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>360 for v in (dx,dy)):
            raise ValueError("Invalid camera orbit increment")
        self._commit(self._candidate(yaw=(self.yaw+dx+180)%360-180,pitch=self.pitch+dy))

    def dolly(self, steps):
        if type(steps) not in (int,float) or not math.isfinite(steps) or abs(steps)>100:
            raise ValueError("Invalid camera dolly increment")
        self._commit(self._candidate(distance=self.distance*math.exp(-steps*0.12)))

    def frame(self,bounds):
        if len(bounds)!=2 or any(len(point)!=3 for point in bounds):
            raise ValueError("Invalid camera frame bounds")
        if any(type(v) not in (int,float) or not math.isfinite(v) for point in bounds for v in point):
            raise ValueError("Nonfinite frame bounds")
        if any(bounds[0][i]>=bounds[1][i] for i in range(3)):
            raise ValueError("Empty or reversed frame bounds")
        target=tuple((bounds[0][i]+bounds[1][i])/2 for i in range(3))
        distance=max(1.,math.sqrt(sum((bounds[1][i]-bounds[0][i])**2 for i in range(3)))*1.35)
        span=max(1.,max(bounds[1][i]-bounds[0][i] for i in range(3))*1.5)
        self._commit(self._candidate(remember=True,target=target,distance=distance,span=span))

    def go(self,coords):
        if len(coords)!=3 or any(type(v) is not int for v in coords):
            raise ValueError("Go requires three exact integer coordinates")
        for axis,value in enumerate(coords):camera_coordinate(str(value),axis)
        self._commit(self._candidate(remember=True,target=sub(tuple(coords),sub(self.eye,self.target))))

    def pan(self,dx,dy):
        if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>4096 for v in (dx,dy)):
            raise ValueError("Invalid camera pan increment")
        self._validate()
        forward=norm(sub(self.target,self.eye));right=norm(cross(forward,(0,1,0)));up=cross(right,forward)
        self._commit(self._candidate(target=add(self.target,add(mul(right,dx),mul(up,dy)))))

    def ray(self,x,y,width,height):
        self._validate()
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (x,y,width,height)) or width<=0 or height<=0: raise ValueError("Viewport unavailable")
        forward=norm(sub(self.target,self.eye));right=norm(cross(forward,(0,1,0)));up=cross(right,forward)
        nx,ny=2*x/width-1,1-2*y/height
        if self.projection=="orthographic":
            origin=add(self.eye,add(mul(right,nx*self.span*width/height/2),mul(up,ny*self.span/2)))
            return origin,forward
        factor=math.tan(math.radians(30))
        return self.eye,norm(add(forward,add(mul(right,nx*factor*width/height),mul(up,ny*factor))))


def pack_faces(faces, colors, origin):
    """Faces: (world x,y,z,direction,stateId); caller bounds batch to 2048."""
    if len(faces)>2048: raise ValueError("Mesh batch exceeds face budget")
    if len(origin)!=3 or any(type(v) is not int for v in origin):raise ValueError("Mesh origin requires exact integers")
    vertices,indices=bytearray(),bytearray()
    low=[math.inf]*3;high=[-math.inf]*3
    for face in faces:
        if not isinstance(face,(tuple,list)) or len(face)!=5:raise ValueError("Invalid mesh face record")
        x,y,z,direction,state=face
        if any(type(v) is not int for v in (x,y,z,state)) or direction not in FACE_NORMALS or state not in colors:
            raise ValueError("Invalid mesh face identity")
        normal=FACE_NORMALS[direction]
        color=colors[state]
        if len(color)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in color):
            raise ValueError("Invalid finite mesh color")
        base=len(vertices)//40
        for corner in FACE_CORNERS[direction]:
            point=(x+corner[0]-origin[0],y+corner[1]-origin[1],-(z+corner[2]-origin[2]))
            if any(not math.isfinite(v) or abs(v)>8192 for v in point): raise ValueError("Scene is outside camera-relative render range")
            vertices.extend(struct.pack("<10f",*point,normal[0],normal[1],-normal[2],*color))
            low=[min(low[i],point[i]) for i in range(3)];high=[max(high[i],point[i]) for i in range(3)]
        indices.extend(struct.pack("<6I",*(base+i for i in TRIANGLES)))
    return bytes(vertices),bytes(indices),(tuple(low),tuple(high)) if faces else ((0,0,0),(0,0,0))
