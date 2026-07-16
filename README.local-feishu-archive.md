# Local Feishu Archive Extension

This repository is a source snapshot of the Hermes deployment on the server.
It intentionally excludes the virtual environment, credentials, runtime caches,
session data, and the archived Feishu messages themselves.

## Included Changes

- `plugins/platforms/feishu/adapter.py` archives every Feishu event delivered to
  the bot into `/root/.hermes/feishu_messages.db` before agent admission.
- On startup it discovers visible group chats and backfills their accessible
  history; joining a later group triggers that group's backfill as well.
- Unmentioned group messages and their attachments are archived but do not call
  the model or receive a reply.
- Attachments are copied to `/root/.hermes/feishu_attachments/<message-id>/`.
- `local-plugins/feishu-context` provides `feishu_context_search`, a read-only
  model tool that searches only the group that invoked it.

## Server Installation

From this repository checkout on the server:

```bash
mkdir -p /root/.hermes/plugins
rsync -a local-plugins/feishu-context/ /root/.hermes/plugins/feishu-context/
```

Enable `feishu-context` under `plugins.enabled` in `/root/.hermes/config.yaml`,
then restart the gateway:

```bash
systemctl restart hermes-gateway
```

The tool accepts an optional keyword, ISO-8601 `after` / `before` bounds, and a
limit of up to 30 messages. It derives the chat ID from the active Feishu group
session, so a model cannot use it to retrieve another group's archive.

When called from the configured `FEISHU_HOME_CHANNEL`, the tool may search all
archived group histories or select a specific group with `chat_id`. Other
conversations remain restricted to their own archive.
