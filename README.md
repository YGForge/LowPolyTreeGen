Requirements
------------
Blender 5.0.1 or newer.


Installation
------------
1. In Blender, go to Edit > Preferences > Get Extensions (or Add-ons on older layouts) and use "Install from Disk".
2. Point it at this folder (or a zip of it) and enable "Generate Tree Plugin".
3. A new "Tree Gen" tab appears in the 3D Viewport sidebar (press N to open the sidebar if it's hidden).


Usage
-----
1. Open the "Tree Gen" tab in the 3D Viewport sidebar.
2. Adjust settings in the panel sections described below.
3. Click "Generate" at the bottom of the panel.

Each click builds a brand-new tree from scratch inside a collection named after the "Collection" field (default: GeneratedTree). Re-running Generate creates another tree rather than modifying the previous one - delete the old collection if you don't want to keep it around.

Change "Seed" to get a different random variation while keeping every other setting the same.

<img width="754" height="804" alt="Screenshot1" src="https://github.com/user-attachments/assets/5f22f204-c7ab-445f-8726-e76fedc8f791" />
<img width="540" height="664" alt="Screenshot2" src="https://github.com/user-attachments/assets/caaf48c5-e908-4ce1-94fd-e6c047644ce4" />
<img width="660" height="838" alt="Screenshot3" src="https://github.com/user-attachments/assets/eed40dd2-313e-4657-bd76-819282f1d772" />


Panel Sections
---------------

**Tree**

Core trunk shape: seed, target collection name, overall tree height, trunk radius, trunk ring/segment count, trunk side count (roundness), and trunk bend (how far the trunk leans toward horizontal by the top).

**Main Branches**

How many branches grow off the trunk, the height range along the trunk they can start in, minimum spacing between them, how evenly they're distributed around the trunk (Angle Order), the chance of a whorl of branches at the same height, branch length range and length mix, thickness, curvature, segment count, and whether branches get joined into the trunk as one object.

**Branch Secondary**

Secondary (twig-level) splits off each main branch: chance of a split occurring, the position range along the branch where splits can happen, how many secondaries spawn per split, their length (as a fraction of the parent branch) and thickness, and whether each secondary is Boolean-trimmed into its parent before joining.

**Roots**

A below-ground root system growing from the trunk base: count, how far from the trunk axis roots attach, thickness, radius clamps, length, vertical and lateral curvature, segment count, upward phase (initial arc before diving down), secondary root splits (same idea as branch secondaries), and whether roots and their secondaries are Boolean-trimmed before joining into the trunk.

**Mesh Simplification**

Optional Decimate passes for the trunk (and roots, if merged into it) and for the merged leaf meshes. Off by default to keep generation fast; enable and set a ratio to reduce poly count.

**Leaves**

Toggle leaf generation on/off and pick a Foliage Type:

- Icosphere Clusters: the original look. Whether each branch's leaf clusters are merged via a Boolean union, whether all leaf geometry across the whole tree is joined into a single object, how many leaf clusters spawn per branch, their scale range, how far they can drift from their branch attach point (Spread), individual leaf cluster width/depth/height, and Bottom Distortion (how irregular and "dangling" the underside of each cluster looks).

- Pine Canopy: a single tapering stack of low-poly cone tiers built directly along the trunk's own (possibly bent) centerline, instead of clusters scattered on branches. Each tier is sized relative to the trunk's own tapered width at that height, and the topmost tier's base lands exactly on the trunk's tip.

  Parameters include:

  - Tier Count
  - Canopy Start: where the lowest tier starts up the trunk
  - Base Radius: how many times wider than the trunk the lowest tier flares out
  - Tier Overlap: how much each tier overlaps into the one below it
  - Vertical Width: an unbounded multiplier stretching every tier's vertical height
  - Taper: how quickly tiers narrow going up
  - Core Width: how wide each tier's solid core is, from the trunk's own centerline up to the tier's full silhouette radius, where it reads as a smooth, needle-less cone
  - Prickliness: how far spikes protrude sideways beyond that core, pulled back flush once Core Width reaches 1
  - Spike Tilt: how far spikes tilt from outward towards straight down
  - Spike Horizontal Deform: random sideways deflection of each spike off perfectly radial
  - Jitter: per-vertex randomness
  - Sides: the number of spikes per tier


Notes
-----
- Generation is seeded: the same seed and settings always produce the same tree, so it's safe to tweak one slider at a time and compare.
- Boolean-heavy settings (Merge Secondary Into Main, Merge Roots Into Trunk, Merge Leaves With Union) look cleaner but are slower to generate on complex trees. Disable them for faster iteration, then turn them back on for a final pass.
- If generation fails, check the Blender status bar / Info log for the reported error - the operator reports failures instead of leaving a half-built tree behind.


License
-------
MIT
