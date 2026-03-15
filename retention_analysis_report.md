# Customer Retention & Churn Analysis Report

## Executive Summary
- Total customers analyzed: 7043
- Overall churn rate: 26.54%
- Avg customer tenure: 32.37 months
- Avg tenure (churned): 17.98 months
- Avg tenure (retained): 37.57 months
- Estimated retention at 12 months: 84.32%
- Estimated retention at 24 months: 78.87%

## Key Churn Drivers (Segment Uplift)
- TenureGroup = 0-3m: churn 56.21% (uplift 111.84%)
- PaymentMethod = Electronic check: churn 45.29% (uplift 70.65%)
- TenureGroup = 4-6m: churn 44.63% (uplift 68.18%)
- Contract = Month-to-month: churn 42.71% (uplift 60.94%)
- InternetService = Fiber optic: churn 41.89% (uplift 57.87%)
- OnlineSecurity = No: churn 41.77% (uplift 57.39%)
- SeniorCitizen = Yes: churn 41.68% (uplift 57.07%)
- TechSupport = No: churn 41.64% (uplift 56.9%)

## Business Recommendations
- Convert high-risk month-to-month users into annual plans through price-lock incentives and loyalty discounts.
- Introduce onboarding + first-90-day save playbooks for early-tenure cohorts where churn concentration is highest.
- Offer proactive support bundles (OnlineSecurity + TechSupport) as retention add-ons for broadband customers.
- Prioritize payment-method nudges away from electronic checks to autopay/card methods linked with lower churn.
- Launch targeted campaigns for high-risk demographic pockets (e.g., senior subscribers lacking support add-ons).

## Notes
- Dataset is a cross-sectional snapshot; exact signup-date cohorts are not available.
- Cohort proxies (tenure bands and service-contract cohorts) are used for retention diagnostics.
