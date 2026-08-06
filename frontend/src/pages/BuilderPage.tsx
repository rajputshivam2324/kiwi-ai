import { useState, useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, Loader2, Code, Eye, FileCode, Folder, ChevronRight, ChevronDown, Trash2 } from 'lucide-react';
import { useAuth, UserButton } from '@clerk/clerk-react';
import { CodeEditor } from '../components/CodeEditor';
import { Preview } from '../components/Preview';
import { FileTree } from '../components/FileTree';
import { DownloadButton } from '../components/DownloadButton';
import type { FileNode } from '../components/FileTree';
import { API_URL, authHeaders } from '../lib/api';

export const BuilderPage = () => {
    const { getToken, isLoaded } = useAuth();
    const location = useLocation();
    const initialPrompt = location.state?.initialPrompt || '';
    const loadProjectId = location.state?.loadProjectId || null;
    const hasStartedRef = useRef(false);

    const [messages, setMessages] = useState<{ role: 'user' | 'assistant', content: string }[]>([]);
    const [currentPrompt, setCurrentPrompt] = useState('');
    const [isBuilding, setIsBuilding] = useState(false);

    // Project State
    const [jobId, setJobId] = useState<string | null>(null);
    const [files, setFiles] = useState<FileNode[]>([]);
    const [selectedFile, setSelectedFile] = useState<string | null>(null);
    const [fileContent, setFileContent] = useState<string>("// Select a file to view code");
    const [previewUrl, setPreviewUrl] = useState<string | null>(null);
    const [isStartingDev, setIsStartingDev] = useState(false);
    const [buildStep, setBuildStep] = useState<string>("");
    const [buildProgress, setBuildProgress] = useState<number>(0);
    const [streamingFiles, setStreamingFiles] = useState<{ path: string; content: string }[]>([]);

    // Tab state for code/preview toggle
    const [activeTab, setActiveTab] = useState<'code' | 'preview'>('code');

    // Build log messages for enhanced chat
    const [buildLogs, setBuildLogs] = useState<string[]>([]);

    // Projects panel state
    const [projects, setProjects] = useState<Array<{ id: string; name: string; status: string; created_at: string }>>([]);
    const [showProjects, setShowProjects] = useState(true);

    // Fetch user's projects when auth is loaded
    useEffect(() => {
        if (isLoaded) {
            fetchProjects();
        }
    }, [isLoaded]);

    const fetchProjects = async () => {
        try {
            const headers = await authHeaders(getToken);
            const res = await fetch(`${API_URL}/api/build/projects`, { headers });
            if (res.ok) {
                const data = await res.json();
                setProjects(data.projects || []);
            }
        } catch (e) {
            console.error("Failed to fetch projects", e);
        }
    };

    const startDevServerForProject = async (id: string) => {
        setIsStartingDev(true);
        try {
            const headers = await authHeaders(getToken);
            const res = await fetch(`${API_URL}/api/build/start-dev/${id}`, {
                method: 'POST',
                headers,
            });
            if (res.ok) {
                const data = await res.json();
                setPreviewUrl(`http://localhost:${data.port}`);
                const evicted = Array.isArray(data.evicted) ? data.evicted.length : 0;
                setBuildLogs(prev => [
                    ...prev,
                    `✅ Preview running on port ${data.port}`,
                    ...(evicted
                        ? [`ℹ️ Freed disk from ${evicted} other live preview(s) (budget limit)`]
                        : []),
                ]);
            } else {
                setPreviewUrl(null);
                setBuildLogs(prev => [...prev, '❌ Failed to start preview server']);
            }
        } catch (e) {
            console.error("Failed to restart dev server", e);
            setPreviewUrl(null);
        } finally {
            setIsStartingDev(false);
        }
    };

    const deleteProject = async (projectId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        if (!confirm('Delete this project? Source and preview files will be removed.')) {
            return;
        }
        try {
            const headers = await authHeaders(getToken);
            const res = await fetch(`${API_URL}/api/build/projects/${projectId}`, {
                method: 'DELETE',
                headers,
            });
            if (!res.ok) {
                setBuildLogs(prev => [...prev, '❌ Failed to delete project']);
                return;
            }
            if (jobId === projectId) {
                setJobId(null);
                setFiles([]);
                setSelectedFile(null);
                setFileContent('// Select a file to view code');
                setPreviewUrl(null);
                setMessages([]);
                setBuildLogs([]);
                setStreamingFiles([]);
            }
            await fetchProjects();
            setBuildLogs(prev => [...prev, '🗑️ Project deleted (DB + disk cleaned)']);
        } catch (err) {
            console.error('Failed to delete project', err);
        }
    };

    const loadProject = async (projectId: string) => {
        setJobId(projectId);

        // Also fetch project details to get prompt
        try {
            const headers = await authHeaders(getToken);
            const res = await fetch(`${API_URL}/api/build/projects/${projectId}`, { headers });
            if (res.ok) {
                const data = await res.json();
                setMessages([{ role: 'user', content: data.project.prompt }]);
            }
        } catch (e) {
            console.error("Failed to fetch project details", e);
        }

        await fetchFiles(projectId);
        setActiveTab('code');
        startDevServerForProject(projectId);
    };

    // Keep idle TTL from killing an open preview session
    useEffect(() => {
        if (!jobId || !previewUrl || !isLoaded) return;
        let cancelled = false;
        const beat = async () => {
            try {
                const headers = await authHeaders(getToken);
                if (cancelled) return;
                await fetch(`${API_URL}/api/build/status/${jobId}`, { headers });
            } catch {
                /* ignore */
            }
        };
        beat();
        const id = window.setInterval(beat, 120_000);
        return () => {
            cancelled = true;
            window.clearInterval(id);
        };
    }, [jobId, previewUrl, isLoaded, getToken]);

    // Handle initial routing (new prompt or loading existing project)
    useEffect(() => {
        if (isLoaded && !hasStartedRef.current) {
            if (loadProjectId) {
                hasStartedRef.current = true;
                loadProject(loadProjectId);
            } else if (initialPrompt) {
                hasStartedRef.current = true;
                setMessages([{ role: 'user', content: initialPrompt }]);
                handleSend(initialPrompt);
            }
        }
    }, [isLoaded, initialPrompt, loadProjectId]);

    const handleSend = async (prompt: string) => {
        if (!prompt.trim()) return;

        const isFollowUp = !!jobId;

        const newMsg = { role: 'user' as const, content: prompt };
        if (prompt !== initialPrompt) {
            setMessages(prev => [...prev, newMsg]);
        }

        setCurrentPrompt('');
        setIsBuilding(true);
        setBuildStep(isFollowUp ? "Updating project..." : "Creating job...");
        setBuildProgress(0);
        setStreamingFiles([]);
        // On follow-up, keep existing files visible; on new build, clear them
        if (!isFollowUp) {
            setFiles([]);
        }
        setBuildLogs([isFollowUp ? '🔄 Updating existing project...' : '🚀 Starting build process...']);
        setActiveTab('code');

        try {
            const token = await getToken();
            const headers = await authHeaders(getToken);

            const endpoint = isFollowUp
                ? `${API_URL}/api/build/chat/${jobId}`
                : `${API_URL}/api/build/chat`;

            const res = await fetch(endpoint, {
                method: 'POST',
                headers,
                body: JSON.stringify({ prompt })
            });

            if (!res.ok) throw new Error('Failed to create job');

            const data = await res.json();
            const activeJobId = data.jobId;
            setJobId(activeJobId);

            // Fetch projects to update sidebar
            fetchProjects();

            // Start SSE connection for real-time updates with auth token
            const sseUrl = new URL(`${API_URL}/api/build/${activeJobId}/stream`);
            if (token) {
                sseUrl.searchParams.append('token', token);
            }
            const eventSource = new EventSource(sseUrl.toString());

            eventSource.addEventListener('status', (event) => {
                const data = JSON.parse(event.data);
                setBuildStep(data.step);
                setBuildProgress(data.progress);
            });

            eventSource.addEventListener('file', (event) => {
                const data = JSON.parse(event.data);
                setStreamingFiles(prev => [...prev, data]);
                setBuildLogs(prev => [...prev, `📄 ${isFollowUp ? 'Updated' : 'Created'}: ${data.path}`]);
            });

            eventSource.addEventListener('build_error', (event) => {
                const data = JSON.parse((event as MessageEvent).data);
                const snippet = (data.message || '').slice(0, 300);
                setBuildLogs(prev => [...prev, `⚠️ Build issue detected — auto-fixing…`, snippet]);
            });

            eventSource.addEventListener('complete', async (event) => {
                const data = JSON.parse((event as MessageEvent).data);
                eventSource.close();
                setIsBuilding(false);

                const previewReady = Boolean(data.previewReady && data.devPort);
                const fixNote = data.fixRounds ? ` (auto-fixed ${data.fixRounds} build issue${data.fixRounds > 1 ? 's' : ''})` : '';

                if (previewReady) {
                    setPreviewUrl(`http://localhost:${data.devPort}`);
                    setMessages(prev => [...prev, {
                        role: 'assistant',
                        content: isFollowUp
                            ? `Project updated and preview is live${fixNote}!`
                            : `Build complete — preview is live${fixNote}! Explore the code or open Preview.`,
                    }]);
                    setBuildLogs(prev => [...prev, `✅ Preview ready on port ${data.devPort}`]);
                    setTimeout(() => setActiveTab('preview'), 500);
                } else {
                    setPreviewUrl(null);
                    setMessages(prev => [...prev, {
                        role: 'assistant',
                        content: isFollowUp
                            ? 'Files updated but preview could not start. Use the chat to describe the error, or click Refresh in Preview after fixing.'
                            : 'Code generated but preview failed verification. Ask me to fix build errors, or try "Restart Preview" from the Preview tab.',
                    }]);
                    if (data.buildWarning) {
                        setBuildLogs(prev => [...prev, `❌ ${String(data.buildWarning).slice(0, 400)}`]);
                    }
                }

                await fetchFiles(activeJobId);
                fetchProjects();
            });

            eventSource.addEventListener('error', (event: Event) => {
                eventSource.close();
                setIsBuilding(false);
                let errorMessage = "Something went wrong during the build.";
                try {
                    const messageEvent = event as MessageEvent;
                    const data = JSON.parse(messageEvent.data);
                    if (data?.message) {
                        errorMessage = `Build failed: ${data.message}`;
                    }
                } catch {
                    // Use default message if parsing fails
                }
                setMessages(prev => [...prev, {
                    role: 'assistant',
                    content: errorMessage
                }]);
                fetchProjects(); // Update failure status
            });

            eventSource.onerror = () => {
                eventSource.close();
                setIsBuilding(false);
            };

        } catch (e) {
            console.error("Failed to start build", e);
            setIsBuilding(false);
            setMessages(prev => [...prev, { role: 'assistant', content: "Failed to connect to the builder service." }]);
        }
    };

    const fetchFiles = async (id: string) => {
        try {
            const headers = await authHeaders(getToken);
            const res = await fetch(`${API_URL}/api/build/files/${id}`, { headers });
            if (res.ok) {
                const data = await res.json();
                setFiles(data.files);

                // Auto-select the first file
                const firstFile = findFirstFile(data.files);
                if (firstFile) {
                    handleFileSelect(firstFile.path);
                }
            }
        } catch (e) {
            console.error("Failed to fetch files", e);
        }
    };

    const findFirstFile = (nodes: FileNode[]): FileNode | null => {
        for (const node of nodes) {
            if (node.type === 'file') return node;
            if (node.children) {
                const found = findFirstFile(node.children);
                if (found) return found;
            }
        }
        return null;
    };

    const handleFileSelect = async (path: string) => {
        setSelectedFile(path);

        // First check streaming files
        const streamedFile = streamingFiles.find(f => f.path === path);
        if (streamedFile) {
            setFileContent(streamedFile.content);
            return;
        }

        // Otherwise fetch from server
        if (!jobId) return;
        try {
            const headers = await authHeaders(getToken);
            const encodedPath = path.split('/').map(seg => encodeURIComponent(seg)).join('/');
            const res = await fetch(`${API_URL}/api/build/files/${jobId}/${encodedPath}`, { headers });
            if (res.ok) {
                const data = await res.json();
                setFileContent(data.content);
            } else {
                setFileContent("// Failed to load content");
            }
        } catch (e) {
            console.error("Failed to fetch file content", e);
            setFileContent("// Failed to load content");
        }
    };

    // Convert streaming files to tree structure for display during build
    const streamingFilesToTree = (): FileNode[] => {
        const root: FileNode[] = [];

        for (const file of streamingFiles) {
            const parts = file.path.split('/');
            let current = root;

            for (let i = 0; i < parts.length; i++) {
                const part = parts[i];
                const isFile = i === parts.length - 1;
                const pathSoFar = parts.slice(0, i + 1).join('/');

                let existing = current.find(n => n.name === part);

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

        return root;
    };

    const displayFiles = files.length > 0 ? files : streamingFilesToTree();

    return (
        <div className="h-screen w-full bg-zinc-950 flex overflow-hidden">
            {/* LEFT PANEL - CHAT */}
            <div className="w-[350px] flex flex-col border-r border-zinc-800 bg-zinc-950 flex-shrink-0">
                <div className="h-14 border-b border-zinc-800 flex items-center px-4 justify-between">
                    <div className="flex items-center gap-2 text-zinc-100 font-semibold">
                        <div className="w-6 h-6 rounded bg-gradient-to-br from-indigo-600 to-purple-600 flex items-center justify-center text-xs">L</div>
                        <span>Kiwi AI</span>
                    </div>
                </div>

                {/* Projects Panel */}
                <div className="border-b border-zinc-800">
                    <button
                        onClick={() => setShowProjects(!showProjects)}
                        className="w-full flex items-center justify-between px-4 py-3 text-zinc-300 hover:bg-zinc-900/50 transition-colors"
                    >
                        <div className="flex items-center gap-2">
                            <Folder className="w-4 h-4" />
                            <span className="text-sm font-medium">Projects</span>
                        </div>
                        {showProjects ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </button>
                    <AnimatePresence>
                        {showProjects && (
                            <motion.div
                                initial={{ height: 0 }}
                                animate={{ height: 'auto' }}
                                exit={{ height: 0 }}
                                className="overflow-hidden"
                            >
                                <div className="px-2 pb-2 max-h-48 overflow-y-auto">
                                    {projects.length === 0 ? (
                                        <div className="px-4 py-3 text-xs text-zinc-500">
                                            No projects yet. Start building!
                                        </div>
                                    ) : (
                                        projects.map((project) => (
                                            <div
                                                key={project.id}
                                                className={`w-full flex items-center gap-1 px-2 py-1 rounded-md text-sm transition-colors ${jobId === project.id
                                                    ? 'bg-indigo-600/20 text-indigo-300'
                                                    : 'text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'
                                                    }`}
                                            >
                                                <button
                                                    type="button"
                                                    onClick={() => loadProject(project.id)}
                                                    className="flex flex-1 items-center gap-2 min-w-0 px-2 py-1 text-left"
                                                >
                                                    <FileCode className="w-4 h-4 flex-shrink-0" />
                                                    <span className="truncate flex-1">{project.name}</span>
                                                    <span className={`text-xs px-1.5 py-0.5 rounded flex-shrink-0 ${project.status === 'completed'
                                                        ? 'bg-green-500/20 text-green-400'
                                                        : project.status === 'failed'
                                                            ? 'bg-red-500/20 text-red-400'
                                                            : 'bg-yellow-500/20 text-yellow-400'
                                                        }`}>
                                                        {project.status === 'processing' ? 'building' : project.status}
                                                    </span>
                                                </button>
                                                <button
                                                    type="button"
                                                    title="Delete project"
                                                    onClick={(e) => deleteProject(project.id, e)}
                                                    className="p-1.5 rounded text-zinc-500 hover:text-red-400 hover:bg-red-500/10 flex-shrink-0"
                                                >
                                                    <Trash2 className="w-3.5 h-3.5" />
                                                </button>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-6">
                    {messages.map((msg, idx) => (
                        <motion.div
                            key={idx}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className={`flex flex-col gap-2 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}
                        >
                            <div className={`max-w-[85%] p-3 rounded-xl text-sm ${msg.role === 'user' ? 'bg-zinc-800 text-zinc-200' : 'text-zinc-300'}`}>
                                {msg.content}
                            </div>
                        </motion.div>
                    ))}

                    {isBuilding && (
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
                            {/* Progress Header */}
                            <div className="flex items-center gap-2 text-zinc-300 text-sm font-medium">
                                <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                                <span>{buildStep}</span>
                            </div>

                            {/* Progress Bar */}
                            <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
                                <motion.div
                                    className="h-full bg-gradient-to-r from-indigo-500 to-purple-500"
                                    initial={{ width: 0 }}
                                    animate={{ width: `${buildProgress}%` }}
                                    transition={{ duration: 0.3 }}
                                />
                            </div>

                            {/* Build Logs */}
                            <div className="bg-zinc-900/50 rounded-lg p-3 max-h-40 overflow-y-auto space-y-1">
                                <AnimatePresence>
                                    {buildLogs.map((log, idx) => (
                                        <motion.div
                                            key={idx}
                                            initial={{ opacity: 0, x: -10 }}
                                            animate={{ opacity: 1, x: 0 }}
                                            className="text-xs text-zinc-400 font-mono flex items-center gap-2"
                                        >
                                            {log}
                                        </motion.div>
                                    ))}
                                </AnimatePresence>
                            </div>

                            {/* File Count */}
                            {streamingFiles.length > 0 && (
                                <div className="flex items-center gap-2 text-xs text-zinc-500">
                                    <FileCode size={12} />
                                    <span>{streamingFiles.length} files generated</span>
                                </div>
                            )}
                        </motion.div>
                    )}
                </div>

                {/* Chat Input */}
                <div className="p-4 border-t border-zinc-800 bg-zinc-950/50 backdrop-blur">
                    <div className="relative">
                        <input
                            type="text"
                            value={currentPrompt}
                            onChange={(e) => setCurrentPrompt(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleSend(currentPrompt)}
                            placeholder="Describe what to change..."
                            className="w-full bg-zinc-900 border border-zinc-800 rounded-lg pl-4 pr-12 py-3 text-sm text-zinc-300 focus:outline-none focus:ring-1 focus:ring-zinc-700"
                        />
                        <button
                            onClick={() => handleSend(currentPrompt)}
                            className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 bg-zinc-800 rounded-md text-zinc-400 hover:text-white transition-colors"
                        >
                            <ArrowUp className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </div>

            {/* RIGHT PANEL - WORKSPACE */}
            <div className="flex-1 flex flex-col bg-zinc-950 min-w-0">
                <div className="h-14 border-b border-zinc-800 flex items-center justify-between px-4 bg-zinc-950">
                    <div className="flex items-center gap-4">
                        <span className="text-sm text-zinc-400">Workspace</span>
                        {isBuilding && (
                            <span className="text-xs text-indigo-400 flex items-center gap-1">
                                <span className="w-2 h-2 bg-indigo-400 rounded-full animate-pulse"></span>
                                Building...
                            </span>
                        )}
                    </div>

                    {/* Tab Toggle Buttons */}
                    <div className="flex items-center gap-3">
                        <div className="flex bg-zinc-900 rounded-lg p-1 border border-zinc-800">
                            <button
                                onClick={() => setActiveTab('code')}
                                className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${activeTab === 'code'
                                    ? 'bg-zinc-700 text-white shadow-sm'
                                    : 'text-zinc-400 hover:text-zinc-200'
                                    }`}
                            >
                                <Code size={14} />
                                Code
                            </button>
                            <button
                                onClick={() => setActiveTab('preview')}
                                className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-all ${activeTab === 'preview'
                                    ? 'bg-zinc-700 text-white shadow-sm'
                                    : 'text-zinc-400 hover:text-zinc-200'
                                    }`}
                            >
                                <Eye size={14} />
                                Preview
                            </button>
                        </div>

                        <DownloadButton jobId={jobId} disabled={isBuilding || !jobId} />

                        <UserButton
                            appearance={{
                                elements: {
                                    userButtonAvatarBox: "w-8 h-8 rounded-full border border-zinc-700",
                                }
                            }}
                        />
                    </div>
                </div>

                <div className="flex-1 flex overflow-hidden">
                    {/* File Tree Sidebar */}
                    <div className="w-64 border-r border-zinc-800 bg-zinc-900/30 p-2 flex flex-col">
                        <div className="text-xs font-semibold text-zinc-500 mb-2 px-2 uppercase tracking-wider">Explorer</div>
                        <FileTree
                            files={displayFiles}
                            onSelectFile={handleFileSelect}
                            selectedFile={selectedFile}
                            isLoading={isBuilding && streamingFiles.length === 0}
                        />
                    </div>

                    {/* Main Content Area */}
                    <div className="flex-1 flex flex-col min-w-0">
                        {/* Editor & Preview Split - Now Tab Based */}
                        <div className="flex-1 flex">
                            {/* Code Editor - Only show when code tab is active */}
                            {activeTab === 'code' && (
                                <motion.div
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="flex-1 border-r border-zinc-800 flex flex-col min-w-0"
                                >
                                    <CodeEditor
                                        code={fileContent}
                                        fileName={selectedFile || undefined}
                                        language={
                                            selectedFile?.endsWith('.css') ? 'css' :
                                                selectedFile?.endsWith('.json') ? 'json' :
                                                    selectedFile?.endsWith('.html') ? 'html' :
                                                        selectedFile?.endsWith('.tsx') || selectedFile?.endsWith('.ts') ? 'typescript' :
                                                            selectedFile?.endsWith('.jsx') || selectedFile?.endsWith('.js') ? 'javascript' :
                                                                'typescript'
                                        }
                                    />
                                </motion.div>
                            )}

                            {/* Preview - Only show when preview tab is active */}
                            {activeTab === 'preview' && (
                                <motion.div
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="flex-1 flex flex-col min-w-0 bg-white"
                                >
                                    <Preview
                                        url={previewUrl}
                                        isBuilding={isBuilding}
                                        isStarting={isStartingDev}
                                        onRefresh={() => jobId && startDevServerForProject(jobId)}
                                    />
                                </motion.div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
