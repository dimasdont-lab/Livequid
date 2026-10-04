"""Gel physics: a few hundred cohesive particles in zero gravity.

Every particle is a small piece of gel. Neighbours repel when they overlap and
attract (cohesion) a bit further away, so a clump behaves like one drop with
surface tension; pieces that get knocked off fly away as separate droplets and
merge back on contact. Pair viscosity makes the clump wobble like jelly
instead of like a bag of marbles.
"""
import numpy as np


class Gel:
    def __init__(self, rects, r0, count=210, seed=7):
        """rects: [(x0, y0, x1, y1)] of the monitors in virtual-desktop pixels."""
        self.rng = np.random.default_rng(seed)
        self.rects = np.asarray(rects, dtype=np.float32)
        self.walls = self._inset(self.rects, r0 * 0.9)
        self.r0 = float(r0)
        self.n = count
        n = count

        # a few sizes so droplets are not all identical
        self.rad = (self.r0 * self.rng.uniform(0.62, 1.0, n)).astype(np.float32)
        self.mass = (self.rad / self.r0) ** 2

        # start as one big blob, centred on the seam between the first two monitors
        cx, cy = self._start_point()
        golden = np.pi * (3.0 - np.sqrt(5.0))
        i = np.arange(n, dtype=np.float32)
        rr = np.sqrt((i + 0.5) / n) * self.r0 * np.sqrt(n) * 1.05
        th = i * golden
        self.p = np.stack([cx + rr * np.cos(th), cy + rr * np.sin(th)], 1).astype(np.float32)
        self.v = np.zeros((n, 2), np.float32)

        self.t = 0.0
        self.cursor = None            # last cursor position
        self.cursor_v = np.zeros(2, np.float32)
        self.cursor_speed = 0.0       # smoothed, px/s

        # --- tunables (accelerations are in px/s^2, lengths in px) ---
        self.k_rep = 1900.0           # overlap repulsion stiffness
        self.k_att = 520.0            # cohesion
        self.cut = 1.85               # cohesion range, in units of (ri + rj)
        self.visc = 9.0               # pair viscosity (jelly damping)
        self.drag = 0.10              # global drag, 1/s (droplets drift for a long time)
        self.restitution = 0.92       # bounce off the monitor edges
        self.cursor_r = self.r0 * 3.4 # solid core of the cursor
        self.magnet_r = self.r0 * 22  # radius where slow cursor gathers droplets
        self.slow = 260.0             # below this speed the cursor collects
        self.fast = 900.0             # above this speed the cursor shatters
        self.centre_pull = 5.0        # very weak: scattered drops slowly find each other

    def _start_point(self):
        """Centre of the desktop (the seam, for two side-by-side monitors)."""
        r = self.rects
        cx, cy = (r[:, 0].min() + r[:, 2].max()) * 0.5, (r[:, 1].min() + r[:, 3].max()) * 0.5
        if ((r[:, 0] <= cx) & (cx <= r[:, 2]) & (r[:, 1] <= cy) & (cy <= r[:, 3])).any():
            return cx, cy
        return (r[0, 0] + r[0, 2]) * 0.5, (r[0, 1] + r[0, 3]) * 0.5

    # ------------------------------------------------------------------
    def step(self, dt, cursor):
        """Advance by dt seconds. cursor: (x, y) in virtual-desktop px or None."""
        n, p, v, rad, mass = self.n, self.p, self.v, self.rad, self.mass

        # ---- cursor kinematics -------------------------------------------------
        if cursor is not None:
            c = np.asarray(cursor, np.float32)
            if self.cursor is not None:
                cv = (c - self.cursor) / dt
                self.cursor_v += (cv - self.cursor_v) * min(1.0, dt * 25.0)
            self.cursor = c
            self.cursor_speed += (float(np.hypot(*self.cursor_v)) - self.cursor_speed) * min(1.0, dt * 12.0)

        # ---- pair forces --------------------------------------------------------
        px, py = p[:, 0], p[:, 1]
        dx = px[None, :] - px[:, None]                    # [i, j] = pj - pi
        dy = py[None, :] - py[:, None]
        dist = np.sqrt(dx * dx + dy * dy) + 1e-3
        s = rad[:, None] + rad[None, :]                   # contact distance
        rng_ = self.cut * s

        rep = self.k_rep * np.clip(s - dist, 0.0, None)   # pushes apart
        w = np.clip(1.0 - dist / rng_, 0.0, None)         # 1 at touch, 0 at cohesion range
        np.fill_diagonal(w, 0.0)
        f = (self.k_att * w - rep) / dist                 # >0 pulls i towards j
        np.fill_diagonal(f, 0.0)
        inv_m = 1.0 / mass
        acc = np.stack([(f * dx).sum(1), (f * dy).sum(1)], 1) * inv_m[:, None]

        wsum = np.maximum(w.sum(1), 1.0)
        acc += (self.visc * 6.0) * (w @ v - w.sum(1)[:, None] * v) / wsum[:, None]
        neigh = (w > 0.0).sum(1).astype(np.float32)       # ~0 for a lone droplet

        # ---- ambient: slow wandering flow + faint reunion ----------------------
        t = self.t
        acc[:, 0] += 9.0 * np.sin(t * 0.31 + p[:, 1] * 0.0021 + 1.3)
        acc[:, 1] += 9.0 * np.cos(t * 0.27 + p[:, 0] * 0.0017)
        com = p.mean(0)
        dc = com - p
        dl = np.linalg.norm(dc, axis=1, keepdims=True) + 1e-3
        acc += self.centre_pull * dc / dl * np.minimum(dl / 600.0, 1.0)

        # ---- cursor -------------------------------------------------------------
        if self.cursor is not None:
            dcur = p - self.cursor
            dd = np.linalg.norm(dcur, axis=1) + 1e-3
            nrm = dcur / dd[:, None]
            speed = self.cursor_speed

            # slow cursor: a magnet for loose droplets (less for the clump itself)
            gather = np.clip(1.0 - speed / self.slow, 0.0, 1.0)
            if gather > 0.0:
                fall = np.clip(1.0 - dd / self.magnet_r, 0.0, 1.0)
                lonely = 1.0 / (1.0 + 0.7 * neigh)
                acc -= nrm * (1500.0 * gather * (fall * lonely))[:, None]
                # and some damping near it so they settle instead of orbiting forever
                v *= 1.0 - np.clip(dt * 3.0 * gather * fall, 0.0, 0.5)[:, None]

            # solid core: moving circle that fling things away
            core = self.cursor_r + rad
            pen = np.clip(core - dd, 0.0, None)
            hit = pen > 0.0
            if hit.any():
                p[hit] += nrm[hit] * pen[hit, None] * 0.55
                rel = v - self.cursor_v
                vn = (rel * nrm).sum(1)
                approach = hit & (vn < 0.0)
                # momentum from the cursor; fast swipes hit much harder than slow ones
                boost = 1.0 + np.clip(speed / self.fast, 0.0, 1.5)
                v[approach] -= (1.0 + 0.55 * boost) * vn[approach, None] * nrm[approach]
                v[approach] += self.cursor_v * (0.35 + 0.35 * min(speed / self.fast, 1.5))
                # fast swipe also sprays the contacted gel sideways
                if speed > self.slow:
                    k = np.clip((speed - self.slow) / self.fast, 0.0, 1.0)
                    side = np.stack([-nrm[:, 1], nrm[:, 0]], 1)
                    jit = self.rng.normal(size=n).astype(np.float32)
                    v[hit] += side[hit] * (jit[hit, None] * 160.0 * k)

        # ---- integrate -----------------------------------------------------------
        v += acc * dt
        v *= 1.0 - self.drag * dt
        sp = np.linalg.norm(v, axis=1, keepdims=True)
        v *= np.minimum(1.0, 2600.0 / np.maximum(sp, 1e-3))
        p += v * dt
        self._bounds()
        self.t += dt

    # ------------------------------------------------------------------
    @staticmethod
    def _inset(rects, m):
        """Shrink every monitor by m, except along edges it shares with another
        monitor, so gel flows over the seam without hitting an invisible wall."""
        out = rects.copy()
        tol = 3.0
        for i, (x0, y0, x1, y1) in enumerate(rects):
            lx, ly, hx, hy = x0 + m, y0 + m, x1 - m, y1 - m
            for j, (a0, b0, a1, b1) in enumerate(rects):
                if i == j:
                    continue
                if min(y1, b1) - max(y0, b0) > 0:           # overlap in y -> side by side
                    if abs(a0 - x1) < tol: hx = x1
                    if abs(a1 - x0) < tol: lx = x0
                if min(x1, a1) - max(x0, a0) > 0:           # overlap in x -> stacked
                    if abs(b0 - y1) < tol: hy = y1
                    if abs(b1 - y0) < tol: ly = y0
            out[i] = (lx, ly, hx, hy)
        return out

    def _bounds(self):
        """Keep everything inside the union of the monitor rectangles."""
        p, v = self.p, self.v
        R = self.walls
        cx = np.clip(p[:, None, 0], R[None, :, 0], R[None, :, 2])
        cy = np.clip(p[:, None, 1], R[None, :, 1], R[None, :, 3])
        dx, dy = cx - p[:, None, 0], cy - p[:, None, 1]
        d2 = dx * dx + dy * dy
        k = d2.argmin(1)
        idx = np.arange(self.n)
        dx, dy, d2 = dx[idx, k], dy[idx, k], d2[idx, k]
        out = d2 > 1e-8
        if not out.any():
            return
        p[out, 0] += dx[out]
        p[out, 1] += dy[out]
        d = np.sqrt(d2[out])
        nx, ny = dx[out] / d, dy[out] / d
        vo = v[out]
        vn = vo[:, 0] * nx + vo[:, 1] * ny
        b = vn < 0
        vo[b, 0] -= (1 + self.restitution) * vn[b] * nx[b]
        vo[b, 1] -= (1 + self.restitution) * vn[b] * ny[b]
        v[out] = vo

    def instances(self, grow=3.5):
        """(x, y, kernel radius, weight) per particle for the renderer."""
        out = np.empty((self.n, 4), np.float32)
        out[:, :2] = self.p
        out[:, 2] = self.rad * grow
        out[:, 3] = 1.0
        return out
