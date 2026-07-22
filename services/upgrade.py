"""Standard upgrade hint for plan-limit / feature-gate rejections.

Contract with the frontend (templates/_security_head.html): a JSON error
response MAY include

    "upgrade": {"reason": "<slug>", "url": "/pricing?upgrade_reason=<slug>"}

The global fetch wrapper watches every failed same-origin JSON response for
this field and shows a single dismissible upgrade CTA; the query param tells
the pricing page (and analytics) which limit drove the visit.
"""


def upgrade_hint(reason):
    return {"reason": reason, "url": f"/pricing?upgrade_reason={reason}"}
