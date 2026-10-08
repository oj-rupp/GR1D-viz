"""Configurable plots without global style changes or automatic show()."""
from dataclasses import dataclass, replace
import warnings
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.colors import Normalize, LogNorm
from .constants import CM_TO_KM

# More labels can be added based on your plotting needs here
# Follow the dictionary convention below
LABELS = {'rho': r'Density (g cm$^{-3}$)', 'temperature': 'Temperature (MeV)',
          'ye': 'Electron fraction', 'v': r'Velocity (cm s$^{-1}$)',
          'press': r'Pressure (dyn cm$^{-2}$)', 'mass_grav': 'Gravitational mass (g)',
          'mass_bary': 'Baryonic mass (g)'}

def _plain_text(value):
    """Escape generated identifiers when external TeX rendering is enabled."""
    if not plt.rcParams['text.usetex']:
        return str(value)
    replacements = {"\\": r"\textbackslash{}", "_": r"\_", "%": r"\%",
                    "&": r"\&", "#": r"\#", "$": r"\$", "{": r"\{", "}": r"\}",
                    "^": r"\textasciicircum{}", "~": r"\textasciitilde{}"}
    return ''.join(replacements.get(c, c) for c in str(value))


@dataclass(frozen=True)
class Panel:
    variable: str
    ylabel: str | None = None
    yscale: str = 'linear'
    ylim: tuple | None = None
    color: str | None = None
    factor: float = 1.0
    twin: bool = False
    hlines: tuple = ()


def _panels(panels):
    panels = [Panel(p) if isinstance(p, str) else Panel(**p) if isinstance(p, dict) else p for p in panels]
    if not panels or panels[0].twin:
        raise ValueError('Provide at least one primary panel; a twin follows its primary')
    previous_twin = False
    for p in panels:
        if p.twin and previous_twin:
            raise ValueError('Only one twin axis per primary panel')
        previous_twin = p.twin
    # Each variable gets one color, shared across primary/twin axes and frames.
    names = list(dict.fromkeys(p.variable for p in panels))
    palette = list(plt.get_cmap('tab20').colors)
    palette = palette[::2] + palette[1::2]
    if len(names) > len(palette):
        palette = [plt.get_cmap('hsv')(i / len(names)) for i in range(len(names))]
    colors = dict(zip(names, palette))
    return [replace(p, color=colors[p.variable]) if p.color is None else p for p in panels]


def _layout(panels, *, xlim=None, xscale='linear', title=''):
    fig, axes = plt.subplots(sum(not p.twin for p in panels), 1, squeeze=False,
                             sharex=True, figsize=(8, 3 * sum(not p.twin for p in panels)),
                             layout='constrained')
    primary = list(axes[:, 0])
    mapped, i = [], -1
    for p in panels:
        if not p.twin:
            i += 1
        ax = primary[i].twinx() if p.twin else primary[i]
        ax.set_ylabel(p.ylabel or LABELS.get(p.variable, _plain_text(p.variable)))
        ax.set_yscale(p.yscale)
        ax.set_xscale(xscale)
        if p.ylim is not None:
            ax.set_ylim(p.ylim)
        if xlim is not None:
            ax.set_xlim(xlim)
        for h in p.hlines:
            ax.axhline(h, color='gray', linestyle='--', linewidth=0.8)
        mapped.append(ax)
    primary[0].set_title(title)
    primary[-1].set_xlabel('Radius (km)')
    return fig, primary, mapped


def profiles(runs, panels=('rho', 'temperature', 'ye'), *, times=None,
             postbounce=False, tolerance=None, xlim=None, xscale='linear', title=''):
    """Compare native radial snapshots across runs. times are seconds.

    times=None selects each variable's own final snapshot; explicit times snap
    independently and legends report actual selected times. tolerance limits
    the mismatch. No radius/time interpolation is performed.
    """
    runs = [runs] if hasattr(runs, 'profile') else list(runs)
    if not runs:
        raise ValueError('Provide at least one Run')
    panels = _panels(panels)
    fig, primary, mapped = _layout(panels, xlim=xlim, xscale=xscale, title=title)
    requested = None if times is None else np.atleast_1d(times)
    for run_index, run in enumerate(runs):
        offset = run.bounce_time if postbounce else 0
        for p, ax in zip(panels, mapped):
            data = run.profile(p.variable)
            for j, t in enumerate([data.times[-1]] if requested is None else requested + offset):
                snap = data.at(t, tolerance=tolerance)
                ax.plot(snap.radius * CM_TO_KM, snap.values * p.factor, color=p.color,
                        linestyle=('-', '--', ':', '-.')[(run_index * (1 if requested is None else len(requested)) + j) % 4],
                        label=f'{_plain_text(run.label)}, {_plain_text(p.variable)}, t={snap.time-offset:.6g} s')
    for p, ax in zip(panels, mapped):
        ax.legend(fontsize='small', loc='upper left' if p.twin else 'upper right')
    return fig, primary


def _frames(run, panels, window, stride, postbounce, tolerance):
    if stride < 1:
        raise ValueError('stride must be >= 1')
    data = [run.profile(p.variable) for p in panels]
    lo = max(d.times[0] for d in data)
    hi = min(d.times[-1] for d in data)
    offset = run.bounce_time if postbounce else 0
    if window is not None:
        lo = max(lo, window[0] + offset)
        hi = min(hi, window[1] + offset)
    times = data[0].times[(data[0].times >= lo) & (data[0].times <= hi)][::stride]
    if not len(times):
        raise ValueError('No frames in the common time window')
    # Preflight before starting animation; no silent gaps or fabricated zeros.
    indices = []
    for d in data:
        ii = np.searchsorted(d.times, times).clip(0, len(d.times)-1)
        left = np.maximum(ii-1, 0)
        ii = np.where(abs(d.times[left]-times) <= abs(d.times[ii]-times), left, ii)
        delta = abs(d.times[ii]-times)
        if tolerance is not None and np.any(delta > tolerance):
            raise ValueError('Variables have mismatched output times beyond tolerance')
        if tolerance is None and np.any(delta > 1e-10):
            warnings.warn('Animation uses nearest native snapshots; set tolerance to limit time mismatches', RuntimeWarning)
        indices.append(ii)
    return data, times, indices, offset


def animate_profiles(run, panels=('rho', 'temperature'), *, window=None, stride=1,
                     postbounce=False, tolerance=None, xlim=None, xscale='linear',
                     title='', interval=50):
    """Animate radial panels for one Run; return FuncAnimation.

    panels: names, dicts, or Panel instances (same as profiles()).
    window: inclusive time interval in seconds; postbounce selects the convention.
    stride: every Nth eligible first-variable frame. tolerance: max time mismatch.
    xlim: km; xscale: Matplotlib scale; interval: playback milliseconds.
    Call save_animation(ani, path, fps=...) to export; retain the returned object.
    """
    panels = _panels(panels)
    data, times, indices, offset = _frames(run, panels, window, stride, postbounce, tolerance)
    fig, primary, mapped = _layout(panels, xlim=xlim, xscale=xscale, title=title)
    lines = []
    for p, ax, d, ii in zip(panels, mapped, data, indices):
        line, = ax.plot([], [], color=p.color, label=_plain_text(p.variable))
        lines.append(line)
        # Fix scales across frames, rather than autoscaling at every update.
        rmin = min(d.radii[i].min() for i in ii) * CM_TO_KM
        rmax = max(d.radii[i].max() for i in ii) * CM_TO_KM
        vals = np.concatenate([d.values[i] * p.factor for i in ii])
        vals = vals[np.isfinite(vals) & ((vals > 0) if p.yscale == 'log' else True)]
        if not vals.size:
            raise ValueError(f'{p.variable}: no valid values for {p.yscale} axis')
        ax.update_datalim([[rmin, vals.min()], [rmax, vals.max()]])
        ax.autoscale_view()
        ax.legend(fontsize='small')
    stamp = fig.suptitle('')
    def update(frame):
        actual = []
        for line, d, ii, p in zip(lines, data, indices, panels):
            i = ii[frame]
            line.set_data(d.radii[i]* CM_TO_KM, d.values[i]*p.factor)
            actual.append(f'{_plain_text(p.variable)}: {d.times[i]-offset:.6g}')
        stamp.set_text(f'{_plain_text(run.label)} | t (s): ' + ', '.join(actual))
        return [*lines, stamp]
    ani = FuncAnimation(fig, update, frames=len(times), interval=interval, blit=False)
    return ani


def _star_setup(run, variable, max_radius, window, stride, postbounce,
                log, vmin, vmax, cmap, resolution):
    if max_radius <= 0 or resolution < 8:
        raise ValueError('max_radius must be positive and resolution >= 8')
    data, times, ii, offset = _frames(run, [Panel(variable)], window, stride, postbounce, None)
    data, ii = data[0], ii[0]
    grid = np.linspace(0, max_radius, resolution)
    # Resample every native radial grid; mask outside its recorded domain.
    images = []
    for i in ii:
        images.append(np.interp(grid, data.radii[i]* CM_TO_KM, data.values[i], left=np.nan, right=np.nan))
    images = np.asarray(images)
    valid = images[np.isfinite(images) & ((images > 0) if log else True)]
    if not valid.size:
        raise ValueError('No valid values inside the requested radius/color domain')
    low = valid.min() if vmin is None else vmin
    high = valid.max() if vmax is None else vmax
    if low == high and vmin is None and vmax is None:
        low, high = (low/1.01, high*1.01) if log else (low-1, high+1)
    if high <= low or (log and low <= 0):
        raise ValueError('Require vmax > vmin (and positive vmin for logarithmic colors)')
    norm = LogNorm(low, high) if log else Normalize(low, high)
    return times-offset, grid, np.ma.masked_invalid(images), norm


def star(run, variable='rho', *, time=None, animate=False, max_radius=100,
         window=None, stride=1, postbounce=False, log=True, vmin=None, vmax=None,
         cmap='inferno', resolution=200, interval=50, label=None, radius_label_color='white'):
    """Polar cross-section: spherically replicated 1D data, not a 2D simulation.

    Unknown central/outer radii are masked. Color normalization stays fixed.
    time selects a static snapshot (seconds); window/stride select animation frames.
    max_radius is km; log/vmin/vmax/cmap set color normalization.
    radius_label_color controls radial tick text (default white).
    Returns (fig, ax), or FuncAnimation when animate=True.
    """
    if not animate:
        d = run.profile(variable)
        offset = run.bounce_time if postbounce else 0
        selected = d.times[-1] if time is None else d.at(time + offset).time
        window = (selected-offset, selected-offset)
    times, grid, images, norm = _star_setup(run, variable, max_radius, window,
                                           stride, postbounce, log, vmin, vmax, cmap, resolution)
    theta = np.linspace(0, 2*np.pi, 129)
    fig, ax = plt.subplots(subplot_kw={'projection': 'polar'}, figsize=(7, 7), layout='constrained')
    ax.grid(False)
    ax.set_xticks([])
    ax.set_ylim(0, max_radius)
    ax.set_ylabel('Radius (km)')
    ax.tick_params(axis='y', colors=radius_label_color)
    def color_image(i):
        a = np.ma.repeat(images[i, :, None], len(theta), axis=1)
        return np.ma.masked_less_equal(a, 0) if log else a
    mesh = ax.pcolormesh(theta, grid, color_image(0), cmap=cmap, norm=norm, shading='nearest')
    fig.colorbar(mesh, ax=ax, shrink=0.7, label=label or LABELS.get(variable, _plain_text(variable)))
    stamp = ax.set_title('')
    def update(i):
        mesh.set_array(color_image(i).ravel())
        stamp.set_text(f'{_plain_text(run.label)} | {_plain_text(variable)} | t={times[i]:.6g} s')
        return mesh, stamp
    update(0)
    if animate:
        return FuncAnimation(fig, update, frames=len(times), interval=interval, blit=False)
    return fig, ax


def series(runs, variable, *, time_column=None, value_column=None, postbounce=False,
           factor=1, ylabel=None, xlim=None, ylim=None, yscale='linear', ax=None):
    """Plot a scalar diagnostic from one/multiple Runs; return (fig, ax).

    variable is a .dat stem. Multi-column tables require value_column.
    time_column defaults to the audited schema (timers: 1; other supported: 0).
    postbounce controls displayed time; native leakage time is handled explicitly.
    factor converts displayed values; pass ax to overlay on an existing axis.
    """
    runs = [runs] if hasattr(runs, 'series') else list(runs)
    if ax is None:
        fig, ax = plt.subplots(layout='constrained')
    else:
        fig = ax.figure
    for run in runs:
        data = run.series(variable, time_column=time_column, value_column=value_column)
        native_postbounce = data.time_reference == 'postbounce'
        shift = 0.0 if native_postbounce == postbounce else (run.bounce_time if native_postbounce else -run.bounce_time)
        ax.plot(data.times + shift, data.values*factor, label=_plain_text(run.label))
    ax.set_xlabel('Time after bounce (s)' if postbounce else 'Simulation time (s)')
    ax.set_ylabel(ylabel or _plain_text(variable))
    ax.set_yscale(yscale)
    if xlim is not None:
        ax.set_xlim(xlim)
    if ylim is not None:
        ax.set_ylim(ylim)
    ax.legend()
    return fig, ax


def quicklook(runs, *, postbounce=False):
    """Compare available central diagnostics across one or multiple Runs.

    Uses the union of recognized files; missing run/diagnostic pairs are skipped
    with a warning. Each run keeps the same color in every panel.
    """
    runs = [runs] if hasattr(runs, 'series') else list(runs)
    if not runs:
        raise ValueError('Provide at least one Run')
    specs = [('rho_c_t', r'Central density (g cm$^{-3}$)', 1, 'log'),
             ('temperature_c_t', 'Central temperature (MeV)', 1, 'linear'),
             ('ye_c_t', 'Central electron fraction', 1, 'linear'),
             ('shock_radius_t', 'Shock radius (km)', CM_TO_KM, 'linear')]
    present = [set(run.available()['series']) for run in runs]
    specs = [s for s in specs if any(s[0] in names for names in present)]
    if not specs:
        raise ValueError('No recognized quicklook diagnostics; use series() for custom files')
    fig, axes = plt.subplots(len(specs), 1, squeeze=False, figsize=(8, 2.8*len(specs)), layout='constrained')
    palette = plt.rcParams['axes.prop_cycle'].by_key()['color']
    for ax, (var, label, factor, scale) in zip(axes[:, 0], specs):
        for i, (run, names) in enumerate(zip(runs, present)):
            if var not in names:
                warnings.warn(f'{run.label}: skipping missing {var}.dat', RuntimeWarning)
                continue
            series(run, var, ax=ax, postbounce=postbounce, factor=factor, ylabel=label, yscale=scale)
            ax.lines[-1].set_color(palette[i % len(palette)])
        ax.legend()
    fig.suptitle(', '.join(_plain_text(run.label) for run in runs))
    return fig, list(axes[:, 0])


def save_animation(animation, path, *, fps=20, dpi=120):
    """GIF uses Pillow; MP4 uses an installed ffmpeg executable."""
    writer = PillowWriter(fps=fps) if str(path).lower().endswith('.gif') else 'ffmpeg'
    kwargs = {'fps': fps} if writer == 'ffmpeg' else {}
    animation.save(path, writer=writer, dpi=dpi, **kwargs)
