output "eks_cluster_name" { value = aws_eks_cluster.main.name }
output "postgres_host" { value = aws_db_instance.postgres.address }
output "redis_host" { value = aws_elasticache_replication_group.redis.primary_endpoint_address }
