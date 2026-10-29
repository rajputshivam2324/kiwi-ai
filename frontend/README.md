# Kiwi AI frontend

The React/TypeScript interface for chat, academic research, and the application builder. It uses Vite, Tailwind CSS, Clerk, Monaco, and streamed responses from the unified FastAPI backend.

See the [project setup guide](../README.md#run-locally) for PostgreSQL, model credentials, and backend startup.

## Run

Use Node.js **22.12+**, or the supported Node 20.19+ line. From `frontend/`:

```bash
test -f .env || cp .env.example .env
npm ci
npm run dev
```

Configure `.env`:

```dotenv
VITE_CLERK_PUBLISHABLE_KEY=your_clerk_publishable_key
VITE_API_URL=http://localhost:8000
VITE_PREVIEW_BASE_URL=http://localhost:5200
```

Open `http://localhost:5173`. Chat and builder routes require a Clerk session. Gemini, database, and Langfuse secrets belong in the backend environment; only the Clerk publishable key is used by the browser.

## Pages and components

| Path | Responsibility |
| --- | --- |
| `src/pages/LandingPage.tsx` | Public product page |
| `src/pages/AuthLandingPage.tsx` | Sign-in entry point |
| `src/pages/ChatPage.tsx` | General chat, research conversations, source cards, and finance-mode UI |
| `src/pages/BuilderPage.tsx` | Project generation and editing interface |
| `src/components/CodeEditor.tsx` | Monaco editing |
| `src/components/FileTree.tsx` | Generated project navigation |
| `src/components/Preview.tsx` | Live Vite preview |
| `src/components/MarkdownRenderer.tsx` | Markdown, code, and mathematical response rendering |
| `src/lib/api.ts` | API base URL and authenticated request headers |

Research conversation operations send the Clerk bearer token. General chat and research preserve the server's `conversation_id` on subsequent turns. Finance UI availability does not imply backend availability: the finance API is disabled in production.

## Checks

```bash
npm run build
npm run lint
```

`build` runs TypeScript checks and creates the production bundle in `dist/`. `lint` runs the repository's ESLint configuration.

## Deployment

The connected Vercel project builds this directory using [vercel.json](vercel.json). Set the frontend environment variables in Vercel before building:

```dotenv
VITE_CLERK_PUBLISHABLE_KEY=your_production_clerk_publishable_key
VITE_API_URL=https://api.kiwiai.shivamio.in
VITE_PREVIEW_BASE_URL=https://preview.kiwiai.shivamio.in
```

The API and generated-app preview use separate origins. The backend must allow the frontend's origin through `CORS_ORIGINS`, and its Clerk JWKS configuration must correspond to the frontend's Clerk application. SSE buffering and preview WebSocket forwarding are configured by the backend's Nginx deployment assets.
