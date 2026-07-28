# Audience analytics loop — setup (one time, ~15 minutes)

The nightly `analytics.yml` workflow pulls each published video's YouTube
audience-retention curve and feeds it back into the pipeline's memory:
scenes that hold viewers strengthen their queries and taste embeddings,
scenes that bleed viewers weaken theirs. Until the three secrets below
exist the workflow runs green and does nothing.

## 1. Google Cloud credentials

1. console.cloud.google.com -> new project (any name).
2. "APIs & Services -> Library": enable **YouTube Analytics API**.
3. "APIs & Services -> OAuth consent screen": External, add yourself as a test user.
4. "Credentials -> Create credentials -> OAuth client ID -> Desktop app".
   Note the **client ID** and **client secret**.

## 2. One-time refresh token

Easiest path: https://developers.google.com/oauthplayground
- Gear icon -> "Use your own OAuth credentials" -> paste ID + secret.
- Authorize scope: `https://www.googleapis.com/auth/yt-analytics.readonly`
  (sign in with the channel's Google account).
- "Exchange authorization code for tokens" -> copy the **refresh token**.

## 3. Repo secrets

Repo Settings -> Secrets and variables -> Actions -> add:
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`.

## 4. Map every upload

After uploading a build to YouTube:

    python3 pipeline/learn.py published <slug> <youtube_video_id>

then commit `pipeline/published_videos.json`. That's the whole loop —
retention data starts flowing the next night. Read the results in
`pipeline/WHATS_WORKING.md` and `build/<slug>/retention.json`.
