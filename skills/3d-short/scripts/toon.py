"""Painted toon look for Blender/EEVEE ("illustrated explainer" style). Works for stills and animation.

  import toon
  mat = toon.material("#d6bab2")        # flat 4-tone material (cool shadows, warm lights, contact shadows)
  toon.toonify()                        # ... or convert the existing materials of a scene (s3d builds)
  toon.no_lines(obj)                    # glow cones etc.: own layer, composited on top
  toon.setup(scene)                     # colour management, world, lines, compositor (everything below)
  toon.render_still(path)               # or s3d.render_mp4(...): the look is all in the compositor

How the look is made
- Flat colours: each material quantises the light it receives into 4 fixed tones (ColorRamp CONSTANT),
  tinted mauve in shadow and warm in light. Ambient occlusion goes into the light *before* the ramp, so
  contact shadows (box on floor, cabinet against wall) are flat patches too.
- Lines (default "object"): geometric outline computed from the meshes and the camera (Freestyle:
  silhouettes, borders, creases), so it is exact and stable in animation. Strokes lie INSIDE the object
  they outline and are coloured with that object's own lit colour, darker (HSV value x0.62) and a bit
  richer (saturation x1.18): a subtle line in the object's tone, never black. Brush taper at both ends,
  thinner with distance, no noise. Tune with the OUTLINE_* constants.
  Alternative lines="sobel": screen-space edges from the depth/normal passes, sketchier; boil=N changes
  their noise every N frames so they "boil" in a video instead of sliding.
- Painted fill: compositor Kuwahara groups colours into brush-like patches; depth haze lifts the back of
  the scene towards `haze_color`; glare puts a halo around lamps (emission strength > 1.2).
- Finish (compositor, so every video frame gets it): paper grain, faint brush streaks, vignette.
"""
import os

import bpy

# 4 light levels (cool -> warm). Multiplied with the base colour.
TONES = ((0.0, (0.50, 0.44, 0.58)),
         (0.18, (0.70, 0.63, 0.72)),
         (0.42, (0.89, 0.84, 0.86)),
         (0.75, (1.00, 0.97, 0.94)))
AO_DISTANCE = 0.9       # m: how far contact shadows reach
AO_STRENGTH = 0.7       # 0 = off, 1 = full occlusion darkens to black before the ramp
AO_RANGE = (0.78, 0.98)  # raw AO -> full occlusion .. none (EEVEE: open floor ~1.0, contacts ~0.83-0.9)
CONTACT = (0.62, 0.55, 0.70)  # flat contact-shadow multiplier (cool mauve) where AO is past half the range
NO_LINES = "toon_overlay"       # glow cones etc.: own view layer, no outline, composited on top
OVERLAY_LAYER = "toon_overlay"
LINES_LAYER = "toon_lines"


def lin(hex_or_rgb):
    """'#rrggbb' (sRGB) -> linear RGBA for node sockets."""
    if isinstance(hex_or_rgb, str):
        h = hex_or_rgb.lstrip("#")
        c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    else:
        c = list(hex_or_rgb)[:3]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return (*c, 1.0)


# ---------------------------------------------------------------- materials
def _ramp(nt, x, y):
    r = nt.nodes.new("ShaderNodeValToRGB")
    r.location = (x, y)
    r.color_ramp.interpolation = "CONSTANT"
    els = r.color_ramp.elements
    while len(els) < len(TONES):
        els.new(0.5)
    for e, (pos, col) in zip(els, TONES):
        e.position, e.color = pos, (*col, 1.0)
    return r


def _shade(nt, base, x=0, y=0, flat=0.0, level=0.5):
    """Toon shading graph inside material tree `nt`. base: a colour socket or an RGBA tuple.
    flat (0..1) squeezes the received light towards `level` before the 4 tones: big surfaces lit by a
    nearby lamp (walls) then get one or two broad bands instead of concentric rings.
    Returns the Emission node's shader output."""
    N, L = nt.nodes, nt.links
    dif = N.new("ShaderNodeBsdfDiffuse")
    dif.location = (x - 600, y)
    s2r = N.new("ShaderNodeShaderToRGB")
    s2r.location = (x - 420, y)
    bw = N.new("ShaderNodeRGBToBW")
    bw.location = (x - 260, y)
    L.new(dif.outputs[0], s2r.inputs[0])
    L.new(s2r.outputs["Color"], bw.inputs[0])
    light = bw.outputs[0]
    if AO_STRENGTH > 0:
        ao = N.new("ShaderNodeAmbientOcclusion")
        ao.location = (x - 420, y - 200)
        ao.inputs["Distance"].default_value = AO_DISTANCE
        mr = N.new("ShaderNodeMapRange")
        mr.location = (x - 260, y - 200)
        L.new(ao.outputs["AO"], mr.inputs["Value"])
        mr.clamp = True
        # EEVEE's horizon-scan AO is faint (contacts ~0.85-0.9): stretch AO_RANGE to the full 0..1
        mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = AO_RANGE
        mr.inputs["To Min"].default_value = 1.0 - AO_STRENGTH
        mul = N.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.location = (x - 100, y - 100)
        L.new(light, mul.inputs[0])
        L.new(mr.outputs["Result"], mul.inputs[1])
        light = mul.outputs[0]
    if flat > 0:
        sq = N.new("ShaderNodeMapRange")
        sq.clamp = False
        sq.location = (x - 50, y - 250)
        L.new(light, sq.inputs["Value"])
        sq.inputs["To Min"].default_value = level * flat
        sq.inputs["To Max"].default_value = 1.0 - (1.0 - level) * flat
        light = sq.outputs["Result"]
    ramp = _ramp(nt, x + 50, y)
    L.new(light, ramp.inputs["Fac"])
    col = N.new("ShaderNodeMix")
    col.data_type, col.blend_type = "RGBA", "MULTIPLY"
    col.location = (x + 350, y)
    col.inputs["Factor"].default_value = 1.0
    if isinstance(base, tuple):
        col.inputs[6].default_value = base
    else:
        L.new(base, col.inputs[6])
    L.new(ramp.outputs["Color"], col.inputs[7])
    shaded = col.outputs[2]
    if AO_STRENGTH > 0:
        # contact shadow as one flat patch on top of the tones (a brightly lit floor would otherwise only
        # drop a single tone, which barely reads)
        cr = N.new("ShaderNodeMapRange")
        cr.clamp = True
        L.new(ao.outputs["AO"], cr.inputs["Value"])
        cr.inputs["From Min"].default_value, cr.inputs["From Max"].default_value = AO_RANGE
        step = N.new("ShaderNodeValToRGB")
        step.color_ramp.interpolation = "CONSTANT"
        e0, e1 = step.color_ramp.elements
        e0.position, e0.color = 0.0, (*CONTACT, 1.0)
        e1.position, e1.color = 0.5, (1.0, 1.0, 1.0, 1.0)
        L.new(cr.outputs["Result"], step.inputs["Fac"])
        cm = N.new("ShaderNodeMix")
        cm.data_type, cm.blend_type = "RGBA", "MULTIPLY"
        cm.inputs["Factor"].default_value = 1.0
        L.new(shaded, cm.inputs[6])
        L.new(step.outputs["Color"], cm.inputs[7])
        shaded = cm.outputs[2]
    em = N.new("ShaderNodeEmission")
    em.location = (x + 550, y)
    L.new(shaded, em.inputs["Color"])
    return em.outputs[0]


def material(color, name=None, checker=None, checker_size=1.4, emission=None, strength=4.0, flat=0.0):
    """Flat toon material. color: '#hex'. checker=('#hexA', '#hexB') makes a floor of squares
    `checker_size` metres wide. emission='#hex' makes an unlit glowing surface (lamps); `strength` > 1.2
    makes the compositor glare put a halo around it. flat=0.3..0.6 for walls (fewer, broader bands)."""
    m = bpy.data.materials.new(name or f"toon_{color}")
    m.use_nodes = True
    m["toon"] = 1
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (1100, 0)
    if emission:
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = lin(emission)
        em.inputs["Strength"].default_value = strength
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        return m
    base = lin(color)
    if checker:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        tc.location = (-200, 300)
        ck = nt.nodes.new("ShaderNodeTexChecker")
        ck.location = (150, 300)
        ck.inputs["Color1"].default_value = lin(checker[0])
        ck.inputs["Color2"].default_value = lin(checker[1])
        ck.inputs["Scale"].default_value = 1.0 / checker_size   # checker: one square per 1/scale units
        nt.links.new(tc.outputs["Object"], ck.inputs["Vector"])
        base = ck.outputs["Color"]
    nt.links.new(_shade(nt, base, 400, 0, flat=flat), out.inputs["Surface"])
    return m


def toonify(materials=None, keep=()):
    """Convert existing materials (Principled / Diffuse, e.g. s3d's photo textures) to toon shading in
    place. The base colour keeps whatever feeds it (image textures, tints), alpha cut-outs (grass cards,
    leaves) keep working, emissive and already-toon materials are left alone. Returns the converted names."""
    done = []
    for m in materials or bpy.data.materials:
        if m.get("toon") or m.name in keep or not m.use_nodes or not m.node_tree:
            continue
        nt = m.node_tree
        out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        if not out or not out.inputs["Surface"].is_linked:
            continue
        bsdf = out.inputs["Surface"].links[0].from_node
        if bsdf.type not in ("BSDF_PRINCIPLED", "BSDF_DIFFUSE"):
            continue
        if bsdf.type == "BSDF_PRINCIPLED":
            es = bsdf.inputs.get("Emission Strength")
            if es and (es.is_linked or es.default_value > 0):
                continue
        bc = bsdf.inputs.get("Base Color") or bsdf.inputs.get("Color")
        base = bc.links[0].from_socket if bc.is_linked else tuple(bc.default_value)
        x, y = bsdf.location
        shader = _shade(nt, base, x, y - 400)
        alpha = bsdf.inputs.get("Alpha")
        if alpha is not None and (alpha.is_linked or alpha.default_value < 1.0):
            tr = nt.nodes.new("ShaderNodeBsdfTransparent")
            mix = nt.nodes.new("ShaderNodeMixShader")
            if alpha.is_linked:
                nt.links.new(alpha.links[0].from_socket, mix.inputs[0])
            else:
                mix.inputs[0].default_value = alpha.default_value
            nt.links.new(tr.outputs[0], mix.inputs[1])
            nt.links.new(shader, mix.inputs[2])
            shader = mix.outputs[0]
        nt.links.new(shader, out.inputs["Surface"])
        m["toon"] = 1
        done.append(m.name)
    return done


def glow_material(color="#fff4f0", alpha=0.08, falloff=1.6):
    """Transparent glow for light cones, strongest at the top and fading towards the open end
    (generated Z: 0 at the bottom of the object, 1 at the top). Put the object in no_lines()."""
    m = bpy.data.materials.new("toon_glow")
    m.use_nodes = True
    m["toon"] = 1
    nt = m.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputMaterial")
    em = N.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = lin(color)
    tr = N.new("ShaderNodeBsdfTransparent")
    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Generated"], sep.inputs[0])
    pw = N.new("ShaderNodeMath")
    pw.operation = "POWER"
    L.new(sep.outputs["Z"], pw.inputs[0])
    pw.inputs[1].default_value = falloff
    a = N.new("ShaderNodeMath")
    a.operation = "MULTIPLY"
    L.new(pw.outputs[0], a.inputs[0])
    a.inputs[1].default_value = alpha
    mix = N.new("ShaderNodeMixShader")
    L.new(a.outputs[0], mix.inputs[0])
    L.new(tr.outputs[0], mix.inputs[1])
    L.new(em.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], out.inputs["Surface"])
    for attr, val in (("surface_render_method", "BLENDED"), ("use_transparency_overlap", False)):
        if hasattr(m, attr):
            setattr(m, attr, val)
    return m


def no_lines(obj):
    """Render `obj` (a glow cone, haze...) in a separate layer composited over the image: it gets no
    outline and does not hide the outlines of what is inside it."""
    col = bpy.data.collections.get(NO_LINES) or bpy.data.collections.new(NO_LINES)
    if NO_LINES not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    col.objects.link(obj)
    for c in list(obj.users_collection):
        if c != col:
            c.objects.unlink(obj)
    obj.visible_shadow = False


# ---------------------------------------------------------------- object-space outline (lines="object")
OUTLINE_WIDTH = 3.2       # px at 1080 wide, middle of a stroke close to the camera
OUTLINE_TAPER = 0.3       # stroke width at its ends, as a fraction of the middle (brush taper)
OUTLINE_FAR = (4.0, 18.0, 0.7)    # (near m, far m, width factor at far)
OUTLINE_VALUE = 0.62      # HSV value multiplier of the object's own colour -> line colour
OUTLINE_SAT = 1.18        # HSV saturation multiplier (darker tones of a colour are richer, not greyer)
OUTLINE_OPACITY = 0.9


def _lines(scene, px):
    """Geometric outline (Freestyle): silhouettes, borders and creases computed from the meshes and the
    camera, not guessed from pixels, so they are exact, antialiased and stable from frame to frame.
    Strokes are drawn INSIDE the silhouette, so every line lies on the object it outlines; the
    compositor uses the stroke only as a mask and colours it with that object's own (lit) colour, darker.
    Own view layer: in Blender 5.x Freestyle strokes also land in the layer's combined image."""
    scene.render.use_freestyle = True
    scene.render.line_thickness_mode = "ABSOLUTE"
    scene.render.line_thickness = 1.0
    scene.view_layers[0].use_freestyle = False
    vl = scene.view_layers.get(LINES_LAYER) or scene.view_layers.new(LINES_LAYER)
    vl.use_freestyle = True
    vl.samples = 1                                   # only the stroke pass of this layer is used
    fs = vl.freestyle_settings
    fs.as_render_pass = True
    fs.crease_angle = 2.4                            # radians (~137 deg): real corners only, not smooth shading
    ls = fs.linesets[0] if len(fs.linesets) else fs.linesets.new("toon")
    ls.select_by_visibility = True
    ls.visibility = "VISIBLE"
    ls.select_by_edge_types = True
    for t in ("silhouette", "border", "crease", "external_contour"):
        setattr(ls, f"select_{t}", True)
    for t in ("contour", "suggestive_contour", "ridge_valley", "material_boundary", "edge_mark"):
        setattr(ls, f"select_{t}", False)
    ls.select_by_collection = False
    if ls.linestyle is None:
        ls.linestyle = bpy.data.linestyles.new("toon_line")
    st = ls.linestyle
    st.color = (1.0, 1.0, 1.0)                       # mask only; the colour is made in the compositor
    st.alpha = 1.0
    st.thickness = OUTLINE_WIDTH * px
    st.thickness_position = "INSIDE"                 # on the object it outlines, never on the background
    st.caps = "ROUND"
    st.use_chaining = True
    st.chaining = "PLAIN"
    st.use_same_object = True                        # a stroke never runs from one object onto another
    st.use_dashed_line = False
    for coll in (st.thickness_modifiers, st.alpha_modifiers, st.geometry_modifiers, st.color_modifiers):
        for mod in list(coll):
            coll.remove(mod)
    # brush taper: thin at both ends, full in the middle (smooth curve along the stroke)
    tp = st.thickness_modifiers.new("taper", "ALONG_STROKE")
    tp.mapping, tp.blend = "CURVE", "MULTIPLY"
    cm = tp.curve
    pts = cm.curves[0].points
    pts[0].location = (0.0, OUTLINE_TAPER)
    pts[1].location = (1.0, OUTLINE_TAPER)
    pts.new(0.18, 1.0)
    pts.new(0.82, 1.0)
    for p in pts:
        p.handle_type = "AUTO"
    cm.update()
    # constant on screen up close, thinner further away (perspective, not a blur)
    d = st.thickness_modifiers.new("depth", "DISTANCE_FROM_CAMERA")
    d.range_min, d.range_max = OUTLINE_FAR[0], OUTLINE_FAR[1]
    d.value_min, d.value_max, d.blend = 1.0, OUTLINE_FAR[2], "MULTIPLY"


def _overlay_layer(scene):
    """Main layer without the overlay collection; overlay layer = that collection only, the rest held out."""
    col = bpy.data.collections.get(NO_LINES)
    if not col or not col.objects or NO_LINES not in scene.collection.children:
        return None
    loose = list(scene.collection.objects)       # objects linked straight to the scene collection
    if loose:
        mc = bpy.data.collections.new("toon_main")
        scene.collection.children.link(mc)
        for o in loose:
            mc.objects.link(o)
            scene.collection.objects.unlink(o)
    for name in (scene.view_layers[0].name, LINES_LAYER):
        if name in scene.view_layers:
            scene.view_layers[name].layer_collection.children[NO_LINES].exclude = True
    ov = scene.view_layers.get(OVERLAY_LAYER) or scene.view_layers.new(OVERLAY_LAYER)
    ov.use_freestyle = False
    for lc in ov.layer_collection.children:
        lc.exclude = False
        lc.holdout = lc.name != NO_LINES
    scene.render.film_transparent = True        # overlay needs alpha; the room hides the world anyway
    return ov


# ---------------------------------------------------------------- compositor
def _set_in(node, names, val):
    for nm in names:
        if nm in node.inputs:
            node.inputs[nm].default_value = val
            return True
        if hasattr(node, nm.lower().replace(" ", "_")):
            setattr(node, nm.lower().replace(" ", "_"), val)
            return True
    return False


class _G:
    """Small helper to build compositor graphs with math/shader nodes."""

    def __init__(self, ng, rl, px, boil):
        self.ng, self.N, self.L, self.rl, self.px = ng, ng.nodes, ng.links, rl, px
        self._step = None
        if boil:
            t = self.N.new("CompositorNodeSceneTime")
            self._step = self.math("FLOOR", self.math("DIVIDE", t.outputs["Frame"], float(boil)))

    def math(self, op, a, b=None):
        n = self.N.new("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                self.L.new(v, n.inputs[i])
        return n.outputs[0]

    def mrange(self, v, a, b, lo=0.0, hi=1.0, smooth=False):
        n = self.N.new("ShaderNodeMapRange")
        n.clamp = True
        if smooth:
            n.interpolation_type = "SMOOTHSTEP"
        self.L.new(v, n.inputs["Value"])
        n.inputs["From Min"].default_value, n.inputs["From Max"].default_value = a, b
        n.inputs["To Min"].default_value, n.inputs["To Max"].default_value = lo, hi
        return n.outputs["Result"]

    def vec(self, op, a, b):
        n = self.N.new("ShaderNodeVectorMath")
        n.operation = op
        self.L.new(a, n.inputs[0])
        if isinstance(b, (int, float)):
            n.inputs["Scale"].default_value = b
        elif isinstance(b, tuple):
            n.inputs[1].default_value = b
        else:
            self.L.new(b, n.inputs[1])
        return n.outputs[0]

    def coords(self, kind="Pixel"):
        ic = self.N.new("CompositorNodeImageCoordinates")
        self.L.new(self.rl.outputs["Image"], ic.inputs["Image"])
        return ic.outputs[kind]

    def noise(self, scale_px, seed, stretch=(1.0, 1.0), boil=True, detail=1.0):
        """Smooth screen-space noise node. stretch=(sx, sy) makes it anisotropic (brush streaks).
        boil: the pattern jumps to a new one every `boil` frames (setup(boil=...))."""
        v = self.vec("MULTIPLY", self.coords(), (1.0 / (scale_px * stretch[0] * self.px),
                                                 1.0 / (scale_px * stretch[1] * self.px), 0.0))
        nz = self.N.new("ShaderNodeTexNoise")
        nz.noise_dimensions = "4D"
        nz.inputs["Scale"].default_value = 1.0
        nz.inputs["Detail"].default_value = detail
        self.L.new(v, nz.inputs["Vector"])
        if boil and self._step is not None:
            self.L.new(self.math("ADD", self.math("MULTIPLY", self._step, 7.31), seed), nz.inputs["W"])
        else:
            nz.inputs["W"].default_value = seed
        return nz

    def mix(self, fac, a, b, blend="MIX"):
        n = self.N.new("ShaderNodeMix")
        n.data_type, n.blend_type = "RGBA", blend
        for sock, v in ((n.inputs["Factor"], fac), (n.inputs[6], a), (n.inputs[7], b)):
            if isinstance(v, (int, float)):
                sock.default_value = v
            elif isinstance(v, tuple):
                sock.default_value = v
            else:
                self.L.new(v, sock)
        return n.outputs[2]


def _sobel_lines(g, color, strength=0.9, darken=0.8, depth_edge=(0.06, 0.14), normal_edge=(0.2, 0.75),
                 wobble=2.5, width=2.2, fade=(6.0, 18.0, 0.6)):
    """Edge lines from the Depth and Normal passes (Sobel), drawn by darkening the pixel underneath with its
    own colour (pixel x pixel x darken) instead of painting black. Returns the new colour socket.
    - depth_edge: relative jump in 1/depth that starts / saturates a line (silhouettes, overlaps). Raise it
      if surfaces seen at a grazing angle (ceilings, long floors) get smudgy false lines.
    - normal_edge: Sobel magnitude of the normals that starts / saturates a line (corners, creases)
    - wobble: px the line wanders (hand tremor)
    - width: px of softening; pressure noise along the line then makes it swell, thin out and break
    - fade: (near m, far m, factor at far) lines get fainter with distance"""
    N, L, rl, px = g.N, g.L, g.rl, g.px

    def sobel(sock):
        f = N.new("CompositorNodeFilter")
        _set_in(f, ["Type", "filter_type"], "Sobel")
        L.new(sock, f.inputs["Image"])
        bw = N.new("CompositorNodeRGBToBW")
        L.new(f.outputs[0], bw.inputs[0])
        return bw.outputs[0]

    wob = g.noise(38, 1.7)
    amp = g.vec("SCALE", g.vec("SUBTRACT", wob.outputs["Color"], (0.5, 0.5, 0.5)), 2 * wobble * px)

    def wobbled(sock):
        d = N.new("CompositorNodeDisplace")
        L.new(sock, d.inputs["Image"])
        L.new(amp, d.inputs["Displacement"])
        _set_in(d, ["Extension X"], "Extend")
        _set_in(d, ["Extension Y"], "Extend")
        return d.outputs[0]

    depth = rl.outputs["Depth"]
    inv = g.math("DIVIDE", 1.0, depth)                       # 1/z: flat surfaces have a constant gradient
    e_d = g.mrange(g.math("DIVIDE", sobel(wobbled(inv)), inv), *depth_edge)   # relative jump
    e_n = g.mrange(sobel(wobbled(rl.outputs["Normal"])), *normal_edge)
    edge = g.math("MAXIMUM", e_d, e_n)
    pr = g.noise(70, 5.3)                                    # pressure, before the softening -> width varies
    edge = g.math("MULTIPLY", edge, g.mrange(pr.outputs["Factor"], 0.3, 0.62, 0.1, 1.0))
    bl = N.new("CompositorNodeBlur")
    bl.inputs["Size"].default_value = (width * px, width * px)
    L.new(edge, bl.inputs["Image"])
    bw = N.new("CompositorNodeRGBToBW")
    L.new(bl.outputs[0], bw.inputs[0])
    edge = g.mrange(bw.outputs[0], 0.04, 0.4)                # re-sharpen: solid core, tapered sides
    edge = g.math("MULTIPLY", edge, g.mrange(depth, fade[0], fade[1], 1.0, fade[2]))
    dark = g.mix(1.0, g.mix(1.0, color, color, "MULTIPLY"), (darken, darken, darken, 1.0), "MULTIPLY")
    return g.mix(g.math("MULTIPLY", edge, strength), color, dark)


def _finish(g, color, grain=0.07, streaks=0.012, speckle=0.02, vignette=0.14):
    """Paper grain (static: the paper does not move), faint vertical brush streaks and a vignette."""
    f = g.math("ADD", 1.0, g.math("MULTIPLY", g.math("SUBTRACT", g.noise(170, 11.0, boil=False).outputs["Factor"], 0.5), grain))
    st = g.noise(14, 23.0, stretch=(0.35, 4.0), boil=False, detail=2.0)
    f = g.math("ADD", f, g.math("MULTIPLY", g.math("SUBTRACT", st.outputs["Factor"], 0.5), streaks))
    wn = g.N.new("ShaderNodeTexWhiteNoise")
    g.L.new(g.coords(), wn.inputs["Vector"])
    f = g.math("ADD", f, g.math("MULTIPLY", g.math("SUBTRACT", wn.outputs["Value"], 0.5), speckle))
    v = g.vec("MULTIPLY", g.vec("SUBTRACT", g.coords("Normalized"), (0.5, 0.5, 0.0)), (1.0, 1.4, 0.0))
    vl = g.N.new("ShaderNodeVectorMath")
    vl.operation = "LENGTH"
    g.L.new(v, vl.inputs[0])
    f = g.math("MULTIPLY", f, g.mrange(vl.outputs["Value"], 0.3, 0.95, 1.0, 1.0 - vignette, smooth=True))
    return g.mix(1.0, color, f, "MULTIPLY")


def _comp(scene, px, kuwahara=7, glare=True, overlay=None, lines="object", haze=(6.0, 20.0, 0.4),
          haze_color="#a78b85", boil=0, finish=True):
    """Compositor: Kuwahara, lines, depth haze, glow overlay, lamp glare, paper finish."""
    ng = bpy.data.node_groups.new("toon_comp", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    scene.compositing_node_group = ng
    N, L = ng.nodes, ng.links
    rl = N.new("CompositorNodeRLayers")
    g = _G(ng, rl, px, boil)
    kw = N.new("CompositorNodeKuwahara")
    _set_in(kw, ["Size"], int(kuwahara * px))
    _set_in(kw, ["Type", "variation"], "Anisotropic")
    _set_in(kw, ["Uniformity"], 4)
    _set_in(kw, ["Sharpness"], 0.6)
    _set_in(kw, ["Eccentricity"], 1.0)
    L.new(rl.outputs["Image"], kw.inputs["Image"])
    last = kw.outputs[0]
    if lines == "sobel":
        last = _sobel_lines(g, last)
    elif lines == "object":
        # stroke mask from the geometric outline layer; colour = the object's own pixel (before the
        # painterly filter, so it is exactly that object's lit colour), darker and a little richer in HSV
        lrl = N.new("CompositorNodeRLayers")
        lrl.layer = LINES_LAYER
        sep = N.new("CompositorNodeSeparateColor")
        L.new(lrl.outputs["Freestyle"], sep.inputs["Image"])
        hs = N.new("CompositorNodeHueSat")
        L.new(rl.outputs["Image"], hs.inputs["Image"])
        hs.inputs["Saturation"].default_value = OUTLINE_SAT
        hs.inputs["Value"].default_value = OUTLINE_VALUE
        last = g.mix(g.math("MULTIPLY", sep.outputs["Alpha"], OUTLINE_OPACITY), last, hs.outputs[0])
    if haze:
        last = g.mix(g.mrange(rl.outputs["Depth"], haze[0], haze[1], 0.0, haze[2], smooth=True),
                     last, lin(haze_color))
    if overlay:
        orl = N.new("CompositorNodeRLayers")
        orl.layer = overlay.name
        oa = N.new("CompositorNodeAlphaOver")
        L.new(last, oa.inputs["Background"])
        L.new(orl.outputs["Image"], oa.inputs["Foreground"])
        last = oa.outputs[0]
    if glare:
        gl = N.new("CompositorNodeGlare")
        _set_in(gl, ["Type", "glare_type"], "Fog Glow")
        _set_in(gl, ["Quality"], "High")
        _set_in(gl, ["Threshold"], 1.2)       # only emitters brighter than white (lamps) glow
        _set_in(gl, ["Strength", "Mix"], 1.0)
        _set_in(gl, ["Size"], 0.85)
        L.new(last, gl.inputs["Image"])
        last = gl.outputs[0]
    if finish:
        last = _finish(g, last)
    out = N.new("NodeGroupOutput")
    L.new(last, out.inputs[0])
    return ng


def setup(scene=None, world="#8f7c8c", world_strength=1.0, kuwahara=7, glare=True, lines="object",
          haze=(6.0, 20.0, 0.4), haze_color="#a78b85", boil=2, finish=True):
    """Colour management, world light, lines and the compositor.
    world: flat world colour, or None to keep the scene's world (e.g. s3d's HDRI sky).
    lines: "object" (default) = geometric outline from the meshes (silhouettes, borders, creases), drawn
           inside each object in a darker tone of that object's own colour (OUTLINE_* constants);
           "sobel" = screen-space edges from the depth/normal passes (sketchier, cheaper); None = no lines.
    haze: (from m, to m, max mix) towards haze_color, or None.
    boil: sobel line noise changes every `boil` frames in an animation (0 = fixed)."""
    scene = scene or bpy.context.scene
    px = scene.render.resolution_x * scene.render.resolution_percentage / 100 / 1080
    vs = scene.view_settings
    vs.view_transform = "Standard"   # keep the palette exactly (AgX would grey it)
    vs.look = "None"
    vs.exposure, vs.gamma = 0.0, 1.0
    if world is not None:
        w = scene.world or bpy.data.worlds.new("toon_world")
        scene.world = w
        w.use_nodes = True
        nt = w.node_tree
        bg = nt.nodes.get("Background") or nt.nodes.new("ShaderNodeBackground")
        for lk in list(bg.inputs["Color"].links):
            nt.links.remove(lk)
        bg.inputs["Color"].default_value = lin(world)
        bg.inputs["Strength"].default_value = world_strength
    scene.render.use_freestyle = lines == "object"
    vl = scene.view_layers[0]
    vl.use_pass_z = True
    vl.use_pass_normal = True
    if lines == "object":
        _lines(scene, px)
    return _comp(scene, px, kuwahara, glare, _overlay_layer(scene), lines, haze, haze_color, boil, finish)


def render_still(path, scene=None, samples=32):
    scene = scene or bpy.context.scene
    scene.eevee.taa_render_samples = samples
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.filepath = path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.render.render(write_still=True)
    return path
