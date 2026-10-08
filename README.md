# GR1D Viz

A small Python package for visualizing GR1D output. The package includes file loading,
run comparisons, configurable radial panels, animations, and polar stellar
cross-sections. This version gives the basic features necessary for visualization;
I hope to integrate other features such as visualization of progenitors through
EOS phase space in the future.

## Main functions

- `quicklook([run1, run2, ...])` compares progenitors with consistent run colors.
- Radial plots assign colors by variable, including twin axes, and styles by
  snapshot/run. Explicit Panel colors still override defaults.
- `configure_style(seaborn=True, latex=False)` configures notebook/script style;
  the CLI supports `--seaborn` and `--latex`. The bundled Matplotlib seaborn
  paper style needs no seaborn installation; LaTeX needs an external TeX setup.
- `star(..., radius_label_color="white")` controls radial tick-label color.
- `EOS({"thermo": path1, "fractions": path2})` supports multiple named files.
  Ambiguous variables require `source=`; each file retains its own grid.
- Physical display conversions are defined in `gr1d_viz.constants`.
- File discovery classifies metadata, diagnostics, spectra, mass-coordinate
  output and unsupported formats instead of guessing from `.dat`/`.xg` alone.
- Inner and outer ghosts are removed when the parameter file and full raw grid
  agree.

See [the notebook](examples/explore.ipynb) for one clearly explained example per
main plotting function. Its final section explains exactly how EOS-derived
quark fraction is computed and what the two radial axes show.

## Why a package plus a notebook?

The package holds reusable readers and plotting code; a notebook is an optional
workspace for choosing runs, variables, scales and snapshots. A short script or
the command line can produce checks after a simulation finishes. All three use
the same implementation. No uploading the output directory is necessary: run
this on the machine that has your output, including a mounted external drive.

## Install

From this folder, in your preferred Python environment:

```bash
python -m pip install -e ".[notebook,eos]"
```

Only NumPy and Matplotlib are required for the core. `eos` adds SciPy/h5py,
`notebook` adds JupyterLab/Pillow. Use Python 3.10+
and a supported Python version for these dependencies. MP4 export additionally
requires the ffmpeg executable; GIF export requires Pillow. No LaTeX installation
is required. Plotters do not change global styles, but calling `configure_style` explicitly does.

Open `examples/explore.ipynb` for the guided workflow or edit `examples/workflow.py`.

## Start here

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import Run, Panel, profiles
import matplotlib.pyplot as plt

run = Run("/path/to/output/s24", label="s24 B145", cache_dir=".gr1d-cache")
print(run.available())
fig, axes = profiles(run, [
    Panel("rho", yscale="log", ylim=(1e8, 1e15)),
    Panel("temperature", ylim=(0, 75)),
    Panel("v", factor=VELOCITY_TO_C, ylabel="v/c", twin=True),
], times=[0.73], xlim=(0, 100))
plt.show()
```

`Run()` only records a folder. Requesting `rho` reads `rho.xg`; unrelated variables
are untouched. Each loaded file is cached in memory for that Run instance and
reused while its modification time and size are unchanged. Keep the Run object
alive across notebook cells. `run.clear_cache()` releases its cached raw arrays;
figures and variables held elsewhere can still retain data. Derived profiles
remain registered until explicitly replaced or the Run is discarded.

Change an existing plot immediately:

```python
axes[0].set_xlim(0, 30)
axes[0].set_ylim(1e10, 1e15)
axes[0].set_yscale("log")
fig.canvas.draw_idle()
fig.savefig("profiles.png", dpi=300)
```

An optional `cache_dir` stores compressed NPZ profiles across
sessions. Data are keyed by absolute source path, file size, modification time,
and reader version. Cache files are safe to delete; old entries are not cleaned
automatically. The first load parses the whole selected file, not the whole output
folder. Disk caches are loaded into memory, not memory-mapped. Very large selected
files can still exhaust memory; streaming/windowed loading is a future extension.
A source changed during a read raises an error. Prefer completed run outputs.

## Plotting guide and code walkthrough

See [the user and developer guide](docs/guide.md) for a walkthrough of the object
structure, examples of each plotting function, all Panel settings, animation
behavior, and how to incorporate new features.

## Features

| Goal | API |
| --- | --- |
| Discover available names | `run.available()` |
| Raw native profiles | `run.profile("rho")` |
| Static multi-panel snapshots/run comparison | `profiles(run_or_list, panels, times=[...])` |
| Twin axis, scaling, unit factors, reference lines | `Panel(variable, twin=True, factor=..., hlines=(...))` |
| Multi-panel animation | `animate_profiles(run, panels, window=(start, end), stride=5)` |
| Static/animated polar cross-section | `star(run, "rho", animate=True, max_radius=30)` |
| Scalar diagnostics, luminosity columns | `series(run_or_list, filename_stem, value_column=...)` |
| Quick central diagnostics/shock comparison | `quicklook(run_or_list)` |
| EOS quantities on density's radial grid | `EOS(...).profile(run, "gamma")` |
| GIF or MP4 export | `save_animation(ani, "movie.gif")` |

Each plotting function returns the figure/axes or animation. It never calls
`show()` or saves automatically. Keep animation objects alive, e.g. `ani = ...`.
Use `plt.show()` on desktop or `HTML(ani.to_jshtml())` in Jupyter. Matplotlib axes
remain accessible for insets, annotations, custom ticks, and publication styling.

## Compare runs and use bounce-relative time

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import series
other = Run("/path/to/output/s28", label="s28 B145")
fig, ax = series([run, other], "shock_radius_t", postbounce=True,
                 factor=CM_TO_KM, ylabel="Shock radius (km)")
```

Times are simulation seconds by default. `postbounce=True` reads each run's
`tbounce.dat` or uses `Run(..., bounce_time=0.262)`. A missing bounce time raises
an error rather than silently assuming zero. Snapshot requests/windows use the
selected time convention. Radius is assumed cm in `.xg` and plotted in km;
values are unchanged unless a Panel/series factor is supplied. Verify these units
against your GR1D build.

`.dat` columns are zero indexed. Supported single-value series default to time
column 0 and value column 1. Multi-value files require `value_column`; timers use
time column 1. Unknown files require both columns explicitly.
For `M1_flux_lum.dat`, columns 1, 2, 3 contain electron-neutrino,
electron-antineutrino, and heavy-flavor luminosities. Other diagnostic files need explicit
column choices. Labels for unknown variables are the supplied variable name;
provide `ylabel` rather than guessing physical units.

## Coordinate correctness

- `.xg` readers support quoted `Time` blocks, blank separators, scientific/Fortran
  exponents, and varying radial zone counts. Each snapshot retains its own grid.
- Negative-radius inner ghosts are removed with their values. Outer ghosts are
  also removed when parameters and the full raw grid agree. Radius zero is
  retained when not part of a verified ghost range. Mass-coordinate and spectral
  output is classified separately and rejected by radius plotters.
- Empty/incomplete blocks and malformed rows raise actionable errors.
- Duplicate times use the last block/row. Times are sorted. Restart directories
  are not automatically concatenated; plotting several Run objects compares them.
- Static plots select the nearest recorded time and label the actual selection.
  Requests outside the recorded interval raise. `tolerance=1e-6` limits snapping.
- Animations use the first variable's native timestamps within the common time
  range. Other variables use nearest native snapshots, warn on differing times,
  and show actual times in the title. Set `tolerance` to reject mismatches. There
  is no temporal interpolation or silently zero-filled missing data.
- Polar plots interpolate onto a regular radial display grid each frame. Outside
  the recorded radial domain is masked, not extrapolated. Fixed normalization
  makes colors comparable across frames; log colors mask nonpositive values.
  This is a spherical replication of 1D output, not inferred angular structure.

## Optional EOS analysis

```python
from gr1d_viz.eos import EOS

eos = EOS({"thermo": "/path/to/sro_eos.h5",
           "fractions": "/path/to/quark_fractions.h5"})
run.add_profile("gamma", eos.profile(run, "gamma", source="thermo"))
run.add_profile("quark_fraction", eos.profile(run, "quark_fraction", source="fractions"))
fig, axes = profiles(run, [Panel("gamma", hlines=(4/3,)),
                           Panel("quark_fraction", ylim=(0, 1))], times=[0.73])
```

EOS axes must be `(ye, logtemp, logrho)` and data shape must match. This assumes
`temperature.xg` is MeV and `rho.xg` is g/cm³. EOS lookup matches temperature/ye snapshots to density times
with a default 1e-8 s tolerance and interpolates radius onto the density grid.
Out-of-table and invalid thermodynamic coordinates yield NaN. Derived results
are explicitly registered in memory: recompute after changing inputs or EOS. 
Other three-dimensional datasets on the same SRO EOS grid can be plotted similarly.
Values are returned in their stored convention: for example, `logpress` remains
logarithmic unless you explicitly convert it.

## Command line

Global options go before the subcommand:

```bash
gr1d-viz /path/to/output list
gr1dviz /path/to/runs --seaborn --postbounce quicklook --progenitors s14 s24 s28 -o comparison.png
gr1d-viz /path/to/output --latex --seaborn profiles --variables rho -o latex.png
gr1d-viz /path/to/output --postbounce quicklook -o quicklook.png
gr1d-viz /path/to/output profiles --variables rho temperature --time .73 -o profiles.png
gr1d-viz /path/to/output animate --variables rho temperature --stride 5 -o panels.gif
gr1d-viz /path/to/output star --variables rho --time .73 --max-radius 30 --log -o star.png
```

For radial comparisons, different panel scales, twin axes and animated stars, use Python
or the notebook. `--log` applies to every selected line panel in the CLI; Python
allows separate scales. `animate --time` sets the start time, while profiles/star
use it as a snapshot request.

## To be added later

EOS phase diagrams/trajectories, mass-shell tracks, and restart
stitching. Their conventions need dedicated interfaces.


## Examples

The plots in [examples/demo](examples/demo) were generated from a GR1D run.
Simulation output and EOS tables are not bundled; set your own paths in the notebook.

## GR1D

This is a separate Python tool for reading output from
[GR1D](https://github.com/evanoconnor/GR1D). The filename catalog was checked against
GR1D commit `20837489ec8f8c6db9aa644144539bd431baa86c`; custom builds may differ.
GR1D source code and EOS tables are not included. See the GR1D repository for
its documentation and scientific references.

## License

MIT License. See [LICENSE](LICENSE).
