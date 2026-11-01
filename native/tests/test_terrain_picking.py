import unittest
from native.amulet_native.terrain_picking import pick_shape,selection_counts


class Scene:
    bounds=((-16,-64,-16),(0,-48,0))
    def cell_state(self,x,y,z): return 1 if (x,y,z)==(-12,-60,-12) else 2 if -16<=x<0 and -64<=y<-48 and -16<=z<0 else None
    def supported(self,state): return state==1
    def cells(self):
        for y in range(-64,-48):
            for z in range(-16,0):
                for x in range(-16,0): yield x,y,z,self.cell_state(x,y,z)


class PickingTests(unittest.TestCase):
    def test_exact_negative_shape_hit_and_inside_exit(self):
        hit=pick_shape(Scene(),(-11.5,-59.5,10),(0,0,-1),-64,-49)
        self.assertEqual(hit["world"],(-12,-60,-12));self.assertEqual(hit["face"],"zp")
        inside=pick_shape(Scene(),(-11.5,-59.5,-11.5),(1,0,0),-64,-49)
        self.assertEqual(inside["face"],"xp")

    def test_unknown_and_cut_cells_never_become_shape_hits(self):
        self.assertIsNone(pick_shape(Scene(),(-15.5,-59.5,10),(0,0,-1),-64,-49))
        self.assertIsNone(pick_shape(Scene(),(-11.5,-59.5,10),(0,0,-1),-64,-61))

    def test_selection_counts_keep_unknown_volume(self):
        counts=selection_counts(Scene(),(-17,-64,-16),(-12,-60,-12))
        self.assertEqual(counts["total"],150)
        self.assertEqual(counts["decoded"],125)
        self.assertEqual(counts["supportedShapes"],1)
        self.assertEqual(counts["unknown"],25)
