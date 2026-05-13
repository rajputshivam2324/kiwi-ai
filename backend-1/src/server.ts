import express from "express";
import cors from "cors";
import dotenv from "dotenv";
import fs from "fs";
import path from "path";
import { fileURLToPath } from 'url';
import OpenAI from "openai";
import { spawn, ChildProcess } from "child_process";
import archiver from "archiver";
import { clerkAuth, requireAuth, optionalAuth } from "./auth.js";
import { initDb, createProject, updateProjectStatus, getProjectsByUser, getProjectByIdAndUser, saveProjectFiles, getProjectFiles, getProjectFileContent } from "./db.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load .env from the same directory as this script
dotenv.config({ path: path.join(__dirname, '.env') });

// Debug: Log environment status (Gemini accepts GEMINI_API_KEY or GOOGLE_API_KEY)
console.log(
    'Environment loaded. Gemini API key is',
    process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY ? 'SET' : 'NOT SET'
);
console.log('CLERK_SECRET_KEY is', process.env.CLERK_SECRET_KEY ? 'SET' : 'NOT SET');
console.log('DATABASE_URL is', process.env.DATABASE_URL ? 'SET' : 'NOT SET');

const app = express();
app.use(express.json());
app.use(cors({
    origin: ['http://localhost:5173', 'http://localhost:3000'],
    credentials: true,
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization'],
}));

// Explicitly handle OPTIONS preflight for all routes using Express 5 compatible syntax
app.use((req, res, next) => {
    // Set CORS headers on ALL responses
    res.header('Access-Control-Allow-Origin', 'http://localhost:5173');
    res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    res.header('Access-Control-Allow-Credentials', 'true');

    if (req.method === 'OPTIONS') {
        return res.sendStatus(204);
    }
    next();
});

// Initialize Clerk middleware
app.use(clerkAuth);

const GEMINI_MODEL = process.env.GEMINI_MODEL ?? "gemini-2.5-flash";
const GEMINI_OPENAI_BASE_URL =
    process.env.GEMINI_BASE_URL ?? "https://generativelanguage.googleapis.com/v1beta/openai/";

function getGeminiApiKey(): string | undefined {
    return process.env.GEMINI_API_KEY || process.env.GOOGLE_API_KEY;
}

function createGeminiOpenAI(timeoutMs?: number): OpenAI {
    const apiKey = getGeminiApiKey();
    if (!apiKey) {
        throw new Error("GEMINI_API_KEY or GOOGLE_API_KEY is not set in environment variables");
    }
    return new OpenAI({
        apiKey,
        baseURL: GEMINI_OPENAI_BASE_URL,
        ...(timeoutMs != null ? { timeout: timeoutMs } : {}),
    });
}

const WORKSPACES_DIR = path.join(__dirname, "workspaces");

// Ensure workspaces directory exists
if (!fs.existsSync(WORKSPACES_DIR)) {
    fs.mkdirSync(WORKSPACES_DIR, { recursive: true });
}

// In-memory job store (for active builds only - completed builds are in DB)
interface Job {
    id: string;
    userId: string;
    status: 'queued' | 'processing' | 'completed' | 'failed';
    prompt: string;
    result?: { projectId: string };
    error?: string;
    files?: Array<{ path: string; content: string }>;
    existingFiles?: Array<{ path: string; content: string }>;
    devPort?: number;
    devProcess?: ChildProcess;
}

const jobs = new Map<string, Job>();

// Port management for dev servers
let nextDevPort = 5200;
const allocatePort = (): number => {
    return nextDevPort++;
};

// Generate unique ID
const generateId = () => `job_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

// Generate a short project name from prompt
const generateProjectName = (prompt: string): string => {
    const words = prompt.trim().split(/\s+/).slice(0, 6).join(' ');
    return words.length > 50 ? words.substring(0, 50) + '...' : words;
};

// Start Vite dev server for a project
const startDevServer = (jobId: string, projectPath: string, port: number): Promise<ChildProcess> => {
    return new Promise((resolve, reject) => {
        console.log(`Starting dev server for ${jobId} on port ${port}...`);

        // First install dependencies, then start dev server
        const npmInstall = spawn('npm', ['install'], { cwd: projectPath, shell: true });

        npmInstall.on('close', (code) => {
            if (code !== 0) {
                reject(new Error(`npm install failed with code ${code}`));
                return;
            }

            console.log(`Dependencies installed for ${jobId}, starting Vite...`);

            const devProcess = spawn('npm', ['run', 'dev', '--', '--port', port.toString(), '--host'], {
                cwd: projectPath,
                shell: true,
                detached: true
            });

            devProcess.stdout?.on('data', (data) => {
                console.log(`[${jobId}] ${data}`);
            });

            devProcess.stderr?.on('data', (data) => {
                console.error(`[${jobId}] ${data}`);
            });

            // Wait a bit for vite to start
            setTimeout(() => {
                resolve(devProcess);
            }, 3000);
        });

        npmInstall.on('error', reject);
    });
};

// Kill dev server for a specific job (helper)
const killDevServerForJob = (jobId: string) => {
    const existingJob = jobs.get(jobId);
    if (existingJob?.devProcess) {
        try {
            process.kill(-existingJob.devProcess.pid!, 'SIGTERM');
            existingJob.devProcess = undefined;
            existingJob.devPort = undefined;
            console.log(`Killed existing dev server for job ${jobId}`);
        } catch (e) {
            console.error(`Failed to kill dev server for ${jobId}:`, e);
        }
    }
};

// AI Generation Function
const generateProject = async (
    job: Job,
    sendEvent: (event: string, data: any) => void,
    existingFiles?: Array<{ path: string; content: string }>
) => {
    console.log('Starting project generation for job:', job.id, existingFiles ? '(follow-up)' : '(new)');

    if (!getGeminiApiKey()) {
        throw new Error('GEMINI_API_KEY or GOOGLE_API_KEY is not set in environment variables');
    }

    const openai = createGeminiOpenAI(120000);

    let systemPrompt: string;
    let userContent: string;

    if (existingFiles && existingFiles.length > 0) {
        // Follow-up mode: include existing project files as context
        systemPrompt = `You are a JSON-only code generation API. You modify existing web applications.
You receive an existing project's files and a follow-up instruction.
You MUST respond with ONLY a valid JSON object. No explanation, no markdown, no code fences, no text before or after the JSON.
The EXACT format is:
{"files":[{"path":"path/to/file.ext","content":"full updated code content here"}]}
Rules:
- Output MUST start with { and end with }
- Include ALL project files (even unchanged ones)
- The project uses React + Vite + TypeScript + Tailwind CSS
- Fix any bugs or issues the user mentions
- DO NOT generate package-lock.json, yarn.lock, or lock files
- DO NOT wrap the JSON in markdown code blocks`;

        const existingFilesContext = existingFiles
            .map(f => `--- ${f.path} ---\n${f.content}`)
            .join('\n\n');

        userContent = `Here are the current project files:\n\n${existingFilesContext}\n\nUser follow-up instruction: ${job.prompt}

RESPOND WITH ONLY THE JSON OBJECT. NO OTHER TEXT.`;
    } else {
        // New project mode
        systemPrompt = `You are a JSON-only code generation API. You generate full stack web applications.
You MUST respond with ONLY a valid JSON object. No explanation, no markdown, no code fences, no text before or after the JSON.
The EXACT format is:
{"files":[{"path":"path/to/file.ext","content":"code content here"}]}
Rules:
- Output MUST start with { and end with }
- Include package.json, index.html, vite.config.ts, tailwind.config.js, postcss.config.js and src folder with necessary components
- Use React + Vite + TypeScript + Tailwind CSS stack
- Create a beautiful, modern UI with proper styling
- DO NOT generate package-lock.json, yarn.lock, or lock files
- DO NOT wrap the JSON in markdown code blocks`;

        userContent = `Build this application: ${job.prompt}

RESPOND WITH ONLY THE JSON OBJECT. NO OTHER TEXT.`;
    }

    // Retry logic for Gemini API (handles transient errors)
    const MAX_RETRIES = 3;
    let responseText = '';
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
        try {
            sendEvent('status', { step: attempt > 1 ? `Retrying AI generation (attempt ${attempt}/${MAX_RETRIES})...` : 'Generating code with AI...', progress: 20 });
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
            console.log(`🚀 Calling Gemini (${GEMINI_MODEL}) (attempt ${attempt}/${MAX_RETRIES})...`);
            console.log('⏱️  Start time:', new Date().toLocaleTimeString());

            const startTime = Date.now();

            const stream = await openai.chat.completions.create({
                model: GEMINI_MODEL,
                messages: [
                    { role: "system", content: systemPrompt },
                    { role: "user", content: userContent }
                ],
                temperature: 0.6,
                top_p: 1.0,
                max_tokens: 16384,
                stream: true
            });

            console.log('✅ Stream connection established, waiting for chunks...');

            // Collect streamed content chunks
            responseText = '';
            let chunkCount = 0;
            let reasoningCount = 0;
            for await (const chunk of stream) {
                const delta = chunk.choices[0]?.delta;
                const reasoning = (delta as any)?.reasoning_content;

                if (reasoning) {
                    reasoningCount++;
                    if (reasoningCount <= 3) {
                        console.log(`🧠 [Reasoning chunk #${reasoningCount}]:`, reasoning.substring(0, 80));
                    } else if (reasoningCount % 50 === 0) {
                        console.log(`🧠 [Reasoning... ${reasoningCount} chunks, ${((Date.now() - startTime) / 1000).toFixed(1)}s elapsed]`);
                    }
                }

                if (delta?.content) {
                    responseText += delta.content;
                    chunkCount++;
                    if (chunkCount <= 3) {
                        console.log(`📦 [Content chunk #${chunkCount}]:`, delta.content.substring(0, 100));
                    } else if (chunkCount % 50 === 0) {
                        console.log(`📦 [Content... ${chunkCount} chunks, ${responseText.length} chars, ${((Date.now() - startTime) / 1000).toFixed(1)}s elapsed]`);
                    }
                    if (chunkCount % 20 === 0) {
                        sendEvent('status', { step: 'AI is generating code...', progress: 20 + Math.min(25, Math.floor(chunkCount / 10)) });
                    }
                }
            }

            const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');
            console.log(`✅ Streaming complete in ${elapsed}s`);
            console.log(`📊 Content chunks: ${chunkCount}, Reasoning chunks: ${reasoningCount}`);
            console.log(`📏 Response length: ${responseText.length} chars`);
            console.log('📝 Preview:', responseText.substring(0, 200));
            console.log('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━');

            if (responseText.length > 0) {
                lastError = null;
                break; // Success — exit retry loop
            } else {
                throw new Error('Empty response from API');
            }

        } catch (err: any) {
            lastError = err;
            const status = err?.status || err?.statusCode || 'unknown';
            console.error(`❌ Attempt ${attempt}/${MAX_RETRIES} failed: ${status} - ${err.message}`);

            if (attempt < MAX_RETRIES) {
                const waitMs = attempt * 5000; // 5s, 10s backoff
                console.log(`⏳ Waiting ${waitMs / 1000}s before retry...`);
                sendEvent('status', { step: `API error (${status}), retrying in ${waitMs / 1000}s...`, progress: 15 });
                await new Promise(resolve => setTimeout(resolve, waitMs));
            }
        }
    }

    if (lastError || responseText.length === 0) {
        throw lastError || new Error('Failed to get response from AI after all retries');
    }

    sendEvent('status', { step: 'Parsing AI response...', progress: 50 });

    // Robust JSON extraction — handles markdown fences, preamble text, etc.
    const extractJSON = (text: string): string | null => {
        // Step 1: Strip markdown code fences
        let cleaned = text.replace(/```(?:json)?\s*/g, '').replace(/```/g, '').trim();

        // Step 2: Find the first '{' and use balanced brace matching to find the complete JSON object
        const startIdx = cleaned.indexOf('{');
        if (startIdx === -1) return null;

        let depth = 0;
        let inString = false;
        let escape = false;
        let endIdx = -1;

        for (let i = startIdx; i < cleaned.length; i++) {
            const ch = cleaned[i];

            if (escape) {
                escape = false;
                continue;
            }

            if (ch === '\\' && inString) {
                escape = true;
                continue;
            }

            if (ch === '"') {
                inString = !inString;
                continue;
            }

            if (inString) continue;

            if (ch === '{') depth++;
            else if (ch === '}') {
                depth--;
                if (depth === 0) {
                    endIdx = i;
                    break;
                }
            }
        }

        if (endIdx === -1) return null;
        return cleaned.substring(startIdx, endIdx + 1);
    };

    let jsonString = extractJSON(responseText);

    if (!jsonString) {
        console.error("Could not find JSON object in AI response. Preview:", responseText.substring(0, 500));
        throw new Error("Invalid response format from AI — no JSON object found");
    }

    let parsed: { files: Array<{ path: string; content: string }> };
    try {
        parsed = JSON.parse(jsonString);
    } catch (e) {
        console.error("JSON parse error:", (e as Error).message);
        console.error("Extracted JSON preview:", jsonString.substring(0, 500));
        throw new Error("Invalid response format from AI — malformed JSON");
    }

    // Validate structure
    if (!parsed.files || !Array.isArray(parsed.files) || parsed.files.length === 0) {
        console.error("Parsed JSON has no files array. Keys:", Object.keys(parsed));
        throw new Error("Invalid response format from AI — missing 'files' array");
    }

    // Filter out any invalid entries
    parsed.files = parsed.files.filter(f => f && typeof f.path === 'string' && typeof f.content === 'string');

    if (parsed.files.length === 0) {
        throw new Error("Invalid response format from AI — no valid file entries");
    }

    console.log(`Successfully parsed ${parsed.files.length} files from AI response`);

    sendEvent('status', { step: 'Creating project files...', progress: 70 });

    const projectPath = path.join(WORKSPACES_DIR, job.id);

    // Write files to disk
    const writtenFiles: Array<{ path: string; content: string }> = [];
    for (const file of parsed.files) {
        const filePath = path.join(projectPath, file.path);
        const dir = path.dirname(filePath);

        if (!fs.existsSync(dir)) {
            fs.mkdirSync(dir, { recursive: true });
        }

        fs.writeFileSync(filePath, file.content);
        writtenFiles.push({ path: file.path, content: file.content });

        sendEvent('file', { path: file.path, content: file.content });
    }

    sendEvent('status', { step: 'Saving project to database...', progress: 75 });

    // Save files to database for persistence
    try {
        await saveProjectFiles(job.id, writtenFiles);
        console.log(`Saved ${writtenFiles.length} files to database for project ${job.id}`);
    } catch (e) {
        console.error('Failed to save files to database:', e);
        // Don't fail the build if DB save fails - files are on disk
    }

    sendEvent('status', { step: 'Installing dependencies...', progress: 80 });

    // Start dev server for live preview
    const port = allocatePort();
    try {
        const devProcess = await startDevServer(job.id, projectPath, port);
        job.devPort = port;
        job.devProcess = devProcess;
        sendEvent('status', { step: 'Dev server started!', progress: 95 });
    } catch (e) {
        console.error('Failed to start dev server:', e);
    }

    sendEvent('status', { step: 'Build complete!', progress: 100 });

    return { projectId: job.id, files: writtenFiles, devPort: port };
};

// ================================
// BUILD ENDPOINTS
// ================================

// SSE endpoint for real-time build updates
app.get('/api/build/:id/stream', optionalAuth, (req, res) => {
    const jobId = req.params.id;
    const job = jobs.get(jobId);

    if (!job) {
        res.status(404).json({ error: 'Job not found' });
        return;
    }

    // Set SSE headers
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('Access-Control-Allow-Origin', '*');

    const sendEvent = (event: string, data: any) => {
        res.write(`event: ${event}\n`);
        res.write(`data: ${JSON.stringify(data)}\n\n`);
    };

    // Start processing
    sendEvent('status', { step: 'Starting build...', progress: 0 });
    job.status = 'processing';

    // Update DB status
    updateProjectStatus(job.id, 'processing').catch(console.error);

    // Check if this is a follow-up (job has existingFiles attached)
    const existingFiles = job.existingFiles;

    generateProject(job, sendEvent, existingFiles)
        .then(async (result) => {
            job.status = 'completed';
            job.result = { projectId: result.projectId };
            job.files = result.files;
            job.devPort = result.devPort;

            // Update DB
            await updateProjectStatus(job.id, 'completed', result.devPort).catch(console.error);

            sendEvent('complete', { projectId: job.id, devPort: result.devPort });
            res.end();
        })
        .catch(async (error) => {
            console.error(`Job ${jobId} failed:`, error);
            job.status = 'failed';
            job.error = error.message;

            // Update DB
            await updateProjectStatus(job.id, 'failed').catch(console.error);

            sendEvent('error', { message: error.message });
            res.end();
        });
});

// Start Build Job (new project)
app.post('/api/build/chat', requireAuth, async (req, res) => {
    try {
        const { prompt } = req.body;
        const userId = req.userId!;

        if (!prompt) {
            res.status(400).json({ error: 'No Prompt received' });
            return;
        }

        const jobId = generateId();
        const projectName = generateProjectName(prompt);

        // Create project in database
        await createProject(jobId, userId, projectName, prompt);

        const job: Job = {
            id: jobId,
            userId,
            status: 'queued',
            prompt
        };
        jobs.set(jobId, job);

        res.json({ jobId, status: 'queued' });
    } catch (error) {
        console.error("Error creating job:", error);
        res.status(500).json({ error: 'Failed to create job' });
    }
});

// Follow-up Build Job (iterate on existing project)
app.post('/api/build/chat/:id', requireAuth, async (req, res) => {
    try {
        const { prompt } = req.body;
        const userId = req.userId!;
        const existingProjectId = req.params.id;

        if (!prompt) {
            res.status(400).json({ error: 'No Prompt received' });
            return;
        }

        // Verify the project belongs to this user
        const project = await getProjectByIdAndUser(existingProjectId, userId);
        if (!project) {
            res.status(404).json({ error: 'Project not found' });
            return;
        }

        // Kill existing dev server if running
        killDevServerForJob(existingProjectId);

        // Gather existing project files for AI context
        let existingFiles: Array<{ path: string; content: string }> = [];
        const projectPath = path.join(WORKSPACES_DIR, existingProjectId);

        if (fs.existsSync(projectPath)) {
            // Read from filesystem
            const readFilesRecursive = (dir: string, basePath: string = ''): Array<{ path: string; content: string }> => {
                const results: Array<{ path: string; content: string }> = [];
                const entries = fs.readdirSync(dir);
                for (const entry of entries) {
                    if (['node_modules', '.git', 'package-lock.json', 'yarn.lock', 'dist', 'build'].includes(entry)) continue;
                    const fullPath = path.join(dir, entry);
                    const relativePath = basePath ? `${basePath}/${entry}` : entry;
                    const stats = fs.statSync(fullPath);
                    if (stats.isDirectory()) {
                        results.push(...readFilesRecursive(fullPath, relativePath));
                    } else {
                        try {
                            const content = fs.readFileSync(fullPath, 'utf-8');
                            results.push({ path: relativePath, content });
                        } catch {
                            // Skip binary files
                        }
                    }
                }
                return results;
            };
            existingFiles = readFilesRecursive(projectPath);
        } else {
            // Fallback to database
            const dbFiles = await getProjectFiles(existingProjectId);
            existingFiles = dbFiles
                .filter((f: any) => !['package-lock.json', 'yarn.lock'].includes(f.file_path))
                .map((f: any) => ({ path: f.file_path, content: f.content }));
        }

        // Reuse the same project ID — create an in-memory job entry
        const job: Job = {
            id: existingProjectId,
            userId,
            status: 'queued',
            prompt,
            existingFiles
        };
        jobs.set(existingProjectId, job);

        // Update the project prompt in DB to reflect the latest instruction
        await updateProjectStatus(existingProjectId, 'queued');

        res.json({ jobId: existingProjectId, status: 'queued', isFollowUp: true });
    } catch (error) {
        console.error("Error creating follow-up job:", error);
        res.status(500).json({ error: 'Failed to create follow-up job' });
    }
});

// List user's projects
app.get('/api/build/projects', requireAuth, async (req, res) => {
    try {
        const userId = req.userId!;
        const projects = await getProjectsByUser(userId);
        res.json({ projects });
    } catch (error) {
        console.error("Error fetching projects:", error);
        res.status(500).json({ error: 'Failed to fetch projects' });
    }
});

// Get single project
app.get('/api/build/projects/:id', requireAuth, async (req, res) => {
    try {
        const userId = req.userId!;
        const project = await getProjectByIdAndUser(req.params.id, userId);
        if (!project) {
            res.status(404).json({ error: 'Project not found' });
            return;
        }
        res.json({ project });
    } catch (error) {
        console.error("Error fetching project:", error);
        res.status(500).json({ error: 'Failed to fetch project' });
    }
});

// Check Job Status
app.get('/api/build/status/:id', requireAuth, async (req, res) => {
    try {
        const jobId = req.params.id;
        const job = jobs.get(jobId);

        if (!job) {
            // Try DB
            const project = await getProjectByIdAndUser(jobId, req.userId!);
            if (project) {
                res.json({
                    id: project.id,
                    status: project.status,
                    result: project.status === 'completed' ? { projectId: project.id } : undefined,
                });
                return;
            }
            res.status(404).json({ error: 'Job not found' });
            return;
        }

        res.json({
            id: job.id,
            status: job.status,
            result: job.result,
            error: job.error
        });
    } catch (error) {
        console.error("Error checking status:", error);
        res.status(500).json({ error: 'Failed to check status' });
    }
});

// Get File Structure - list files for a project
app.get('/api/build/files/:id', requireAuth, async (req, res) => {
    const projectId = req.params.id;
    const projectPath = path.join(WORKSPACES_DIR, projectId);

    // First try filesystem
    if (fs.existsSync(projectPath)) {
        const getFileStructure = (dir: string): any[] => {
            const files = fs.readdirSync(dir);
            return files
                .filter(file => file !== 'node_modules' && file !== '.git')
                .map(file => {
                    const filePath = path.join(dir, file);
                    const stats = fs.statSync(filePath);
                    const relativePath = path.relative(projectPath, filePath);

                    if (stats.isDirectory()) {
                        return {
                            name: file,
                            type: 'directory',
                            path: relativePath,
                            children: getFileStructure(filePath)
                        };
                    } else {
                        return {
                            name: file,
                            type: 'file',
                            path: relativePath
                        };
                    }
                });
        };

        try {
            const structure = getFileStructure(projectPath);
            res.json({ files: structure });
            return;
        } catch (error) {
            console.error("Error reading files from fs:", error);
        }
    }

    // Fallback: reconstruct from database
    try {
        const dbFiles = await getProjectFiles(projectId);
        if (dbFiles.length === 0) {
            res.status(404).json({ error: 'Project not found' });
            return;
        }

        // Build tree structure from flat file list
        const root: any[] = [];
        for (const file of dbFiles) {
            const parts = file.file_path.split('/');
            let current = root;

            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];
                const isFile = i === parts.length - 1;
                const pathSoFar = parts.slice(0, i + 1).join('/');

                let existing = current.find((n: any) => n.name === part);

                if (!existing) {
                    existing = {
                        name: part,
                        type: isFile ? 'file' : 'directory',
                        path: pathSoFar,
                        children: isFile ? undefined : []
                    };
                    current.push(existing);
                }

                if (!isFile && existing.children) {
                    current = existing.children;
                }
            }
        }

        res.json({ files: root });
    } catch (error) {
        console.error("Error reading files from DB:", error);
        res.status(500).json({ error: 'Failed to read files' });
    }
});

// Get File Content - catch-all route for nested file paths
app.get('/api/build/files/:id/*filepath', requireAuth, async (req, res) => {
    const projectId = req.params.id;
    // Extract the full file path from the URL (everything after /api/build/files/:id/)
    const prefix = `/api/build/files/${projectId}/`;
    const decodedPath = decodeURIComponent(req.url.split('?')[0]); // strip query params and decode
    const filePathParam = decodedPath.startsWith(prefix) ? decodedPath.slice(prefix.length) : null;

    if (!filePathParam) {
        res.status(400).json({ error: 'File path required' });
        return;
    }

    const projectPath = path.join(WORKSPACES_DIR, projectId);
    const fullPath = path.join(projectPath, filePathParam);

    // Security check to prevent directory traversal
    if (!fullPath.startsWith(projectPath)) {
        res.status(403).json({ error: 'Access denied' });
        return;
    }

    // Try filesystem first
    if (fs.existsSync(fullPath)) {
        try {
            const content = fs.readFileSync(fullPath, 'utf-8');
            res.json({ content });
            return;
        } catch (error) {
            console.error("Error reading file from fs:", error);
        }
    }

    // Fallback: database
    try {
        const content = await getProjectFileContent(projectId, filePathParam);
        if (content !== null) {
            res.json({ content });
            return;
        }
        res.status(404).json({ error: 'File not found' });
    } catch (error) {
        console.error("Error reading file content:", error);
        res.status(500).json({ error: 'Failed to read file content' });
    }
});

// Download project as ZIP
app.get('/api/build/download/:id', requireAuth, (req, res) => {
    const projectId = req.params.id;
    const projectPath = path.join(WORKSPACES_DIR, projectId);

    if (!fs.existsSync(projectPath)) {
        res.status(404).json({ error: 'Project not found' });
        return;
    }

    res.setHeader('Content-Type', 'application/zip');
    res.setHeader('Content-Disposition', `attachment; filename="${projectId}.zip"`);

    const archive = archiver('zip', { zlib: { level: 9 } });

    archive.on('error', (err) => {
        console.error('Archive error:', err);
        res.status(500).json({ error: 'Failed to create archive' });
    });

    archive.pipe(res);
    archive.directory(projectPath, false);
    archive.finalize();
});

// Start or restart dev server for a project
app.post('/api/build/start-dev/:id', requireAuth, async (req, res) => {
    const projectId = req.params.id;
    const userId = req.userId!;

    try {
        // Verify project belongs to user
        const project = await getProjectByIdAndUser(projectId, userId);
        if (!project) {
            res.status(404).json({ error: 'Project not found' });
            return;
        }

        let job = jobs.get(projectId);
        if (!job) {
            job = { id: projectId, userId, status: project.status as any, prompt: project.prompt };
            jobs.set(projectId, job);
        }

        // Kill existing dev server if running
        killDevServerForJob(projectId);

        const projectPath = path.join(WORKSPACES_DIR, projectId);

        // Ensure files exist on disk for Vite to serve
        if (!fs.existsSync(projectPath)) {
            const dbFiles = await getProjectFiles(projectId);
            if (dbFiles.length === 0) {
                res.status(404).json({ error: 'Project files not found' });
                return;
            }
            for (const file of dbFiles) {
                const filePath = path.join(projectPath, file.file_path);
                const dir = path.dirname(filePath);
                if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
                fs.writeFileSync(filePath, file.content);
            }
        }

        const port = allocatePort();
        const devProcess = await startDevServer(projectId, projectPath, port);
        job.devPort = port;
        job.devProcess = devProcess;

        // Update the DB with new port
        await updateProjectStatus(projectId, project.status, port).catch(console.error);

        res.json({ port });
    } catch (error) {
        console.error("Error starting dev server:", error);
        res.status(500).json({ error: 'Failed to start dev server' });
    }
});

// Kill dev server for a specific job
app.delete('/api/build/jobs/:id', requireAuth, (req, res) => {
    const jobId = req.params.id;
    const job = jobs.get(jobId);

    if (!job) {
        res.status(404).json({ error: 'Job not found' });
        return;
    }

    if (job.devProcess) {
        try {
            // Kill the process group
            process.kill(-job.devProcess.pid!, 'SIGTERM');
            job.devProcess = undefined;
            job.devPort = undefined;
            console.log(`Killed dev server for job ${jobId}`);
        } catch (e) {
            console.error(`Failed to kill dev server for ${jobId}:`, e);
        }
    }

    res.json({ success: true });
});

// Cleanup all dev servers
app.delete('/api/build/cleanup', requireAuth, (req, res) => {
    let killed = 0;
    for (const [jobId, job] of jobs) {
        if (job.devProcess) {
            try {
                process.kill(-job.devProcess.pid!, 'SIGTERM');
                job.devProcess = undefined;
                job.devPort = undefined;
                killed++;
            } catch (e) {
                console.error(`Failed to kill dev server for ${jobId}:`, e);
            }
        }
    }
    console.log(`Cleaned up ${killed} dev servers`);
    res.json({ success: true, killed });
});

// ================================
// NORMAL CHAT ENDPOINT
// ================================

app.post('/api/chat/message', requireAuth, async (req, res) => {
    try {
        const { message, history } = req.body;

        if (!message) {
            res.status(400).json({ error: 'No message provided' });
            return;
        }

        if (!getGeminiApiKey()) {
            res.status(500).json({ error: 'GEMINI_API_KEY or GOOGLE_API_KEY not configured' });
            return;
        }

        const openai = createGeminiOpenAI();

        // Build conversation context
        const conversationHistory = (history || []).map((msg: any) => ({
            role: msg.role === 'user' ? 'user' : 'assistant' as const,
            content: msg.content
        }));

        // Set SSE headers for streaming
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.setHeader('Access-Control-Allow-Origin', '*');

        const systemPrompt = `You are Kiwi AI — a world-class AI assistant that is helpful, accurate, and engaging.

Core principles:
- Be thorough yet concise. Provide complete answers without unnecessary filler.
- Use rich markdown formatting: headings (##), bold (**text**), bullet points, numbered lists, tables, and code blocks with language tags.
- For code: always use fenced code blocks with the language specified (e.g. \`\`\`python). Include brief comments in code. If showing a complete file, mention the filename.
- For math: use LaTeX notation with $...$ for inline and $$...$$ for block equations.
- Structure longer responses with clear sections using ## headings.
- When explaining concepts, use analogies and real-world examples to make things click.
- For comparisons, use tables.
- Be conversational and warm, but always precise and factual.
- If asked about building full apps/websites, suggest the user try Build mode for an interactive experience.
- End with a brief follow-up suggestion or question when appropriate to keep the conversation flowing.`;

        const stream = await openai.chat.completions.create({
            model: GEMINI_MODEL,
            messages: [
                { role: "system", content: systemPrompt },
                ...conversationHistory,
                { role: "user", content: message }
            ],
            temperature: 0.6,
            top_p: 0.9,
            max_tokens: 4096,
            stream: true,
        });

        for await (const chunk of stream) {
            const delta = chunk.choices[0]?.delta as { content?: string; reasoning_content?: string } | undefined;
            // Only stream final content (omit model reasoning / thinking deltas)
            if (delta?.content) {
                res.write(`data: ${JSON.stringify({ content: delta.content })}\n\n`);
            }
        }

        res.write(`data: [DONE]\n\n`);
        res.end();
    } catch (error) {
        console.error("Chat error:", error);
        // If headers not sent yet, send error as JSON
        if (!res.headersSent) {
            res.status(500).json({ error: 'Failed to process message' });
        } else {
            res.write(`data: ${JSON.stringify({ error: 'Stream error' })}\n\n`);
            res.end();
        }
    }
});

// ================================
// PREVIEW / STATIC
// ================================

// Serve generated projects statically
app.use('/preview', express.static(WORKSPACES_DIR));

// ================================
// GRACEFUL SHUTDOWN
// ================================

const cleanup = () => {
    console.log('\nShutting down, cleaning up dev servers...');
    for (const [jobId, job] of jobs) {
        if (job.devProcess) {
            try {
                process.kill(-job.devProcess.pid!, 'SIGTERM');
                console.log(`Killed dev server for ${jobId}`);
            } catch (e) {
                // Process might already be dead
            }
        }
    }
    process.exit(0);
};

process.on('SIGINT', cleanup);
process.on('SIGTERM', cleanup);

// ================================
// START SERVER
// ================================

const PORT = process.env.PORT || 4000;

const startServer = async () => {
    try {
        // Initialize database tables
        await initDb();

        app.listen(PORT, () => {
            console.log(`🚀 Server running on port ${PORT}`);
            console.log(`📁 Workspaces directory: ${WORKSPACES_DIR}`);
        });
    } catch (error) {
        console.error('Failed to start server:', error);
        process.exit(1);
    }
};

startServer();
