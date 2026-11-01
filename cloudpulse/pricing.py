"""Published AWS on-demand prices (us-east-1, Linux, USD)."""

# shortcut: us-east-1 prices are applied to every region; load per-region prices from the AWS Price List API if regions matter.

# resource type -> (service, USD per hour while running)
HOURLY = {
    "t3.micro": ("EC2", 0.0104),
    "t3.medium": ("EC2", 0.0416),
    "m5.large": ("EC2", 0.096),
    "c5.xlarge": ("EC2", 0.17),
    "r5.large": ("EC2", 0.126),
    "db.t3.micro": ("RDS", 0.017),
    "db.m5.large": ("RDS", 0.171),
    "cache.t3.micro": ("ElastiCache", 0.017),
    "eks-cluster": ("EKS", 0.10),
    "s3-standard": ("S3", 0.0),
}

# service -> USD per GB-month of storage (EBS gp3, RDS gp2, S3 Standard), billed even when stopped
STORAGE_GB_MONTH = {"EC2": 0.08, "RDS": 0.115, "S3": 0.023, "ElastiCache": 0.0, "EKS": 0.0}


def daily_cost(type_, storage_gb, running):
    service, hourly = HOURLY[type_]
    return hourly * 24 * bool(running) + storage_gb * STORAGE_GB_MONTH[service] / 30
