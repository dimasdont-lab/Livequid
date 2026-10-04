"""OpenGL renderer: matrix grid + liquid-glass gel.

Pass 1  every particle is splatted as a soft kernel into a half-resolution
        float texture: (field, d field/dx, d field/dy). Cost scales with the
        area of the gel, not with the size of the desktop.
Pass 2  one full-screen shader turns that field into a glass surface:
        refraction of the (procedural) grid, chromatic fringe, fresnel rim,
        specular highlights and inner caustics.
"""
import numpy as np
import moderngl

SPLAT_VS = """
#version 330
uniform vec2 world;
in vec2 corner;
in vec4 inst;                       // x, y, kernel radius, weight
out vec2 d;
out vec2 rw;
void main() {
    d = corner * inst.z;
    rw = vec2(inst.z, inst.w);
    vec2 p = inst.xy + d;
    gl_Position = vec4(p.x / world.x * 2.0 - 1.0, 1.0 - p.y / world.y * 2.0, 0.0, 1.0);
}
"""

SPLAT_FS = """
#version 330
uniform float gscale;
in vec2 d;
in vec2 rw;
out vec4 o;
void main() {
    float q = dot(d, d) / (rw.x * rw.x);
    if (q >= 1.0) discard;
    float a = 1.0 - q;
    float f = a * a * a;                              // Wyvill kernel
    vec2 g = -6.0 * a * a * d / (rw.x * rw.x);        // its gradient
    o = vec4(f, g * gscale, 0.0) * rw.y;
}
"""

QUAD_VS = """
#version 330
in vec2 corner;
void main() { gl_Position = vec4(corner, 0.0, 1.0); }
"""

GLASS_FS = """
#version 330
uniform sampler2D field;
uniform vec2  res;
uniform float time;
uniform float r0;            // particle radius, px (the unit of all gel sizes)
uniform float grid;          // grid cell, px
uniform float thr;           // iso-level of the gel surface
out vec4 outc;

float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }

// ---------- background: thin matrix-green grid -------------------------------
vec3 background(vec2 p) {
    vec2 q = p / grid;
    vec2 fr = abs(fract(q + 0.5) - 0.5) * grid;                // px distance to nearest line
    float m = min(fr.x, fr.y);
    float line = 1.0 - smoothstep(0.30, 1.15, m);              // ~1px hairline
    float halo = exp(-m * 0.30) * 0.07;

    vec2 cell = floor(q);
    vec2 mj = abs(fract(q * 0.25 + 0.5) - 0.5) * grid * 4.0; // lines every 4th cell
    float majline = 1.0 - smoothstep(0.30, 1.25, min(mj.x, mj.y));


    // slow, faint pulse travelling over the grid
    float pulse = 0.78 + 0.22 * sin(time * 0.35 + (p.x * 0.9 + p.y * 0.6) * 0.0032);

    vec3 green = vec3(0.02, 0.62, 0.22);
    vec3 col = vec3(0.004, 0.017, 0.010);
    col += green * (line * 0.36 + majline * 0.22 + halo) * pulse;
    return col;
}

void main() {
    vec2 uv = gl_FragCoord.xy / res;
    vec2 p = vec2(gl_FragCoord.x, res.y - gl_FragCoord.y);
    vec4 F = texture(field, uv);
    float f = F.x;
    vec2 grad = F.yz / r0;                               // d field / d px
    float gmag = length(grad) + 1e-6;

    // signed distance (px) to the surface, anti-aliased coverage
    float dist = (f - thr) / gmag;
    float cover = clamp(dist + 0.5, 0.0, 1.0);

    vec3 base = background(p);
    // vignette
    vec2 vc = (p / res - 0.5);
    base *= 1.0 - 0.35 * dot(vc, vc);

    vec3 col = base;
    if (f > thr * 0.25) {
        // height of the gel surface: steep at the rim, flat in the middle
        float inside = max(f - thr, 0.0);
        float c = 2.2;
        float hmax = 2.4 * r0;
        float H = hmax * (1.0 - exp(-inside * c));
        vec2 gH = hmax * c * exp(-inside * c) * grad;
        // soften the very edge so the rim does not alias
        gH *= smoothstep(-1.0, 3.0, dist);
        vec3 n = normalize(vec3(-gH, 1.0));

        // refraction: look through the lens, slightly magnified, with chromatic fringe
        vec2 off = -n.xy * (0.55 * r0) * (0.4 + 1.6 * (1.0 - n.z));
        vec3 refr;
        refr.r = background(p + off * 0.93).r;
        refr.g = background(p + off * 1.00).g;
        refr.b = background(p + off * 1.09).b;
        refr *= 1.0 - 0.35 * dot(vc, vc);
        // gel is almost clear: a whisper of green absorption, deeper where thicker
        refr *= mix(vec3(1.0), vec3(0.80, 0.97, 0.86), clamp(H / hmax, 0.0, 1.0) * 0.6);
        refr += vec3(0.0, 0.010, 0.006) * (H / hmax);     // slight self-glow

        vec3 V = vec3(0.0, 0.0, 1.0);
        vec3 L1 = normalize(vec3(-0.55, -0.70, 0.55));    // key light, top-left
        vec3 L2 = normalize(vec3( 0.60,  0.55, 0.45));    // bounce, bottom-right
        float ndv = clamp(n.z, 0.0, 1.0);
        float fres = 0.02 + 0.98 * pow(1.0 - ndv, 3.2);

        vec3 h1 = normalize(L1 + V);
        vec3 h2 = normalize(L2 + V);
        float s1 = pow(max(dot(n, h1), 0.0), 110.0) * 1.6 + pow(max(dot(n, h1), 0.0), 14.0) * 0.10;
        float s2 = pow(max(dot(n, h2), 0.0), 70.0) * 0.55;

        // fake environment seen in the rim reflection
        vec2 rdir = normalize(n.xy + 1e-5);
        float sky = 0.5 + 0.5 * dot(rdir, normalize(vec2(-0.55, -0.7)));
        vec3 env = mix(vec3(0.01, 0.06, 0.03), vec3(0.55, 1.0, 0.78), pow(sky, 2.0));

        // inner caustic: light focused on the side opposite to the key light
        float cau = pow(1.0 - ndv, 1.6) * max(dot(rdir, -normalize(vec2(-0.55, -0.7))), 0.0);
        cau *= smoothstep(0.0, 6.0, dist);

        vec3 glass = refr;
        glass += env * fres * 0.85;
        glass += vec3(0.80, 1.0, 0.92) * s1;
        glass += vec3(0.35, 0.95, 0.60) * s2;
        glass += vec3(0.25, 0.95, 0.50) * cau * 0.55;

        col = mix(base, glass, cover);
    } else {
        // faint soft shadow around the gel
        col *= 1.0 - 0.18 * smoothstep(0.0, thr * 0.25, f);
    }

    // dither (dark gradients band easily)
    col += (hash(gl_FragCoord.xy + fract(time)) - 0.5) / 255.0;
    outc = vec4(col, 1.0);
}
"""


class Renderer:
    def __init__(self, ctx, width, height, r0, max_particles, field_scale=0.5, grid=48.0):
        self.ctx = ctx
        self.w, self.h = int(width), int(height)
        self.r0 = float(r0)
        self.grid = float(grid)
        self.thr = 0.62

        fw, fh = max(1, int(self.w * field_scale)), max(1, int(self.h * field_scale))
        self.field_tex = ctx.texture((fw, fh), 4, dtype="f2")
        self.field_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.field_tex.repeat_x = self.field_tex.repeat_y = False
        self.field_fbo = ctx.framebuffer(color_attachments=[self.field_tex])

        self.splat = ctx.program(vertex_shader=SPLAT_VS, fragment_shader=SPLAT_FS)
        self.splat["world"].value = (self.w, self.h)
        self.splat["gscale"].value = self.r0
        self.glass = ctx.program(vertex_shader=QUAD_VS, fragment_shader=GLASS_FS)
        self.glass["res"].value = (self.w, self.h)
        self.glass["r0"].value = self.r0
        self.glass["grid"].value = self.grid
        self.glass["thr"].value = self.thr
        self.glass["field"].value = 0

        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4")
        self.quad_vbo = ctx.buffer(quad.tobytes())
        self.inst_vbo = ctx.buffer(reserve=max_particles * 16, dynamic=True)
        self.splat_vao = ctx.vertex_array(
            self.splat, [(self.quad_vbo, "2f", "corner"), (self.inst_vbo, "4f/i", "inst")])
        self.glass_vao = ctx.vertex_array(self.glass, [(self.quad_vbo, "2f", "corner")])
        self.count = 0

    def render(self, inst, time, target=None):
        """inst: (n, 4) float32 -> x, y, kernel radius, weight."""
        ctx = self.ctx
        self.count = len(inst)
        self.inst_vbo.write(np.ascontiguousarray(inst, dtype="f4").tobytes())

        self.field_fbo.use()
        self.field_fbo.clear(0.0, 0.0, 0.0, 0.0)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        self.splat_vao.render(moderngl.TRIANGLE_STRIP, instances=self.count)
        ctx.disable(moderngl.BLEND)

        (target or ctx.screen).use()
        self.field_tex.use(0)
        self.glass["time"].value = float(time)
        self.glass_vao.render(moderngl.TRIANGLE_STRIP)
