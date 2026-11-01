"""Exact voxel identities and bounded camera/mesh math; no Qt or file IO."""

from dataclasses import dataclass, field
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

    def remember(self):
        self.history.append((self.target,self.yaw,self.pitch,self.distance,self.span,self.projection))
        self.history=self.history[-32:]

    def back(self):
        if self.history:
            self.target,self.yaw,self.pitch,self.distance,self.span,self.projection=self.history.pop()
            self.rebase()

    def rebase(self):
        eye=self.eye
        if any(not math.isfinite(v) for v in eye): raise ValueError("Nonfinite camera")
        if any(abs(eye[i]-self.origin[i])>=256 for i in range(3)):
            self.origin=tuple(math.floor(v/256)*256 for v in eye)
            self.origin_revision+=1

    def orbit(self, dx, dy):
        pitch=self.pitch+dy
        if not -89<=pitch<=89: raise ValueError("Camera pitch limit reached")
        self.yaw=(self.yaw+dx+180)%360-180
        self.pitch=pitch
        self.rebase()

    def dolly(self, steps):
        distance=self.distance*math.exp(-steps*0.12)
        if not .5<=distance<=2048: raise ValueError("Camera distance limit reached")
        self.distance=distance
        self.rebase()

    def frame(self,bounds):
        self.remember()
        self.target=tuple((bounds[0][i]+bounds[1][i])/2 for i in range(3))
        self.distance=max(1.,math.sqrt(sum((bounds[1][i]-bounds[0][i])**2 for i in range(3)))*1.35)
        self.span=max(1.,max(bounds[1][i]-bounds[0][i] for i in range(3))*1.5)
        self.rebase()

    def go(self,coords):
        self.remember()
        # Go sets the camera location, keeping its direction and orbit distance.
        offset=sub(self.eye,self.target)
        self.target=sub(tuple(coords),offset)
        self.rebase()

    def pan(self,dx,dy):
        forward=norm(sub(self.target,self.eye)); right=norm(cross(forward,(0,1,0))); up=cross(right,forward)
        shift=add(mul(right,dx),mul(up,dy))
        candidate=add(self.eye,shift)
        if any(not (-4096<=candidate[i]<=4095 if i==1 else -34359738368<=candidate[i]<=34359738367) for i in range(3)):
            raise ValueError("Camera navigation limit reached")
        self.target=add(self.target,shift);self.rebase()

    def ray(self,x,y,width,height):
        if width<=0 or height<=0: raise ValueError("Viewport unavailable")
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
    vertices,indices=bytearray(),bytearray()
    low=[math.inf]*3;high=[-math.inf]*3
    for face in faces:
        x,y,z,direction,state=face
        normal=FACE_NORMALS[direction]
        color=colors[state]
        base=len(vertices)//40
        for corner in FACE_CORNERS[direction]:
            point=(x+corner[0]-origin[0],y+corner[1]-origin[1],-(z+corner[2]-origin[2]))
            if any(abs(v)>8192 for v in point): raise ValueError("Scene is outside camera-relative render range")
            vertices.extend(struct.pack("<10f",*point,normal[0],normal[1],-normal[2],*color))
            low=[min(low[i],point[i]) for i in range(3)];high=[max(high[i],point[i]) for i in range(3)]
        indices.extend(struct.pack("<6I",*(base+i for i in TRIANGLES)))
    return bytes(vertices),bytes(indices),(tuple(low),tuple(high)) if faces else ((0,0,0),(0,0,0))
