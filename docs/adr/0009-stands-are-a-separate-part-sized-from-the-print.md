# 0009: Stands are a separate part, sized from the print by blending two tuned stands

Date: 2026-10-28

The stand scripts (examples/stand) were tuned by hand for two prints: the 120 x 90 x
2.48 mm blue prints and the 133 x 199 x 1.48 mm portrait. The app now makes stands itself
(`layertone.stand`, page "Add a stand", `--stand`, `layertone-stand`).

- A stand is its own 3MF/STL next to the print, not a second object in the print's 3MF:
  it prints in one colour at 0.20 mm layers (4 walls, 25% gyroid), while the print
  needs 0.08 mm layers and swaps. Jade White by default.
- Plain: length = print width (rounded to 1 mm); depth, front and back height, lean,
  slot position and slot depth are blended between the two tuned stands by print height
  (90 mm -> 199.4 mm), each rounded to a whole number, clamped below 90 mm and up to 1.5x
  the span above. The two tuned prints reproduce the old stands exactly.
- Contour: the portrait stand's hill, footprint scaled by width / 133 (kept under 250 mm) and
  height / 199 (0.75-1.3, so the summit stays ~10 mm deep around the slot).
- Slot = print thickness + 0.3 mm. Still unproven on a real print.
- The page sizes the stand from its last preview (size and tallest point), so it does
  not render the full-size print a second time.
