# Fill a Bambu Studio template 3MF instead of writing one from scratch

We export by opening a template project (templates/a1_0.08.3mf, taken from a real HueForge export for the A1) and replacing its mesh, thumbnails, filament colours and tool changes. Writing a 3MF from scratch would mean reproducing hundreds of Bambu print settings; the template already has the ones that worked (0.08 mm layers, 0.2 mm first layer, AMS lite slots). The cost is that we depend on Bambu's private file layout (`Metadata/*.config`) and need one template per printer and layer height.
