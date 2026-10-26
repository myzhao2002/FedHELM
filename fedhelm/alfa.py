"""ALFA's sensor domain is deliberately separate from the service-remediation domain.

Only explicitly named physical measurements enter X. Failure messages are labels,
never inputs. Sequence filenames and timestamps are retained solely for auditing.
"""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np

LABELS = ['healthy', 'engine', 'elevator', 'aileron', 'rudder']
TOPICS = {
    'mavros-imu-data': [f'field.{group}.{axis}' for group in
        ('angular_velocity', 'linear_acceleration') for axis in 'xyz'],
    'mavros-rc-out': [f'field.channels{i}' for i in range(6)],
    'mavros-nav_info-roll': ['field.commanded', 'field.measured'],
    'mavros-nav_info-pitch': ['field.commanded', 'field.measured'],
    'mavros-vfr_hud': ['field.groundspeed', 'field.throttle', 'field.climb'],
}
FEATURES = [topic+'/'+column for topic, columns in TOPICS.items() for column in columns]
FEATURES += ['derived/roll_tracking_error', 'derived/pitch_tracking_error']


def read_topic(path, columns):
    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if not set(['%time', *columns]) <= set(reader.fieldnames or []):
            raise ValueError(f'Missing columns: {path.name}')
        rows = [(int(r['%time']), [float(r[c]) for c in columns]) for r in reader]
    if not rows:
        raise ValueError(f'Empty topic: {path.name}')
    rows.sort(key=lambda row: row[0])
    times = np.array([r[0] for r in rows], dtype=np.int64)
    values = np.array([r[1] for r in rows], dtype=np.float32)
    if not np.isfinite(values).all():
        raise ValueError(f'Nonfinite input: {path.name}')
    return times, values


def sequence_label(name):
    if 'no_ground_truth' in name:
        return None
    if 'rudder' in name and 'aileron' in name:
        return 5  # held out as compound, never silently merged into a known class
    if 'no_failure' in name:
        return 0
    return next((i for i, label in enumerate(LABELS) if i and label in name), None)


def prepare(root, output):
    root, output = Path(root), Path(output)
    xs, ys, groups, ends, onsets = [], [], [], [], []
    sequences, omitted, hashes = [], [], {}
    for directory in sorted((root / 'processed').glob('carbonZ_*')):
        label = sequence_label(directory.name)
        if label is None:
            omitted.append({'sequence': directory.name, 'reason': 'no ground truth'})
            continue
        signals = []
        for topic, columns in TOPICS.items():
            file = directory / f'{directory.name}-{topic}.csv'
            times, values = read_topic(file, columns)
            signals.append((times, values))
            hashes[str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
        onset = None
        if label:
            failures = []
            for file in sorted(directory.glob('*-failure_status-*.csv')):
                times, values = read_topic(file, ['field.data'])
                failures.extend(times[values[:, 0] != 0].tolist())
                hashes[str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
            if not failures:
                raise ValueError(f'Fault onset missing: {directory.name}')
            onset = min(failures)
        start = max(t[0] for t, _ in signals)
        stop = min(t[-1] for t, _ in signals)
        # Causal 10 Hz resampling: last observation at or before each grid point.
        grid = np.arange(start, stop+1, 100_000_000, dtype=np.int64)
        columns, ages = [], []
        for times, values in signals:
            idx = np.searchsorted(times, grid, side='right')-1
            columns.append(values[idx]); ages.append(grid-times[idx])
        series = np.concatenate(columns, axis=1)
        # Control tracking residuals expose a stuck/ineffective surface without
        # introducing fault labels or sequence metadata into model inputs.
        series = np.column_stack((series, series[:, 13]-series[:, 12],
                                  series[:, 15]-series[:, 14])).astype(np.float32)
        max_age = np.max(np.array(ages), axis=0)
        n = 0
        for i in range(0, len(grid)-20, 10):
            left, right = grid[i], grid[i]+2_000_000_000
            # Drop boundary-touching and crossing windows, plus stale sensor gaps.
            if onset is not None and left <= onset <= right:
                continue
            if np.max(max_age[i:i+20]) > 1_000_000_000:
                continue
            target = 0 if onset is None or right < onset else label
            xs.append(series[i:i+20]); ys.append(target); groups.append(directory.name)
            ends.append((right-start)/1e9)
            onsets.append((onset-start)/1e9 if onset is not None else -1.)
            n += 1
        sequences.append({'id': directory.name, 'fault_class': label, 'windows': n,
                          'onset_seconds': (onset-start)/1e9 if onset else None})
    if not xs:
        raise ValueError('No ALFA windows; run scripts.download_alfa first')
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, x=np.array(xs), y=np.array(ys), groups=np.array(groups),
                        ends=np.array(ends), onsets=np.array(onsets))
    manifest = {'source': 'https://doi.org/10.1184/R1/12707963', 'labels': LABELS,
        'features': FEATURES, 'window_seconds': 2, 'stride_seconds': 1, 'resample_hz': 10,
        'resampling': 'causal previous observation, maximum age 1 second',
        'sequences': sequences, 'omitted': omitted, 'input_sha256': hashes,
        'label_counts': {str(k): int(sum(np.array(ys) == k)) for k in range(6)}}
    output.with_suffix('.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def group_split(groups, y, seed):
    """Class-stratified complete-sequence 70/30 split; all compound flight held out."""
    rng = np.random.default_rng(seed)
    train, test, novel = [], [], []
    for label in range(6):
        flights = sorted(g for g in np.unique(groups) if int(y[groups == g].max()) == label)
        rng.shuffle(flights)
        if label == 5:
            novel.extend(flights); continue
        if len(flights) < 2:
            raise ValueError(f'Need at least two independent sequences for class {label}')
        n = max(1, min(len(flights)-1, round(len(flights)*.3)))
        test.extend(flights[:n]); train.extend(flights[n:])
    assert not set(train) & set(test)
    return {'train': sorted(train), 'test': sorted(test), 'novel': sorted(novel)}


def metrics(y, predicted):
    from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, classification_report
    return {'accuracy': float(accuracy_score(y, predicted)),
        'macro_f1': float(f1_score(y, predicted, labels=range(5), average='macro', zero_division=0)),
        'confusion_matrix': confusion_matrix(y, predicted, labels=range(5)).tolist(),
        'per_class': classification_report(y, predicted, labels=range(5), target_names=LABELS,
                                           output_dict=True, zero_division=0)}
