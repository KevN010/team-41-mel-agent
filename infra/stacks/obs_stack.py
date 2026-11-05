from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_budgets as budgets,
    aws_cloudwatch as cw,
)
from constructs import Construct

NAMESPACE = "MelAgent"


def _search(metric: str, stat: str, label: str) -> cw.MathExpression:
    """Dimension-agnostic view of a custom metric (the emitter may add RuleId, ModelId, Verdict...)."""
    return cw.MathExpression(
        expression=f"SEARCH('{NAMESPACE} {metric}', '{stat}', 300)",
        label=label,
        period=Duration.minutes(5),
    )


class ObsStack(Stack):
    """Dashboard, ModelCalls alarm and monthly budget."""

    def __init__(self, scope: Construct, construct_id: str, *, alert_email: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dash = cw.Dashboard(self, "Dashboard", dashboard_name="MelAgent")

        def graph(title: str, left: list, **kw) -> cw.GraphWidget:
            return cw.GraphWidget(title=title, left=left, width=8, height=6, **kw)

        # Aggregate (dimensionless) ModelCalls drives the alarm; emitters must publish it.
        model_calls_1m = cw.Metric(
            namespace=NAMESPACE, metric_name="ModelCalls", statistic="Sum", period=Duration.minutes(1)
        )

        dash.add_widgets(
            graph("Decisions by rule", [_search("DecisionsByRule", "Sum", "")]),
            graph("Model calls (per minute, limit 60)", [model_calls_1m], left_annotations=[cw.HorizontalAnnotation(value=60, label="rate limit")]),
            graph("Model tokens", [_search("ModelTokens", "Sum", "")]),
        )
        dash.add_widgets(
            graph("Judge verdicts", [_search("JudgeVerdicts", "Sum", "")]),
            graph(
                "Latency ms p50 / p95",
                [
                    cw.Metric(namespace=NAMESPACE, metric_name="LatencyMs", statistic="p50", period=Duration.minutes(5), label="p50"),
                    cw.Metric(namespace=NAMESPACE, metric_name="LatencyMs", statistic="p95", period=Duration.minutes(5), label="p95"),
                ],
            ),
            graph("Cost USD", [_search("CostUsd", "Sum", "")]),
        )

        self.alarm = cw.Alarm(
            self,
            "ModelCallsAlarm",
            alarm_name="MelAgent-ModelCalls-over-60-per-minute",
            alarm_description="Process-wide model call rate exceeded the 60/min token bucket.",
            metric=model_calls_1m,
            threshold=60,
            evaluation_periods=1,
            comparison_operator=cw.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
        )

        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="mel-agent-monthly",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=50, unit="USD"),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type="ACTUAL",
                        comparison_operator="GREATER_THAN",
                        threshold=80,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=alert_email)],
                )
            ],
        )

        CfnOutput(self, "DashboardName", value="MelAgent")
