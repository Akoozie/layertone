# 0006: Cards have rounded corners, cut into the mesh

Date: 2026-10-28

Feedback: square cards don't look like real cards. Every Card now has 2.5 mm corners (3 mm read like a credit card in review)
(CardSpec.corner / svg_card(corner=) / `--corner`, 0 = square).

- `heightfield_mesh(z, px, mask=...)` drops everything outside the outline: the
  heights outside are set to 0 so Delatin puts vertices along the arc, then
  triangles with a vertex outside are removed. The walls and the bottom fan come
  from the remaining outline as before, so the mesh stays closed. The arc is cut at
  pixel resolution (0.08 mm), finer than a nozzle line.
- The preview PNG gets the same outline as transparency.
- The bottom fan needs a convex (star-shaped) outline; a rounded rectangle is.
