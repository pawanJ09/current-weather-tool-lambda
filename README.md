# current-weather-tool-lambda

Deterministic **tool** in the Agentic Weather App (Style 3: Bedrock
AgentCore). A plain Lambda function that fetches current weather
conditions from [Open-Meteo](https://open-meteo.com/) for a given
latitude/longitude. No AI, no reasoning, no loop -- it's registered as an
**AWS Lambda target behind an AgentCore Gateway**, and called by the
Orchestrator Runtime's MCP client through that Gateway.

Runtime: **Python 3.13** · Dependencies: **none** (standard library only)

## Why no `requests` library

This handler uses `urllib` from the standard library instead of
`requests`. Functionally identical for a single GET call, and it means
the deployment package is just `handler.py` zipped up -- no dependency
layer, no `pip install -t`, no vendoring step in CI.

## Why the response has no `statusCode`/`body` envelope

This is built fresh for Style 3, not adapted from a Bedrock Agent Action
Group handler. AgentCore Gateway maps a Lambda target's return value
straight back to the MCP tool result -- there's no HTTP proxy integration
involved, so the handler just returns the weather dict directly (or
`{"error": "..."}` on failure). See `schema/gateway-tool-schema.json` for
the registered contract.

## Repo layout

```
src/handler.py                Lambda handler + Open-Meteo client
tests/test_handler.py         Unit tests (mocked HTTP, no real network calls)
events/                       Sample invocation payloads + a reference-only
                               sample of the Gateway's context object shape
schema/gateway-tool-schema.json   AgentCore Gateway ToolDefinition (input/output schema)
iam/                          Trust policy, execution-role policy, and a note
                               on the Gateway invoke permission (deferred --
                               see iam/GATEWAY-PERMISSION.md)
.github/workflows/            CI (lint+test+coverage) and Deploy (build, deploy, smoke-test)
Makefile                      make check / make build -- see below
```

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
make install
make check    # ruff format + ruff check + pytest --cov (90% floor)
```

Or run the pieces individually: `make format`, `make lint`, `make test`.

## Manual test (no AWS needed)

```bash
python3 -c "
from src.handler import lambda_handler
import json
print(lambda_handler(json.load(open('events/sample_event_gateway.json')), None))
"
```

This makes a real call to Open-Meteo (no API key required) and prints
current conditions for New York City. Passing `None` as the context is
fine locally -- the handler only reads `context.client_context` to log
the Gateway-assigned tool name, and falls back cleanly when it's absent.

## Building the deployment package

```bash
make build
```

Produces `function.zip` containing just `handler.py` at the zip root.
This is the exact artifact the `deploy` workflow builds and ships;
running it locally lets you inspect it before trusting CI.

## Configuring the project

Nothing to configure by hand to run this Lambda standalone -- it takes no
environment variables and calls a free, keyless public API. The only
configuration step is wiring it up as a Gateway target once the Gateway
itself exists (Step 4 of the overall build, a separate repo/component):

1. Deploy this Lambda (push to `main`, or run the `Deploy` workflow manually).
2. Register it as a Lambda target on the AgentCore Gateway, pasting in
   `schema/gateway-tool-schema.json` as the tool definition.
3. Grant the Gateway permission to invoke this function -- see
   `iam/GATEWAY-PERMISSION.md` for the exact command and why it isn't
   automated in this repo's `deploy.yml`.

## AWS setup: fully automatic, first run included

The deploy workflow bootstraps the execution role and function itself --
no manual `aws iam create-role` / `aws lambda create-function` step.

On the **first** push to `main`, the `deploy` job:

1. Checks whether `current-weather-tool-lambda-role` exists
   (`aws iam get-role`). If not, creates it from `iam/trust-policy.json`
   and attaches `iam/execution-role-policy.json` (CloudWatch Logs only --
   outbound HTTPS to Open-Meteo needs no IAM grant), then pauses ~10s for
   IAM propagation.
2. Checks whether the `current-weather-tool-lambda` function exists
   (`aws lambda get-function`). If not, calls `create-function` with that
   role's ARN -- retrying a few times with backoff, since a brand-new IAM
   role can take a little longer than 10s to become assumable by Lambda.
3. Smoke-tests the live function with `events/sample_event_gateway.json`
   and fails the deploy if the response doesn't contain `temperature_f`.

On every **subsequent** push, both checks find existing resources and the
job just calls `update-function-code` instead.

**Not automated here, by design:** the Gateway resource-based invoke
permission (`aws lambda add-permission ... --principal
bedrock-agentcore.amazonaws.com`). That requires the Gateway target's ARN,
which doesn't exist until the Gateway itself is built -- see
`iam/GATEWAY-PERMISSION.md`.

## GitHub Actions setup

- **`ci.yml`** -- lint (`ruff check`), format check (`ruff format --check`),
  tests with a 90% coverage floor. Runs on PRs, non-`main` pushes, and as
  a reusable `workflow_call` from `deploy.yml`.
- **`deploy.yml`** -- on push to `main` (or manual dispatch): reruns CI as
  a gate, builds `function.zip`, creates-or-updates the execution role and
  function, then invokes the **live deployed function** and checks the
  response.

### Required repo secret

| Secret | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | ARN of an IAM role GitHub assumes via OIDC (trust policy scoped to this repo, permissions covering `current-weather-tool-lambda` and `current-weather-tool-lambda-role`) |

Minimum permissions policy for that OIDC role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RoleBootstrap",
      "Effect": "Allow",
      "Action": ["iam:GetRole", "iam:CreateRole", "iam:PutRolePolicy"],
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/current-weather-tool-lambda-role"
    },
    {
      "Sid": "PassRoleToLambda",
      "Effect": "Allow",
      "Action": "iam:PassRole",
      "Resource": "arn:aws:iam::<ACCOUNT_ID>:role/current-weather-tool-lambda-role",
      "Condition": { "StringEquals": { "iam:PassedToService": "lambda.amazonaws.com" } }
    },
    {
      "Sid": "LambdaDeployAndInvoke",
      "Effect": "Allow",
      "Action": [
        "lambda:GetFunction",
        "lambda:CreateFunction",
        "lambda:UpdateFunctionCode",
        "lambda:InvokeFunction"
      ],
      "Resource": "arn:aws:lambda:<REGION>:<ACCOUNT_ID>:function:current-weather-tool-lambda"
    }
  ]
}
```

## Next component

`forecast-weather-tool-lambda` -- structurally identical to this repo
(same invocation contract, same CI/CD pattern), just a different
Open-Meteo query and response shape. After that: `outfit-suggestion-agent`
on AgentCore Runtime, then the AgentCore Gateway itself (which is what
finally wires this Lambda in as a live tool), then the Orchestrator.
