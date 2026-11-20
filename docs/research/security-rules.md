# Security findings for the report (step 5)

Deterministic checks on the scanned inventory. Each finding: id, severity, resource, evidence, fix (and whether the Leaseweb output fixes it automatically).

| Id | Severity | Check | Data | Auto-fixed in output? |
|---|---|---|---|---|
| SG-001 | critical | SSH (22) or RDP (3389) open to `0.0.0.0/0` or `::/0` | SG ingress rules | yes: restricted to `var.admin_cidr` |
| SG-002 | high | DB ports (3306, 5432, 1433, 27017, 6379, 9200) open to the internet | SG ingress | yes: private network only |
| SG-003 | medium | all ports / all protocols (`-1`) open to the internet | SG ingress | no, flagged |
| SG-004 | low | unused security groups (no attached ENI) | SGs vs ENIs | dropped from output |
| S3-001 | critical | public bucket (policy status `IsPublic` or ACL AllUsers) without an intended static-site reason | `get_bucket_policy_status`, ACLs | no, ask the user |
| S3-002 | high | account/bucket public access block off | `get_public_access_block` | n/a |
| S3-003 | medium | no default encryption | `get_bucket_encryption` | n/a |
| S3-004 | low | versioning off | `get_bucket_versioning` | n/a |
| RDS-001 | critical | `PubliclyAccessible = true` | `describe_db_instances` | yes |
| RDS-002 | high | `StorageEncrypted = false` | same | disk encryption note |
| RDS-003 | medium | `BackupRetentionPeriod = 0` | same | backup cron added |
| EC2-001 | high | IMDSv1 allowed (`HttpTokens = optional`) | `MetadataOptions` | n/a on Leaseweb |
| EC2-002 | medium | unencrypted EBS volumes | `describe_volumes` | note |
| EC2-003 | medium | public IP on an instance that sits behind a LB | instance + TG membership | yes: private only |
| IAM-001 | critical | root account has access keys or no MFA | `get_account_summary` | n/a |
| IAM-002 | high | access keys older than 90 days / unused | credential report | n/a |
| ELB-001 | medium | HTTP listener without redirect to HTTPS | listeners | yes: redirect added where supported |
| NET-001 | info | everything in the default VPC | VPC `IsDefault` | output uses a dedicated private network |

These double as the "security" angle for the jury: the migration also fixes problems the customer didn't know about.
