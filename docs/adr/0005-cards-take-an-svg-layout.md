# 0005: Cards can take an SVG layout

Date: 2026-10-28

The request was a cleaner, more modern card. The built-in Card layout (picture left,
text centre, QR right) can't do it, and every new look would mean more Card mode
options. A card is a flat object, so it can be drawn as an SVG instead.

Decision: `svg_card` in src/layertone/card.py turns an 85 x 55 mm SVG into the
same fixed-band Card as ADR 0004.

- resvg (the resvg-py wheel, no system libraries) renders it at half the mesh pixel
  (0.04 mm) on white. Text always uses the bundled Inter / Inter Display (OFL).
- The design's colours are the exact colours of its flat areas (anti-aliased edges
  don't count). Each prints in the nearest filament of the Stack (Lab distance).
  Two colours on one filament give a warning naming them.
- The filaments are reordered: the card face first, then from smallest to largest
  area, so small text stands lowest (sturdy, short shadows, no stripes of other
  bands on its sides). A 5-layer blue band over black still shows as blue.
- SVG cards default to 0.8 mm at the thinnest point (about a 0.9 mm card): the
  1.2 mm built-in default looked like a plaque.
- `data-back="blue"` on the <svg> (or `--back`) prints that filament first: the
  side on the bed is then solid colour, it shows as a stripe on the card edge, and
  shapes in that colour on the front become inlays down to it.
- `class="raise"` shapes in the top filament stand 0.4 mm taller (same colour emboss).
- Strokes narrower than about 0.45 mm (what an octagon opening removes, not
  counting rounded-off corners) are grown one sub-pixel per pass, up to 4 passes.
- Each 0.08 mm pixel's height is the mix of its 2 x 2 sub-pixels' band tops.
- QR codes are the designer's job: draw them on a 1 mm grid, full-size QR (not Micro QR).
  examples/cards/make_designs.py does this with segno.

Later the same day the first three example designs were judged amateur. They were
replaced by three layouts built on a 6 mm margin and 4 mm baseline grid with two
type sizes (examples/cards). Small text is always as heavy as Inter Bold because of
the 0.45 mm stroke rule, so hierarchy comes from size and space, not weight.
`layertone-card --photo` (src/layertone/photo.py) renders a lit, angled view of the
printed card to judge designs by.

Round 3, after an independent review graded round 2 at 4-6/10: the 0.45 mm stroke
rule makes every line of text under about 4 mm print as heavy as Inter Bold or
heavier (2.6 mm text becomes ~0.17 em strokes, heavier than Inter Black). Weight
contrast is only possible with big type: Inter Display Regular needs 6.2 mm, Light
7.8 mm (measured: Light 0.058 em, Regular 0.072, Medium 0.083, SemiBold 0.098,
Bold 0.113 thinnest stroke). So hierarchy = a large light name against small heavy
details, plus case, size and space. Examples: night (picked) and crop.
