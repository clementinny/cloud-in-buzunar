# CloudInBuzunar Monitor for Android

The companion application can act as a camera/audio source and can monitor a
paired CloudInBuzunar server independently. Server monitoring uses a foreground
service so Android shows an ongoing notification.

## Server alerts

1. Install the app on the phone that should receive notifications.
2. Enter the complete server URL, for example HTTPS on port 8443.
3. Choose a check interval and the number of consecutive failed checks required
   before an outage is announced.
4. Tap **Salvează și pornește alertele** and allow notifications.

The default is one check every 60 seconds and an outage alert after three
consecutive failures. A single successful check resets the failure counter.
After an announced outage, the first successful check creates a recovery
notification. Monitoring remains enabled after app upgrades and device restarts.

For a Caddy internal certificate, install the CloudInBuzunar root CA on the
companion phone as a trusted user CA. The app accepts certificates from the
Android system trust store and user-installed trust store. Avoid accepting an
unknown certificate.

Android may delay checks during aggressive battery-saving modes. Set the
application battery mode to unrestricted when timely alerts are important.

## Backend contract

Availability uses the existing public endpoint:

~~~http
GET /api/health
~~~

It must return a successful HTTP status and JSON containing a status value of
online.

When the app has a paired device token, it also checks:

~~~http
GET /api/system/alerts/feed?limit=25
Authorization: Bearer DEVICE_TOKEN
~~~

The response may use an alerts array (preferred) or an events array:

~~~json
{
  "alerts": [
    {
      "id": 123,
      "severity": "warning",
      "title": "Temperatură ridicată",
      "message": "Telefonul a depășit pragul configurat."
    }
  ]
}
~~~

Only events with an id or event_id are shown. After Android posts the
notifications, the app acknowledges them with:

~~~http
POST /api/system/alerts/feed/ack
Authorization: Bearer DEVICE_TOKEN
Content-Type: application/json

{"event_ids": [123]}
~~~

A missing feed endpoint (HTTP 404) does not interfere with basic outage and
recovery monitoring.
