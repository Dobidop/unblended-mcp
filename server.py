"""
unblended-mcp — MCP server that exposes headless Blender via unblended.

Provides both raw access (exec/eval) and high-level convenience tools
for common Blender operations.

Run:  python server.py
"""

import sys
import os
import json

# unblended lives next door
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "unBlended"))

from mcp.server.fastmcp import FastMCP
from unblended import BlenderSession, BlenderError

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "unblended-mcp",
    instructions=(
        "This server controls a headless Blender instance. "
        "You can run arbitrary bpy Python code via blender_exec/blender_eval, "
        "or use the high-level tools for common operations. "
        "The Blender session persists across calls — state (objects, materials, "
        "scene setup) carries over between tool invocations."
    ),
)

# ---------------------------------------------------------------------------
# Session lifecycle — lazy start, kept alive across tool calls
# ---------------------------------------------------------------------------

_session: BlenderSession | None = None


def _get_session() -> BlenderSession:
    """Return the active BlenderSession, starting one if needed."""
    global _session
    if _session is None or not _session.ping():
        if _session is not None:
            try:
                _session.close()
            except Exception:
                pass
        _session = BlenderSession()
        _session.start()
    return _session


# ---------------------------------------------------------------------------
# Raw tools — full bpy power
# ---------------------------------------------------------------------------


@mcp.tool()
def blender_exec(code: str) -> str:
    """
    Execute arbitrary Python code inside the Blender process.

    The code has full access to bpy and all of Blender's Python API.
    The namespace persists between calls, so you can define variables
    and functions that are available in subsequent calls.

    Args:
        code: Python code to execute (can be multi-line).

    Returns:
        "ok" on success.
    """
    b = _get_session()
    b.exec(code)
    return "ok"


@mcp.tool()
def blender_eval(expression: str) -> str:
    """
    Evaluate a Python expression inside Blender and return the result.

    Useful for querying scene state, reading object properties, etc.
    Blender-specific types (Vector, Matrix) are converted to plain
    lists/numbers automatically.

    Args:
        expression: A Python expression to evaluate.

    Returns:
        The result as a JSON string.
    """
    b = _get_session()
    result = b.eval(expression)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def blender_run_script(script_path: str) -> str:
    """
    Execute a Python script file inside Blender.

    The script has access to the full bpy module and the persistent
    namespace.

    Args:
        script_path: Absolute path to a .py file.

    Returns:
        "ok" on success.
    """
    b = _get_session()
    b.run(script_path)
    return "ok"


# ---------------------------------------------------------------------------
# High-level tools — common operations
# ---------------------------------------------------------------------------


@mcp.tool()
def blender_status() -> str:
    """
    Get the current state of the Blender session.

    Returns Blender version, scene objects, active object, and
    render settings.
    """
    b = _get_session()
    info = {
        "blender_version": b.blender_version(),
        "scene_objects": b.list_objects(),
        "active_object": b.eval(
            "bpy.context.active_object.name if bpy.context.active_object else None"
        ),
        "render_engine": b.eval("bpy.context.scene.render.engine"),
        "resolution": b.eval(
            "[bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y]"
        ),
    }
    return json.dumps(info, indent=2)


@mcp.tool()
def blender_clear_scene() -> str:
    """
    Delete all objects, materials, and images from the scene.
    Gives you a blank slate.
    """
    b = _get_session()
    b.clear_scene()
    return "Scene cleared"


@mcp.tool()
def blender_open(blend_path: str) -> str:
    """
    Open a .blend file, replacing the current scene.

    Args:
        blend_path: Absolute path to a .blend file.
    """
    b = _get_session()
    b.open_blend(blend_path)
    objects = b.list_objects()
    return json.dumps({"opened": blend_path, "objects": objects}, indent=2)


@mcp.tool()
def blender_save(blend_path: str) -> str:
    """
    Save the current scene to a .blend file.

    Args:
        blend_path: Absolute path for the output .blend file.
    """
    b = _get_session()
    b.save_blend(blend_path)
    return f"Saved to {blend_path}"


@mcp.tool()
def blender_render(
    output_path: str,
    engine: str = "CYCLES",
    samples: int = 64,
    resolution_x: int = 1024,
    resolution_y: int = 1024,
    use_gpu: bool = True,
) -> str:
    """
    Render the current scene to an image file.

    Args:
        output_path: Absolute file path for the rendered image (e.g. .png).
        engine: Render engine — "CYCLES" or "BLENDER_EEVEE_NEXT".
        samples: Number of render samples.
        resolution_x: Image width in pixels.
        resolution_y: Image height in pixels.
        use_gpu: Use GPU rendering (CUDA/OptiX) if available.
    """
    b = _get_session()
    b.render(
        output_path,
        engine=engine,
        samples=samples,
        resolution=(resolution_x, resolution_y),
        use_gpu=use_gpu,
    )
    return f"Rendered to {output_path}"


@mcp.tool()
def blender_add_object(
    type: str,
    name: str = "",
    location: list[float] = [0, 0, 0],
    rotation: list[float] = [0, 0, 0],
    scale: list[float] = [1, 1, 1],
    params: str = "",
) -> str:
    """
    Add a mesh primitive or other object to the scene.

    Args:
        type: Object type. One of: cube, sphere, uv_sphere, cylinder,
              cone, torus, plane, circle, monkey, empty, camera, light.
        name: Optional name for the object.
        location: [x, y, z] position.
        rotation: [x, y, z] rotation in degrees.
        scale: [x, y, z] scale factors.
        params: Extra keyword args as a Python dict string,
                e.g. "segments=64, ring_count=32" for a UV sphere.
    """
    b = _get_session()

    ops_map = {
        "cube": "bpy.ops.mesh.primitive_cube_add",
        "sphere": "bpy.ops.mesh.primitive_uv_sphere_add",
        "uv_sphere": "bpy.ops.mesh.primitive_uv_sphere_add",
        "ico_sphere": "bpy.ops.mesh.primitive_ico_sphere_add",
        "cylinder": "bpy.ops.mesh.primitive_cylinder_add",
        "cone": "bpy.ops.mesh.primitive_cone_add",
        "torus": "bpy.ops.mesh.primitive_torus_add",
        "plane": "bpy.ops.mesh.primitive_plane_add",
        "circle": "bpy.ops.mesh.primitive_circle_add",
        "monkey": "bpy.ops.mesh.primitive_monkey_add",
        "empty": "bpy.ops.object.empty_add",
        "camera": "bpy.ops.object.camera_add",
        "light": "bpy.ops.object.light_add",
    }

    op = ops_map.get(type.lower())
    if not op:
        return f"Unknown type '{type}'. Supported: {', '.join(ops_map.keys())}"

    extra = f", {params}" if params else ""
    code = f"""
import math
{op}(location=loc, rotation=tuple(math.radians(r) for r in rot){extra})
obj = bpy.context.active_object
if obj_name:
    obj.name = obj_name
obj.scale = tuple(sc)
"""
    b.exec(
        code,
        loc=location,
        rot=rotation,
        sc=scale,
        obj_name=name,
    )
    result_name = b.eval("bpy.context.active_object.name")
    return json.dumps({"created": result_name, "type": type}, indent=2)


@mcp.tool()
def blender_add_modifier(
    object_name: str,
    modifier_type: str,
    settings: str = "",
) -> str:
    """
    Add a modifier to an object.

    Args:
        object_name: Name of the target object.
        modifier_type: Blender modifier type, e.g. "SUBSURF", "MIRROR",
                       "BOOLEAN", "ARRAY", "SOLIDIFY", "BEVEL", etc.
        settings: Python code to configure the modifier. The modifier
                  is available as 'mod'. Example:
                  "mod.levels = 2; mod.render_levels = 3"
    """
    b = _get_session()
    code = f"""
obj = bpy.data.objects[obj_name]
bpy.context.view_layer.objects.active = obj
mod = obj.modifiers.new(name=mod_type, type=mod_type)
{settings}
"""
    b.exec(code, obj_name=object_name, mod_type=modifier_type)
    return f"Added {modifier_type} modifier to '{object_name}'"


@mcp.tool()
def blender_set_material(
    object_name: str,
    color: list[float] = [0.8, 0.8, 0.8],
    roughness: float = 0.5,
    metallic: float = 0.0,
    material_name: str = "",
) -> str:
    """
    Create and assign a simple Principled BSDF material to an object.

    For complex materials (textures, nodes), use blender_exec instead.

    Args:
        object_name: Name of the target object.
        color: [R, G, B] base color (0.0 - 1.0 each).
        roughness: Surface roughness (0 = mirror, 1 = matte).
        metallic: Metallic factor (0 = dielectric, 1 = metal).
        material_name: Optional name for the material.
    """
    b = _get_session()
    code = """
obj = bpy.data.objects[obj_name]
mat_name = custom_mat_name or f"{obj_name}_Material"
mat = bpy.data.materials.new(name=mat_name)
mat.use_nodes = True
nodes = mat.node_tree.nodes
principled = nodes.get("Principled BSDF")
principled.inputs['Base Color'].default_value = (color[0], color[1], color[2], 1.0)
principled.inputs['Roughness'].default_value = roughness
principled.inputs['Metallic'].default_value = metallic
if obj.data.materials:
    obj.data.materials[0] = mat
else:
    obj.data.materials.append(mat)
"""
    b.exec(
        code,
        obj_name=object_name,
        color=color,
        roughness=roughness,
        metallic=metallic,
        custom_mat_name=material_name,
    )
    return f"Material applied to '{object_name}'"


@mcp.tool()
def blender_setup_camera(
    location: list[float] = [5, -5, 4],
    look_at: list[float] = [0, 0, 0],
    lens: float = 50.0,
) -> str:
    """
    Add (or replace) the scene camera, aimed at a target point.

    Args:
        location: [x, y, z] camera position.
        look_at: [x, y, z] point the camera looks at.
        lens: Focal length in mm.
    """
    b = _get_session()
    code = """
from mathutils import Vector

# Remove existing cameras
for obj in list(bpy.data.objects):
    if obj.type == 'CAMERA':
        bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.object.camera_add(location=tuple(cam_loc))
cam = bpy.context.active_object
cam.name = "Camera"
direction = Vector(tuple(target)) - Vector(tuple(cam_loc))
cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
cam.data.lens = focal_length
bpy.context.scene.camera = cam
"""
    b.exec(code, cam_loc=location, target=look_at, focal_length=lens)
    return f"Camera at {location} looking at {look_at}"


@mcp.tool()
def blender_setup_lighting(
    type: str = "three_point",
    energy: float = 300.0,
) -> str:
    """
    Set up a lighting rig in the scene.

    Removes any existing lights first.

    Args:
        type: Lighting preset — "three_point", "sun", or "hdri_sky".
        energy: Base energy/strength multiplier.
    """
    b = _get_session()

    # Remove existing lights
    b.exec("""
for obj in list(bpy.data.objects):
    if obj.type == 'LIGHT':
        bpy.data.objects.remove(obj, do_unlink=True)
""")

    if type == "three_point":
        code = """
import math
bpy.ops.object.light_add(type='AREA', location=(4, -4, 6))
key = bpy.context.active_object
key.name = "KeyLight"
key.data.energy = energy
key.data.size = 3
key.rotation_euler = (math.radians(55), 0, math.radians(45))

bpy.ops.object.light_add(type='AREA', location=(-3, -2, 4))
fill = bpy.context.active_object
fill.name = "FillLight"
fill.data.energy = energy * 0.33
fill.data.size = 5
fill.rotation_euler = (math.radians(60), 0, math.radians(-30))

bpy.ops.object.light_add(type='AREA', location=(0, 5, 3))
rim = bpy.context.active_object
rim.name = "RimLight"
rim.data.energy = energy * 0.5
rim.data.size = 2
rim.rotation_euler = (math.radians(110), 0, 0)
"""
    elif type == "sun":
        code = """
import math
bpy.ops.object.light_add(type='SUN', location=(0, 0, 10))
sun = bpy.context.active_object
sun.name = "Sun"
sun.data.energy = energy / 100
sun.rotation_euler = (math.radians(50), 0, math.radians(30))
"""
    elif type == "hdri_sky":
        code = """
world = bpy.context.scene.world
if world is None:
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
world.use_nodes = True
nodes = world.node_tree.nodes
links = world.node_tree.links
bg = nodes.get("Background") or nodes.new("ShaderNodeBackground")
bg.inputs['Strength'].default_value = energy / 300
bg.inputs['Color'].default_value = (0.05, 0.1, 0.2, 1)
sky = nodes.new("ShaderNodeTexSky")
sky.sky_type = 'NISHITA'
links.new(sky.outputs['Color'], bg.inputs['Color'])
"""
    else:
        return f"Unknown lighting type '{type}'. Use: three_point, sun, hdri_sky"

    b.exec(code, energy=energy)
    return f"{type} lighting set up (energy={energy})"


@mcp.tool()
def blender_import_model(file_path: str) -> str:
    """
    Import a 3D model file (.obj, .fbx, .stl, .blend).

    Automatically detects the format from the file extension.

    Args:
        file_path: Absolute path to the model file.
    """
    b = _get_session()
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".obj":
        name = b.import_obj(file_path)
    elif ext == ".fbx":
        name = b.import_fbx(file_path)
    elif ext == ".stl":
        name = b.import_stl(file_path)
    elif ext == ".blend":
        b.exec("""
with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
    data_to.objects = data_from.objects
for obj in data_to.objects:
    if obj is not None:
        bpy.context.collection.objects.link(obj)
        bpy.context.view_layer.objects.active = obj
""", path=file_path)
        name = b.eval("bpy.context.active_object.name if bpy.context.active_object else None")
    else:
        return f"Unsupported format: {ext}"

    objects = b.list_objects()
    return json.dumps({"imported": name, "format": ext, "scene_objects": objects}, indent=2)


@mcp.tool()
def blender_list_objects() -> str:
    """List all objects in the current scene with their types and locations."""
    b = _get_session()
    result = b.eval("""
[{
    "name": o.name,
    "type": o.type,
    "location": [round(v, 3) for v in o.location],
    "visible": not o.hide_viewport
} for o in bpy.data.objects]
""")
    return json.dumps(result, indent=2)


@mcp.tool()
def blender_delete_object(object_name: str) -> str:
    """
    Delete an object from the scene by name.

    Args:
        object_name: Name of the object to delete.
    """
    b = _get_session()
    b.exec("""
obj = bpy.data.objects.get(name)
if obj:
    bpy.data.objects.remove(obj, do_unlink=True)
else:
    raise ValueError(f"Object '{name}' not found")
""", name=object_name)
    return f"Deleted '{object_name}'"


@mcp.tool()
def blender_transform_object(
    object_name: str,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    scale: list[float] | None = None,
) -> str:
    """
    Move, rotate, or scale an object.

    Args:
        object_name: Name of the object.
        location: [x, y, z] new position (or null to keep current).
        rotation: [x, y, z] new rotation in degrees (or null to keep).
        scale: [x, y, z] new scale (or null to keep).
    """
    b = _get_session()
    code = """
import math
obj = bpy.data.objects[name]
if new_loc is not None:
    obj.location = tuple(new_loc)
if new_rot is not None:
    obj.rotation_euler = tuple(math.radians(r) for r in new_rot)
if new_sc is not None:
    obj.scale = tuple(new_sc)
"""
    b.exec(code, name=object_name, new_loc=location, new_rot=rotation, new_sc=scale)
    return f"Transformed '{object_name}'"


# ---------------------------------------------------------------------------
# Shutdown hook
# ---------------------------------------------------------------------------

import atexit

@atexit.register
def _cleanup():
    global _session
    if _session is not None:
        try:
            _session.close()
        except Exception:
            pass
        _session = None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start Blender eagerly so the session is warm before any tool call.
    # This avoids MCP client timeouts on the first invocation.
    _get_session()
    mcp.run()
