# Start docker-compose and wait for services
docker-compose up -d postgres redis minio
echo "Wait for db..."
sleep 5
docker-compose exec api poetry run alembic upgrade head
docker-compose up -d web api
