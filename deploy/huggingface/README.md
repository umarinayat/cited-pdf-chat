---
title: Cited PDF Chat
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 8000
pinned: false
short_description: PDF chat with verified, highlighted citations
---

# Cited PDF Chat

Ask questions about a PDF, including a scanned one. Every sentence of the answer links to the exact passage it came
from, highlighted on the page, and every quote is checked against the PDF's own words.

Source code, architecture and accuracy results: https://github.com/umarinayat/cited-pdf-chat

This Space builds straight from that repository (see `Dockerfile`); Settings → "Factory rebuild" deploys the latest
commit. Add a `GEMINI_API_KEY` secret in the Space settings for written answers. Without it the app runs in
search-only mode and shows the closest passages.

Limits on this public demo: 30 questions an hour per visitor, 300 model answers a day in total, PDFs up to 15 MB and
40 pages, and uploads are deleted after 24 hours. Don't upload confidential documents.
