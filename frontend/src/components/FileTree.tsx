import React from 'react';
import { File, Folder, FolderOpen, ChevronRight, ChevronDown, FileCode, FileJson, FileText } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

export interface FileNode {
    name: string;
    type: 'file' | 'directory';
    path: string;
    children?: FileNode[];
}

interface FileTreeProps {
    files: FileNode[];
    onSelectFile: (path: string) => void;
    selectedFile: string | null;
    isLoading?: boolean;
}

const getFileIcon = (name: string) => {
    if (name.endsWith('.json')) return <FileJson size={16} className="text-yellow-400" />;
    if (name.endsWith('.ts') || name.endsWith('.tsx')) return <FileCode size={16} className="text-blue-400" />;
    if (name.endsWith('.js') || name.endsWith('.jsx')) return <FileCode size={16} className="text-yellow-300" />;
    if (name.endsWith('.css')) return <FileText size={16} className="text-pink-400" />;
    if (name.endsWith('.html')) return <FileText size={16} className="text-orange-400" />;
    return <File size={16} className="text-zinc-400" />;
};

const FileTreeNode: React.FC<{
    node: FileNode;
    onSelect: (path: string) => void;
    selectedFile: string | null;
    level: number
}> = ({ node, onSelect, selectedFile, level }) => {
    const [isOpen, setIsOpen] = React.useState(true);

    const toggleOpen = (e: React.MouseEvent) => {
        e.stopPropagation();
        setIsOpen(!isOpen);
    };

    const handleSelect = () => {
        if (node.type === 'file') {
            onSelect(node.path);
        } else {
            setIsOpen(!isOpen);
        }
    };

    const isSelected = selectedFile === node.path;

    return (
        <div className="select-none">
            <motion.div
                whileHover={{ x: 2 }}
                className={`flex items-center py-1.5 px-2 cursor-pointer transition-colors rounded-md mx-1 ${isSelected
                        ? 'bg-indigo-600/20 text-indigo-300'
                        : 'hover:bg-zinc-800/50 text-zinc-400 hover:text-zinc-200'
                    }`}
                style={{ paddingLeft: `${level * 12 + 8}px` }}
                onClick={handleSelect}
            >
                <span className="mr-1.5 opacity-70">
                    {node.type === 'directory' ? (
                        <div onClick={toggleOpen} className="p-0.5 hover:bg-white/10 rounded">
                            {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </div>
                    ) : (
                        <div className="w-4" />
                    )}
                </span>

                <span className="mr-2">
                    {node.type === 'directory' ? (
                        isOpen ? <FolderOpen size={16} className="text-indigo-400" /> : <Folder size={16} className="text-indigo-400" />
                    ) : (
                        getFileIcon(node.name)
                    )}
                </span>

                <span className="text-sm font-medium truncate">{node.name}</span>
            </motion.div>

            <AnimatePresence>
                {node.type === 'directory' && isOpen && node.children && (
                    <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                    >
                        {node.children.map((child) => (
                            <FileTreeNode
                                key={child.path}
                                node={child}
                                onSelect={onSelect}
                                selectedFile={selectedFile}
                                level={level + 1}
                            />
                        ))}
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
};

const LoadingSkeleton = () => (
    <div className="space-y-2 p-2">
        {[...Array(5)].map((_, i) => (
            <motion.div
                key={i}
                initial={{ opacity: 0.3 }}
                animate={{ opacity: [0.3, 0.6, 0.3] }}
                transition={{ duration: 1.5, repeat: Infinity, delay: i * 0.1 }}
                className="flex items-center gap-2"
            >
                <div className="w-4 h-4 bg-zinc-700 rounded" />
                <div className="h-4 bg-zinc-700 rounded" style={{ width: `${60 + Math.random() * 40}%` }} />
            </motion.div>
        ))}
    </div>
);

export const FileTree: React.FC<FileTreeProps> = ({ files, onSelectFile, selectedFile, isLoading }) => {
    if (isLoading) {
        return (
            <div className="h-full overflow-auto py-2 bg-zinc-900/50 rounded-lg border border-zinc-800/50">
                <LoadingSkeleton />
            </div>
        );
    }

    if (files.length === 0) {
        return (
            <div className="h-full flex items-center justify-center text-zinc-600 text-sm">
                No files yet
            </div>
        );
    }

    return (
        <div className="h-full overflow-auto py-2 bg-zinc-900/50 rounded-lg border border-zinc-800/50">
            {files.map((file) => (
                <FileTreeNode
                    key={file.path}
                    node={file}
                    onSelect={onSelectFile}
                    selectedFile={selectedFile}
                    level={0}
                />
            ))}
        </div>
    );
};
