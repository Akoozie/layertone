# layertone

Turns a picture into a thin printed panel where stacked layers of different
filaments blend into the picture's colours when lit from the front.

## Language

**Filament**:
A spool the printer can use, described by its colour, its **TD** and its **Slot**.
_Avoid_: material, colour (a filament has a colour, it is not one)

**TD (transmission distance)**:
How thick a filament must be before you can no longer see what is under it, in mm. Higher TD = more see-through.
_Avoid_: opacity, transparency

**Slot**:
The AMS lite position (1-4) a filament is loaded in on the printer.

**Stack**:
The ordered list of filaments a print uses, bottom (first printed) to top. Up to 8; a filament may come back higher up, never twice in a row.

**Lane**:
One AMS slot as the 3MF sees it: Bambu Studio's project filament 1-4. Every tool change picks a lane.

**Spool change**:
A pause in the print, one free layer before a filament that isn't loaded is needed, where you swap the spool in one **Lane** for it. Only Stacks with more than 4 different filaments have them.
_Avoid_: manual swap (a **Swap** is the layer where the filament changes)

**Swap**:
The layer at which the printer changes to the next filament in the **Stack**. A stack of N filaments has N-1 swaps.
_Avoid_: colour change, tool change (that is the slicer's word for the same thing)

**Swap plan**:
The set of swaps chosen for one picture and **Stack**.

**Base**:
The layers every point of the panel gets, printed in the first filament of the **Stack**.

**Backing**:
Solid layers of the first filament under the **Base**, only to make the panel thicker. Printed in 0.2 mm layers; it doesn't change any colour.

**Frame**:
An optional raised border around the picture, as tall as the tallest **Height**.

**Height**:
How many layers tall one point of the panel is. Taller points show more of the upper filaments.

**Palette**:
Every colour the print can show for one **Swap plan**, one per possible **Height**.

**Preview**:
A picture of how the printed panel should look, made from the **Palette**.

**Dithering**:
Mixing two neighbouring **Heights** in dots one nozzle line wide, so the eye sees a tone between them.

**Flat Paint**:
The other mode: no blending, every colour of the picture is a flat part printed in its own filament side by side.
_Avoid_: multi-colour mode

**Calibration board**:
A print with one tile per **Height** of a **Swap plan**, read against a chart of the **Palette** to check the TD guesses.

**Card**:
The business card mode: an 85 x 55 mm Layered print with a fixed **Swap plan** where every filament gets a band of layers thick enough to hide the one below. Text, bars and QR squares rise to the top of their filament's band. A Card can also come from an SVG layout, one filament per fill colour.

**Project**:
One saved file holding the edited picture and every setting.

**Stand**:
A separate one-colour part the finished print leans in: a slot 0.3 mm wider than the print's thickness, leaning back 10-12 degrees. Plain (a wedge bar as long as the print is wide) or Contour (a terraced hill with the slot on the summit).

**Wall**:
One big picture printed as a grid of **Tiles** that fit the A1 bed (about 240 mm at most). It is planned and rendered once, so every Tile has the same **Swap plan** and the colours match across the seams.

**Tile**:
One bed-sized piece of a **Wall**, named by row and column (A1 = top row, first column) with its label engraved into the back, mirrored, and an arrow to the top. Neighbouring Tiles share their edge pixels, so the picture has no gap.

**Join**:
How a Wall's Tiles hold together, cut into the back so the front has no seam lines: Magnets (5 x 2 mm magnet pockets and link plates), Dovetail keys (butterfly recesses and keys), Back clips (peg holes and two-peg plates) or None (flat backs, glue). The Backing is thickened so a pocket never reaches the colour layers.

## Relationships

- A **Stack** has 1-4 **Filaments** and N-1 **Swaps**
- A **Swap plan** fixes one **Palette**; each point of the picture gets the **Height** whose palette colour is closest
- The **Base** is always the first filament of the **Stack**

## Example dialogue

> **Dev:** "Why did the plan put all three swaps right after the base?"
> **Domain expert:** "With a dark base and see-through colours, one layer of each is enough to tint it. The tall points are then mostly white."
