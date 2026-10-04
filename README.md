# Checkmk Signal Notifier

Send Checkmk host and service notifications to Signal through an existing [`signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api) instance.

The project has two parts:

- A small HTTP relay, deployed with Docker Compose beside the Signal API. It authenticates Checkmk requests and forwards them to the API's `/v2/send` endpoint.
- A Checkmk notification script that formats host/service state changes and calls the relay.

```text
Checkmk notification script --Bearer token--> Signal relay --Docker network--> signal-api --Signal--> recipient(s)
```

The relay does not run or register Signal itself. It reuses the existing Signal API container and its persistent account data. It can run as a small standalone Compose project or as another service in the existing SignalClient Compose project.

## Requirements

- Docker Engine and Docker Compose v2 on the host running `signal-api`.
- An existing `signal-api` container reachable on a Docker network shared with the relay.
- Checkmk Community or a commercial edition with a site-local notification script. The script runs on the Checkmk site host.
- Network access from Checkmk to the relay's published port.

## Configure and start the relay

Copy the example environment file and set the Signal account, recipients, and a long random relay token:

```bash
cp .env.example .env
openssl rand -hex 32
```

Put the generated value in `NOTIFY_TOKEN` in `.env`. Set `SIGNAL_NUMBER` to the registered sending number and `SIGNAL_RECIPIENTS` to one or more recipient numbers separated by commas. Confirm `SIGNAL_DOCKER_NETWORK` matches the Docker network used by the existing Signal API. The example value is generic and must be replaced with the actual network name on your host.

By default, the relay binds to `127.0.0.1:8788` and is reachable only from the Docker host. Set `NOTIFY_BIND_IP` to the host's management IP for a remote Checkmk server, then restrict that port in the host firewall to the Checkmk server address only.

```bash
docker compose config
docker compose up -d --build
docker compose ps
```

The relay's `/healthz` endpoint checks that the Signal API configuration endpoint responds. It does not send a message.

## Use an existing SignalClient Compose project

If SignalClient already has a Compose project, the relay can be added as another service there instead of running the repository's Compose project separately. Use the existing network that contains `signal-api` (for example, `notification-nw`) and point `build` and `env_file` at this checkout. In this mode, remove the standalone Compose project's external-network declaration; the existing Compose project already owns the network. Do not run both modes at once because both publish the same relay port.

## Install the Checkmk notification script

Copy `checkmk/notifications/signal` to the Checkmk site's local notification directory and make it executable:

```bash
mkdir -p ~/local/share/check_mk/notifications
cp checkmk/notifications/signal ~/local/share/check_mk/notifications/signal
chmod 0750 ~/local/share/check_mk/notifications/signal
```

Create the per-site configuration from the example. Replace the placeholder with the host address and published port reachable from Checkmk:

```bash
cp checkmk/signal-notify.json.example ~/etc/check_mk/signal-notify.json
chmod 0600 ~/etc/check_mk/signal-notify.json
```

Edit `signal-notify.json` with the relay URL and the same token as `NOTIFY_TOKEN`. The file is outside the repository and must remain readable by the Checkmk site user only.

In Checkmk, create a notification rule, choose the `Signal` method, and select the intended contacts and host/service events. The configured Signal recipients are fixed by `SIGNAL_RECIPIENTS`; all notifications matched by that rule go to those recipients. Activate changes and test with a controlled state change. Checkmk's notification history and `~/var/log/notify.log` show the delivery result.

## Security notes

The relay requires a Bearer token and rejects requests without it. The default bind is loopback; do not publish it to an untrusted network. The example uses HTTP, so the token is not encrypted in transit. On a network that is not trusted end to end, place the relay behind TLS or add TLS at the relay, and keep the firewall restricted regardless.

The relay needs access to the Docker network containing `signal-api`, but it does not mount the Docker socket. Do not publish the Signal API's own port to untrusted networks; its send endpoint can transmit messages and is not authenticated by this project.

## Development

Run the relay unit tests with Python 3.12 or newer:

```bash
python3 -m unittest discover -s test -v
```

See [LICENSE](LICENSE) for licensing terms.
