resource "aws_sns_topic" "alerts" {
  name              = "${local.prefix}-alerts"
  kms_master_key_id = aws_kms_key.pipeline.arn
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "queue_oldest_message_age" {
  alarm_name          = "${local.prefix}-queue-oldest-message-age"
  alarm_description   = "Oldest visible message exceeds the customer-facing processing SLO."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  metric_name         = "ApproximateAgeOfOldestMessage"
  namespace           = "AWS/SQS"
  period              = 60
  statistic           = "Maximum"
  threshold           = var.age_threshold_seconds
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    QueueName = aws_sqs_queue.processing.name
  }
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages_visible" {
  alarm_name          = "${local.prefix}-dlq-messages-visible"
  alarm_description   = "A message landed on the DLQ. Investigate poison messages."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    QueueName = aws_sqs_queue.dlq.name
  }
}

resource "aws_cloudwatch_metric_alarm" "retry_ratio" {
  alarm_name          = "${local.prefix}-retry-ratio"
  alarm_description   = "Receive/Delete ratio > 2 over 15 minutes indicates a retry storm."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 2
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  metric_query {
    id          = "received"
    return_data = false
    metric {
      namespace   = "AWS/SQS"
      metric_name = "NumberOfMessagesReceived"
      period      = 300
      stat        = "Sum"
      dimensions = {
        QueueName = aws_sqs_queue.processing.name
      }
    }
  }

  metric_query {
    id          = "deleted"
    return_data = false
    metric {
      namespace   = "AWS/SQS"
      metric_name = "NumberOfMessagesDeleted"
      period      = 300
      stat        = "Sum"
      dimensions = {
        QueueName = aws_sqs_queue.processing.name
      }
    }
  }

  metric_query {
    id          = "ratio"
    expression  = "received / IF(deleted==0, 1, deleted)"
    label       = "ReceiveToDeleteRatio"
    return_data = true
  }
}
