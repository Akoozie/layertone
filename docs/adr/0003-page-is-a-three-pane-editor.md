# 0003: The page is a three-pane editor

Date: 2026-10-28

The page used to be one long form: every control stacked in a left column, the
picture and the preview beside it, and the swap list below. In review it did not
look like an app.

Decision: lay the page out like a desktop editor (Bambu Studio, Figma, HueForge).

- Top bar: project name, Layered / Flat Paint switch, preview status, Open, Save, Export 3MF.
- Left: settings in sections (Picture, Stack, Size, Picture tuning, Clean up, Experimental).
- Centre: the picture and the preview at the same scale, a floating tool bar
  (Crop, Paint, Text; 2D / 3D), and a layer strip showing every layer's colour
  with the swaps marked. Dragging along it stops the preview at that layer.
- Right: the print plan (size, height, colour match, filament changes) and the calibration board.
- Each Stack row is a picker button (colour, name, TD, AMS slot) with a drag handle; a hidden
  <select> per row still holds the value. Rows reorder by drag or by ↑ ↓ on the handle, and empty
  rows always sink to the end so the bottom filament is never None.
- The filament list editor is a dialog. Messages after export or save are toasts.
- Light and dark follow the system. Still one HTML file, no build step, no CDN.
- Zoom and pan move the picture and the preview together (wheel, + / - / 0, drag the preview,
  space-drag or middle-drag on the picture, double-click the preview).
- Views: Side by side, Compare (one pane, the picture under the print, split by a line you drag;
  the picture side is cut to the crop so the two line up) and 3D.
- Keys: C / B / T pick a tool, W Compare, D 3D, Ctrl+Z, Ctrl+S, Ctrl+E.

Below 1180 px wide the side panes get narrower; below 900 px everything stacks
into one scrolling column.
