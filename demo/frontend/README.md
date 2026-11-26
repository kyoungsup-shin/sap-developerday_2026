# A2A demo frontend

```bash
npm install
npm run dev
```

Vite proxies `/api` to `http://localhost:8080`; start the backend gateway first. The UI uses a `fetch` streaming response because browser `EventSource` supports only GET requests.

Open **Harness Studio** in the sidebar to inspect the default Profile through
`GET /api/harness-profile`. The read-only **Agents & A2A** view shows Team
Skills, internal Specialists, evidence domains and allowed Tools. Agent names
and Prompt buttons open the existing system Prompt modal. Refresh and Retry
reload configuration; navigating back to Chat retains the conversation and draft.
The Gateway must include the Profile endpoint from framework step 1. No editing,
save controls or connection-verification claims are added in this UI step.
