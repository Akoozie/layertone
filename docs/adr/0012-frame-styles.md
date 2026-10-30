# 0012: Frame styles vary the border height with no new swaps

Date: 2026-10-30

A raised Frame around the picture can now have a Style instead of only a flat rim.

- Styles are height profiles of the existing Stack, with no new swaps. Light tones
  are tall (up to max_layers, the top filament) and dark tones are low (down to
  base_layers). The middle height uses the tallest layer where the middle filament
  is on top.
- Ten styles are supported: flat, dark, bevel, cove, steps, mat, double, lip, beads,
  and rounded.
- Profiles vary with distance in from the outer edge: bevel slopes linearly, cove
  curves as a square, steps drops across three tiers, and beads places round dots
  along the sides.
- Rounded is a style whose outer corners are cut with radius equal to the frame
  width. Both single 3MF exports and tiled wall exports apply the corner outline
  mask to the mesh, and previews render transparent corners.
