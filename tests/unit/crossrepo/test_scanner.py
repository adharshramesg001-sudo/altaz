from atlaz.crossrepo.scanner import scan_declared_service_names, scan_outbound_calls, scan_pubsub_signals


def test_scan_outbound_calls_finds_literal_url(tmp_path):
    (tmp_path / "client.py").write_text(
        'import requests\n\ndef fetch():\n    return requests.get("http://order-service:8080/api/orders")\n'
    )

    signals = scan_outbound_calls(str(tmp_path))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.host == "order-service"
    assert signal.path == "/api/orders"
    assert signal.evidence.file == "client.py"
    assert signal.evidence.line == 4


def test_scan_outbound_calls_finds_env_var_reference(tmp_path):
    (tmp_path / "config.py").write_text('import os\n\nBASE = os.environ["ORDER_SERVICE_URL"]\n')

    signals = scan_outbound_calls(str(tmp_path))

    assert len(signals) == 1
    assert signals[0].host == "ORDER_SERVICE"
    assert signals[0].path == ""


def test_scan_outbound_calls_ignores_env_var_without_service_suffix(tmp_path):
    (tmp_path / "config.py").write_text('import os\n\nDEBUG = os.getenv("DEBUG")\n')

    signals = scan_outbound_calls(str(tmp_path))

    assert signals == []


def test_scan_outbound_calls_skips_ignored_dirs(tmp_path):
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "index.js").write_text('fetch("http://order-service/api")')

    signals = scan_outbound_calls(str(tmp_path))

    assert signals == []


def test_scan_declared_service_names_reads_docker_compose(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  order-service:\n    image: order:latest\n  payment-service:\n    image: payment:latest\n"
    )

    names = scan_declared_service_names(str(tmp_path))

    assert names == {"order-service", "payment-service"}


def test_scan_declared_service_names_reads_k8s_manifest(tmp_path):
    (tmp_path / "deployment.yaml").write_text("kind: Service\nmetadata:\n  name: order-service\n")

    names = scan_declared_service_names(str(tmp_path))

    assert names == {"order-service"}


def test_scan_pubsub_signals_finds_kafka_producer_and_consumer(tmp_path):
    (tmp_path / "producer.py").write_text('producer.send("OrderCreated", value=payload)\n')
    (tmp_path / "consumer.py").write_text('consumer.subscribe(["OrderCreated"])\n')

    signals = scan_pubsub_signals(str(tmp_path))

    by_file = {s.evidence.file: s for s in signals}
    assert by_file["producer.py"].direction == "publish"
    assert by_file["producer.py"].topic == "OrderCreated"
    assert by_file["producer.py"].library == "kafka"
    assert by_file["consumer.py"].direction == "consume"
    assert by_file["consumer.py"].topic == "OrderCreated"


def test_scan_pubsub_signals_finds_rabbitmq_publish_and_consume(tmp_path):
    (tmp_path / "worker.py").write_text(
        'channel.basic_publish(exchange="", routing_key="order-tasks", body=b"x")\n'
        'channel.basic_consume(queue="order-tasks", on_message_callback=cb)\n'
    )

    signals = scan_pubsub_signals(str(tmp_path))

    assert {(s.direction, s.topic, s.library) for s in signals} == {
        ("publish", "order-tasks", "rabbitmq"),
        ("consume", "order-tasks", "rabbitmq"),
    }


def test_scan_pubsub_signals_finds_sqs_queue_name_from_url(tmp_path):
    (tmp_path / "sqs_client.py").write_text(
        'sqs.send_message(QueueUrl="https://sqs.us-east-1.amazonaws.com/123456789012/order-tasks", MessageBody=x)\n'
    )

    signals = scan_pubsub_signals(str(tmp_path))

    assert len(signals) == 1
    assert signals[0].direction == "publish"
    assert signals[0].topic == "order-tasks"
    assert signals[0].library == "sqs"


def test_scan_pubsub_signals_finds_google_pubsub_topic_and_subscription(tmp_path):
    (tmp_path / "gcp.py").write_text(
        'topic = publisher.topic_path(project, "order-created")\n'
        'sub = subscriber.subscription_path(project, "order-created-sub")\n'
    )

    signals = scan_pubsub_signals(str(tmp_path))

    assert {(s.direction, s.topic, s.library) for s in signals} == {
        ("publish", "order-created", "google_pubsub"),
        ("consume", "order-created-sub", "google_pubsub"),
    }
