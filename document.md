# Functional Requirements

## 1. Overview
LabelMV is a multi-view video annotation tool designed to facilitate labeling of objects across synchronized video streams. Users can draw, edit, and manage bounding box annotations, assign object classes, unique IDs, and personal protective equipment (PPE) attributes, and export or import labels.

## 2. Functional Requirements

### 2.1 Launcher UI
- FR-1: Allow the user to specify the number of camera views to annotate.
- FR-2: Provide a dropdown to select display resolution.
- FR-3: Launch the main annotation UI with the specified settings.

### 2.2 Video Input and Frame Sampling
- FR-4: Allow the user to browse and load N video files, one per view.
- FR-5: Prompt the user to enter a target FPS and sample frames accordingly.
- FR-6: Retrieve individual frames by index and obtain video dimensions.

### 2.3 Frame and View Navigation
- FR-7: Display a slider for navigating sampled frames.
- FR-8: Provide "Next Frame"/"Previous Frame" buttons and support keyboard shortcuts (d/a).
- FR-9: Provide "Next View"/"Prev View" buttons and support keyboard shortcuts (w/s).
- FR-10: Display the current frame number and view index.

### 2.4 Annotation Creation and Management
- FR-11: Allow toggling "Add Label" mode to draw bounding boxes with the mouse.
- FR-12: Automatically correct boxes drawn with inverted coordinates.
- FR-13: List all bounding boxes for the current frame and view in a sidebar.
- FR-14: Enable selection of a listed annotation to highlight its box on the image.
- FR-15: Allow removal of the selected annotation via "Remove Label" button or 'r' shortcut.
- FR-16: Support resizing bounding boxes by dragging corner handles.
- FR-17: Support moving bounding boxes by dragging inside the box.

### 2.5 Label Editing and Attributes
- FR-18: Provide text inputs to edit the object class and unique ID of a box.
- FR-19: Provide an "Update Box" button to apply changes to the selected annotation.
- FR-20: Offer dropdown menus for PPE attributes:
  - Gown: [NA, GC, GI, GA]
  - Mask: [NA, PR, NC, RC, MI, MA]
  - Eyewear: [NA, PR, GG, FC, FI, SG, PG, EA]
  - Glove-L: [NA, HC, HA]
  - Glove-R: [NA, HC, HA]

### 2.6 Temporal Annotation Utilities
- FR-21: Provide a "Load prebox" feature to copy bounding boxes from the previous frame (z shortcut).
- FR-22: Provide a "Load Pre-attribute" feature to copy attributes from the previous frame for the same ID.
- FR-23: Provide a "Clear all" feature to remove all annotations for the current frame.

### 2.7 Import and Export
- FR-24: Enable exporting annotations to a text file via "Export Labels", using format:
  `view, frame, id, object, attributes, left top width height` (in original video coordinates).
- FR-25: Enable importing annotations from a text file via "Import Labels", parsing and displaying them.