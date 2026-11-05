# KICKOFF (read this one file, then go)

Clock: 5 hours. Region: us-west-2. English first. Jev external. GPT on Bedrock only.

## Minute 0 to 10: make the directory
1. Terminal:
   cd ~/GitHub/team-41
   unzip ~/Downloads/mel-agent-kit.zip      # creates mel-agent/
   cd mel-agent && bash bootstrap.sh         # copies the pack in, inits git, venv
2. Open ~/GitHub/team-41/mel-agent in Claude Code (Projects).
3. Confirm AWS: `aws sts get-caller-identity` and `aws bedrock list-foundation-models --region us-west-2 --query 'modelSummaries[?contains(modelId,`openai`) || contains(modelId,`haiku`)].modelId'`
   Paste that model list into models/candidates.txt. The model-selection agent reads it.

## Minute 10: launch 5 agents at once (they need only the pack)
| Agent | Model | Prompt file |
|---|---|---|
| Wave 0 contracts | Opus | prompts/00-wave0-contracts.md |
| Model selection | Sonnet | prompts/01-model-selection.md |
| CDK skeleton | Sonnet | prompts/02-cdk-skeleton.md |
| Outcome fixtures test | Haiku | prompts/wave1/D2-outcome-fixtures.md |
| Schema proposal | Haiku | prompts/wave1/Z-schema-proposal.md |

How to launch each: new agent, paste the prompt file contents as the task. Each agent works on its own branch named after the file (wave0, model-selection, cdk, d2, z).

## Minute 60: Wave 0 merged -> launch 10 agents at once
Merge wave0 to main first. Then one agent per file in prompts/wave1/ (A, B, C, D, E, F, G, H, I, J, K, L). G is Opus. I is Haiku. The rest Sonnet.
Rule: an agent that finishes early does NOT pick up another task. It reports and stops.

## Minute 150: merge Wave 1 -> launch Wave 2
| Agent | Model | Prompt |
|---|---|---|
| Integration + deploy | Opus | prompts/wave2/integration.md |
| Adversarial review (fresh context) | Opus | prompts/wave2/review.md |
| Evals + evidence bundle | Haiku | prompts/wave2/evals-evidence.md |
| Docs + demo script | Haiku | prompts/wave2/docs-demo.md |

## Minute 225: deployed and traced? Then stretch
Only if the e2e trace exists: prompts/stretch/hindi.md (Sonnet). Otherwise skip.

## Minute 270: freeze
No merges unless a test is red. Run the demo twice. Record the second run.

## If something blocks you
- Bedrock access denied: run scripts/day0_bedrock.py, read the error, enable model access in the console for us-west-2, retry. Fallback model order is in CLAUDE.md.
- Agent edits a file it does not own: revert that file, re-run the agent with "You own only: ..." repeated at the top.
- Wave 0 takes longer than 75 minutes: launch A, B, C, D, H anyway against the draft models.py; they will need a rebase.
