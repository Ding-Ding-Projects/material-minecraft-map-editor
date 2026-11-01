"""CPU voxel traversal of accepted shape data, independent of render objects."""

import math


def ray_box(eye, direction, low, high):
    enter, leave = -math.inf, math.inf
    enter_face, leave_face = None, None
    # Stable iteration provides X, then Y, then Z tie order.
    for axis in range(3):
        if abs(direction[axis]) < 1e-15:
            if not low[axis] <= eye[axis] < high[axis]: return None
            continue
        first = (low[axis]-eye[axis])/direction[axis]
        last = (high[axis]-eye[axis])/direction[axis]
        first_face = "xyz"[axis] + "n"
        last_face = "xyz"[axis] + "p"
        if first > last:
            first,last=last,first
            first_face,last_face=last_face,first_face
        if first > enter: enter,enter_face=first,first_face
        if last < leave: leave,leave_face=last,last_face
        if leave < enter: return None
    return enter,leave,enter_face,leave_face


def pick_shape(scene, eye, direction, cut_low, cut_high):
    """Scene supplies integer bounds and cell_state(x,y,z), supported(stateId)."""
    if any(not math.isfinite(v) for v in (*eye,*direction)): return None
    low,high=scene.bounds
    low=(low[0],max(low[1],cut_low),low[2])
    high=(high[0],min(high[1],cut_high+1),high[2])
    if any(a>=b for a,b in zip(low,high)): return None
    # Reduce to the exact scene-local integer origin before traversal.
    local_eye=tuple(eye[i]-low[i] for i in range(3))
    extent=tuple(high[i]-low[i] for i in range(3))
    interval=ray_box(local_eye,direction,(0,0,0),extent)
    if interval is None or interval[1] < 0 or interval[0] > 4096: return None
    current=max(0.,interval[0])
    stop=min(4096.,interval[1])
    epsilon=1e-7
    point=tuple(local_eye[i]+direction[i]*(current+epsilon) for i in range(3))
    cell=[math.floor(v) for v in point]
    steps=[1 if v>0 else -1 if v<0 else 0 for v in direction]
    for _ in range(512):
        if any(not 0<=cell[i]<extent[i] for i in range(3)): return None
        world=tuple(cell[i]+low[i] for i in range(3))
        state=scene.cell_state(*world)
        if state is not None and scene.supported(state):
            hit=ray_box(local_eye,direction,cell,tuple(c+1 for c in cell))
            distance,face=(hit[0],hit[2]) if hit[0]>=0 else (hit[1],hit[3])
            if distance <= stop:
                return {"world":world,"stateId":state,"face":face,"distance":distance}
        crossings=[]
        for axis in range(3):
            if steps[axis]==0: crossings.append(math.inf)
            else:
                edge=cell[axis]+(1 if steps[axis]>0 else 0)
                crossings.append((edge-local_eye[axis])/direction[axis])
        next_time=min(crossings)
        if not math.isfinite(next_time) or next_time>stop: return None
        # Crossing a shared edge/corner advances all tied axes, while the
        # intersected face tie is resolved by ray_box's fixed axis ordering.
        for axis,value in enumerate(crossings):
            if abs(value-next_time)<=1e-10: cell[axis]+=steps[axis]
        current=next_time
    raise ValueError("Picking exceeded bounded traversal")


def selection_counts(scene, first, second):
    if any(type(v) is not int for v in (*first,*second)): raise ValueError("Integer selection required")
    low=tuple(min(a,b) for a,b in zip(first,second))
    high=tuple(max(a,b) for a,b in zip(first,second))
    total=math.prod(high[i]-low[i]+1 for i in range(3))
    known=supported=0
    for x,y,z,state in scene.cells():
        if all(low[i]<=v<=high[i] for i,v in enumerate((x,y,z))):
            known+=1
            supported+=int(scene.supported(state))
    return {"minimum":low,"maximum":high,"total":total,"decoded":known,
            "supportedShapes":supported,"unknown":total-known}
