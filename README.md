# Pauger 3D Mast Viewer

Static three.js viewer for the P1–P7 mast models. Open `index.html` via any
static file server (or GitHub Pages). Orbit = drag, zoom = scroll, pan =
right-drag. Model switcher in the bottom bar.

## Rebuilding models from .3dm

The `.3dm` sources (44–155 MB each) are converted to draco-compressed `.glb`
(0.7–2.4 MB) in two steps:

```bash
python3 -m venv venv && venv/bin/pip install rhino3dm trimesh numpy
venv/bin/python tools/convert_3dm.py P1.3dm P2.3dm ...   # edit SRC/DST paths in the script
npx @gltf-transform/cli weld models/raw/P1.glb /tmp/w.glb
npx @gltf-transform/cli simplify /tmp/w.glb /tmp/s.glb --ratio 0 --error 0.001
npx @gltf-transform/cli draco /tmp/s.glb models/P1.glb --quantize-position 14
```

The simplify step is deliberate IP protection, not just bandwidth: it decimates
to ~3% of the original vertices (up to ~8 mm surface deviation), so the
published models look right at viewing distance but are useless as
manufacturing/reverse-engineering data. Web 3D can always be downloaded —
ship geometry you can afford to give away.

Notes on the conversion (`tools/convert_3dm.py`):

- Uses the render meshes embedded in the .3dm (no meshing engine needed).
- Keeps only the main geometry cluster; "parked" detail views scattered
  around the model in the source files are dropped automatically.
- Meshes are merged per display color (object color, else layer color) to
  minimize draw calls; 2D annotations (curves, hatches, text, dims) are ignored.
- 16-bit draco position quantization — lower bits show visible lumps on
  small fittings because merged meshes span the whole ~16 m scene.
