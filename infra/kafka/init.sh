#!/bin/sh
set -eu
bin=/opt/kafka/bin
config=/run/secrets/kafka_admin.properties
for topic in credimarket.inventario.comandos.v1 credimarket.inventario.eventos.v1; do
  "$bin/kafka-topics.sh" --bootstrap-server kafka:9092 --command-config "$config" \
    --create --if-not-exists --topic "$topic" --partitions 3 --replication-factor 1 \
    --config retention.ms=604800000 --config cleanup.policy=delete
  "$bin/kafka-topics.sh" --bootstrap-server kafka:9092 --command-config "$config" \
    --create --if-not-exists --topic "$topic.dlq" --partitions 3 --replication-factor 1 \
    --config retention.ms=1209600000 --config cleanup.policy=delete
done
acl() { "$bin/kafka-acls.sh" --bootstrap-server kafka:9092 --command-config "$config" --add "$@"; }
acl --allow-principal User:prestamos --operation Write --operation Describe --topic credimarket.inventario.comandos.v1
acl --allow-principal User:inventario --operation Read --operation Describe --topic credimarket.inventario.comandos.v1
acl --allow-principal User:inventario --operation Write --operation Describe --topic credimarket.inventario.eventos.v1
acl --allow-principal User:prestamos --operation Read --operation Describe --topic credimarket.inventario.eventos.v1
acl --allow-principal User:inventario --operation Write --operation Describe --topic credimarket.inventario.comandos.v1.dlq
acl --allow-principal User:prestamos --operation Write --operation Describe --topic credimarket.inventario.eventos.v1.dlq
acl --allow-principal User:inventario --operation Read --group inventario-v1
acl --allow-principal User:prestamos --operation Read --group prestamos-v1
for user in prestamos inventario; do
  acl --allow-principal "User:$user" --operation IdempotentWrite --cluster
done
echo 'Topics and service ACLs configured.'
