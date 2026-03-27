import * as path from 'path';
import { execSync } from 'child_process';
import * as cdk from 'aws-cdk-lib/core';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export class LambdaUsageStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ── Bedrock permission (shared by both Lambdas) ─────────────────────────
    const bedrockPolicy = new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'bedrock:InvokeModel',
        'bedrock:InvokeModelWithResponseStream',
      ],
      resources: ['*'], // Bedrock does not support resource-level ARNs for models
    });

    // Required for cross-region inference profiles (eu.* models) —
    // the role must be able to view and confirm the Marketplace subscription.
    const marketplacePolicy = new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'aws-marketplace:ViewSubscriptions',
        'aws-marketplace:Subscribe',
      ],
      resources: ['*'],
    });

    // =========================================================================
    // STANDARD LAMBDA
    // Two sequential Bedrock calls inside a single Lambda execution.
    // =========================================================================
    const standardLambda = new lambda.Function(this, 'StandardLambda', {
      functionName: 'bedrock-standard-two-calls',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.lambda_handler',
      code: lambda.Code.fromAsset('lambda/standard'),
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      description: 'Standard Lambda: 2 sequential Bedrock calls in one invocation',
    });

    standardLambda.addToRolePolicy(bedrockPolicy);
    standardLambda.addToRolePolicy(marketplacePolicy);

    // =========================================================================
    // DURABLE LAMBDA LAYER
    // Uses local pip to install dependencies (no Docker required).
    // Falls back to Docker if pip is not available on the host.
    // =========================================================================
    const durableSourceDir = path.join(__dirname, '../lambda/durable');

    const durableLayer = new lambda.LayerVersion(this, 'DurableLayer', {
      layerVersionName: 'bedrock-durable-deps',
      compatibleRuntimes: [lambda.Runtime.PYTHON_3_13],
      description: 'AWS Durable Execution SDK and dependencies',
      code: lambda.Code.fromAsset(durableSourceDir, {
        bundling: {
          image: cdk.DockerImage.fromRegistry('python:3.13'),
          local: {
            tryBundle(outputDir: string): boolean {
              try {
                execSync(
                  `python3.13 -m pip install -r requirements.txt -t ${outputDir}/python`,
                  { cwd: durableSourceDir, stdio: 'inherit' },
                );
                return true;
              } catch {
                return false; // fall back to Docker
              }
            },
          },
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output/python',
          ],
        },
      }),
    });

    // =========================================================================
    // DURABLE LAMBDA
    // State checkpointing is managed by the AWS Durable Execution SDK.
    // A custom role is required so we can attach the durable checkpoint policy.
    // =========================================================================
    const durableRole = new iam.Role(this, 'DurableRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
    });

    const durableLambda = new lambda.Function(this, 'DurableLambda', {
      functionName: 'bedrock-durable-two-calls',
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(durableSourceDir, {
        exclude: ['requirements.txt'],
      }),
      layers: [durableLayer],
      timeout: cdk.Duration.minutes(5),
      memorySize: 512,
      description: 'Durable Lambda: 2-step Bedrock chain via the AWS Durable Execution SDK',
      role: durableRole,
      durableConfig: {
        executionTimeout: cdk.Duration.minutes(10),
        retentionPeriod: cdk.Duration.days(1),
      },
    });

    const durableCheckpointPolicy = new iam.PolicyStatement({
      actions: [
        'lambda:CheckpointDurableExecution',
        'lambda:GetDurableExecutionState',
      ],
      resources: ['*'],
    });

    durableLambda.addToRolePolicy(bedrockPolicy);
    durableLambda.addToRolePolicy(marketplacePolicy);
    durableLambda.addToRolePolicy(durableCheckpointPolicy);



  }
}
