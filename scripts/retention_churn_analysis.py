import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import seaborn as sns
from plotly.offline import plot
from plotly.subplots import make_subplots


sns.set_theme(style="whitegrid")


def kaplan_meier_curve(durations: pd.Series, events: pd.Series) -> pd.DataFrame:
    """Compute a simple Kaplan-Meier survival estimate."""
    durations = durations.astype(int)
    events = events.astype(int)

    event_table = (
        pd.DataFrame({"duration": durations, "event": events})
        .groupby("duration", as_index=False)
        .agg(events=("event", "sum"), total=("event", "count"))
        .sort_values("duration")
    )

    n = len(durations)
    at_risk = n
    survival = 1.0
    rows = [{"month": 0, "survival": 1.0, "at_risk": n, "events": 0}]

    for _, row in event_table.iterrows():
        d = int(row["events"])
        if at_risk > 0:
            survival *= (1 - d / at_risk)
        rows.append(
            {
                "month": int(row["duration"]),
                "survival": float(survival),
                "at_risk": int(at_risk),
                "events": d,
            }
        )
        at_risk -= int(row["total"])

    return pd.DataFrame(rows)


def load_and_clean_data(input_path: Path) -> pd.DataFrame:
    df = pd.read_csv(input_path)

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()

    df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")
    df["MonthlyCharges"] = pd.to_numeric(df["MonthlyCharges"], errors="coerce")
    df["tenure"] = pd.to_numeric(df["tenure"], errors="coerce")

    # If total charges is missing for brand-new accounts, backfill with monthly*tenure.
    df["TotalCharges"] = df["TotalCharges"].fillna(df["MonthlyCharges"] * df["tenure"])

    df["ChurnFlag"] = (df["Churn"] == "Yes").astype(int)
    df["SeniorCitizen"] = df["SeniorCitizen"].map({0: "No", 1: "Yes"})

    tenure_bins = [-0.1, 3, 6, 12, 24, 48, 72]
    tenure_labels = ["0-3m", "4-6m", "7-12m", "13-24m", "25-48m", "49-72m"]
    df["TenureGroup"] = pd.cut(df["tenure"], bins=tenure_bins, labels=tenure_labels)

    charge_bins = [0, 35, 70, 1000]
    charge_labels = ["Low", "Mid", "High"]
    df["MonthlyChargeBand"] = pd.cut(
        df["MonthlyCharges"], bins=charge_bins, labels=charge_labels, include_lowest=True
    )

    df["CLVProxy"] = df["MonthlyCharges"] * df["tenure"]

    return df


def metric_table(df: pd.DataFrame, col: str) -> pd.DataFrame:
    out = (
        df.groupby(col, dropna=False, observed=False)
        .agg(
            customers=("customerID", "count"),
            churn_rate=("ChurnFlag", "mean"),
            avg_tenure=("tenure", "mean"),
            avg_monthly_charges=("MonthlyCharges", "mean"),
        )
        .reset_index()
        .sort_values("churn_rate", ascending=False)
    )
    out["churn_rate"] = (out["churn_rate"] * 100).round(2)
    out["avg_tenure"] = out["avg_tenure"].round(2)
    out["avg_monthly_charges"] = out["avg_monthly_charges"].round(2)
    return out


def draw_static_figures(df: pd.DataFrame, out_dir: Path, retention_curve: pd.DataFrame) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    contract_rates = metric_table(df, "Contract")
    plt.figure(figsize=(8, 5))
    sns.barplot(data=contract_rates, x="Contract", y="churn_rate", hue="Contract", dodge=False)
    plt.title("Churn Rate by Contract Type")
    plt.ylabel("Churn Rate (%)")
    plt.xlabel("")
    plt.xticks(rotation=12)
    plt.tight_layout()
    plt.savefig(out_dir / "churn_by_contract.png", dpi=150)
    plt.close()

    tenure_rates = metric_table(df, "TenureGroup")
    plt.figure(figsize=(9, 5))
    sns.barplot(data=tenure_rates, x="TenureGroup", y="churn_rate", hue="TenureGroup", dodge=False)
    plt.title("Churn Rate by Tenure Group")
    plt.ylabel("Churn Rate (%)")
    plt.xlabel("Tenure Group")
    plt.tight_layout()
    plt.savefig(out_dir / "churn_by_tenure_group.png", dpi=150)
    plt.close()

    cohort_heatmap = (
        df.pivot_table(
            index="Contract",
            columns="InternetService",
            values="ChurnFlag",
            aggfunc="mean",
            fill_value=0,
        )
        * 100
    )
    plt.figure(figsize=(8, 5))
    sns.heatmap(cohort_heatmap, annot=True, fmt=".1f", cmap="YlOrRd")
    plt.title("Churn % by Contract x Internet Service")
    plt.tight_layout()
    plt.savefig(out_dir / "churn_heatmap_contract_internet.png", dpi=150)
    plt.close()

    plt.figure(figsize=(9, 5))
    sns.lineplot(data=retention_curve, x="month", y="survival")
    plt.title("Estimated Retention Curve (Kaplan-Meier)")
    plt.ylabel("Retention Probability")
    plt.xlabel("Tenure Month")
    plt.ylim(0, 1.05)
    plt.tight_layout()
    plt.savefig(out_dir / "retention_curve.png", dpi=150)
    plt.close()


def build_interactive_dashboard(
    df: pd.DataFrame,
    retention_curve: pd.DataFrame,
    output_file: Path,
) -> None:
    contract = metric_table(df, "Contract")
    tenure = metric_table(df, "TenureGroup").sort_values("TenureGroup")
    payment = metric_table(df, "PaymentMethod")

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Churn Rate by Contract",
            "Churn Rate by Tenure Group",
            "Retention Curve (Kaplan-Meier)",
            "Churn Rate by Payment Method",
        ),
    )

    fig.add_trace(
        go.Bar(x=contract["Contract"], y=contract["churn_rate"], marker_color="#E76F51"),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=tenure["TenureGroup"].astype(str), y=tenure["churn_rate"], marker_color="#2A9D8F"),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Scatter(x=retention_curve["month"], y=retention_curve["survival"], mode="lines", line=dict(color="#1D3557", width=3)),
        row=2,
        col=1,
    )
    fig.add_trace(
        go.Bar(x=payment["PaymentMethod"], y=payment["churn_rate"], marker_color="#F4A261"),
        row=2,
        col=2,
    )

    fig.update_layout(
        height=840,
        width=1280,
        title_text="Customer Retention & Churn Dashboard",
        template="plotly_white",
        showlegend=False,
    )
    fig.update_yaxes(title_text="Churn Rate (%)", row=1, col=1)
    fig.update_yaxes(title_text="Churn Rate (%)", row=1, col=2)
    fig.update_yaxes(title_text="Retention Probability", row=2, col=1)
    fig.update_yaxes(title_text="Churn Rate (%)", row=2, col=2)

    dashboard_html = plot(fig, include_plotlyjs="cdn", output_type="div")

    top5 = (
        df.groupby("customerID", as_index=False)
        .agg(tenure=("tenure", "max"), total_charges=("TotalCharges", "max"), churn=("Churn", "max"))
        .sort_values("total_charges", ascending=False)
        .head(5)
    )

    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Customer Retention & Churn Dashboard</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --card: #ffffff;
      --text: #1f2937;
      --muted: #6b7280;
      --accent: #2a9d8f;
    }}
    body {{ font-family: Segoe UI, Tahoma, sans-serif; margin: 0; background: var(--bg); color: var(--text); }}
    .container {{ max-width: 1300px; margin: 24px auto; padding: 0 16px; }}
    .hero {{ background: linear-gradient(120deg, #d8f3dc, #bee1e6); border-radius: 18px; padding: 20px 24px; margin-bottom: 16px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 16px; }}
    .card {{ background: var(--card); border-radius: 12px; padding: 14px; box-shadow: 0 6px 18px rgba(17,24,39,.08); }}
    .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .value {{ font-size: 24px; font-weight: 700; color: var(--accent); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 12px; overflow: hidden; }}
    th, td {{ padding: 10px; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 14px; }}
    th {{ background: #f0f4f8; }}
  </style>
</head>
<body>
  <div class=\"container\">
    <div class=\"hero\">
      <h1>Customer Retention & Churn Analysis</h1>
      <p>Interactive decision dashboard for subscription retention strategy.</p>
    </div>
    {dashboard_html}
    <h2>Top Customers by Lifetime Billing</h2>
    {top5.to_html(index=False)}
  </div>
</body>
</html>
"""

    output_file.write_text(html, encoding="utf-8")


def create_summary(df: pd.DataFrame, retention_curve: pd.DataFrame) -> dict:
    overall_churn = round(df["ChurnFlag"].mean() * 100, 2)
    avg_tenure = round(df["tenure"].mean(), 2)
    avg_tenure_churned = round(df[df["ChurnFlag"] == 1]["tenure"].mean(), 2)
    avg_tenure_retained = round(df[df["ChurnFlag"] == 0]["tenure"].mean(), 2)

    monthly_rev = df["MonthlyCharges"].sum()
    retained_mrr = df.loc[df["ChurnFlag"] == 0, "MonthlyCharges"].sum()
    churned_mrr = df.loc[df["ChurnFlag"] == 1, "MonthlyCharges"].sum()

    retention_12m = retention_curve.loc[retention_curve["month"] <= 12, "survival"].tail(1)
    retention_24m = retention_curve.loc[retention_curve["month"] <= 24, "survival"].tail(1)

    risk_dims = [
        "Contract",
        "PaymentMethod",
        "InternetService",
        "OnlineSecurity",
        "TechSupport",
        "PaperlessBilling",
        "SeniorCitizen",
        "TenureGroup",
    ]

    risk_rows = []
    baseline = df["ChurnFlag"].mean()
    for col in risk_dims:
        table = (
            df.groupby(col, dropna=False, observed=False)["ChurnFlag"]
            .mean()
            .reset_index()
        )
        table["uplift"] = table["ChurnFlag"] / baseline - 1
        for _, row in table.iterrows():
            risk_rows.append(
                {
                    "dimension": col,
                    "segment": str(row[col]),
                    "churn_rate": round(float(row["ChurnFlag"]) * 100, 2),
                    "uplift_vs_overall_pct": round(float(row["uplift"]) * 100, 2),
                }
            )

    risk_df = pd.DataFrame(risk_rows).sort_values("uplift_vs_overall_pct", ascending=False)

    top_risk = risk_df.head(10).to_dict(orient="records")

    summary = {
        "overall": {
            "customers": int(len(df)),
            "churn_rate_pct": overall_churn,
            "avg_tenure_months": avg_tenure,
            "avg_tenure_churned_months": avg_tenure_churned,
            "avg_tenure_retained_months": avg_tenure_retained,
            "total_mrr": round(float(monthly_rev), 2),
            "retained_mrr": round(float(retained_mrr), 2),
            "churned_mrr": round(float(churned_mrr), 2),
            "retention_12m_est": round(float(retention_12m.iloc[0]) * 100, 2) if len(retention_12m) else None,
            "retention_24m_est": round(float(retention_24m.iloc[0]) * 100, 2) if len(retention_24m) else None,
        },
        "top_risk_segments": top_risk,
    }

    return summary


def write_markdown_report(summary: dict, out_path: Path) -> None:
    top_lines = []
    for r in summary["top_risk_segments"][:8]:
        top_lines.append(
            f"- {r['dimension']} = {r['segment']}: churn {r['churn_rate']}% (uplift {r['uplift_vs_overall_pct']}%)"
        )

    md = f"""# Customer Retention & Churn Analysis Report

## Executive Summary
- Total customers analyzed: {summary['overall']['customers']}
- Overall churn rate: {summary['overall']['churn_rate_pct']}%
- Avg customer tenure: {summary['overall']['avg_tenure_months']} months
- Avg tenure (churned): {summary['overall']['avg_tenure_churned_months']} months
- Avg tenure (retained): {summary['overall']['avg_tenure_retained_months']} months
- Estimated retention at 12 months: {summary['overall']['retention_12m_est']}%
- Estimated retention at 24 months: {summary['overall']['retention_24m_est']}%

## Key Churn Drivers (Segment Uplift)
{chr(10).join(top_lines)}

## Business Recommendations
- Convert high-risk month-to-month users into annual plans through price-lock incentives and loyalty discounts.
- Introduce onboarding + first-90-day save playbooks for early-tenure cohorts where churn concentration is highest.
- Offer proactive support bundles (OnlineSecurity + TechSupport) as retention add-ons for broadband customers.
- Prioritize payment-method nudges away from electronic checks to autopay/card methods linked with lower churn.
- Launch targeted campaigns for high-risk demographic pockets (e.g., senior subscribers lacking support add-ons).

## Notes
- Dataset is a cross-sectional snapshot; exact signup-date cohorts are not available.
- Cohort proxies (tenure bands and service-contract cohorts) are used for retention diagnostics.
"""

    out_path.write_text(md, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Customer Retention & Churn Analysis")
    parser.add_argument(
        "--input",
        default="data/raw/telco_customer_churn.csv",
        help="Path to the input churn dataset CSV",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for all output artifacts",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"

    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    df = load_and_clean_data(input_path)

    retention_curve = kaplan_meier_curve(df["tenure"], df["ChurnFlag"])

    summary = create_summary(df, retention_curve)

    metric_cols = [
        "Contract",
        "PaymentMethod",
        "InternetService",
        "TenureGroup",
        "SeniorCitizen",
        "OnlineSecurity",
        "TechSupport",
    ]

    for col in metric_cols:
        metric_table(df, col).to_csv(tables_dir / f"churn_by_{col.lower()}.csv", index=False)

    retention_curve.to_csv(tables_dir / "retention_curve.csv", index=False)
    df.to_csv(tables_dir / "cleaned_dataset.csv", index=False)

    draw_static_figures(df, figures_dir, retention_curve)
    build_interactive_dashboard(df, retention_curve, output_dir / "retention_dashboard.html")

    with (output_dir / "summary_metrics.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    write_markdown_report(summary, output_dir / "retention_analysis_report.md")

    print("Analysis complete. Outputs generated in:", output_dir.resolve())


if __name__ == "__main__":
    main()
