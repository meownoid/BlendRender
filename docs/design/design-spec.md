# BlendRender design specification

The accepted dashboard and login concepts in this directory are the visual source of truth.

## Tokens

- Background: `#0d1013`; surfaces: `#13171b`, `#181d22`, `#20262c`.
- Hairline border: `#30363d`; primary text: `#f2f3f4`; muted text: `#9ca3ab`.
- Accent: `#ff8a1f`; queued: `#4da3ff`; success: `#39c76a`; danger: `#ff4d43`.
- Typography: Inter Variable for product UI and JetBrains Mono Variable for frame numbers.
- Radii: 5–8 px for controls, 8–12 px only for media frames and purposeful panels.
- Icons: precise 1.5–1.75 px outline icons at 16–22 px.

## Layout and responsive behavior

- Native comparison viewport: 1586 × 992.
- Desktop: quiet 73 px header, 378 px job rail, fluid render workspace, 372 px new-render rail.
- The header system control opens a shared 372 px system-stats rail with 15-minute CPU, GPU, host
  memory, and GPU-VRAM plots; it replaces the new-render rail until the user switches back.
- Below 1280 px the new-render rail becomes an overlay drawer.
- Below 820 px the job rail becomes a horizontal selector and the frame rail scrolls horizontally.
- The dashboard preview is always a real completed frame. The bundled demo render is gated to Vite development mode.
- The login render has no color wash; only the natural dark-to-image edge blend and the approved CSS edge fade are used.

## Allowed primary copy

`BlendRender`, `New render`, `Render jobs`, `All`, `Active`, `Completed`, `Rendered frames`,
`Download selected`, `Download all`, `Drop a packed .blend file`, `or choose a file`, `Mode`,
`Still`, `Frame range`, `Start`, `End`, `Backend`, `OptiX`, `CUDA`, `Queue render`,
`CPU`, `System stats`, `Last 15 minutes`, `GPU`, `MEM`, `VRAM`,
`Open render node`, `Enter the access password configured for this pod.`, `Password`, `Continue`,
and `Blender 5.2 LTS · GPU node`.
