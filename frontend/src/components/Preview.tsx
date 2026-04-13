import React from 'react';
import { RefreshCw, ExternalLink, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';

interface PreviewProps {
    url: string | null;
    isBuilding?: boolean;
    isStarting?: boolean;
    onRefresh?: () => void;
}

export const Preview: React.FC<PreviewProps> = ({ url, isBuilding, isStarting, onRefresh }) => {
    const [key, setKey] = React.useState(0);

    const refresh = () => {
        setKey(k => k + 1);
        if (onRefresh) onRefresh();
    };

    if (isBuilding) {
        return (
            <div className="h-full flex flex-col items-center justify-center bg-zinc-950 text-zinc-500 border border-zinc-800 rounded-lg">
                <motion.div
                    className="p-4 rounded-full bg-zinc-900 mb-4"
                    animate={{ rotate: 360 }}
                    transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                >
                    <Loader2 size={24} className="text-indigo-400" />
                </motion.div>
                <p className="text-zinc-400 font-medium">Building your application...</p>
                <p className="text-zinc-600 text-sm mt-1">Preview will appear when ready</p>
            </div>
        );
    }

    if (isStarting) {
        return (
            <div className="h-full flex flex-col items-center justify-center bg-zinc-950 text-zinc-500 border border-zinc-800 rounded-lg">
                <motion.div
                    className="p-4 rounded-full bg-zinc-900 mb-4"
                    animate={{ rotate: 360 }}
                    transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                >
                    <Loader2 size={24} className="text-green-400" />
                </motion.div>
                <p className="text-zinc-400 font-medium">Starting dev server...</p>
                <p className="text-zinc-600 text-sm mt-1">This may take a few seconds</p>
            </div>
        );
    }

    if (!url) {
        return (
            <div className="h-full flex flex-col items-center justify-center bg-zinc-950 text-zinc-500 border border-zinc-800 rounded-lg">
                <div className="p-4 rounded-full bg-zinc-900 mb-4">
                    <ExternalLink size={24} />
                </div>
                <p className="text-zinc-400">Application preview will appear here</p>
                <p className="text-zinc-600 text-sm mt-1">Enter a prompt to start building</p>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-zinc-950 border border-zinc-800 rounded-lg overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800">
                <div className="flex items-center gap-2">
                    <div className="flex gap-1.5">
                        <div className="w-3 h-3 rounded-full bg-red-500/20 border border-red-500/50" />
                        <div className="w-3 h-3 rounded-full bg-yellow-500/20 border border-yellow-500/50" />
                        <div className="w-3 h-3 rounded-full bg-green-500/20 border border-green-500/50" />
                    </div>
                    <span className="text-xs text-zinc-500 ml-2 bg-black/20 px-2 py-0.5 rounded font-mono truncate max-w-[300px]">
                        {url}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={refresh}
                        className="p-1.5 hover:bg-zinc-800 text-zinc-400 hover:text-white rounded transition-colors"
                        title="Refresh"
                    >
                        <RefreshCw size={14} />
                    </button>
                    <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 hover:bg-zinc-800 text-zinc-400 hover:text-white rounded transition-colors"
                        title="Open in new tab"
                    >
                        <ExternalLink size={14} />
                    </a>
                </div>
            </div>
            <div className="flex-1 relative bg-white">
                <iframe
                    key={key}
                    src={url}
                    className="w-full h-full border-0"
                    title="App Preview"
                />
            </div>
        </div>
    );
};
