# 0008: Engraved cards: dark top, 0.8 mm grooves, 5 mm caps; inlays in 0.16 mm layers

Date: 2026-10-28

TEST4 (white top, 0.45 mm grooves, 2 mm caps) printed with the small text filled in.
The card research (library reports/business_cards_2026-10-28/) found makers use two
nozzle lines (~0.8 mm) per stroke and 5-6 mm caps on a 0.4 nozzle. So:

- `ENGRAVE_STROKE` 0.8 mm: grooves are thickened to at least that.
- `ENGRAVE_CAP` 5 mm: an engraved SVG with `<text>` under 5 mm cap height (font-size x
  0.727), or a built-in text card that has to shrink below it, gets a warning that
  points to the Smooth (face-down) finish.
- `engraved()` makes the darkest filament the card face and the lightest the text
  (`dark_top=False` / `--light-top` keeps the chosen face). Black hides what is under
  it in 0.4 mm, so the grooves are half as deep as they are wide and the card is about
  1.1 mm (0.72 mm white floor, 0.4 mm black top) instead of 1.6 mm. Still one swap.
  SVG layouts keep their own colours: design them dark (examples/cards/contour_logo.svg).
- Face-down inlays print in `INLAY_LAYER` 0.16 mm layers (the 3MF's layer height too):
  the front is flat, so finer Z only adds swaps. White in black is 0.2 + 4 x 0.16 =
  0.84 mm, 5 layers instead of 9, about half the swaps. The body behind is whole layers.
- Face-down inlay 3MFs stay on the textured PEI plate (the A1's stock
  plate). `--smooth-plate` asks for smooth PEI ("High Temp Plate"): the face takes the
  plate's finish, and texture softens fine edges, so on textured keep details ~3 mm caps. 5 mm engraved text
  looked goofy, so small text (2.5-3 mm caps, phone numbers) goes face down:
  black in white needs only 0.36 mm (2 layers), about 3 swaps
  (examples/cards/contour_logo_inlay.svg, TEST7).
