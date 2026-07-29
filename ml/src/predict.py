import argparse
import json

from src.models import delay_risk, eta_prediction

MODEL_PREDICTORS = {
    "eta": eta_prediction.predict,
    "delay": delay_risk.predict,
}


def main():
    parser = argparse.ArgumentParser(description="Run inference with a trained Fleet Optimization ML model")
    parser.add_argument("--model", choices=MODEL_PREDICTORS.keys(), required=True)
    parser.add_argument("--payload", required=True, help="JSON string of feature values")
    args = parser.parse_args()

    payload = json.loads(args.payload)
    result = MODEL_PREDICTORS[args.model](payload)
    print(f"Prediction: {result}")


if __name__ == "__main__":
    main()
