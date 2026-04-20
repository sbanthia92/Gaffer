#!/usr/bin/env bash
# One-time setup: install and configure the CloudWatch agent on EC2.
# Run as: sudo bash scripts/setup_cloudwatch.sh
set -euo pipefail

REGION="us-east-1"
LOG_GROUP="/gaffer/production/api"

echo "==> Installing CloudWatch agent..."
yum install -y amazon-cloudwatch-agent

echo "==> Writing agent config..."
mkdir -p /opt/aws/amazon-cloudwatch-agent/etc
cat > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json << 'EOF'
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/gaffer/app.log",
            "log_group_name": "/gaffer/production/api",
            "log_stream_name": "{instance_id}",
            "timestamp_format": "%Y-%m-%dT%H:%M:%S",
            "timezone": "UTC",
            "multi_line_start_pattern": "^\\{"
          }
        ]
      }
    },
    "log_stream_name": "{instance_id}"
  }
}
EOF

echo "==> Creating log directory..."
mkdir -p /var/log/gaffer
chown ec2-user:ec2-user /var/log/gaffer

echo "==> Starting CloudWatch agent..."
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json

systemctl enable amazon-cloudwatch-agent
systemctl start amazon-cloudwatch-agent

echo "==> Creating ETL dead-man's switch alarm..."
# Fires if no SnapshotSuccess metric arrives within 2 hours (2 × 1-hour periods).
# The ETL emits this metric via boto3 after every successful snapshot run.
# Requires the EC2 IAM role to have cloudwatch:PutMetricData + cloudwatch:PutMetricAlarm.
aws cloudwatch put-metric-alarm \
  --region "$REGION" \
  --alarm-name "gaffer-etl-snapshot-missing" \
  --alarm-description "ETL snapshot has not completed in over 2 hours" \
  --namespace "Gaffer/ETL" \
  --metric-name "SnapshotSuccess" \
  --dimensions Name=Mode,Value=snapshot \
  --statistic Sum \
  --period 3600 \
  --evaluation-periods 2 \
  --threshold 1 \
  --comparison-operator LessThanThreshold \
  --treat-missing-data breaching \
  --alarm-actions "arn:aws:sns:${REGION}:$(aws sts get-caller-identity --query Account --output text):gaffer-alerts" \
  --ok-actions    "arn:aws:sns:${REGION}:$(aws sts get-caller-identity --query Account --output text):gaffer-alerts"

echo "==> Done. Logs will appear in CloudWatch under: $LOG_GROUP"
echo "    ETL alarm: gaffer-etl-snapshot-missing (fires if silent for 2h)"
echo "    NOTE: create SNS topic 'gaffer-alerts' and subscribe your email to receive alerts."
