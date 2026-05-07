"""
MODEL TRAINING SCRIPT
Label qilingan dataset.csv dan model train qiladi.

Ishlatish:
    python train_model.py --dataset dataset.csv --output structure_model.pkl
"""

import argparse
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder


FEATURE_COLS = [
    "height", "rel_height", "x_pos", "y_gap",
    "uppercase_ratio", "digit_ratio", "word_count", "char_count",
    "starts_symbol", "is_numbered", "ends_colon", "confidence"
]


def load_and_validate(path: str):
    df = pd.read_csv(path, encoding="utf-8-sig")

    # Label bo'sh qatorlarni olib tashlash
    df = df[df["label"].notna() & (df["label"].str.strip() != "")]
    df["label"] = df["label"].str.strip().str.lower()

    valid_labels = {"heading1", "heading2", "bullet", "numbered", "paragraph"}
    invalid = set(df["label"].unique()) - valid_labels
    if invalid:
        print(f"Noto'g'ri labellar (o'tkazib yuboriladi): {invalid}")
        df = df[df["label"].isin(valid_labels)]

    print(f"\nDataset yukandi: {len(df)} qator")
    print("Label taqsimoti:")
    for label, count in df["label"].value_counts().items():
        bar = "█" * (count // 10)
        print(f"  {label:12s} {count:4d}  {bar}")

    return df


def train(dataset_path: str, output_path: str):
    df = load_and_validate(dataset_path)

    if len(df) < 50:
        print("\n⚠️  Kamida 50 ta labeled qator kerak!")
        return

    X = df[FEATURE_COLS].fillna(0)
    y = df["label"]

    le = LabelEncoder()
    y_enc = le.fit_transform(y)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
    )

    print(f"\nTrain: {len(X_train)}, Test: {len(X_test)}")
    print("Model train qilinmoqda...")

    model = RandomForestClassifier(
        n_estimators=300,
        max_depth=None,
        min_samples_split=2,
        min_samples_leaf=1,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)

    print("\n" + "="*50)
    print("NATIJALAR:")
    print("="*50)
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # Cross-validation
    cv_scores = cross_val_score(model, X, y_enc, cv=5, scoring="f1_macro")
    print(f"Cross-validation F1 (5-fold): {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # Feature importance
    print("\nFeature importance (yuqoridan pastga):")
    importances = pd.Series(model.feature_importances_, index=FEATURE_COLS)
    for feat, imp in importances.sort_values(ascending=False).items():
        bar = "█" * int(imp * 50)
        print(f"  {feat:20s} {imp:.3f}  {bar}")

    # Saqlash
    joblib.dump({"model": model, "label_encoder": le, "features": FEATURE_COLS}, output_path)
    print(f"\nModel saqlandi: {output_path}")
    print("Backend ichida ishlatish uchun shu faylni app/ papkaga ko'chiring.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="dataset.csv")
    parser.add_argument("--output", default="structure_model.pkl")
    args = parser.parse_args()
    train(args.dataset, args.output)