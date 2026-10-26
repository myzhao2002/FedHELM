"""Convert external CSV/JSON into the stable dataset API. No online fault injection."""
import argparse
import csv
import json
from pathlib import Path
from fedhelm.datasets import DatasetImport,Frame,Record
from fedhelm.telemetry import FIELDS


def convert_csv(path,dataset_id,mapping):
    columns=mapping.get('columns',{});labels=mapping.get('labels',{});scales=mapping.get('scales',{})
    grouped={}
    with path.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            def get(key):return row[columns.get(key,key)]
            event=get('event_id');label=labels.get(get('label'),get('label'));split=get('split')
            frame=Frame(**{key:float(get(key))*scales.get(key,1) for key in FIELDS})
            if event not in grouped:grouped[event]={'label':label,'split':split,'series':[]}
            if grouped[event]['label']!=label or grouped[event]['split']!=split:raise ValueError('同一事件标签或分区冲突')
            grouped[event]['series'].append(frame)
    return DatasetImport(dataset_id=dataset_id,source='external',records=[Record(event_id=k,**v) for k,v in grouped.items()])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('input',type=Path);parser.add_argument('--dataset-id',default='external-v1')
    parser.add_argument('--mapping',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--upload',choices=list('abc'));parser.add_argument('--url',default='http://127.0.0.1:15000')
    args=parser.parse_args();mapping=json.loads(args.mapping.read_text(encoding='utf-8')) if args.mapping else {}
    body=convert_csv(args.input,args.dataset_id,mapping) if args.input.suffix.lower()=='.csv' else DatasetImport.model_validate_json(args.input.read_text(encoding='utf-8-sig'))
    args.output.write_text(body.model_dump_json(indent=2),encoding='utf-8')
    print(f'Validated {len(body.records)} events; saved {args.output}')
    if args.upload:
        import httpx
        with httpx.Client(timeout=30,trust_env=False) as client:
            response=client.post(args.url+'/ui/datasets/'+args.upload+'/import',json=body.model_dump());response.raise_for_status()
            print(response.json())


if __name__=='__main__':main()
