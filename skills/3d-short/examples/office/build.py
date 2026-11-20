"""Example: painted toon office (basement storeroom) as one still, in the toon.py style.

  blender --background --python build.py -- <workdir> [--lines 0] [--line-style sobel|freestyle] [--character 1] [--post 0]
Output: <workdir>/office.png (1080x1920). --post 0 renders only the raw toon shading (no lines, painterly
filter, glow or finish); --lines 0 keeps everything but the outline — handy to judge each layer on its own.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_scripts(here):
    import glob
    for c in (os.environ.get("KYLO_SCRIPTS", ""), os.path.join(here, "..", "..", "scripts"), os.path.join(here, "scripts")):
        if c and os.path.exists(os.path.join(c, "toon.py")):
            return os.path.abspath(c)
    hits = sorted(glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/kylo-3d-shorts/*/skills/3d-short/scripts")))
    if hits:
        return hits[-1]
    raise SystemExit("set KYLO_SCRIPTS=<plugin>/skills/3d-short/scripts")


sys.path.insert(0, _find_scripts(HERE))
import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402
import toon  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
WORK = argv[0] if argv else "."
OPT = dict(zip(argv[1::2], argv[2::2]))
POST = OPT.get("--post", "1") != "0"
LINES = OPT.get("--lines", "1") != "0"
LINE_STYLE = OPT.get("--line-style", "sobel")       # sobel | freestyle
CHARACTER = OPT.get("--character", "0") != "0"

# ---------------------------------------------------------------- palette (from the reference)
C = dict(ceiling="#a2867f", wall="#d6bab2", wall2="#c4a49c", dado="#3d4049", floorA="#7a6460", floorB="#3b3e47",
         box="#8d604f", lid="#5e4137", desk="#d3c6c3", metal="#8b8a90", pipe="#6c6670", plant="#b8bf5c",
         pot="#8a5a45", orange="#d38d56", black="#26262b", paper="#ead9d6", light="#fff4f0", shirt="#c4673f",
         pants="#3c3f4a", skin="#e3b49b", hair="#3a2a28", teal="#2f8ea3", screen="#1d1d22", frame="#9c6f55")

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE"
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = 1080, 1920, 100
for attr, val in (("use_shadows", True), ("shadow_ray_count", 2), ("shadow_step_count", 8), ("use_raytracing", False)):
    if hasattr(sc.eevee, attr):
        setattr(sc.eevee, attr, val)

_mats = {}


def M(c):
    if c not in _mats:
        _mats[c] = toon.material(c)
    return _mats[c]


def T(x, y, z):
    """three.js coordinates (y up, -z forward) -> Blender (z up)."""
    return Vector((x, -z, y))


def box(w, h, d, x, y, z, color, ry=0.0, name="box"):
    """Box w(x) h(up) d(depth) centred at three.js (x, y, z), turned ry around the vertical."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=T(x, y, z), rotation=(0, 0, ry))
    o = bpy.context.object
    o.name = name
    o.scale = (w, d, h)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(M(color) if isinstance(color, str) else color)
    return o


def cyl(r, h, x, y, z, color, r2=None, verts=16, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r, radius2=r if r2 is None else r2, depth=h,
                                    location=T(x, y, z), rotation=rot)
    o = bpy.context.object
    o.data.materials.append(M(color))
    bpy.ops.object.shade_smooth()
    return o


def ball(r, x, y, z, color, scale=(1, 1, 1)):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=20, ring_count=12, location=T(x, y, z))
    o = bpy.context.object
    o.scale = scale
    o.data.materials.append(M(color))
    bpy.ops.object.shade_smooth()
    return o


def capsule(r, length, x, y, z, color, rot=(0, 0, 0), scale=(1, 1, 1)):
    """Vertical capsule (three.js CapsuleGeometry: `length` is the straight middle part)."""
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, segments=20, ring_count=14, location=(0, 0, 0))
    o = bpy.context.object
    for v in o.data.vertices:
        v.co.z += length / 2 if v.co.z > 1e-4 else (-length / 2 if v.co.z < -1e-4 else 0)
    o.location = T(x, y, z)
    o.rotation_euler = rot
    o.scale = scale
    o.data.materials.append(M(color))
    bpy.ops.object.shade_smooth()
    return o


# ---------------------------------------------------------------- room
floor_mat = toon.material("#ffffff", "floor", checker=(C["floorA"], C["floorB"]), checker_size=1.4)
box(10, 0.02, 13, 0, -0.01, -0.5, floor_mat, name="floor")
box(10, 0.02, 13, 0, 3.61, -0.5, C["ceiling"], name="ceiling")
WALL = toon.material(C["wall"], "wall", flat=0.5)     # flat: broad bands, not rings around the lamp
WALL2 = toon.material(C["wall2"], "wall2", flat=0.5)
box(10, 3.6, 0.1, 0, 1.8, -6, WALL, name="wall_back")
box(0.1, 3.6, 13, -5, 1.8, -0.5, WALL2, name="wall_left")
box(0.1, 3.6, 13, 5, 1.8, -0.5, WALL2, name="wall_right")
box(10, 1.05, 0.12, 0, 0.525, -5.95, C["dado"], name="dado")
box(0.12, 1.05, 13, -4.95, 0.525, -0.5, C["dado"])
box(0.12, 1.05, 13, 4.95, 0.525, -0.5, C["dado"])
box(10, 0.05, 0.16, 0, 1.07, -5.93, C["wall2"], name="moulding")
box(0.9, 3.6, 0.9, 0.9, 1.8, -5.6, WALL2, name="pillar")
# fluorescent panel + glow cone + the actual light
box(1.5, 0.05, 0.55, -1.3, 3.57, -1.6, toon.material("#fff", "tube", emission=C["light"]), name="tube")
bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=2.2, radius2=0.45, depth=3.5, end_fill_type="NOTHING",
                                location=T(-1.3, 1.8, -1.6))
glow = bpy.context.object
glow.name = "glow"
glow.data.materials.append(toon.glow_material(C["light"], 0.11))
toon.no_lines(glow)
# a big soft area light: wide, gentle falloff -> few broad tone bands on the walls instead of tight rings
bpy.ops.object.light_add(type="AREA", location=T(-1.3, 3.5, -1.6))
lamp = bpy.context.object
lamp.data.shape, lamp.data.size, lamp.data.size_y = "RECTANGLE", 3.2, 1.6
lamp.data.energy, lamp.data.color = 1000, (1.0, 0.94, 0.9)
# light pool on the ceiling around the fitting (the area light only shines down)
bpy.ops.object.light_add(type="POINT", location=T(-1.3, 3.3, -1.6))
pool = bpy.context.object
pool.data.energy, pool.data.color, pool.data.shadow_soft_size = 70, (1.0, 0.92, 0.88), 0.3
bpy.ops.object.light_add(type="SUN")
sun = bpy.context.object
sun.data.energy, sun.data.color, sun.data.angle = 1.6, (1.0, 0.91, 0.87), math.radians(6)
sun.rotation_euler = (Vector((0, 0, 0)) - T(-3, 9, 6)).to_track_quat("-Z", "Y").to_euler()
# pipes, duct, vent panel
for x in (2.0, 2.65, 2.9):
    cyl(0.07, 3.1, x, 1.75, -5.82, C["pipe"], verts=10)
box(3.5, 0.2, 0.25, 3.0, 3.25, -4.0, C["pipe"], ry=-0.4, name="duct")
box(0.9, 0.8, 0.05, 4.3, 2.9, -5.9, "#5a4544")
# filing cabinet
box(0.75, 1.3, 0.65, -2.7, 0.65, -5.55, C["metal"], name="cabinet")
for y in (0.45, 0.95):
    box(0.25, 0.05, 0.04, -2.7, y, -5.2, C["black"])
# picture
box(0.75, 0.55, 0.04, -0.6, 2.2, -5.92, C["frame"])
box(0.62, 0.42, 0.05, -0.6, 2.2, -5.9, C["paper"])
# plant
cyl(0.22, 0.42, -1.7, 0.21, -5.3, C["pot"], r2=0.16)
for i in range(9):
    o = cyl(0.07, 0.75, -1.7, 0.75, -5.3, C["plant"], r2=0.0, verts=4,
            rot=(math.cos(i * 2.4) * 0.7, math.sin(i * 2.4) * 0.7, i * 0.7))
# L desk, monitors, chair
box(2.8, 0.07, 0.85, 2.9, 0.78, -3.4, C["desk"], name="desk")
box(0.85, 0.07, 2.0, 4.05, 0.78, -2.3, C["desk"])
box(2.8, 0.74, 0.05, 2.9, 0.4, -3.8, C["desk"])
box(0.05, 0.74, 2.0, 4.45, 0.4, -2.3, C["desk"])
for x in (2.3, 3.3):
    box(0.75, 0.45, 0.05, x, 1.15, -3.6, C["screen"], name="monitor")
    box(0.06, 0.2, 0.06, x, 0.9, -3.6, C["black"])


def chair(x, z, ry):
    cyl(0.27, 0.07, x, 0.5, z, C["orange"], verts=20)
    box(0.45, 0.5, 0.06, x - math.sin(ry) * 0.25, 0.82, z - math.cos(ry) * 0.25, C["black"], ry=-ry)
    cyl(0.03, 0.45, x, 0.26, z, C["black"], verts=8)
    for i in range(5):
        a = i * 1.256
        box(0.32, 0.04, 0.05, x + math.cos(a) * 0.15, 0.05, z - math.sin(a) * 0.15, C["black"], ry=a)


chair(3.0, -2.6, 0)


def cardboard(x, z, ry, y=0.0):
    box(0.62, 0.36, 0.44, x, y + 0.18, z, C["box"], ry=-ry, name="cardbox")
    box(0.65, 0.07, 0.47, x, y + 0.39, z, C["lid"], ry=-ry, name="lid")


for x, z, r in ((-3.9, 0.4, 0.3), (-3.4, 0.9, -0.2), (-2.6, 1.9, 0.5), (-0.4, -2.5, 0.2), (0.4, -2.9, -0.4),
                (0.9, -1.6, 0.9), (0.7, 0.2, 0.1), (0.5, 1.6, -0.3), (3.0, 0.3, 0.3), (3.7, 0.9, -0.2)):
    cardboard(x, z, r)
cardboard(3.3, 0.55, 0.1, 0.43)
cardboard(4.4, -3.5, 0, 1.62)
cardboard(4.4, -3.6, 0.2, 2.05)
for x, z, r in ((0.0, -2.0, 0.4), (3.2, 1.5, -0.3), (2.8, 1.75, 0.8)):
    box(0.3, 0.004, 0.4, x, 0.012, z, C["paper"], ry=-r, name="paper")
# tall cabinets on the right
box(0.8, 1.9, 0.9, 4.5, 0.95, -1.0, "#d9d1cb")
box(0.8, 2.2, 0.9, 4.5, 1.1, 0.1, "#a9a3a6")
# foreground table with tablet, pencil and chair back
box(4, 0.08, 1.0, 0.4, 0.98, 5.6, "#b9a7a3", name="table")
box(0.36, 0.02, 0.26, 0.45, 1.03, 5.45, C["teal"], ry=0.15)
box(0.32, 0.025, 0.22, 0.45, 1.033, 5.45, "#d89a4a", ry=0.15)
cyl(0.022, 0.45, -0.25, 1.045, 5.5, "#cfd4dc", verts=10, rot=(0, math.pi / 2, -0.5))
capsule(0.32, 0.35, -0.9, 0.95, 4.6, C["orange"], rot=(0, -0.1, 0), scale=(0.8, 0.25, 0.75))

# ---------------------------------------------------------------- character (simple, off by default)
if CHARACTER:
    P = T(-1.0, 0, -1.4)
    parts = [
        capsule(0.09, 0.62, -0.11, 0.42, 0, C["pants"]),
        capsule(0.09, 0.62, 0.11, 0.42, 0, C["pants"]),
        capsule(0.2, 0.42, 0, 1.13, 0, C["shirt"]),
        capsule(0.065, 0.5, -0.27, 1.08, 0, C["shirt"], rot=(0, -0.12, 0)),
        capsule(0.065, 0.5, 0.27, 1.08, 0, C["shirt"], rot=(0, 0.12, 0)),
        ball(0.15, 0, 1.6, 0, C["skin"]),
        ball(0.155, 0, 1.66, -0.02, C["hair"], scale=(1, 1, 0.7)),
        ball(0.026, -0.05, 1.62, 0.14, "#2a2224"),
        ball(0.026, 0.05, 1.62, 0.14, "#2a2224"),
    ]
    bpy.ops.object.empty_add(location=P, rotation=(0, 0, -0.25))
    rig = bpy.context.object
    for o in parts:
        o.parent = rig

# ---------------------------------------------------------------- camera
bpy.ops.object.camera_add(location=T(0.3, 1.75, 7.2))
cam = bpy.context.object
cam.rotation_euler = (T(0.4, 1.3, -2) - cam.location).to_track_quat("-Z", "Y").to_euler()
cam.data.sensor_fit = "VERTICAL"
cam.data.angle = math.radians(58)
cam.data.clip_start, cam.data.clip_end = 0.05, 60
sc.camera = cam

# ---------------------------------------------------------------- style + render
if POST:
    toon.setup(sc, world="#8a7898", world_strength=0.55, lines=LINE_STYLE if LINES else None)
else:
    toon.setup(sc, world="#8a7898", world_strength=0.55, glare=False, lines=None)
    sc.compositing_node_group = None          # raw toon shading only (no lines, filter or finish)
    sc.render.use_single_layer = True
FRAME = int(os.environ.get("FRAME", "1"))      # the line noise "boils" every 2 frames (toon.setup boil=2)
sc.frame_set(FRAME)
out = os.path.join(os.path.abspath(WORK), "office.png" if FRAME == 1 else f"office_f{FRAME:04d}.png")
if POST:
    toon.render_still(out, sc)
else:
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = out
    bpy.ops.render.render(write_still=True)
print("SAVED", out)
