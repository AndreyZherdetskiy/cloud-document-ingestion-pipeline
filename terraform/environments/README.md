When wiring a root stack, pass `module.sqs.queue_arn` into `modules/s3` as `ingest_queue_arn`, and pass `module.s3.bucket_arn` plus `account_id` into `modules/sqs` as `s3_bucket_arn` and `aws_account_id`.

For S3→SSE-KMS SQS, pass `aws_account_id` and `module.s3.bucket_arn` into `modules/kms` as `aws_account_id` and `documents_bucket_arn`. The KMS key policy grants `s3.amazonaws.com` `kms:GenerateDataKey` and `kms:Decrypt` scoped to that bucket (`aws:SourceArn`). See [Granting permissions to publish event notifications to a destination](https://docs.aws.amazon.com/AmazonS3/latest/userguide/grant-destinations-permissions-to-s3.html). Pass `module.kms.key_arn` into `modules/sqs` as `kms_key_id`.

**Implemented:** `terraform/environments/{dev,staging,prod}/main.tf` wires all modules with the predicted-bucket-ARN pattern. Copy `providers.tf.example` / `backend.tf.example` only if you need to replace live `providers.tf` / add remote state on human GO.
