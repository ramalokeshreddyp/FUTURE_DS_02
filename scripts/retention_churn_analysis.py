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

        overall_churn = df["ChurnFlag"].mean() * 100
        retention_12m = retention_curve.loc[retention_curve["month"] <= 12, "survival"].tail(1)
        retention_24m = retention_curve.loc[retention_curve["month"] <= 24, "survival"].tail(1)
        retention_12m_val = float(retention_12m.iloc[0] * 100) if len(retention_12m) else np.nan
        retention_24m_val = float(retention_24m.iloc[0] * 100) if len(retention_24m) else np.nan

        total_mrr = float(df["MonthlyCharges"].sum())
        churned_mrr = float(df.loc[df["ChurnFlag"] == 1, "MonthlyCharges"].sum())
        retained_mrr = float(df.loc[df["ChurnFlag"] == 0, "MonthlyCharges"].sum())
        mrr_at_risk_pct = (churned_mrr / total_mrr * 100) if total_mrr else 0.0

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
                table["uplift_pct"] = (table["ChurnFlag"] / baseline - 1) * 100
                for _, row in table.iterrows():
                        risk_rows.append(
                                {
                                        "dimension": col,
                                        "segment": str(row[col]),
                                        "churn_rate": float(row["ChurnFlag"] * 100),
                                        "uplift_pct": float(row["uplift_pct"]),
                                }
                        )

        risk_df = pd.DataFrame(risk_rows).sort_values("uplift_pct", ascending=False)
        top_risk = risk_df.head(8).copy()
        top_risk["label"] = top_risk["dimension"] + " = " + top_risk["segment"]

        overview_fig = make_subplots(
                rows=2,
                cols=2,
                subplot_titles=(
                        "Churn Rate by Contract",
                        "Churn Rate by Tenure Band",
                        "Retention Curve (Kaplan-Meier Estimate)",
                        "Churn Rate by Payment Method",
                ),
                vertical_spacing=0.14,
                horizontal_spacing=0.1,
        )
        overview_fig.add_trace(
                go.Bar(
                        x=contract["Contract"],
                        y=contract["churn_rate"],
                        marker_color=["#A63A50", "#5C80BC", "#2CA58D"],
                        text=contract["churn_rate"].round(1).astype(str) + "%",
                        textposition="outside",
                ),
                row=1,
                col=1,
        )
        overview_fig.add_trace(
                go.Bar(
                        x=tenure["TenureGroup"].astype(str),
                        y=tenure["churn_rate"],
                        marker_color="#E07A5F",
                        text=tenure["churn_rate"].round(1).astype(str) + "%",
                        textposition="outside",
                ),
                row=1,
                col=2,
        )
        overview_fig.add_trace(
                go.Scatter(
                        x=retention_curve["month"],
                        y=retention_curve["survival"] * 100,
                        mode="lines",
                        line=dict(color="#264653", width=4),
                        fill="tozeroy",
                        fillcolor="rgba(38,70,83,0.14)",
                ),
                row=2,
                col=1,
        )
        overview_fig.add_trace(
                go.Bar(
                        x=payment["PaymentMethod"],
                        y=payment["churn_rate"],
                        marker_color="#F4A261",
                        text=payment["churn_rate"].round(1).astype(str) + "%",
                        textposition="outside",
                ),
                row=2,
                col=2,
        )
        overview_fig.update_layout(
                height=840,
                template="plotly_white",
                showlegend=False,
                margin=dict(t=80, l=40, r=20, b=20),
                font=dict(family="Segoe UI, Tahoma, sans-serif", color="#1f2937"),
                paper_bgcolor="rgba(255,255,255,0)",
                plot_bgcolor="rgba(255,255,255,0)",
        )
        overview_fig.update_yaxes(title_text="Churn Rate (%)", row=1, col=1)
        overview_fig.update_yaxes(title_text="Churn Rate (%)", row=1, col=2)
        overview_fig.update_yaxes(title_text="Retention (%)", row=2, col=1, range=[0, 105])
        overview_fig.update_yaxes(title_text="Churn Rate (%)", row=2, col=2)

        heat_df = (
                df.pivot_table(
                        index="Contract",
                        columns="InternetService",
                        values="ChurnFlag",
                        aggfunc="mean",
                        fill_value=0,
                )
                * 100
        ).round(2)
        heatmap_fig = px.imshow(
                heat_df,
                text_auto=True,
                aspect="auto",
                color_continuous_scale="YlOrRd",
                labels=dict(x="Internet Service", y="Contract", color="Churn %"),
        )
        heatmap_fig.update_layout(
                height=420,
                margin=dict(t=35, l=40, r=20, b=30),
                font=dict(family="Segoe UI, Tahoma, sans-serif"),
                paper_bgcolor="rgba(255,255,255,0)",
                plot_bgcolor="rgba(255,255,255,0)",
        )

        risk_fig = go.Figure(
                go.Bar(
                        x=top_risk["uplift_pct"],
                        y=top_risk["label"],
                        orientation="h",
                        marker=dict(
                                color=top_risk["uplift_pct"],
                                colorscale="RdYlGn_r",
                                colorbar=dict(title="Uplift %"),
                        ),
                        text=top_risk["churn_rate"].round(1).astype(str) + "% churn",
                        textposition="outside",
                )
        )
        risk_fig.update_layout(
                height=460,
                xaxis_title="Churn Uplift vs Overall (%)",
                yaxis_title="Risk Segment",
                margin=dict(t=30, l=150, r=20, b=30),
                font=dict(family="Segoe UI, Tahoma, sans-serif"),
                paper_bgcolor="rgba(255,255,255,0)",
                plot_bgcolor="rgba(255,255,255,0)",
        )

        revenue_fig = make_subplots(
                rows=1,
                cols=2,
                specs=[[{"type": "domain"}, {"type": "xy"}]],
                subplot_titles=("MRR Split: Retained vs Churned", "Monthly Charges by Churn Status"),
                horizontal_spacing=0.12,
        )
        revenue_fig.add_trace(
                go.Pie(
                        labels=["Retained MRR", "Churned MRR"],
                        values=[retained_mrr, churned_mrr],
                        hole=0.55,
                        marker=dict(colors=["#2A9D8F", "#E76F51"]),
                        textinfo="percent+label",
                ),
                row=1,
                col=1,
        )
        revenue_fig.add_trace(
                go.Box(
                        x=df["Churn"],
                        y=df["MonthlyCharges"],
                        marker_color="#5C80BC",
                        boxmean=True,
                        name="MonthlyCharges",
                ),
                row=1,
                col=2,
        )
        revenue_fig.update_layout(
                height=430,
                showlegend=False,
                margin=dict(t=60, l=35, r=20, b=20),
                font=dict(family="Segoe UI, Tahoma, sans-serif"),
                paper_bgcolor="rgba(255,255,255,0)",
                plot_bgcolor="rgba(255,255,255,0)",
        )
        revenue_fig.update_yaxes(title_text="Monthly Charges", row=1, col=2)

        service_fig = px.sunburst(
                df,
                path=["Contract", "InternetService", "Churn"],
                color="Churn",
                color_discrete_map={"Yes": "#E76F51", "No": "#2A9D8F"},
        )
        service_fig.update_layout(
                height=470,
                margin=dict(t=20, l=20, r=20, b=20),
                font=dict(family="Segoe UI, Tahoma, sans-serif"),
                paper_bgcolor="rgba(255,255,255,0)",
                plot_bgcolor="rgba(255,255,255,0)",
        )

        dashboard_html = plot(overview_fig, include_plotlyjs="cdn", output_type="div")
        heatmap_html = plot(heatmap_fig, include_plotlyjs=False, output_type="div")
        risk_html = plot(risk_fig, include_plotlyjs=False, output_type="div")
        revenue_html = plot(revenue_fig, include_plotlyjs=False, output_type="div")
        service_html = plot(service_fig, include_plotlyjs=False, output_type="div")

        top_customers = (
                df.groupby("customerID", as_index=False)
                .agg(tenure=("tenure", "max"), total_charges=("TotalCharges", "max"), churn=("Churn", "max"))
                .sort_values("total_charges", ascending=False)
                .head(10)
        )
        top_customers["total_charges"] = top_customers["total_charges"].round(2)

        action_playbook = pd.DataFrame(
                [
                        ["Early-life churn spike", "First 90-day onboarding + proactive CS calls", "0-6 month tenure customers", "Reduce early churn by 15-20%"],
                        ["Month-to-month instability", "Offer annual-plan migration incentives", "Month-to-month contracts", "Improve retention and billing predictability"],
                        ["Support/security gap", "Bundle OnlineSecurity + TechSupport", "Fiber users without add-ons", "Lower risk for high-bill users"],
                        ["Payment friction", "Push card/autopay conversion campaigns", "Electronic check users", "Reduce payment-driven churn"],
                ],
                columns=["Churn Challenge", "Retention Action", "Target Segment", "Expected Impact"],
        )

        html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
    <meta charset=\"UTF-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
    <title>Customer Retention & Churn Executive Dashboard</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Manrope:wght@500;700;800&display=swap');

        :root {{
            --bg: #f3f7fa;
            --bg2: #e6edf5;
            --card: rgba(255, 255, 255, 0.86);
            --ink: #0f172a;
            --muted: #5b6472;
            --line: #d7dee8;
            --accent: #0f766e;
        }}

        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            color: var(--ink);
            background:
                radial-gradient(circle at 10% 20%, rgba(15, 118, 110, 0.11), transparent 32%),
                radial-gradient(circle at 90% 10%, rgba(92, 128, 188, 0.15), transparent 35%),
                linear-gradient(160deg, var(--bg), var(--bg2));
            font-family: "Space Grotesk", "Segoe UI", sans-serif;
        }}

        .container {{ max-width: 1360px; margin: 0 auto; padding: 26px 18px 48px; }}
        .hero {{
            border: 1px solid rgba(15, 23, 42, 0.08);
            background: linear-gradient(135deg, rgba(15,118,110,0.14), rgba(92,128,188,0.14));
            backdrop-filter: blur(6px);
            border-radius: 20px;
            padding: 22px 24px;
            box-shadow: 0 16px 30px rgba(15, 23, 42, 0.08);
            display: grid;
            gap: 8px;
            margin-bottom: 16px;
        }}
        .hero h1 {{ margin: 0; font-family: "Manrope", sans-serif; font-size: clamp(1.5rem, 3vw, 2.2rem); }}
        .hero p {{ margin: 0; color: var(--muted); max-width: 900px; }}

        .meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 6px; }}
        .chip {{
            border: 1px solid rgba(15,23,42,0.08);
            background: rgba(255,255,255,0.7);
            padding: 7px 12px;
            border-radius: 999px;
            font-size: 12px;
            color: #1f2937;
        }}

        .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 14px 0 16px; }}
        .kpi {{
            background: var(--card);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 16px;
            padding: 14px;
            box-shadow: 0 9px 24px rgba(15, 23, 42, 0.07);
        }}
        .kpi .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }}
        .kpi .value {{ font-family: "Manrope", sans-serif; font-weight: 800; font-size: 28px; margin-top: 6px; color: var(--accent); }}
        .kpi .sub {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}

        .panel {{
            background: var(--card);
            border: 1px solid rgba(15,23,42,0.08);
            border-radius: 16px;
            padding: 10px 12px 12px;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.06);
            margin-bottom: 12px;
        }}
        .section-title {{ font-family: "Manrope", sans-serif; margin: 4px 4px 10px; font-size: 1.08rem; }}

        .split {{ display: grid; grid-template-columns: 1.1fr .9fr; gap: 12px; }}
        .split-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}

        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 9px 10px; border-bottom: 1px solid var(--line); text-align: left; font-size: 13px; }}
        th {{ background: rgba(148, 163, 184, 0.12); font-weight: 700; }}
        tr:hover td {{ background: rgba(148,163,184,0.08); }}

        .callouts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }}
        .note {{
            border-radius: 12px;
            padding: 12px;
            background: rgba(255,255,255,0.72);
            border: 1px solid rgba(15,23,42,0.08);
            font-size: 13px;
            color: #1f2937;
        }}

        .footer {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}

        @media (max-width: 1024px) {{
            .split, .split-2 {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class=\"container\">
        <section class=\"hero\">
            <h1>Customer Retention & Churn Executive Dashboard</h1>
            <p>Premium analytics view for churn diagnostics, retention strategy design, and customer lifetime optimization in subscription businesses.</p>
            <div class=\"meta\">
                <span class=\"chip\">Dataset: Telco Customer Churn</span>
                <span class=\"chip\">Records: {len(df):,}</span>
                <span class=\"chip\">Analysis: Cohort Proxy + Survival Curve</span>
                <span class=\"chip\">Last Refresh: Auto-generated by Python pipeline</span>
            </div>
        </section>

        <section class=\"kpi-grid\">
            <div class=\"kpi\"><div class=\"label\">Overall Churn Rate</div><div class=\"value\">{overall_churn:.2f}%</div><div class=\"sub\">Benchmark target: less than 20%</div></div>
            <div class=\"kpi\"><div class=\"label\">Retention at 12 Months</div><div class=\"value\">{retention_12m_val:.2f}%</div><div class=\"sub\">Survival curve estimate</div></div>
            <div class=\"kpi\"><div class=\"label\">Retention at 24 Months</div><div class=\"value\">{retention_24m_val:.2f}%</div><div class=\"sub\">Survival curve estimate</div></div>
            <div class=\"kpi\"><div class=\"label\">MRR at Risk</div><div class=\"value\">{mrr_at_risk_pct:.2f}%</div><div class=\"sub\">${churned_mrr:,.0f} of ${total_mrr:,.0f}</div></div>
            <div class=\"kpi\"><div class=\"label\">Average Tenure</div><div class=\"value\">{df['tenure'].mean():.2f}m</div><div class=\"sub\">Churned: {df.loc[df['ChurnFlag']==1, 'tenure'].mean():.2f}m</div></div>
            <div class=\"kpi\"><div class=\"label\">Highest Risk Segment</div><div class=\"value\">{top_risk.iloc[0]['segment']}</div><div class=\"sub\">{top_risk.iloc[0]['dimension']} | +{top_risk.iloc[0]['uplift_pct']:.1f}% uplift</div></div>
        </section>

        <section class=\"panel\">
            <h2 class=\"section-title\">Core Retention Signals</h2>
            {dashboard_html}
        </section>

        <section class=\"split\">
            <div class=\"panel\">
                <h2 class=\"section-title\">Risk Uplift Ranking</h2>
                {risk_html}
            </div>
            <div class=\"panel\">
                <h2 class=\"section-title\">Contract x Internet Churn Heatmap</h2>
                {heatmap_html}
            </div>
        </section>

        <section class=\"split-2\">
            <div class=\"panel\">
                <h2 class=\"section-title\">Revenue and Pricing Dynamics</h2>
                {revenue_html}
            </div>
            <div class=\"panel\">
                <h2 class=\"section-title\">Service Mix Churn Composition</h2>
                {service_html}
            </div>
        </section>

        <section class=\"split\">
            <div class=\"panel\">
                <h2 class=\"section-title\">Top Customers by Lifetime Billing</h2>
                {top_customers.to_html(index=False)}
            </div>
            <div class=\"panel\">
                <h2 class=\"section-title\">Retention Action Playbook</h2>
                {action_playbook.to_html(index=False)}
            </div>
        </section>

        <section class=\"panel\">
            <h2 class=\"section-title\">Executive Takeaways</h2>
            <div class=\"callouts\">
                <div class=\"note\"><strong>1. Early lifecycle is the critical save window.</strong><br/>Customers in 0-6 month tenure bands have materially higher churn and should receive high-touch onboarding.</div>
                <div class=\"note\"><strong>2. Contract design is a major retention lever.</strong><br/>Month-to-month subscribers churn much more than annual-plan users; migration campaigns are high ROI.</div>
                <div class=\"note\"><strong>3. Service support correlates with lower risk.</strong><br/>Security and support add-ons should be bundled for high-risk broadband segments.</div>
                <div class=\"note\"><strong>4. Billing experience drives churn behavior.</strong><br/>Electronic-check users show elevated churn, indicating payment friction and engagement gaps.</div>
            </div>
            <div class=\"footer\">This dashboard is auto-generated from the pipeline and is designed for stakeholder presentations, retention planning, and portfolio showcase.</div>
        </section>
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
