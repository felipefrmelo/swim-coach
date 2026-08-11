---
name: post-swim-checkin
description: Record structured post-swim feedback such as RPE, technique quality, pain signal, and notes for a completed activity.
---

# Post-swim check-in

1. Resolve the completed activity.
2. Collect only missing fields: RPE 1–10, technique, pain present/location/severity, and optional note.
3. Reflect back sensitive pain information before storing when ambiguity matters.
4. Call `record_session_feedback` with a stable idempotency key.
5. Confirm what was stored.
6. Do not diagnose. For strong, acute, persistent, or worrying symptoms, recommend pausing and seeking qualified professional assessment.
