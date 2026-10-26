"""Reproducible ALFA benchmark: grouped flights, causal windows, saved models/reports.

The federated runner simulates independent clients in one bounded CPU process.
It does not claim to run the ALFA experiment inside the live 16-agent service cluster.
"""
import argparse
import copy
import hashlib
import json
import os
import time
from pathlib import Path

os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')
import numpy as np
from fedhelm.alfa import LABELS, FEATURES, prepare, group_split, metrics


def summarize_windows(x):
    return np.concatenate([x.mean(1), x.std(1), x.min(1), x.max(1), x[:, -1]-x[:, 0]], axis=1)


def extra_trees(x, y, train, test, output, seed):
    from sklearn.ensemble import ExtraTreesClassifier
    import pickle
    model = ExtraTreesClassifier(n_estimators=300, min_samples_leaf=2,
        max_features=.7, class_weight='balanced', n_jobs=2, random_state=seed)
    features = summarize_windows(x)
    model.fit(features[train], y[train])
    with (output/'model.pkl').open('wb') as stream:
        pickle.dump({'model': model, 'features': FEATURES, 'labels': LABELS,
                     'transform': 'mean/std/min/max/last-minus-first'}, stream)
    return model.predict(features[test]), {'model_kind': 'centralized ExtraTrees baseline',
        'parameters': model.get_params(), 'federated': False}


def federation(x, y, groups, ends, train, test, output, args, seed):
    import torch
    from torch import nn
    torch.set_num_threads(2); torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.project = nn.Linear(x.shape[-1], 32)
            self.position = nn.Parameter(torch.zeros(20, 32))
            self.encoder = nn.TransformerEncoder(nn.TransformerEncoderLayer(32, 4, 128,
                dropout=0., batch_first=True), 6, enable_nested_tensor=False)
            self.norm = nn.LayerNorm(32); self.head = nn.Linear(32, 5)
        def forward(self, values):
            values = self.encoder(self.project(values)+self.position)
            return self.head(self.norm(values.mean(1)))
    # Validation comes only from training flights. Within each class/flight,
    # reserve a tail block and purge overlapping 2-second training windows.
    clients = {}; validation = []
    for group in np.unique(groups[train]):
        local_train, local_val = [], []
        for label in np.unique(y[(groups == group) & train]):
            idx = np.flatnonzero((groups == group) & train & (y == label))
            idx = idx[np.argsort(ends[idx])]
            nv = max(1, round(.2*len(idx)))
            val = idx[-nv:]; fit = idx[ends[idx] < ends[val[0]]-2.]
            local_train.extend(fit.tolist()); local_val.extend(val.tolist())
        if local_train and local_val:
            clients[group] = (np.array(local_train), np.array(local_val))
            validation.extend(local_val)
    if len(clients) < args.clients:
        raise ValueError('Not enough independent training clients')
    fit = np.concatenate([t for t, _ in clients.values()])
    mean = x[fit].mean((0,1)); std = x[fit].std((0,1)).clip(.0001)
    tx = torch.from_numpy(np.clip((x-mean)/std, -10, 10).astype('float32'))
    ty = torch.from_numpy(y.astype('int64'))
    counts = np.bincount(y[fit], minlength=5)[:5]
    # Class weighting is configurable because ALFA has very few independent
    # elevator/rudder flights; the exponent must be selected on validation data.
    class_weights = torch.tensor((counts.sum()/np.maximum(counts, 1))**args.class_weight_power,
                                 dtype=torch.float32)
    class_weights /= class_weights.mean()
    net = Net(); best = copy.deepcopy(net.state_dict()); best_score = -1
    history = []; prior = {}; previous_weights = {}; names = sorted(clients)
    def predict(model, idx):
        model.eval(); result = []
        with torch.no_grad():
            for chunk in range(0, len(idx), 256):
                result.extend(model(tx[idx[chunk:chunk+256]]).argmax(-1).tolist())
        return np.array(result)
    for rnd in range(args.rounds):
        selected = rng.choice(names, args.clients, replace=False).tolist()
        base = torch.nn.utils.parameters_to_vector(net.parameters()).detach().clone()
        updates = []; scores = []; components = []
        for name in selected:
            local = copy.deepcopy(net).train(); tr, va = clients[name]
            optimizer = torch.optim.AdamW(local.parameters(), lr=args.lr)
            for epoch in range(2):
                shuffled = rng.permutation(tr)
                for offset in range(0, len(shuffled), 32):
                    batch = shuffled[offset:offset+32]
                    optimizer.zero_grad()
                    loss = nn.functional.cross_entropy(local(tx[batch]), ty[batch], weight=class_weights)
                    loss.backward(); nn.utils.clip_grad_norm_(local.parameters(), 1.); optimizer.step()
            quality = metrics(y[va], predict(local, va))['macro_f1']
            delta = torch.nn.utils.parameters_to_vector(local.parameters()).detach()-base
            # Actual Top-50% sparsification and blockwise INT8 dequantization.
            indices = delta.abs().topk((delta.numel()+1)//2).indices
            sparse = torch.zeros_like(delta); sparse[indices] = delta[indices]
            for offset in range(0, len(delta), 256):
                block = delta[offset:offset+256]; scale = block.abs().max()/127
                if scale > 0:
                    sparse[offset:offset+256] = (sparse[offset:offset+256]/scale).round().clamp(-127,127)*scale
            hist = np.bincount(y[tr], minlength=5)[:5]; probabilities = hist[hist>0]/hist.sum()
            diversity = float(-(probabilities*np.log(probabilities)).sum()/np.log(5))
            updates.append(sparse)
            components.append({'client': name, 'samples': len(tr), 'diversity': diversity,
                               'validation_f1': quality, 'nonzero': int(torch.count_nonzero(sparse))})
        direction = sum(previous_weights.get(n, 1/len(selected))*d for n, d in zip(selected, updates))
        for c, delta in zip(components, updates):
            name = c['client']; old = prior.get(name, {})
            cosine = float(nn.functional.cosine_similarity(delta[None], direction[None]))
            stability = .6*old.get('stability',cosine)+.4*cosine
            quality = .7*old.get('quality',c['validation_f1'])+.3*c['validation_f1']
            prior[name] = {'stability':stability, 'quality':quality}
            contribution = (c['samples']/max(v['samples'] for v in components))*c['diversity'] if rnd<3 else (
                .4*c['diversity']+.35*quality+.25*(stability+1)/2)
            scores.append(c['samples']*(contribution if args.method=='fedhelm' else 1))
            c.update(quality_ewma=quality, stability_ewma=stability, contribution=contribution)
        weights = np.array(scores); weights = weights/weights.sum() if weights.sum() else np.ones(len(scores))/len(scores)
        previous_weights = dict(zip(selected, weights.tolist()))
        torch.nn.utils.vector_to_parameters(base+sum(float(w)*d for w,d in zip(weights,updates)), net.parameters())
        validation_f1 = metrics(y[validation], predict(net, validation))['macro_f1']
        if validation_f1 > best_score:
            best_score = validation_f1; best = copy.deepcopy(net.state_dict()); best_round = rnd+1
        for component, weight in zip(components, weights): component['weight'] = float(weight)
        history.append({'round':rnd+1, 'validation_f1':validation_f1, 'clients':components})
        (output/'rounds.json').write_text(json.dumps(history, indent=2), encoding='utf-8')
        print(f'{args.method} seed={seed} round={rnd+1}/{args.rounds} validation_F1={validation_f1:.4f}', flush=True)
    net.load_state_dict(best)
    torch.save({'state_dict':best, 'mean':mean.tolist(), 'std':std.tolist(), 'features':FEATURES,
        'labels':LABELS, 'architecture':{'layers':6,'hidden':32,'heads':4,'window':20},
        'selected_round':best_round, 'domain':'alfa-flight-v1'}, output/'model.pt')
    (output/'client-splits.json').write_text(json.dumps({g:{'train':tr.tolist(),'validation':va.tolist()}
        for g,(tr,va) in clients.items()}, indent=2), encoding='utf-8')
    return predict(net, np.flatnonzero(test)), {'federated':True,'clients_per_round':args.clients,
        'rounds':args.rounds,'selected_round':best_round,'validation_macro_f1':best_score,
        'layers':6,'hidden_dimension':32,'memory_probe':'unavailable; validation F1 fallback',
        'memory_fusion':False,'test_used_for_selection':False,'client_transport':'single-process simulation',
        'normalization':'fit windows only','loss':'powered inverse class-frequency weighted cross entropy',
        'class_weight_power':args.class_weight_power}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, default=Path('data/alfa'))
    p.add_argument('--prepared', type=Path, default=Path('data/alfa/windows-v2.npz'))
    p.add_argument('--output', type=Path, default=Path('artifacts/alfa'))
    p.add_argument('--method', choices=['extra-trees','fedavg','fedhelm'], default='fedhelm')
    p.add_argument('--rounds', type=int, default=80); p.add_argument('--clients', type=int, default=12)
    p.add_argument('--repeats', type=int, default=1); p.add_argument('--seed', type=int, default=631)
    p.add_argument('--lr', type=float, default=.0005)
    p.add_argument('--class-weight-power', type=float, default=.5,
                   help='inverse-frequency exponent; tune with validation only (default: 0.5)')
    args = p.parse_args()
    if min(args.rounds,args.clients,args.repeats)<1: p.error('rounds, clients, repeats must be positive')
    if not 0 <= args.class_weight_power <= 2: p.error('--class-weight-power must be in [0, 2]')
    if not args.prepared.exists(): print(json.dumps(prepare(args.data,args.prepared)['label_counts']), flush=True)
    data = np.load(args.prepared, allow_pickle=False)
    x,y,groups,ends,onsets = (data[k] for k in ['x','y','groups','ends','onsets'])
    reports = []
    for repeat in range(args.repeats):
        seed=args.seed+repeat; directory=args.output/args.method/f'seed-{seed}'
        if (directory/'report.json').exists():
            raise FileExistsError(f'{directory} already evaluated; choose a new output directory')
        directory.mkdir(parents=True,exist_ok=True)
        split=group_split(groups,y,seed); train=np.isin(groups,split['train']); test=np.isin(groups,split['test'])
        (directory/'split.json').write_text(json.dumps(split,indent=2),encoding='utf-8')
        start=time.monotonic()
        if args.method=='extra-trees': pred, details=extra_trees(x,y,train,test,directory,seed)
        else: pred, details=federation(x,y,groups,ends,train,test,directory,args,seed)
        result=metrics(y[test],pred); delays=[]; missed=[]
        for group in split['test']:
            selected=groups[test]==group; onset=onsets[test][selected][0]
            if onset<0: continue
            hit=selected & (ends[test]>onset) & (pred!=0)
            if hit.any(): delays.append(float(ends[test][hit].min()-onset))
            else: missed.append(group)
        normal_flights=np.array(['no_failure' in g for g in groups[test]])
        result.update(seed=seed,method=args.method,details=details,labels=LABELS,window_count=int(test.sum()),
            train_flights=len(split['train']),test_flights=len(split['test']),
            normal_flight_false_alarm_rate=float((pred[normal_flights]!=0).mean()) if normal_flights.any() else None,
            detection_delay_seconds={'p50':float(np.percentile(delays,50)) if delays else None,
                'p95':float(np.percentile(delays,95)) if delays else None,'detected':len(delays),'missed_flights':missed,
                'definition':'first nonhealthy prediction after onset; not necessarily correct root cause'},
            compound_evaluation='held out; novel-class identification not implemented',
            elapsed_seconds=time.monotonic()-start,
            dataset_sha256=hashlib.sha256(args.prepared.read_bytes()).hexdigest(),
            claim='measured benchmark; not a reproduction of the manuscript table')
        predictions=[{'sequence':str(g),'end_seconds':float(t),'expected':LABELS[int(a)],'predicted':LABELS[int(b)]}
                     for g,t,a,b in zip(groups[test],ends[test],y[test],pred)]
        (directory/'predictions.json').write_text(json.dumps(predictions,indent=2),encoding='utf-8')
        (directory/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8'); reports.append(result)
        print(f'TEST {args.method}: accuracy={result["accuracy"]:.4f} macro_F1={result["macro_f1"]:.4f}',flush=True)
    summary={'runs':len(reports),'method':args.method,'seeds':[r['seed'] for r in reports],
        **{k:{'mean':float(np.mean([r[k] for r in reports])),'std':float(np.std([r[k] for r in reports]))}
           for k in ['accuracy','macro_f1']}}
    (args.output/args.method/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__=='__main__': main()
