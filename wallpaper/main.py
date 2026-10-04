"""Livequid wallpaper: matrix grid + zero-gravity liquid-glass gel across all monitors.

  python main.py              run as the desktop wallpaper
  python main.py --windowed   debug: normal window instead of wallpaper
Quit with Ctrl+Alt+Q (or stop.bat).
"""
import argparse
import sys
import time

import glfw
import moderngl

from sim import Gel
from renderer import Renderer

WIN = sys.platform == "win32"
if WIN:
    import winutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windowed", action="store_true", help="debug window (not wallpaper)")
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--particles", type=int, default=210, help="more = bigger blob")
    ap.add_argument("--field-scale", type=float, default=0.5, help="gel field resolution (lower = lighter)")
    args = ap.parse_args()

    if WIN:
        winutil.set_dpi_aware()
        rects = winutil.monitors()
        vx, vy, vw, vh = winutil.virtual_screen()
    else:  # dev fallback
        rects, (vx, vy, vw, vh) = [(0, 0, 1280, 720)], (0, 0, 1280, 720)
    if args.windowed:
        vw, vh = min(vw, 1600), min(vh, 900)
        rects = [(0, 0, vw, vh)]
        vx = vy = 0
    rects = [(a - vx, b - vy, c - vx, d - vy) for a, b, c, d in rects]   # to canvas coordinates

    if not glfw.init():
        raise SystemExit("glfw init failed")
    glfw.window_hint(glfw.DECORATED, bool(args.windowed))
    glfw.window_hint(glfw.VISIBLE, bool(args.windowed))
    glfw.window_hint(glfw.FOCUS_ON_SHOW, False)
    glfw.window_hint(glfw.RESIZABLE, False)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    win = glfw.create_window(vw, vh, "Livequid", None, None)
    if not win:
        raise SystemExit("could not create an OpenGL 3.3 window")
    glfw.make_context_current(win)
    glfw.swap_interval(1)
    if WIN and not args.windowed:
        winutil.embed_in_desktop(glfw.get_win32_window(win))

    ctx = moderngl.create_context()
    min_h = min(r[3] - r[1] for r in rects)
    r0 = max(8.0, min_h * 0.0145)                         # gel scales with the screen
    gel = Gel(rects, r0, args.particles)
    rend = Renderer(ctx, vw, vh, r0, args.particles, args.field_scale, grid=max(24.0, min_h / 22))

    SUB = 1.0 / 120.0
    acc, last, t0 = 0.0, time.perf_counter(), time.perf_counter()
    paused_check, asleep = 0.0, False
    while not glfw.window_should_close(win):
        glfw.poll_events()
        now = time.perf_counter()
        if WIN:
            if winutil.quit_hotkey_down():
                break
            if now - paused_check > 0.5:                   # don't burn GPU under a fullscreen game
                paused_check = now
                asleep = winutil.fullscreen_app_active()
            if paused_check and asleep:
                time.sleep(0.25)
                last = time.perf_counter()
                continue
            cx, cy = winutil.cursor_pos()
            cursor = (cx - vx, cy - vy)
        else:
            mx, my = glfw.get_cursor_pos(win)
            cursor = (mx, my)

        acc += min(now - last, 0.05)
        last = now
        while acc >= SUB:
            gel.step(SUB, cursor)
            acc -= SUB

        rend.render(gel.instances(), now - t0)
        glfw.swap_buffers(win)
        if args.fps < 60:                                  # vsync is 60+; sleep to lower the rate
            time.sleep(max(0.0, 1.0 / args.fps - (time.perf_counter() - now)))
    glfw.terminate()


if __name__ == "__main__":
    main()
