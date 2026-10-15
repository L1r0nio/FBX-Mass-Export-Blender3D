bl_info = {
    "name": "FBX Mass Export mesh",
    "author": "L1ra",
    "version": (0, 5, 5),
    "blender": (4, 3, 2),
    "location": "File > Export > FBX > Batch Export",
    "description": "Adds batch export to the native FBX export dialog",
    "category": "Import-Export",
}


import bpy
import os
import re
import sys
import subprocess
from mathutils import Vector
from bpy.props import BoolProperty, EnumProperty
from bpy.types import Operator, Panel, PropertyGroup



def GetMeshCollectionName(obj):
    for col in obj.users_collection:
        if col.name != "Scene Collection":
            return col.name
    return None



def TokenizeName(name):
    return re.findall(r'[A-Za-z]+|[0-9]+', name)



def BuildGroupFingerprints(tokens):
    word_indices = [i for i, t in enumerate(tokens) if not t[0].isdigit()]
    fingerprints = []
    for skip_idx in word_indices:
        fp = []
        for i, t in enumerate(tokens):
            if i == skip_idx:
                fp.append("*")
            elif t[0].isdigit():
                fp.append(("N", t))
            else:
                fp.append(("W", t.lower()))
        fingerprints.append((tuple(fp), skip_idx))
    return fingerprints



def GroupByNameSimilarity(objects):
    if not objects:
        return {}

    token_map = {}
    for obj in objects:
        tokens = TokenizeName(obj.name)
        token_map[obj] = tokens

    fingerprint_buckets = {}

    for obj, tokens in token_map.items():
        fps = BuildGroupFingerprints(tokens)
        for fp, skip_idx in fps:
            if fp not in fingerprint_buckets:
                fingerprint_buckets[fp] = []
            fingerprint_buckets[fp].append((obj, skip_idx))

    used = set()
    raw_groups = []

    sorted_buckets = sorted(fingerprint_buckets.items(), key=lambda x: -len(x[1]))

    for fp, bucket_items in sorted_buckets:
        group_objs = []
        skip_positions = set()
        for obj, skip_idx in bucket_items:
            if id(obj) not in used:
                group_objs.append(obj)
                skip_positions.add(skip_idx)

        if len(group_objs) >= 2:
            for obj in group_objs:
                used.add(id(obj))
            raw_groups.append((group_objs, skip_positions))

    for obj in objects:
        if id(obj) not in used:
            used.add(id(obj))
            raw_groups.append(([obj], set()))

    result = {}
    for group_objs, skip_positions in raw_groups:
        names = [o.name for o in group_objs]
        fbx_name = DeriveFbxName(names, skip_positions, token_map)
        if fbx_name in result:
            fbx_name = fbx_name + "_" + str(len(result))
        result[fbx_name] = group_objs

    return result



def DeriveFbxName(names, skip_positions, token_map=None):
    if len(names) == 1:
        return names[0]

    if token_map:
        first_obj = None
        for obj, tokens in token_map.items():
            if obj.name == names[0]:
                first_obj = obj
                break
        if first_obj:
            tokens = token_map[first_obj]
            result_parts = []
            for i, t in enumerate(tokens):
                if i not in skip_positions:
                    result_parts.append(t)
            if result_parts:
                return "_".join(result_parts)

    return BuildFbxNameFallback(names)



def BuildFbxNameFallback(names):
    token_lists = [TokenizeName(n) for n in names]
    if not token_lists:
        return names[0] if names else "unnamed"

    min_len = min(len(tl) for tl in token_lists)

    prefix_tokens = []
    for i in range(min_len):
        vals = set(tl[i].lower() for tl in token_lists)
        if len(vals) == 1:
            prefix_tokens.append(token_lists[0][i])
        else:
            break

    suffix_tokens = []
    for i in range(1, min_len - len(prefix_tokens) + 1):
        vals = set(tl[-i].lower() for tl in token_lists)
        if len(vals) == 1:
            suffix_tokens.insert(0, token_lists[0][-i])
        else:
            break

    parts = []
    if prefix_tokens:
        parts.extend(prefix_tokens)
    if suffix_tokens:
        parts.extend(suffix_tokens)

    return "_".join(parts) if parts else names[0]



def CollectExportGroups(context, props, useSelection=False):
    if useSelection:
        pool = [o for o in context.selected_objects if o.type == "MESH"]
    else:
        pool = [o for o in context.scene.objects if o.type == "MESH"]

    pool = [o for o in pool if not o.fbxBatchExclude]

    groups = []

    if props.groupByName:
        name_groups = GroupByNameSimilarity(pool)
        for fbx_name, objs in name_groups.items():
            col_name = GetMeshCollectionName(objs[0]) if props.useCollectionFolders else None
            key_obj = objs[0]
            groups.append((fbx_name, col_name, objs, key_obj))

    elif props.groupByParent:
        parent_map = {}
        standalone = []
        for obj in pool:
            if obj.parent and obj.parent.type == "MESH":
                if obj.parent not in parent_map:
                    parent_map[obj.parent] = []
                parent_map[obj.parent].append(obj)
            else:
                standalone.append(obj)

        for parent, children in parent_map.items():
            if parent.fbxBatchExclude:
                continue
            col_name = GetMeshCollectionName(parent) if props.useCollectionFolders else None
            groups.append((parent.name, col_name, children, parent))

        for obj in standalone:
            col_name = GetMeshCollectionName(obj) if props.useCollectionFolders else None
            groups.append((obj.name, col_name, [obj], obj))
    else:
        for obj in pool:
            col_name = GetMeshCollectionName(obj) if props.useCollectionFolders else None
            groups.append((obj.name, col_name, [obj], obj))

    return groups



class FbxBatchProps(PropertyGroup):
    useCollectionFolders: BoolProperty(
        name="By Collection",
        description="Export each mesh into a subfolder named after its collection",
        default=False,
    )
    groupByParent: BoolProperty(
        name="Group by Parent",
        description="Meshes that share a mesh parent are combined into one FBX named after the parent",
        default=False,
    )
    groupByName: BoolProperty(
        name="Group by Name",
        description="Objects with similar names differing only in one structural word token are combined into one FBX",
        default=False,
    )
    openAfterExport: BoolProperty(
        name="Open Folder",
        description="Open the output folder after export finishes",
        default=True,
    )
    showPreview: BoolProperty(
        name="Preview",
        description="Show list of objects that will be exported",
        default=True,
    )
    moveToOrigin: BoolProperty(
        name="Move to Origin",
        description="Temporarily move each object or group to the world origin before export so that the FBX pivot sits at (0,0,0). Objects are returned to their original positions afterwards",
        default=False,
    )
    originAnchor: EnumProperty(
        name="Anchor",
        description="Which point is placed at the world origin during export",
        items=[
            ("ORIGIN", "Object Origin",
             "The key object's origin pivot point is moved to (0,0,0) and all group members follow"),
            ("BBOX_CENTER", "Bounding Box Center",
             "The center of the group's combined bounding box is moved to (0,0,0)"),
            ("LOWEST_ORIGIN", "Lowest Origin",
             "The origin of the object with the lowest Z among the group is moved to (0,0,0)"),
        ],
        default="ORIGIN",
    )



class MeshFbxBatchExporter:
    def __init__(self, context, fbxOp, props):
        self.context = context
        self.fbxOp = fbxOp
        self.props = props
        self.outputDir = os.path.dirname(bpy.path.abspath(fbxOp.filepath))
        self.exportedCount = 0
        self.failedNames = []


    def StashSelection(self):
        selected = {o for o in self.context.view_layer.objects if o.select_get()}
        active = self.context.view_layer.objects.active
        for obj in self.context.view_layer.objects:
            obj.select_set(False)
        return selected, active


    def RestoreSelection(self, state):
        selected, active = state
        for obj in self.context.view_layer.objects:
            obj.select_set(obj in selected)
        self.context.view_layer.objects.active = active


    def BuildSettings(self, filepath):
        op = self.fbxOp
        return {
            "filepath":                         filepath,
            "use_selection":                    True,
            "use_visible":                      op.use_visible,
            "use_active_collection":            op.use_active_collection,
            "global_scale":                     op.global_scale,
            "apply_unit_scale":                 op.apply_unit_scale,
            "apply_scale_options":              op.apply_scale_options,
            "use_space_transform":              op.use_space_transform,
            "bake_space_transform":             op.bake_space_transform,
            "object_types":                     {"MESH"},
            "use_mesh_modifiers":               op.use_mesh_modifiers,
            "use_mesh_modifiers_render":        op.use_mesh_modifiers_render,
            "mesh_smooth_type":                 op.mesh_smooth_type,
            "colors_type":                      op.colors_type,
            "prioritize_active_color":          op.prioritize_active_color,
            "use_subsurf":                      op.use_subsurf,
            "use_mesh_edges":                   op.use_mesh_edges,
            "use_tspace":                       op.use_tspace,
            "use_triangles":                    op.use_triangles,
            "use_custom_props":                 op.use_custom_props,
            "add_leaf_bones":                   op.add_leaf_bones,
            "primary_bone_axis":                op.primary_bone_axis,
            "secondary_bone_axis":              op.secondary_bone_axis,
            "use_armature_deform_only":         op.use_armature_deform_only,
            "armature_nodetype":                op.armature_nodetype,
            "bake_anim":                        op.bake_anim,
            "bake_anim_use_all_bones":          op.bake_anim_use_all_bones,
            "bake_anim_use_nla_strips":         op.bake_anim_use_nla_strips,
            "bake_anim_use_all_actions":        op.bake_anim_use_all_actions,
            "bake_anim_force_startend_keying":  op.bake_anim_force_startend_keying,
            "bake_anim_step":                   op.bake_anim_step,
            "bake_anim_simplify_factor":        op.bake_anim_simplify_factor,
            "path_mode":                        op.path_mode,
            "embed_textures":                   op.embed_textures,
            "batch_mode":                       "OFF",
            "use_batch_own_dir":                op.use_batch_own_dir,
            "axis_forward":                     op.axis_forward,
            "axis_up":                          op.axis_up,
        }


    def ComputeAnchorObject(self, objects, key_obj):
        mode = self.props.originAnchor

        if mode == "ORIGIN":
            return key_obj

        elif mode == "LOWEST_ORIGIN":
            self.context.view_layer.update()
            all_objs = list(objects)
            if key_obj not in all_objs:
                all_objs.append(key_obj)
            lowest = min(all_objs, key=lambda o: o.matrix_world.translation.z)
            return lowest

        elif mode == "BBOX_CENTER":
            return None

        return key_obj


    def ComputeBBoxCenter(self, objects, key_obj):
        self.context.view_layer.update()
        all_objs = list(objects)
        if key_obj not in all_objs:
            all_objs.append(key_obj)
        mins = Vector((float("inf"), float("inf"), float("inf")))
        maxs = Vector((float("-inf"), float("-inf"), float("-inf")))
        for obj in all_objs:
            for corner in obj.bound_box:
                world_corner = obj.matrix_world @ Vector(corner)
                mins.x = min(mins.x, world_corner.x)
                mins.y = min(mins.y, world_corner.y)
                mins.z = min(mins.z, world_corner.z)
                maxs.x = max(maxs.x, world_corner.x)
                maxs.y = max(maxs.y, world_corner.y)
                maxs.z = max(maxs.z, world_corner.z)
        return (mins + maxs) / 2.0


    def MoveGroupToOrigin(self, objects, key_obj):
        """Move objects so the anchor ends up at world origin (0,0,0).
        Pure transform math — no operators, no 3D view context needed."""
        all_objs = list(objects)
        if key_obj not in all_objs:
            all_objs.append(key_obj)

        saved_locations = {}
        for obj in all_objs:
            saved_locations[obj] = obj.location.copy()

        self.context.view_layer.update()

        mode = self.props.originAnchor

        if mode == "BBOX_CENTER":
            center = self.ComputeBBoxCenter(objects, key_obj)
            offset = -center
        else:
            anchor_obj = self.ComputeAnchorObject(objects, key_obj)
            offset = Vector((0.0, 0.0, 0.0)) - anchor_obj.matrix_world.translation

        # Apply offset only to root objects within the group;
        # children will follow their parent automatically.
        for obj in all_objs:
            parent_in_group = obj.parent is not None and obj.parent in all_objs
            if parent_in_group:
                continue

            if obj.parent is not None:
                # Convert world-space offset into parent-local space
                parent_matrix = obj.parent.matrix_world
                try:
                    local_offset = parent_matrix.inverted().to_3x3() @ offset
                except ValueError:
                    local_offset = offset
            else:
                local_offset = offset

            obj.location = obj.location + local_offset

        self.context.view_layer.update()
        return saved_locations


    def RestoreAfterMove(self, saved):
        if saved is None:
            return
        for obj, loc in saved.items():
            obj.location = loc
        self.context.view_layer.update()


    def ExportGroup(self, name, col_name, objects, key_obj):
        for obj in self.context.view_layer.objects:
            obj.select_set(False)

        for obj in objects:
            obj.select_set(True)
        if objects:
            self.context.view_layer.objects.active = objects[0]

        saved_move = None
        if self.props.moveToOrigin:
            saved_move = self.MoveGroupToOrigin(objects, key_obj)

            for obj in self.context.view_layer.objects:
                obj.select_set(False)
            for obj in objects:
                obj.select_set(True)
            if objects:
                self.context.view_layer.objects.active = objects[0]

        folder = os.path.join(self.outputDir, col_name) if col_name else self.outputDir
        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, name + ".fbx")

        try:
            bpy.ops.export_scene.fbx(**self.BuildSettings(filepath))
            self.exportedCount += 1
            print(f"  ✓  {name}  →  {filepath}")
        except Exception as error:
            self.failedNames.append(name)
            print(f"  ✗  {name}  ERROR: {error}")
        finally:
            self.RestoreAfterMove(saved_move)
            for obj in objects:
                obj.select_set(False)


    def OpenFolder(self):
        if sys.platform == "win32":
            subprocess.Popen(["explorer", self.outputDir])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", self.outputDir])
        else:
            subprocess.Popen(["xdg-open", self.outputDir])


    def Run(self):
        groups = CollectExportGroups(self.context, self.props, self.fbxOp.use_selection)
        if not groups:
            return groups, False

        os.makedirs(self.outputDir, exist_ok=True)
        state = self.StashSelection()

        wm = self.context.window_manager
        wm.progress_begin(0, len(groups))
        for i, (name, col_name, objects, key_obj) in enumerate(groups):
            wm.progress_update(i)
            self.ExportGroup(name, col_name, objects, key_obj)
        wm.progress_end()

        self.RestoreSelection(state)

        if self.props.openAfterExport:
            self.OpenFolder()

        return groups, True



class FBXBATCH_OT_export(Operator):
    bl_idname = "fbxbatch.export"
    bl_label = "Export All Meshes"
    bl_description = "Export every mesh in the scene as a separate .fbx using current dialog settings"

    def execute(self, context):
        fbxOp = context.space_data.active_operator
        props = context.scene.fbxBatchProps
        exporter = MeshFbxBatchExporter(context, fbxOp, props)
        groups, hasTargets = exporter.Run()

        if not hasTargets:
            self.report({"WARNING"}, "No mesh objects found")
            return {"CANCELLED"}

        if exporter.failedNames:
            failed = ", ".join(exporter.failedNames)
            self.report({"WARNING"}, f"Exported {exporter.exportedCount}/{len(groups)}. Failed: {failed}")
        else:
            self.report({"INFO"}, f"Done — {exporter.exportedCount} file(s) saved to {exporter.outputDir}")

        return {"FINISHED"}



class FILE_PT_fbxBatch(Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Batch Export"
    bl_parent_id = "FILE_PT_operator"
    bl_options = {"DEFAULT_CLOSED"}
    bl_order = 100

    @classmethod
    def poll(cls, context):
        return (
            hasattr(context.space_data, "active_operator")
            and context.space_data.active_operator.bl_idname == "EXPORT_SCENE_OT_fbx"
        )


    def draw(self, context):
        layout = self.layout
        props = context.scene.fbxBatchProps
        fbxOp = context.space_data.active_operator
        groups = CollectExportGroups(context, props, fbxOp.use_selection)
        count = len(groups)

        box = layout.box()
        col = box.column(align=True)

        row = col.row(align=True)
        row.prop(props, "useCollectionFolders", icon="OUTLINER_COLLECTION")
        row.prop(props, "groupByParent", icon="OUTLINER_OB_EMPTY")

        row = col.row(align=True)
        row.prop(props, "groupByName", icon="SORTALPHA")
        row.prop(props, "openAfterExport", icon="FILE_FOLDER")

        row = col.row(align=True)
        row.prop(props, "showPreview", icon="HIDE_OFF" if props.showPreview else "HIDE_ON")

        col.separator(factor=0.5)
        row = col.row(align=True)
        row.prop(props, "moveToOrigin", icon="OBJECT_ORIGIN")
        sub = row.row(align=True)
        sub.active = props.moveToOrigin
        sub.prop(props, "originAnchor", text="")

        if props.showPreview:
            layout.separator(factor=0.3)
            box = layout.box()

            header = box.row()
            scope = "selected" if fbxOp.use_selection else "scene"
            header.label(
                text=f"{count} {'file' if count == 1 else 'files'}  ·  {scope}",
                icon="MESH_DATA",
            )

            if groups:
                preview_col = box.column(align=True)

                if props.groupByName:
                    for fbx_name, col_name, objs, key_obj in groups:
                        self.DrawNameGroupRow(preview_col, fbx_name, objs, props)
                elif props.groupByParent:
                    pool = (
                        [o for o in context.selected_objects if o.type == "MESH"]
                        if fbxOp.use_selection
                        else [o for o in context.scene.objects if o.type == "MESH"]
                    )
                    drawn_parents = set()
                    standalone = []
                    for obj in pool:
                        if obj.fbxBatchExclude:
                            continue
                        if obj.parent and obj.parent.type == "MESH":
                            if obj.parent not in drawn_parents:
                                drawn_parents.add(obj.parent)
                                children = [o for o in pool if o.parent == obj.parent and not o.fbxBatchExclude]
                                self.DrawGroupRow(preview_col, obj.parent.name, children, obj.parent, props)
                        else:
                            standalone.append(obj)
                    for obj in standalone:
                        self.DrawObjectRow(preview_col, obj, props)
                else:
                    for fbx_name, col_name, objs, key_obj in groups:
                        self.DrawObjectRow(preview_col, objs[0], props)
            else:
                row = box.row()
                row.alert = True
                label = "Nothing selected" if fbxOp.use_selection else "No mesh objects in scene"
                row.label(text=label, icon="ERROR")

        layout.separator(factor=0.5)

        row = layout.row()
        row.scale_y = 1.4
        row.enabled = count > 0
        row.operator(
            "fbxbatch.export",
            text=f"Export All Meshes  ({count})" if count else "No Meshes Found",
            icon="EXPORT",
        )


    def DrawObjectRow(self, col, obj, props):
        row = col.row(align=True)
        excluded = obj.fbxBatchExclude
        icon = "CHECKBOX_DEHLT" if excluded else "CHECKBOX_HLT"
        row.prop(obj, "fbxBatchExclude", text="", icon=icon, emboss=False, invert_checkbox=True)
        sub = row.row()
        sub.active = not excluded
        label = obj.name if len(obj.name) <= 26 else obj.name[:24] + "…"
        sub.label(text=label, icon="MESH_DATA")
        col_name = GetMeshCollectionName(obj) if props.useCollectionFolders else None
        if col_name:
            right = sub.row()
            right.alignment = "RIGHT"
            right.label(text=col_name, icon="OUTLINER_COLLECTION")


    def DrawGroupRow(self, col, name, children, key_obj, props):
        row = col.row(align=True)
        excluded = key_obj.fbxBatchExclude
        icon = "CHECKBOX_DEHLT" if excluded else "CHECKBOX_HLT"
        row.prop(key_obj, "fbxBatchExclude", text="", icon=icon, emboss=False, invert_checkbox=True)
        sub = row.row()
        sub.active = not excluded
        label = name if len(name) <= 22 else name[:20] + "…"
        sub.label(text=label, icon="OUTLINER_OB_EMPTY")
        right = sub.row()
        right.alignment = "RIGHT"
        col_name = GetMeshCollectionName(key_obj) if props.useCollectionFolders else None
        if col_name:
            right.label(text=col_name, icon="OUTLINER_COLLECTION")
        right.label(text=f"{len(children)} meshes")


    def DrawNameGroupRow(self, col, fbx_name, objects, props):
        row = col.row(align=True)
        sub = row.row()
        label = fbx_name if len(fbx_name) <= 22 else fbx_name[:20] + "…"
        sub.label(text=label, icon="FILE_3D")
        right = sub.row()
        right.alignment = "RIGHT"
        right.label(text=f"{len(objects)} meshes")

        for obj in objects:
            child_row = col.row(align=True)
            child_row.separator(factor=2.0)
            excluded = obj.fbxBatchExclude
            icon = "CHECKBOX_DEHLT" if excluded else "CHECKBOX_HLT"
            child_row.prop(obj, "fbxBatchExclude", text="", icon=icon, emboss=False, invert_checkbox=True)
            child_sub = child_row.row()
            child_sub.active = not excluded
            child_label = obj.name if len(obj.name) <= 24 else obj.name[:22] + "…"
            child_sub.label(text=child_label, icon="MESH_DATA")



registeredClasses = (
    FbxBatchProps,
    FBXBATCH_OT_export,
    FILE_PT_fbxBatch,
)



def register():
    for cls in registeredClasses:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fbxBatchProps = bpy.props.PointerProperty(type=FbxBatchProps)
    bpy.types.Object.fbxBatchExclude = BoolProperty(
        name="Exclude from Batch",
        description="Skip this object during batch FBX export",
        default=False,
    )



def unregister():
    del bpy.types.Scene.fbxBatchProps
    del bpy.types.Object.fbxBatchExclude
    for cls in reversed(registeredClasses):
        bpy.utils.unregister_class(cls)



if __name__ == "__main__":
    register()
