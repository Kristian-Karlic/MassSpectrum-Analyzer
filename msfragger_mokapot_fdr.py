"""
Standalone mokapot FDR control on MSFragger .pin files.

Reads one or more .pin files, runs mokapot's semi-supervised learning,
and writes FDR-filtered results (q-values and PEP) to CSV.

Usage:
    python msfragger_mokapot_fdr.py                          # all .pin files in Perc_FDR_1_pct/
    python msfragger_mokapot_fdr.py path/to/file.pin         # single file
    python msfragger_mokapot_fdr.py path/to/dir              # all .pin files in directory (recursive)
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# NumPy 2.0 removed np.float_, mokapot 0.10.0 still uses it
if not hasattr(np, "float_"):
    np.float_ = np.float64

import mokapot
from sklearn.svm import LinearSVC
from sklearn.model_selection import GridSearchCV, KFold


def load_pin(pin_path: Path) -> pd.DataFrame:
    """Load an MSFragger .pin file (tab-delimited)."""
    df = pd.read_csv(pin_path, sep="\t")
    print(f"  Loaded {pin_path.name}: {len(df)} PSMs")
    return df


def run_mokapot_on_pin(df: pd.DataFrame, pin_name: str, output_dir: Path) -> pd.DataFrame:
    """Run mokapot on a PIN-format DataFrame and return results with q-values."""

    # Identify feature columns (everything except metadata)
    metadata_cols = {"SpecId", "Label", "ScanNr", "Peptide", "Proteins"}
    feature_cols = [c for c in df.columns if c not in metadata_cols]

    # Ensure features are numeric
    for col in feature_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    print(f"  Features ({len(feature_cols)}): {feature_cols}")

    # Target/decoy stats
    n_target = (df["Label"] == 1).sum()
    n_decoy = (df["Label"] == -1).sum()
    print(f"  Targets: {n_target} | Decoys: {n_decoy}")

    if n_target == 0 or n_decoy == 0:
        raise ValueError(f"Need both targets and decoys — got {n_target} targets, {n_decoy} decoys")

    # Convert Label: 1 target, -1 decoy → 1/0 for mokapot (bool(-1) == True!)
    df = df.copy()
    df["Label"] = np.where(df["Label"] == 1, 1, 0)

    # Create dataset
    dataset = mokapot.LinearPsmDataset(
        psms=df,
        target_column="Label",
        spectrum_columns=["ScanNr"],
        peptide_column="Peptide",
        protein_column="Proteins",
        feature_columns=feature_cols,
    )

    # Custom SVM with higher max_iter to avoid IRLS convergence warnings
    svm = LinearSVC(dual=False, max_iter=5000, random_state=7)
    param_grid = {"C": [0.1, 1, 10]}
    cv_model = GridSearchCV(
        svm, param_grid=param_grid, refit=False,
        cv=KFold(3, shuffle=True, random_state=42), n_jobs=-1,
    )
    model = mokapot.Model(
        estimator=cv_model, train_fdr=0.01, max_iter=10, rng=42,
    )

    # Run semi-supervised learning
    print("  Running mokapot.brew()...")
    t0 = time.time()
    results, models = mokapot.brew(dataset, model=model, test_fdr=0.01, folds=3, rng=42)
    print(f"  brew() completed in {time.time() - t0:.1f}s")

    # --- Feature weight debug ---
    # After fit(), m.estimator is the trained SVM (replaces the GridSearchCV)
    # m.features has the feature names, m.scaler has the StandardScaler used
    print(f"\n  === Feature Weights (from {len(models)} fold models) ===")
    fold_weights = []
    for i, m in enumerate(models):
        svm = m.estimator
        if hasattr(svm, "coef_"):
            weights = svm.coef_.flatten()
            fold_weights.append(weights)
            print(f"\n  Fold {i+1} weights (sorted by |weight|):")
            for fname, w in sorted(zip(feature_cols, weights), key=lambda x: abs(x[1]), reverse=True):
                print(f"    {fname:>30s}: {w:+.6f}")
        else:
            print(f"  Fold {i+1}: no coef_ found (type: {type(svm).__name__})")

    if fold_weights:
        avg_weights = np.mean(fold_weights, axis=0)
        std_weights = np.std(fold_weights, axis=0) if len(fold_weights) > 1 else np.zeros_like(avg_weights)
        print(f"\n  === Average Feature Weights (across {len(fold_weights)} folds) ===")
        ranked = sorted(zip(feature_cols, avg_weights, std_weights), key=lambda x: abs(x[1]), reverse=True)
        max_abs = max(abs(w) for _, w, _ in ranked) if ranked else 1
        for fname, w, s in ranked:
            bar_len = int(abs(w) / max_abs * 30)
            bar = ("+" if w > 0 else "-") * bar_len
            print(f"    {fname:>30s}: {w:+.6f} ±{s:.6f}  {bar}")

        # Also show scaler stats from last fold for context
        scaler = models[-1].scaler
        if hasattr(scaler, "mean_") and hasattr(scaler, "scale_"):
            print(f"\n  === Feature Scaling (StandardScaler from last fold) ===")
            print(f"    {'Feature':>30s}   {'Mean':>12s}   {'Std':>12s}")
            for fname, mean, scale in zip(feature_cols, scaler.mean_, scaler.scale_):
                print(f"    {fname:>30s}   {mean:>12.4f}   {scale:>12.4f}")
    print()

    # Write results to temp files and read back
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        files = results.to_txt(dest_dir=tmpdir, decoys=True)

        target_psms = None
        decoy_psms = None
        for f in files:
            fname = Path(f).name
            if "psms" in fname:
                file_df = pd.read_csv(f, sep="\t")
                if "decoy" in fname:
                    decoy_psms = file_df
                else:
                    target_psms = file_df

    if target_psms is None:
        raise ValueError("Mokapot produced no target PSM results")

    # Row count integrity checks
    if len(target_psms) != n_target:
        print(f"  WARNING: Target count mismatch: {n_target} input vs {len(target_psms)} output")
    if decoy_psms is not None and len(decoy_psms) != n_decoy:
        print(f"  WARNING: Decoy count mismatch: {n_decoy} input vs {len(decoy_psms)} output")

    psm_dfs = [target_psms]
    if decoy_psms is not None:
        psm_dfs.append(decoy_psms)
    psm_results = pd.concat(psm_dfs, ignore_index=True)

    # FDR summary
    for fdr in [0.01, 0.05, 0.10]:
        count = (psm_results["mokapot q-value"] <= fdr).sum()
        print(f"  PSMs at {fdr*100:.0f}% FDR: {count}")

    # Write PIN file with features used for training
    pin_cols = ["Label", "ScanNr", "Peptide", "Proteins"] + feature_cols
    pin_to_write = df[pin_cols].copy()
    # Convert Label back to 1/-1 format for PIN standard
    pin_to_write["Label"] = np.where(pin_to_write["Label"] == 1, 1, -1)
    pin_file = output_dir / f"{pin_name}_mokapot.pin"
    pin_to_write.to_csv(pin_file, sep="\t", index=False)
    print(f"  PIN file saved: {pin_file}")

    return psm_results


def main():
    # Determine input path(s)
    if len(sys.argv) > 1:
        input_path = Path(sys.argv[1])
        if input_path.is_file():
            pin_files = [input_path]
        elif input_path.is_dir():
            pin_files = sorted(input_path.rglob("*.pin"))
        else:
            print(f"Error: {input_path} not found")
            sys.exit(1)
    else:
        # Default: look in Perc_FDR_1_pct/
        default_dir = Path(__file__).parent / "labile-mouse-paper"
        if not default_dir.exists():
            print(f"Error: no argument given and {default_dir} not found")
            sys.exit(1)
        pin_files = sorted(default_dir.rglob("*.pin"))

    if not pin_files:
        print("No .pin files found")
        sys.exit(1)

    print(f"Found {len(pin_files)} .pin file(s)\n")

    output_dir = Path(__file__).parent / "mokapot_results"
    output_dir.mkdir(exist_ok=True)

    all_results = []

    for pin_path in pin_files:
        print(f"Processing: {pin_path}")
        df = load_pin(pin_path)

        try:
            result = run_mokapot_on_pin(df, pin_path.stem, output_dir)
            result["source_file"] = pin_path.stem
            all_results.append(result)

            # Write per-file result
            out_file = output_dir / f"{pin_path.stem}_mokapot.csv"
            result.to_csv(out_file, index=False)
            print(f"  Saved: {out_file}\n")

        except Exception as e:
            print(f"  FAILED: {e}\n")

    # Write combined results if multiple files
    if len(all_results) > 1:
        combined = pd.concat(all_results, ignore_index=True)
        combined_file = output_dir / "combined_mokapot.csv"
        combined.to_csv(combined_file, index=False)
        print(f"Combined results: {combined_file}")

        # Combined FDR summary
        print("\n=== Combined FDR Summary ===")
        for fdr in [0.01, 0.05, 0.10]:
            count = (combined["mokapot q-value"] <= fdr).sum()
            total = len(combined)
            print(f"  {fdr*100:.0f}% FDR: {count}/{total} ({count/total*100:.1f}%)")


if __name__ == "__main__":
    main()
