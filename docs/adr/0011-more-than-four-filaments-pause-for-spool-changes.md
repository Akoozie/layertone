# 0011: More than 4 filaments: the print pauses for Spool changes

Date: 2026-10-29

A Layered Stack may have up to 8 filaments (was 4, ADR 0002), and a filament may come
back higher up (black, Jade White, blue, black). The AMS lite still holds 4 spools, so:

- The 3MF's project filaments are the 4 **Lanes**, not the Stack. The first 4 different
  filaments start in lanes 1-4; a filament that comes back reuses its lane.
- A 5th different filament takes the lane whose filament is needed again furthest away
  (never the one printing), so you swap as few spools as possible (spools.py).
- One layer before it is needed, on the latest layer without a tool change, the 3MF has a
  Bambu pause (`type="1"`, the A1's `M400 U1`) with the message "Swap the X spool for Y".
  Pause and tool change never share a layer: Bambu keeps one custom G-code per layer.
- Purges into a lane that gets a Spool change use the template's largest flush volume,
  since the colour in that lane changes.
- The swap planner only keeps layouts with a free layer for every pause. It now ranks all
  layouts at once on a coarse colour set and scores the best 8 exactly; past 5000 layouts
  (tall Stacks with many filaments) it searches by moving one swap at a time.
- Flat Paint and Cards stay at 4: they print colours side by side in the same layers.

Not yet tested on the printer: how the AMS lite takes a spool swapped in by hand during a
pause. The first print with a Spool change should be watched.
