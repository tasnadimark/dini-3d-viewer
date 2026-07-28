"""Convert Rhino .3dm render meshes to .glb, colored by object/layer color, merged per color.
Drops geometry clusters detached from the main assembly (parked detail views)."""
import sys, os
import numpy as np
import rhino3dm
import trimesh

SRC = "/Users/mark/Downloads/wetransfer_https-tasnadimark-github-io-dini-3d-viewer_2026-07-24_1219"
DST = "/Users/mark/dini-3d-viewer/models/raw"
os.makedirs(DST, exist_ok=True)
MARGIN = 300.0  # mm; union-find inflate -> merges objects with gap < 2*MARGIN

def xform_to_np(x):
    return np.array([[x.M00, x.M01, x.M02, x.M03],
                     [x.M10, x.M11, x.M12, x.M13],
                     [x.M20, x.M21, x.M22, x.M23],
                     [x.M30, x.M31, x.M32, x.M33]])

def get_meshes(g):
    if isinstance(g, rhino3dm.Mesh):
        return [g]
    if isinstance(g, rhino3dm.Brep):
        ms = [g.Faces[i].GetMesh(rhino3dm.MeshType.Render) for i in range(len(g.Faces))]
        return [m for m in ms if m and len(m.Vertices) > 0]
    if isinstance(g, rhino3dm.Extrusion):
        m = g.GetMesh(rhino3dm.MeshType.Render)
        return [m] if m and len(m.Vertices) > 0 else []
    return []

def obj_color(f, attrs):
    if attrs.ColorSource == rhino3dm.ObjectColorSource.ColorFromObject:
        c = attrs.ObjectColor
        return (c[0], c[1], c[2])
    li = attrs.LayerIndex
    if 0 <= li < len(f.Layers):
        c = f.Layers[li].Color
        return (c[0], c[1], c[2])
    return (200, 200, 200)

def mesh_to_arrays(m, xf=None):
    n = len(m.Vertices)
    v = np.array([[m.Vertices[i].X, m.Vertices[i].Y, m.Vertices[i].Z] for i in range(n)])
    if xf is not None:
        v = v @ xf[:3, :3].T + xf[:3, 3]
    tris = []
    for i in range(len(m.Faces)):
        fc = m.Faces[i]
        if len(fc) == 4 and fc[2] != fc[3]:
            tris.append((fc[0], fc[1], fc[2])); tris.append((fc[0], fc[2], fc[3]))
        else:
            tris.append((fc[0], fc[1], fc[2]))
    # Rhino Z-up -> glTF Y-up
    v = v[:, [0, 2, 1]] * np.array([1, 1, -1])
    return v, np.array(tris)

def convert(name):
    path = name if os.path.sep in name else os.path.join(SRC, name)
    name = os.path.basename(path)
    f = rhino3dm.File3dm.Read(path)
    entries = []  # (bbox_min, bbox_max, nverts, color, [(v, t), ...])

    layers = list(f.Layers)
    layers_by_id = {str(l.Id): l for l in layers}

    def layer_visible(li):
        lay = layers[li] if 0 <= li < len(layers) else None
        while lay is not None:
            if not lay.Visible:
                return False
            lay = layers_by_id.get(str(lay.ParentLayerId))
        return True

    def is_hidden(attrs):
        return (attrs.Mode == rhino3dm.ObjectMode.Hidden
                or not attrs.Visible
                or not layer_visible(attrs.LayerIndex))

    def add(g, attrs, xf=None, bbox_geom=None):
        parts = []
        for m in get_meshes(g):
            v, t = mesh_to_arrays(m, xf)
            if len(t):
                parts.append((v, t))
        if not parts:
            return
        bb = (bbox_geom or g).GetBoundingBox()
        # flat 2D plates (dimension legends, laminate markers) are drawing furniture
        if min(bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y, bb.Max.Z - bb.Min.Z) < 0.5:
            return
        entries.append((np.array([bb.Min.X, bb.Min.Y, bb.Min.Z]),
                        np.array([bb.Max.X, bb.Max.Y, bb.Max.Z]),
                        sum(len(v) for v, _ in parts), obj_color(f, attrs), parts))

    for o in f.Objects:
        if is_hidden(o.Attributes):
            continue
        g = o.Geometry
        if isinstance(g, rhino3dm.InstanceReference):
            idef = f.InstanceDefinitions.FindId(g.ParentIdefId)
            if idef is None:
                continue
            xf = xform_to_np(g.Xform)
            for oid in idef.GetObjectIds():
                dobj = f.Objects.FindId(oid)
                if dobj is not None and not layer_visible(dobj.Attributes.LayerIndex):
                    continue
                if dobj is not None:
                    add(dobj.Geometry, dobj.Attributes, xf, bbox_geom=g)
        else:
            add(g, o.Attributes)

    # ponytail: O(n^2) bbox union-find, fine for <=3k objects per file
    n = len(entries)
    mins = np.array([e[0] for e in entries]) - MARGIN
    maxs = np.array([e[1] for e in entries]) + MARGIN
    parent = list(range(n))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for i in range(n):
        ov = (mins[i] <= maxs) & (mins <= maxs[i])
        for j in np.where(ov.all(axis=1))[0]:
            if j > i:
                ri, rj = find(i), find(int(j))
                if ri != rj:
                    parent[ri] = rj
    from collections import defaultdict
    clusters = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)
    keep = max(clusters.values(), key=lambda ids: sum(entries[i][2] for i in ids))
    dropped = n - len(keep)

    by_color = defaultdict(list)
    for i in keep:
        by_color[entries[i][3]].extend(entries[i][4])

    scene = trimesh.Scene()
    for col, parts in by_color.items():
        voff = 0; vs = []; ts = []
        for v, t in parts:
            vs.append(v); ts.append(t + voff); voff += len(v)
        mesh = trimesh.Trimesh(vertices=np.vstack(vs), faces=np.vstack(ts), process=False)
        mesh.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=[col[0], col[1], col[2], 255],
                metallicFactor=0.1, roughnessFactor=0.8))
        scene.add_geometry(mesh, node_name=f"c{col[0]}_{col[1]}_{col[2]}")

    out = os.path.join(DST, name.replace(".3dm", ".glb"))
    scene.export(out)
    nv = sum(len(m.vertices) for m in scene.geometry.values())
    print(f"{name}: kept {len(keep)}/{n} objs ({dropped} parked-detail dropped), "
          f"{len(by_color)} color groups, {nv} verts -> {os.path.getsize(out)/1e6:.1f} MB")

for name in sys.argv[1:]:
    convert(name)
