import bpy
import math
import random
import bmesh
from array import array
from mathutils import Vector, Quaternion
from bpy.props import (
    IntProperty,
    FloatProperty,
    BoolProperty,
    StringProperty,
    EnumProperty,
    PointerProperty,
)
from bpy.types import PropertyGroup, Operator, Panel


# ============================================================
# PROPERTY GROUPS (one per panel category)
# ============================================================

class TREEGEN_PG_Tree(PropertyGroup):
    seed: IntProperty(name="Seed", default=84)
    collection_name: StringProperty(name="Collection", default="GeneratedTree")
    tree_height: FloatProperty(name="Tree Height", default=8.0, min=0.1, unit='LENGTH')
    trunk_radius: FloatProperty(name="Trunk Radius", default=0.8, min=0.01, unit='LENGTH')
    trunk_segments: IntProperty(name="Trunk Segments", default=16, min=2)
    trunk_sides: IntProperty(name="Trunk Sides", default=12, min=3)
    trunk_bend: FloatProperty(
        name="Trunk Bend", default=0.0, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "0 keeps the trunk vertical (only the usual per-ring jitter moves it). "
            "1 leans it 90% of the way to fully horizontal by the top"
        ),
    )


class TREEGEN_PG_Branches(PropertyGroup):
    main_branch_count: IntProperty(name="Count", default=8, min=0)
    branch_min_height: FloatProperty(
        name="Min Height", default=0.25, min=0.0, max=1.0, subtype='FACTOR',
        description="Fraction of tree height below which branches cannot start",
    )
    branch_max_height: FloatProperty(
        name="Max Height", default=0.85, min=0.0, max=1.0, subtype='FACTOR',
        description="Fraction of tree height above which branches cannot start",
    )
    branch_min_spacing: FloatProperty(
        name="Min Spacing", default=0.08, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "Minimum gap between two branch origins, as a fraction of the full trunk "
            "height. 0 allows branches at the same point, 1 forces opposite ends"
        ),
    )
    branch_angle_order: FloatProperty(
        name="Angle Order", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "How evenly the main branches are spaced around the trunk's "
            "360 degrees. 0 picks each branch's angle fully at random, "
            "which can cluster several branches on one side and leave the "
            "canopy lopsided; 1 spaces every branch perfectly evenly "
            "around the trunk instead, so there's a branch on each side "
            "and the canopy fills out fully. Even at 1, which evenly-spaced "
            "slot each branch gets is shuffled rather than assigned in "
            "height order, so the angle doesn't spiral steadily upward"
        ),
    )
    branch_same_height_chance: FloatProperty(
        name="Same Height Chance", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "Chance that, while moving up the trunk placing one branch per "
            "height, an extra branch also spawns at that exact same "
            "height - like a whorl of branches instead of a single one. "
            "That extra branch's angle still follows Angle Order along "
            "with every other branch. 0 always just moves on to the next "
            "height as usual; 1 always adds the extra branch"
        ),
    )
    branch_length_min: FloatProperty(name="Length Min", default=2.0, min=0.0, unit='LENGTH')
    branch_length_max: FloatProperty(name="Length Max", default=5.2, min=0.0, unit='LENGTH')
    branch_long_ratio: FloatProperty(
        name="Long Ratio", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        description="0 = all branches short, 1 = all long, 0.5 = an even mix of both",
    )
    branch_thickness: FloatProperty(
        name="Thickness", default=0.6, min=0.0,
        description="Relative to the trunk's tapered radius at the attach point, not an absolute width",
    )
    branch_thickness_random: FloatProperty(name="Thickness Random", default=0.5, min=0.0, max=1.0, subtype='FACTOR')
    branch_curvature: FloatProperty(
        name="Curvature", default=1.0, min=0.0,
        description="Above 1 winds the branch further around its own axis per segment, coiling into a spiral",
    )
    branch_segments: IntProperty(name="Segments", default=12, min=2)
    join_branches_with_trunk: BoolProperty(
        name="Join Branches With Trunk", default=False,
        description=(
            "Join every main branch (already joined with its own "
            "secondaries) into the trunk as a single object, instead of "
            "leaving branches and trunk as separate objects. A plain "
            "join, not a Boolean - any hidden overlap where a branch "
            "pokes into the trunk is left as-is"
        ),
    )


class TREEGEN_PG_Secondary(PropertyGroup):
    split_chance: FloatProperty(name="Split Chance", default=0.6, min=0.0, max=1.0, subtype='FACTOR')
    split_min: FloatProperty(
        name="Split Position Min", default=0.30, min=0.0, max=1.0, subtype='FACTOR',
        description="Where along the branch's own length (0 = base, 1 = tip) a split can occur",
    )
    split_max: FloatProperty(name="Split Position Max", default=0.68, min=0.0, max=1.0, subtype='FACTOR')
    secondary_count_min: IntProperty(name="Secondary Count Min", default=2, min=0)
    secondary_count_max: IntProperty(name="Secondary Count Max", default=4, min=0)
    secondary_length_min: FloatProperty(
        name="Secondary Length Min", default=0.30, min=0.0,
        description="Fraction of the parent's length",
    )
    secondary_length_max: FloatProperty(name="Secondary Length Max", default=0.6, min=0.0)
    secondary_thickness: FloatProperty(
        name="Secondary Thickness", default=0.7, min=0.0,
        description="Relative to the parent's local radius at the split point",
    )
    merge_secondary_into_main: BoolProperty(
        name="Merge Secondary Into Main", default=True,
        description=(
            "Trim away each secondary branch's overlap with the branch it "
            "grows from via Boolean Difference before joining it in, "
            "instead of joining the raw meshes straight together. A main "
            "branch and its secondary branches always end up joined into "
            "a single object either way; this only removes the hidden "
            "overlap a plain join would leave behind"
        ),
    )


class TREEGEN_PG_Roots(PropertyGroup):
    root_count_min: IntProperty(name="Count Min", default=3, min=0)
    root_count_max: IntProperty(name="Count Max", default=9, min=0)
    root_attach_distance: FloatProperty(
        name="Attach Distance", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "How far from the trunk's central axis each root starts, as a "
            "fraction of the trunk's base radius. 0 starts every root at "
            "the trunk's center; 1 starts it right at the trunk's outer "
            "edge. Each root's initial growth direction follows the "
            "trunk's own tapered surface normal at that point either way, "
            "and it's still raised just enough to never dip below the "
            "trunk's bottom boundary"
        ),
    )
    root_thickness: FloatProperty(name="Thickness", default=0.5, min=0.0)
    root_thickness_random: FloatProperty(name="Thickness Random", default=0.5, min=0.0, max=1.0, subtype='FACTOR')
    root_radius_min: FloatProperty(
        name="Radius Min", default=0.25, min=0.0,
        description="Absolute clamp applied after Thickness/Thickness Random",
    )
    root_radius_max: FloatProperty(name="Radius Max", default=0.75, min=0.0)
    root_length_min: FloatProperty(name="Length Min", default=1.5, min=0.0)
    root_length_max: FloatProperty(name="Length Max", default=4.5, min=0.0)
    root_curvature: FloatProperty(name="Curvature", default=1.5, min=0.0)
    root_lateral_curvature: FloatProperty(
        name="Lateral Curvature", default=3.0, min=0.0,
        description=(
            "Strength of random left/right (horizontal) bending as each "
            "root grows, independent of the up-then-down curve driven by "
            "Curvature. 0 keeps growth confined to a single vertical "
            "plane; higher values wander further side to side"
        ),
    )
    root_segments: IntProperty(name="Segments", default=12, min=2)
    root_upward_phase: FloatProperty(
        name="Upward Phase", default=0.0, min=0.0, max=0.99, subtype='FACTOR',
        description=(
            "Fraction of each root's length that arcs opposite the eventual downward "
            "pull before it starts diving down, instead of bending straight down immediately"
        ),
    )
    root_split_chance: FloatProperty(name="Split Chance", default=0.65, min=0.0, max=1.0, subtype='FACTOR')
    root_secondary_count_min: IntProperty(name="Secondary Count Min", default=1, min=0)
    root_secondary_count_max: IntProperty(name="Secondary Count Max", default=2, min=0)
    root_secondary_length_min: FloatProperty(name="Secondary Length Min", default=0.3, min=0.0)
    root_secondary_length_max: FloatProperty(name="Secondary Length Max", default=0.6, min=0.0)
    root_secondary_thickness: FloatProperty(name="Secondary Thickness", default=0.5, min=0.0)
    merge_secondary_roots_into_main: BoolProperty(
        name="Merge Secondary Roots Into Main", default=True,
        description=(
            "Trim away each secondary root's overlap with the root it "
            "grows from via Boolean Difference before joining it in, "
            "instead of joining the raw meshes straight together. Roots "
            "always end up joined into a single object either way; this "
            "only removes the hidden overlap a plain join would leave behind"
        ),
    )
    merge_roots_into_trunk: BoolProperty(
        name="Merge Roots Into Trunk", default=True,
        description=(
            "Trim away each root's overlap with the trunk via Boolean "
            "Difference before joining it in, instead of joining the raw "
            "root mesh straight into the trunk. Roots always end up "
            "joined into the trunk as a single object either way; this "
            "only removes the hidden overlap a plain join would leave behind"
        ),
    )


class TREEGEN_PG_Mesh(PropertyGroup):
    decimate_trunk: BoolProperty(
        name="Decimate Trunk", default=False,
        description="Simplify the trunk mesh (includes roots if joined into it). Off by default to keep generation fast",
    )
    trunk_decimate_ratio: FloatProperty(name="Trunk Decimate Ratio", default=0.65, min=0.0, max=1.0, subtype='FACTOR')

    decimate_leaves: BoolProperty(
        name="Decimate Leaves", default=False,
        description="Simplify each merged leaf mesh. Off by default to keep generation fast",
    )
    leaves_decimate_ratio: FloatProperty(name="Leaves Decimate Ratio", default=0.65, min=0.0, max=1.0, subtype='FACTOR')


class TREEGEN_PG_Leaves(PropertyGroup):
    generate_leaves: BoolProperty(
        name="Generate Leaves", default=False,
        description="Disable to generate a bare tree with no leaf clusters",
    )
    foliage_type: EnumProperty(
        name="Foliage Type",
        items=(
            (
                'ICOSPHERE', "Icosphere Clusters",
                "Scatter deformed icosphere blobs along each branch and the canopy top",
            ),
            (
                'PINE', "Pine Canopy",
                "Build a single tapering stack of low-poly cone tiers along the trunk, like a conifer",
            ),
        ),
        default='ICOSPHERE',
        description="How the tree's foliage mass is shaped",
    )
    merge_leaves_with_union: BoolProperty(
        name="Merge Leaves (Union)", default=True,
        description="Merge each branch's leaf clusters into one mesh via boolean UNION",
    )
    join_all_leaves: BoolProperty(
        name="Join All Leaves Into One Mesh", default=False,
        description="Join every branch's leaf mesh (and the canopy fill) into a single object",
    )
    leaves_per_branch_min: IntProperty(name="Per Branch Min", default=3, min=0)
    leaves_per_branch_max: IntProperty(name="Per Branch Max", default=9, min=0)
    leaf_scale_min: FloatProperty(name="Scale Min", default=0.35, min=0.0)
    leaf_scale_max: FloatProperty(name="Scale Max", default=0.6, min=0.0)
    leaf_spread: FloatProperty(
        name="Spread", default=1.0, min=0.0,
        description="How far an individual cluster can drift from its branch attach point",
    )
    leaf_width: FloatProperty(name="Width", default=2.0, min=0.0)
    leaf_depth: FloatProperty(name="Depth", default=2.0, min=0.0)
    leaf_height: FloatProperty(name="Height", default=0.95, min=0.0)
    bottom_distortion: FloatProperty(
        name="Bottom Distortion", default=1.0, min=0.0, soft_max=1.0, max=10.0, subtype='FACTOR',
        description=(
            "How much each leaf cluster's lower hemisphere gets pulled "
            "further downward at random, breaking the underside into an "
            "irregular, dangling silhouette instead of a flat or evenly "
            "rounded one. 0 leaves the bottom as smooth as the top; 1 is "
            "the original full-strength stretch, and values above 1 push "
            "it further still"
        ),
    )

    pine_tier_count: IntProperty(
        name="Tier Count", default=6, min=1, max=40,
        description="How many stacked cone tiers make up the canopy",
    )
    pine_canopy_start: FloatProperty(
        name="Canopy Start", default=0.30, min=0.0, max=0.95, subtype='FACTOR',
        description="Fraction of the way up the trunk where the lowest, widest tier begins",
    )
    pine_base_radius: FloatProperty(
        name="Base Radius", default=2.4, min=1.0,
        description=(
            "How many times wider than the trunk itself the lowest tier "
            "flares out. Every tier's radius is measured relative to the "
            "trunk's own (tapered) radius at that height, shrinking down to "
            "exactly 1.0 (an exact fit) at the topmost tier, so the trunk "
            "is never left wider than the foliage around it"
        ),
    )
    pine_tier_overlap: FloatProperty(
        name="Tier Overlap", default=0.45, min=0.0, max=0.95, subtype='FACTOR',
        description="How far each tier's cone extends down into the tier below, hiding the seam between them",
    )
    pine_vertical_width: FloatProperty(
        name="Vertical Width", default=1.0, min=0.0,
        description=(
            "Multiplier on each tier's own vertical height (how far its "
            "apex reaches above its base), on top of Tier Overlap. No "
            "upper limit, so tiers can be stretched arbitrarily tall"
        ),
    )
    pine_taper: FloatProperty(
        name="Taper", default=1.4, min=0.1,
        description=(
            "How quickly tiers shrink in radius going up. Higher values pull "
            "the upper tiers in faster, ending in a sharper point"
        ),
    )
    pine_core_width: FloatProperty(
        name="Core Width", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "Radius of each tier's solid core, from the trunk's own "
            "centerline (0, so needles spring directly out of it) to the "
            "tier's full silhouette radius (1, where the needle tips land "
            "on that same radius too - a smooth rounded cone with no "
            "needles left showing)"
        ),
    )
    pine_prickliness: FloatProperty(
        name="Prickliness", default=0.35, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "How far each spike protrudes sideways beyond the tier's core "
            "(see Core Width). 0 keeps spikes flush with the core; 1 makes "
            "them stick out sharply - unless Core Width is 1, which always "
            "pulls them back flush regardless of this value"
        ),
    )
    pine_spike_tilt: FloatProperty(
        name="Spike Tilt", default=0.3, min=0.0, max=1.0, subtype='FACTOR',
        description=(
            "How far each spike tilts from pointing straight out away from "
            "the trunk (0) towards pointing straight down (1, almost "
            "vertical)"
        ),
    )
    pine_spike_horizontal_deform: FloatProperty(
        name="Spike Horizontal Deform", default=0.0, min=0.0,
        description=(
            "Random horizontal deflection of each spike's angle, so they "
            "aren't all perfectly radial (directed straight away from the "
            "trunk's center) - the same idea as Roots' Lateral Curvature"
        ),
    )
    pine_jitter: FloatProperty(
        name="Jitter", default=0.15, min=0.0, max=1.0, subtype='FACTOR',
        description="Random per-vertex variation applied to each tier's radius, so tiers don't look perfectly uniform",
    )
    pine_sides: IntProperty(
        name="Sides", default=8, min=3, max=32,
        description="Number of spikes around each tier",
    )


class TREEGEN_PG_Settings(PropertyGroup):
    tree: PointerProperty(type=TREEGEN_PG_Tree)
    branches: PointerProperty(type=TREEGEN_PG_Branches)
    secondary: PointerProperty(type=TREEGEN_PG_Secondary)
    roots: PointerProperty(type=TREEGEN_PG_Roots)
    mesh: PointerProperty(type=TREEGEN_PG_Mesh)
    leaves: PointerProperty(type=TREEGEN_PG_Leaves)


# ============================================================
# GENERATION LOGIC
# ============================================================

def generate_tree(context):
    settings = context.scene.tree_generator_settings
    tree_s = settings.tree
    branch_s = settings.branches
    secondary_s = settings.secondary
    root_s = settings.roots
    mesh_s = settings.mesh
    leaf_s = settings.leaves

    # Each process gets its own independent RNG stream, derived from the one
    # Seed field but never shared with any other process's stream. This is
    # what keeps every process free to run on its own: turning Leaves on/off
    # (or changing any other process's settings) changes only how many
    # random numbers that process's own stream produces, and can never shift
    # what number another process's stream hands out next. Only generation
    # order is fixed (trunk, then branches, then leaves, then roots) - never
    # a shared random sequence between them.
    rng_trunk = random.Random(tree_s.seed)
    rng_branches = random.Random(tree_s.seed + 1)
    rng_leaves = random.Random(tree_s.seed + 2)
    rng_roots = random.Random(tree_s.seed + 3)

    tree_collection_name = tree_s.collection_name
    tree_height = tree_s.tree_height
    trunk_radius = tree_s.trunk_radius
    trunk_segments = tree_s.trunk_segments
    trunk_sides = tree_s.trunk_sides
    trunk_bend = tree_s.trunk_bend

    main_branch_count = branch_s.main_branch_count
    branch_min_height = branch_s.branch_min_height
    branch_max_height = branch_s.branch_max_height
    branch_min_spacing = branch_s.branch_min_spacing
    branch_angle_order = branch_s.branch_angle_order
    branch_same_height_chance = branch_s.branch_same_height_chance
    branch_length_min = branch_s.branch_length_min
    branch_length_max = branch_s.branch_length_max
    branch_long_ratio = branch_s.branch_long_ratio
    branch_thickness = branch_s.branch_thickness
    branch_thickness_random = branch_s.branch_thickness_random
    branch_curvature = branch_s.branch_curvature
    branch_segments = branch_s.branch_segments
    join_branches_with_trunk = branch_s.join_branches_with_trunk

    split_chance = secondary_s.split_chance
    split_min = secondary_s.split_min
    split_max = secondary_s.split_max
    secondary_count_min = secondary_s.secondary_count_min
    secondary_count_max = secondary_s.secondary_count_max
    secondary_length_min = secondary_s.secondary_length_min
    secondary_length_max = secondary_s.secondary_length_max
    secondary_thickness = secondary_s.secondary_thickness
    merge_secondary_into_main = secondary_s.merge_secondary_into_main

    root_count_min = root_s.root_count_min
    root_count_max = root_s.root_count_max
    root_attach_distance = root_s.root_attach_distance
    root_thickness = root_s.root_thickness
    root_thickness_random = root_s.root_thickness_random
    root_radius_min = root_s.root_radius_min
    root_radius_max = root_s.root_radius_max
    root_length_min = root_s.root_length_min
    root_length_max = root_s.root_length_max
    root_curvature = root_s.root_curvature
    root_lateral_curvature = root_s.root_lateral_curvature
    root_segments = root_s.root_segments
    root_upward_phase = root_s.root_upward_phase
    root_split_chance = root_s.root_split_chance
    root_secondary_count_min = root_s.root_secondary_count_min
    root_secondary_count_max = root_s.root_secondary_count_max
    root_secondary_length_min = root_s.root_secondary_length_min
    root_secondary_length_max = root_s.root_secondary_length_max
    root_secondary_thickness = root_s.root_secondary_thickness
    merge_secondary_roots_into_main = root_s.merge_secondary_roots_into_main
    merge_roots_into_trunk = root_s.merge_roots_into_trunk

    decimate_trunk = mesh_s.decimate_trunk
    trunk_decimate_ratio = mesh_s.trunk_decimate_ratio
    decimate_leaves = mesh_s.decimate_leaves
    leaves_decimate_ratio = mesh_s.leaves_decimate_ratio

    generate_leaves = leaf_s.generate_leaves
    foliage_type = leaf_s.foliage_type
    merge_leaves_with_union = leaf_s.merge_leaves_with_union
    join_all_leaves = leaf_s.join_all_leaves
    leaves_per_branch_min = leaf_s.leaves_per_branch_min
    leaves_per_branch_max = leaf_s.leaves_per_branch_max
    leaf_scale_min = leaf_s.leaf_scale_min
    leaf_scale_max = leaf_s.leaf_scale_max
    leaf_spread = leaf_s.leaf_spread
    leaf_width = leaf_s.leaf_width
    leaf_depth = leaf_s.leaf_depth
    leaf_height = leaf_s.leaf_height
    bottom_distortion = leaf_s.bottom_distortion

    pine_tier_count = leaf_s.pine_tier_count
    pine_canopy_start = leaf_s.pine_canopy_start
    pine_base_radius = leaf_s.pine_base_radius
    pine_tier_overlap = leaf_s.pine_tier_overlap
    pine_vertical_width = leaf_s.pine_vertical_width
    pine_taper = leaf_s.pine_taper
    pine_core_width = leaf_s.pine_core_width
    pine_prickliness = leaf_s.pine_prickliness
    pine_spike_tilt = leaf_s.pine_spike_tilt
    pine_spike_horizontal_deform = leaf_s.pine_spike_horizontal_deform
    pine_jitter = leaf_s.pine_jitter
    pine_sides = leaf_s.pine_sides

    # --------------------------------------------------------
    # GENERATED TREE COLLECTION
    # --------------------------------------------------------

    tree_collection = bpy.data.collections.get(tree_collection_name)

    if tree_collection is None:
        tree_collection = bpy.data.collections.new(tree_collection_name)
        context.scene.collection.children.link(tree_collection)
    else:
        for obj in list(tree_collection.objects):
            bpy.data.objects.remove(obj, do_unlink=True)

    # --------------------------------------------------------
    # MATERIALS
    # --------------------------------------------------------

    def create_material(name, color, roughness=1.0):
        mat = bpy.data.materials.get(name)

        if mat is None:
            mat = bpy.data.materials.new(name)
            mat.use_nodes = True

        mat.diffuse_color = (*color, 1.0)
        mat.roughness = roughness

        # Drive the actual shader's Base Color too, not just the legacy
        # diffuse_color swatch, so the color shows up in render/export and
        # isn't left at the default Principled BSDF gray.
        principled = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
        if principled:
            principled.inputs["Base Color"].default_value = (*color, 1.0)
            principled.inputs["Roughness"].default_value = roughness

        return mat

    trunk_material = create_material("Tree_Trunk", (0.30, 0.12, 0.045))
    branch_material = create_material("Tree_Branch", (0.24, 0.085, 0.03))

    # Each leaf cluster is assigned one of these at random (see
    # create_leaf_cluster), and a cluster's material survives the later
    # boolean UNION merge, so the merged canopy mesh stays visibly made of
    # differently colored groups instead of a single flat green.
    leaf_materials = [
        create_material("Leaf_Dark", (0.07, 0.20, 0.045)),
        create_material("Leaf_Green", (0.14, 0.38, 0.07)),
        create_material("Leaf_Mid", (0.20, 0.48, 0.08)),
        create_material("Leaf_Light", (0.30, 0.58, 0.10)),
        create_material("Leaf_Highlight", (0.42, 0.62, 0.14)),
    ]

    # --------------------------------------------------------
    # COLLECTION HELPER
    # --------------------------------------------------------

    def move_to_tree_collection(obj):
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)

        tree_collection.objects.link(obj)

    # --------------------------------------------------------
    # CURVED MESH
    # --------------------------------------------------------

    def create_curved_mesh(points, radius_start, radius_end, rng, sides=6, material=None, name="Branch"):
        points = [Vector(p) for p in points]

        if len(points) < 2:
            return None

        verts = []
        faces = []

        # Rotation-minimizing frame: each ring's side/up basis is carried
        # forward from the previous ring by only the rotation needed to
        # match the new tangent, instead of being rebuilt from scratch
        # against a fixed global reference axis at every point. Rebuilding
        # from a fixed reference twists sharply (or even flips outright)
        # wherever the tangent swings past being near-parallel to that
        # reference - exactly what happens where a branch curves back
        # along its own growth axis.
        side = None
        up = None
        prev_tangent = None

        for i, point in enumerate(points):

            if i == 0:
                tangent = (points[1] - points[0]).normalized()
            elif i == len(points) - 1:
                tangent = (points[-1] - points[-2]).normalized()
            else:
                tangent = (points[i + 1] - points[i - 1]).normalized()

            if side is None:
                # First ring only: pick a reference axis that isn't
                # near-parallel to the tangent, otherwise the cross
                # product below degenerates towards zero.
                reference = Vector((0, 0, 1))
                if abs(tangent.dot(reference)) > 0.9:
                    reference = Vector((1, 0, 0))

                side = tangent.cross(reference).normalized()
                up = tangent.cross(side).normalized()
            else:
                rotation = prev_tangent.rotation_difference(tangent)
                side = rotation @ side
                side = (side - tangent * side.dot(tangent)).normalized()
                up = tangent.cross(side).normalized()

            prev_tangent = tangent

            t = i / (len(points) - 1)
            radius = radius_start + (radius_end - radius_start) * t
            # Small per-ring jitter so the taper isn't perfectly smooth.
            radius *= rng.uniform(0.94, 1.06)

            for s in range(sides):
                angle = (math.pi * 2 / sides) * s
                offset = side * math.cos(angle) * radius + up * math.sin(angle) * radius
                verts.append(tuple(point + offset))

        # Side faces: one quad per ring segment.
        for i in range(len(points) - 1):
            for s in range(sides):
                a = i * sides + s
                b = i * sides + (s + 1) % sides
                c = (i + 1) * sides + (s + 1) % sides
                d = (i + 1) * sides + s
                faces.append((a, b, c, d))

        # Bottom cap.
        faces.append(tuple(reversed(range(sides))))

        # Top cap.
        top_start = (len(points) - 1) * sides
        faces.append(tuple(top_start + i for i in range(sides)))

        mesh = bpy.data.meshes.new(name + "Mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        obj = bpy.data.objects.new(name, mesh)
        tree_collection.objects.link(obj)

        if material:
            obj.data.materials.append(material)

        for polygon in mesh.polygons:
            polygon.use_smooth = False

        return obj

    # --------------------------------------------------------
    # TRUNK
    # --------------------------------------------------------

    def create_trunk():
        verts = []
        faces = []
        ring_centers = []

        current_pos = Vector((0, 0, 0))
        step_length = tree_height / trunk_segments

        # A single random horizontal direction the trunk leans towards. The
        # angle between the growth direction and straight up ramps from 0 at
        # the base to trunk_bend * 81 degrees at the top (81 = 90% of 90).
        lean_angle = rng_trunk.uniform(0, math.pi * 2)
        lean_direction = Vector((math.cos(lean_angle), math.sin(lean_angle), 0))
        max_bend_angle = trunk_bend * (math.pi / 2) * 0.9

        for i in range(trunk_segments + 1):
            t = i / trunk_segments

            if i > 0:
                bend_angle = t * max_bend_angle

                growth_direction = (
                    Vector((0, 0, 1)) * math.cos(bend_angle)
                    + lean_direction * math.sin(bend_angle)
                ).normalized()

                current_pos += growth_direction * step_length

                # Per-ring horizontal jitter on top of the overall lean, so
                # the trunk still wobbles a little even at trunk_bend == 0.
                current_pos.x += rng_trunk.uniform(-0.16, 0.16)
                current_pos.y += rng_trunk.uniform(-0.16, 0.16)

            center = current_pos.copy()
            ring_centers.append(center.copy())

            # Taper down to 18% of the base radius by the top ring.
            radius = trunk_radius * (1.0 - t * 0.82)

            for s in range(trunk_sides):
                angle = (math.pi * 2 / trunk_sides) * s
                # Per-vertex jitter so the cross-section isn't a perfect circle.
                variation = rng_trunk.uniform(0.88, 1.12)
                x = math.cos(angle) * radius * variation
                y = math.sin(angle) * radius * variation
                verts.append((center.x + x, center.y + y, center.z))

        for i in range(trunk_segments):
            for s in range(trunk_sides):
                a = i * trunk_sides + s
                b = i * trunk_sides + (s + 1) % trunk_sides
                c = (i + 1) * trunk_sides + (s + 1) % trunk_sides
                d = (i + 1) * trunk_sides + s
                faces.append((a, b, c, d))

        faces.append(tuple(range(trunk_sides - 1, -1, -1)))

        top_start = trunk_segments * trunk_sides
        faces.append(tuple(top_start + i for i in range(trunk_sides)))

        mesh = bpy.data.meshes.new("TrunkMesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()

        obj = bpy.data.objects.new("TreeWood", mesh)
        tree_collection.objects.link(obj)
        obj.data.materials.append(trunk_material)

        for polygon in mesh.polygons:
            polygon.use_smooth = False

        return obj, ring_centers

    trunk, trunk_points = create_trunk()

    # --------------------------------------------------------
    # LEAF CLUSTER
    # --------------------------------------------------------

    # Scratch buffer of leaf clusters for whichever branch/canopy group is
    # currently being generated. Cleared and merged separately per group so
    # each branch ends up with its own leaf mesh instead of one for the tree.
    pending_leaf_clusters = []

    # Every leaf object still standing once each group is done with it (its
    # merged mesh if Merge Leaves (Union) is on, or its raw leaf clusters
    # otherwise), for the JOIN ALL LEAVES INTO ONE MESH step below.
    all_leaf_objects = []

    def create_leaf_cluster(position, scale):
        # Built directly via bmesh rather than bpy.ops.mesh.primitive_ico_sphere_add:
        # dozens of these get created per tree, and each bpy.ops call carries
        # real overhead (context validation, undo push, scene update) that
        # direct mesh-data creation skips.
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=1, radius=1.0)

        mesh = bpy.data.meshes.new("LeafClusterMesh")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new("LeafCluster", mesh)
        obj.location = position

        move_to_tree_collection(obj)

        # Bulk-edit vertex positions via foreach_get/foreach_set instead of
        # a per-vertex vertex.co loop: each .co access crosses the Python/C
        # boundary individually, which adds up over dozens of clusters.
        vert_count = len(mesh.vertices)
        coords = array('f', [0.0]) * (vert_count * 3)
        mesh.vertices.foreach_get('co', coords)

        for i in range(vert_count):
            base = i * 3
            # Hemisphere test uses the untouched unit-icosphere Z, captured
            # before this vertex's own coords get overwritten below.
            orig_z = coords[base + 2]

            coords[base] = coords[base] * (leaf_width * rng_leaves.uniform(0.94, 1.06))
            coords[base + 1] = coords[base + 1] * (leaf_depth * rng_leaves.uniform(0.94, 1.06))
            coords[base + 2] = coords[base + 2] * (leaf_height * rng_leaves.uniform(0.94, 1.06))

            if orig_z < 0.0 and bottom_distortion > 0.0:
                # Extra downward pull for the lower hemisphere only,
                # stronger the closer a vertex started to the bottom pole,
                # so the underside stretches into uneven dangling points
                # instead of bulging as a uniform blob. At 0 this is a
                # no-op, so the bottom matches the top exactly.
                coords[base + 2] -= bottom_distortion * rng_leaves.uniform(0.0, 1.0) * abs(orig_z) * leaf_height * 1.5

        mesh.vertices.foreach_set('co', coords)
        mesh.update()

        obj.scale = (scale, scale, scale)

        obj.rotation_euler = (
            rng_leaves.uniform(-0.15, 0.15),
            rng_leaves.uniform(-0.15, 0.15),
            rng_leaves.uniform(0, math.pi * 2),
        )

        obj.data.materials.append(rng_leaves.choice(leaf_materials))

        for polygon in obj.data.polygons:
            polygon.use_smooth = False

        pending_leaf_clusters.append(obj)

        return obj

    # --------------------------------------------------------
    # PINE CANOPY (alternate foliage type)
    # --------------------------------------------------------

    # These three read trunk_points/trunk_radius/trunk_segments (the bent
    # centerline create_trunk built and its taper formula) by a fractional
    # ring index, so the canopy can be positioned and sized as if it grows
    # directly out of the trunk's own surface at any height in between
    # rings, bend and all, instead of assuming a straight vertical trunk.

    def trunk_position_at(ring_index):
        ring_index = max(0.0, min(ring_index, len(trunk_points) - 1))
        i0 = int(math.floor(ring_index))
        i1 = min(i0 + 1, len(trunk_points) - 1)
        return trunk_points[i0].lerp(trunk_points[i1], ring_index - i0)

    def trunk_tangent_at(ring_index):
        ring_index = max(0.0, min(ring_index, len(trunk_points) - 1))
        i0 = int(math.floor(ring_index))
        i1 = min(i0 + 1, len(trunk_points) - 1)
        if i0 == i1:
            i0 = max(0, i0 - 1)
        return (trunk_points[i1] - trunk_points[i0]).normalized()

    def trunk_radius_at(ring_index):
        t = max(0.0, min(ring_index / trunk_segments, 1.0))
        return trunk_radius * (1.0 - t * 0.82)

    def create_pine_tier(
        base_position, tangent, radius, height, sides, rng, material,
        core_width, prickliness, spike_tilt, horizontal_deform,
        jitter, tier_rotation, name,
    ):
        # One tier is a jittered, star-shaped cone built directly in world
        # space around base_position: rim vertices alternate between a
        # "notch" (sitting exactly on the core radius) and a "spike" tip
        # (Prickliness controls how far it protrudes beyond the core,
        # blended against Core Width so the two coincide - a plain rounded
        # cone, no needles - once Core Width reaches 1. Spike Tilt blends
        # each spike's direction from straight outward to straight down,
        # and Horizontal Deform randomly deflects its angle off perfectly
        # radial). tangent is the trunk's own local growth direction at
        # this height, so the tier's apex leans the same way the trunk
        # does instead of always pointing world-up.
        bm = bmesh.new()

        reference = Vector((0, 0, 1))
        if abs(tangent.dot(reference)) > 0.9:
            reference = Vector((1, 0, 0))
        basis_x = tangent.cross(reference).normalized()
        basis_y = tangent.cross(basis_x).normalized()

        world_down = Vector((0.0, 0.0, -1.0))

        # core_width sweeps the notch radius from the trunk's own
        # centerline (0) out to the tier's full silhouette radius (1). The
        # spike radius is blended the same way, from its fully-extended
        # reach (core_width 0) down to that same core radius (core_width
        # 1) - so at 1 the notch and spike land on the exact same circle
        # and the star shape disappears into a smooth rounded cone, while
        # at 0 the notches collapse to the trunk's centerline and the
        # needles read as springing directly out of it.
        core_radius = radius * core_width
        max_spike_radius = radius * (1.0 + prickliness * 1.8)
        spike_radius = max_spike_radius * (1.0 - core_width) + core_radius * core_width

        rim_verts = []

        for s in range(sides):
            # angle_out is this spike's own slot; angle_in is the notch that
            # follows it, halfway to the next spike's slot. Appending in
            # that same angular order (spike, then its trailing notch) is
            # what keeps the rim a simple alternating star instead of a
            # self-crossing one - a notch appended out of angular order
            # would make the fan below bowtie across itself.
            angle_out = tier_rotation + (math.pi * 2 / sides) * s
            angle_in = angle_out + (math.pi / sides)

            deform = rng.uniform(-1.0, 1.0) * horizontal_deform * (math.pi / sides)
            spike_angle = angle_out + deform
            radial_dir = basis_x * math.cos(spike_angle) + basis_y * math.sin(spike_angle)
            spike_dir = (radial_dir * (1.0 - spike_tilt) + world_down * spike_tilt).normalized()
            spike_length = spike_radius * rng.uniform(1.0 - jitter, 1.0 + jitter)
            spike_pos = base_position + spike_dir * spike_length
            rim_verts.append(bm.verts.new(spike_pos))

            r_in = core_radius * rng.uniform(1.0 - jitter, 1.0 + jitter)
            inner_pos = base_position + (
                basis_x * math.cos(angle_in) + basis_y * math.sin(angle_in)
            ) * r_in
            rim_verts.append(bm.verts.new(inner_pos))

        apex = bm.verts.new(base_position + tangent * height)
        base_center = bm.verts.new(base_position)

        ring_count = len(rim_verts)
        for i in range(ring_count):
            a = rim_verts[i]
            b = rim_verts[(i + 1) % ring_count]
            bm.faces.new((apex, a, b))
            bm.faces.new((base_center, b, a))

        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

        mesh = bpy.data.meshes.new(name + "Mesh")
        bm.to_mesh(mesh)
        bm.free()

        obj = bpy.data.objects.new(name, mesh)

        move_to_tree_collection(obj)

        if material:
            obj.data.materials.append(material)

        for polygon in obj.data.polygons:
            polygon.use_smooth = False

        return obj

    def create_pine_canopy():
        # Tiers are stacked along the trunk's own (possibly bent) centerline
        # from Canopy Start up to the very last ring, widest at the bottom
        # and narrowing towards the tip (Taper). Each tier's radius is
        # measured relative to the trunk's own tapered radius at that ring,
        # collapsing to an exact 1:1 fit by the last tier - so that tier's
        # base exactly caps the trunk's tip, with nothing left exposed above
        # or beside it. Each tier is also tall enough (Tier Overlap) to bury
        # its own base inside the tier below, hiding the seam between them -
        # Vertical Width then scales that height further still, unbounded.
        trunk_top_index = len(trunk_points) - 1
        start_index = pine_canopy_start * trunk_top_index
        index_range = max(0.01, trunk_top_index - start_index)
        last = max(1, pine_tier_count - 1)

        base_indices = [start_index + (i / last) * index_range for i in range(pine_tier_count)]
        base_positions = [trunk_position_at(bi) for bi in base_indices]

        tier_objects = []

        for i in range(pine_tier_count):
            s = i / last
            base_index = base_indices[i]
            base_position = base_positions[i]

            tangent = trunk_tangent_at(base_index)
            radius = trunk_radius_at(base_index) * (1.0 + (pine_base_radius - 1.0) * (1.0 - s) ** pine_taper)

            if i < pine_tier_count - 1:
                step_distance = (base_positions[i + 1] - base_position).length
            elif pine_tier_count > 1:
                step_distance = (base_position - base_positions[i - 1]).length
            else:
                step_distance = index_range

            tier_height = max(0.01, step_distance) * (1.0 + pine_tier_overlap) * pine_vertical_width
            tier_rotation = rng_leaves.uniform(0.0, math.pi * 2)

            tier = create_pine_tier(
                base_position,
                tangent,
                radius,
                tier_height,
                pine_sides,
                rng_leaves,
                rng_leaves.choice(leaf_materials),
                pine_core_width,
                pine_prickliness,
                pine_spike_tilt,
                pine_spike_horizontal_deform,
                pine_jitter,
                tier_rotation,
                f"PineTier_{i}",
            )
            if decimate_leaves:
                decimate_object(tier, leaves_decimate_ratio)

            tier_objects.append(tier)

        # Left as separate per-tier objects, not pre-joined into one mesh -
        # otherwise Join All Leaves Into One Mesh would have nothing left to
        # do for a Pine Canopy. The JOIN ALL LEAVES step further down joins
        # them (along with everything else in all_leaf_objects) if and only
        # if that toggle is on.
        return tier_objects

    # --------------------------------------------------------
    # DECIMATE (mesh simplification)
    # --------------------------------------------------------

    def decimate_object(obj, ratio):
        context.view_layer.objects.active = obj
        obj.select_set(True)

        decimate = obj.modifiers.new(name="LowPoly", type='DECIMATE')
        decimate.ratio = ratio
        bpy.ops.object.modifier_apply(modifier=decimate.name)

        for polygon in obj.data.polygons:
            polygon.use_smooth = False

        obj.select_set(False)

        return obj

    # --------------------------------------------------------
    # CLEANUP MESH
    # --------------------------------------------------------

    # Tracks every object cleanup_mesh has already processed, so the final
    # sweep over the whole collection can skip re-cleaning objects that were
    # already cleaned right after their own join or merge step.
    cleaned_objects = set()

    def cleanup_mesh(obj):
        if obj is None or obj.type != 'MESH':
            return

        cleaned_objects.add(obj)

        mesh = obj.data
        bm = bmesh.new()

        try:
            bm.from_mesh(mesh)

            # Remove loose vertices / edges left over from joining meshes.
            loose_verts = [v for v in bm.verts if not v.link_faces]
            if loose_verts:
                bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

            loose_edges = [e for e in bm.edges if not e.link_faces]
            if loose_edges:
                bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

            # Remove degenerate/duplicate geometry from overlapping seams.
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

            bm.to_mesh(mesh)
            mesh.update()
        finally:
            bm.free()

        for polygon in mesh.polygons:
            polygon.use_smooth = False

    # --------------------------------------------------------
    # BOOLEAN UNION MERGE HELPERS
    # --------------------------------------------------------

    def mesh_bounds(mesh):
        # Local-space AABB. All our procedural objects (trunk, branches,
        # roots, leaves) bake world coordinates directly into their mesh
        # data and keep an identity object transform, so local space here
        # is world space - no matrix conversion needed.
        if len(mesh.vertices) == 0:
            return None

        xs = [v.co.x for v in mesh.vertices]
        ys = [v.co.y for v in mesh.vertices]
        zs = [v.co.z for v in mesh.vertices]
        return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))

    def union_result_shrank(bounds_before, bounds_after, tolerance=0.01):
        # A correct UNION only ever adds material, so the result's bounding
        # box should always contain the pre-union one. If it doesn't, the
        # boolean solver silently ate part of the original geometry - a
        # real failure mode that a simple "is it empty" check misses,
        # since the corrupted result can still have plenty of polygons.
        if bounds_before is None:
            return False
        if bounds_after is None:
            return True

        for old_min, old_max, new_min, new_max in (
            (bounds_before[0], bounds_before[1], bounds_after[0], bounds_after[1]),
            (bounds_before[2], bounds_before[3], bounds_after[2], bounds_after[3]),
            (bounds_before[4], bounds_before[5], bounds_after[4], bounds_after[5]),
        ):
            if new_min > old_min + tolerance or new_max < old_max - tolerance:
                return True

        return False

    def recalc_normals(obj):
        # Correct any inside-out geometry a previous CSG step left behind
        # before it's used again. Blender's boolean solver reads face
        # winding to tell "solid" from "empty"; an inverted operand can
        # make the NEXT union behave like a subtraction - carving a hole
        # where it should have added material, and hiding the operand's
        # own shape entirely. A bounding-box check alone doesn't catch
        # this, since flipping normals doesn't change the extent.
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

    def mesh_has_open_boundary(mesh):
        # A correct union (or a plain join) of watertight inputs is always
        # itself watertight - every one of our procedural meshes (trunk,
        # branches, roots) is a fully capped, closed tube. Any edge shared
        # by only one face means the boolean solver actually dropped
        # geometry, leaving a hole - a failure mode the bounding-box check
        # can miss if the hole is on the interior of the silhouette.
        bm = bmesh.new()
        bm.from_mesh(mesh)
        has_boundary = any(edge.is_boundary for edge in bm.edges)
        bm.free()
        return has_boundary

    def apply_boolean_union_chain(objects):
        # Boolean-UNIONs every object in the list into the first one, one
        # operand at a time, each against its own untouched source object,
        # via Blender's own modifier_apply (which correctly folds in
        # materials, UVs, vertex groups, ... - a hand-rolled bmesh bake of
        # the evaluated stack was tried here before and got that wrong,
        # which is what was actually causing branches/the trunk to vanish).
        #
        # Certain overlapping/self-intersecting operand shapes can still
        # make a single union step degenerate (rare, but real - Blender's
        # boolean solver can silently erode previously-good geometry or
        # flip normals from bad input, not just produce an empty result).
        # Each step is backed up beforehand so a bad step can be rolled
        # back and retried as a plain join instead of losing what was
        # merged so far.
        merged = objects[0]
        operands = objects[1:]

        context.view_layer.objects.active = merged

        for other in operands:
            recalc_normals(other)

            backup_mesh = merged.data.copy()
            bounds_before = mesh_bounds(merged.data)

            boolean = merged.modifiers.new(name="UnionMerge", type='BOOLEAN')
            boolean.operation = 'UNION'
            boolean.object = other

            bpy.ops.object.modifier_apply(modifier=boolean.name)

            recalc_normals(merged)

            step_failed = (
                union_result_shrank(bounds_before, mesh_bounds(merged.data))
                or mesh_has_open_boundary(merged.data)
            )

            if step_failed:
                broken_mesh = merged.data
                merged.data = backup_mesh
                bpy.data.meshes.remove(broken_mesh)

                bpy.ops.object.select_all(action='DESELECT')
                merged.select_set(True)
                other.select_set(True)
                context.view_layer.objects.active = merged
                bpy.ops.object.join()
            else:
                bpy.data.meshes.remove(backup_mesh)
                bpy.data.objects.remove(other, do_unlink=True)

        return merged

    def merge_leaf_cluster_group(leaf_objects, name):
        # Collapses one group's leaf clusters (e.g. one branch's) into a
        # single mesh via boolean UNION. Each group gets merged
        # independently so the tree ends up with one leaf mesh per branch
        # instead of one for the whole tree.
        if not leaf_objects:
            return None

        # Record each sphere's world position and material up front, before
        # merging/deleting, so its material zone can be reassigned
        # explicitly afterwards (see apply_boolean_union_chain). Leaf
        # clusters are small and roughly uniform, so classifying by
        # distance to each sphere's center is accurate and cheap.
        cluster_info = [
            (obj.matrix_world.translation.copy(), obj.data.materials[0])
            for obj in leaf_objects
        ]

        leaves = apply_boolean_union_chain(leaf_objects)
        leaves.name = name

        unique_materials = []
        for _, mat in cluster_info:
            if mat not in unique_materials:
                unique_materials.append(mat)

        leaves.data.materials.clear()
        for mat in unique_materials:
            leaves.data.materials.append(mat)

        to_local = leaves.matrix_world.inverted()
        local_zones = [
            (to_local @ world_center, unique_materials.index(mat))
            for world_center, mat in cluster_info
        ]

        for polygon in leaves.data.polygons:
            face_center = polygon.center
            nearest_zone = min(
                local_zones,
                key=lambda zone: (zone[0] - face_center).length_squared,
            )
            polygon.material_index = nearest_zone[1]
            polygon.use_smooth = False

        if decimate_leaves:
            decimate_object(leaves, leaves_decimate_ratio)

        cleanup_mesh(leaves)

        return leaves

    # --------------------------------------------------------
    # BRANCH HEIGHT / LENGTH DISTRIBUTION
    # --------------------------------------------------------

    def generate_branch_heights(count, min_height, max_height, min_spacing):
        # Rejection-sample height fractions so branches respect
        # branch_min_spacing instead of being placed fully independently
        # (which tends to cluster). If the requested count can't fit at
        # this spacing, fewer are returned.
        heights = []
        max_attempts = count * 200

        for _ in range(max_attempts):
            if len(heights) >= count:
                break

            candidate = rng_branches.uniform(min_height, max_height)

            if all(abs(candidate - h) >= min_spacing for h in heights):
                heights.append(candidate)

        return sorted(heights)

    def pick_branch_length():
        # Each branch is independently "long" with probability
        # branch_long_ratio, otherwise "short". Long branches are sampled
        # from the upper half of [branch_length_min, branch_length_max],
        # short from the lower half, so the mix between short and long
        # branches is controllable instead of always averaging out to the
        # same middling length.
        midpoint = (branch_length_min + branch_length_max) / 2

        if rng_branches.random() < branch_long_ratio:
            return rng_branches.uniform(midpoint, branch_length_max)

        return rng_branches.uniform(branch_length_min, midpoint)

    # --------------------------------------------------------
    # STRUCTURE GENERATOR (branches and roots)
    # --------------------------------------------------------

    def generate_structure(
        start,
        direction,
        length,
        radius,
        curvature,
        segments,
        allow_split,
        struct_split_chance,
        struct_split_min,
        struct_split_max,
        struct_secondary_count_min,
        struct_secondary_count_max,
        struct_secondary_length_min,
        struct_secondary_length_max,
        struct_secondary_thickness,
        is_root=False,
    ):
        # This structure's own stream - roots and branches (main or
        # secondary) never draw from each other's random sequence, no
        # matter how deep the recursion goes. Leaves always draw from
        # rng_leaves instead, further down, regardless of which of these
        # this call is.
        rng = rng_roots if is_root else rng_branches

        start = Vector(start)
        direction = Vector(direction).normalized()

        points = [start.copy()]
        radii = [radius]

        current = start.copy()
        current_direction = direction.copy()

        # Fixed axis this branch spirals around. Using the structure's own
        # starting direction means increasing curvature winds the tip
        # around its own growth axis rather than just adding more noise.
        spiral_axis = current_direction.copy()

        # A single random horizontal direction this root leans into during
        # its upward phase, so the sideways bend reads as one deliberate
        # lean instead of random per-step jitter that averages back to zero.
        kick_angle = rng.uniform(0, math.pi * 2)
        kick_direction = Vector((math.cos(kick_angle), math.sin(kick_angle), 0))

        for i in range(1, segments + 1):
            t = i / segments

            if is_root:

                if t < root_upward_phase:
                    # Early growth: arc opposite the eventual downward pull
                    # (a gentle upward/outward flare) instead of diving
                    # down immediately. The lateral kick fades out over
                    # this same phase, handing off to the downward dive.
                    phase_t = t / root_upward_phase
                    downward_force = -(1.0 - phase_t) * curvature * 0.6
                    lateral_strength = (1.0 - phase_t) * curvature * 0.6
                else:
                    # Remaining growth: transition into the normal downward curve.
                    phase_t = (t - root_upward_phase) / (1.0 - root_upward_phase)
                    downward_force = phase_t * curvature * 1.2
                    lateral_strength = 0.0

                random_bend = (
                    Vector((
                        rng.uniform(-0.5, 0.5) * root_lateral_curvature,
                        rng.uniform(-0.5, 0.5) * root_lateral_curvature,
                        -downward_force,
                    ))
                    + kick_direction * lateral_strength
                )

                # Blend the new bend in gradually rather than snapping the
                # direction straight to it, so the curve stays smooth from
                # one segment to the next.
                current_direction += random_bend * 0.20

            else:
                # Continuous rotation around the branch's own axis.
                # Curvature values above 1 rotate it further per segment
                # than a gentle bend, letting it coil into a visible spiral.
                spiral_step_angle = curvature * (math.pi / segments) * 1.5
                current_direction.rotate(Quaternion(spiral_axis, spiral_step_angle))

                random_bend = Vector((
                    rng.uniform(-1, 1),
                    rng.uniform(-1, 1),
                    rng.uniform(-0.15, 0.35),
                ))

                current_direction += random_bend * 0.20

            current_direction = current_direction.normalized()

            if not is_root:
                # Keep branches trending at least slightly upward - without
                # this floor, the random bend can tip a branch fully level
                # or downward, reading as broken/drooping rather than a
                # natural curve.
                if current_direction.z < 0.03:
                    current_direction.z = 0.03
                    current_direction.normalize()

            current += current_direction * (length / segments)
            points.append(current.copy())

            # Taper down to 12% of the base radius by the tip.
            point_radius = radius * (1.0 - t * 0.88)
            radii.append(point_radius)

        # ----------------------------------------------------
        # CREATE CURRENT STRUCTURE
        # ----------------------------------------------------

        obj = create_curved_mesh(
            points,
            radius,
            radii[-1],
            rng,
            sides=6,
            material=trunk_material if is_root else branch_material,
            name="Root" if is_root else "Branch",
        )

        # ----------------------------------------------------
        # LEAVES
        # ----------------------------------------------------

        if not is_root and generate_leaves and foliage_type == 'ICOSPHERE':
            cluster_count = rng_leaves.randint(leaves_per_branch_min, leaves_per_branch_max)

            for i in range(cluster_count):
                index = rng_leaves.randint(max(1, len(points) // 2), len(points) - 1)

                offset = Vector((
                    rng_leaves.uniform(-leaf_spread, leaf_spread),
                    rng_leaves.uniform(-leaf_spread, leaf_spread),
                    rng_leaves.uniform(-leaf_spread * 0.5, leaf_spread),
                ))

                cluster_scale = rng_leaves.uniform(leaf_scale_min, leaf_scale_max)

                # Clamp the offset so a large Spread can never push a
                # cluster far enough to lose all contact with the branch it
                # grows from - otherwise it ends up floating disconnected
                # from the merged leaf mesh instead of overlapping it.
                max_offset = radii[index] + cluster_scale * min(leaf_width, leaf_depth, leaf_height) * 0.9
                if offset.length > max_offset:
                    offset = offset * (max_offset / offset.length)

                create_leaf_cluster(points[index] + offset, cluster_scale)

        # ----------------------------------------------------
        # CHILDREN
        # ----------------------------------------------------

        child_objects = []

        if allow_split and rng.random() < struct_split_chance:
            split_t = rng.uniform(struct_split_min, struct_split_max)
            split_index = int(split_t * (len(points) - 1))
            split_index = max(1, min(split_index, len(points) - 2))

            split_point = points[split_index]

            # Use the parent's LOCAL radius at the split point, not its base radius.
            parent_radius = radii[split_index]
            child_radius = parent_radius * struct_secondary_thickness

            count = rng.randint(struct_secondary_count_min, struct_secondary_count_max)

            parent_direction = (points[split_index] - points[split_index - 1]).normalized()

            # Local frame around the parent direction, used to spread
            # siblings evenly around it instead of picking each one fully
            # independently (which can land two of them at nearly the same
            # angle and have them grow alongside each other into what
            # looks like one branch).
            reference = Vector((0, 0, 1))
            if abs(parent_direction.dot(reference)) > 0.9:
                reference = Vector((1, 0, 0))
            frame_x = parent_direction.cross(reference).normalized()
            frame_y = parent_direction.cross(frame_x).normalized()

            angle_step = (math.pi * 2) / count

            for child_index in range(count):
                spread_angle = (
                    angle_step * child_index
                    + rng.uniform(-angle_step * 0.3, angle_step * 0.3)
                )

                lateral = frame_x * math.cos(spread_angle) + frame_y * math.sin(spread_angle)

                # Secondary roots can angle either up or down off their
                # parent; secondary branches always skew upward (matching
                # the upward-trend clamp applied to every branch's growth).
                vertical = rng.uniform(-0.2, 0.5) if is_root else rng.uniform(0.15, 0.65)

                side = lateral + Vector((0, 0, vertical))

                # Blend the parent's own direction with the sideways/vertical
                # offset above, so each secondary grows off at an angle
                # rather than either continuing dead straight or splitting
                # off perpendicular to its parent.
                split_direction = (
                    parent_direction + side * rng.uniform(0.45, 0.80)
                ).normalized()

                secondary_length = length * rng.uniform(
                    struct_secondary_length_min, struct_secondary_length_max
                )

                child = generate_structure(
                    split_point,
                    split_direction,
                    secondary_length,
                    child_radius,
                    curvature,
                    segments,
                    False,
                    0, 0, 0, 0, 0, 0, 0,
                    struct_secondary_thickness,
                    is_root,
                )

                if child:
                    trim_secondary_into_parent = (
                        merge_secondary_roots_into_main if is_root else merge_secondary_into_main
                    )

                    if trim_secondary_into_parent:
                        # Merge (Boolean Difference): trim away the part of
                        # this secondary structure that's buried inside its
                        # parent, so the join below doesn't leave any hidden
                        # overlapping geometry behind. A main structure and
                        # all its secondaries always end up joined into one
                        # object either way (see the join below); this only
                        # decides whether the overlap is trimmed away first.
                        boolean = child.modifiers.new(name="TrimToParent", type='BOOLEAN')
                        boolean.operation = 'DIFFERENCE'
                        boolean.object = obj
                        boolean.solver = 'FLOAT'

                        context.view_layer.objects.active = child
                        bpy.ops.object.modifier_apply(modifier=boolean.name)

                    child_objects.append(child)

        # ----------------------------------------------------
        # JOIN THIS STRUCTURE WITH ITS CHILDREN
        # ----------------------------------------------------

        if child_objects:
            # Unconditional plain join: every secondary that split off this
            # structure ends up as one object with it. Any overlap was
            # already dealt with above (Boolean Difference trim per child,
            # if that toggle was on), so there's nothing left for this join
            # itself to clean up.
            objects_to_join = [obj] + child_objects

            bpy.ops.object.select_all(action='DESELECT')

            for child_obj in objects_to_join:
                if child_obj:
                    child_obj.select_set(True)

            context.view_layer.objects.active = obj
            bpy.ops.object.join()
            obj = context.active_object

            # Cleanup only this branch family, not the whole tree, so each
            # recursive call stays cheap. Decimation is deliberately not
            # done here: it only ever applies to the trunk or to merged
            # leaves (see Mesh Simplification settings), not per branch.
            cleanup_mesh(obj)

        return obj

    # --------------------------------------------------------
    # MAIN BRANCHES
    # --------------------------------------------------------

    main_branch_objects = []

    branch_heights = generate_branch_heights(
        main_branch_count,
        branch_min_height,
        branch_max_height,
        branch_min_spacing,
    )

    # Decide up front which heights also get an extra, same-height branch
    # (a whorl), so the final branch count - needed below to lay out Angle
    # Order's evenly-spaced slots - already includes them. Duplicate height
    # values are intentional: each entry still becomes its own independent
    # branch with its own angle, tilt, length and radius.
    branch_plan = []
    for height_factor in branch_heights:
        branch_plan.append(height_factor)
        if rng_branches.random() < branch_same_height_chance:
            branch_plan.append(height_factor)

    total_branch_count = len(branch_plan)

    # Single random starting rotation for the whole evenly-spaced ring of
    # branches, so Angle Order == 1 doesn't always put the first slot at
    # the same absolute world angle across different trees.
    branch_base_angle = rng_branches.uniform(0, math.pi * 2)

    # The slots themselves stay perfectly even around the full circle, but
    # which slot lands on which branch is shuffled rather than handed out
    # in height order - otherwise, moving up the trunk, the angle would
    # always spiral steadily in one direction instead of scattering
    # randomly around the trunk.
    angle_slots = [
        branch_base_angle + (math.pi * 2 * slot / total_branch_count)
        for slot in range(total_branch_count)
    ]
    rng_branches.shuffle(angle_slots)

    for branch_index, height_factor in enumerate(branch_plan):
        pending_leaf_clusters.clear()

        index = int(height_factor * trunk_segments)
        index = max(1, min(index, len(trunk_points) - 2))

        start = trunk_points[index]

        # Blends between a fully random angle (Angle Order 0) and this
        # branch's shuffled, evenly-spaced slot around the trunk's 360
        # degrees (Angle Order 1). max_jitter shrinks from a full circle
        # (any angle is equally likely, since the slot angle plus a
        # uniform +/-180 degree offset is itself uniform around the
        # circle) down to none at all.
        max_jitter = math.pi * (1.0 - branch_angle_order)
        angle = angle_slots[branch_index] + rng_branches.uniform(-max_jitter, max_jitter)

        # Angled mostly outward with a moderate upward tilt, so branches
        # read as growing away from the trunk rather than straight up
        # alongside it.
        horizontal = rng_branches.uniform(0.65, 1.0)
        vertical = rng_branches.uniform(0.15, 0.60)

        direction = Vector((
            math.cos(angle) * horizontal,
            math.sin(angle) * horizontal,
            vertical,
        )).normalized()

        length = pick_branch_length()

        t = start.z / tree_height

        # Branches attached higher up (where the trunk has already tapered)
        # come out proportionally thinner too, on top of the trunk's own
        # taper at that height.
        branch_radius = (
            trunk_radius
            * (1.0 - t * 0.75)
            * branch_thickness
            * rng_branches.uniform(1.0 - branch_thickness_random, 1.0 + branch_thickness_random)
        )

        branch = generate_structure(
            start,
            direction,
            length,
            branch_radius,
            branch_curvature,
            branch_segments,
            True,
            split_chance,
            split_min,
            split_max,
            secondary_count_min,
            secondary_count_max,
            secondary_length_min,
            secondary_length_max,
            secondary_thickness,
            False,
        )

        if branch:
            main_branch_objects.append(branch)

        if merge_leaves_with_union:
            branch_leaves = merge_leaf_cluster_group(pending_leaf_clusters, f"BranchLeaves_{branch_index}")
            if branch_leaves:
                all_leaf_objects.append(branch_leaves)
        else:
            all_leaf_objects.extend(pending_leaf_clusters)

    # --------------------------------------------------------
    # JOIN BRANCHES WITH TRUNK
    # --------------------------------------------------------

    main_branch_objects = [obj for obj in main_branch_objects if obj and obj.name in bpy.data.objects]

    if join_branches_with_trunk and main_branch_objects:
        bpy.ops.object.select_all(action='DESELECT')

        trunk.select_set(True)

        for branch in main_branch_objects:
            branch.select_set(True)

        context.view_layer.objects.active = trunk

        bpy.ops.object.join()

        trunk = context.active_object

        cleanup_mesh(trunk)

    # --------------------------------------------------------
    # TOP CANOPY
    # --------------------------------------------------------

    if generate_leaves and foliage_type == 'ICOSPHERE':
        pending_leaf_clusters.clear()

        top = trunk_points[-2]

        # Scatter clusters in a rough dome above the trunk's top ring so the
        # canopy has its own fill, independent of the per-branch leaves.
        for i in range(20):
            angle = rng_leaves.uniform(0, math.pi * 2)
            radius = rng_leaves.uniform(0.3, 1.1)

            position = top + Vector((
                math.cos(angle) * radius,
                math.sin(angle) * radius,
                rng_leaves.uniform(0.1, 1.2),
            ))

            create_leaf_cluster(position, rng_leaves.uniform(leaf_scale_min, leaf_scale_max))

        if merge_leaves_with_union:
            canopy_leaves = merge_leaf_cluster_group(pending_leaf_clusters, "CanopyLeaves")
            if canopy_leaves:
                all_leaf_objects.append(canopy_leaves)
        else:
            all_leaf_objects.extend(pending_leaf_clusters)
    elif generate_leaves and foliage_type == 'PINE':
        # A tiered canopy built directly along the trunk axis, instead of
        # per-branch clusters - see PINE CANOPY above. Tiers stay as
        # separate objects here so JOIN ALL LEAVES INTO ONE MESH further
        # down is what decides whether they end up joined.
        all_leaf_objects.extend(create_pine_canopy())

    # --------------------------------------------------------
    # JOIN ALL LEAVES INTO ONE MESH
    # --------------------------------------------------------

    # A plain join, not a boolean union: different branches' leaf meshes
    # generally don't overlap (unlike the individual leaf clusters within
    # one branch, already resolved above), so there's no hidden geometry to
    # remove here, just objects to consolidate.
    if join_all_leaves:
        all_leaf_objects = [obj for obj in all_leaf_objects if obj and obj.name in bpy.data.objects]

        if all_leaf_objects:
            bpy.ops.object.select_all(action='DESELECT')

            leaves = all_leaf_objects[0]

            for obj in all_leaf_objects:
                obj.select_set(True)

            context.view_layer.objects.active = leaves

            bpy.ops.object.join()

            leaves = context.active_object
            leaves.name = "TreeLeaves"

            cleanup_mesh(leaves)

    # --------------------------------------------------------
    # ROOTS
    # --------------------------------------------------------

    root_count = rng_roots.randint(root_count_min, root_count_max)
    root_objects = []

    for i in range(root_count):
        # Evenly spaced around the trunk, with a bit of jitter so it doesn't
        # read as a perfectly regular ring of roots.
        angle = (math.pi * 2 * i / root_count) + rng_roots.uniform(-0.35, 0.35)

        # The trunk's own outward surface normal at this angle, derived
        # from its linear taper (see create_trunk's radius formula): a
        # cone that narrows going up has a normal that leans away from
        # purely horizontal by the taper's slope, not a flat radial
        # direction. The random term adds the same small per-root variation
        # the old flat direction had.
        taper_slope = 0.82 * trunk_radius / tree_height
        direction = Vector((
            math.cos(angle),
            math.sin(angle),
            taper_slope + rng_roots.uniform(-0.02, 0.02),
        )).normalized()

        root_radius = (
            trunk_radius
            * root_thickness
            * rng_roots.uniform(1.0 - root_thickness_random, 1.0 + root_thickness_random)
        )
        root_radius = max(root_radius_min, min(root_radius, root_radius_max))

        root_length = rng_roots.uniform(root_length_min, root_length_max)

        # How far from the trunk's central axis this root starts, as a
        # fraction of the trunk's base radius (0 = center, 1 = edge).
        start_offset = root_attach_distance * trunk_radius

        # Starting the root's center ring exactly at z=0 (the trunk's own
        # bottom cap) makes the ring's near half dip to z=-root_radius,
        # poking out below the trunk's bottom boundary. Raising the start
        # by one radius keeps the ring's lowest point at z=0 instead - this
        # stays a safe margin regardless of Attach Distance, since tilting
        # direction upward (above) can only ever shrink how far the ring
        # dips below its own center, never grow it.
        root = generate_structure(
            Vector((
                math.cos(angle) * start_offset,
                math.sin(angle) * start_offset,
                root_radius,
            )),
            direction,
            root_length,
            root_radius,
            root_curvature,
            root_segments,
            True,
            root_split_chance,
            0.35,
            0.70,
            root_secondary_count_min,
            root_secondary_count_max,
            root_secondary_length_min,
            root_secondary_length_max,
            root_secondary_thickness,
            True,
        )

        if root:
            root_objects.append(root)

    # --------------------------------------------------------
    # JOIN ROOTS WITH TRUNK
    # --------------------------------------------------------

    root_objects = [obj for obj in root_objects if obj and obj.name in bpy.data.objects]

    if merge_roots_into_trunk:
        # Merge (Boolean Difference): trim away each root's overlap with
        # the trunk before the unconditional join below, so no hidden
        # overlapping geometry survives into the joined mesh. Unlike main
        # branches (which stay separate from the trunk - see MAIN
        # BRANCHES), roots always end up joined into the trunk as a single
        # object; this toggle only decides whether the overlap is trimmed
        # away first.
        for root in root_objects:
            boolean = root.modifiers.new(name="TrimToTrunk", type='BOOLEAN')
            boolean.operation = 'DIFFERENCE'
            boolean.object = trunk
            boolean.solver = 'FLOAT'

            context.view_layer.objects.active = root
            bpy.ops.object.modifier_apply(modifier=boolean.name)

    if root_objects:
        bpy.ops.object.select_all(action='DESELECT')

        trunk.select_set(True)

        for root in root_objects:
            root.select_set(True)

        context.view_layer.objects.active = trunk

        bpy.ops.object.join()

        trunk = context.active_object
        trunk.name = "TreeWood"

        cleanup_mesh(trunk)

    # --------------------------------------------------------
    # DECIMATE TRUNK
    # --------------------------------------------------------

    # Applied once here, after roots have been joined in, rather than after
    # each join, so the trunk is never decimated more than once per
    # generation.
    if decimate_trunk:
        decimate_object(trunk, trunk_decimate_ratio)

    # --------------------------------------------------------
    # FINAL CLEANUP
    # --------------------------------------------------------

    # cleanup_mesh already sets use_smooth per-face and every join or merge
    # step above already ran it on its own result, so only objects that
    # were never combined into another object (e.g. standalone leaf
    # clusters) still need it.
    for obj in list(tree_collection.objects):
        if obj.type == 'MESH' and obj not in cleaned_objects:
            cleanup_mesh(obj)

    # --------------------------------------------------------
    # SELECT TREE
    # --------------------------------------------------------

    bpy.ops.object.select_all(action='DESELECT')

    for obj in tree_collection.objects:
        obj.select_set(True)

    if tree_collection.objects:
        context.view_layer.objects.active = tree_collection.objects[0]

    print("====================================")
    print("LOW POLY TREE GENERATED")
    print("Collection:", tree_collection_name)
    print("Seed:", tree_s.seed)
    print("Branches:", total_branch_count, "/", main_branch_count)
    print("Roots:", root_count)
    print("====================================")

    return total_branch_count, root_count


# ============================================================
# OPERATOR
# ============================================================

class TREEGEN_OT_Generate(Operator):
    bl_idname = "treegen.generate"
    bl_label = "Generate Tree"
    bl_description = "Generate a new procedural tree using the settings above"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            branch_count, root_count = generate_tree(context)
        except Exception as exc:
            self.report({'ERROR'}, f"Tree generation failed: {exc}")
            return {'CANCELLED'}

        self.report({'INFO'}, f"Generated tree: {branch_count} branches, {root_count} roots")
        return {'FINISHED'}


# ============================================================
# PANEL
# ============================================================

class TREEGEN_PT_Panel(Panel):
    bl_idname = "TREEGEN_PT_panel"
    bl_label = "Tree Generator"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tree Gen"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.tree_generator_settings

        header, body = layout.panel("treegen_panel_tree", default_closed=False)
        header.label(text="Tree")
        if body:
            tree_s = settings.tree
            body.prop(tree_s, "seed")
            body.prop(tree_s, "collection_name")
            body.prop(tree_s, "tree_height")
            body.prop(tree_s, "trunk_radius")
            body.prop(tree_s, "trunk_segments")
            body.prop(tree_s, "trunk_sides")
            body.prop(tree_s, "trunk_bend", slider=True)

        header, body = layout.panel("treegen_panel_branches", default_closed=False)
        header.label(text="Main Branches")
        if body:
            branch_s = settings.branches
            body.prop(branch_s, "main_branch_count")
            body.prop(branch_s, "branch_min_height", slider=True)
            body.prop(branch_s, "branch_max_height", slider=True)
            body.prop(branch_s, "branch_min_spacing", slider=True)
            body.prop(branch_s, "branch_angle_order", slider=True)
            body.prop(branch_s, "branch_same_height_chance", slider=True)
            body.prop(branch_s, "branch_length_min")
            body.prop(branch_s, "branch_length_max")
            body.prop(branch_s, "branch_long_ratio", slider=True)
            body.prop(branch_s, "branch_thickness")
            body.prop(branch_s, "branch_thickness_random", slider=True)
            body.prop(branch_s, "branch_curvature")
            body.prop(branch_s, "branch_segments")
            body.separator()
            body.prop(branch_s, "join_branches_with_trunk")

        header, body = layout.panel("treegen_panel_secondary", default_closed=True)
        header.label(text="Branch Secondary")
        if body:
            secondary_s = settings.secondary
            body.prop(secondary_s, "split_chance", slider=True)
            body.prop(secondary_s, "split_min", slider=True)
            body.prop(secondary_s, "split_max", slider=True)
            body.prop(secondary_s, "secondary_count_min")
            body.prop(secondary_s, "secondary_count_max")
            body.prop(secondary_s, "secondary_length_min")
            body.prop(secondary_s, "secondary_length_max")
            body.prop(secondary_s, "secondary_thickness")
            body.separator()
            body.prop(secondary_s, "merge_secondary_into_main")

        header, body = layout.panel("treegen_panel_roots", default_closed=True)
        header.label(text="Roots")
        if body:
            root_s = settings.roots
            body.prop(root_s, "root_count_min")
            body.prop(root_s, "root_count_max")
            body.prop(root_s, "root_attach_distance", slider=True)
            body.prop(root_s, "root_thickness")
            body.prop(root_s, "root_thickness_random", slider=True)
            body.prop(root_s, "root_radius_min")
            body.prop(root_s, "root_radius_max")
            body.prop(root_s, "root_length_min")
            body.prop(root_s, "root_length_max")
            body.prop(root_s, "root_curvature")
            body.prop(root_s, "root_lateral_curvature")
            body.prop(root_s, "root_segments")
            body.prop(root_s, "root_upward_phase", slider=True)
            body.prop(root_s, "root_split_chance", slider=True)
            body.prop(root_s, "root_secondary_count_min")
            body.prop(root_s, "root_secondary_count_max")
            body.prop(root_s, "root_secondary_length_min")
            body.prop(root_s, "root_secondary_length_max")
            body.prop(root_s, "root_secondary_thickness")
            body.separator()
            body.prop(root_s, "merge_roots_into_trunk")
            body.prop(root_s, "merge_secondary_roots_into_main")

        header, body = layout.panel("treegen_panel_mesh", default_closed=True)
        header.label(text="Mesh Simplification")
        if body:
            mesh_s = settings.mesh

            body.prop(mesh_s, "decimate_trunk")
            sub = body.column()
            sub.enabled = mesh_s.decimate_trunk
            sub.prop(mesh_s, "trunk_decimate_ratio", slider=True)

            body.separator()

            body.prop(mesh_s, "decimate_leaves")
            sub = body.column()
            sub.enabled = mesh_s.decimate_leaves
            sub.prop(mesh_s, "leaves_decimate_ratio", slider=True)

        header, body = layout.panel("treegen_panel_leaves", default_closed=False)
        header.label(text="Leaves")
        if body:
            leaf_s = settings.leaves
            body.prop(leaf_s, "generate_leaves")

            sub = body.column()
            sub.enabled = leaf_s.generate_leaves
            sub.prop(leaf_s, "foliage_type")
            sub.prop(leaf_s, "join_all_leaves")

            if leaf_s.foliage_type == 'ICOSPHERE':
                sub.prop(leaf_s, "merge_leaves_with_union")
                sub.prop(leaf_s, "leaves_per_branch_min")
                sub.prop(leaf_s, "leaves_per_branch_max")
                sub.prop(leaf_s, "leaf_scale_min")
                sub.prop(leaf_s, "leaf_scale_max")
                sub.prop(leaf_s, "leaf_spread")
                sub.prop(leaf_s, "leaf_width")
                sub.prop(leaf_s, "leaf_depth")
                sub.prop(leaf_s, "leaf_height")
                sub.prop(leaf_s, "bottom_distortion", slider=True)
            else:
                sub.prop(leaf_s, "pine_tier_count")
                sub.prop(leaf_s, "pine_canopy_start", slider=True)
                sub.prop(leaf_s, "pine_base_radius")
                sub.prop(leaf_s, "pine_tier_overlap", slider=True)
                sub.prop(leaf_s, "pine_vertical_width")
                sub.prop(leaf_s, "pine_taper")
                sub.prop(leaf_s, "pine_core_width", slider=True)
                sub.prop(leaf_s, "pine_prickliness", slider=True)
                sub.prop(leaf_s, "pine_spike_tilt", slider=True)
                sub.prop(leaf_s, "pine_spike_horizontal_deform")
                sub.prop(leaf_s, "pine_jitter", slider=True)
                sub.prop(leaf_s, "pine_sides")

        layout.separator()

        row = layout.row()
        row.alignment = 'CENTER'
        row.scale_y = 1.6
        row.operator("treegen.generate", text="Generate", icon='FILE_REFRESH')


# ============================================================
# REGISTRATION
# ============================================================

classes = (
    TREEGEN_PG_Tree,
    TREEGEN_PG_Branches,
    TREEGEN_PG_Secondary,
    TREEGEN_PG_Roots,
    TREEGEN_PG_Mesh,
    TREEGEN_PG_Leaves,
    TREEGEN_PG_Settings,
    TREEGEN_OT_Generate,
    TREEGEN_PT_Panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.tree_generator_settings = PointerProperty(type=TREEGEN_PG_Settings)


def unregister():
    del bpy.types.Scene.tree_generator_settings

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
