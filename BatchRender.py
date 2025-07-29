bl_info = {
    "name": "BatchRender",
    "blender": (3, 0, 0),
    "category": "Render",
    "version": (2, 1, 0),
    "author": "Assistant",
    "description": "Professional single object and batch rendering suite",
    "location": "3D Viewport > Sidebar (N) > BatchRender",
}

import bpy
import os
import time
import shutil
from bpy.types import Panel, Operator, UIList, PropertyGroup
from bpy.props import BoolProperty, StringProperty, CollectionProperty, IntProperty, FloatProperty, EnumProperty

class RENDER_UL_batch_objects(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            if item.obj and item.obj.name in bpy.data.objects:
                layout.prop(item.obj, "name", text="", emboss=False, icon='OBJECT_DATA')
            else:
                layout.label(text="Invalid Object", icon='ERROR')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='OBJECT_DATA')

class RENDER_PG_batch_object(PropertyGroup):
    obj: bpy.props.PointerProperty(
        type=bpy.types.Object,
        name="Object"
    )

class RENDER_OT_single_object(Operator):
    """Render only the selected object"""
    bl_idname = "render.single_object"
    bl_label = "Render Selected Object"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        if not context.active_object:
            self.report({'ERROR'}, "No object selected!")
            return {'CANCELLED'}
        
        selected_obj = context.active_object
        scene = context.scene
        visibility_states = {}
        
        # Save and hide all other objects
        for obj in bpy.data.objects:
            if obj != selected_obj:
                visibility_states[obj.name] = {
                    'hide_viewport': obj.hide_viewport,
                    'hide_render': obj.hide_render
                }
                obj.hide_render = True
                obj.hide_viewport = True
        
        # Set proper file extension
        self.set_file_extension(context)
        
        # Start render
        bpy.ops.render.render('INVOKE_DEFAULT')
        
        # Restore visibility after delay
        if scene.single_render_restore:
            def restore_settings():
                for obj_name, states in visibility_states.items():
                    if obj_name in bpy.data.objects:
                        obj = bpy.data.objects[obj_name]
                        obj.hide_viewport = states['hide_viewport']
                        obj.hide_render = states['hide_render']
                return None
            
            bpy.app.timers.register(restore_settings, first_interval=2.0)
        
        self.report({'INFO'}, f"Rendering '{selected_obj.name}'")
        return {'FINISHED'}
    
    def set_file_extension(self, context):
        """Set proper file extension based on format"""
        scene = context.scene
        file_format = scene.render.image_settings.file_format
        
        extensions = {
            'PNG': '.png',
            'JPEG': '.jpg',
            'OPEN_EXR': '.exr',
            'TIFF': '.tiff',
            'BMP': '.bmp',
            'TARGA': '.tga'
        }
        
        extension = extensions.get(file_format, '.png')
        
        if not scene.render.filepath.endswith(extension):
            if '.' in scene.render.filepath:
                scene.render.filepath = scene.render.filepath.rsplit('.', 1)[0] + extension
            else:
                scene.render.filepath += extension

class RENDER_OT_add_to_batch(Operator):
    """Add selected object to batch render list"""
    bl_idname = "render.add_to_batch"
    bl_label = "Add to List"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        if not context.active_object:
            self.report({'ERROR'}, "No object selected!")
            return {'CANCELLED'}
        
        selected_obj = context.active_object
        
        # Check if already in list
        for item in scene.batch_render_objects:
            if item.obj == selected_obj:
                self.report({'WARNING'}, f"'{selected_obj.name}' already in list!")
                return {'CANCELLED'}
        
        # Add to list
        item = scene.batch_render_objects.add()
        item.obj = selected_obj
        
        self.report({'INFO'}, f"'{selected_obj.name}' added to batch list")
        return {'FINISHED'}

class RENDER_OT_remove_from_batch(Operator):
    """Remove selected item from batch render list"""
    bl_idname = "render.remove_from_batch"
    bl_label = "Remove from List"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        index = scene.batch_render_index
        
        if 0 <= index < len(scene.batch_render_objects):
            obj_name = scene.batch_render_objects[index].obj.name if scene.batch_render_objects[index].obj else "Unknown"
            scene.batch_render_objects.remove(index)
            scene.batch_render_index = min(max(0, index - 1), len(scene.batch_render_objects) - 1)
            self.report({'INFO'}, f"'{obj_name}' removed from batch list")
        
        return {'FINISHED'}

class RENDER_OT_clear_batch(Operator):
    """Clear batch render list"""
    bl_idname = "render.clear_batch"
    bl_label = "Clear List"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        context.scene.batch_render_objects.clear()
        context.scene.batch_render_index = 0
        self.report({'INFO'}, "Batch list cleared")
        return {'FINISHED'}

class RENDER_OT_cancel_batch(Operator):
    """Cancel batch rendering"""
    bl_idname = "render.cancel_batch"
    bl_label = "Cancel Batch Render"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        scene.batch_render_cancelled = True
        self.report({'INFO'}, "Batch render cancelled")
        return {'FINISHED'}

class RENDER_OT_batch_render(Operator):
    """Start batch rendering"""
    bl_idname = "render.batch_render"
    bl_label = "Start Batch Render"
    bl_options = {'REGISTER', 'UNDO'}
    
    _timer = None
    _current_index = 0
    _visibility_states = {}
    _original_filepath = ""
    _start_time = 0
    _total_objects = 0
    _is_running = False
    
    def modal(self, context, event):
        scene = context.scene
        
        if event.type == 'TIMER':
            # Check if cancelled
            if scene.batch_render_cancelled:
                self.finish_batch_render(context, cancelled=True)
                return {'CANCELLED'}
            
            # Check if render completed
            try:
                is_rendering = bpy.app.is_job_running('RENDER')
            except:
                is_rendering = False
            
            if not is_rendering and self._is_running:
                # Update progress
                scene.batch_render_progress = ((self._current_index + 1) / self._total_objects) * 100
                
                # Move to next object
                self._current_index += 1
                
                if self._current_index < len(scene.batch_render_objects):
                    self.render_next_object(context)
                else:
                    self.finish_batch_render(context)
                    return {'FINISHED'}
            
            # Update progress info
            if self._is_running:
                self.update_progress_info(context)
        
        return {'PASS_THROUGH'}
    
    def execute(self, context):
        scene = context.scene
        
        if len(scene.batch_render_objects) == 0:
            self.report({'ERROR'}, "Batch list is empty!")
            return {'CANCELLED'}
        
        if not scene.batch_render_path:
            self.report({'ERROR'}, "Output folder not selected!")
            return {'CANCELLED'}
        
        # Check and create output directory
        output_path = bpy.path.abspath(scene.batch_render_path)
        if not os.path.exists(output_path):
            try:
                os.makedirs(output_path)
            except PermissionError:
                self.report({'ERROR'}, "Cannot create folder: Permission denied!")
                return {'CANCELLED'}
            except Exception as e:
                self.report({'ERROR'}, f"Cannot create folder: {str(e)}")
                return {'CANCELLED'}
        
        # Check write permissions
        if not os.access(output_path, os.W_OK):
            self.report({'ERROR'}, "No write permission to output folder!")
            return {'CANCELLED'}
        
        # Check disk space (minimum 100MB)
        try:
            free_space = shutil.disk_usage(output_path).free
            if free_space < 100 * 1024 * 1024:  # 100MB
                self.report({'WARNING'}, "Low disk space detected!")
        except:
            pass
        
        # Initialize batch render
        self._original_filepath = scene.render.filepath
        self._visibility_states = {}
        
        # Save all objects visibility states
        for obj in bpy.data.objects:
            self._visibility_states[obj.name] = {
                'hide_viewport': obj.hide_viewport,
                'hide_render': obj.hide_render
            }
        
        # Reset progress and status
        scene.batch_render_cancelled = False
        scene.batch_render_progress = 0
        scene.batch_render_current_object = ""
        scene.batch_render_status = "Starting batch render..."
        scene.batch_render_eta = "Calculating..."
        
        # Initialize counters
        self._start_time = time.time()
        self._total_objects = len(scene.batch_render_objects)
        self._is_running = True
        self._current_index = 0
        
        # Start rendering first object
        self.render_next_object(context)
        
        # Start modal timer
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        
        self.report({'INFO'}, f"Batch render started: {self._total_objects} objects")
        return {'RUNNING_MODAL'}
    
    def render_next_object(self, context):
        scene = context.scene
        
        if self._current_index >= len(scene.batch_render_objects):
            return
            
        current_item = scene.batch_render_objects[self._current_index]
        current_obj = current_item.obj
        
        # Validate object
        if not current_obj or current_obj.name not in bpy.data.objects:
            print(f"Skipping invalid object at index {self._current_index}")
            self._current_index += 1
            if self._current_index < len(scene.batch_render_objects):
                self.render_next_object(context)
            else:
                self.finish_batch_render(context)
            return
        
        # Hide all objects
        for obj in bpy.data.objects:
            obj.hide_render = True
            obj.hide_viewport = True
        
        # Show only current object
        current_obj.hide_render = False
        current_obj.hide_viewport = False
        
        # Generate filename
        prefix = scene.batch_render_prefix.strip()
        clean_name = bpy.path.clean_name(current_obj.name)
        
        if prefix:
            filename = f"{prefix}_{clean_name}_{self._current_index + 1:03d}"
        else:
            filename = f"{clean_name}_{self._current_index + 1:03d}"
        
        # Set filepath with proper extension
        extension = self.get_file_extension(scene)
        filepath = os.path.join(
            bpy.path.abspath(scene.batch_render_path),
            filename + extension
        )
        scene.render.filepath = filepath
        
        # Update status
        scene.batch_render_current_object = current_obj.name
        scene.batch_render_status = f"Rendering: {current_obj.name} ({self._current_index + 1}/{self._total_objects})"
        
        # Force viewport update
        bpy.context.view_layer.update()
        
        # Start render
        try:
            bpy.ops.render.render('INVOKE_DEFAULT', write_still=True)
            print(f"Rendering {self._current_index + 1}/{self._total_objects}: {current_obj.name}")
        except Exception as e:
            print(f"Render error for {current_obj.name}: {e}")
            self.report({'ERROR'}, f"Failed to render {current_obj.name}")
            # Continue with next object
            self._current_index += 1
            if self._current_index < len(scene.batch_render_objects):
                self.render_next_object(context)
            else:
                self.finish_batch_render(context)
    
    def finish_batch_render(self, context, cancelled=False):
        scene = context.scene
        wm = context.window_manager
        
        # Stop timer
        if self._timer:
            wm.event_timer_remove(self._timer)
            self._timer = None
        
        # Restore original settings
        scene.render.filepath = self._original_filepath
        
        # Restore object visibility
        for obj_name, states in self._visibility_states.items():
            if obj_name in bpy.data.objects:
                obj = bpy.data.objects[obj_name]
                obj.hide_viewport = states['hide_viewport']
                obj.hide_render = states['hide_render']
        
        # Reset variables
        self._current_index = 0
        self._visibility_states = {}
        self._is_running = False
        
        # Update final status
        if cancelled:
            scene.batch_render_progress = 0
            scene.batch_render_status = "Cancelled by user"
            scene.batch_render_eta = ""
            scene.batch_render_current_object = ""
            scene.batch_render_cancelled = False
        else:
            scene.batch_render_progress = 100
            scene.batch_render_current_object = ""
            scene.batch_render_status = f"Completed! {self._total_objects} objects rendered"
            
            elapsed_time = time.time() - self._start_time
            minutes = int(elapsed_time // 60)
            seconds = int(elapsed_time % 60)
            scene.batch_render_eta = f"Total time: {minutes:02d}:{seconds:02d}"
            
            print(f"Batch render completed: {self._total_objects} objects")
    
    def update_progress_info(self, context):
        """Update progress and ETA information"""
        scene = context.scene
        
        if self._total_objects > 0 and self._current_index > 0:
            elapsed_time = time.time() - self._start_time
            avg_time_per_object = elapsed_time / self._current_index
            remaining_objects = self._total_objects - self._current_index
            eta_seconds = avg_time_per_object * remaining_objects
            
            eta_minutes = int(eta_seconds // 60)
            eta_secs = int(eta_seconds % 60)
            scene.batch_render_eta = f"ETA: {eta_minutes:02d}:{eta_secs:02d}"
            
            progress = (self._current_index / self._total_objects) * 100
            scene.batch_render_progress = progress
    
    def get_file_extension(self, scene):
        """Get proper file extension based on render format"""
        file_format = scene.render.image_settings.file_format
        
        extensions = {
            'PNG': '.png',
            'JPEG': '.jpg',
            'OPEN_EXR': '.exr',
            'TIFF': '.tiff',
            'BMP': '.bmp',
            'TARGA': '.tga',
            'IRIS': '.rgb',
            'CINEON': '.cin',
            'DPX': '.dpx'
        }
        
        return extensions.get(file_format, '.png')

class RENDER_OT_restore_all(Operator):
    """Show all objects in viewport and render"""
    bl_idname = "render.restore_all"
    bl_label = "Show All Objects"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        for obj in bpy.data.objects:
            obj.hide_viewport = False
            obj.hide_render = False
        
        self.report({'INFO'}, "All objects restored")
        return {'FINISHED'}

class RENDER_OT_hide_others(Operator):
    """Hide all objects except selected"""
    bl_idname = "render.hide_others"
    bl_label = "Hide Others"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        if not context.active_object:
            self.report({'ERROR'}, "No object selected!")
            return {'CANCELLED'}
        
        selected_obj = context.active_object
        
        for obj in bpy.data.objects:
            if obj != selected_obj:
                obj.hide_viewport = True
                obj.hide_render = True
        
        self.report({'INFO'}, f"Hidden all except '{selected_obj.name}'")
        return {'FINISHED'}

class RENDER_PT_single_object_panel(Panel):
    """Single Object Render Panel"""
    bl_label = "BatchRender"
    bl_idname = "RENDER_PT_single_object"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "BatchRender"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        
        # SINGLE OBJECT RENDER SECTION
        box = layout.box()
        row = box.row()
        row.label(text="Single Object Render", icon='RENDER_STILL')
        
        if context.active_object:
            # Active object info
            col = box.column(align=False)
            split = col.split(factor=0.3)
            split.label(text="Active:")
            split.label(text=context.active_object.name, icon='OBJECT_DATA')
            
            # Main render button
            col = box.column(align=True)
            col.scale_y = 1.3
            col.operator("render.single_object", text="Render Selected Object", icon='RENDER_STILL')
            
            # Options
            box.separator(factor=0.3)
            row = box.row()
            row.prop(scene, "single_render_restore", text="Auto Restore", icon='RECOVER_LAST')
            
            # Helper buttons
            box.separator(factor=0.3)
            row = box.row(align=True)
            row.operator("render.hide_others", text="Hide Others", icon='HIDE_ON')
            row.operator("render.restore_all", text="Show All", icon='HIDE_OFF')
        else:
            # No selection state
            col = box.column(align=True)
            col.scale_y = 1.2
            col.alert = True
            col.label(text="No object selected", icon='ERROR')
            col.alert = False
            col.scale_y = 1.0
            col.label(text="Select an object to render", icon='INFO')
        
        layout.separator()
        
        # BATCH RENDER SECTION
        box = layout.box()
        row = box.row()
        row.label(text="Batch Render", icon='RENDERLAYERS')
        
        # Output settings
        col = box.column(align=False)
        col.label(text="Output Settings:", icon='FILEBROWSER')
        
        col = box.column(align=True)
        col.prop(scene, "batch_render_path", text="")
        
        row = col.row(align=True)
        row.prop(scene, "batch_render_prefix", text="", icon='SMALL_CAPS')
        
        box.separator()
        
        # Render format settings
        format_box = box.box()
        format_box.label(text="Format", icon='SCENE_DATA')
        
        # Dimensions
        col = format_box.column(align=True)
        col.label(text="Dimensions:")
        
        row = col.row(align=True)
        row.prop(scene.render, "resolution_x", text="X")
        row.prop(scene.render, "resolution_y", text="Y")
        
        col.separator()
        
        # Output format
        col = format_box.column(align=True)
        col.label(text="Output:")
        col.template_image_settings(scene.render.image_settings, color_management=False)
        
        box.separator()
        
        # Object list section
        col = box.column(align=False)
        row = col.row()
        row.label(text="Objects to Render:", icon='OUTLINER_OB_MESH')
        if context.active_object:
            row.operator("render.add_to_batch", text="", icon='ADD')
        
        # List and controls
        row = col.row()
        row.template_list("RENDER_UL_batch_objects", "", scene, "batch_render_objects", scene, "batch_render_index", rows=4)
        
        col_buttons = row.column(align=True)
        col_buttons.operator("render.remove_from_batch", text="", icon='REMOVE')
        col_buttons.separator()
        col_buttons.operator("render.clear_batch", text="", icon='TRASH')
        
        # List status
        if len(scene.batch_render_objects) > 0:
            sub = col.column(align=True)
            sub.scale_y = 0.8
            sub.label(text=f"Total: {len(scene.batch_render_objects)} objects", icon='INFO')
        else:
            sub = col.column(align=True)
            sub.scale_y = 0.9
            sub.enabled = False
            sub.label(text="List is empty", icon='INFO')
            sub.label(text="Select object and click + to add")
        
        # Progress display (only during rendering)
        if hasattr(scene, 'batch_render_progress') and scene.batch_render_progress > 0:
            box.separator()
            progress_box = box.box()
            progress_box.label(text="Render Progress", icon='TIME')
            
            # Progress bar
            col = progress_box.column(align=True)
            row = col.row(align=True)
            row.prop(scene, "batch_render_progress", text="", slider=True)
            row.label(text=f"{scene.batch_render_progress:.0f}%")
            
            # Status information
            if scene.batch_render_current_object:
                col.label(text=f"Current: {scene.batch_render_current_object}", icon='OBJECT_DATA')
            
            if scene.batch_render_status and "Rendering:" in scene.batch_render_status:
                col.label(text=scene.batch_render_status, icon='RENDER_ANIMATION')
            
            if scene.batch_render_eta and scene.batch_render_eta != "Calculating...":
                col.label(text=scene.batch_render_eta, icon='TIME')
            
            # Cancel button during rendering
            if scene.batch_render_progress > 0 and scene.batch_render_progress < 100:
                col.separator()
                col.operator("render.cancel_batch", text="Cancel Rendering", icon='CANCEL')
        
        # Batch render button
        if len(scene.batch_render_objects) > 0 and scene.batch_render_path:
            box.separator()
            col = box.column(align=True)
            col.scale_y = 1.4
            
            # Button state based on render status
            if hasattr(scene, 'batch_render_progress') and 0 < scene.batch_render_progress < 100:
                col.enabled = False
                col.operator("render.batch_render", text="Rendering...", icon='TIME')
            else:
                col.operator("render.batch_render", text=f"Render {len(scene.batch_render_objects)} Objects", icon='RENDER_ANIMATION')
        else:
            # Missing settings warning
            col = box.column(align=True)
            col.scale_y = 1.2
            col.enabled = False
            
            if len(scene.batch_render_objects) == 0:
                col.operator("render.batch_render", text="Add Objects to List", icon='INFO')
            elif not scene.batch_render_path:
                col.operator("render.batch_render", text="Set Output Path", icon='INFO')

def register():
    # Register classes
    bpy.utils.register_class(RENDER_PG_batch_object)
    bpy.utils.register_class(RENDER_UL_batch_objects)
    bpy.utils.register_class(RENDER_OT_single_object)
    bpy.utils.register_class(RENDER_OT_add_to_batch)
    bpy.utils.register_class(RENDER_OT_remove_from_batch)
    bpy.utils.register_class(RENDER_OT_clear_batch)
    bpy.utils.register_class(RENDER_OT_cancel_batch)
    bpy.utils.register_class(RENDER_OT_batch_render)
    bpy.utils.register_class(RENDER_OT_restore_all)
    bpy.utils.register_class(RENDER_OT_hide_others)
    bpy.utils.register_class(RENDER_PT_single_object_panel)
    
    # Register scene properties
    bpy.types.Scene.single_render_restore = BoolProperty(
        name="Restore After Render",
        description="Restore other objects visibility after render completes",
        default=True
    )
    
    bpy.types.Scene.batch_render_objects = CollectionProperty(
        type=RENDER_PG_batch_object
    )
    
    bpy.types.Scene.batch_render_index = IntProperty(
        name="Index for batch render list",
        default=0
    )
    
    bpy.types.Scene.batch_render_path = StringProperty(
        name="Batch Render Output Path",
        description="Folder where batch render files will be saved",
        default="//renders/",
        subtype='DIR_PATH'
    )
    
    bpy.types.Scene.batch_render_prefix = StringProperty(
        name="Batch Render Prefix",
        description="Prefix to be added to filenames (e.g. 'project_v1')",
        default="",
        maxlen=50
    )
    
    # Progress tracking properties
    bpy.types.Scene.batch_render_progress = FloatProperty(
        name="Batch Render Progress",
        description="Batch render progress percentage",
        default=0.0,
        min=0.0,
        max=100.0,
        subtype='PERCENTAGE'
    )
    
    bpy.types.Scene.batch_render_current_object = StringProperty(
        name="Current Rendering Object",
        description="Currently rendering object name",
        default=""
    )
    
    bpy.types.Scene.batch_render_status = StringProperty(
        name="Batch Render Status",
        description="Current batch render status",
        default="Ready"
    )
    
    bpy.types.Scene.batch_render_eta = StringProperty(
        name="Batch Render ETA",
        description="Estimated time remaining",
        default=""
    )
    
    bpy.types.Scene.batch_render_cancelled = BoolProperty(
        name="Batch Render Cancelled",
        description="Flag to cancel batch render",
        default=False
    )

def unregister():
    # Unregister classes
    bpy.utils.unregister_class(RENDER_PG_batch_object)
    bpy.utils.unregister_class(RENDER_UL_batch_objects)
    bpy.utils.unregister_class(RENDER_OT_single_object)
    bpy.utils.unregister_class(RENDER_OT_add_to_batch)
    bpy.utils.unregister_class(RENDER_OT_remove_from_batch)
    bpy.utils.unregister_class(RENDER_OT_clear_batch)
    bpy.utils.unregister_class(RENDER_OT_cancel_batch)
    bpy.utils.unregister_class(RENDER_OT_batch_render)
    bpy.utils.unregister_class(RENDER_OT_restore_all)
    bpy.utils.unregister_class(RENDER_OT_hide_others)
    bpy.utils.unregister_class(RENDER_PT_single_object_panel)
    
    # Clean up properties
    del bpy.types.Scene.single_render_restore
    del bpy.types.Scene.batch_render_objects
    del bpy.types.Scene.batch_render_index
    del bpy.types.Scene.batch_render_path
    del bpy.types.Scene.batch_render_prefix
    del bpy.types.Scene.batch_render_progress
    del bpy.types.Scene.batch_render_current_object
    del bpy.types.Scene.batch_render_status
    del bpy.types.Scene.batch_render_eta
    del bpy.types.Scene.batch_render_cancelled

if __name__ == "__main__":
    register()