import argparse

import pandas as pd

from src.models import eta_prediction

MODEL_TRAINERS = {
    "eta": eta_prediction.train,
}


def main():
    parser = argparse.ArgumentParser(description="Train a Fleet Optimization ML model")
    parser.add_argument("--model", choices=MODEL_TRAINERS.keys(), required=True)
    parser.add_argument("--input", required=True, help="Path to input CSV (e.g. data/raw/trips.csv)")
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    result = MODEL_TRAINERS[args.model](df)
    print(f"Trained '{args.model}' model: {result}")


if __name__ == "__main__":
    main()
