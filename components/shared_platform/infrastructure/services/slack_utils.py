import requests
from django.conf import settings
from slack import WebClient

# Use your organization slack url
webhook_url = 'https://hooks.slack.com/services/xxxxxx'

def _send(channel, msg, icon=":partydeploy:"):
    if settings.SEND_SLACK:
        host = socket.gethostname()
        slack_data = {"channel": channel, "username": "discovobot",
                      "text": f"{settings.DEPLOYED_ENV} [{host}]\n{msg}",
                      "icon_emoji": icon}

        requests.post(  # noqa: F841
            webhook_url, data=json.dumps(slack_data),
            headers={'Content-Type': 'application/json'}
        )
    else:
        logger.debug(msg)

def send_pinecone_upsert_report(content_type, upserted_items, omitted_items):
    msg = f"🌐 Pinecone Daily Report:\n{'-' * 25}\n" \
          f"📈 Upserted {len(upserted_items)} unique URLs.\n" \
          f"🚫 Omitted {len(omitted_items)} URLs."
    _send("#discovery-data-report", msg)
