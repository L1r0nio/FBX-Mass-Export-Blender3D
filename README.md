# FBX Mass Export for Blender

A lightweight Blender addon for batch exporting meshes as individual FBX files
with smart grouping, per-group anchors, and a live preview — all inside the
native FBX export dialog.

## Features

- **Per-mesh export** — each mesh (or group) exports as a separate `.fbx`
  file, named after the mesh or the group's name anchor.
- **Native UI integration** — lives inside Blender's standard FBX export
  dialog (`File > Export > FBX`), so your usual export settings are reused.
- **Grouping modes**
  - **By Name** — objects whose names differ only in one structural word
    (`Left` / `Right`) or by a numeric suffix (`_1` / `_1_1` / `_1_2`) are
    combined into a single FBX. Grouping is transitive.
    A configurable **Strip Words** list removes variant tokens (e.g.
    `Body`, `Windows`, `Inside`, `Outside`) from both comparison and
    filename generation, so `..._Body_Brown` and `..._Windows_Brown`
    correctly merge into `..._Brown`.
  - **By Parent** — meshes that share a mesh parent are combined into one
    FBX named after the parent.
  - **By Proximity** — meshes that are close in 3D space *and* share
    enough name tokens are combined into one FBX. Two meshes are grouped
    when:
    - their names share at least **Common Words** tokens (after stripping
      ignored words), **and**
    - their origins are within **Threshold** meters **or** their world-space
      bounding boxes overlap.
    This catches modular pieces that touch physically but whose names
    differ in a non-trivial way (e.g. wall segments with different
    connector details). Proximity mode takes precedence over Name and
    Parent grouping.
- **Collections as subfolders** — optionally export each mesh/group into a
  subfolder named after its collection.
- **Per-group anchors**
  - **Origin anchor** (radio button) — pick which object's pivot is used
    by *Move to Origin*.
  - **Name anchor** (font icon) — pick which object's name becomes the
    final FBX filename.
  - Both default to the group's shortest name (the numeric base) and can
    be overridden by clicking the icon.
- **Solo mode** (star icon) — take a mesh out of grouping and export it
  as a standalone FBX. Solo objects are ignored by every grouping mode.
- **Exclusion system**
  - Toggle individual meshes with the checkbox.
  - Toggle a whole group from the group header checkbox.
  - Excluded meshes remain visible in the preview (greyed out) so you can
    re-enable them with one click.
- **Move to Origin** — temporarily move each group to the world origin
  before export so the FBX pivot sits at `(0, 0, 0)`. Objects are restored
  to their original positions afterwards. Supports three anchor modes:
  - `Object Origin` — the origin anchor's pivot goes to `(0, 0, 0)`.
  - `Bounding Box Center` — the group's combined bounding-box center.
  - `Lowest Origin` — the origin of the object with the lowest Z.
- **Live preview** — always see exactly how many files will be produced
  and which meshes go into which FBX.
- **Post-export action** — open the output folder automatically when done.

## Installation

1. Download `FBX_MASS_EXPORT.py`.
2. In Blender: `Edit > Preferences > Add-ons > Install from disk` and pick
   the file.
3. Enable **FBX Mass Export** in the add-on list.

## Usage

1. Open the standard FBX export dialog: `File > Export > FBX`.
2. Configure the export settings as usual.
3. Expand the **Batch Export** panel in the sidebar of the file browser:
   - Toggle **By Collection**, **Group by Parent**, **Group by Name**, or
     **Group by Proximity**.
   - In **Proximity** mode, adjust **Threshold** and **Common Words**.
     Both appear inline under the toggle.
   - In **Name** or **Proximity** mode, edit the **Strip Words** list
     (comma-separated, default `Body, Windows, Inside, Outside`).
   - Optionally enable **Move to Origin** and pick an anchor mode.
   - Use the preview list to:
     - exclude a whole group (checkbox in the group header),
     - exclude a single mesh (checkbox on its row),
     - set the **origin anchor** (radio button) and **name anchor**
       (font icon) for each group,
     - mark a mesh as **solo** (star) to export it outside of any group.
   - Click **Export All Meshes**.

### Reading the preview

Inside a group each row shows, from left to right:

| Icon               | Meaning                                                       |
| ------------------ | ------------------------------------------------------------- |
| ☑ / ☐              | Include / exclude this mesh                                   |
| ☆ / ★              | Solo — export outside the group                               |
| ◉ / ○              | Origin anchor (used by *Move to Origin*)                      |
| 𝑭 (font)          | Name anchor (used as the FBX filename)                        |

The header row of a group has its own checkbox that toggles every mesh in
the group at once.

## Requirements

- Blender 4.3 or newer.
- No external dependencies.

## Version

`0.8.1`
