import argparse
import json
import logging
from demandflow.sample import generate
from demandflow.pipeline import run


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sample = sub.add_parser('sample')
    sample.add_argument('--output', default='data/sales.csv')
    sample.add_argument('--end')
    pipeline = sub.add_parser('run')
    pipeline.add_argument('--csv', default='data/sales.csv')
    pipeline.add_argument('--horizon', type=int, default=14)
    pipeline.add_argument('--full', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == 'sample':
        generate(args.output, end=args.end)
    else:
        print(json.dumps(run(args.csv, args.horizon, args.full), indent=2))


if __name__ == '__main__':
    main()
