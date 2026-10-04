"""In-app updates from tagged releases.

How an update flows:

1. ``sources`` lists available releases (GitHub tags named vX.Y.Z, or a local
   folder of zips in simulation mode) and downloads one as a zip.
2. ``installer.stage_release`` unpacks the zip into ``updates/staged`` and
   records a pending action. Nothing in use is touched yet.
3. The launcher (``sar_log.launcher``) applies pending actions *before*
   starting the app, when no code is running from the install folder. The
   current code is moved to ``updates/previous`` so it can be restored, and
   any failure rolls the swap back automatically.

The user's data (``data/``) and the Python environment (``.venv/``) are never
touched by an update.
"""
