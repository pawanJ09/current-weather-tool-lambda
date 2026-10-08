# Gateway invoke permission -- deliberately not set up in this repo

This Lambda's execution role (`iam/trust-policy.json` +
`iam/execution-role-policy.json`) controls what the function can **do**
(write logs). It says nothing about who can **invoke** it.

For AgentCore Gateway to call this function as a Lambda target, the
function needs a **resource-based policy** granting
`lambda:InvokeFunction` to the Gateway's principal, scoped to the specific
Gateway target that will be created for it -- e.g.:

```bash
aws lambda add-permission \
  --function-name current-weather-tool-lambda \
  --statement-id AllowAgentCoreGatewayInvoke \
  --action lambda:InvokeFunction \
  --principal bedrock-agentcore.amazonaws.com \
  --source-arn <gateway-target-arn>
```

That `<gateway-target-arn>` doesn't exist until the Gateway and its
targets are created -- which is Step 4 of the build plan (AgentCore
Gateway + tool targets), after both weather Lambdas are deployed. This
repo's `deploy.yml` intentionally stops at creating/updating the
**function**, and does not attempt this `add-permission` call.

Run the command above (or the equivalent step in the Gateway repo's
deploy workflow) once the Gateway target for this function exists.
