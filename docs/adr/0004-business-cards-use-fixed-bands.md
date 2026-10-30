# 0004: Business cards use fixed filament bands, not Flat Paint parts

Date: 2026-10-28

Business cards were requested. A card needs crisp text in a solid colour, and a
plate of several cards should not cost a filament change per card.

Decision: a Card is a Layered print with a fixed Swap plan (src/layertone/card.py).

- Every filament above the base gets a band of layers that hides 90% of the one below
  (5 to 12 layers of 0.08 mm, from its TD). Text, the accent bar, the border and QR
  squares are raised to the top of their filament's band, so they show it solid.
- Swaps happen at whole-plate heights, so 8 cards on one plate still change filament
  once per Swap. Flat Paint parts would swap inside every layer they share.
- The cost: raised text in the top filament shows thin stripes of the lower bands on
  its sides. Seen from the front this doesn't show.
- A picture can be a layered photo (heights from the bands' Palette) or a one-colour
  logo in the accent filament.
- Text is Inter Bold (OFL, bundled in src/layertone/fonts), thickened so its thinnest
  strokes are at least 0.45 mm; 2.6 mm is the smallest size allowed. A card whose
  text does not fit at that size is refused rather than overlapped.
- QR squares are 1 mm on a 1 mm grid; the QR panel is the lightest filament, the
  squares the darkest. segno makes the code.
- The mesh is the same Delatin heightfield as Layered mode, at 0.08 mm pixels with
  soft edges; one card is about 40-60k triangles, a plate of 8 is under 500k.
