"""Explicit plotting style setup for notebooks and the CLI."""
import shutil
import matplotlib.pyplot as plt


def configure_style(*, seaborn=False, latex=False):
    """Apply a global style for subsequent plots.

    seaborn=True uses Matplotlib's bundled seaborn-v0_8-paper style (no seaborn
    dependency). latex=True requires an external TeX installation. Default text
    uses Matplotlib mathtext and does not require LaTeX.
    """
    if latex and shutil.which('latex') is None:
        raise RuntimeError('LaTeX formatting requires a TeX installation with latex on PATH; omit --latex or use latex=False.')
    plt.style.use('seaborn-v0_8-paper' if seaborn else 'default')
    plt.rcParams.update({'text.usetex': latex})
    if latex:
        plt.rcParams['font.family'] = 'serif'
