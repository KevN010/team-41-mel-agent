# cdk-nag AwsSolutions

All six stacks: zero unsuppressed errors. Suppressions actually used:

- `AwsSolutions-CFR1`: This hackathon simulator is intentionally accessible from every country.
- `AwsSolutions-CFR2`: CloudFront serves static files only; a paid WAF is outside the fixed demo scope.
- `AwsSolutions-CFR4`: The AWS default CloudFront certificate is required for the distribution domain; HTTPS-only redirects are enforced.
- `AwsSolutions-COG1`: The requested Cognito default password policy is retained for the demo.
- `AwsSolutions-COG2`: MFA is explicitly disabled by the fixed demo requirements.
- `AwsSolutions-COG8`: The paid Cognito Plus plan is outside the fixed hackathon demo scope.
- `AwsSolutions-IAM5`: Resource wildcards cover only specified model families, table indexes, log streams, artifacts objects, ECR authentication, metrics, and /mel parameters; actions are explicit.
- `AwsSolutions-L1`: Python 3.12 is explicitly required by the Lambda interface contract.
- `AwsSolutions-SMG4`: This third-party Jev key is rotated by its human owner; no provider rotation API is available.
