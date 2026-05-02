# Jarvis Android Companion

This is a scaffold for the Android side of the caller-identification flow:

1. Android receives an incoming call through `CallScreeningService`.
2. The companion app extracts the phone number.
3. The app tries identity sources in order: saved contacts, commercial provider hook, then Jarvis public lookup.
4. Jarvis returns a notification title/body plus optional speech text.
5. The app shows the caller info in a high-priority notification and can play Jarvis-generated MP3 audio from `/tts`.

## What This Scaffold Includes

- Settings screen for backend URL, shared token, device id, voice toggle, and provider-ready preferences
- `IncomingCallScreeningService` for incoming call detection
- `JarvisApiClient` for the backend contract
- Notification helper and MP3 playback helper
- Contact lookup support for saved numbers
- A commercial-provider abstraction with a Hiya integration scaffold

## What You Still Need To Do

1. Open this folder in Android Studio.
2. Sync Gradle and let Android Studio generate the wrapper files.
3. Install the app on your Android phone.
4. In Android Settings, set this app as your caller ID / spam app if your device exposes that option.
5. Set `PHONE_BRIDGE_TOKEN` in your Jarvis backend `.env`.
6. Enter the same token and your Jarvis backend URL in the Android app, for example `http://192.168.1.20:8000`.
7. Allow notification permission on Android 13+.

## Backend Contract

Endpoint:

`POST /phone/incoming-call`

Request example:

```json
{
  "phone_number": "+919876543210",
  "caller_name_hint": null,
  "device_id": "pixel-8",
  "speak_result": true
}
```

Header when `PHONE_BRIDGE_TOKEN` is set:

`X-Jarvis-Token: your-shared-secret`

Response example:

```json
{
  "event_id": "uuid",
  "phone_number": "+919876543210",
  "normalized_number": "+919876543210",
  "summary": "Public reports suggest this may be a telemarketing number.",
  "notification_title": "Incoming call: +919876543210",
  "notification_body": "Public reports suggest this may be a telemarketing number.",
  "speak_text": "Public reports suggest this may be a telemarketing number.",
  "public_data_only": true,
  "results": []
}
```

## Notes

- The app does not block or reject calls.
- The current provider order is: contacts -> commercial provider scaffold -> Jarvis public web lookup.
- Hiya is scaffolded as the cleanest official integration point, but the actual SDK dependency and credential wiring still need your vendor credentials.
- Speech playback now comes from your Jarvis `/tts` endpoint instead of local Android TTS.
- Some Android vendors handle call-screening permissions a little differently, so you may need to enable the app manually in Phone app settings.
