#!/usr/bin/env python3
"""MelAgent CDK app. Everything deploys to us-west-2. cdk-nag AwsSolutions pack runs on every synth."""
import os

import aws_cdk as cdk
from cdk_nag import AwsSolutionsChecks

from stacks.agent_stack import DEFAULT_PROFILES, AgentStack
from stacks.api_stack import ApiStack
from stacks.auth_stack import AuthStack
from stacks.data_stack import DataStack
from stacks.obs_stack import ObsStack
from stacks.secrets_stack import SecretsStack

REGION = "us-west-2"

app = cdk.App()
env = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=REGION)

# Context inputs (cdk deploy -c key=value). scripts/deploy.sh passes alert_email from $ALERT_EMAIL.
alert_email = app.node.try_get_context("alert_email") or "alerts@example.com"
profiles = list(DEFAULT_PROFILES)
haiku_profile_id = app.node.try_get_context("haiku_profile_id")
if haiku_profile_id:
    profiles.append(haiku_profile_id)
profiles += list(app.node.try_get_context("extra_inference_profiles") or [])

data = DataStack(app, "MelAgentDataStack", env=env)
auth = AuthStack(app, "MelAgentAuthStack", env=env)
secrets = SecretsStack(app, "MelAgentSecretsStack", env=env)
api = ApiStack(
    app,
    "MelAgentApiStack",
    env=env,
    user_pool=auth.user_pool,
    user_pool_client=auth.client,
    sim_origin=f"https://{data.distribution.distribution_domain_name}",
)
agent = AgentStack(
    app,
    "MelAgentAgentStack",
    env=env,
    table=data.table,
    followup_queue=data.followup_queue,
    artifacts_bucket=data.artifacts_bucket,
    jev_secret=secrets.jev_secret,
    inference_profiles=profiles,
)
obs = ObsStack(app, "MelAgentObsStack", env=env, alert_email=alert_email)

cdk.Aspects.of(app).add(AwsSolutionsChecks(verbose=True))
app.synth()
