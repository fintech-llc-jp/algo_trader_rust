<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Run and deploy your AI Studio app

This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/b33925aa-11e9-4204-916e-d53dc75d6d60

## Run Locally

**Prerequisites:**  Node.js


1. Install dependencies:
   `npm install`
2. Set the `GEMINI_API_KEY` in [.env.local](.env.local) to your Gemini API key
3. Run the app:
   `npm run dev`

## Optional: connect to algo-trader BFF

Set these values in `.env.local` when you want the MVP UI to call the local backend:

```bash
VITE_BFF_BASE_URL=http://127.0.0.1:8090
# optional when BFF auth is enabled
# VITE_BFF_API_KEY=your_api_key
```
