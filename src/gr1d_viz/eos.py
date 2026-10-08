"""Optional SRO EOS lookup on explicitly aligned native radial snapshots."""
import numpy as np
from .data import Profile, _readonly

class EOS:
    def __init__(self, paths):
        """One path, a sequence of paths, or {source_name: path}.

        Variables found in exactly one file resolve automatically. If several
        files contain them, pass source= explicitly; files are never merged.
        """
        from pathlib import Path
        if isinstance(paths, (str, Path)):
            paths = {'default': paths}
        elif not isinstance(paths, dict):
            paths = {f'file{i}': path for i, path in enumerate(paths)}
        if not paths:
            raise ValueError('Provide at least one EOS file')
        self.paths = {str(name): Path(path).expanduser().resolve() for name, path in paths.items()}
        self.path = next(iter(self.paths.values())) if len(self.paths) == 1 else None
        self._interpolators = {}

    def available(self):
        """Return dataset names per source without loading thermodynamic arrays."""
        import h5py
        result = {}
        for name, path in self.paths.items():
            with h5py.File(path, 'r') as f:
                result[name] = sorted(f.keys())
        return result

    def interpolator(self, variable, *, source=None):
        import h5py
        from scipy.interpolate import RegularGridInterpolator
        needed = ('Xu', 'Xd', 'Xs') if variable == 'quark_fraction' else (variable,)
        if source is not None and source not in self.paths:
            raise KeyError(f'Unknown EOS source {source!r}; choose from {list(self.paths)}')
        if source is None:
            matches = [name for name, keys in self.available().items() if all(k in keys for k in needed)]
            if len(matches) != 1:
                raise ValueError(f'{variable}: expected one source, found {matches}; pass source= explicitly or supply a file containing {needed}')
            source = matches[0]
        path = self.paths[source]
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        key = (source, variable)
        if key not in self._interpolators or self._interpolators[key][0] != stamp:
            with h5py.File(path, 'r') as f:
                axes = tuple(f[k][:] for k in ('ye', 'logtemp', 'logrho'))
                values = sum(f[k][:] for k in needed) if variable == 'quark_fraction' else f[variable][:]
            if values.shape != tuple(len(a) for a in axes):
                raise ValueError('EOS requires dataset axis order (ye, logtemp, logrho)')
            interp = RegularGridInterpolator(axes, values, bounds_error=False, fill_value=np.nan)
            self._interpolators[key] = (stamp, interp)
        return self._interpolators[key][1]

    def profile(self, run, variable, *, tolerance=1e-8, source=None):
        """Use rho's native grid; reject unmatched times and radial extrapolation.

        Assumes rho in g/cm^3, temperature in MeV, and dimensionless ye.
        Out-of-table or nonpositive rho/T return NaN rather than zero.
        """
        density = run.profile('rho')
        temperature = run.profile('temperature')
        electron = run.profile('ye')
        interp = self.interpolator(variable, source=source)
        result = []
        for t, radius, rho in zip(density.times, density.radii, density.values):
            temp = temperature.at(t, tolerance=tolerance)
            ye = electron.at(t, tolerance=tolerance)
            T = np.interp(radius, temp.radius, temp.values, left=np.nan, right=np.nan)
            Y = np.interp(radius, ye.radius, ye.values, left=np.nan, right=np.nan)
            values = np.full(len(radius), np.nan)
            valid = np.isfinite(T) & np.isfinite(Y) & (T > 0) & (rho > 0)
            points = np.column_stack((Y[valid], np.log10(T[valid]), np.log10(rho[valid])))
            values[valid] = interp(points)
            result.append(_readonly(values))
        return Profile(density.times, density.radii, tuple(result))
