"""Show what the saved recordings contain and how a model does on them.

Needs only Python and NumPy, so it also runs without ROS and without equipment:

    python scripts/analiza.py                      all recordings and models
    python scripts/analiza.py check P01_ucenje     targets and held force by phase
    python scripts/analiza.py evaluate             newest model on its own recordings
    python scripts/analiza.py predict              forecast of the estimate against holding it
"""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/shimmer_ros2'))

from shimmer_ros2 import grip_report  # noqa: E402


def show_table(header, rows):
    """Print text cells in columns; the first is left-aligned, the others right-aligned."""
    widths = [max(map(len, column)) for column in zip(header, *rows)]
    for row in (header, *rows):
        first, *others = (cell.rjust(width) for cell, width in zip(row, widths))
        print('  '.join([first.strip().ljust(widths[0]), *others]))


def show_warnings(subject, warnings):
    for warning in warnings:
        print(f'! {subject}: {warning}.')


def when(created_utc):
    return created_utc[:16].replace('T', ' ')


def newtons(value):
    return '–' if value is None else f'{value:.1f}'


def percent(share, digits=0):
    return f'{100 * share:.{digits}f} %'


def list_everything(root):
    reports = [grip_report.recording_report(root, metadata['recording_id'])
               for metadata in grip_report.list_recordings(root)]
    models = grip_report.list_models(root)
    if not reports and not models:
        raise ValueError(f'U {root} nema snimki ni modela.')
    print(f'Snimke u {root / "recordings"}')
    show_table(
        ['OZNAKA', 'ID', 'SNIMLJENO (UTC)', 'TRAJANJE', 'MVC [N]', 'VRH [N]', 'STISAK', 'RAZINE'],
        [[r['session'], r['recording_id'][:8], when(r['created_utc']),
          f"{r['duration_sec']:.0f} s", newtons(r['mvc_n']), newtons(r['peak_n']),
          percent(r['grip_share']),
          f"{r['levels_followed']}/{r['levels_total']}" if r['phases'] else 'slobodna']
         for r in reports])
    for report in reports:
        show_warnings(report['session'], grip_report.recording_warnings(report))

    sessions = {r['recording_id']: r['session'] for r in reports}

    def names(recording_ids):
        return ', '.join(sessions.get(i, i[:8]) for i in recording_ids) or '–'

    print(f'\nModeli u {root / "models"}')
    show_table(
        ['ID', 'TRENIRAN (UTC)', 'UČENJE', 'VALIDACIJA', 'RMSE [N]'],
        [[path.stem[:8], when(model['created_utc']), names(model['training_ids']),
          names(model['validation_ids']),
          f"{model['validation_metrics']['rmse_n']:.2f}" if model['validation_metrics'] else '–']
         for path, model in models])
    for path, model in models:
        subject = f'model {path.stem[:8]}'
        if not model['validation_ids']:
            show_warnings(subject, ['nema validacijske snimke'])
        for recording_id in model['validation_ids']:
            if recording_id in sessions:
                evaluation = grip_report.evaluate_model(root, model, recording_id)
                show_warnings(f'{subject}, validacija {evaluation["session"]}',
                              grip_report.evaluation_warnings(evaluation))
    print('\nSTISAK je udio snimke sa silom iznad '
          f'{percent(grip_report.GRIP_THRESHOLD, 1)} MVC, a RAZINE broj praćenih od '
          'zadanih razina stiska.')
    print('Pojedinosti: check OZNAKA za faze snimke, '
          'evaluate [MODEL] za pogrešku po razinama sile.')


def check_recording(root, name):
    report = grip_report.recording_report(root, grip_report.find_recording(root, name))
    mvc = f"MVC {report['mvc_n']:.1f} N" if report['mvc_n'] else 'bez zadanog MVC-a'
    print(f"{report['session']} ({report['recording_id']}), {when(report['created_utc'])} UTC, "
          f"{report['duration_sec']:.0f} s, {mvc}")
    print(f"Vršna sila {report['peak_n']:.1f} N; "
          f"stisak u {percent(report['grip_share'])} snimke.")
    if not report['phases']:
        print('Slobodna snimka bez zadanih razina.')
        return
    print()
    show_table(
        ['FAZA', 'CILJ [% MVC]', 'CILJ [N]', 'DRŽANO [N]', 'RAZLIKA [% MVC]', 'OCJENA'],
        [[str(index), str(phase['target_percent']), newtons(phase['target_n']),
          newtons(phase['held_n']),
          '–' if phase['held_n'] is None else
          f"{round(100 * (phase['held_n'] - phase['target_n']) / report['reference_n']):+d}",
          'praćeno' if phase['followed'] else 'nije praćeno']
         for index, phase in enumerate(report['phases'], 1)])
    print('\nDržana sila je medijan druge polovice faze. Faza je praćena uz razliku do '
          f'{percent(grip_report.PHASE_TOLERANCE)} MVC.')
    show_warnings(report['session'], grip_report.recording_warnings(report))


def evaluate(root, model_name, recording_names):
    path, model = grip_report.find_model(root, model_name)
    recording_ids = ([grip_report.find_recording(root, name) for name in recording_names]
                     or model['training_ids'] + model['validation_ids'])
    delays = ', '.join(map(str, model['emg_delays_ms']))
    print(f'Model {path.stem} ({when(model["created_utc"])} UTC), EMG odgode {delays} ms')
    for recording_id in recording_ids:
        result = grip_report.evaluate_model(root, model, recording_id)
        role = ('učenje' if recording_id in model['training_ids'] else
                'validacija' if recording_id in model['validation_ids'] else 'nova snimka')
        print(f"\n{result['session']} ({role}): {result['rows']} redaka, "
              f"MAE {result['mae_n']:.2f} N, RMSE {result['rmse_n']:.2f} N "
              f"({percent(result['rmse_n'] / result['reference_n'], 1)} referentne sile "
              f"{result['reference_n']:.1f} N)")
        show_table(
            ['RAZINA SILE', 'REDAKA', 'MAE [N]', 'RMSE [N]', 'POMAK [N]'],
            [[level['name'], str(level['rows']),
              *([f"{level['mae_n']:.2f}", f"{level['rmse_n']:.2f}", f"{level['bias_n']:+.2f}"]
                if level['rows'] else ['–', '–', '–'])]
             for level in result['levels']])
        show_warnings(result['session'], grip_report.evaluation_warnings(result))
    print('\nRazine su izmjerena sila kao udio referentne sile. POMAK je srednja razlika '
          'procjene i izmjerene sile; pozitivan znači da model procjenjuje previše.')


def predict(root, model_name, recording_names, horizons_ms):
    path, model = grip_report.find_model(root, model_name)
    recording_ids = ([grip_report.find_recording(root, name) for name in recording_names]
                     or model['training_ids'] + model['validation_ids'])
    print(f'Model {path.stem} ({when(model["created_utc"])} UTC). Prognoza procijenjene sile '
          'Hankel-DMD-om, uz pogrešku zadržavanja zadnje procjene za usporedbu.')
    for recording_id in recording_ids:
        result = grip_report.forecast_report(root, model, recording_id, horizons_ms)
        print()
        print(f"{result['session']}: do {result['against_force'][0]['forecasts']} prognoza "
              'po horizontu, RMSE u N')

        def cells(row):
            if not row['forecasts']:
                return ['–', '–', '–']
            change = row['forecast_rmse_n'] / row['hold_rmse_n'] - 1
            return [f"{row['forecast_rmse_n']:.2f}", f"{row['hold_rmse_n']:.2f}",
                    f'{100 * change:+.0f} %']

        show_table(
            ['HORIZONT', 'PROGNOZA', 'ZADRŽAVANJE', 'RAZLIKA',
             'PROGNOZA*', 'ZADRŽAVANJE*', 'RAZLIKA*'],
            [[f"{own['horizon_ms']} ms", *cells(own), *cells(measured)]
             for own, measured in zip(result['against_estimate'], result['against_force'])])
        show_warnings(result['session'], grip_report.evaluation_warnings(result))
    print()
    print('Stupci bez zvjezdice mjere prognozu prema kasnijoj procjeni, a stupci sa zvjezdicom '
          'prema izmjerenoj sili, gdje ulazi i pogreška same procjene. Negativna RAZLIKA znači '
          'da je prognoza bolja od zadržavanja zadnje procjene.')


def main(arguments=None):
    parser = argparse.ArgumentParser(
        description='Pregled snimki i modela sile stiska; radi bez ROS-a i opreme.')
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'grip_data',
                        help='Mapa sa snimkama i modelima (zadano grip_data).')
    actions = parser.add_subparsers(dest='action', metavar='list|check|evaluate|predict')
    actions.add_parser('list', help='Sve snimke i modeli (zadano).')
    check = actions.add_parser('check', help='Ciljevi i držana sila po fazama snimke.')
    check.add_argument('recording', metavar='SNIMKA', help='Oznaka sesije ili ID snimke.')
    model = actions.add_parser('evaluate', help='Pogreška modela po razinama sile.')
    model.add_argument('model', nargs='?', metavar='MODEL',
                       help='Putanja ili ID modela (zadano: najnoviji).')
    model.add_argument('--recordings', nargs='+', default=[], metavar='SNIMKA',
                       help='Snimke za provjeru (zadano: snimke iz modela).')
    forecast = actions.add_parser(
        'predict', help='Prognoza procjene u usporedbi sa zadržavanjem zadnje vrijednosti.')
    forecast.add_argument('model', nargs='?', metavar='MODEL',
                          help='Putanja ili ID modela (zadano: najnoviji).')
    forecast.add_argument('--recordings', nargs='+', default=[], metavar='SNIMKA',
                          help='Snimke za provjeru (zadano: snimke iz modela).')
    forecast.add_argument('--horizons', nargs='+', type=int, metavar='MS',
                          default=list(grip_report.HORIZONS_MS),
                          help='Horizonti prognoze u ms (zadano 100 250 500).')
    args = parser.parse_args(arguments)
    if args.action == 'predict' and not all(0 < horizon <= 2000 for horizon in args.horizons):
        parser.error('--horizons moraju biti između 1 i 2000 ms.')
    root = args.data_dir.expanduser().resolve()
    try:
        if args.action == 'check':
            check_recording(root, args.recording)
        elif args.action == 'evaluate':
            evaluate(root, args.model, args.recordings)
        elif args.action == 'predict':
            predict(root, args.model, args.recordings, args.horizons)
        else:
            list_everything(root)
    except KeyError as error:
        print(f'GREŠKA: u snimci ili modelu nedostaje polje {error}.')
        return 1
    except (ValueError, OSError) as error:
        print(f'GREŠKA: {error}')
        return 1
    return 0


if __name__ == '__main__':
    # Croatian letters must also print where the default encoding lacks them,
    # such as redirected output on Windows.
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
