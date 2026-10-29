import { useAuth, useUser, UserButton } from '@clerk/clerk-react';
import { useNavigate } from 'react-router-dom';
import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Plus,
    ArrowUp,
    Mic,
    Plus as PlusIcon,
    FileText,
    TrendingUp,
    Code,
    X,
    PanelLeft,
    Loader2,
    BookOpen,
    Trash2,
    Search,
    MessageSquare,
    Copy,
    Check,
    ThumbsUp,
    ThumbsDown,
    RefreshCw,
    Sparkles
} from 'lucide-react';

import { FinanceCard } from '../components/FinanceCard';
import { MarkdownRenderer } from '../components/MarkdownRenderer';
import { API_URL, authHeaders } from '../lib/api';
import '../styles/chat-ui.css';

type Mode = 'normal' | 'build' | 'arxiv' | 'finance';

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    agent?: { id: string; name: string; emoji: string };
    toolResults?: Array<{ name: string; data: any }>;
    sources?: any[];
}

interface RecentProject {
    id: string;
    name: string;
    status: string;
}

interface ArxivConversation {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
    message_count: number;
}

export const ChatPage = () => {
    const { getToken, isLoaded } = useAuth();
    const { user } = useUser();
    const navigate = useNavigate();
    const [prompt, setPrompt] = useState('');
    const [selectedMode, setSelectedMode] = useState<Mode>('normal');
    const [messages, setMessages] = useState<Message[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [uploadedFiles, setUploadedFiles] = useState<File[]>([]);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [recentProjects, setRecentProjects] = useState<RecentProject[]>([]);
    const [mcpOnline, setMcpOnline] = useState(false);

    // Arxiv conversation state
    const [arxivConversations, setArxivConversations] = useState<ArxivConversation[]>([]);
    const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
    const [normalConversationId, setNormalConversationId] = useState<string | null>(null);
    const [arxivOnline, setArxivOnline] = useState(false);
    const [streamStatus, setStreamStatus] = useState<string | null>(null);
    const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
    const [likedMessages, setLikedMessages] = useState<Set<string>>(new Set());
    const [dislikedMessages, setDislikedMessages] = useState<Set<string>>(new Set());

    const handleCopyMessage = async (id: string, content: string) => {
        try {
            await navigator.clipboard.writeText(content);
            setCopiedMessageId(id);
            setTimeout(() => setCopiedMessageId(null), 2000);
        } catch (err) {
            console.error('Failed to copy', err);
        }
    };

    // Check grow-mcp health and fetch projects on mount
    useEffect(() => {
        if (isLoaded && user) {
            fetchProjects();
            checkMcpHealth();
            checkArxivHealth();
            fetchArxivConversations();
        }
    }, [isLoaded, user]);

    const checkMcpHealth = async () => {
        try {
            const res = await fetch(`${API_URL}/health`);
            if (res.ok) {
                setMcpOnline(true);
            }
        } catch (e) {
            console.error('grow-mcp backend not reachable', e);
            setMcpOnline(false);
        }
    };

    const checkArxivHealth = async () => {
        try {
            const res = await fetch(`${API_URL}/`);
            if (res.ok) {
                setArxivOnline(true);
            }
        } catch (e) {
            console.error('arxiv backend not reachable', e);
            setArxivOnline(false);
        }
    };

    const fetchProjects = async () => {
        try {
            const headers = await authHeaders(getToken);
            const res = await fetch(`${API_URL}/api/build/projects`, { headers });
            if (res.ok) {
                const data = await res.json();
                setRecentProjects(data.projects.slice(0, 5) || []);
            }
        } catch (e) {
            console.error("Failed to fetch projects", e);
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
            if (res.ok) {
                await fetchProjects();
            }
        } catch (err) {
            console.error('Failed to delete project', err);
        }
    };

    const fetchArxivConversations = useCallback(async () => {
        if (!user?.id) return;
        try {
            const res = await fetch(`${API_URL}/conversations?user_id=${user.id}`, { headers: await authHeaders(getToken) });
            if (res.ok) {
                const data = await res.json();
                setArxivConversations(data.conversations || []);
            }
        } catch (e) {
            console.error("Failed to fetch arxiv conversations", e);
        }
    }, [user?.id, getToken]);

    const loadConversation = async (conversationId: string) => {
        try {
            const res = await fetch(`${API_URL}/conversations/${conversationId}/messages`, { headers: await authHeaders(getToken) });
            if (!res.ok) throw new Error('Failed to load conversation');
            const data = await res.json();

            const loadedMessages: Message[] = (data.messages || [])
                .filter((m: any) => m.role !== 'system')
                .map((m: any) => ({
                    id: m.id,
                    role: m.role as 'user' | 'assistant',
                    content: m.content,
                    sources: m.sources || [],
                }));

            setMessages(loadedMessages);
            setActiveConversationId(conversationId);
            setSelectedMode('arxiv');
        } catch (e) {
            console.error("Failed to load conversation", e);
        }
    };

    const deleteArxivConversation = async (conversationId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            await fetch(`${API_URL}/conversations/${conversationId}`, {
                method: 'DELETE', headers: await authHeaders(getToken)
            });
            setArxivConversations(prev => prev.filter(c => c.id !== conversationId));
            if (activeConversationId === conversationId) {
                setMessages([]);
                setActiveConversationId(null);
                setNormalConversationId(null);
            }
        } catch (e) {
            console.error("Failed to delete conversation", e);
        }
    };

    useEffect(() => {
        // Smooth auto-scroll that triggers whenever messages update
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [messages]);

    const handleModeSelect = (mode: Mode) => {
        setSelectedMode(selectedMode === mode ? 'normal' : mode);
    };

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        if (e.target.files) {
            const newFiles = Array.from(e.target.files);
            setUploadedFiles(prev => [...prev, ...newFiles]);
        }
    };

    const removeUploadedFile = (index: number) => {
        setUploadedFiles(prev => prev.filter((_, i) => i !== index));
    };

    const handleFinanceSubmit = async (userMessage: Message) => {
        try {
            const mcpMessages = messages
                .concat(userMessage)
                .map(msg => ({
                    role: msg.role === 'assistant' ? 'model' as const : 'user' as const,
                    content: msg.content
                }));

            const res = await fetch(`${API_URL}/api/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: mcpMessages })
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.error || 'Network response was not ok');
            }

            const reader = res.body?.getReader();
            const decoder = new TextDecoder();
            if (!reader) throw new Error('No reader available');

            const aiMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: ''
            };

            setMessages(prev => [...prev, aiMessage]);
            setIsLoading(false);

            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6).trim();
                        if (dataStr === '[DONE]') continue;

                        try {
                            const data = JSON.parse(dataStr);

                            setMessages(prev => prev.map(msg => {
                                if (msg.id !== aiMessage.id) return msg;

                                const updatedMsg = { ...msg };

                                if (data.type === 'agent') {
                                    updatedMsg.agent = data.agent;
                                } else if (data.type === 'text') {
                                    if (data.overwrite) {
                                        updatedMsg.content = data.content;
                                    } else {
                                        updatedMsg.content = data.content;
                                    }
                                } else if (data.type === 'tools') {
                                    updatedMsg.toolResults = data.toolResults;
                                } else if (data.error) {
                                    updatedMsg.content += '\\n\\n**[Error]** ' + data.error;
                                }

                                return updatedMsg;
                            }));
                        } catch (e) {
                            console.error('Error parsing finance stream chunk', e);
                        }
                    }
                }
            }
        } catch (error) {
            console.error('Finance chat error:', error);
            setIsLoading(false);
            setMessages(prev => [...prev, {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: 'Sorry, I encountered an error with the finance assistant. Ensure the unified backend is running and Groww MCP is connected.'
            }]);
        }
    };

    const handleArxivSubmit = async (userMessage: Message) => {
        try {
            const res = await fetch(`${API_URL}/chat/stream`, {
                method: 'POST',
                headers: await authHeaders(getToken),
                body: JSON.stringify({
                    message: userMessage.content,
                    conversation_id: activeConversationId || undefined,
                    user_id: user?.id || 'anonymous',
                })
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || 'Arxiv backend error');
            }

            const reader = res.body?.getReader();
            const decoder = new TextDecoder();
            if (!reader) throw new Error('No reader available');

            const aiMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: '',
                agent: { id: 'arxiv', name: 'Kiwi Research', emoji: '📚' },
            };

            setMessages(prev => [...prev, aiMessage]);
            setIsLoading(false);

            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';  // Keep incomplete line in buffer

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6).trim();
                        if (dataStr === '[DONE]') {
                            setStreamStatus(null);
                            continue;
                        }

                        try {
                            const data = JSON.parse(dataStr);

                            if (data.type === 'conversation_id') {
                                setActiveConversationId(data.data);
                            } else if (data.type === 'status') {
                                setStreamStatus(data.data);
                            } else if (data.type === 'tool_result') {
                                // Could display tool badges in the future
                                console.log('Tool result:', data.data);
                            } else if (data.type === 'sources') {
                                setMessages(prev => prev.map(msg =>
                                    msg.id === aiMessage.id
                                        ? { ...msg, sources: data.data }
                                        : msg
                                ));
                            } else if (data.type === 'content') {
                                setMessages(prev => prev.map(msg =>
                                    msg.id === aiMessage.id
                                        ? { ...msg, content: msg.content + (data.data || '') }
                                        : msg
                                ));
                            } else if (data.type === 'reasoning') {
                                // Skip reasoning content
                            } else if (data.type === 'error') {
                                setMessages(prev => prev.map(msg =>
                                    msg.id === aiMessage.id
                                        ? { ...msg, content: msg.content + '\n\n**⚠️ Error:** ' + data.data }
                                        : msg
                                ));
                            }
                        } catch (e) {
                            console.error('Error parsing arxiv stream chunk', e);
                        }
                    }
                }
            }

            // Refresh conversation list after stream
            setStreamStatus(null);
            fetchArxivConversations();

        } catch (error) {
            console.error('Arxiv chat error:', error);
            setIsLoading(false);
            setStreamStatus(null);
            setMessages(prev => [...prev, {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: 'Sorry, I could not reach the research service. Ensure the unified backend is running on port 8000.',
            }]);
        }
    };


    const handleNormalSubmit = async (userMessage: Message) => {
        try {
            const headers = await authHeaders(getToken);
            const res = await fetch(`${API_URL}/api/chat/message`, {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    message: userMessage.content,
                    history: messages,
                    conversation_id: normalConversationId || undefined
                })
            });

            if (!res.ok) throw new Error('Network response was not ok');

            const reader = res.body?.getReader();
            const decoder = new TextDecoder();

            if (!reader) throw new Error('No reader available');

            const aiMessage: Message = {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: '',
                agent: { id: 'kiwi', name: 'Kiwi AI', emoji: '🥝' }
            };

            setMessages(prev => [...prev, aiMessage]);
            setIsLoading(false);

            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6).trim();
                        if (dataStr === '[DONE]') continue;

                        try {
                            const data = JSON.parse(dataStr);
                            if (data.conversation_id) {
                                setNormalConversationId(data.conversation_id);
                            } else if (data.content) {
                                setMessages(prev => prev.map(msg =>
                                    msg.id === aiMessage.id
                                        ? { ...msg, content: msg.content + data.content }
                                        : msg
                                ));
                            } else if (data.error) {
                                setMessages(prev => prev.map(msg =>
                                    msg.id === aiMessage.id
                                        ? { ...msg, content: msg.content + '\n\n**⚠️ Error:** ' + data.error }
                                        : msg
                                ));
                            }
                        } catch (e) {
                            console.error('Error parsing stream chunk', e);
                        }
                    }
                }
            }
        } catch (error) {
            console.error('Chat error:', error);
            setIsLoading(false);
            setMessages(prev => [...prev, {
                id: (Date.now() + 1).toString(),
                role: 'assistant',
                content: 'Sorry, I encountered an error while processing your request. Please try again.',
                agent: { id: 'kiwi', name: 'Kiwi AI', emoji: '🐦' }
            }]);
        }
    };

    const handleSubmit = async () => {
        if (!prompt.trim() && uploadedFiles.length === 0) return;

        if (selectedMode === 'build') {
            navigate('/builder', { state: { initialPrompt: prompt } });
            return;
        }

        const userMessage: Message = {
            id: Date.now().toString(),
            role: 'user',
            content: prompt + (uploadedFiles.length > 0 ? ` [${uploadedFiles.length} files attached]` : '')
        };

        setMessages(prev => [...prev, userMessage]);
        setPrompt('');
        setIsLoading(true);
        setUploadedFiles([]);

        if (selectedMode === 'finance') {
            await handleFinanceSubmit(userMessage);
        } else if (selectedMode === 'arxiv') {
            await handleArxivSubmit(userMessage);
        } else if (selectedMode === 'normal') {
            await handleNormalSubmit(userMessage);
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
        }
    };

    const handleLike = (id: string) => {
        setLikedMessages(prev => {
            const next = new Set(prev);
            if (next.has(id)) { next.delete(id); } else { next.add(id); }
            return next;
        });
        setDislikedMessages(prev => { const next = new Set(prev); next.delete(id); return next; });
    };

    const handleDislike = (id: string) => {
        setDislikedMessages(prev => {
            const next = new Set(prev);
            if (next.has(id)) { next.delete(id); } else { next.add(id); }
            return next;
        });
        setLikedMessages(prev => { const next = new Set(prev); next.delete(id); return next; });
    };

    const handleRegenerate = async (msgId: string) => {
        // Find the user message that preceded this assistant message
        const msgIndex = messages.findIndex(m => m.id === msgId);
        if (msgIndex <= 0) return;
        const userMsg = messages[msgIndex - 1];
        if (userMsg.role !== 'user') return;

        // Remove the assistant message and re-submit
        setMessages(prev => prev.filter(m => m.id !== msgId));
        setIsLoading(true);

        if (selectedMode === 'finance') {
            await handleFinanceSubmit(userMsg);
        } else if (selectedMode === 'arxiv') {
            await handleArxivSubmit(userMsg);
        } else {
            await handleNormalSubmit(userMsg);
        }
    };

    const startNewChat = () => {
        setMessages([]);
        setPrompt('');
        setUploadedFiles([]);
        setActiveConversationId(null);
        setNormalConversationId(null);
        setStreamStatus(null);
        setSelectedMode('normal');
    };

    const startNewArxivChat = () => {
        setMessages([]);
        setPrompt('');
        setUploadedFiles([]);
        setActiveConversationId(null);
        setNormalConversationId(null);
        setStreamStatus(null);
        setSelectedMode('arxiv');
    };

    const formatTimeAgo = (dateStr: string) => {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMin = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMin / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMin < 1) return 'just now';
        if (diffMin < 60) return `${diffMin}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;
        return date.toLocaleDateString();
    };

    return (
        <div className="h-screen w-full bg-[var(--chat-bg)] flex overflow-hidden">
            {/* LEFT SIDEBAR */}
            <motion.div
                initial={{ width: 280 }}
                animate={{ width: sidebarOpen ? 280 : 0, opacity: sidebarOpen ? 1 : 0 }}
                transition={{ duration: 0.3, ease: "easeInOut" }}
                className="flex-shrink-0 bg-[var(--sidebar-bg)] flex flex-col border-r border-zinc-200 overflow-hidden"
            >
                {/* Header - Just Text with Toggle */}
                <div className="p-5 flex items-center justify-between">
                    <span className="text-zinc-900 font-medium text-xl tracking-tight font-elegant italic">Kiwi AI</span>
                    <button
                        onClick={() => setSidebarOpen(false)}
                        className="p-1.5 hover:bg-zinc-200/50 rounded-lg text-zinc-500 hover:text-zinc-700 transition-colors"
                        title="Close sidebar"
                    >
                        <PanelLeft className="w-4 h-4" />
                    </button>
                </div>

                {/* Navigation */}
                <div className="px-3 space-y-1">
                    <button
                        onClick={startNewChat}
                        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-zinc-200/50 rounded-xl transition-all group text-left"
                    >
                        <PlusIcon className="w-5 h-5 text-zinc-400 group-hover:text-zinc-600" />
                        <span className="text-zinc-600 text-[15px]">New chat</span>
                    </button>

                    <button
                        onClick={() => navigate('/builder')}
                        className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-zinc-200/50 rounded-xl transition-all group text-left"
                    >
                        <Code className="w-5 h-5 text-zinc-400 group-hover:text-zinc-600" />
                        <span className="text-zinc-600 text-[15px]">Builder</span>
                    </button>
                </div>

                {/* Scrollable section for projects + research history */}
                <div className="flex-1 overflow-y-auto px-3 py-4">
                    {/* Recent Projects */}
                    <div className="mb-6">
                        <div className="px-3 mb-3">
                            <span className="text-sm font-medium text-zinc-600">Recent Projects</span>
                        </div>
                        <div className="space-y-1">
                            {recentProjects.length === 0 ? (
                                <div className="px-3 text-sm text-zinc-500">No projects yet</div>
                            ) : (
                                recentProjects.map((project) => (
                                    <button
                                        key={project.id}
                                        onClick={() => navigate('/builder', { state: { loadProjectId: project.id } })}
                                        className="w-full px-3 py-2.5 rounded-xl text-zinc-500 text-[15px] text-left hover:bg-zinc-200/50 hover:text-zinc-700 transition-all flex justify-between items-center group"
                                        title={project.name}
                                    >
                                        <span className="truncate flex-1">{project.name}</span>
                                        <span
                                            role="button"
                                            tabIndex={0}
                                            onClick={(e) => deleteProject(project.id, e)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' || e.key === ' ') {
                                                    deleteProject(project.id, e as unknown as React.MouseEvent);
                                                }
                                            }}
                                            className="p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-zinc-200/50 hover:text-red-500 transition-all flex-shrink-0"
                                            title="Delete project"
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </span>
                                    </button>
                                ))
                            )}
                        </div>
                    </div>

                    {/* Research History */}
                    <div>
                        <div className="px-3 mb-3 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <BookOpen className="w-3.5 h-3.5 text-indigo-500/70" />
                                <span className="text-sm font-medium text-zinc-600">Research History</span>
                            </div>
                            <button
                                onClick={startNewArxivChat}
                                className="p-1 hover:bg-zinc-200/50 rounded-md text-zinc-400 hover:text-indigo-500 transition-colors"
                                title="New research chat"
                            >
                                <Plus className="w-3.5 h-3.5" />
                            </button>
                        </div>
                        <div className="space-y-0.5">
                            {arxivConversations.length === 0 ? (
                                <div className="px-3 text-sm text-zinc-600 italic">
                                    No research chats yet
                                </div>
                            ) : (
                                arxivConversations.map((conv) => (
                                    <button
                                        key={conv.id}
                                        onClick={() => loadConversation(conv.id)}
                                        className={`w-full px-3 py-2.5 rounded-xl text-[14px] text-left transition-all flex items-center gap-2 group ${activeConversationId === conv.id
                                            ? 'bg-indigo-50/50 text-indigo-600 border border-indigo-200/50'
                                            : 'text-zinc-500 hover:bg-zinc-200/50 hover:text-zinc-700'
                                            }`}
                                        title={conv.title}
                                    >
                                        <MessageSquare className="w-3.5 h-3.5 flex-shrink-0 opacity-50" />
                                        <div className="flex-1 min-w-0">
                                            <div className="truncate">{conv.title}</div>
                                            <div className="text-[11px] text-zinc-600 mt-0.5">
                                                {formatTimeAgo(conv.updated_at)}
                                            </div>
                                        </div>
                                        <button
                                            onClick={(e) => deleteArxivConversation(conv.id, e)}
                                            className="p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-zinc-200/50 hover:text-red-500 transition-all flex-shrink-0"
                                            title="Delete conversation"
                                        >
                                            <Trash2 className="w-3 h-3" />
                                        </button>
                                    </button>
                                ))
                            )}
                        </div>
                    </div>
                </div>

                {/* User Profile */}
                <div className="p-4 border-t border-zinc-200">
                    <div className="flex items-center gap-3">
                        <UserButton
                            appearance={{
                                elements: {
                                    userButtonAvatarBox: "w-8 h-8 rounded-full border border-zinc-200",
                                    userButtonPopoverCard: "bg-white border border-zinc-200 text-zinc-900 shadow-2xl",
                                    userButtonPopoverActionButtonText: "text-zinc-700",
                                    userButtonPopoverActionButtonIcon: "text-zinc-500",
                                    userButtonPopoverFooter: "hidden"
                                }
                            }}
                        />
                        <span className="text-zinc-600 text-[15px] flex-1">Account</span>
                    </div>
                </div>
            </motion.div>

            {/* MAIN CONTENT AREA */}
            <div className="flex-1 flex flex-col min-w-0 relative">
                {/* Sidebar Toggle - When collapsed */}
                {!sidebarOpen && (
                    <motion.button
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        onClick={() => setSidebarOpen(true)}
                        className="absolute top-4 left-4 z-10 p-2 bg-white/80 backdrop-blur-sm border border-zinc-200 rounded-lg text-zinc-500 hover:text-zinc-800 hover:bg-zinc-100 transition-all"
                        title="Open sidebar"
                    >
                        <PanelLeft className="w-4 h-4" />
                    </motion.button>
                )}

                {/* Background Gradients */}
                <div className="absolute inset-0 overflow-hidden pointer-events-none">
                    <div className="absolute -top-[20%] -left-[10%] w-[50%] h-[80%] bg-purple-500/10 blur-[120px] rounded-full" />
                    <div className="absolute -bottom-[20%] -right-[10%] w-[50%] h-[80%] bg-blue-500/10 blur-[120px] rounded-full" />
                    <div className="absolute top-[30%] left-[30%] w-[40%] h-[40%] bg-pink-500/5 blur-[100px] rounded-full" />
                </div>

                {/* Streaming Status Bar */}
                <AnimatePresence>
                    {streamStatus && (
                        <motion.div
                            initial={{ opacity: 0, y: -20 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -20 }}
                            className="absolute top-4 left-1/2 -translate-x-1/2 z-20 px-4 py-2 bg-indigo-500/10 backdrop-blur-md border border-indigo-500/20 rounded-full flex items-center gap-2"
                        >
                            <Search className="w-3.5 h-3.5 text-indigo-500 animate-pulse" />
                            <span className="text-sm text-indigo-600">{streamStatus}</span>
                        </motion.div>
                    )}
                </AnimatePresence>

                {/* Chat Messages Area */}
                <div className="flex-1 overflow-y-auto px-4 py-6">
                    {messages.length === 0 ? (
                        /* Centered Hero with Input */
                        <div className="h-full flex flex-col items-center justify-center">
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="w-full max-w-3xl"
                            >
                                {/* Stylish Mixed Font Greeting */}
                                <h1 className="text-5xl md:text-6xl text-zinc-900 text-center mb-10 font-elegant">
                                    <span className="font-light italic">Hi,</span>{' '}
                                    <span className="font-normal">how can</span>{' '}
                                    <span className="font-semibold">I help</span>{' '}
                                    <span className="italic font-light text-transparent bg-clip-text bg-gradient-to-r from-purple-400 via-pink-400 to-blue-400">you</span>{' '}
                                    <span className="font-normal">today?</span>
                                </h1>

                                {/* Centered Input Box */}
                                <motion.div
                                    initial={{ opacity: 0, scale: 0.95 }}
                                    animate={{ opacity: 1, scale: 1 }}
                                    transition={{ delay: 0.1 }}
                                    className="bg-white border border-zinc-200 rounded-3xl p-5 shadow-xl shadow-zinc-200/50 relative group focus-within:border-zinc-300 focus-within:shadow-purple-500/5 transition-all duration-300"
                                >
                                    {/* Uploaded Files Preview */}
                                    <AnimatePresence>
                                        {uploadedFiles.length > 0 && (
                                            <motion.div
                                                initial={{ opacity: 0, height: 0 }}
                                                animate={{ opacity: 1, height: 'auto' }}
                                                exit={{ opacity: 0, height: 0 }}
                                                className="flex gap-2 mb-3 flex-wrap"
                                            >
                                                {uploadedFiles.map((file, idx) => (
                                                    <div
                                                        key={idx}
                                                        className="flex items-center gap-2 px-3 py-1.5 bg-zinc-100 border border-zinc-200 rounded-lg text-xs text-zinc-700"
                                                    >
                                                        <FileText className="w-3 h-3" />
                                                        <span className="truncate max-w-[120px]">{file.name}</span>
                                                        <button
                                                            onClick={() => removeUploadedFile(idx)}
                                                            className="hover:text-zinc-900"
                                                        >
                                                            <X className="w-3 h-3" />
                                                        </button>
                                                    </div>
                                                ))}
                                            </motion.div>
                                        )}
                                    </AnimatePresence>

                                    <div className="flex flex-col gap-3">
                                        {/* Text Input */}
                                        <div className="flex items-start justify-between">
                                            <textarea
                                                value={prompt}
                                                onChange={(e) => setPrompt(e.target.value)}
                                                onKeyDown={handleKeyDown}
                                                placeholder="Type a message..."
                                                className="w-full bg-transparent text-zinc-900 placeholder-zinc-400 resize-none outline-none text-base min-h-[56px]"
                                                rows={2}
                                            />
                                            <div className="w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center flex-shrink-0">
                                                <span className="text-emerald-400 text-xs font-bold">K</span>
                                            </div>
                                        </div>

                                        {/* Bottom Controls */}
                                        <div className="flex items-center justify-between">
                                            {/* Left: Mode Selection */}
                                            <div className="flex items-center gap-1">
                                                <input
                                                    type="file"
                                                    ref={fileInputRef}
                                                    onChange={handleFileUpload}
                                                    multiple
                                                    className="hidden"
                                                />
                                                <button
                                                    onClick={() => fileInputRef.current?.click()}
                                                    className="p-2 hover:bg-zinc-100 rounded-lg text-zinc-500 hover:text-zinc-800 transition-colors"
                                                    title="Upload files"
                                                >
                                                    <Plus className="w-5 h-5" />
                                                </button>

                                                <button
                                                    onClick={() => handleModeSelect('arxiv')}
                                                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${selectedMode === 'arxiv'
                                                        ? 'bg-zinc-100 text-indigo-600 border border-indigo-200'
                                                        : 'hover:bg-zinc-100 text-zinc-500'
                                                        }`}
                                                    title={arxivOnline ? 'arXiv Research connected' : 'arXiv backend offline'}
                                                >
                                                    <FileText className="w-3.5 h-3.5" />
                                                    <span>Research</span>
                                                    {arxivOnline && (
                                                        <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full" />
                                                    )}
                                                </button>

                                                <button
                                                    onClick={() => handleModeSelect('finance')}
                                                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${selectedMode === 'finance'
                                                        ? 'bg-zinc-100 text-emerald-600 border border-emerald-200'
                                                        : 'hover:bg-zinc-100 text-zinc-500'
                                                        }`}
                                                    title={mcpOnline ? 'Groww MCP connected' : 'Groww MCP offline'}
                                                >
                                                    <TrendingUp className="w-3.5 h-3.5" />
                                                    <span>Finance</span>
                                                    {mcpOnline && (
                                                        <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />
                                                    )}
                                                </button>
                                            </div>

                                            {/* Right: Build Button & Submit */}
                                            <div className="flex items-center gap-2">
                                                <button
                                                    onClick={() => handleModeSelect('build')}
                                                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${selectedMode === 'build'
                                                        ? 'bg-zinc-100 text-purple-600 border border-purple-200 shadow-[0_0_15px_rgba(168,85,247,0.1)]'
                                                        : 'hover:bg-zinc-100 text-zinc-500'
                                                        }`}
                                                >
                                                    <Code className="w-3.5 h-3.5" />
                                                    <span>Build</span>
                                                </button>

                                                <button className="p-2 hover:bg-zinc-100 rounded-lg text-zinc-500 hover:text-zinc-800 transition-colors">
                                                    <Mic className="w-4 h-4" />
                                                </button>

                                                <button
                                                    onClick={handleSubmit}
                                                    disabled={!prompt.trim() && uploadedFiles.length === 0}
                                                    className={`p-2 rounded-lg transition-all duration-200 ${prompt.trim() || uploadedFiles.length > 0
                                                        ? 'bg-zinc-900 text-white hover:bg-zinc-800 shadow-md shadow-zinc-200'
                                                        : 'bg-zinc-200 text-zinc-400 cursor-not-allowed'
                                                        }`}
                                                >
                                                    <ArrowUp className="w-4 h-4" />
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                </motion.div>
                            </motion.div>
                        </div>
                    ) : (
                        /* Chat View with Input at Bottom */
                        <div className="max-w-3xl mx-auto space-y-0 min-h-full flex flex-col">
                            <div className="flex-1 pb-48 chat-container">
                                <AnimatePresence>
                                    {messages.map((msg) => (
                                        <motion.div
                                            key={msg.id}
                                            initial={{ opacity: 0, y: 8 }}
                                            animate={{ opacity: 1, y: 0 }}
                                            exit={{ opacity: 0 }}
                                            transition={{ duration: 0.3, ease: 'easeOut' }}
                                            className={`chat-message-row ${msg.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'}`}
                                        >
                                            <div className="chat-message-inner">
                                                {/* Avatar */}
                                                <div className="chat-avatar-col">
                                                    {msg.role === 'assistant' ? (
                                                        <div className="chat-avatar chat-avatar-ai">
                                                            {msg.agent ? (
                                                                <span className="text-sm">{msg.agent.emoji}</span>
                                                            ) : (
                                                                <Sparkles className="w-4 h-4 text-emerald-600" />
                                                            )}
                                                        </div>
                                                    ) : (
                                                        <div className="chat-avatar chat-avatar-user">
                                                            <span className="text-xs font-bold text-white">
                                                                {user?.firstName?.[0]?.toUpperCase() || 'U'}
                                                            </span>
                                                        </div>
                                                    )}
                                                </div>

                                                {/* Content Column */}
                                                <div className="chat-content-col group">
                                                    {/* Name */}
                                                    <div className="chat-name">
                                                        {msg.role === 'assistant'
                                                            ? (msg.agent?.name || 'Kiwi AI')
                                                            : (user?.firstName || 'You')
                                                        }
                                                    </div>

                                                    {/* Message Body */}
                                                    <div className="chat-body">
                                                        {msg.role === 'assistant' && msg.content === '' && isLoading ? (
                                                            <div className="thinking-indicator">
                                                                <div className="thinking-shimmer">
                                                                    <Sparkles className="w-4 h-4 text-zinc-400 animate-pulse" />
                                                                    <span className="text-sm text-zinc-400">Thinking...</span>
                                                                </div>
                                                            </div>
                                                        ) : (
                                                            <div className="prose-container">
                                                                <MarkdownRenderer content={msg.content} />
                                                            </div>
                                                        )}
                                                    </div>

                                                    {/* Tool Results */}
                                                    {msg.toolResults && msg.toolResults.length > 0 && (
                                                        <div className="mt-4 flex flex-col items-center w-full">
                                                            {msg.toolResults.map((tr, idx) => (
                                                                <FinanceCard
                                                                    key={`card-${msg.id}-${idx}`}
                                                                    cardData={{ title: tr.name.replace(/_/g, ' ').toUpperCase(), data: tr.data }}
                                                                    agentName={msg.agent?.name}
                                                                />
                                                            ))}
                                                        </div>
                                                    )}

                                                    {/* Sources badge for arxiv */}
                                                    {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (() => {
                                                        const seenKeys = new Set<string>();
                                                        const uniqueSources = msg.sources.filter((src: any) => {
                                                            const meta = src?.metadata || {};
                                                            const key = meta.arxiv_id || meta.url || meta.pdf_url || meta.title || '';
                                                            if (!key || seenKeys.has(key)) return false;
                                                            seenKeys.add(key);
                                                            return true;
                                                        });
                                                        if (uniqueSources.length === 0) return null;
                                                        return (
                                                            <div className="mt-4 pt-3 border-t border-[var(--border-color)]">
                                                                <div className="text-xs text-zinc-500 mb-2">📎 Sources ({uniqueSources.length})</div>
                                                                <div className="flex flex-wrap gap-1.5">
                                                                    {uniqueSources.slice(0, 8).map((src: any, idx: number) => {
                                                                        const meta = src?.metadata || {};
                                                                        const title = meta.title || meta.arxiv_id || 'Paper';
                                                                        const arxivId = meta.arxiv_id || '';
                                                                        const url = meta.url || meta.pdf_url || (arxivId ? `https://arxiv.org/abs/${arxivId}` : '#');
                                                                        const displayTitle = title.length > 30 ? title.slice(0, 30) + '…' : title;
                                                                        return (
                                                                            <a
                                                                                key={`src-${idx}-${arxivId}`}
                                                                                href={url}
                                                                                target="_blank"
                                                                                rel="noopener noreferrer"
                                                                                className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-zinc-100 hover:bg-zinc-200 border border-zinc-200 text-xs text-indigo-600 hover:text-indigo-700 transition-colors max-w-[220px]"
                                                                                title={title}
                                                                            >
                                                                                <FileText className="w-3 h-3 flex-shrink-0" />
                                                                                <span className="truncate">{displayTitle}</span>
                                                                            </a>
                                                                        );
                                                                    })}
                                                                </div>
                                                            </div>
                                                        );
                                                    })()}

                                                    {/* Action Bar — ChatGPT style */}
                                                    {msg.role === 'assistant' && msg.content && (
                                                        <div className="chat-actions opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                                                            <button
                                                                onClick={() => handleCopyMessage(msg.id, msg.content)}
                                                                className="chat-action-btn"
                                                                title="Copy"
                                                            >
                                                                {copiedMessageId === msg.id ? (
                                                                    <Check className="w-4 h-4 text-emerald-500" />
                                                                ) : (
                                                                    <Copy className="w-4 h-4" />
                                                                )}
                                                            </button>
                                                            <button
                                                                onClick={() => handleLike(msg.id)}
                                                                className={`chat-action-btn ${likedMessages.has(msg.id) ? 'chat-action-active' : ''}`}
                                                                title="Good response"
                                                            >
                                                                <ThumbsUp className="w-4 h-4" />
                                                            </button>
                                                            <button
                                                                onClick={() => handleDislike(msg.id)}
                                                                className={`chat-action-btn ${dislikedMessages.has(msg.id) ? 'chat-action-active-bad' : ''}`}
                                                                title="Bad response"
                                                            >
                                                                <ThumbsDown className="w-4 h-4" />
                                                            </button>
                                                            <button
                                                                onClick={() => handleRegenerate(msg.id)}
                                                                className="chat-action-btn"
                                                                title="Regenerate"
                                                            >
                                                                <RefreshCw className="w-4 h-4" />
                                                            </button>
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        </motion.div>
                                    ))}
                                </AnimatePresence>

                                {/* Thinking loader when waiting for first response */}
                                {isLoading && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
                                    <motion.div
                                        initial={{ opacity: 0, y: 8 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        className="chat-message-row chat-message-assistant"
                                    >
                                        <div className="chat-message-inner">
                                            <div className="chat-avatar-col">
                                                <div className="chat-avatar chat-avatar-ai">
                                                    <Sparkles className="w-4 h-4 text-emerald-600 animate-pulse" />
                                                </div>
                                            </div>
                                            <div className="chat-content-col">
                                                <div className="chat-name">Kiwi AI</div>
                                                <div className="thinking-indicator">
                                                    <div className="thinking-dots">
                                                        <span className="thinking-dot" style={{ animationDelay: '0ms' }} />
                                                        <span className="thinking-dot" style={{ animationDelay: '200ms' }} />
                                                        <span className="thinking-dot" style={{ animationDelay: '400ms' }} />
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </motion.div>
                                )}
                                <div ref={messagesEndRef} />
                            </div>
                        </div>
                    )}
                </div>

                {/* INPUT AREA - Only show when messages exist */}
                {messages.length > 0 && (
                    <div className="px-4 pb-6 absolute bottom-0 left-0 right-0 bg-gradient-to-t from-[var(--chat-bg)] via-[var(--chat-bg)] to-transparent pt-10">
                        <div className="max-w-3xl mx-auto">
                            <motion.div
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="bg-white border border-zinc-200 rounded-2xl p-4 shadow-xl shadow-zinc-200/50 relative group focus-within:border-zinc-300 transition-all duration-300"
                            >
                                {/* Uploaded Files Preview */}
                                <AnimatePresence>
                                    {uploadedFiles.length > 0 && (
                                        <motion.div
                                            initial={{ opacity: 0, height: 0 }}
                                            animate={{ opacity: 1, height: 'auto' }}
                                            exit={{ opacity: 0, height: 0 }}
                                            className="flex gap-2 mb-3 flex-wrap"
                                        >
                                            {uploadedFiles.map((file, idx) => (
                                                <div
                                                    key={idx}
                                                    className="flex items-center gap-2 px-3 py-1.5 bg-zinc-100 rounded-lg text-xs text-zinc-700 border border-zinc-200"
                                                >
                                                    <FileText className="w-3 h-3" />
                                                    <span className="truncate max-w-[120px]">{file.name}</span>
                                                    <button
                                                        onClick={() => removeUploadedFile(idx)}
                                                        className="hover:text-zinc-900"
                                                    >
                                                        <X className="w-3 h-3" />
                                                    </button>
                                                </div>
                                            ))}
                                        </motion.div>
                                    )}
                                </AnimatePresence>

                                <div className="flex flex-col gap-3">
                                    {/* Text Input */}
                                    <div className="flex items-start justify-between">
                                        <textarea
                                            value={prompt}
                                            onChange={(e) => setPrompt(e.target.value)}
                                            onKeyDown={handleKeyDown}
                                            placeholder="Type a message..."
                                            className="w-full bg-transparent text-zinc-900 placeholder-zinc-400 resize-none outline-none text-base min-h-[56px]"
                                            rows={2}
                                        />
                                    </div>

                                    {/* Bottom Controls */}
                                    <div className="flex items-center justify-between">
                                        {/* Left: Mode Selection */}
                                        <div className="flex items-center gap-1">
                                            <input
                                                type="file"
                                                ref={fileInputRef}
                                                onChange={handleFileUpload}
                                                multiple
                                                className="hidden"
                                            />
                                            <button
                                                onClick={() => fileInputRef.current?.click()}
                                                className="p-2 hover:bg-zinc-100 rounded-lg text-zinc-500 hover:text-zinc-800 transition-colors"
                                                title="Upload files"
                                            >
                                                <Plus className="w-5 h-5" />
                                            </button>

                                            <button
                                                onClick={() => handleModeSelect('arxiv')}
                                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${selectedMode === 'arxiv'
                                                    ? 'bg-zinc-100 text-indigo-600 border border-indigo-200'
                                                    : 'hover:bg-zinc-100 text-zinc-500'
                                                    }`}
                                                title={arxivOnline ? 'arXiv Research connected' : 'arXiv backend offline'}
                                            >
                                                <FileText className="w-3.5 h-3.5" />
                                                <span className="hidden sm:inline">Research</span>
                                                {arxivOnline && (
                                                    <span className="w-1.5 h-1.5 bg-indigo-400 rounded-full" />
                                                )}
                                            </button>

                                            <button
                                                onClick={() => handleModeSelect('finance')}
                                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${selectedMode === 'finance'
                                                    ? 'bg-zinc-100 text-emerald-600 border border-emerald-200'
                                                    : 'hover:bg-zinc-100 text-zinc-500'
                                                    }`}
                                                title={mcpOnline ? 'Groww MCP connected' : 'Groww MCP offline'}
                                            >
                                                <TrendingUp className="w-3.5 h-3.5" />
                                                <span className="hidden sm:inline">Finance</span>
                                                {mcpOnline && (
                                                    <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full" />
                                                )}
                                            </button>
                                        </div>

                                        {/* Right: Build Button & Submit */}
                                        <div className="flex items-center gap-2">
                                            <button
                                                onClick={() => handleModeSelect('build')}
                                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${selectedMode === 'build'
                                                    ? 'bg-zinc-100 text-purple-600 border border-purple-200 shadow-[0_0_15px_rgba(168,85,247,0.1)]'
                                                    : 'hover:bg-zinc-100 text-zinc-500'
                                                    }`}
                                            >
                                                <Code className="w-3.5 h-3.5" />
                                                <span>Build</span>
                                            </button>

                                            <button
                                                onClick={handleSubmit}
                                                disabled={!prompt.trim() && uploadedFiles.length === 0}
                                                className={`p-2 rounded-lg transition-all duration-200 ${prompt.trim() || uploadedFiles.length > 0
                                                    ? 'bg-zinc-900 text-white hover:bg-zinc-800 shadow-md shadow-zinc-200'
                                                    : 'bg-zinc-200 text-zinc-400 cursor-not-allowed border border-zinc-200/50'
                                                    }`}
                                            >
                                                {isLoading ? (
                                                    <Loader2 className="w-4 h-4 text-zinc-400 animate-spin" />
                                                ) : (
                                                    <ArrowUp className="w-4 h-4" />
                                                )}
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            </motion.div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
