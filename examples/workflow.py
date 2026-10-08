"""Edit folder paths, then run, or execute one block at a time in a notebook."""
from gr1d_viz.constants import CM_PER_KM, CM_TO_KM, VELOCITY_TO_C, GRAMS_TO_SOLAR_MASS
from gr1d_viz import Run, Panel, profiles, series, animate_profiles, star, quicklook, save_animation
import matplotlib.pyplot as plt

# Example path and EOS
run = Run('/path/to/GR1D/output/s24', label='s24 B145', cache_dir='.gr1d-cache')
print(run.available())

# Files are read only when requested. Subsequent plots reuse arrays.
fig, axes = profiles(run, [
    Panel('rho', yscale='log', ylim=(1e8, 1e15)),
    Panel('temperature', ylim=(0, 75)),
    Panel('v', factor=VELOCITY_TO_C, ylabel='v/c', ylim=(-.2, .2), twin=True, hlines=(0,)),
], times=[.7, .73], xlim=(0, 100))
fig.savefig('profiles.png', dpi=300)
# Change a displayed plot without reading or reconstructing data:
axes[0].set_xlim(0, 30)
axes[0].set_ylim(1e10, 1e15)
fig.canvas.draw_idle()

# Add another run to compare progenitors or EOS models.
# other = Run('/path/to/other/output', label='s24 LS220')
# fig, ax = series([run, other], 'shock_radius_t', postbounce=True,
#                  factor=CM_TO_KM, ylabel='Shock radius (km)', xlim=(0, 1))

# Known post-run central diagnostics and shock radius (only present files).
# fig, axes = quicklook(run, postbounce=True)
# fig.savefig('quicklook.png', dpi=200)

# Reuse identical panel definitions for static plots and animation.
# ani = animate_profiles(run, [Panel('rho', yscale='log'), Panel('temperature')],
#                        window=(.6, .8), stride=5, xlim=(0, 100), tolerance=1e-6)
# save_animation(ani, 'profiles.gif', fps=20)

# Spherically symmetric cross-section with fixed logarithmic color range.
# fig, ax = star(run, 'rho', time=.73, max_radius=30, log=True,
#                vmin=1e10, vmax=1e15)
# ani = star(run, 'rho', animate=True, window=(.6, .8), stride=5,
#            max_radius=30, log=True, vmin=1e10, vmax=1e15)
# save_animation(ani, 'star.mp4')  # Requires ffmpeg

# Neutrino luminosity: select each column explicitly, reuse one axes.
# fig, ax = series(run, 'M1_flux_lum', value_column=1, ylabel='Luminosity (erg/s)')
# ax.lines[-1].set_label('nu_e')
# series(run, 'M1_flux_lum', value_column=2, ax=ax)
# ax.lines[-1].set_label('anti-nu_e')
# series(run, 'M1_flux_lum', value_column=3, ax=ax)
# ax.lines[-1].set_label('nu_x')
# ax.legend()
# Add a custom inset through Matplotlib, without changing the loader.

# Optional EOS-derived quantities share the plotting API.
# from gr1d_viz.eos import EOS
# eos = EOS('/path/to/sro_eos.h5')
# run.add_profile('quark_fraction', eos.profile(run, 'quark_fraction'))
# run.add_profile('gamma', eos.profile(run, 'gamma'))
# fig, axes = profiles(run, [Panel('rho', yscale='log'),
#                            Panel('quark_fraction', twin=True, ylim=(0, 1))], times=[.73])
plt.show()
