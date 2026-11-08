"""Process published aggregate statistics transcribed from Siebers et al. (2024)."""
from pathlib import Path
import pandas as pd

RAW = Path("data/raw")
OUT = Path("data/processed")

def run():
    OUT.mkdir(parents=True, exist_ok=True)
    app = pd.read_csv(RAW / "published_app_usage.csv")
    phone = pd.read_csv(RAW / "published_phone_effects.csv")
    effects = pd.read_csv(RAW / "published_app_effects.csv")
    desc = pd.read_csv(RAW / "published_descriptives.csv")
    app.to_csv(OUT / "app_usage_summary.csv", index=False)
    phone.to_csv(OUT / "phone_effects_summary.csv", index=False)
    effects.to_csv(OUT / "app_effects_summary.csv", index=False)
    desc.to_csv(OUT / "descriptive_summary.csv", index=False)
    # Directional interpretation only; significance follows the article's Bayesian p-values.
    effects["negative_association"] = effects["within_person_beta"] < 0
    effects["paper_significance_p_lt_05"] = effects["bayesian_p"] < 0.05
    effects.to_csv(OUT / "app_effects_interpreted.csv", index=False)
    return app, phone, effects, desc

if __name__ == "__main__":
    a,p,e,d = run()
    print("Saved published aggregate tables to", OUT)
    print("App-category effects:")
    print(e.to_string(index=False))
