# 0007: Cards print face down with flush inlays by default

Date: 2026-10-28

Feedback: no protruding text, the surface should be smooth. A heightfield top can't give
colour without relief, so by default a Card is printed face down instead
(`inlay_card`, `export_inlay_3mf` in src/layertone/card.py). `--relief` / the page's
"Raised text" box keeps ADR 0004's raised bands. A layered photo always needs relief.

- Each pixel takes the filament whose band top is nearest its height in the raised
  Card, so the built-in layout and SVG layouts both work unchanged.
- The front is the first layers on the plate (smooth, the plate's texture). Every
  colour is a flat part there (Flat Paint style); the card colour also fills the
  body behind. The file is mirrored on purpose.
- The front layers are deep enough for each inlay to hide 90% of the body behind
  it: white in black needs 0.84 mm (0.2 + 8 x 0.08); 0.36 mm at least, 1.08 at most.
  Bambu Studio changes filament once per layer in that depth only.
- Lines can be 0.42 mm (Bambu's 0.4 mm nozzle line width) instead of 0.45: flush
  text has no side walls or shadows making it look bolder.
- About 75k triangles per card (mask_mesh runs), ~600k for a plate of 8.

Same day, the question was why so many swaps. Third finish, "engrave" (`--finish engrave`,
page Finish select): face up, the card colour on top and everything else cut into it
(`engraved(spec)`, `svg_card(engrave=True)`). Two filaments = one swap. The top band
comes from the TD (white over black: 0.88 mm, the model's 90% hide; 0.6 mm would show
~80%). Grooves are at least 0.45 mm wide (the same stroke rule as raised text).
The floor is 0.6 mm at the thinnest; a white/black card is 1.6 mm.
