# Structure of GR1D Viz

## Objects and responsibilities

| Object | What it represents | Fields or methods you will use |
| --- | --- | --- |
| `Run` | One output folder plus its caches | `folder`, `label`, `available()`, `profile()`, `series()`, `bounce_time`, `add_profile()`, `clear_cache()` |
| `Profile` | One radial variable across time | `times`, `radii`, `values`, `at(time)` |
| `Snapshot` | One selected radial profile | `time`, `radius`, `values` |
| `Series` | One scalar diagnostic across time | `times`, `values` |
| `Panel` | Settings for one radial curve/axis | `variable`, `ylabel`, `yscale`, `ylim`, `factor`, `color`, `twin`, `hlines` |
| `EOS` | An EOS file plus cached interpolators | `interpolator(variable)`, `profile(run, variable)` |

## Trace a data request

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import Run
run = Run("/path/to/output", label="s24")
p = run.profile("mass_grav")
snap = p.at(0.3)
print(snap.time)  # actual selected simulation time
radius_km = snap.radius * CM_TO_KM
```

1. `Run.profile` checks for a registered derived profile first.
2. Otherwise it resolves `mass_grav.xg` and checks the source modification time
   and size against the memory cache.
3. On a cache miss it tries the optional disk cache; otherwise it calls `read_xg`.
4. `read_xg` reads Time blocks, drops negative-radius ghost rows, validates the
   remaining grid, sorts times, and returns a `Profile`.
5. The Run remembers that Profile and returns it. An unchanged source returns
   the same cached object on subsequent calls.
6. `Profile.at` selects a nearest timestamp and returns a `Snapshot` using the
   corresponding radius/value arrays. Out-of-range times raise; tolerance can
   reject a nearest match that is too far away.

`p.times[i]`, `p.radii[i]`, and `p.values[i]` describe one matching frame.
Radii/values are tuples of arrays because the number of zones can vary. Even
when the zone count is constant, the radius coordinates can move between frames.
A `Snapshot` uses singular `radius`; a `Profile` uses plural `radii`.

`run.series("temperature_c_t")` follows the scalar-table reader instead and
returns a `Series`. This differs from the top-level plotting function named
`series(...)`, which calls the method and draws its arrays.

## Choose a plotting function

| Function | Use it for | Input | Return |
| --- | --- | --- | --- |
| `profiles` | Static radial snapshots; compare times/runs | One Run or list of Runs, panels, requested times | Figure and list of primary axes |
| `animate_profiles` | Radial panels evolving with time | One Run, panels, time window/stride | Matplotlib `FuncAnimation` |
| `series` | Scalar diagnostic versus time; compare runs | One Run or list, .dat stem, column selection | Figure and one axis |
| `quicklook` | Quick central diagnostic and shock checks | One Run or list of Runs | Figure and list of axes |
| `star` | Polar view of one radial variable | One Run, variable, radius/color settings | Figure/axis, or `FuncAnimation` when animated |
| `save_animation` | Write an animation to disk | Animation, output path | No return value |

These functions do not call `show()` or save automatically. Static figures use
`fig.savefig(...)`; animations use `save_animation(...)`. Display them with
`plt.show()` or, in a notebook, `HTML(ani.to_jshtml())`. Keep a reference to `ani`.

### Static radial profiles

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import Panel, profiles
fig, axes = profiles(run, [
    Panel("mass_grav", factor=GRAMS_TO_SOLAR_MASS,
          ylabel=r"Gravitational mass ($M_\odot$)"),
], times=[0.0, 0.3], xlim=(0, 100), title="Mass profiles")
```

`times` is simulation seconds unless `postbounce=True`. With `times=None`, each
variable uses its own final frame; those frames need not be simultaneous. Explicit
times snap independently for each run/variable, and legends show actual times.
`tolerance` limits the snapping error. `xscale` controls the shared radial scale;
`xlim` is km. This function draws native coordinates without interpolation.

### Panel settings

| Setting | Meaning | Default |
| --- | --- | --- |
| `variable` | File stem or registered derived-profile name | Required |
| `ylabel` | Override the default label | Known label or variable name |
| `yscale` | Matplotlib scale, e.g. linear/log/symlog | `linear` |
| `ylim` | Vertical limits, in displayed units | Automatic |
| `factor` | Multiply raw values before plotting | `1.0` |
| `color` | Matplotlib color | Automatic |
| `twin` | Right-hand axis on the preceding primary panel | `False` |
| `hlines` | Reference lines in displayed units | Empty tuple |

For example, density and velocity can occupy one row with different vertical
axes, while temperature occupies another row:

```python
panels = [
    Panel("rho", yscale="log", ylim=(1e8, 1e15)),
    Panel("v", factor=VELOCITY_TO_C, ylabel="v/c",
          twin=True, color="tab:red", hlines=(0,)),
    Panel("temperature", ylim=(0, 75)),
]
# Requires rho.xg, v.xg, temperature.xg in the selected Run folder.
fig, axes = profiles(run, panels, times=None)
```

A twin must follow a primary; only one twin is allowed per primary. Changing
`factor` does not change the label automatically: specify the new units yourself.
`Panel` stores settings, not data, so the same list works for static and animated
radial plots. Strings and dictionaries are also accepted as panel specifications.

`axes` contains primary axes only. `fig.axes` also includes twins; in this example
`fig.axes[-1]` is the velocity twin. If you add other axes later, use a reference
to the specific twin rather than relying on its list position.

### Rescale a drawn figure

```python
axes[0].set_xlim(0, 30)
axes[0].set_ylim(1e10, 1e15)
axes[0].set_ylabel("My density label")
fig.canvas.draw_idle()
```

This operates on existing Matplotlib objects and does not call a reader.
Because Panel is frozen, create a new configuration when you want a new plot:

```python
from dataclasses import replace
narrow_density = replace(panels[0], ylim=(1e10, 1e15))
```

### Multi-panel animation

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import animate_profiles, save_animation
ani = animate_profiles(run, panels, window=(0.3, 0.4), stride=5,
                       tolerance=1e-6, xlim=(0, 100), interval=50)
save_animation(ani, "profiles.gif", fps=20)
```

`window` selects simulation time or post-bounce time, according to `postbounce`.
`stride=5` retains every fifth eligible frame. `interval` controls interactive
playback in milliseconds; export `fps` separately controls the saved movie.
Frames follow the first variable's timestamps in the common time interval.
Other variables use nearest native frames; `tolerance` rejects excessive time
mismatches. Titles display the actual selected times. Auto limits are fixed from
the selected frames, avoiding changing scales during playback.

The nested `update(frame)` function captures the arrays, lines and text created
by `animate_profiles`. Matplotlib calls it for each frame. `line.set_data(...)`
updates existing curves; it does not reread files. This captured state is called
a closure and is why a new animation class is unnecessary here.

### Scalar diagnostics and comparisons

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import series
other = Run("/path/to/other/output", label="Other model")
fig, ax = series([run, other], "temperature_c_t", postbounce=True,
                 ylabel="Central temperature (MeV)", xlim=(0, 1))
```

`time_column` and `value_column` are zero-indexed. Single-value series default
to columns 0 and 1; multi-value tables require explicit `value_column`.
Timers default to time column 1. Unknown files require both columns explicitly. `factor`, `yscale`,
`xlim`, `ylim`, and `ylabel` customize the display. Unlike radial `profiles`,
this function accepts one variable per call. Pass an existing `ax` to overlay
another scalar curve, then customize line labels through Matplotlib.

For GR1D's luminosity convention, columns 1/2/3 of `M1_flux_lum.dat` are
nu_e/anti-nu_e/nu_x. Select the column explicitly rather than inferring its meaning.
Post-bounce time requires each Run's `tbounce.dat` or explicit `bounce_time`.

### Quick checks after a run

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import quicklook
fig, axes = quicklook(run, postbounce=True)
fig.savefig("quicklook.png", dpi=200)
```

Recognized files: `rho_c_t.dat`, `temperature_c_t.dat`, `ye_c_t.dat`, and
`shock_radius_t.dat`. Missing diagnostics are skipped. If none is present, it
raises. To change which defaults appear, edit the `specs` list in `quicklook`.

### Polar cross-section

```python
from gr1d_viz.constants import CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import star
fig, ax = star(run, "mass_grav", time=0.3, max_radius=100,
               log=False, label="Enclosed gravitational mass (g)")
ani = star(run, "mass_grav", animate=True, window=(0.3, 0.4),
           stride=5, max_radius=100, log=False)
```

`max_radius` is km. `radius_label_color` sets radial tick text;
`cmap`, `vmin`, `vmax`, and `log` control color;
`resolution` controls radial display sampling. No unit `factor` parameter exists
for this function. The same function handles static and animated views; `time`
is only used for static views, while `window`/`stride` control animations.
It resamples each native radial grid and repeats values around the circle.
Unknown inner/outer radii are masked. Colors stay fixed across animation frames.