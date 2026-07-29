import pandas as pd


def build_eta_features(df: pd.DataFrame) -> pd.DataFrame:
    """Turns raw trip rows into the numeric feature set the ETA model trains on."""
    features = pd.DataFrame()
    features["distance_km"] = df["distance_km"]
    features["num_stops"] = df["num_stops"]
    features["hour_of_day"] = pd.to_datetime(df["scheduled_start"]).dt.hour
    features["day_of_week"] = pd.to_datetime(df["scheduled_start"]).dt.dayofweek
    features["avg_historical_speed_kph"] = df["avg_historical_speed_kph"]
    return features
