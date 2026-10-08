import argparse
from . import Run, Panel, profiles, quicklook, star, animate_profiles, save_animation, configure_style

def main():
    p = argparse.ArgumentParser(description='Plot selected local GR1D output files')
    p.add_argument('folder', help='Directory containing output from a GR1D simulation')
    p.add_argument('--cache-dir', help='Path to directory to store cached files')
    p.add_argument('--postbounce', action='store_true', help='Express times relative to bounce; does not remove pre-bounce data')
    p.add_argument('--bounce-time', type=float, help='Override tbounce.dat with a bounce time in simulation seconds (applies to every selected run)')
    p.add_argument('--latex', action='store_true', help='Use an installed LaTeX renderer')
    p.add_argument('--seaborn', action='store_true', help='Use Matplotlib seaborn paper style')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    q = sub.add_parser('quicklook')
    group = q.add_mutually_exclusive_group()
    group.add_argument('--compare', nargs='+', help='Additional output folders')
    group.add_argument('--progenitors', nargs='+', help='Subfolders under folder, e.g. s14 s24 s28')
    q.add_argument('-o', '--output', required=True, help='Output filename, including extension (e.g. quicklook.png)')
    for mode in ('profiles', 'animate', 'star'):
        q = sub.add_parser(mode)
        q.add_argument('--variables', nargs='+', default=['rho'] if mode == 'star' else ['rho', 'temperature'])
        q.add_argument('--time', type=float)
        if mode == 'star':
            q.add_argument('--radius-label-color', default='white')
        q.add_argument('--max-radius', type=float, default=100)
        q.add_argument('--log', action='store_true')
        q.add_argument('--stride', type=int, default=1)
        q.add_argument('-o', '--output', required=True)
    args = p.parse_args()
    try:
        configure_style(seaborn=args.seaborn, latex=args.latex)
    except RuntimeError as exc:
        p.error(str(exc))
    run = Run(args.folder, cache_dir=args.cache_dir, bounce_time=args.bounce_time)
    if args.command == 'list':
        for kind, names in run.available().items():
            print(f'{kind}: ' + ', '.join(names))
        return
    if args.command == 'quicklook':
        from pathlib import Path
        folders = [Path(args.folder)/name for name in args.progenitors] if args.progenitors else [Path(args.folder), *map(Path, args.compare or [])]
        runs = [Run(path, cache_dir=args.cache_dir, bounce_time=args.bounce_time) for path in folders]
        fig, _ = quicklook(runs, postbounce=args.postbounce)
    elif args.command == 'profiles':
        fig, _ = profiles(run, [Panel(v, yscale='log' if args.log else 'linear') for v in args.variables],
                          times=None if args.time is None else [args.time], postbounce=args.postbounce,
                          xlim=(0, args.max_radius))
    elif args.command == 'star':
        if len(args.variables) != 1:
            p.error('star requires exactly one variable')
        fig, _ = star(run, args.variables[0], time=args.time, postbounce=args.postbounce,
                      max_radius=args.max_radius, log=args.log, radius_label_color=args.radius_label_color)
    else:
        ani = animate_profiles(run, [Panel(v, yscale='log' if args.log else 'linear') for v in args.variables],
                               stride=args.stride, postbounce=args.postbounce, xlim=(0, args.max_radius),
                               window=None if args.time is None else (args.time, float('inf')))
        save_animation(ani, args.output)
        return
    fig.savefig(args.output, dpi=200)

if __name__ == '__main__':
    main()
