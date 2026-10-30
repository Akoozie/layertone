# 0010: Walls are tiles cut from one render, with joins cut into the back

Date: 2026-10-28

A picture bigger than the A1 bed (256 mm) prints as a Wall of Tiles (`layertone.wall`,
page "Wall tiles" and "Join", `--wall 2x2 --join magnets`).

- The picture is planned and rendered once, then the heights are cut into tiles that
  share their edge pixel column or row. One Swap plan therefore covers every tile, the
  colours match across seams, and the front has no gap. Seams are plain cuts: no lip,
  no Frame (a Frame only runs round the outside of the wall).
- Joins live in the back, never in the colour layers. The Backing is raised until every
  cut leaves 0.6 mm above it (magnets: 2.8 mm backing, 4.28 mm total at the whale
  demo). The user's Backing setting is only a minimum.
- Magnet pocket is a print-tested fit for 5 x 2 mm magnets: Ø5.4 bore, four Ø1.0 crush ribs
  at 45 degrees leaving 5.0 mm, 2.2 mm deep, 0.4 mm chamfer, 9 mm from the seam, two or
  more per seam about 100 mm apart. Both tiles of a seam get the pocket at the same
  spot; a link plate (30 x 12 x 3 mm) with two matching pockets bridges the seam.
- Keys and plates are the no-magnet options: butterfly recesses 1.6 mm deep with drop-in
  keys, and Ø4.4 peg holes with two-peg plates. None leaves the back flat for gluing.
- Each tile has its label engraved 0.4 mm into the back, mirrored so it reads from the
  back, with an arrow to the top. Seam positions are measured from the tile's own edge;
  tiles in one row (or column) share their length, so both halves of a seam match.
- Export is one 3MF per tile (same plan and filament presets), one joins 3MF (one
  colour, 0.20 mm layers, 2 spares), a layout sheet PNG and a zip of them. A tile is
  500k-830k triangles with dither on; that is heavy but under 1M.
- Not yet proven on a real print: seam fit, magnet pull, and Bambu Studio slicing time.
