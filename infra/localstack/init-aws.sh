#!/usr/bin/env bash
# LocalStack ready.d init: ingest DLQ→queue + processing DLQ→queue → bucket → S3→SQS.
# SSE-KMS is not configured here (Stage 1 stub); real AWS path uses KMS per ADR-010.
set -euo pipefail

APP_ENV="${APP_ENV:-dev}"
AWS_REGION="${AWS_DEFAULT_REGION:-${AWS_REGION:-eu-central-1}}"
S3_BUCKET="${S3_BUCKET:-${APP_ENV}-doc-pipeline}"

DLQ_NAME="${APP_ENV}-document-ingestion-dlq"
QUEUE_NAME="${APP_ENV}-document-ingestion"
PROCESSING_DLQ_NAME="${APP_ENV}-document-processing-dlq"
PROCESSING_QUEUE_NAME="${APP_ENV}-document-processing"

echo "init-aws: region=${AWS_REGION} bucket=${S3_BUCKET}"

# 1. Dead-letter queue first.
awslocal sqs create-queue --queue-name "${DLQ_NAME}" --region "${AWS_REGION}"
DLQ_URL="$(awslocal sqs get-queue-url --queue-name "${DLQ_NAME}" --output text --query QueueUrl)"
DLQ_ARN="$(awslocal sqs get-queue-attributes \
  --queue-url "${DLQ_URL}" \
  --attribute-names QueueArn \
  --output text \
  --query 'Attributes.QueueArn')"

# 2. Main ingest queue: VisibilityTimeout=300, RedrivePolicy maxReceiveCount=5.
# Poison → DLQ: docs/runbooks/dlq-replay.md
QUEUE_ATTRS_FILE="$(mktemp)"
cat > "${QUEUE_ATTRS_FILE}" <<EOF
{
  "VisibilityTimeout": "300",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"${DLQ_ARN}\",\"maxReceiveCount\":\"5\"}"
}
EOF
awslocal sqs create-queue \
  --queue-name "${QUEUE_NAME}" \
  --region "${AWS_REGION}" \
  --attributes "file://${QUEUE_ATTRS_FILE}"
rm -f "${QUEUE_ATTRS_FILE}"

QUEUE_URL="$(awslocal sqs get-queue-url --queue-name "${QUEUE_NAME}" --output text --query QueueUrl)"
QUEUE_ARN="$(awslocal sqs get-queue-attributes \
  --queue-url "${QUEUE_URL}" \
  --attribute-names QueueArn \
  --output text \
  --query 'Attributes.QueueArn')"

# Allow S3 to publish ObjectCreated events (AWS requires queue policy; LocalStack mirrors this).
QUEUE_POLICY_FILE="$(mktemp)"
cat > "${QUEUE_POLICY_FILE}" <<EOF
{
  "Policy": "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"AllowS3SendMessage\",\"Effect\":\"Allow\",\"Principal\":{\"Service\":\"s3.amazonaws.com\"},\"Action\":\"sqs:SendMessage\",\"Resource\":\"${QUEUE_ARN}\",\"Condition\":{\"ArnLike\":{\"aws:SourceArn\":\"arn:aws:s3:::${S3_BUCKET}\"}}}]}"
}
EOF
awslocal sqs set-queue-attributes \
  --queue-url "${QUEUE_URL}" \
  --attributes "file://${QUEUE_POLICY_FILE}"
rm -f "${QUEUE_POLICY_FILE}"

# 3. Processing queue + DLQ (internal PROCESS_DOCUMENT bus; maxReceiveCount=5).
awslocal sqs create-queue --queue-name "${PROCESSING_DLQ_NAME}" --region "${AWS_REGION}"
PROCESSING_DLQ_URL="$(awslocal sqs get-queue-url --queue-name "${PROCESSING_DLQ_NAME}" --output text --query QueueUrl)"
PROCESSING_DLQ_ARN="$(awslocal sqs get-queue-attributes \
  --queue-url "${PROCESSING_DLQ_URL}" \
  --attribute-names QueueArn \
  --output text \
  --query 'Attributes.QueueArn')"

PROCESSING_ATTRS_FILE="$(mktemp)"
cat > "${PROCESSING_ATTRS_FILE}" <<EOF
{
  "VisibilityTimeout": "300",
  "RedrivePolicy": "{\"deadLetterTargetArn\":\"${PROCESSING_DLQ_ARN}\",\"maxReceiveCount\":\"5\"}"
}
EOF
awslocal sqs create-queue \
  --queue-name "${PROCESSING_QUEUE_NAME}" \
  --region "${AWS_REGION}" \
  --attributes "file://${PROCESSING_ATTRS_FILE}"
rm -f "${PROCESSING_ATTRS_FILE}"

PROCESSING_QUEUE_URL="$(awslocal sqs get-queue-url --queue-name "${PROCESSING_QUEUE_NAME}" --output text --query QueueUrl)"

# 4. Bucket and S3 event notification → ingest queue for s3:ObjectCreated:*.
awslocal s3 mb "s3://${S3_BUCKET}" --region "${AWS_REGION}" 2>/dev/null || true

NOTIFICATION_FILE="$(mktemp)"
cat > "${NOTIFICATION_FILE}" <<EOF
{
  "QueueConfigurations": [
    {
      "QueueArn": "${QUEUE_ARN}",
      "Events": ["s3:ObjectCreated:*"]
    }
  ]
}
EOF
awslocal s3api put-bucket-notification-configuration \
  --bucket "${S3_BUCKET}" \
  --notification-configuration "file://${NOTIFICATION_FILE}"
rm -f "${NOTIFICATION_FILE}"

echo "init-aws: main queue URL=${QUEUE_URL}"
echo "init-aws: DLQ URL=${DLQ_URL}"
echo "init-aws: processing queue URL=${PROCESSING_QUEUE_URL}"
echo "init-aws: processing DLQ URL=${PROCESSING_DLQ_URL}"
echo "init-aws: bucket=s3://${S3_BUCKET}"
