bl_info = {
    "name": "FBX Mass Export mesh",
    "author": "L1ra",
    "version": (0, 7, 1),
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
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup



def GetMeshCollectionName(obj):
    for col in obj.users_collection:
        if col.name != "Scene Collection":
            return col.name
    return None



def TokenizeName(name):
    return re.findall(r'[A-Za-z]+|[0-9]+', name)



def WordSkipMatch(tokensA, tokensB):
    if len(tokensA) != len(tokensB):
        return False
    diffs = [i for i, (a, b) in enumerate(zip(tokensA, tokensB)) if a.lower() != b.lower()]
    if len(diffs) != 1:
        return False
    idx = diffs[0]
    return not tokensA[idx][0].isdigit()



def NumericPrefixMatch(tokensA, tokensB):
    if len(tokensA) == len(tokensB):
        return False
    shorter, longer = (tokensA, tokensB) if len(tokensA) < len(tokensB) else (tokensB, tokensA)
    if not shorter or not longer:
        return False
    for i, t in enumerate(shorter):
        if t.lower() != longer[i].lower():
            return False
    for t in longer[len(shorter):]:
        if not t[0].isdigit():
            return False
    return True



def NamesMatch(tokensA, tokensB):
    if tokensA == tokensB:
        return True
    if WordSkipMatch(tokensA, tokensB):
        return True
    if NumericPrefixMatch(tokensA, tokensB):
        return True
    return False



def AutoAnchorFrom(objs):
    return min(objs, key=lambda o: (len(TokenizeName(o.name)), o.name))



def GetEffectiveAnchor(objs, attr_name):
    active = [o for o in objs if not o.fbxBatchExclude]
    if not active:
        active = list(objs)
    if not active:
        return None
    for o in active:
        if getattr(o, attr_name, False):
            return o
    return AutoAnchorFrom(active)



def _OriginAnchorUpdate(self, context):
    if not getattr(self, "fbxBatchOriginAnchor", False):
        return
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        this_tokens = TokenizeName(self.name)
    except Exception:
        return
    for obj in scene.objects:
        if obj is self or obj.type != "MESH":
            continue
        if getattr(obj, "fbxBatchOriginAnchor", False):
            try:
                if NamesMatch(this_tokens, TokenizeName(obj.name)):
                    obj.fbxBatchOriginAnchor = False
            except Exception:
                pass



def _NameAnchorUpdate(self, context):
    if not getattr(self, "fbxBatchNameAnchor", False):
        return
    scene = getattr(context, "scene", None)
    if scene is None:
        return
    try:
        this_tokens = TokenizeName(self.name)
    except Exception:
        return
    for obj in scene.objects:
        if obj is self or obj.type != "MESH":
            continue
        if getattr(obj, "fbxBatchNameAnchor", False):
            try:
                if NamesMatch(this_tokens, TokenizeName(obj.name)):
                    obj.fbxBatchNameAnchor = False
            except Exception:
                pass



def GroupByNameSimilarity(objects):
    if not objects:
        return []

    tokenMap = {obj: TokenizeName(obj.name) for obj in objects}
    parent = {id(obj): id(obj) for obj in objects}

    def Find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def Union(a, b):
        ra, rb = Find(a), Find(b)
        if ra != rb:
            parent[ra] = rb

    objs = list(objects)
    n = len(objs)
    for i in range(n):
        for j in range(i + 1, n):
            if NamesMatch(tokenMap[objs[i]], tokenMap[objs[j]]):
                Union(id(objs[i]), id(objs[j]))

    groupsByRoot = {}
    for obj in objects:
        groupsByRoot.setdefault(Find(id(obj)), []).append(obj)

    return list(groupsByRoot.values())



def CollectExportGroups(context, props, useSelection=False):
    if useSelection:
        pool = [o for o in context.selected_objects if o.type == "MESH"]
    else:
        pool = [o for o in context.scene.objects if o.type == "MESH"]

    groups = []

    if props.groupByName:
        solo = [o for o in pool if o.fbxBatchSolo]
        groupable = [o for o in pool if not o.fbxBatchSolo]

        name_groups = GroupByNameSimilarity(groupable)
        used_names = {}
        for objs in name_groups:
            name_anchor = GetEffectiveAnchor(objs, "fbxBatchNameAnchor")
            origin_anchor = GetEffectiveAnchor(objs, "fbxBatchOriginAnchor")
            if name_anchor is None or origin_anchor is None:
                continue
            base = name_anchor.name
            if base in used_names:
                used_names[base] += 1
                fbx_name = f"{base}_{used_names[base]}"
            else:
                used_names[base] = 0
                fbx_name = base
            col_name = GetMeshCollectionName(name_anchor) if props.useCollectionFolders else None
            groups.append((fbx_name, col_name, objs, origin_anchor))

        for obj in solo:
            col_name = GetMeshCollectionName(obj) if props.useCollectionFolders else None
            groups.append((obj.name, col_name, [obj], obj))

    elif props.groupByParent:
        parent_map = {}
        standalone = []
        for obj in pool:
            if obj.parent and obj.parent.type == "MESH":
                parent_map.setdefault(obj.parent, []).append(obj)
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



class FBXBATCH_OT_toggleGroupExclude(Operator):
    bl_idname = "fbxbatch.toggle_group_exclude"
    bl_label = "Toggle Group Exclude"
    bl_options = {"INTERNAL"}

    anchor_name: StringProperty()

    def execute(self, context):
        anchor = context.scene.objects.get(self.anchor_name)
        if anchor is None or anchor.type != "MESH":
            return {"CANCELLED"}

        tokens = TokenizeName(anchor.name)
        group = [
            o for o in context.scene.objects
            if o.type == "MESH"
            and not o.fbxBatchSolo
            and NamesMatch(tokens, TokenizeName(o.name))
        ]
        if not group:
            return {"CANCELLED"}

        all_excluded = all(o.fbxBatchExclude for o in group)
        new_val = not all_excluded
        for o in group:
            o.fbxBatchExclude = new_val
        return {"FINISHED"}



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

        for obj in all_objs:
            parent_in_group = obj.parent is not None and obj.parent in all_objs
            if parent_in_group:
                continue

            if obj.parent is not None:
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
        raw_groups = CollectExportGroups(self.context, self.props, self.fbxOp.use_selection)

        groups = []
        for name, col_name, objects, key_obj in raw_groups:
            active = [o for o in objects if not o.fbxBatchExclude]
            if not active:
                continue
            if key_obj is None or key_obj.fbxBatchExclude or key_obj not in objects:
                key_obj = active[0]
            groups.append((name, col_name, active, key_obj))

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
                        if len(objs) >= 2:
                            self.DrawNameGroupHeader(preview_col, fbx_name, objs)
                        for obj in objs:
                            self.DrawNameGroupChild(preview_col, obj, objs, indent=(len(objs) >= 2))
                elif props.groupByParent:
                    pool = (
                        [o for o in context.selected_objects if o.type == "MESH"]
                        if fbxOp.use_selection
                        else [o for o in context.scene.objects if o.type == "MESH"]
                    )
                    drawn_parents = set()
                    standalone = []
                    for obj in pool:
                        if obj.parent and obj.parent.type == "MESH":
                            if obj.parent not in drawn_parents:
                                drawn_parents.add(obj.parent)
                                children = [o for o in pool if o.parent == obj.parent]
                                self.DrawParentGroupRow(preview_col, obj.parent, children, props)
                        else:
                            standalone.append(obj)
                    for obj in standalone:
                        self.DrawObjectRow(preview_col, obj, props)
                else:
                    for fbx_name, col_name, objs, key_obj in groups:
                        for obj in objs:
                            self.DrawObjectRow(preview_col, obj, props)
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


    # ---------- draw helpers ----------

    def DrawNameGroupHeader(self, col, fbx_name, objects):
        row = col.row(align=True)

        # Group-exclude checkbox (toggles fbxBatchExclude on all members)
        all_excluded = all(o.fbxBatchExclude for o in objects)
        # Not excluded (i.e. active) → show CHECKBOX_HLT (checked).
        # All excluded → show CHECKBOX_DEHLT (empty).
        icon = "CHECKBOX_DEHLT" if all_excluded else "CHECKBOX_HLT"
        op = row.operator("fbxbatch.toggle_group_exclude", text="", icon=icon, emboss=False)
        op.anchor_name = objects[0].name

        sub = row.row()
        sub.active = not all_excluded
        label = fbx_name if len(fbx_name) <= 22 else fbx_name[:20] + "…"
        sub.label(text=label, icon="FILE_3D")
        right = sub.row()
        right.alignment = "RIGHT"
        right.label(text=f"{len(objects)} meshes")


    def DrawNameGroupChild(self, col, obj, group_objects, indent=True):
        row = col.row(align=True)
        if indent:
            row.separator(factor=2.0)

        excluded = obj.fbxBatchExclude

        # Individual exclude checkbox
        icon = "CHECKBOX_DEHLT" if excluded else "CHECKBOX_HLT"
        row.prop(obj, "fbxBatchExclude", text="", icon=icon, emboss=False, invert_checkbox=True)

        # Solo toggle
        solo = obj.fbxBatchSolo
        solo_icon = "SOLO_ON" if solo else "SOLO_OFF"
        row.prop(obj, "fbxBatchSolo", text="", icon=solo_icon, emboss=False)

        # Origin anchor (radio-button style)
        is_origin = _IsEffectiveAnchor(obj, group_objects, "fbxBatchOriginAnchor")
        origin_icon = "RADIOBUT_ON" if is_origin else "RADIOBUT_OFF"
        row.prop(obj, "fbxBatchOriginAnchor", text="", icon=origin_icon, emboss=False)

        # Name anchor (font/letter icon)
        is_name = _IsEffectiveAnchor(obj, group_objects, "fbxBatchNameAnchor")
        name_icon = "FONT_DATA" if is_name else "OUTLINER_DATA_FONT"
        row.prop(obj, "fbxBatchNameAnchor", text="", icon=name_icon, emboss=False)

        # Name label
        sub = row.row()
        sub.active = not excluded
        label = obj.name if len(obj.name) <= 24 else obj.name[:22] + "…"
        sub.label(text=label, icon="MESH_DATA")


    def DrawParentGroupRow(self, col, parent, children, props):
        row = col.row(align=True)
        excluded = parent.fbxBatchExclude
        icon = "CHECKBOX_DEHLT" if excluded else "CHECKBOX_HLT"
        row.prop(parent, "fbxBatchExclude", text="", icon=icon, emboss=False, invert_checkbox=True)
        sub = row.row()
        sub.active = not excluded
        label = parent.name if len(parent.name) <= 22 else parent.name[:20] + "…"
        sub.label(text=label, icon="OUTLINER_OB_EMPTY")
        right = sub.row()
        right.alignment = "RIGHT"
        col_name = GetMeshCollectionName(parent) if props.useCollectionFolders else None
        if col_name:
            right.label(text=col_name, icon="OUTLINER_COLLECTION")
        right.label(text=f"{len(children)} meshes")

        for obj in children:
            child_row = col.row(align=True)
            child_row.separator(factor=2.0)
            excluded = obj.fbxBatchExclude
            icon = "CHECKBOX_DEHLT" if excluded else "CHECKBOX_HLT"
            child_row.prop(obj, "fbxBatchExclude", text="", icon=icon, emboss=False, invert_checkbox=True)
            child_sub = child_row.row()
            child_sub.active = not excluded
            child_label = obj.name if len(obj.name) <= 24 else obj.name[:22] + "…"
            child_sub.label(text=child_label, icon="MESH_DATA")


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



def _IsEffectiveAnchor(obj, group_objects, attr_name):
    if getattr(obj, attr_name, False) and not obj.fbxBatchExclude:
        return True
    if any(getattr(o, attr_name, False) and not o.fbxBatchExclude for o in group_objects):
        return False
    active = [o for o in group_objects if not o.fbxBatchExclude]
    if not active:
        return False
    return AutoAnchorFrom(active) is obj



registeredClasses = (
    FbxBatchProps,
    FBXBATCH_OT_toggleGroupExclude,
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
    bpy.types.Object.fbxBatchSolo = BoolProperty(
        name="Solo (don't group)",
        description="Export this mesh as a single FBX, ignoring name-based grouping",
        default=False,
    )
    bpy.types.Object.fbxBatchOriginAnchor = BoolProperty(
        name="Origin Anchor",
        description="Use this object's origin as the pivot when moving the group to origin",
        default=False,
        update=_OriginAnchorUpdate,
    )
    bpy.types.Object.fbxBatchNameAnchor = BoolProperty(
        name="Name Anchor",
        description="Use this object's name as the FBX filename for the group",
        default=False,
        update=_NameAnchorUpdate,
    )



def unregister():
    del bpy.types.Scene.fbxBatchProps
    del bpy.types.Object.fbxBatchExclude
    del bpy.types.Object.fbxBatchSolo
    del bpy.types.Object.fbxBatchOriginAnchor
    del bpy.types.Object.fbxBatchNameAnchor
    for cls in reversed(registeredClasses):
        bpy.utils.unregister_class(cls)



if __name__ == "__main__":
    register()
