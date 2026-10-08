"""Readers preserve native sampling; files are never modified."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import tempfile
import warnings
import shlex
from .catalog import classify, series_schema
import numpy as np

_TIME = re.compile(r'^\s*"?Time\s*[:=]?\s+([+\-\d.eEdD]+)')

def _float(s):
    return float(s.replace('D', 'E').replace('d', 'e'))

def _readonly(a):
    a = np.asarray(a, dtype=float)
    a.setflags(write=False)
    return a

@dataclass(frozen=True)
class Snapshot:
    time: float
    radius: np.ndarray  # cm
    values: np.ndarray

@dataclass(frozen=True)
class Profile:
    times: np.ndarray
    radii: tuple
    values: tuple

    def at(self, time, *, tolerance=None):
        """Nearest native snapshot; reject requests beyond the recorded range."""
        if not np.isfinite(time) or time < self.times[0] or time > self.times[-1]:
            raise ValueError(f'Time {time} outside [{self.times[0]}, {self.times[-1]}]')
        i = int(np.argmin(abs(self.times - time)))
        if tolerance is not None and abs(self.times[i] - time) > tolerance:
            raise ValueError(f'No snapshot within {tolerance} s of {time}')
        return Snapshot(float(self.times[i]), self.radii[i], self.values[i])

@dataclass(frozen=True)
class Series:
    times: np.ndarray
    values: np.ndarray
    time_reference: str = "simulation"


def read_xg(path, *, radial_zones=None, ghost_zones=None):
    """Read quoted Time blocks, including changing numbers of radial zones.

    Negative-radius inner ghost cells are excluded before physical-grid
    validation; radius zero is retained. Duplicate times use the last complete
    block (restart wins). Empty blocks
    are rejected: a partially written running output should be read later.
    """
    blocks = {}
    t, rows = None, []
    def flush():
        if t is None:
            return
        if not rows:
            raise ValueError(f'{path}: empty/incomplete block at t={t}')
        a = np.asarray(rows)
        if not np.all(np.isfinite(a)):
            raise ValueError(f'{path}: radii and values must be finite')
        # GR1D reflects the inner grid through r=0 for boundary ghost cells.
        # Keep radius/value pairs together; never fold ghosts onto positive r.
        # Trim outer ghosts only when parameters and the complete raw grid agree.
        if radial_zones is not None and ghost_zones is not None:
            n, g = int(radial_zones), int(ghost_zones)
            if g > 0 and len(a) == n + 2*g and np.all(a[:g, 0] < 0) and np.all(a[g:, 0] >= 0):
                a = a[g:g+n]
        a = a[a[:, 0] >= 0]
        if not len(a):
            raise ValueError(f'{path}: no nonnegative-radius physical cells at t={t}')
        if np.any(np.diff(a[:, 0]) <= 0):
            raise ValueError(f'{path}: physical radii must be strictly increasing')
        blocks[t] = (_readonly(a[:, 0]), _readonly(a[:, 1]))
    with open(path) as f:
        for line_number, line in enumerate(f, 1):
            s = line.strip()
            match = _TIME.match(line)
            if match:
                flush()
                t, rows = _float(match[1]), []
                if not np.isfinite(t):
                    raise ValueError(f'{path}:{line_number}: nonfinite time')
            elif not s or s.startswith(('#', '!', '"', '@')):
                continue
            else:
                if t is None:
                    raise ValueError(f'{path}:{line_number}: data before Time header')
                fields = s.split()
                if len(fields) != 2:
                    raise ValueError(f'{path}:{line_number}: expected radius and value')
                try:
                    rows.append(tuple(_float(x) for x in fields))
                except ValueError as e:
                    raise ValueError(f'{path}:{line_number}: invalid numeric row') from e
    flush()
    if not blocks:
        raise ValueError(f'{path}: no profiles found')
    times = sorted(blocks)
    return Profile(_readonly(times), tuple(blocks[t][0] for t in times), tuple(blocks[t][1] for t in times))


def read_dat(path, time_column=0, value_column=1):
    rows = []
    with open(path) as f:
        for n, line in enumerate(f, 1):
            line = line.split('#', 1)[0].strip()
            if not line or line.startswith(('!', '"', '@')):
                continue
            try:
                rows.append([_float(x) for x in line.split()])
            except ValueError as e:
                raise ValueError(f'{path}:{n}: expected numeric table') from e
    try:
        a = np.asarray(rows, dtype=float)
        if a.ndim != 2 or not a.size or min(time_column, value_column) < 0:
            raise ValueError('Empty table or invalid columns')
        t, v = a[:, time_column], a[:, value_column]
    except (ValueError, IndexError) as e:
        raise ValueError(f'{path}: invalid table or column selection') from e
    if not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)):
        raise ValueError(f'{path}: nonfinite selected data')
    # Last duplicate wins, preserving restart policy.
    _, reverse_indices = np.unique(t[::-1], return_index=True)
    indices = len(t) - 1 - reverse_indices
    indices = indices[np.argsort(t[indices])]
    return Series(_readonly(t[indices]), _readonly(v[indices]))


class Run:
    """A local output folder. Construction only lists names, never loads data.

    memory cache is automatic; cache_dir enables source-stat-validated NPZ
    profile caches across sessions. Call clear_cache() to release memory.
    """
    def __init__(self, folder, label=None, *, cache_dir=None, bounce_time=None):
        self.folder = Path(folder).expanduser().resolve()
        if not self.folder.is_dir():
            raise NotADirectoryError(self.folder)
        self.label = label or self.folder.name
        self.cache_dir = Path(cache_dir).expanduser() if cache_dir else None
        self._cache = {}
        self._derived = {}
        self._bounce_time = bounce_time

    @property
    def parameters(self):
        """Read key=value settings, preserving strings and stripping comments."""
        path = self.folder / 'parameters'
        if not path.exists():
            return {}
        result = {}
        for line in path.read_text().splitlines():
            tokens = shlex.split(line, comments=True)
            if '=' in tokens:
                i = tokens.index('=')
                if i == 1 and len(tokens) > 2:
                    result[tokens[0]] = ' '.join(tokens[2:])
            elif '=' in line.split('#', 1)[0]:
                key, value = line.split('#', 1)[0].split('=', 1)
                result[key.strip()] = value.strip().strip('"').strip("'")
        return result

    def available(self):
        """Classify names; unknown/special formats are not offered as time series."""
        categories = {k: [] for k in ('profiles', 'series', 'metadata', 'diagnostics',
                                      'spectra', 'mass_profiles', 'special_profiles',
                                      'binary_or_restart', 'unknown')}
        parameters = self.parameters
        for path in sorted(self.folder.iterdir()):
            if not path.is_file() or path.name.startswith('.'):
                continue
            kind = classify(path.name, parameters)
            categories[kind].append(path.stem if path.suffix in {'.xg', '.dat'} else path.name)
        categories['profiles'] = sorted(set(categories['profiles']) | set(self._derived))
        return categories

    def inspect_files(self):
        """Return filename/category/schema records without loading large arrays."""
        parameters = self.parameters
        return [dict(filename=p.name, category=classify(p.name, parameters),
                     **(series_schema(p.name) if classify(p.name, parameters) in {'series', 'diagnostics'} else {}))
                for p in sorted(self.folder.iterdir()) if p.is_file() and not p.name.startswith('.')]

    @property
    def bounce_metadata(self):
        """Raw finite values in tbounce.dat; only first value is universally time."""
        path = self.folder / 'tbounce.dat'
        values = _readonly([_float(x) for x in path.read_text().split()])
        if not len(values) or not np.all(np.isfinite(values)):
            raise ValueError(f'{path}: invalid bounce metadata')
        return {'time_s': float(values[0]), 'raw_values': values}

    @property
    def bounce_time(self):
        if self._bounce_time is not None:
            return float(self._bounce_time)
        path = self.folder / 'tbounce.dat'
        if not path.exists():
            raise FileNotFoundError('Post-bounce times require tbounce.dat or Run(..., bounce_time=...)')
        return self.bounce_metadata['time_s']

    def clear_cache(self):
        self._cache.clear()

    def _path(self, variable, suffix):
        name = str(variable)
        if Path(name).name != name:
            raise ValueError('Use a filename/stem within this Run folder')
        return self.folder / (name if name.endswith(suffix) else name + suffix)

    def add_profile(self, name, profile):
        """Register an explicitly computed Profile for the same plotting API.

        Recompute and register again if source data or EOS changes. Derived
        profiles are not written to disk or automatically invalidated.
        """
        if not isinstance(profile, Profile) or not len(profile.times):
            raise ValueError('Expected a nonempty Profile')
        if not (len(profile.times) == len(profile.radii) == len(profile.values)):
            raise ValueError('Inconsistent Profile lengths')
        if not np.all(np.isfinite(profile.times)) or np.any(np.diff(profile.times) <= 0):
            raise ValueError('Profile times must be finite and increasing')
        for r, v in zip(profile.radii, profile.values):
            if len(r) != len(v) or not len(r) or not np.all(np.isfinite(r)) or np.any(np.diff(r) <= 0):
                raise ValueError('Invalid radial profile')
        self._derived[name] = profile

    def profile(self, variable):
        if variable in self._derived:
            return self._derived[variable]
        path = self._path(variable, '.xg')
        parameters = self.parameters
        kind = classify(path.name, parameters)
        if kind not in {'profiles', 'unknown'}:
            raise ValueError(f'{path.name} is {kind}, not a supported radius profile.')
        if kind == 'unknown':
            warnings.warn(f'{path.name}: unclassified .xg; assuming two-column radius (cm) data', RuntimeWarning)
        grid = (parameters.get('radial_zones'), parameters.get('ghosts1'))
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size, grid)
        key = ('profile', path)
        if key in self._cache and self._cache[key][0] == stamp:
            return self._cache[key][1]
        cache_path = None
        result = None
        if self.cache_dir:
            token = hashlib.sha256(json.dumps([str(path), *stamp, 'reader-v3-grid-ghosts']).encode()).hexdigest()
            cache_path = self.cache_dir / (token + '.npz')
            if cache_path.exists():
                try:
                    with np.load(cache_path, allow_pickle=False) as f:
                        offsets = f['offsets']
                        radii, values = f['radii'], f['values']
                        result = Profile(_readonly(f['times']),
                            tuple(_readonly(radii[a:b]) for a, b in zip(offsets[:-1], offsets[1:])),
                            tuple(_readonly(values[a:b]) for a, b in zip(offsets[:-1], offsets[1:])))
                except (OSError, ValueError, KeyError):
                    warnings.warn(f'Ignoring invalid cache {cache_path}', RuntimeWarning)
        if result is None:
            result = read_xg(path, radial_zones=grid[0], ghost_zones=grid[1])
            if cache_path:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix='.npz')
                os.close(fd)
                try:
                    np.savez_compressed(tmp, times=result.times,
                        offsets=np.r_[0, np.cumsum([len(r) for r in result.radii])],
                        radii=np.concatenate(result.radii), values=np.concatenate(result.values))
                    os.replace(tmp, cache_path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
        if (path.stat().st_mtime_ns, path.stat().st_size) != stamp[:2]:
            raise RuntimeError(f'{path} changed during loading; retry after output stops changing')
        self._cache[key] = (stamp, result)
        return result

    def series(self, variable, *, time_column=None, value_column=None):
        path = self._path(variable, '.dat')
        kind = classify(path.name, self.parameters)
        if kind not in {'series', 'diagnostics', 'unknown'}:
            raise ValueError(f'{path.name} is {kind}, not a time series; use bounce_metadata/parameters or a dedicated reader')
        schema = series_schema(path.name)
        if kind == 'unknown' and (time_column is None or value_column is None):
            raise ValueError(f'{path.name} is unclassified; provide time_column and value_column explicitly after checking its format')
        if schema['requires_value_column'] and value_column is None:
            raise ValueError(f'{path.name} has multiple diagnostics; select value_column explicitly')
        time_column = schema['time_column'] if time_column is None else time_column
        value_column = 1 if value_column is None else value_column
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
        key = ('series', path, time_column, value_column)
        if key not in self._cache or self._cache[key][0] != stamp:
            raw = read_dat(path, time_column, value_column)
            result = Series(raw.times, raw.values, schema['time_reference'])
            if (path.stat().st_mtime_ns, path.stat().st_size) != stamp:
                raise RuntimeError(f'{path} changed during loading; retry')
            self._cache[key] = (stamp, result)
        return self._cache[key][1]
