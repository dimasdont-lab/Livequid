"""OpenGL renderer: matrix grid + liquid-glass gel.

Pass 1  every particle is splatted as a soft kernel into a half-resolution
        float texture: (field, d field/dx, d field/dy). Cost scales with the
        area of the gel, not with the size of the desktop.
Pass 2  one full-screen shader turns that field into a glass surface:
        refraction of the (procedural) grid, chromatic fringe, fresnel rim,
        specular highlights and inner caustics.
"""
import ctypes

import numpy as np
from OpenGL import GL
from OpenGL.GL import shaders as glsh

SPLAT_VS = """
#version 330
uniform vec2 world;
layout(location = 0) in vec2 corner;
layout(location = 1) in vec4 inst;                       // x, y, kernel radius, weight
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
layout(location = 0) in vec2 corner;
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


def _program(vs, fs):
    return glsh.compileProgram(glsh.compileShader(vs, GL.GL_VERTEX_SHADER),
                               glsh.compileShader(fs, GL.GL_FRAGMENT_SHADER), validate=False)


class Renderer:
    """Needs a current OpenGL 3.3 core context (created by the caller)."""

    def __init__(self, width, height, r0, max_particles, field_scale=0.5, grid=48.0):
        self.w, self.h = int(width), int(height)
        self.r0 = float(r0)
        self.thr = 0.62
        self.fw = max(1, int(self.w * field_scale))
        self.fh = max(1, int(self.h * field_scale))

        # half-resolution float texture holding (field, dfield/dx, dfield/dy)
        self.tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA16F, self.fw, self.fh, 0, GL.GL_RGBA, GL.GL_HALF_FLOAT, None)
        for k, v in ((GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR), (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR),
                     (GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE), (GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, k, v)
        self.fbo = GL.glGenFramebuffers(1)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glFramebufferTexture2D(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0, GL.GL_TEXTURE_2D, self.tex, 0)
        status = GL.glCheckFramebufferStatus(GL.GL_FRAMEBUFFER)
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        if status != GL.GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("float framebuffer not supported by this GPU/driver (status %s)" % status)

        self.splat = _program(SPLAT_VS, SPLAT_FS)
        self.glass = _program(QUAD_VS, GLASS_FS)
        GL.glUseProgram(self.splat)
        GL.glUniform2f(GL.glGetUniformLocation(self.splat, "world"), self.w, self.h)
        GL.glUniform1f(GL.glGetUniformLocation(self.splat, "gscale"), self.r0)
        GL.glUseProgram(self.glass)
        loc = lambda n: GL.glGetUniformLocation(self.glass, n)
        GL.glUniform2f(loc("res"), self.w, self.h)
        GL.glUniform1f(loc("r0"), self.r0)
        GL.glUniform1f(loc("grid"), float(grid))
        GL.glUniform1f(loc("thr"), self.thr)
        GL.glUniform1i(loc("field"), 0)
        self.u_time = loc("time")

        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype=np.float32)
        self.quad_vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.quad_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad, GL.GL_STATIC_DRAW)
        self.inst_vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.inst_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, max_particles * 16, None, GL.GL_DYNAMIC_DRAW)

        self.glass_vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self.glass_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.quad_vbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, False, 0, ctypes.c_void_p(0))

        self.splat_vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self.splat_vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.quad_vbo)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, False, 0, ctypes.c_void_p(0))
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.inst_vbo)
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 4, GL.GL_FLOAT, False, 0, ctypes.c_void_p(0))
        GL.glVertexAttribDivisor(1, 1)
        GL.glBindVertexArray(0)

    def render(self, inst, time, target=0):
        """inst: (n, 4) float32 -> x, y, kernel radius, weight. target: framebuffer id (0 = window)."""
        inst = np.ascontiguousarray(inst, dtype=np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.inst_vbo)
        GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, inst.nbytes, inst)

        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, self.fbo)
        GL.glViewport(0, 0, self.fw, self.fh)
        GL.glClearColor(0, 0, 0, 0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE)
        GL.glUseProgram(self.splat)
        GL.glBindVertexArray(self.splat_vao)
        GL.glDrawArraysInstanced(GL.GL_TRIANGLE_STRIP, 0, 4, len(inst))
        GL.glDisable(GL.GL_BLEND)

        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, target)
        GL.glViewport(0, 0, self.w, self.h)
        GL.glUseProgram(self.glass)
        GL.glUniform1f(self.u_time, float(time))
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.tex)
        GL.glBindVertexArray(self.glass_vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
